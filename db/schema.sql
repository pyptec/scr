CREATE TABLE IF NOT EXISTS unidades (
    unit_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    simbol TEXT
);
CREATE TABLE IF NOT EXISTS dispositivos (
    device_id INTEGER PRIMARY KEY,
    nombre TEXT,
    tipo TEXT,
    ubicacion TEXT
);
CREATE TABLE IF NOT EXISTS mediciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    device_id TEXT,
    payload_json TEXT NOT NULL,
    sent_aws INTEGER DEFAULT 0,
    sent_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mediciones_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id INTEGER,
    timestamp_utc TEXT NOT NULL,
    device_id TEXT,
    unit_id INTEGER,
    valor REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_id) REFERENCES mediciones(id),
    FOREIGN KEY(unit_id) REFERENCES unidades(unit_id)
);

CREATE TABLE IF NOT EXISTS aws_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicion_id INTEGER,
    topic TEXT,
    payload_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    FOREIGN KEY(medicion_id) REFERENCES mediciones(id)
);

CREATE INDEX IF NOT EXISTS idx_mediciones_time
ON mediciones(timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_detalle_unit_time
ON mediciones_detalle(unit_id, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_queue_status
ON aws_queue(status);