import json
import traceback

import joblib
import numpy as np
import tensorflow as tf
import zmq

from .config import MODEL_CANDIDATES, SCALER_PATH, SEQ_LEN_EXPECTED, ZMQ_BIND


def log(*args):
    print(*args)


def load_model():
    for model_path in MODEL_CANDIDATES:
        if model_path.exists():
            try:
                log("Loading model:", model_path)
                return tf.keras.models.load_model(str(model_path), compile=False)
            except Exception:
                traceback.print_exc()
    raise RuntimeError("No valid model found in models/")


def load_scaler():
    if SCALER_PATH.exists():
        try:
            return joblib.load(SCALER_PATH)
        except Exception:
            traceback.print_exc()
    return None


def normalize_prediction(pred):
    try:
        p = np.array(pred).squeeze()

        if p.size == 1:
            prob = float(p)
            return {
                "direction": 1 if prob > 0.5 else 0,
                "probability": prob,
                "strength": abs(prob - 0.5) * 2,
                "reversal": 1.0 - prob,
            }

        return {
            "direction": int(np.argmax(p)),
            "probability": float(np.max(p)),
            "strength": float(np.max(p)),
        }

    except Exception:
        traceback.print_exc()
        return {
            "direction": 0,
            "probability": 0.0,
            "strength": 0.0,
            "reversal": 0.0,
        }


def main():
    log("Starting AI server...")

    model = load_model()
    scaler = load_scaler()

    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind(ZMQ_BIND)

    log("Server running on", ZMQ_BIND)

    while True:
        try:
            msg = socket.recv()
            data = json.loads(msg.decode())
            seq = np.array(data.get("sequence", []), dtype=float)

            if seq.size == 0:
                socket.send_json({"error": "empty_sequence"})
                continue

            if seq.ndim == 2:
                seq = seq.reshape(1, seq.shape[0], seq.shape[1])

            if seq.shape[1] != SEQ_LEN_EXPECTED:
                socket.send_json(
                    {
                        "error": "invalid_seq_len",
                        "expected": SEQ_LEN_EXPECTED,
                        "got": seq.shape[1],
                    }
                )
                continue

            if scaler is not None:
                shape = seq.shape
                flat = seq.reshape(-1, shape[2])
                flat = scaler.transform(flat)
                seq = flat.reshape(shape)

            pred = model.predict(seq, verbose=0)
            socket.send_json(normalize_prediction(pred))

        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            try:
                socket.send_json({"error": "server_error"})
            except Exception:
                pass

    socket.close()
    context.term()
    log("Stopped")


if __name__ == "__main__":
    main()
