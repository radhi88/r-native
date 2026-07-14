"""
retrain_full.py — إعادة تدريب كاملة لنموذج FRIDAY.

الخطوات:
  1. استخراج البيانات من MT5 (اختياري)
  2. تحضير التسلسلات مع ميزات SMC الكاملة (31 ميزة)
  3. تدريب نموذج Conv1D + Multi-Head Attention + GRU
  4. عرض نتائج التدريب

الاستخدام:
  python retrain_full.py              # تدريب كامل من الصفر (اتجاه)
  python retrain_full.py --incremental  # ضبط دقيق للنموذج الحالي
  python retrain_full.py --epochs 30 --batch-size 64
  python retrain_full.py --regime --symbol XAUUSDm
      # وضع النظام: يستخدم تسلسلات M15 من {sym}_regime/ ويدرّب رأس الانحدار
      # الناتج: models/{sym}/regime_model.keras + models/{sym}/regime_scaler.pkl
      # (لا يُلغي نموذج الاتجاه model.keras / scaler.pkl)
"""

import subprocess
import sys
import time
from pathlib import Path

from _bootstrap import bootstrap
bootstrap()

from mt5_ai.config import (
    CSV_HISTORY, MT5_SYMBOL, PREPARED_DIR, MODEL_PATH, RAW_DATA_DIR,
    DEFAULT_SYMBOLS, symbol_model_path, symbol_scaler_path,
)


def regime_model_path(symbol: str) -> Path:
    """
    مسار نموذج النظام المستقل عن نموذج الاتجاه.
    models/{SYMBOL}/regime_model.keras
    لا يتعارض مع model.keras (نموذج الاتجاه، المرحلة 3).
    """
    return symbol_model_path(symbol).parent / "regime_model.keras"


def regime_scaler_path(symbol: str) -> Path:
    """
    مسار الـ scaler المستقل لوضع النظام.
    models/{SYMBOL}/regime_scaler.pkl
    لا يتعارض مع scaler.pkl (نموذج الاتجاه).
    """
    return symbol_model_path(symbol).parent / "regime_scaler.pkl"


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - t0
    ok = result.returncode == 0
    status = "✓ نجح" if ok else "✗ فشل"
    print(f"\n{status}  ({elapsed:.1f}s)")
    return ok


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FRIDAY Full Retraining Pipeline")
    parser.add_argument("--epochs",      type=int, default=60)
    parser.add_argument("--batch-size",  type=int, default=128)
    parser.add_argument("--patience",    type=int, default=10)
    parser.add_argument("--incremental", action="store_true",
                        help="Fine-tune existing model (faster, preserves weights)")
    parser.add_argument("--skip-prepare", action="store_true",
                        help="Skip data preparation (use existing X.npy/y.npy)")
    parser.add_argument("--symbol", type=str, default=MT5_SYMBOL)
    parser.add_argument("--history", type=Path, default=None,
                        help="CSV or Parquet history file. Defaults to data/raw/{symbol}_history.parquet")
    parser.add_argument("--per-symbol", action="store_true",
                        help="Train a separate model+scaler for each symbol "
                             "(models/{SYMBOL}/model.keras + scaler.pkl)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbol list for --per-symbol "
                             "(default: config DEFAULT_SYMBOLS)")
    parser.add_argument("--regime", action="store_true",
                        help="Regime (vol regression) mode: threads --target regime to "
                             "prepare_sequences and --task regression to train_hybrid. "
                             "Writes models/{SYMBOL}/regime_model.keras + regime_scaler.pkl. "
                             "Does NOT overwrite the direction model.keras / scaler.pkl.")
    args = parser.parse_args()

    scripts_dir = Path(__file__).parent
    python = sys.executable

    def _train_one(symbol: str) -> bool:
        sym = str(symbol).strip()
        hist = RAW_DATA_DIR / f"{sym}_history.parquet"
        if not hist.exists() and sym == MT5_SYMBOL and CSV_HISTORY.exists():
            hist = CSV_HISTORY
        if not hist.exists():
            print(f"\n[SKIP] {sym}: history not found at {hist}")
            return False

        if args.regime:
            # ── وضع النظام (regime) ──────────────────────────────────────
            # تسلسلات M15 في مجلد مستقل لتجنب تلوث تسلسلات الاتجاه
            prepared_dir = PREPARED_DIR / f"{sym}_regime"
            scaler_out   = regime_scaler_path(sym)   # models/{SYMBOL}/regime_scaler.pkl
            model_out    = regime_model_path(sym)     # models/{SYMBOL}/regime_model.keras
        else:
            # ── وضع الاتجاه (direction) — سلوك غير متغير ─────────────────
            prepared_dir = PREPARED_DIR / sym
            scaler_out   = symbol_scaler_path(sym)   # models/{SYMBOL}/scaler.pkl
            model_out    = symbol_model_path(sym)    # models/{SYMBOL}/model.keras

        prepared_dir.mkdir(parents=True, exist_ok=True)
        model_out.parent.mkdir(parents=True, exist_ok=True)

        if not args.skip_prepare:
            prepare_cmd = [
                python, str(scripts_dir / "prepare_sequences.py"),
                "--history", str(hist),
                "--symbol",  sym,
                "--out-dir", str(prepared_dir),
                "--scaler",  str(scaler_out),
            ]
            if args.regime:
                # تحضير تسلسلات النظام (M15 + تسمية الانحدار + حواف الثلثيات)
                prepare_cmd += ["--target", "regime"]

            step_label = (
                f"[{sym}] 1/2 Prepare sequences (regime M15 vol)"
                if args.regime
                else f"[{sym}] 1/2 Prepare sequences (31 SMC features)"
            )
            ok = run_step(step_label, prepare_cmd)
            if not ok:
                print(f"\n[FAIL] {sym}: data preparation failed")
                return False

        train_cmd = [
            python, str(scripts_dir / "train_hybrid.py"),
            "--epochs",      str(args.epochs),
            "--batch-size",  str(args.batch_size),
            "--patience",    str(args.patience),
            "--prepared-dir", str(prepared_dir),
            "--model-out",   str(model_out),
            "--scaler-out",  str(scaler_out),
        ]
        if args.incremental:
            train_cmd.append("--incremental")
        if args.regime:
            # تدريب رأس الانحدار (softplus + Huber + R2Score + val_r2)
            train_cmd += ["--task", "regression"]

        step_label = (
            f"[{sym}] 2/2 Train Conv1D+MHA+GRU -> {model_out} (regime regression)"
            if args.regime
            else f"[{sym}] 2/2 Train Conv1D+MHA+GRU -> {model_out}"
        )
        ok = run_step(step_label, train_cmd)
        if not ok:
            print(f"\n[FAIL] {sym}: training failed")
        return ok

    if args.per_symbol:
        symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
                   if args.symbols else list(DEFAULT_SYMBOLS))
        mode_label = "regime regression" if args.regime else "direction"
        print(f"\nFRIDAY — per-symbol retraining ({mode_label})")
        print(f"  Symbols ({len(symbols)}): {', '.join(symbols)}")
        results = {}
        for sym in symbols:
            results[sym] = _train_one(sym)
        print(f"\n{'='*60}\n  Per-symbol summary\n{'='*60}")
        for sym, ok in results.items():
            status = "OK" if ok else "FAIL/SKIP"
            mp = regime_model_path(sym) if args.regime else symbol_model_path(sym)
            print(f"  {sym:<10} {status:<10} -> {mp if ok else '(no model)'}")
        trained = sum(1 for v in results.values() if v)
        print(f"\nTrained {trained}/{len(symbols)} per-symbol models.")
        if trained == 0:
            sys.exit(1)
        return

    # ── Мarshal single-symbol paths ─────────────────────────────────────────
    history_path = args.history or (RAW_DATA_DIR / f"{args.symbol}_history.parquet")
    if not history_path.exists() and args.symbol == MT5_SYMBOL and CSV_HISTORY.exists():
        history_path = CSV_HISTORY

    if args.regime:
        # وضع النظام: مجلد مستقل + مسارات نموذج مستقلة
        prepared_dir_single = PREPARED_DIR / f"{args.symbol}_regime"
        model_out_single    = regime_model_path(args.symbol)
        scaler_out_single   = regime_scaler_path(args.symbol)
        mode_str = "regime (vol regression, M15)"
    else:
        prepared_dir_single = PREPARED_DIR
        model_out_single    = MODEL_PATH
        scaler_out_single   = None
        mode_str = "اتجاه (direction)"

    print("\nFRIDAY — إعادة التدريب الكاملة")
    print(f"  الرمز:          {args.symbol}")
    print(f"  ملف التاريخ:    {history_path}")
    print(f"  مسار البيانات: {prepared_dir_single}")
    print(f"  مسار النموذج: {model_out_single}")
    print(f"  الوضع:         {mode_str}")
    print(f"  تدريج:         {'تدريجي (fine-tune)' if args.incremental else 'كامل من الصفر'}")

    # ── 1. تحضير التسلسلات ─────────────────────────────────────────────────
    if not args.skip_prepare:
        if not history_path.exists():
            print(f"\n✗ ملف التاريخ غير موجود: {history_path}")
            print("  شغّل get_data.py أولاً أو أضف --skip-prepare إذا كانت X.npy موجودة")
            sys.exit(1)

        prepare_cmd = [
            python,
            str(scripts_dir / "prepare_sequences.py"),
            "--history", str(history_path),
            "--symbol",  str(args.symbol),
        ]
        if args.regime:
            prepared_dir_single.mkdir(parents=True, exist_ok=True)
            prepare_cmd += [
                "--out-dir", str(prepared_dir_single),
                "--scaler",  str(scaler_out_single),
                "--target",  "regime",
            ]

        step_label = (
            "الخطوة 1/2: تحضير تسلسلات النظام (M15 vol regime)"
            if args.regime
            else "الخطوة 1/2: تحضير التسلسلات مع ميزات SMC (31 ميزة)"
        )
        ok = run_step(step_label, prepare_cmd)
        if not ok:
            print("\n✗ فشل تحضير البيانات. أوقفت التدريب.")
            sys.exit(1)
    else:
        print("\n⟳  تخطي تحضير البيانات (--skip-prepare)")
        x_file = prepared_dir_single / "X.npy"
        if not x_file.exists():
            print(f"✗ X.npy غير موجود في {prepared_dir_single}")
            sys.exit(1)

    # ── 2. تدريب النموذج ──────────────────────────────────────────────────
    train_cmd = [
        python, str(scripts_dir / "train_hybrid.py"),
        "--epochs",     str(args.epochs),
        "--batch-size", str(args.batch_size),
        "--patience",   str(args.patience),
    ]
    if args.incremental:
        train_cmd.append("--incremental")
    if args.regime:
        model_out_single.parent.mkdir(parents=True, exist_ok=True)
        train_cmd += [
            "--task",        "regression",
            "--prepared-dir", str(prepared_dir_single),
            "--model-out",   str(model_out_single),
            "--scaler-out",  str(scaler_out_single),
        ]

    step_label = (
        "الخطوة 2/2: تدريب النموذج Conv1D + MHA + GRU (انحدار النظام)"
        if args.regime
        else "الخطوة 2/2: تدريب النموذج Conv1D + MHA + GRU"
    )
    ok = run_step(step_label, train_cmd)
    if not ok:
        print("\n✗ فشل التدريب.")
        sys.exit(1)

    # ── ملخص ───────────────────────────────────────────────────────────────
    import json
    report_path = model_out_single.parent / "training_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"\n{'='*60}")
        print("  ملخص النتائج")
        print(f"{'='*60}")
        if args.regime:
            print(f"  Best val R2:  {report.get('best_val_r2', float('nan')):.4f}")
            gap = report.get('train_val_gap')
            r2  = report.get('best_val_r2', float('nan'))
            if gap is not None:
                print(f"  Train R2:     {report.get('best_train_r2', float('nan')):.4f}")
                print(f"  Train/Val gap:{gap:+.4f}")
            print(f"  الميزات:      {report.get('features_count', 0)}")
            print(f"  عينات التدريب: {report.get('training_samples', 0):,}")
            print(f"\n  ✓ نموذج النظام محفوظ في: {model_out_single}")
            print(f"  ✓ scaler النظام محفوظ في: {scaler_out_single}")
            print("  (نموذج الاتجاه model.keras لم يتغير)")
        else:
            thr = report.get("thresholds", {})
            print(f"  AUC أفضل:     {report.get('best_val_auc', 0):.4f}")
            gap = report.get('train_val_gap')
            auc = report.get('best_val_auc', 0)
            if gap is not None:
                gate = "PASS" if (auc >= 0.55 and gap < 0.10) else "FAIL"
                print(f"  Train AUC:    {report.get('best_train_auc', 0):.4f}")
                print(f"  Train/Val gap:{gap:+.4f}")
                print(f"  Gate (>=0.55 & gap<0.10): {gate}")
            print(f"  دقة الاتجاه:  {thr.get('direction_accuracy', 0):.1%}")
            print(f"  التغطية:      {thr.get('coverage', 0):.1%}")
            print(f"  F1:           {thr.get('f1', 0):.3f}")
            print(f"  Expected Val: {thr.get('expected_value', 0):.3f}")
            print(f"  عتبة الشراء:  {thr.get('buy_threshold', 0.60):.2f}")
            print(f"  عتبة البيع:   {thr.get('sell_threshold', 0.40):.2f}")
            print(f"  الميزات:      {report.get('features_count', 0)}")
            print(f"  عينات التدريب: {report.get('training_samples', 0):,}")
            print(f"\n  ✓ النموذج محفوظ في: {MODEL_PATH}")
            print("  ✓ العتبات المثلى حُفِّثت في: symbol_thresholds.json")

    print("\n✓ اكتملت إعادة التدريب بنجاح!")


if __name__ == "__main__":
    main()
