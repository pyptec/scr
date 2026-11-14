CREATE TABLE j1939_engine_events (
 event_id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL, equipment_id TEXT NOT NULL,
 timestamp_utc TEXT NOT NULL, event_type TEXT NOT NULL CHECK(event_type IN ('START','STOP','COMM_LOST','COMM_RECOVERED','STATE_RECONCILED')),
 previous_state TEXT NOT NULL, current_state TEXT NOT NULL, rpm REAL CHECK(rpm IS NULL OR rpm>=0),
 source_address INTEGER NOT NULL CHECK(source_address BETWEEN 0 AND 253), pgn INTEGER NOT NULL DEFAULT 61444,
 spn INTEGER NOT NULL DEFAULT 190, reason TEXT NOT NULL, evidence_quality TEXT NOT NULL,
 evidence_ref TEXT, observed_at_utc TEXT, recorded_at_utc TEXT NOT NULL
);
CREATE INDEX idx_j1939_events_equipment_time ON j1939_engine_events(gateway_id,equipment_id,timestamp_utc);
CREATE TABLE j1939_engine_sessions (
 session_id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL, equipment_id TEXT NOT NULL,
 start_event_id TEXT UNIQUE REFERENCES j1939_engine_events(event_id),
 stop_event_id TEXT UNIQUE REFERENCES j1939_engine_events(event_id),
 started_at_utc TEXT, ended_at_utc TEXT, observed_from_utc TEXT NOT NULL, observed_until_utc TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ABIERTA','CERRADA','INDETERMINADA')),
 active INTEGER NOT NULL CHECK(active IN (0,1)), initial_rpm REAL, final_rpm REAL,
 initial_hourmeter REAL, final_hourmeter REAL,
 duration_seconds REAL CHECK(duration_seconds IS NULL OR duration_seconds>=0),
 verified_seconds REAL NOT NULL DEFAULT 0 CHECK(verified_seconds>=0),
 time_without_communication REAL CHECK(time_without_communication IS NULL OR time_without_communication>=0),
 quality TEXT NOT NULL CHECK(quality IN ('CONFIRMED','INCOMPLETE')), close_reason TEXT, notes TEXT,
 CHECK(ended_at_utc IS NULL OR started_at_utc IS NULL OR ended_at_utc>=started_at_utc),
 CHECK(status!='CERRADA' OR (active=0 AND ended_at_utc IS NOT NULL AND stop_event_id IS NOT NULL))
);
CREATE UNIQUE INDEX idx_j1939_one_active_session ON j1939_engine_sessions(gateway_id,equipment_id) WHERE active=1;
CREATE INDEX idx_j1939_sessions_equipment_time ON j1939_engine_sessions(gateway_id,equipment_id,observed_from_utc);
CREATE TABLE j1939_observation_gaps (
 gap_id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL, equipment_id TEXT NOT NULL,
 session_id TEXT REFERENCES j1939_engine_sessions(session_id), started_at_utc TEXT NOT NULL,
 recovered_at_utc TEXT, duration_seconds REAL CHECK(duration_seconds IS NULL OR duration_seconds>=0),
 reason TEXT NOT NULL, CHECK(recovered_at_utc IS NULL OR recovered_at_utc>=started_at_utc)
);
CREATE UNIQUE INDEX idx_j1939_one_open_gap ON j1939_observation_gaps(gateway_id,equipment_id) WHERE recovered_at_utc IS NULL;
CREATE TABLE j1939_recorder_checkpoint (
 gateway_id TEXT NOT NULL, equipment_id TEXT NOT NULL, writer_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence>=0), state TEXT NOT NULL,
 last_confirmed_state TEXT NOT NULL, last_observed_at_utc TEXT,
 session_id TEXT REFERENCES j1939_engine_sessions(session_id), needs_reconcile INTEGER NOT NULL CHECK(needs_reconcile IN (0,1)),
 PRIMARY KEY(gateway_id,equipment_id)
);
CREATE TABLE j1939_recorder_batches (
 batch_id TEXT PRIMARY KEY, writer_id TEXT NOT NULL, sequence INTEGER NOT NULL,
 gateway_id TEXT NOT NULL, equipment_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 UNIQUE(writer_id,sequence)
);

CREATE INDEX idx_j1939_gaps_session ON j1939_observation_gaps(session_id);
