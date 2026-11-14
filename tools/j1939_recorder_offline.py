"""Administración/replay OFFLINE. Sin CAN, .env, SSH o servicios."""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from j1939.config import load_yaml
from j1939.decoder import SignalDecoder
from j1939.engine_detector import DetectorConfig
from j1939.engine_recorder import EngineRecorder, RecorderConfig
from j1939.engine_store import EngineStore
from j1939.parser import FrameParseError, parse_capture_record, parse_slcan_line

CANDUMP = re.compile(r"^\((\d+(?:\.\d+)?)\)\s+\S+\s+([0-9a-fA-F]{8})#([0-9a-fA-F]{0,16})$")


def parse_replay_line(line: str, format_name: str):
    """Reutiliza parser existente; candump admite solo formato absoluto clásico -L."""
    if format_name == "csv":
        return parse_capture_record(line)
    if format_name != "candump":
        raise ValueError("unsupported replay format")
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    match = CANDUMP.fullmatch(line.strip())
    if not match:
        raise FrameParseError("expected classic extended candump -L record")
    seconds, can_id, data = match.groups()
    stamp = datetime.fromtimestamp(float(seconds), timezone.utc)
    return parse_slcan_line(f"T{can_id}{len(data) // 2:X}{data}", stamp)


class ReplayClock:
    def __init__(self, stamp: datetime):
        self.initial = self.current = stamp

    def monotonic(self):
        return (self.current - self.initial).total_seconds()

    def utcnow(self):
        return self.current


def run_replay(path: Path, format_name: str, config: RecorderConfig, store: EngineStore) -> dict:
    if not config.enabled:
        raise ValueError("offline recording must be explicitly enabled")
    decoder = SignalDecoder(load_yaml(BASE_DIR / "config/j1939_signals.yml")["signals"])
    clock = recorder = None
    summary = {"frames": 0, "rpmValidDecoded": 0, "rpmAccepted": 0, "outOfOrder": 0, "maxRpm": None}

    def drain():
        while recorder.drain_once():
            pass
        if recorder.last_error:
            raise RuntimeError("offline persistence failed: " + recorder.last_error)

    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            frame = parse_replay_line(line, format_name)
            if frame is None:
                continue
            summary["frames"] += 1
            if clock is None:
                clock = ReplayClock(frame.timestamp_utc)
                recorder = EngineRecorder(config, clock, store)
            elif frame.timestamp_utc < clock.current:
                summary["outOfOrder"] += 1
                continue
            clock.current = frame.timestamp_utc
            recorder.poll()
            for signal in decoder.decode(frame):
                selected = signal.key == "engine_speed" and signal.source_address == config.detector.source_address
                if selected and signal.quality == "GOOD" and isinstance(signal.value, (int, float)) and math.isfinite(signal.value):
                    summary["rpmValidDecoded"] += 1
                    summary["maxRpm"] = max(summary["maxRpm"] or 0, signal.value)
                accepted = recorder.offer_decoded(signal, evidence_ref=f"{path.name}:line:{line_number}")
                if selected and accepted:
                    summary["rpmAccepted"] += 1
            drain()
    if recorder is None:
        raise ValueError("no replay frames")
    recorder.flush()
    drain()
    # El EOF no demuestra parada ni pérdida futura; no adelantar artificialmente el reloj.
    with sqlite3.connect(store.path.as_uri() + "?mode=ro", uri=True) as c:
        summary["events"] = dict(c.execute("SELECT event_type,COUNT(*) FROM j1939_engine_events WHERE event_id LIKE ? GROUP BY event_type", (recorder.writer_id + ":%",)))
    summary["syntheticOrReal"] = "depends_on_input_provenance_not_inferred"
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    migrate = commands.add_parser("migrate", help="migración explícita, solo tras revisión")
    migrate.add_argument("--database", type=Path, required=True)
    migrate.add_argument("--create", action="store_true", help="permite crear archivo nuevo; no crea carpetas")
    replay = commands.add_parser("replay", help="lee archivos, jamás transmite a CAN")
    replay.add_argument("--input", type=Path, required=True)
    replay.add_argument("--format", choices=("csv", "candump"), required=True)
    replay.add_argument("--database", type=Path, required=True, help="DB de ensayo ya migrada")
    replay.add_argument("--config", type=Path, required=True)
    replay.add_argument("--enable-offline-recording", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        store = EngineStore(args.database)
        if args.command == "migrate":
            store.migrate(create=args.create)
            print(json.dumps({"migration": 1, "status": "applied_or_verified"}))
        else:
            raw = json.loads(args.config.read_text(encoding="utf-8"))
            config = RecorderConfig(gateway_id=raw["gateway_id"], detector=DetectorConfig(**raw["detector"]), enabled=True)
            print(json.dumps(run_replay(args.input, args.format, config, store), sort_keys=True))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print("Offline operation failed: " + type(exc).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
