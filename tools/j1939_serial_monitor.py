from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path: sys.path.insert(0, str(BASE_DIR))

from j1939.config import load_yaml
from j1939.decoder import SignalDecoder
from j1939.transport import ReplayCanFrameSource, SerialCanFrameSource


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor pasivo J1939")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--port"); group.add_argument("--replay")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--signals", default=str(BASE_DIR / "config/j1939_signals.yml"))
    args = parser.parse_args()
    decoder = SignalDecoder(load_yaml(args.signals)["signals"])
    source = ReplayCanFrameSource(args.replay) if args.replay else SerialCanFrameSource(args.port, args.baudrate)
    source.open()
    try:
        while True:
            frame = source.read_frame()
            if frame is None:
                if args.replay: break
                continue
            item = frame.public_dict()
            print(f'{item["timestampUtc"]} CAN={item["canId"]} PGN={item["pgn"]} SA={item["sourceAddress"]} DLC={item["dlc"]} DATA={item["data"]}')
            for signal in decoder.decode(frame):
                print(f"  {signal.key}={signal.value} {signal.unit} quality={signal.quality} confidence={signal.confidence}")
    finally:
        source.close()
    return 0


if __name__ == "__main__": raise SystemExit(main())
