from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from j1939.config import ConfigurationError, load_project_env, runtime_settings
from j1939.service import J1939Runtime, start_local_api
from j1939.transport import CanFrameSource, ReplayCanFrameSource, SerialCanFrameSource, SocketCanFrameSource


def create_frame_source(settings: dict, stop: threading.Event) -> CanFrameSource:
    transport = settings["transport"]
    if transport == "socketcan":
        return SocketCanFrameSource(settings["can_interface"])
    if transport == "serial":
        return SerialCanFrameSource(settings["serial_device"], settings["serial_baudrate"])
    if transport == "replay":
        if not settings.get("replay_file"):
            raise ConfigurationError("J1939_REPLAY_FILE is required for replay transport")
        return ReplayCanFrameSource(settings["replay_file"], stop)
    raise ConfigurationError(f"unsupported J1939_TRANSPORT: {transport}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Servicio pasivo J1939 de SAMEE100")
    parser.add_argument("--replay", help="archivo RAW generado por SAMEE100")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_project_env(BASE_DIR)
    settings = runtime_settings(BASE_DIR)
    if not settings["enabled"]:
        logging.info("J1939_ENABLED=false; service disabled")
        return 0
    if args.replay:
        settings["transport"] = "replay"; settings["replay_file"] = args.replay
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set()); signal.signal(signal.SIGTERM, lambda *_: stop.set())
    source = create_frame_source(settings, stop)
    device = settings["can_interface"] if settings["transport"] == "socketcan" else settings.get("serial_device") or settings.get("replay_file")
    logging.info("J1939 | enabled=true | transport=%s | device=%s", settings["transport"], device)
    runtime = J1939Runtime(settings)
    server, api_thread = start_local_api(runtime, settings["api_host"], settings["api_port"])
    reconnect = False
    try:
        while not stop.is_set():
            try:
                source.open(); runtime.state.set_connected(True, reconnect); reconnect = True
                logging.info("J1939 | %s connected | %s", settings["transport"], device)
                while not stop.is_set():
                    frame = source.read_frame()
                    if frame is not None: runtime.process(frame)
                    elif settings["transport"] == "replay": break
            except (OSError, ValueError, RuntimeError) as exc:
                runtime.state.set_connected(False)
                logging.warning("J1939 | %s disconnected | reason=%s", settings["transport"], exc)
                if settings["transport"] == "replay": return 2
                logging.info("J1939 | reconnecting in 2 s")
                stop.wait(2)
            finally:
                source.close()
            if settings["transport"] == "replay": break
    finally:
        runtime.state.set_connected(False)
        if runtime.capture.status()["captureActive"]: runtime.capture.stop("SERVICE_STOPPED")
        server.shutdown(); server.server_close(); api_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
