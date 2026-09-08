from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    pass


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "si", "on"}


def load_project_env(base_dir: Path) -> bool:
    """Carga el .env del proyecto sin sobrescribir el entorno del servicio."""
    from dotenv import load_dotenv

    return bool(load_dotenv(dotenv_path=base_dir / ".env", override=False))


def load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("configuration root must be a mapping")
    signals = value.get("signals")
    if not isinstance(signals, list):
        raise ConfigurationError("signals must be a list")
    required = {"key", "name", "pgn", "start_byte", "bit_length", "byte_order", "signed", "scale", "offset", "unit", "source", "enabled", "confidence"}
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict) or required - signal.keys():
            missing = sorted(required - signal.keys()) if isinstance(signal, dict) else sorted(required)
            raise ConfigurationError(f"signals[{index}] missing fields: {', '.join(missing)}")
        if int(signal["start_byte"]) < 1 or int(signal["bit_length"]) < 1:
            raise ConfigurationError(f"signals[{index}] has an invalid byte/bit range")
        if signal["byte_order"] not in {"little", "big"}:
            raise ConfigurationError(f"signals[{index}] has invalid byte_order")
        if signal["confidence"] not in {"CONFIRMED", "PROBABLE", "UNKNOWN"}:
            raise ConfigurationError(f"signals[{index}] has invalid confidence")
    return value


def runtime_settings(base_dir: Path) -> dict[str, Any]:
    return {
        "enabled": env_bool("J1939_ENABLED", False),
        "transport": os.getenv("J1939_TRANSPORT", "serial").strip().lower(),
        "can_interface": os.getenv("J1939_CAN_INTERFACE", "can0").strip(),
        "serial_device": os.getenv("J1939_SERIAL_DEVICE", "").strip(),
        "serial_baudrate": int(os.getenv("J1939_SERIAL_BAUDRATE", "115200")),
        "replay_file": os.getenv("J1939_REPLAY_FILE", "").strip(),
        "heartbeat_seconds": int(os.getenv("J1939_HEARTBEAT_SECONDS", "600")),
        "recent_frame_limit": int(os.getenv("J1939_RECENT_FRAME_LIMIT", "200")),
        "api_host": "127.0.0.1",
        "api_port": int(os.getenv("J1939_LOCAL_API_PORT", "8765")),
        "capture_dir": base_dir / os.getenv("J1939_CAPTURE_DIR", "data/j1939_captures"),
        "capture_max_duration_seconds": int(os.getenv("J1939_CAPTURE_MAX_DURATION_SECONDS", "3600")),
        "capture_max_file_mb": float(os.getenv("J1939_CAPTURE_MAX_FILE_MB", "50")),
        "capture_max_files": int(os.getenv("J1939_CAPTURE_MAX_FILES", "20")),
        "capture_queue_size": int(os.getenv("J1939_CAPTURE_QUEUE_SIZE", "2000")),
        "can_bitrate": int(os.getenv("J1939_CAN_BITRATE", os.getenv("J1939_BITRATE", "250000"))),
        "signal_file": base_dir / os.getenv("J1939_SIGNAL_CONFIG", "config/j1939_signals.yml"),
    }
