"""Dry-run tests for chart_drawings module.

Run from repo root:    python -m tests.test_chart_drawings
"""
from __future__ import annotations

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chart_drawings as cd


def test_order_block_schema():
    d = cd.draw_order_block("XAGUSDm", "h1", 1700000000, 1700003600,
                             price_high=33.18, price_low=33.04, side="bull")
    assert d["type"] == "rectangle"
    assert d["symbol"] == "XAGUSDm"
    assert d["price_high"] == 33.18
    assert d["price_low"] == 33.04
    assert d["style"]["fill"] is True
    assert d["meta"]["pattern"] == "order_block"
    assert d["meta"]["side"] == "bull"
    assert d["id"].startswith("r_smc_ob_")
    print("OK test_order_block_schema")


def test_order_block_id_is_deterministic():
    a = cd.draw_order_block("XAUUSDm", "h1", 100, 200, 50.5, 50.1, "bull")
    b = cd.draw_order_block("XAUUSDm", "h1", 100, 200, 50.5, 50.1, "bull")
    assert a["id"] == b["id"], "same logical key must produce same ID"
    c = cd.draw_order_block("XAUUSDm", "h1", 100, 200, 50.5, 50.1, "bear")
    assert a["id"] != c["id"], "different side must produce different ID"
    print("OK test_order_block_id_is_deterministic")


def test_fvg_schema():
    d = cd.draw_fvg("EURUSDm", "m15", 100, 200, 1.0850, 1.0830, side="bear")
    assert d["type"] == "rectangle"
    assert d["meta"]["pattern"] == "fvg"
    assert d["style"]["color"] == "#FF7043"   # bearish FVG color
    print("OK test_fvg_schema")


def test_bos_and_choch_distinct():
    a = cd.draw_bos("XAUUSDm", "h1", 1700000000, 2400.0, "bull")
    b = cd.draw_choch("XAUUSDm", "h1", 1700000000, 2400.0, "bull")
    assert a["type"] == "trendline" and b["type"] == "trendline"
    assert a["style"]["line_style"] == "solid"
    assert b["style"]["line_style"] == "dash"
    assert a["meta"]["pattern"] == "bos"
    assert b["meta"]["pattern"] == "choch"
    print("OK test_bos_and_choch_distinct")


def test_sl_tp_zone_returns_three():
    out = cd.draw_sl_tp_zone("XAGUSDm", entry=33.10, sl=32.95, tp=33.50, side="long")
    assert len(out) == 3
    types = sorted(d["meta"]["category"] for d in out)
    assert types == ["entry_level", "sl", "tp"]
    print("OK test_sl_tp_zone_returns_three")


def test_narrative_label_arabic():
    text = "دخول طويل عند OB صاعد بعد كسر سيولة"
    d = cd.draw_narrative_label("XAUUSDm", 1700000000, 2400.0, text)
    # Must round-trip through JSON unchanged
    j = json.dumps(d, ensure_ascii=False)
    parsed = json.loads(j)
    assert parsed["text"] == text
    assert parsed["meta"]["rtl"] is True
    assert parsed["meta"]["font"] == "Tahoma"
    print("OK test_narrative_label_arabic")


def test_drawings_from_smc_snapshot_handles_empty():
    out = cd.drawings_from_smc_snapshot("XAGUSDm", "h1", {})
    assert out == []
    print("OK test_drawings_from_smc_snapshot_handles_empty")


def test_drawings_from_full_snapshot():
    snap = {
        "fresh_ob_above": {"top": 33.20, "bottom": 33.15, "created_at": 1700000000, "age_bars": 5},
        "fresh_ob_below": {"top": 32.50, "bottom": 32.45, "created_at": 1700000000, "age_bars": 8},
        "fresh_fvg_bull": [],
        "fresh_fvg_bear": [],
        "last_bos":       {"direction": "UP",   "level": 33.10, "created_at": 1700000000, "age_bars": 2},
        "last_choch":     {"direction": "DOWN", "level": 32.80, "created_at": 1700000000, "age_bars": 6},
        "recent_liq_sweep": {"side": "BUY", "level": 33.30, "created_at": 1700000000, "age_bars": 3, "reclaim": True},
        "liq_above": [33.40, 33.55],
        "liq_below": [32.30],
        "idm_status": {"swept": True, "side": "UP", "level": 32.90, "created_at": 1700000000, "age_bars": 4},
    }
    out = cd.drawings_from_smc_snapshot("XAGUSDm", "h1", snap)
    types = sorted({d["type"] for d in out})
    assert "rectangle" in types  # OBs
    assert "trendline" in types  # BOS / CHoCH
    assert "arrow"     in types  # sweep
    assert "hline"     in types  # IDM + liq pools
    assert len(out) >= 7         # 2 OBs + 1 BOS + 1 CHoCH + 1 sweep + 1 IDM + 3 liq pools
    print(f"OK test_drawings_from_full_snapshot ({len(out)} drawings)")


def test_filter_and_cap_drops_stale():
    import time
    now = int(time.time())
    old = cd.draw_bos("X", "h1", now - 10*3600, 100.0, "bull")
    old["created_at"] = now - 10*3600
    new = cd.draw_bos("X", "h1", now - 100,     100.0, "bear")
    new["created_at"] = now - 100
    kept = cd.filter_and_cap([old, new], stale_after_sec=6*3600)
    assert len(kept) == 1
    assert kept[0]["meta"]["side"] == "bear"
    print("OK test_filter_and_cap_drops_stale")


def test_json_serializable():
    d = cd.draw_order_block("X", "h1", 100, 200, 50.5, 50.1, "bull")
    j = json.dumps(d)
    parsed = json.loads(j)
    assert parsed == d
    print("OK test_json_serializable")


if __name__ == "__main__":
    test_order_block_schema()
    test_order_block_id_is_deterministic()
    test_fvg_schema()
    test_bos_and_choch_distinct()
    test_sl_tp_zone_returns_three()
    test_narrative_label_arabic()
    test_drawings_from_smc_snapshot_handles_empty()
    test_drawings_from_full_snapshot()
    test_filter_and_cap_drops_stale()
    test_json_serializable()
    print("\n✓ all chart_drawings tests passed")
