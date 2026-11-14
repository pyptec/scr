"""Captura automática aislada: RX existente -> cola -> deque/RAW/manifiesto.

Sin receptor CAN, servicios, red o migración automática. Activación explícita.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shutil
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .engine_detector import DetectorClock, EngineState
from .engine_store import RecordingBatch, utc_text
from .evidence_store import EvidenceStore
from .models import CanFrame
from .parser import parse_capture_record

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_NAME = re.compile(r"^j1939_auto_([a-f0-9]{32})_([a-f0-9]{32})\.txt(?:\.partial)?$")


@dataclass(frozen=True, slots=True)
class EvidenceConfig:
    directory: Path
    selections: tuple[tuple[int, int], ...]
    gateway_id: str
    equipment_id: str
    engine_source_address: int
    enabled: bool = False
    pre_seconds: float = 60
    post_seconds: float = 60
    max_confirmation_seconds: float = 30
    max_frame_gap_seconds: float = 5
    max_buffer_frames: int = 10000
    queue_size: int = 2048
    max_file_bytes: int = 50 * 1024 * 1024
    segment_seconds: float = 3600
    min_free_bytes: int = 100 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    max_files: int = 200
    retention_enabled: bool = False
    retention_seconds: float = 30 * 86400

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() and len(x) <= 256 for x in (self.gateway_id, self.equipment_id)):
            raise ValueError("explicit bounded gateway/equipment identity required")
        if type(self.engine_source_address) is not int or not 0 <= self.engine_source_address <= 253 or (0xF004, self.engine_source_address) not in self.selections:
            raise ValueError("explicit engine RPM source must be selected")
        directory = Path(self.directory).resolve()
        if directory.is_relative_to(REPO_ROOT) or directory == Path(directory.anchor):
            raise ValueError("evidence directory must be scoped and outside repository")
        object.__setattr__(self, "directory", directory)
        if type(self.enabled) is not bool or type(self.retention_enabled) is not bool:
            raise ValueError("flags must be booleans")
        for name in ("pre_seconds", "post_seconds", "max_confirmation_seconds", "max_frame_gap_seconds", "segment_seconds", "retention_seconds"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise ValueError("time limits must be finite and positive")
        for name in ("max_buffer_frames", "queue_size", "max_file_bytes", "min_free_bytes", "max_total_bytes", "max_files"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("storage/count limits must be nonnegative integers")
        if self.queue_size < 4 or self.max_buffer_frames < 1 or self.max_files < 1 or self.max_file_bytes < 1024 or self.max_total_bytes < self.max_file_bytes + 8192:
            raise ValueError("insufficient bounded storage limits")
        if not self.selections or len(self.selections) > 128:
            raise ValueError("explicit PGN/SA selections required (1..128)")
        for pgn, sa in self.selections:
            if type(pgn) is not int or not 0 <= pgn <= 0x3FFFF or type(sa) is not int or not 0 <= sa <= 253:
                raise ValueError("invalid PGN/SA selection")


class DirectoryLease:
    """Lock de SO, liberado tras muerte del proceso; no se infiere actividad por PID."""
    def __init__(self, directory):
        self.file = (directory / ".j1939_evidence.lock").open("a+b")
        try:
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0"); self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.file.close()
            raise

    def close(self):
        if not self.file.closed:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


class AutoEvidence:
    def __init__(self, config: EvidenceConfig, clock: DetectorClock, store: EvidenceStore):
        self.config, self.clock, self.store = config, clock, store
        self._selections = frozenset(config.selections)
        self._queue = queue.Queue(config.queue_size)
        self._producer = threading.Lock()
        self._consumer = threading.RLock()
        self._buffer = deque()
        self._seen_order, self._seen = deque(), set()
        self._control_sequences = {}
        self._control_writers = deque()
        self._capture = self._meta = self._file = self._lease = None
        self._candidate_at = None
        self._deadline = None
        self._segment_at = 0
        self._total_bytes = self._raw_count = 0
        self._sync_iter = None
        self._last_sync = 0
        self._stop = threading.Event()
        self._thread = None
        self.dropped_frames = self.dropped_controls = self.duplicates = self.buffer_evictions = 0
        self.storage_errors = self.metadata_errors = 0
        self.last_error = None

    def offer_frame(self, frame: CanFrame) -> bool:
        """Solo RAM/cola. Llamar antes de ofrecer la señal decodificada al registrador."""
        if not self.config.enabled or not frame.is_extended or frame.j1939 is None:
            return False
        if (frame.j1939.pgn, frame.j1939.source_address) not in self._selections:
            return False
        if frame.dlc != len(frame.data) or not 0 <= frame.dlc <= 8:
            return False
        try:
            stamp = utc_text(frame.timestamp_utc)
        except ValueError:
            return False
        key = (stamp, frame.can_id, bytes(frame.data))
        with self._producer:
            if key in self._seen:
                self.duplicates += 1
                return False
            # Dos posiciones reservadas para avisos; incluso controles tienen límite.
            if self._queue.qsize() >= self.config.queue_size - 2:
                self.dropped_frames += 1
                return False
            self._queue.put_nowait(("frame", frame, self.clock.monotonic()))
            self._seen.add(key); self._seen_order.append(key)
            if len(self._seen_order) > self.config.max_buffer_frames:
                self._seen.discard(self._seen_order.popleft())
            return True

    def observe_batch(self, batch: RecordingBatch) -> bool:
        if not self.config.enabled:
            return False
        if (batch.gateway_id != self.config.gateway_id or batch.equipment_id != self.config.equipment_id
                or batch.source_address != self.config.engine_source_address):
            return False
        with self._producer:
            if batch.sequence <= self._control_sequences.get(batch.writer_id, 0):
                return True
            try:
                self._queue.put_nowait(("batch", batch, self.clock.monotonic()))
                if batch.writer_id not in self._control_sequences:
                    self._control_writers.append(batch.writer_id)
                    if len(self._control_writers) > 64:
                        self._control_sequences.pop(self._control_writers.popleft(), None)
                self._control_sequences[batch.writer_id] = batch.sequence
                return True
            except queue.Full:
                self.dropped_controls += 1
                return False

    def _totals(self):
        size = count = 0
        for p in self.config.directory.glob("j1939_auto_*"):
            if p.is_file() and not p.is_symlink():
                size += p.stat().st_size
                count += int(bool(RAW_NAME.fullmatch(p.name)))
        self._total_bytes, self._raw_count = size, count

    def _safe_raw(self, path):
        p = Path(path)
        if p.is_symlink() or p.parent.resolve() != self.config.directory or not RAW_NAME.fullmatch(p.name):
            raise ValueError("unsafe evidence path")
        return p

    def _manifest_path(self, segment_id):
        if not re.fullmatch(r"[a-f0-9]{32}", segment_id):
            raise ValueError("invalid segment ID")
        return self.config.directory / f"j1939_auto_{segment_id}.json"

    def _manifest(self, meta):
        p = self._manifest_path(meta["segment_id"])
        tmp = p.with_suffix(".json.tmp")
        data = json.dumps(meta, sort_keys=True).encode("utf-8")
        if len(data) > 65536:
            raise ValueError("manifest exceeds memory budget")
        previous = p.stat().st_size if p.exists() else 0
        self._space(len(data))  # Incluye coexistencia temporal del manifiesto anterior y el nuevo.
        with tmp.open("wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, p)
        self._total_bytes += len(data) - previous

    def _persist(self, meta):
        self._manifest(meta)
        try:
            session = self.store.save_segment(meta)
            if session and meta.get("session_id") != session:
                meta["session_id"] = session
                self._manifest(meta)
        except Exception as exc:
            self.metadata_errors += 1
            self.last_error = "metadata:" + type(exc).__name__

    @staticmethod
    def _hash(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def _initialize(self):
        if self._lease is not None:
            return
        self.config.directory.mkdir(parents=True, exist_ok=True)
        lease = DirectoryLease(self.config.directory)
        self._lease = lease
        try:
            self._totals()
            self._recover()
        except BaseException:
            lease.close(); self._lease = None
            raise

    def _space(self, amount, *, new_file=False):
        reserve = 4096
        if shutil.disk_usage(self.config.directory).free < self.config.min_free_bytes + amount + reserve:
            raise OSError("evidence free-space limit")
        if self._total_bytes + amount + reserve > self.config.max_total_bytes or (new_file and self._raw_count >= self.config.max_files):
            raise OSError("evidence quota reached; retention is not automatic")

    def _open_segment(self, at):
        self._space(1024, new_file=True)
        segment = uuid.uuid4().hex
        path = self.config.directory / f'j1939_auto_{self._capture["capture_id"]}_{segment}.txt.partial'
        self._meta = dict(segment_id=segment, capture_id=self._capture["capture_id"],
                          anchor_batch_id=self._capture["anchor_batch_id"], session_id=None,
                          file_path=str(path), started_at_utc=None, ended_at_utc=None,
                          frame_count=0, pgns=[], sources=[], size_bytes=0, integrity="OPEN",
                          close_reason=None, sha256=None, warnings=sorted(self._capture["warnings"]),
                          backed_up_sha256=None, closed_at_utc=None)
        self._file = path.open("xb", buffering=0)
        self._raw_count += 1
        self._segment_at = at
        self._persist(self._meta)
        header = ("# SAMEE100 J1939 capture\n# capture_version: samee100-j1939-auto-v1\n"
                  + "# auto_metadata: " + json.dumps(self._meta, sort_keys=True) + "\n"
                  + "timestamp_utc,can_id,extended,dlc,data,pgn,source_address\n").encode()
        if len(header) >= self.config.max_file_bytes:
            raise OSError("header exceeds configured segment size")
        self._write(header)

    def _write(self, data):
        self._space(len(data))
        count = self._file.write(data)
        if count != len(data):
            raise OSError("short evidence write")
        self._meta["size_bytes"] += count
        self._total_bytes += count

    def _finish_segment(self, reason, *, incomplete=False, rename=True):
        if self._meta is None:
            return
        meta = self._meta
        try:
            if self._file:
                self._file.flush(); os.fsync(self._file.fileno())
        finally:
            if self._file:
                self._file.close()
            self._file = None
        path = self._safe_raw(meta["file_path"])
        if rename:
            final = path.with_suffix("")
            if final.exists():
                raise FileExistsError("final evidence already exists")
            path.rename(final); path = final
        if incomplete:
            self._scan(meta, path, reason=reason)
        meta["file_path"] = str(path)
        meta["size_bytes"] = path.stat().st_size
        meta["sha256"] = self._hash(path)
        warnings = set(meta["warnings"]) | self._capture["warnings"]
        if self.dropped_frames or self.dropped_controls:
            warnings.add("queue_drop")
        meta["warnings"] = sorted(warnings)
        meta["integrity"] = "INCOMPLETE" if incomplete or warnings or not meta["frame_count"] else "COMPLETE"
        meta["close_reason"] = reason
        meta["closed_at_utc"] = utc_text(self.clock.utcnow())
        self._persist(meta)
        self._meta = None
        self._totals()

    def _fault(self, exc):
        self.storage_errors += 1
        self.last_error = "storage:" + type(exc).__name__
        if self._capture:
            self._capture["warnings"].add("storage_error")
        if self._meta:
            try:
                self._finish_segment("write_error", incomplete=True, rename=False)
            except Exception:
                if self._file:
                    self._file.close()
                self._file = self._meta = None
        self._totals()

    def _record(self, data, at):
        if not self._capture:
            return
        if self._file and (self._meta["size_bytes"] + len(data) > self.config.max_file_bytes
                           or (at - self._segment_at >= self.config.segment_seconds and self._meta["frame_count"])):
            self._finish_segment("rotation")
        if self._file is None:
            self._open_segment(at)
        if self._meta["size_bytes"] + len(data) > self.config.max_file_bytes:
            raise OSError("record exceeds configured segment size")
        self._write(data)

    def _frame(self, frame, at):
        # Búfer por tiempo monotónico de recepción, con límite estricto de cantidad.
        self._buffer.append((at, frame))
        window = self.config.pre_seconds + self.config.max_confirmation_seconds
        while self._buffer and at - self._buffer[0][0] > window:
            self._buffer.popleft()
        while len(self._buffer) > self.config.max_buffer_frames:
            self._buffer.popleft(); self.buffer_evictions += 1
        if self._capture:
            self._write_frame(frame, at)

    def _write_frame(self, frame, at):
        previous = self._capture.get("last_frame_at")
        if previous is not None and at - previous > self.config.max_frame_gap_seconds:
            self._capture["warnings"].add("frame_gap")
        self._capture["last_frame_at"] = at
        item = frame.public_dict()
        stamp = utc_text(frame.timestamp_utc)
        row = f'{stamp},{item["canId"]},true,{frame.dlc},{item["data"]},{item["pgn"]},{item["sourceAddress"]}\n'.encode()
        self._record(row, at)
        m = self._meta
        m["frame_count"] += 1
        m["started_at_utc"] = min(m["started_at_utc"] or stamp, stamp)
        m["ended_at_utc"] = max(m["ended_at_utc"] or stamp, stamp)
        if item["pgn"] not in m["pgns"]: m["pgns"].append(item["pgn"])
        if item["sourceAddress"] not in m["sources"]: m["sources"].append(item["sourceAddress"])

    def _marker(self, batch, at):
        for index, event in enumerate(batch.events):
            value = {"id": f"{batch.batch_id}:{index}", "type": event.event_type.value,
                     "utc": utc_text(event.timestamp_utc), "rpm": event.rpm,
                     "source": event.source_address}
            self._record(("# EVENT " + json.dumps(value, sort_keys=True) + "\n").encode(), at)

    def _start_capture(self, batch, at, *, confirmed):
        self._capture = dict(capture_id=uuid.uuid5(uuid.NAMESPACE_URL, batch.batch_id).hex,
                             anchor_batch_id=batch.batch_id, warnings=set())
        if not confirmed: self._capture["warnings"].add("unconfirmed_start")
        anchor = self._candidate_at or batch.observed_at_utc or batch.timestamp_utc
        desired = anchor - timedelta(seconds=self.config.pre_seconds)
        if not self._buffer or self._buffer[0][1].timestamp_utc > desired:
            self._capture["warnings"].add("prebuffer_short")
        self._deadline = None
        for buffered_at, frame in self._buffer:
            if frame.timestamp_utc >= desired:
                self._write_frame(frame, buffered_at)
        self._marker(batch, at)

    def _end_capture(self, reason, *, incomplete=False):
        if (reason == "post_stop_elapsed" and self._capture and self._deadline is not None
                and self._deadline - self._capture.get("last_frame_at", float("-inf")) > self.config.max_frame_gap_seconds):
            self._capture["warnings"].add("post_window_no_rx")
        self._finish_segment(reason, incomplete=incomplete)
        self._capture = None
        self._deadline = None
        self._candidate_at = None

    def _batch(self, batch, at):
        kinds = {e.event_type.value for e in batch.events}
        # Estado de captura antes de I/O: un disco lleno no debe perder el plazo de STOP.
        if self._capture and ("COMMUNICATION_LOST" in kinds or batch.discontinuity):
            self._capture["warnings"].add("observation_gap")
        if self._capture and self._deadline is None and ("STOP" in kinds or batch.state == EngineState.STOPPED):
            self._deadline = at + self.config.post_seconds
            if "STOP" not in kinds: self._capture["warnings"].add("unobserved_stop_transition")
        if batch.state == EngineState.STARTING and self._candidate_at is None:
            self._candidate_at = batch.observed_at_utc or batch.timestamp_utc
        if "START" in kinds:
            candidate = self._candidate_at
            if self._capture:
                self._end_capture("new_start_during_post_window", incomplete=True)
            self._candidate_at = candidate
            self._start_capture(batch, at, confirmed=True)
        elif batch.state == EngineState.RUNNING and (not self._capture or self._deadline is not None):
            candidate = self._candidate_at
            if self._capture: self._end_capture("running_during_post_window", incomplete=True)
            self._candidate_at = candidate
            self._start_capture(batch, at, confirmed=False)
        elif self._capture:
            self._marker(batch, at)
        if self._capture and ("COMMUNICATION_LOST" in kinds or batch.discontinuity):
            self._capture["warnings"].add("observation_gap")
        if self._capture and self._deadline is None and ("STOP" in kinds or batch.state == EngineState.STOPPED):
            self._deadline = at + self.config.post_seconds
            if "STOP" not in kinds: self._capture["warnings"].add("unobserved_stop_transition")
        if batch.state in (EngineState.STOPPED, EngineState.UNKNOWN, EngineState.RUNNING, EngineState.COMM_LOST, EngineState.STOPPING):
            self._candidate_at = None

    def tick(self):
        """Solo escritor; cierra cola posterior incluso sin nuevas tramas."""
        if self._deadline is not None and self.clock.monotonic() >= self._deadline:
            self._end_capture("post_stop_elapsed")

    def _scan(self, meta, path, *, reason="recovered_incomplete"):
        frames, pgns, sources, bad = 0, set(), set(), False
        first = last = None
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    frame = parse_capture_record(line)
                    if frame:
                        stamp = utc_text(frame.timestamp_utc)
                        first = min(first or stamp, stamp); last = max(last or stamp, stamp)
                        frames += 1
                        pgn, source = f"{frame.j1939.pgn:04X}", f"{frame.j1939.source_address:02X}"
                        if len(pgns) < 128 or pgn in pgns: pgns.add(pgn)
                        else: bad = True
                        if len(sources) < 128 or source in sources: sources.add(source)
                        else: bad = True
                except (ValueError, TypeError):
                    bad = True
        meta.update(frame_count=frames, started_at_utc=first, ended_at_utc=last,
                    pgns=sorted(pgns), sources=sorted(sources), size_bytes=path.stat().st_size,
                    file_path=str(path), sha256=self._hash(path), integrity="INCOMPLETE",
                    close_reason=reason, closed_at_utc=utc_text(self.clock.utcnow()))
        meta["warnings"] = sorted(set(meta.get("warnings", [])) | ({"process_interruption"} if reason == "recovered_incomplete" else {reason}) | ({"malformed_record"} if bad else set()))

    @staticmethod
    def _load_manifest(path):
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("unsafe or oversized manifest")
        return json.loads(path.read_text(encoding="utf-8"))

    def _recover(self):
        known, blocked = set(), set()
        for number, p in enumerate(self.config.directory.glob("j1939_auto_*.json"), 1):
            if number > self.config.max_files * 4:
                raise OSError("recovery manifest limit reached; archive metadata explicitly")
            if p.is_symlink(): continue
            try:
                meta = self._load_manifest(p)
                raw = self._safe_raw(meta["file_path"])
                known.add(raw.name)
                if meta["integrity"] == "OPEN":
                    if not raw.exists() and raw.suffix == ".partial" and raw.with_suffix("").exists():
                        raw = raw.with_suffix("")
                    if raw.exists(): self._scan(meta, raw)
                    else: meta.update(integrity="MISSING", close_reason="raw_missing", sha256=None)
                    self._persist(meta)
                elif not raw.exists() and meta["integrity"] not in ("DELETED", "MISSING"):
                    deleted = meta.get("deletion_authorized") and meta.get("backed_up_sha256") == meta.get("sha256")
                    meta.update(integrity="DELETED" if deleted else "MISSING", close_reason="retention_recovered" if deleted else "raw_missing")
                    self._persist(meta)
            except Exception as exc:
                self.metadata_errors += 1; self.last_error = "recovery:" + type(exc).__name__
                match = re.fullmatch(r"j1939_auto_([a-f0-9]{32})\.json", p.name)
                if match: blocked.add(match[1])
        for number, raw in enumerate(self.config.directory.glob("j1939_auto_*.txt.partial"), 1):
            if number > self.config.max_files:
                raise OSError("recovery RAW file limit reached")
            if raw.name in known: continue
            self._safe_raw(raw)
            match = RAW_NAME.fullmatch(raw.name)
            if match[2] in blocked: continue  # Preservar manifiesto corrupto y RAW para inspección.
            meta = dict(segment_id=match[2], capture_id=match[1], anchor_batch_id="orphan:" + match[2],
                        session_id=None, warnings=["orphan"], backed_up_sha256=None)
            self._scan(meta, raw)
            self._persist(meta)
        self._totals()

    def synchronize(self, *, limit=None):
        """Solo escritor: reintentar metadatos desde manifiestos, sin reescribir RAW."""
        count = 0
        if self._sync_iter is None:
            self._sync_iter = iter(self.config.directory.glob("j1939_auto_*.json"))
        while limit is None or count < limit:
            try: p = next(self._sync_iter)
            except StopIteration:
                self._sync_iter = None; break
            count += 1
            if p.is_symlink(): continue
            try:
                meta = self._load_manifest(p)
                self._safe_raw(meta["file_path"])
                # Nunca sustituir counters activos por el manifiesto inicial.
                if self._meta and meta["segment_id"] == self._meta["segment_id"]:
                    self._file.flush(); os.fsync(self._file.fileno())
                    meta = dict(self._meta)
                self._persist(meta)
            except Exception as exc:
                self.metadata_errors += 1; self.last_error = "metadata:" + type(exc).__name__

    def drain_once(self):
        if not self.config.enabled: return False
        with self._consumer:
            try: self._initialize()
            except Exception as exc:
                self.storage_errors += 1; self.last_error = "initialize:" + type(exc).__name__
                return False
            try: kind, value, at = self._queue.get_nowait()
            except queue.Empty:
                try:
                    self.tick()
                    if self.clock.monotonic() - self._last_sync >= 5:
                        self.synchronize(limit=8); self._last_sync = self.clock.monotonic()
                except Exception as exc: self._fault(exc)
                return False
            try:
                if self._deadline is not None and at > self._deadline:
                    self._end_capture("post_stop_elapsed")
                if kind == "frame": self._frame(value, at)
                else: self._batch(value, at)
            except Exception as exc:
                self._fault(exc)
            finally:
                self._queue.task_done()
            return True

    def acknowledge_backup(self, segment_id, sha256):
        """Atestación explícita del operador; no acredita por sí sola una copia remota."""
        with self._consumer:
            p = self._manifest_path(segment_id)
            meta = self._load_manifest(p)
            raw = self._safe_raw(meta["file_path"])
            if meta["integrity"] != "COMPLETE" or sha256 != meta["sha256"] or self._hash(raw) != sha256:
                raise ValueError("only complete verified evidence can be marked backed up")
            meta["backed_up_sha256"] = sha256
            self._persist(meta)

    def prune(self, *, authorized=False):
        """Nunca invocado automáticamente. Requiere opt-in, autorización y respaldo."""
        if not authorized or not self.config.retention_enabled:
            raise PermissionError("explicit retention authorization required")
        removed = 0
        with self._consumer:
            for p in self.config.directory.glob("j1939_auto_*.json"):
                if p.is_symlink(): continue
                meta = self._load_manifest(p)
                if meta["integrity"] != "COMPLETE" or meta.get("backed_up_sha256") != meta["sha256"]:
                    continue
                from datetime import datetime
                age = (self.clock.utcnow() - datetime.fromisoformat(meta["closed_at_utc"].replace("Z", "+00:00"))).total_seconds()
                if age < self.config.retention_seconds or not self.store.session_closed(meta["segment_id"]):
                    continue
                raw = self._safe_raw(meta["file_path"])
                if raw.suffix != ".txt" or self._hash(raw) != meta["sha256"]: continue
                meta["deletion_authorized"] = True
                self._persist(meta)
                raw.unlink()  # Ruta absoluta comprobada; solo fichero propio verificado/respaldo/sesión cerrada.
                meta.update(integrity="DELETED", close_reason="authorized_backed_up_retention")
                self._persist(meta); removed += 1
            self._totals()
        return removed

    def status(self):
        return dict(enabled=self.config.enabled, queued=self._queue.qsize(), buffered=len(self._buffer),
                    droppedFrames=self.dropped_frames, droppedControls=self.dropped_controls,
                    duplicates=self.duplicates, bufferEvictions=self.buffer_evictions,
                    storageErrors=self.storage_errors, metadataErrors=self.metadata_errors,
                    lastError=self.last_error, activeCapture=self._capture and self._capture["capture_id"])

    def start(self):
        if not self.config.enabled: return
        if self._thread is not None: raise RuntimeError("evidence worker already started")
        self._thread = threading.Thread(target=self._run, name="j1939-auto-evidence", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            if not self.drain_once(): self._stop.wait(0.05)
        while self.drain_once(): pass
        self._shutdown()

    def _shutdown(self):
        try:
            if self._capture: self._end_capture("process_stop", incomplete=True)
        except Exception as exc: self._fault(exc)
        finally:
            if self._sync_iter is not None:
                self._sync_iter.close(); self._sync_iter = None
            if self._lease: self._lease.close(); self._lease = None

    def close(self, timeout=3):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            return not self._thread.is_alive() and self._queue.empty()
        while self.drain_once(): pass
        self._shutdown()
        return self._queue.empty()
