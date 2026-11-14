CREATE TABLE j1939_evidence_batch_sessions (
 batch_id TEXT PRIMARY KEY REFERENCES j1939_recorder_batches(batch_id),
 session_id TEXT NOT NULL REFERENCES j1939_engine_sessions(session_id)
);
CREATE INDEX idx_j1939_evidence_batch_session ON j1939_evidence_batch_sessions(session_id);
CREATE TRIGGER j1939_evidence_bind_batch AFTER INSERT ON j1939_recorder_batches
BEGIN
 INSERT INTO j1939_evidence_batch_sessions(batch_id,session_id)
 SELECT NEW.batch_id,sid FROM (
  SELECT session_id AS sid FROM j1939_recorder_checkpoint WHERE gateway_id=NEW.gateway_id AND equipment_id=NEW.equipment_id
  UNION ALL
  SELECT session_id AS sid FROM j1939_engine_sessions WHERE stop_event_id IN
   (SELECT event_id FROM j1939_engine_events WHERE substr(event_id,1,length(NEW.batch_id)+1)=NEW.batch_id||':')
 ) WHERE sid IS NOT NULL LIMIT 1;
END;
CREATE TABLE j1939_evidence_segments (
 segment_id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, anchor_batch_id TEXT NOT NULL,
 session_id TEXT REFERENCES j1939_engine_sessions(session_id), file_path TEXT NOT NULL UNIQUE,
 started_at_utc TEXT, ended_at_utc TEXT, frame_count INTEGER NOT NULL CHECK(frame_count>=0),
 pgn_json TEXT NOT NULL, source_json TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
 integrity TEXT NOT NULL CHECK(integrity IN ('OPEN','COMPLETE','INCOMPLETE','MISSING','DELETED')),
 close_reason TEXT, sha256 TEXT CHECK(sha256 IS NULL OR length(sha256)=64),
 manifest_json TEXT NOT NULL
);
CREATE INDEX idx_j1939_evidence_session_time ON j1939_evidence_segments(session_id,started_at_utc);
