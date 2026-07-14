import joblib
import numpy as np
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import (
    CHECKPOINT_DIR,
    MODEL_PATH,
    NEW_BATCH_X_PATH,
    NEW_BATCH_Y_PATH,
    SCALER_PATH,
)


BATCH_SIZE = 32
EPOCHS = 1
LR = 1e-5


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")
    if not NEW_BATCH_X_PATH.exists() or not NEW_BATCH_Y_PATH.exists():
        raise FileNotFoundError("Expected new_batch_X.npy and new_batch_y.npy in data/prepared/")

    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LR),
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )

    scaler = joblib.load(SCALER_PATH) if SCALER_PATH.exists() else None
    X_new = np.load(NEW_BATCH_X_PATH)
    y_new = np.load(NEW_BATCH_Y_PATH)

    if scaler is not None:
        shape = X_new.shape
        flat = X_new.reshape(-1, shape[2])
        flat = scaler.transform(flat)
        X_new = flat.reshape(shape)

    callbacks = [
        EarlyStopping(monitor="loss", patience=3, restore_best_weights=True),
        ModelCheckpoint(
            filepath=str(CHECKPOINT_DIR / "ckpt_latest.keras"),
            save_best_only=True,
            monitor="loss",
        ),
    ]

    model.fit(
        X_new,
        y_new,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        shuffle=True,
        callbacks=callbacks,
    )

    model.save(MODEL_PATH)
    print("Incremental update complete")


if __name__ == "__main__":
    main()
