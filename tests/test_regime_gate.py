"""
Phase 9 — REGIME-02: Gate harness ordering + honest-negative behavior tests.

These tests are EXPECTED TO FAIL (RED) until 09-04 implements
scripts/gate_regime.py.

The gate harness must:
  1. Compute a naive baseline (persistence/rolling-vol) BEFORE loading the model.
  2. Write 09-GATE-RESULT.md with a VERDICT (PASS or FAIL) on BOTH pass and fail outcomes.

Imports/subprocess invocations are wrapped so absence causes FAILED (not collection error).
"""

import subprocess
import sys
import os
import pytest
from pathlib import Path


# Root of the MT5 project (two levels up from tests/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _python_exe() -> str:
    """Return the venv Python executable path."""
    candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _gate_script() -> Path:
    return PROJECT_ROOT / "scripts" / "gate_regime.py"


class TestBaselineComputedBeforeModel:
    """
    REGIME-02 (D-05): The gate harness must compute the naive baseline BEFORE loading
    or scoring the trained model, so an honest comparison is locked in first.
    """

    def test_baseline_computed_before_model(self):
        """
        Invoke the gate in dry-run mode via subprocess and inspect stdout for ordering:
          - The string 'baseline' (or 'naive') must appear BEFORE 'model' in the output.

        If scripts/gate_regime.py does not exist yet, the test fails RED.
        If it exists but the ordering is wrong, the test fails with a descriptive message.
        """
        gate = _gate_script()
        if not gate.exists():
            pytest.fail(
                f"scripts/gate_regime.py not yet created — RED expected. "
                f"Expected at: {gate}"
            )

        result = subprocess.run(
            [_python_exe(), str(gate), "--symbol", "XAUUSDm", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )

        stdout = result.stdout.lower()
        stderr = result.stderr.lower()
        combined = stdout + "\n" + stderr

        # Look for "baseline" or "naive" before "model" in the output
        baseline_keywords = ["baseline", "naive"]
        model_keywords = ["model", "loading model", "model loaded", "model score"]

        baseline_pos = None
        for kw in baseline_keywords:
            pos = combined.find(kw)
            if pos != -1:
                if baseline_pos is None or pos < baseline_pos:
                    baseline_pos = pos

        model_pos = None
        for kw in model_keywords:
            pos = combined.find(kw)
            if pos != -1:
                if model_pos is None or pos < model_pos:
                    model_pos = pos

        assert baseline_pos is not None, (
            "Gate stdout does not mention 'baseline' or 'naive'. "
            "The gate harness must compute and print the naive baseline. "
            f"stdout={result.stdout[:500]!r}"
        )
        assert model_pos is not None, (
            "Gate stdout does not mention 'model'. "
            "The gate harness must also load/score the model. "
            f"stdout={result.stdout[:500]!r}"
        )
        assert baseline_pos < model_pos, (
            f"'baseline' appears at position {baseline_pos} in output but "
            f"'model' appears at position {model_pos}. "
            "Baseline must be computed and printed BEFORE the model is loaded/scored. "
            f"stdout={result.stdout[:800]!r}"
        )


class TestWritesResultOnFail:
    """
    REGIME-02 (D-05 / Phase-2 honest-negative ethos): The gate must write
    09-GATE-RESULT.md regardless of whether the model passes or fails the baseline check.
    """

    def test_writes_result_on_fail(self, tmp_path):
        """
        Simulate a FAIL outcome by invoking the gate in dry-run mode with a flag
        that forces a degenerate/constant prediction (so it cannot beat the naive baseline).
        Assert that 09-GATE-RESULT.md is created and contains a VERDICT line.

        Implementation strategy:
          - Pass --dry-run (or --force-fail if the gate supports it) to trigger the fail path.
          - The gate must STILL write the result file (honest-negative ethos from 02-GATE-RESULT.md).
          - We look for the result file in either PROJECT_ROOT/.planning/phases/09-*/ or
            PROJECT_ROOT/ itself (wherever gate_regime.py chooses to write it).

        If scripts/gate_regime.py does not exist yet, the test fails RED.
        """
        gate = _gate_script()
        if not gate.exists():
            pytest.fail(
                f"scripts/gate_regime.py not yet created — RED expected. "
                f"Expected at: {gate}"
            )

        # Run gate with --dry-run (expected to fail the gate check since no real model)
        result = subprocess.run(
            [_python_exe(), str(gate), "--symbol", "XAUUSDm", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )

        # Search for the result file in known locations
        candidate_paths = [
            PROJECT_ROOT / "09-GATE-RESULT.md",
            PROJECT_ROOT / ".planning" / "phases" / "09-volatility-regime-retarget" / "09-GATE-RESULT.md",
            PROJECT_ROOT / ".planning" / "09-GATE-RESULT.md",
        ]

        result_file = None
        for p in candidate_paths:
            if p.exists():
                result_file = p
                break

        assert result_file is not None, (
            "09-GATE-RESULT.md was not written after running gate_regime.py --dry-run. "
            "The gate MUST write the result file on BOTH pass and fail outcomes "
            "(Phase-2 honest-negative ethos — no silent failures). "
            f"Searched: {[str(p) for p in candidate_paths]}. "
            f"gate stdout={result.stdout[:400]!r} stderr={result.stderr[:200]!r}"
        )

        content = result_file.read_text(encoding="utf-8")
        assert "VERDICT" in content.upper() or "PASS" in content.upper() or "FAIL" in content.upper(), (
            f"09-GATE-RESULT.md exists but contains no VERDICT/PASS/FAIL marker. "
            f"Content preview: {content[:300]!r}"
        )


class TestGateScriptExists:
    """
    Sanity: gate_regime.py must exist before other gate tests can be meaningful.
    This test makes the RED state explicit.
    """

    def test_gate_script_file_exists(self):
        """
        Assert that scripts/gate_regime.py exists.
        This is the primary RED marker — will fail until 09-04 creates the script.
        """
        gate = _gate_script()
        assert gate.exists(), (
            f"scripts/gate_regime.py does not exist yet. "
            f"This is expected (RED) until plan 09-04 implements it. "
            f"Expected path: {gate}"
        )
