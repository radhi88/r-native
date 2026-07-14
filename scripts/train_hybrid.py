"""
train_hybrid.py — تدريب / ضبط دقيق لنموذج FRIDAY.

الوضع الكامل (افتراضي):
  بناء نموذج جديد Conv1D + Multi-Head Attention + GRU وتدريبه من الصفر.

الوضع التدريجي (--incremental):
  تحميل النموذج الحالي وضبطه الدقيق بمعدل تعلم أقل دون فقدان الأوزان المكتسبة.
  مفيد لإعادة التدريب الدورية بعد تراكم بيانات صفقات جديدة.

مهمة الانحدار (--task regression):
  رأس softplus(1) + Huber loss + R2Score metric، جميع الـ callbacks تراقب val_r2.
  مخصص لهدف التقلب/النظام (volatility/regime) — لا يُعدّل مسار الاتجاه.
"""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import CHECKPOINT_DIR, DATA_DIR, MODEL_PATH, PREPARED_DIR


REPORT_PATH = MODEL_PATH.parent / "training_report.json"
_THRESHOLDS_PATH = DATA_DIR / "symbol_thresholds.json"


def load_meta(prepared_dir=PREPARED_DIR):
    meta_path = prepared_dir / "meta.json"
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_model(seq_len: int, features: int, task: str = "direction") -> tf.keras.Model:
    """
    معمارية Conv1D + Multi-Head Self-Attention + GRU.

    - Conv1D (causal) لاستخراج الأنماط المحلية
    - Multi-Head Attention لالتقاط التبعيات البعيدة
    - GRU للتسلسل الزمني
    - Dropout منع Overfitting مع بيانات مالية ضجّاجة

    task="direction"  -> Dense(1, activation="sigmoid")  (الاتجاه — الافتراضي)
    task="regression" -> Dense(1, activation="softplus") (التقلب — vol >= 0)
    """
    reg = tf.keras.regularizers.l2(1e-5)
    inp = layers.Input(shape=(seq_len, features), name="sequence_input")

    # ── تطبيع أولي + ضجيج ─────────────────────────────────────────────────
    x = layers.LayerNormalization(name="input_norm")(inp)
    x = layers.GaussianNoise(0.01, name="input_noise")(x)

    # ── كتلة Conv1D الأولى (أنماط قصيرة المدى) ────────────────────────────
    x = layers.Conv1D(64, kernel_size=5, padding="causal", activation="relu",
                      kernel_regularizer=reg, name="conv1")(x)
    x = layers.BatchNormalization(name="bn1")(x)
    x = layers.SpatialDropout1D(0.05, name="sdrop1")(x)

    # ── كتلة Conv1D الثانية (أنماط متوسطة المدى) ──────────────────────────
    x = layers.Conv1D(96, kernel_size=3, padding="causal", activation="relu",
                      kernel_regularizer=reg, name="conv2")(x)
    x = layers.BatchNormalization(name="bn2")(x)

    # ── Multi-Head Self-Attention (التبعيات بعيدة المدى) ──────────────────
    attn_out = layers.MultiHeadAttention(
        num_heads=4, key_dim=24, dropout=0.10, name="mha"
    )(x, x)
    x = layers.Add(name="attn_residual")([x, attn_out])
    x = layers.LayerNormalization(name="attn_norm")(x)

    # ── GRU (التسلسل الزمني) ───────────────────────────────────────────────
    x = layers.GRU(64, kernel_regularizer=reg, recurrent_dropout=0.10,
                   name="gru")(x)
    x = layers.Dropout(0.30, name="gru_drop")(x)

    # ── طبقة إخراج — تتغير بحسب المهمة (task) فقط ──────────────────────────
    x = layers.Dense(48, activation="gelu", kernel_regularizer=reg, name="dense1")(x)
    x = layers.Dropout(0.30, name="dense_drop")(x)

    if task == "regression":
        # رأس الانحدار: softplus يضمن vol >= 0
        out = layers.Dense(1, activation="softplus", name="output")(x)
    else:
        # رأس الاتجاه (الافتراضي): sigmoid للتصنيف الثنائي
        out = layers.Dense(1, activation="sigmoid", name="output")(x)

    return models.Model(inp, out, name="friday_hybrid_v2")


def split_data(X, y, meta):
    train_end = int(meta.get("train_end", len(X) * 0.70))
    val_end   = int(meta.get("val_end",   len(X) * 0.85))
    return (
        X[:train_end],  y[:train_end],
        X[train_end:val_end], y[train_end:val_end],
        X[val_end:],    y[val_end:],
        train_end, val_end,
    )


def class_weight(y):
    values, counts = np.unique(y, return_counts=True)
    total = len(y)
    return {int(v): float(total / (len(values) * c)) for v, c in zip(values, counts)}


def scan_thresholds(prob: np.ndarray, y: np.ndarray) -> dict:
    """بحث دقيق عن العتبات المثلى مع مقاييس أشمل."""
    best = {
        "score":              -1.0,
        "buy_threshold":       0.55,
        "sell_threshold":      0.45,
        "coverage":            0.0,
        "direction_accuracy":  0.0,
        "precision":           0.0,
        "recall":              0.0,
        "f1":                  0.0,
        "expected_value":      0.0,
    }

    for buy_thr in np.arange(0.50, 0.86, 0.01):
        sell_thr = 1.0 - buy_thr
        buy  = prob >= buy_thr
        sell = prob <= sell_thr
        trade = buy | sell

        if trade.sum() < max(30, int(len(y) * 0.02)):
            continue

        direction_correct = ((buy & (y == 1)) | (sell & (y == 0)))[trade]
        accuracy  = float(direction_correct.mean())
        coverage  = float(trade.mean())

        # مقاييس إضافية
        tp = int(((buy & (y == 1)) | (sell & (y == 0))).sum())
        fp = int(((buy & (y == 0)) | (sell & (y == 1))).sum())
        fn = int((~trade & (y == (1 if buy.sum() > sell.sum() else 0))).sum())

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall + 1e-9)

        # قيمة متوقعة بفرض R:R = 1.5
        ev = accuracy * 1.5 - (1 - accuracy) * 1.0

        # نقاط: دقة الاتجاه × جذر تربيعي لنسبة التغطية
        score = accuracy * np.sqrt(min(coverage / 0.15, 1.0))

        if score > best["score"]:
            best = {
                "score":             float(score),
                "buy_threshold":     float(buy_thr),
                "sell_threshold":    float(sell_thr),
                "coverage":          coverage,
                "direction_accuracy": accuracy,
                "precision":         precision,
                "recall":            recall,
                "f1":                float(f1),
                "expected_value":    float(ev),
            }

    return best


def main():
    parser = argparse.ArgumentParser(description="FRIDAY model training")
    parser.add_argument("--task",
                        choices=["direction", "regression"],
                        default="direction",
                        help="Training task: 'direction' (binary sigmoid, default) or "
                             "'regression' (softplus vol head, Huber loss, R2Score metric, val_r2 callbacks)")
    parser.add_argument("--epochs",       type=int,   default=60)
    parser.add_argument("--batch-size",   type=int,   default=128)
    parser.add_argument("--patience",     type=int,   default=10)
    parser.add_argument("--incremental",  action="store_true",
                        help="Fine-tune existing model instead of training from scratch")
    parser.add_argument("--fine-tune-lr", type=float, default=1e-5,
                        help="Learning rate for incremental fine-tuning")
    parser.add_argument("--prepared-dir", type=Path, default=None,
                        help="Directory holding X.npy/y.npy/meta.json (default: config PREPARED_DIR)")
    parser.add_argument("--model-out", type=Path, default=None,
                        help="Output path for the trained .keras model (default: config MODEL_PATH)")
    parser.add_argument("--scaler-out", type=Path, default=None,
                        help="Per-symbol scaler .pkl to copy into the model dir (optional)")
    args = parser.parse_args()

    is_regression = args.task == "regression"

    # ── Effective paths (per-symbol overrides; module constants untouched) ─
    prepared_dir = args.prepared_dir if args.prepared_dir is not None else PREPARED_DIR
    model_path = args.model_out if args.model_out is not None else MODEL_PATH
    report_path = model_path.parent / "training_report.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # ── تحميل البيانات ────────────────────────────────────────────────────
    X = np.load(prepared_dir / "X.npy", mmap_mode="r")
    y = np.load(prepared_dir / "y.npy")
    meta = load_meta(prepared_dir)

    # أوزان العينات — مخصصة لمسار الاتجاه فقط (direction task only)
    # في وضع الانحدار يتم التدريب بدون أوزان (Open Q3 resolved: drop for vol regression)
    if args.task == "direction":
        weights_path = prepared_dir / "sample_weights.npy"
        sample_weights_all = np.load(weights_path) if weights_path.exists() else None
    else:
        sample_weights_all = None  # regression: train unweighted

    splits = split_data(X, y, meta)
    X_train, y_train, X_val, y_val, X_test, y_test, train_end, val_end = splits

    if args.task == "direction":
        sw_train = sample_weights_all[:train_end] if sample_weights_all is not None else None
    else:
        sw_train = None  # regression: unweighted

    print(f"Task:       {args.task}")
    print(f"X:          {X.shape}")
    print(f"y:          {y.shape}")
    print(f"Features:   {X.shape[2]}")
    print(f"Train/Val/Test: {len(y_train)}/{len(y_val)}/{len(y_test)}")
    if args.task == "direction":
        print(f"Positive rates: {y_train.mean():.3f} / {y_val.mean():.3f} / {y_test.mean():.3f}")
    else:
        print(f"y stats (train): mean={y_train.mean():.6f}  std={y_train.std():.6f}  "
              f"min={y_train.min():.6f}  max={y_train.max():.6f}")
    print(f"Sample weights: {'loaded' if sw_train is not None else 'none'}")
    print(f"Mode:       {'incremental (fine-tune)' if args.incremental else 'full training'}")

    # ── بناء / تحميل النموذج ─────────────────────────────────────────────
    if args.incremental and model_path.exists():
        print(f"Loading existing model from {model_path} for fine-tuning...")
        model = tf.keras.models.load_model(str(model_path))
        lr = args.fine_tune_lr
        effective_epochs  = min(args.epochs, 10)
        effective_patience = min(args.patience, 3)
        print(f"Fine-tune LR: {lr}  Epochs: {effective_epochs}  Patience: {effective_patience}")
    else:
        if args.incremental:
            print("No existing model found — training from scratch.")
        # Pass task so build_model swaps the output activation correctly
        model = build_model(X.shape[1], X.shape[2], task=args.task)
        lr = 3e-4
        effective_epochs  = args.epochs
        effective_patience = args.patience

    # ── Compile — branches on task ─────────────────────────────────────────
    if is_regression:
        # وضع الانحدار: Huber loss + MAE + R2Score; val_r2 هو المؤشر المُراقَب
        model.compile(
            optimizer=tf.keras.optimizers.Adam(lr),
            loss=tf.keras.losses.Huber(delta=1.0),
            metrics=[
                "mae",
                tf.keras.metrics.R2Score(name="r2"),
            ],
        )
        monitor_metric = "val_r2"
        monitor_mode   = "max"
        best_ckpt_name = "best_regime_model.keras"
    else:
        # وضع الاتجاه (الافتراضي): BinaryCrossentropy + AUC/Precision/Recall
        model.compile(
            optimizer=tf.keras.optimizers.Adam(lr),
            loss=tf.keras.losses.BinaryCrossentropy(label_smoothing=0.04),
            metrics=[
                "accuracy",
                tf.keras.metrics.AUC(name="auc"),
                tf.keras.metrics.Precision(name="precision"),
                tf.keras.metrics.Recall(name="recall"),
            ],
        )
        monitor_metric = "val_auc"
        monitor_mode   = "max"
        best_ckpt_name = "best_direction_model.keras"

    model.summary()

    # ── Callbacks — all three monitor the task-appropriate metric ──────────
    best_path = CHECKPOINT_DIR / best_ckpt_name
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor=monitor_metric, mode=monitor_mode,
            patience=effective_patience,
            restore_best_weights=True,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(best_path),
            monitor=monitor_metric, mode=monitor_mode,
            save_best_only=True,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor=monitor_metric, mode=monitor_mode,
            patience=2, factor=0.5, min_lr=1e-6,
        ),
    ]

    # ── التدريب ───────────────────────────────────────────────────────────
    fit_kwargs = dict(
        validation_data=(X_val, y_val),
        epochs=effective_epochs,
        batch_size=args.batch_size,
        shuffle=False,
        callbacks=callbacks,
    )
    if args.task == "direction":
        # أوزان العينات تتضمن ضمنياً توازن الفئات — لا حاجة لـ class_weight معها
        if sw_train is not None:
            fit_kwargs["sample_weight"] = sw_train
        else:
            fit_kwargs["class_weight"] = class_weight(y_train)
    # regression: no sample_weight / class_weight — train unweighted

    history = model.fit(X_train, y_train, **fit_kwargs)

    # ── تقييم ─────────────────────────────────────────────────────────────
    metrics = model.evaluate(X_test, y_test, verbose=0, batch_size=args.batch_size)
    test_metrics = dict(zip(model.metrics_names, [float(v) for v in metrics]))

    # ── حفظ النموذج ───────────────────────────────────────────────────────
    model.save(model_path)
    if best_path.exists() and Path(best_path).resolve() != Path(model_path).resolve():
        shutil.copy2(best_path, model_path)

    # Per-symbol scaler -> models/{SYMBOL}/scaler.pkl  (or regime_scaler.pkl for regression)
    # --scaler-out specifies the DESTINATION path (e.g. models/{sym}/regime_scaler.pkl).
    # The SOURCE is prepared_dir / <filename> (written by prepare_sequences.py).
    if args.scaler_out is not None:
        dest_scaler = Path(args.scaler_out)
        src_scaler  = prepared_dir / dest_scaler.name
        if not src_scaler.exists():
            # Fallback: check the standard scaler name in prepared_dir
            src_scaler = prepared_dir / "regime_scaler.pkl" if is_regression else prepared_dir / "scaler.pkl"
        if src_scaler.exists():
            dest_scaler.parent.mkdir(parents=True, exist_ok=True)
            if src_scaler.resolve() != dest_scaler.resolve():
                shutil.copy2(str(src_scaler), str(dest_scaler))
            print(f"Saved scaler:  {dest_scaler}")
        else:
            print(f"WARNING: scaler source not found (tried: {src_scaler}); scaler not copied.")

    # ── تقرير — يتفرع بحسب المهمة ────────────────────────────────────────
    if is_regression:
        # وضع الانحدار: استخرج أفضل val_r2 وفجوة train/val r2
        val_r2_hist   = history.history.get("val_r2", [float("nan")])
        train_r2_hist = history.history.get("r2", [])
        best_epoch    = int(np.nanargmax(val_r2_hist))
        best_val_r2   = float(val_r2_hist[best_epoch])
        best_train_r2 = float(train_r2_hist[best_epoch]) if best_epoch < len(train_r2_hist) else float("nan")
        train_val_gap = float(best_train_r2 - best_val_r2)

        report = {
            "task":                "regression",
            "model_architecture":  "conv1d_mha_gru_v2",
            "features_count":      int(X.shape[2]),
            "seq_len":             int(X.shape[1]),
            "training_samples":    int(len(y_train)),
            "val_samples":         int(len(y_val)),
            "test_samples":        int(len(y_test)),
            "best_val_r2":         best_val_r2,
            "best_epoch":          int(best_epoch),
            "best_train_r2":       best_train_r2,
            "train_val_gap":       train_val_gap,
            "incremental":         args.incremental,
            "train_end":           train_end,
            "val_end":             val_end,
            "history":             {k: [float(v) for v in vals] for k, vals in history.history.items()},
            "test_metrics":        test_metrics,
            "sample_weights_used": False,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)

        print(f"\nSaved model:    {model_path}")
        print(f"Saved report:   {report_path}")
        print(f"Test metrics:   {test_metrics}")
        print(f"Best val R2:    {best_val_r2:.4f}")
        print(f"Best train R2:  {best_train_r2:.4f}  |  train/val gap: {train_val_gap:+.4f} (epoch {best_epoch})")

    else:
        # وضع الاتجاه (الافتراضي): val_auc + scan_thresholds + symbol_thresholds.json
        val_prob = model.predict(X_val, verbose=0, batch_size=args.batch_size).flatten()
        threshold_report = scan_thresholds(val_prob, y_val)

        val_auc_hist = history.history.get("val_auc", [0.0])
        train_auc_hist = history.history.get("auc", [])
        best_epoch = int(np.argmax(val_auc_hist))
        best_val_auc = float(val_auc_hist[best_epoch])
        best_train_auc = float(train_auc_hist[best_epoch]) if best_epoch < len(train_auc_hist) else float("nan")
        train_val_gap = float(best_train_auc - best_val_auc)

        report = {
            "task":                "direction",
            "model_architecture":  "conv1d_mha_gru_v2",
            "features_count":      int(X.shape[2]),
            "seq_len":             int(X.shape[1]),
            "training_samples":    int(len(y_train)),
            "val_samples":         int(len(y_val)),
            "test_samples":        int(len(y_test)),
            "best_val_auc":        float(best_val_auc),
            "best_epoch":          int(best_epoch),
            "best_train_auc":      float(best_train_auc),
            "train_val_gap":       float(train_val_gap),
            "incremental":         args.incremental,
            "train_end":           train_end,
            "val_end":             val_end,
            "history":             {k: [float(v) for v in vals] for k, vals in history.history.items()},
            "test_metrics":        test_metrics,
            "thresholds":          threshold_report,
            "sample_weights_used": sw_train is not None,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)

        # ── تحديث symbol_thresholds.json بالعتبات المثلى (direction only) ──
        try:
            state = {}
            if _THRESHOLDS_PATH.exists():
                state = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
            state["_global_optimal"] = {
                "buy_threshold":      threshold_report["buy_threshold"],
                "sell_threshold":     threshold_report["sell_threshold"],
                "coverage":           threshold_report["coverage"],
                "direction_accuracy": threshold_report["direction_accuracy"],
                "f1":                 threshold_report["f1"],
                "expected_value":     threshold_report["expected_value"],
                "model_architecture": "conv1d_mha_gru_v2",
            }
            _THRESHOLDS_PATH.write_text(
                json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"Updated symbol_thresholds.json with optimal thresholds")
        except Exception as exc:
            print(f"Warning: could not update symbol_thresholds.json: {exc}")

        print(f"\nSaved model:   {model_path}")
        print(f"Saved report:  {report_path}")
        print(f"Test metrics:  {test_metrics}")
        print(f"Thresholds:    {threshold_report}")
        print(f"Best val AUC:  {best_val_auc:.4f}")
        print(f"Best train AUC: {best_train_auc:.4f}  |  train/val gap: {train_val_gap:+.4f} (epoch {best_epoch})")


if __name__ == "__main__":
    main()
