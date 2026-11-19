"""Read-only views of existing engine sessions and event snapshots."""
from contextlib import closing
import json
import hashlib
import math
from pathlib import Path
from datetime import datetime
import sqlite3


def sessions(path, limit=20, offset=0):
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("invalid pagination")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM j1939_engine_sessions ORDER BY observed_from_utc DESC, session_id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [_detail(c, row) for row in rows]


def detail(path, session_id):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM j1939_engine_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        return _detail(c, row)


def _hourmeter_snapshot(event):
    """Return only a verifiable v2 FEE5/EA reading, retaining its provenance."""
    try:
        snap = json.loads(event["evidence_ref"] or "{}")
        if snap.get("kind") != "j1939_signal_snapshot_v2":
            return None
        evaluated = datetime.fromisoformat(snap["evaluatedAtUtc"].replace("Z", "+00:00"))
        event_time = datetime.fromisoformat(event["timestamp_utc"].replace("Z", "+00:00"))
        limit = snap["maxSampleAgeSeconds"]
        if (evaluated.utcoffset() is None or event_time.utcoffset() is None or evaluated > event_time
                or isinstance(limit, bool) or not isinstance(limit, (int, float))
                or not math.isfinite(limit) or limit <= 0):
            return None
        valid = []
        for sample in snap.get("signals", []):
            if not isinstance(sample, dict):
                continue
            value = sample.get("value")
            if (sample.get("key") != "engine_total_hours" or sample.get("pgn") != 0xFEE5
                    or sample.get("spn") != 247 or sample.get("sourceAddress") != 0xEA
                    or sample.get("unit") != "h" or sample.get("available") is not True
                    or sample.get("quality") != "GOOD" or sample.get("confidence") != "CONFIRMED"
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                continue
            stamp = datetime.fromisoformat(sample["timestampUtc"].replace("Z", "+00:00"))
            if stamp.utcoffset() is not None and 0 <= (evaluated - stamp).total_seconds() <= limit:
                valid.append((stamp, {"value": value, "timestamp_utc": sample["timestampUtc"],
                                      "event_id": event["event_id"], "event_type": event["event_type"],
                                      "source": "event_snapshot_v2"}))
        return max(valid, key=lambda x: x[0]) if valid else None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None


def _hourmeter_history(c, row):
    result = {"start": None, "stop": None, "prior": None, "posterior": None, "delta": None}
    try:
        first = datetime.fromisoformat(row["observed_from_utc"].replace("Z", "+00:00"))
        stop = datetime.fromisoformat(row["ended_at_utc"].replace("Z", "+00:00")) if row["ended_at_utc"] and row["stop_event_id"] else None
        if first.utcoffset() is None or (stop and (stop.utcoffset() is None or stop < first)):
            return result
    except (AttributeError, TypeError, ValueError):
        return result
    prior = []; posterior = []
    for event in c.execute("SELECT * FROM j1939_engine_events WHERE gateway_id=? AND equipment_id=? ORDER BY timestamp_utc, event_id", (row["gateway_id"], row["equipment_id"])):
        reading = _hourmeter_snapshot(event)
        if not reading:
            continue
        stamp, sample = reading
        if event["event_id"] == row["start_event_id"] and event["event_type"] == "START":
            result["start"] = sample
        if event["event_id"] == row["stop_event_id"] and event["event_type"] == "STOP":
            result["stop"] = sample
        if stamp <= first:
            prior.append(reading)
        if stop is not None and stamp >= stop:
            posterior.append(reading)
    if prior:
        result["prior"] = max(prior, key=lambda x: x[0])[1]
    if posterior:
        result["posterior"] = min(posterior, key=lambda x: x[0])[1]
    a, b = result["prior"], result["posterior"]
    if a and b and b["value"] >= a["value"]:
        result["delta"] = b["value"] - a["value"]
    return result


def _detail(c, row):
    session_id = row["session_id"]
    result = dict(row)
    result["observation_gaps"] = [dict(x) for x in c.execute("SELECT * FROM j1939_observation_gaps WHERE session_id=? ORDER BY started_at_utc", (session_id,))]
    # Context only: no UPDATE and no inferred session_id. The unlinked gap must
    # close at the exact reconciliation event that opened this session.
    result["prior_observation_context"] = []
    if row["start_event_id"] is None and session_id.endswith(":session"):
        reconcile_id = session_id[:-len(":session")] + ":reconciled"
        event = c.execute("""SELECT timestamp_utc, observed_at_utc FROM j1939_engine_events
                          WHERE event_id=? AND gateway_id=? AND equipment_id=?
                          AND event_type='STATE_RECONCILED' AND current_state='RUNNING'""",
                          (reconcile_id, row["gateway_id"], row["equipment_id"])).fetchone()
        if event and event["observed_at_utc"] == row["observed_from_utc"]:
            candidates = c.execute("""SELECT * FROM j1939_observation_gaps
                      WHERE gateway_id=? AND equipment_id=? AND session_id IS NULL
                      AND recovered_at_utc=?""", (row["gateway_id"], row["equipment_id"], event["timestamp_utc"])).fetchall()
            try:
                first = datetime.fromisoformat(row["observed_from_utc"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(event["timestamp_utc"].replace("Z", "+00:00"))
                if first.utcoffset() is not None and end.utcoffset() is not None and 0 <= (end-first).total_seconds() <= 2:
                    for gap in candidates:
                        start = datetime.fromisoformat(gap["started_at_utc"].replace("Z", "+00:00"))
                        if start.utcoffset() is not None and 0 <= (first-start).total_seconds() <= 300:
                            result["prior_observation_context"].append(dict(gap))
            except (TypeError, ValueError, AttributeError):
                pass
    result["events"] = []
    for event_id in (row["start_event_id"], row["stop_event_id"]):
        if event_id:
            event = c.execute("SELECT * FROM j1939_engine_events WHERE event_id=?", (event_id,)).fetchone()
            if event:
                result["events"].append(dict(event))
    result["evidence"] = []
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='j1939_evidence_segments'").fetchone():
        result["evidence"] = [dict(x) for x in c.execute("SELECT * FROM j1939_evidence_segments WHERE session_id=? ORDER BY started_at_utc", (session_id,))]
    # Event snapshots are evidence, not interpolated samples. Only accept EA and
    # the recorded availability decision made at event time.
    result["event_measurements"] = {}
    legacy_freshness_unknown = False
    expected = {"engine_speed": 0xF004, "coolant_temperature": 0xFEEE,
                "engine_total_hours": 0xFEE5, "dc_voltage_field_1": 0xFEF7}
    for event in result["events"]:
        readings = {}
        try:
            snapshot = json.loads(event["evidence_ref"] or "{}")
            if snapshot.get("kind") in ("j1939_signal_snapshot_v1", "j1939_signal_snapshot_v2"):
                if snapshot.get("kind") == "j1939_signal_snapshot_v1":
                    legacy_freshness_unknown = True
                for sample in snapshot.get("signals", []):
                    if (isinstance(sample, dict) and sample.get("sourceAddress") == 0xEA
                            and expected.get(sample.get("key")) == sample.get("pgn")
                            and sample.get("available") is True and sample.get("quality") == "GOOD"
                            and sample.get("confidence") == ("PROBABLE" if sample.get("key") == "dc_voltage_field_1" else "CONFIRMED")):
                        try:
                            sample_time = datetime.fromisoformat(sample["timestampUtc"].replace("Z", "+00:00"))
                            event_time = datetime.fromisoformat(event["timestamp_utc"].replace("Z", "+00:00"))
                            valid_time = (sample_time.utcoffset() is not None and event_time.utcoffset() is not None
                                          and sample_time <= event_time)
                            if valid_time and snapshot.get("kind") == "j1939_signal_snapshot_v2":
                                evaluated = datetime.fromisoformat(snapshot["evaluatedAtUtc"].replace("Z", "+00:00"))
                                limit = snapshot["maxSampleAgeSeconds"]
                                valid_time = (evaluated.utcoffset() is not None and evaluated <= event_time
                                              and isinstance(limit, (int, float)) and not isinstance(limit, bool)
                                              and math.isfinite(limit) and limit > 0
                                              and 0 <= (evaluated - sample_time).total_seconds() <= limit)
                            if valid_time:
                                readings[sample["key"]] = sample
                        except (KeyError, TypeError, ValueError, AttributeError):
                            continue
        except (TypeError, ValueError, AttributeError):
            pass
        result["event_measurements"][event["event_type"]] = readings
    for position, event_type in (("first", "START"), ("last", "STOP")):
        sample = result["event_measurements"].get(event_type, {}).get("coolant_temperature")
        result["coolant_" + position] = sample.get("value") if sample else None
    result["rpm_max"] = None
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='j1939_session_summary'").fetchone():
        peak = c.execute("SELECT rpm_max FROM j1939_session_summary WHERE session_id=? AND source_address=234 AND pgn=61444", (session_id,)).fetchone()
        if peak:
            result["rpm_max"] = peak[0]
    a, b = row["initial_hourmeter"], row["final_hourmeter"]
    result["hourmeter_observations"] = _hourmeter_history(c, row)
    result["hourmeter_delta"] = result["hourmeter_observations"]["delta"]
    result["warnings"] = []
    if legacy_freshness_unknown:
        result["warnings"].append("legacy_snapshot_freshness_limit_unknown")
    if result["rpm_max"] is None:
        result["warnings"].append("rpm_max_not_recorded")
    else:
        result["warnings"].append("rpm_max_persisted_samples_only")
    if result["coolant_first"] is None or result["coolant_last"] is None:
        result["warnings"].append("coolant_snapshot_unavailable")
    if not row["start_event_id"]:
        result["warnings"].append("unconfirmed_start")
    if result["observation_gaps"]:
        result["warnings"].append("observation_gaps")
    if result["prior_observation_context"]:
        result["warnings"].append("unlinked_prior_observation_context")
    if not result["evidence"] or any(e["integrity"] != "COMPLETE" for e in result["evidence"]):
        result["warnings"].append("raw_evidence_incomplete_or_missing")
    if a is not None and b is not None and b < a:
        result["warnings"].append("hourmeter_decreased")
    return result


def verify_evidence(segment, *, max_bytes=64 * 1024 * 1024):
    """Explicit read-only check; a checksum match never changes temporal integrity."""
    result = {"exists": False, "size_match": None, "sha256_match": None,
              "computed_sha256": None, "temporal_integrity": segment.get("integrity"),
              "close_reason": segment.get("close_reason"), "warnings": [], "error": None}
    try:
        manifest = json.loads(segment.get("manifest_json") or "{}")
        result["warnings"] = manifest.get("warnings", [])
    except (TypeError, ValueError):
        result["warnings"] = ["invalid_manifest"]
    try:
        path = Path(segment["file_path"])
        with path.open("rb") as stream:
            import os
            before = os.fstat(stream.fileno())
            result["exists"] = True
            result["actual_size"] = before.st_size
            result["size_match"] = before.st_size == segment.get("size_bytes")
            if before.st_size > max_bytes:
                result["error"] = "SIZE_LIMIT_EXCEEDED"
                return result
            digest = hashlib.sha256()
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                result["error"] = "FILE_CHANGED_DURING_CHECK"
                return result
            result["computed_sha256"] = digest.hexdigest()
            if segment.get("sha256"):
                result["sha256_match"] = result["computed_sha256"] == segment["sha256"].lower()
    except FileNotFoundError:
        result["error"] = "FILE_NOT_FOUND"
    except (OSError, KeyError, TypeError, ValueError):
        result["error"] = "FILE_UNREADABLE"
    return result


def verify_registered_evidence(database, session_id, segment_id, raw_directory, *, max_bytes=64 * 1024 * 1024, max_seconds=2.0):
    """Check one DB-registered RAW under a trusted directory, without following links.

    Platforms without secure directory-relative opening fail closed.
    """
    import os
    import re
    import stat
    import time
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", session_id) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", segment_id):
        raise ValueError("invalid identifier")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM j1939_evidence_segments WHERE session_id=? AND segment_id=?", (session_id, segment_id)).fetchone()
    if row is None:
        return None
    segment = dict(row)
    result = {"segment_id": segment_id, "exists": False, "size_match": None,
              "sha256_match": None, "computed_sha256": None,
              "temporal_integrity": segment["integrity"], "close_reason": segment["close_reason"], "error": None}
    try:
        manifest = json.loads(segment["manifest_json"] or "{}")
        result["warnings"] = manifest.get("warnings", []) if isinstance(manifest, dict) else ["invalid_manifest"]
    except (TypeError, ValueError):
        result["warnings"] = ["invalid_manifest"]
    root = Path(raw_directory).resolve()
    target = Path(segment["file_path"])
    if (not target.is_absolute() or target.parent.resolve() != root
            or not re.fullmatch(r"j1939_auto_[a-f0-9]{32}_[a-f0-9]{32}\.txt(?:\.partial)?", target.name)):
        result["error"] = "PATH_NOT_AUTHORIZED"
        return result
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        result["error"] = "SECURE_OPEN_UNSUPPORTED"
        return result
    directory_fd = file_fd = None
    try:
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            result["error"] = "NOT_REGULAR_FILE"
            return result
        result["exists"] = True
        result["size_match"] = before.st_size == segment["size_bytes"]
        if before.st_size > max_bytes:
            result["error"] = "SIZE_LIMIT_EXCEEDED"
            return result
        digest, total, deadline = hashlib.sha256(), 0, time.monotonic() + max_seconds
        while True:
            if time.monotonic() > deadline:
                result["error"] = "TIME_LIMIT_EXCEEDED"
                return result
            block = os.read(file_fd, min(1024 * 1024, max_bytes - total + 1))
            if not block: break
            total += len(block)
            if total > max_bytes:
                result["error"] = "SIZE_LIMIT_EXCEEDED"
                return result
            digest.update(block)
        after = os.fstat(file_fd)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            result["error"] = "FILE_CHANGED_DURING_CHECK"
            return result
        result["computed_sha256"] = digest.hexdigest()
        if segment["sha256"]:
            result["sha256_match"] = result["computed_sha256"] == segment["sha256"].lower()
    except FileNotFoundError:
        result["error"] = "FILE_NOT_FOUND"
    except OSError:
        result["error"] = "FILE_UNREADABLE"
    finally:
        if file_fd is not None: os.close(file_fd)
        if directory_fd is not None: os.close(directory_fd)
    return result
