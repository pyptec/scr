CREATE TABLE j1939_session_summary (
 session_id TEXT PRIMARY KEY REFERENCES j1939_engine_sessions(session_id),
 rpm_max REAL NOT NULL CHECK(rpm_max >= 0),
 source_address INTEGER NOT NULL CHECK(source_address BETWEEN 0 AND 253),
 pgn INTEGER NOT NULL CHECK(pgn=61444)
);
