import json
from pathlib import Path
import sys

import zmq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mt5_ai.config import FEATURES, SEQ_LEN_EXPECTED, ZMQ_BIND


def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(ZMQ_BIND)

    payload = {"sequence": [[0.0] * FEATURES for _ in range(SEQ_LEN_EXPECTED)]}

    sock.send(json.dumps(payload).encode())
    reply = sock.recv().decode()
    print("Reply:", reply)


if __name__ == "__main__":
    main()
