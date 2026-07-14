import json
from pathlib import Path
import sys

import numpy as np
import zmq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mt5_ai.config import PREPARED_DIR, ZMQ_BIND


def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(ZMQ_BIND)

    X = np.load(PREPARED_DIR / "X.npy")
    payload = {"sequence": X[0].tolist()}

    sock.send(json.dumps(payload).encode())
    print("Reply:", sock.recv().decode())


if __name__ == "__main__":
    main()
