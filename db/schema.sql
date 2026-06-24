-- =========================================================
-- BASE DE DATOS SAMEE100
-- PYP Tecnología Electrónica SAS
-- Modelo:
-- gateway_id  = Nodo / gateway SAMEE100
-- device_id   = Elemento de medición conectado
-- source_type = gateway / device
-- unit_id     = Variable medida
-- =========================================================


-- =========================================================
-- GATEWAYS / NODOS SAMEE100
-- =========================================================
CREATE TABLE IF NOT EXISTS gateways (
    gateway_id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT,
    ubicacion TEXT,
    cliente TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- DISPOSITIVOS / ELEMENTOS DE MEDICIÓN
-- Ejemplo:
-- 31 = Eastron SDM630
-- 7  = SHT20
-- 13 = Sistema SAMEE100
-- =========================================================
CREATE TABLE IF NOT EXISTS dispositivos (
    device_id INTEGER PRIMARY KEY,
    gateway_id INTEGER,
    nombre TEXT,
    tipo TEXT,
    ubicacion TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(gateway_id) REFERENCES gateways(gateway_id)
);


-- =========================================================
-- CATÁLOGO DE UNIDADES / VARIABLES
-- unit_id puede repetirse en diferentes device_id.
-- Por eso NO debe usarse solo como identificador único de medición.
-- =========================================================
CREATE TABLE IF NOT EXISTS unidades (
    unit_id INTEGER PRIMARY KEY,
    name TEXT,
    simbol TEXT,
    description TEXT
);


-- =========================================================
-- MEDICIONES RAW
-- Guarda el payload completo original.
-- device_id queda para compatibilidad histórica.
-- =========================================================
CREATE TABLE IF NOT EXISTS mediciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    device_id TEXT,
    payload_json TEXT NOT NULL,
    sent_aws INTEGER DEFAULT 0,
    sent_at TEXT,
    created_at TEXT NOT NULL
);


-- =========================================================
-- MEDICIONES NORMALIZADAS
-- Aquí queda cada variable individual.
--
-- Casos:
--
-- Payload con "g":
--   source_type = 'device'
--   device_id = valor de g
--   gateway_id puede quedar NULL y resolverse por tabla dispositivos
--
-- Payload con "i":
--   source_type = 'gateway'
--   gateway_id = valor de i
--   device_id = NULL
-- =========================================================
CREATE TABLE IF NOT EXISTS mediciones_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id INTEGER,
    timestamp_utc TEXT NOT NULL,
    gateway_id INTEGER,
    device_id TEXT,
    source_type TEXT,
    unit_id INTEGER,
    valor REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_id) REFERENCES mediciones(id),
    FOREIGN KEY(gateway_id) REFERENCES gateways(gateway_id),
    FOREIGN KEY(unit_id) REFERENCES unidades(unit_id)
);


-- =========================================================
-- COLA AWS
-- Guarda payloads pendientes cuando no hay conexión.
-- =========================================================
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


-- =========================================================
-- ÍNDICES
-- Mejoran consultas del dashboard, reportes y series.
-- =========================================================
CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_timestamp
ON mediciones_detalle(timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_unit
ON mediciones_detalle(unit_id);

CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_device_unit
ON mediciones_detalle(device_id, unit_id);

CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_gateway_unit
ON mediciones_detalle(gateway_id, unit_id);

CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_source
ON mediciones_detalle(source_type);

CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_compuesta
ON mediciones_detalle(gateway_id, source_type, device_id, unit_id, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_aws_queue_status
ON aws_queue(status);


-- =========================================================
-- VISTA GENERAL DE MEDICIONES
-- Mantiene compatibilidad con consultas antiguas.
-- Incluye gateway, dispositivo y unidad.
-- =========================================================
DROP VIEW IF EXISTS vw_mediciones;

CREATE VIEW vw_mediciones AS
SELECT
    md.id,
    md.raw_id,
    md.timestamp_utc,

    COALESCE(md.gateway_id, d.gateway_id) AS gateway_id,
    g.nombre AS gateway,
    g.cliente AS cliente,

    CASE
        WHEN md.source_type IS NOT NULL AND TRIM(md.source_type) <> ''
            THEN md.source_type
        WHEN md.gateway_id IS NOT NULL
             AND (md.device_id IS NULL OR TRIM(md.device_id) = '')
            THEN 'gateway'
        WHEN md.device_id IS NOT NULL
             AND TRIM(md.device_id) <> ''
            THEN 'device'
        ELSE 'unknown'
    END AS source_type,

    NULLIF(TRIM(md.device_id), '') AS device_id,
    d.nombre AS dispositivo,
    d.tipo AS tipo_dispositivo,
    d.ubicacion AS ubicacion_dispositivo,

    md.unit_id,
    u.name AS variable,
    u.name AS name,
    u.simbol AS simbol,
    md.valor,
    md.created_at

FROM mediciones_detalle md

LEFT JOIN dispositivos d
    ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id

LEFT JOIN gateways g
    ON COALESCE(md.gateway_id, d.gateway_id) = g.gateway_id

LEFT JOIN unidades u
    ON md.unit_id = u.unit_id;