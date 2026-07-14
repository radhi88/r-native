"""pixel_sprites.py — Retro 16x16 pixel sprite data for R Native.

H.20 — Pixel mascot module that powers the in-app pixel widget
       (``pixel_widget.py``) and the standalone HTML lab
       (``dashboard/pixel_lab.html``).

This file contains ONLY pure-Python data and helpers — no PySide6 imports —
so it can be re-used by:

* the desktop PySide6 widget (drawn via ``QPainter`` rects),
* the Flask brain_server (served as JSON to the HTML panel),
* the MQL5 EA exporter (renders mini icons for the trade journal),
* the build_exe scripts (bakes the sprite atlas into _internal).

Palette is locked to the R Native gold/violet/dark navy theme so the
mascot blends seamlessly with the Algory-comfort layout (Phase H.10) and
the modern dark theme (Phase H.9).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
#  PALETTE — exactly the colours used by app.py + r_factory_ui.html
# ─────────────────────────────────────────────────────────────────────────────
#
#  Key  Hex          Role
#  ───  ───────────  ────────────────────────────────────────────────
#   .   transparent  empty pixel
#   K   #0a0a0f      outline / shadow (matches BG_0 of app.py)
#   W   #f1f5f9      crisp highlight / star sparkle (matches TEXT)
#   D   #5a5a70      mid-grey terminal text (matches TEXT_DIM)
#   d   #2a2a38      darker grey (matches BG_ELEVATED)
#   G   #fbbf24      R-Factory gold (matches GOLD palette token)
#   O   #b45309      gold shadow / pressed gold (matches GOLD_DIM)
#   Y   #fef3c7      pale yellow highlight
#   B   #f7931a      bitcoin orange (BTC asset class)
#   b   #c47e15      bitcoin shadow / dark orange
#   V   #22c55e      bullish neon green (matches GREEN of app.py)
#   v   #0e2a1a      bullish shadow / armed-bg (matches GREEN_BG)
#   R   #ef4444      bearish neon red (matches RED of app.py)
#   r   #2a0e0e      bearish shadow / loss-bg (matches RED_BG)
#   P   #ffcca3      skin peach (trader face)
#   p   #d4936a      skin shadow
#   H   #6d4c41      hair brown
#   h   #4e342e      hair dark
#   C   #06b6d4      live cyan (OOS / diamond) — matches CYAN of app.py
#   U   #a78bfa      R-Factory violet (matches VIOLET token)
#   u   #4c1d95      violet shadow / violet-soft
#   F   #2563eb      ethereum blue (ETH asset class)
#   f   #1d4ed8      ethereum shadow
#   M   #94a3b8      muted grey (matches TEXT_MUTED of app.py)
#   m   #26262f      border grey
#
PALETTE: Dict[str, Optional[str]] = {
    ".": None,
    "K": "#0a0a0f",
    "W": "#f1f5f9",
    "D": "#5a5a70",
    "d": "#2a2a38",
    "G": "#fbbf24",
    "O": "#b45309",
    "Y": "#fef3c7",
    "B": "#f7931a",
    "b": "#c47e15",
    "V": "#22c55e",
    "v": "#0e2a1a",
    "R": "#ef4444",
    "r": "#2a0e0e",
    "P": "#ffcca3",
    "p": "#d4936a",
    "H": "#6d4c41",
    "h": "#4e342e",
    "C": "#06b6d4",
    "U": "#a78bfa",
    "u": "#4c1d95",
    "F": "#2563eb",
    "f": "#1d4ed8",
    "M": "#94a3b8",
    "m": "#26262f",
}


# ─────────────────────────────────────────────────────────────────────────────
#  TRADER STATES — used by pixel_widget.py to map engine events to mascots
# ─────────────────────────────────────────────────────────────────────────────
#
#  Map of trader_state → preset_id  used by Trader.react()
#
STATE_TO_PRESET: Dict[str, str] = {
    "idle":         "bull-trader",         # neutral / scanning
    "scanning":     "r-mascot",            # GA running
    "profit":       "diamond-hands",       # in-profit live trade
    "big-profit":   "rocket-mode",         # >5% gain
    "loss":         "emotion-fomo",        # in-loss live trade
    "panic":        "emotion-panic",       # drawdown > daily-cap
    "liquidated":   "skull",               # margin call / cap hit
    "hodl":         "diamond-hands",       # HODL shield active
    "deploying":    "golden-candle",       # genome being deployed
    "campaign":     "bull-trader",         # GA campaign running
    "range":        "confused",            # sideways market
}


# ─────────────────────────────────────────────────────────────────────────────
#  SPRITE PRESETS — 16x16 strings, 2 frames each (Frame-1 = pose, Frame-2 = anim)
# ─────────────────────────────────────────────────────────────────────────────
#
#  All sprites are intentionally hand-pixeled so they look chunky and
#  retro — never AI-blurry. Each frame is a list of 16 strings of length 16.
#
SPRITE_PRESETS: List[Dict] = [
    # ════════════════ SYMBOLS ════════════════
    {
        "id": "xau-gold",
        "name": "XAU Gold Bar",
        "category": "symbols",
        "description": "Classic 16-bit gold bullion bar with diagonal shimmer.",
        "frames": [
            [
                "................",
                "....KKKKKKKK....",
                "...KYYYYYYYOK...",
                "..KYGGGGGGGOOK..",
                ".KYGGGGGGGGGOOK.",
                ".KYYYYYGGGGGOOK.",
                ".KGGGGYYYYGGOOK.",
                ".KGGGGGGGGYGOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                "..KOOOOOOOOOK...",
                "...KKKKKKKKK....",
                "................",
            ],
            [
                "................",
                "....KKKKKKKK....",
                "...KYYYYYYYOK...",
                "..KYGGGGYGGGOOK.",
                ".KYGGGYWYGGGOOK.",
                ".KYYYYWWWYGGOOK.",
                ".KGGGYWYGGGGOOK.",
                ".KGGGGYGGGGGOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                ".KGGGGGGGGGOOOK.",
                "..KOOOOOOOOOK...",
                "...KKKKKKKKK....",
                "................",
            ],
        ],
    },
    {
        "id": "btc-coin",
        "name": "BTC Bitcoin",
        "category": "symbols",
        "description": "Digital gold — Bitcoin coin with embossed ₿ glyph.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KYYYYYYYYK...",
                "..KYBBBBBBBBoK..",
                ".KYBBBWBWBBBBoK.",
                ".KBBBWWWBWWBBoK.",
                "KBBBWWWBWWWBBoK.",
                "KBBBBWWBWWWBBoK.",
                "KBBBWWWBWWBBBoK.",
                "KBBBBWWBWWWBBoK.",
                "KBBBWWWBWWBBBoK.",
                "KBBBBWWWWWBBBoK.",
                ".KBBBWBBBBBBBoK.",
                ".KYBBBBBBBBBoK..",
                "..KooooooooKK...",
                "...KKKKKKKKK....",
                "................",
            ],
            [
                "....KKKKKKKK....",
                "...KYYYYYYYYK...",
                "..KYBBBBBBBBoK..",
                ".KYBBBWBYBBBBoK.",
                ".KBBBWWYYWWBBoK.",
                "KBBBWWYBYWWBBoK.",
                "KBBBBWYBYWWBBoK.",
                "KBBBWWYBYWBBBoK.",
                "KBBBBWYBYWWBBoK.",
                "KBBBWWYBYWBBBoK.",
                "KBBBBWYYYYBBBoK.",
                ".KBBBWBBBBBBBoK.",
                ".KYBBBBBBBBBoK..",
                "..KooooooooKK...",
                "...KKKKKKKKK....",
                "................",
            ],
        ],
    },
    {
        "id": "eth-coin",
        "name": "ETH Ethereum",
        "category": "symbols",
        "description": "Ethereum diamond logo on a chunky royal-blue token.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KFFFFFFFfK...",
                "..KFFFFKKFFFFfK.",
                ".KFFFFKWWKFFFFfK",
                ".KFFFKWWWWKFFFfK",
                "KFFFKWWWWWWKFFfK",
                "KFFKWWWWWWWWKFfK",
                "KFFFKKKKKKKKFFfK",
                "KFFFKWWWWWWKFFfK",
                "KFFFFKWWWWKFFFfK",
                "KFFFFFKWWKFFFFfK",
                ".KFFFFFKKFFFFffK",
                ".KFFFFFFFFFFfK..",
                "..KffffffffKK...",
                "...KKKKKKKKK....",
                "................",
            ],
            [
                "....KKKKKKKK....",
                "...KFFFFFFFfK...",
                "..KFFFFKKFFFFfK.",
                ".KFFFFKWWKFFFFfK",
                ".KFFFKWYYWKFFFfK",
                "KFFFKWYYYYWKFFfK",
                "KFFKWYYWWYYWKFfK",
                "KFFFKKKKKKKKFFfK",
                "KFFFKWYYYYWKFFfK",
                "KFFFFKWYYWKFFFfK",
                "KFFFFFKWWKFFFFfK",
                ".KFFFFFKKFFFFffK",
                ".KFFFFFFFFFFfK..",
                "..KffffffffKK...",
                "...KKKKKKKKK....",
                "................",
            ],
        ],
    },
    {
        "id": "usd-bill",
        "name": "USD Dollar",
        "category": "symbols",
        "description": "Crisp $ bill — used as the cash flow indicator.",
        "frames": [
            [
                "................",
                ".KKKKKKKKKKKKKK.",
                ".KvvvvvvvvvvvvK.",
                ".KvVVVVVVVVVVvK.",
                ".KvVKKVVVVKKVvK.",
                ".KvVKVVVVVVKVvK.",
                ".KvVKVKKKKKVKVvK",
                ".KvVKVVKKVKKVVvK",
                ".KvVKKKKVKKKVVvK",
                ".KvVVKVKKVVKVVvK",
                ".KvVKVVKKKVKVVvK",
                ".KvVKKKKKKKKKVvK",
                ".KvVVVVVVVVVVvK.",
                ".KvvvvvvvvvvvvK.",
                ".KKKKKKKKKKKKKK.",
                "................",
            ],
            [
                "................",
                ".KKKKKKKKKKKKKK.",
                ".KvvvvvvvvvvvvK.",
                ".KvVVVVVVVVVVvK.",
                ".KvVKKVVVVKKVvK.",
                ".KvVKVVWWVVKVvK.",
                ".KvVKVKKWKKVKVvK",
                ".KvVKVVKWVKKVVvK",
                ".KvVKKKKWKKKVVvK",
                ".KvVVKVKWVVKVVvK",
                ".KvVKVVKWKVKVVvK",
                ".KvVKKKKWKKKKVvK",
                ".KvVVVVVVVVVVvK.",
                ".KvvvvvvvvvvvvK.",
                ".KKKKKKKKKKKKKK.",
                "................",
            ],
        ],
    },
    # ════════════════ CHARACTERS ════════════════
    {
        "id": "bull-trader",
        "name": "Bull Trader",
        "category": "characters",
        "description": "Bullish breakout mascot — green sunglasses & gold horns.",
        "frames": [
            [
                "...KK......KK...",
                "..KGGK....KGGK..",
                ".KGGYK....KGGYK.",
                ".KGGOKKKKKKGGOK.",
                ".KKKKvvvvvvKKKK.",
                "KKvvvvvvvvvvvvKK",
                "KvvvKKvvvvKKvvvK",
                "KvvKKWKKvKKWKKvK",
                "KvKKVVKvKKVVKvvK",
                "KvKKVVKvKKVVKvvK",
                "KvvKKKKvvKKKKvvK",
                "KvvvvvKPPKvvvvvK",
                ".KvvvvKppKvvvvK.",
                "..KKvvvvvvvvKK..",
                "....KKKKKKKK....",
                ".....KDKKDK.....",
            ],
            [
                "..KK........KK..",
                ".KGGK......KGGK.",
                ".KGGYK....KGGYK.",
                ".KGGOKKKKKKGGOK.",
                ".KKKKvvvvvvKKKK.",
                "KKvvvvvvvvvvvvKK",
                "KvvvKKvvvvKKvvvK",
                "KvvKKWKKvKKWKKvK",
                "KvKKVVKvKKVVKvvK",
                "KvKKVVKvKKVVKvvK",
                "KvvKKKKvvKKKKvvK",
                "KvvvvvKPPKvvvvvK",
                ".KvvvvKppKvvvvK.",
                "..KKvvvvvvvvKK..",
                "....KKKKKKKK....",
                ".....KK..KK.....",
            ],
        ],
    },
    {
        "id": "bear-trader",
        "name": "Bear Trader",
        "category": "characters",
        "description": "Bearish short-seller — grizzly with red laser headband.",
        "frames": [
            [
                "..KKKK....KKKK..",
                ".KhhhK....KhhhK.",
                "KhhhhKKKKKKhhhhK",
                "KhhhhhhhhhhhhhhK",
                "KhhKKKKKKKKKKhhK",
                "KhKRRRRRRRRRRKhK",
                "KKhRKKRhRKKRhhKK",
                "KKhRRRRhRRRRhhKK",
                "KKhRKKRhRKKRhhKK",
                "KKhhhhhhKKhhhhKK",
                "KKhhhhKKKKhhhhKK",
                ".KhhhhhPPKhhhhK.",
                ".KhhhhhppKhhhhK.",
                "..KKhhhhhhhhKK..",
                "....KKKKKKKK....",
                ".....KDKKDK.....",
            ],
            [
                "..KKKK....KKKK..",
                ".KhhhK....KhhhK.",
                "KhhhhKKKKKKhhhhK",
                "KhhhhhhhhhhhhhhK",
                "KhhKKKKKKKKKKhhK",
                "KhKWWWWWWWWWWKhK",
                "KKhWKKWhWKKWhhKK",
                "KKhWWWWhWWWWhhKK",
                "KKhWKKWhWKKWhhKK",
                "KKhhhhhhKKhhhhKK",
                "KKhhhhKKKKhhhhKK",
                ".KhhhhhPPKhhhhK.",
                ".KhhhhhppKhhhhK.",
                "..KKhhhhhhhhKK..",
                "....KKKKKKKK....",
                ".....KK..KK.....",
            ],
        ],
    },
    {
        "id": "r-mascot",
        "name": "R Native Mascot",
        "category": "characters",
        "description": "The R logo wearing a trader visor — your campaign assistant.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KGGGGGGGGK...",
                "..KGGOOOOOOGGK..",
                ".KGGOKKKKKKOOGK.",
                ".KKKKMMMMMMKKKK.",
                "KKMMMMMMMMMMMMKK",
                "KMMKKMRRRRMKKMMK",
                "KMKWWMRRRRMWWKMK",
                "KMKWUMRRRRMUWKMK",
                "KMMKKMMRRMMKKMMK",
                "KMMMMRRRRRRMMMMK",
                "KMMMMRRRMRRRMMMK",
                ".KMMMRRMMRMMMMK..",
                "..KKMRRMMMRMMKK..",
                "...KRRMMMMRRRK..",
                "...KKKKKKKKKK...",
            ],
            [
                "....KKKKKKKK....",
                "...KGGGGGGGGK...",
                "..KGGOOOOOOGGK..",
                ".KGGOKKKKKKOOGK.",
                ".KKKKMMMMMMKKKK.",
                "KKMMMMMMMMMMMMKK",
                "KMMKKMGGGGMKKMMK",
                "KMKYYMGGGGMYYKMK",
                "KMKYUMGGGGMUYKMK",
                "KMMKKMMGGMMKKMMK",
                "KMMMMRRRRRRMMMMK",
                "KMMMMRRRMRRRMMMK",
                ".KMMMRRMMRMMMK..",
                "..KKMRRMMMRMMKK..",
                "...KRRMMMMRRRK..",
                "...KKKKKKKKKK...",
            ],
        ],
    },
    {
        "id": "friday-trader",
        "name": "Friday Hacker",
        "category": "characters",
        "description": "Friday cyber-trader with violet neon hood and cyan goggles.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KuuUUUUuuK...",
                "..KuUUUUUUUUuK..",
                ".KuUUUUUUUUUUuK.",
                ".KuUKKKKKKKKUuK.",
                "KuUKMMMMMMMMKUuK",
                "KuUKMCCKMCCMKUuK",
                "KuUKMCWKMCWMKUuK",
                "KuUKMCCKMCCMKUuK",
                "KuUKMMMMMMMMKUuK",
                "KuUKMMMPPMMMKUuK",
                ".KuUKKMPPMKKUuK.",
                ".KuUUUKMMKUUUuK.",
                "..KuUUUUUUUUuK..",
                "...KKKKKKKKKK...",
                ".....KKKKKK.....",
            ],
            [
                "....KKKKKKKK....",
                "...KuuUUUUuuK...",
                "..KuUUUUUUUUuK..",
                ".KuUUUUUUUUUUuK.",
                ".KuUKKKKKKKKUuK.",
                "KuUKMMMMMMMMKUuK",
                "KuUKMCWKMCCMKUuK",
                "KuUKMCWKMCWMKUuK",
                "KuUKMCCKMCWMKUuK",
                "KuUKMMMMMMMMKUuK",
                "KuUKMMMPPMMMKUuK",
                ".KuUKKMVVMKKUuK.",
                ".KuUUUKMMKUUUuK.",
                "..KuUUUUUUUUuK..",
                "...KKKKKKKKKK...",
                ".....KKKKKK.....",
            ],
        ],
    },
    # ════════════════ EMOTIONS ════════════════
    {
        "id": "emotion-fomo",
        "name": "FOMO Trader",
        "category": "emotions",
        "description": "Sweating eyes-bulging trader watching candles rocket without him.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPPPPPPKPPK...",
                "KPPKKKKPPKKKKPPK",
                "KPKWWWWKPKWWWWKP",
                "KPKWKKWKPKWKKWKP",
                "KPKWKKWKPKWKKWKP",
                "KPPKKKKPPKKKKPPK",
                "KPPPPPKUUPPPPPPK",
                "KPPPPPKUUPPPPPPK",
                ".KPPPPKKKKPPPPK.",
                "..KPPKRRRRKPPK..",
                "...KKKKKKKKKK...",
                "....KVV..KVV....",
                "....KVV..KVV....",
            ],
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPPPPPPKPPK...",
                "KPPKKKKPPKKKKPPK",
                "KPKWWWWKPKWWWWKP",
                "KPKWKKWKPKWKKWKP",
                "KPKWKKWKPKWKKWKP",
                "KPPKKKKPPKKKKPPK",
                "KPPPPPPKKPPPPPPK",
                "KPPPPPKUUPPPPPPK",
                ".KPPPPKKKKPPPPK.",
                "..KPPKRRRRKPPK..",
                "...KKKKKKKKKK...",
                "....KVV..KVV....",
                ".........KVV....",
            ],
        ],
    },
    {
        "id": "emotion-panic",
        "name": "Panic Seller",
        "category": "emotions",
        "description": "Tears streaming — daily-cap breach / margin call mood.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPppKKKKKKppPK.",
                "KppKKWWKKWWKKppK",
                "KPKKWWUKKWWUKKPK",
                "KPKKWWUKKWWUKKPK",
                "KPPKKUUKKUUKKPPK",
                "KPPPKUUPPKUUPPPK",
                "KPPPPKUUPPKUUPPK",
                "KKPPPKUUPPKUUPKK",
                ".KKPPKKKKKKPPKK.",
                "..KKKKRRRRKKKK..",
                "....KRRRRRRK....",
                ".....KRRRRK.....",
                "......KKKK......",
            ],
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPppKKKKKKppPK.",
                "KppKKWWKKWWKKppK",
                "KPKKWWUKKWWUKKPK",
                "KPKKWWUKKWWUKKPK",
                "KPPKKUUKKUUKKPPK",
                "KPPPKUUPPKUUPPPK",
                "KKPPKUUPPKUUPPKK",
                "KUKPPKUUPPKUUPUK",
                ".KKPPKKKKKKPPKK.",
                "..KKKKRRRRKKKK..",
                "....KRRRRRRK....",
                ".....KRRRRK.....",
                "......KKKK......",
            ],
        ],
    },
    {
        "id": "diamond-hands",
        "name": "Diamond Hands",
        "category": "emotions",
        "description": "Meditative HODLer with massive cyan diamonds — calm mode.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPKKKKKKKKPPK.",
                "KPPKWWKKKKWWKPPK",
                "KPPKKKKKKKKKKPPK",
                "KPPPPKDKKKDKPPPP",
                "KPPPPKKKKKKKPPPP",
                "KPPKKKKWWKKKKPPK",
                ".KPKCCKKKKCCKPK.",
                "KCCWCCKKKKCCWCCK",
                "KCCCCCCCCCCCCCCK",
                ".KCCCCCCCCCCCCK.",
                "..KCCCCCCCCCCK..",
                "....KCCCCCCK....",
                "......KKKK......",
            ],
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPKKKKKKKKPPK.",
                "KPPKWWKKKKWWKPPK",
                "KPPKKKKKKKKKKPPK",
                "KPPPPKDKKKDKPPPP",
                "KPPPPKKKKKKKPPPP",
                "KPPKKKKWWKKKKPPK",
                ".KPKCCKKKKCCKPK.",
                "KCCYCCKKKKCCYCCK",
                "KCCCCCCCCCCCCCCK",
                ".KCCCCCCCCCCCCK.",
                "..KCCCCCCCCCCK..",
                "....KCCCCCCK....",
                "......KKKK......",
            ],
        ],
    },
    {
        "id": "rocket-mode",
        "name": "Rocket Mode",
        "category": "emotions",
        "description": "Trader strapped to a rocket — big-profit mode (>5% gain).",
        "frames": [
            [
                "......KKKK......",
                ".....KGGGGK.....",
                "....KGYYGGGK....",
                "....KGYYYYGK....",
                "....KGGYGGGK....",
                "....KGPPPGGK....",
                "....KGPWWGGK....",
                "....KGPPPGGK....",
                "....KKKKKKKK....",
                "....KKvvvvKK....",
                "....KvVVVvK.....",
                "....KvVVVvK.....",
                "...KKKvVvKKK....",
                "..KOOKKvKKOOK...",
                ".KOYRRKKRRYOK...",
                "..KRRRKKRRRK....",
            ],
            [
                "......KKKK......",
                ".....KGGGGK.....",
                "....KGYYGGGK....",
                "....KGYYYYGK....",
                "....KGGYGGGK....",
                "....KGPPPGGK....",
                "....KGPWWGGK....",
                "....KGPPPGGK....",
                "....KKKKKKKK....",
                "....KKvvvvKK....",
                "....KvVVVvK.....",
                "....KvVVVvK.....",
                "...KKKvVvKKK....",
                "..KOOKKvKKOOK...",
                "..KRRYKKYRRK....",
                "...KRKRRKRK.....",
            ],
        ],
    },
    {
        "id": "skull",
        "name": "Liquidated",
        "category": "emotions",
        "description": "Margin-call / kill-switch tripped — the dreaded skull.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KWWWWWWWWK...",
                "..KWWWWWWWWWWK..",
                ".KWWWKKKKKKWWWK.",
                "KWWWKKKWWKKKWWWK",
                "KWWKKRRWWRRKKWWK",
                "KWKKRRRRRRRRKKWK",
                "KWKKRRRRRRRRKKWK",
                "KWKKKRRWWRRKKKWK",
                "KWWKKKRWWRKKKWWK",
                "KWWWKWWWWWWKWWWK",
                ".KWWKWKWWKWKWWK.",
                ".KWWKWKWWKWKWWK.",
                "..KKWKKKKKKKWKK.",
                "....KKKKKKKK....",
                "......KKKK......",
            ],
            [
                "....KKKKKKKK....",
                "...KWWWWWWWWK...",
                "..KWWWWWWWWWWK..",
                ".KWWWKKKKKKWWWK.",
                "KWWWKKKWWKKKWWWK",
                "KWWKRRRRRRRRKWWK",
                "KWKKRRRRRRRRKKWK",
                "KWKKRRRRRRRRKKWK",
                "KWKKKRRWWRRKKKWK",
                "KWWKKKRWWRKKKWWK",
                "KWWWKWWWWWWKWWWK",
                ".KWWKWKWWKWKWWK.",
                ".KWWKWKWWKWKWWK.",
                "..KKWKKKKKKKWKK.",
                "....KKKKKKKK....",
                "......KKKK......",
            ],
        ],
    },
    {
        "id": "confused",
        "name": "Sideways Trader",
        "category": "emotions",
        "description": "Stuck in a range — confused trader with ??? above head.",
        "frames": [
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPPPPPPPPPPPK.",
                "KPPKKKKPKKKKPPPK",
                "KPKMMMMPKMMMMKPK",
                "KPKMWKKPKKWMMKPK",
                "KPKMWKKPKKWMMKPK",
                "KPPKKKKPKKKKPPPK",
                "KPPPPKKMMKPPPPPK",
                "KPPPPKMMMMKPPPPK",
                ".KPPPPPMMMPPPPPK",
                "..KPPPPPPPPPPK..",
                "...KKKKKKKKKKK..",
                "....KGGKKGGK....",
                "....KGGKKGGK....",
            ],
            [
                "....KKKKKKKK....",
                "...KPPPPPPPPK...",
                "..KPPPPPPPPPPK..",
                ".KPPPPPPPPPPPPK.",
                "KPPKKKKPKKKKPPPK",
                "KPKMMMMPKMMMMKPK",
                "KPKKWMPMKWKMMKPK",
                "KPKMKWPMWKMMMKPK",
                "KPPKKKKPKKKKPPPK",
                "KPPPPKMMMMKPPPPK",
                "KPPPPMKMKMMKPPPK",
                ".KPPPMMMMMMPPPPK",
                "..KPPPPPPPPPPK..",
                "...KKKKKKKKKKK..",
                "....KGGKKGGK....",
                "....KGGKKGGK....",
            ],
        ],
    },
    # ════════════════ ITEMS ════════════════
    {
        "id": "golden-candle",
        "name": "Bull Candle",
        "category": "items",
        "description": "Bullish green-gold candlestick — bull engulfing signal.",
        "frames": [
            [
                "......KKKK......",
                "......KYYK......",
                "......KGGK......",
                "....KKKKKKKK....",
                "...KYYYYYYYOK...",
                "...KYYYYYYYOK...",
                "...KYYGGGGYOK...",
                "...KYGGGGGGOK...",
                "...KYGGGGGGOK...",
                "...KGGGGGGGOK...",
                "...KGGGGGGGOK...",
                "...KOOOOOOOOK...",
                "....KKKKKKKK....",
                "......KGGK......",
                "......KGGK......",
                "......KKKK......",
            ],
            [
                "......KKKK......",
                "......KWWK......",
                "......KYYK......",
                "....KKKKKKKK....",
                "...KYYYYYYYOK...",
                "...KYYYYYYYOK...",
                "...KYYVVVVYOK...",
                "...KYVVVVVVOK...",
                "...KYVVVVVVOK...",
                "...KVVVVVVVOK...",
                "...KVVVVVVVOK...",
                "...KOOOOOOOOK...",
                "....KKKKKKKK....",
                "......KGGK......",
                "......KGGK......",
                "......KKKK......",
            ],
        ],
    },
    {
        "id": "red-candle",
        "name": "Bear Candle",
        "category": "items",
        "description": "Bearish red candle — bear engulfing / short signal.",
        "frames": [
            [
                "......KKKK......",
                "......KRRK......",
                "......KrrK......",
                "....KKKKKKKK....",
                "...KrRRRRRRrK...",
                "...KRRRRRRRRK...",
                "...KRRRrrrrRRK..",
                "...KRRrrrrrrRK..",
                "...KRRrrrrrrRK..",
                "...KrrrrrrrrRK..",
                "...KrrrrrrrrRK..",
                "...KrrrrrrrrRK..",
                "....KKKKKKKK....",
                "......KRRK......",
                "......KRRK......",
                "......KKKK......",
            ],
            [
                "......KKKK......",
                "......KKKK......",
                "......KRRK......",
                "....KKKKKKKK....",
                "...KrRRRRRRrK...",
                "...KRRRRRRRRK...",
                "...KRRRrrrrRRK..",
                "...KRRrrWrrrRK..",
                "...KRRrWWWWrRK..",
                "...KrrrWrrrrRK..",
                "...KrrrrrrrrRK..",
                "...KrrrrrrrrRK..",
                "....KKKKKKKK....",
                "......KRRK......",
                "......KRRK......",
                "......KKKK......",
            ],
        ],
    },
    {
        "id": "money-bag",
        "name": "Profit Bag",
        "category": "items",
        "description": "Sack of gold coins — profit secured / vault deposit.",
        "frames": [
            [
                "................",
                "......KKKK......",
                ".....KDDDDK.....",
                "....KKKKKKKK....",
                "...KGGGGGGGGK...",
                "..KGGOGGGGOGGK..",
                ".KGGGGGGGGGGGGK.",
                ".KGGGOGGGGOGGGK.",
                "KGGGGGGGGGGGGGGK",
                "KGGGOGGGGGGOGGGK",
                "KGGGGGGGGGGGGGGK",
                "KGGGOGGGGGGOGGGK",
                ".KGGGGGGGGGGGGK.",
                "..KOOOOOOOOOOK..",
                "...KKKKKKKKKK...",
                "................",
            ],
            [
                "................",
                "......KKKK......",
                ".....KDDDDK.....",
                "....KKKKKKKK....",
                "...KGGYGGGGGGK..",
                "..KGGOGGYGGOGGK..",
                ".KGGYGGGGGGGGGK.",
                ".KGGGOGGYYOGGGK.",
                "KGGGGGGGGGGGGGGK",
                "KGGGOGGYGGOGGGGK",
                "KGGGGYGGGGGGGGGK",
                "KGGGOGGGGGGOGGGK",
                ".KGGYGGGGGGGGGK.",
                "..KOOOOOOOOOOK..",
                "...KKKKKKKKKK...",
                "................",
            ],
        ],
    },
    {
        "id": "trophy",
        "name": "Vault Trophy",
        "category": "items",
        "description": "Golden trophy — top genome of the campaign.",
        "frames": [
            [
                "................",
                "..KKKKKKKKKKKK..",
                ".KGGGGGGGGGGGGK.",
                "KGYYYYYYYYYYYGK.",
                "KGYGGGGGGGGGYGK.",
                "KGYGGGYYYGGGYGK.",
                "KGYGGYGGGYGGYGK.",
                "KGYGYGGGGGYGYGK.",
                "KGYGYGGGGGYGYGK.",
                "KGGYGGGGGGYGGGK.",
                ".KGGYYYYYYYGGK..",
                "..KGGGGGGGGGGK..",
                "...KKGGGGGGKK...",
                "....KKKKKKKK....",
                "...KKKKKKKKKK...",
                "..KKKKKKKKKKKK..",
            ],
            [
                "................",
                "..KKKKKKKKKKKK..",
                ".KGGGGGGGGGGGGK.",
                "KGYYYYYYYYYYYGK.",
                "KGYGGGGGGGGGYGK.",
                "KGYGGWYYYWGGYGK.",
                "KGYGWWGGGWWGYGK.",
                "KGYGYGGGGGYGYGK.",
                "KGYGYGGGGGYGYGK.",
                "KGGYGGGGGGYGGGK.",
                ".KGGYYYYYYYGGK..",
                "..KGGGGGGGGGGK..",
                "...KKGGGGGGKK...",
                "....KKKKKKKK....",
                "...KKKKKKKKKK...",
                "..KKKKKKKKKKKK..",
            ],
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def get_preset(preset_id: str) -> Optional[Dict]:
    """Return the full preset dict for *preset_id* or ``None`` if missing."""
    for p in SPRITE_PRESETS:
        if p["id"] == preset_id:
            return p
    return None


def preset_for_state(state: str) -> Dict:
    """Return the preset best matching engine *state* (always non-None)."""
    pid = STATE_TO_PRESET.get(state, "bull-trader")
    p = get_preset(pid)
    if p is None:
        p = SPRITE_PRESETS[0]
    return p


def frame_pixels(preset_id: str, frame_idx: int = 0) -> List[List[Optional[str]]]:
    """Return a 16x16 grid of (hex_color or None) for the given preset frame.

    >>> grid = frame_pixels("xau-gold", 0)
    >>> grid[3][8]   # central gold pixel
    '#fbbf24'
    """
    preset = get_preset(preset_id)
    if not preset:
        return [[None] * 16 for _ in range(16)]
    frames = preset["frames"]
    frame_idx = max(0, min(frame_idx, len(frames) - 1))
    lines = frames[frame_idx]

    grid: List[List[Optional[str]]] = []
    for y in range(16):
        row_chars = (lines[y] if y < len(lines) else ".").ljust(16, ".")[:16]
        row: List[Optional[str]] = []
        for x in range(16):
            ch = row_chars[x]
            row.append(PALETTE.get(ch))
        grid.append(row)
    return grid


def categories() -> List[str]:
    """Distinct sprite categories in order of declaration."""
    seen, out = set(), []
    for p in SPRITE_PRESETS:
        c = p["category"]
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def export_json(target: Optional[Path] = None) -> str:
    """Dump the whole palette + preset list as JSON (used by the HTML lab).

    If *target* is given, the JSON is also written to disk.
    """
    payload = {
        "palette": PALETTE,
        "state_to_preset": STATE_TO_PRESET,
        "presets": SPRITE_PRESETS,
    }
    s = json.dumps(payload, indent=2, ensure_ascii=False)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(s, encoding="utf-8")
    return s


def state_from_pnl(pnl: float, net_worth: float, *, daily_cap: float = 10.0,
                   hodl: bool = False) -> str:
    """Map a live PnL reading to a trader-state string the widget understands.

    The thresholds intentionally mirror the executor's safety cap so the
    mascot's mood matches the actual risk envelope of the worker.
    """
    if net_worth <= 0:
        return "liquidated"
    if hodl:
        return "hodl"
    if pnl <= -abs(daily_cap):
        return "panic"
    if net_worth > 0 and pnl >= net_worth * 0.05:
        return "big-profit"
    if pnl > 0:
        return "profit"
    if pnl < 0:
        return "loss"
    return "idle"


__all__ = [
    "PALETTE",
    "SPRITE_PRESETS",
    "STATE_TO_PRESET",
    "categories",
    "export_json",
    "frame_pixels",
    "get_preset",
    "preset_for_state",
    "state_from_pnl",
]


if __name__ == "__main__":  # pragma: no cover
    # Self-test + JSON dump
    print(f"R Native pixel_sprites — {len(SPRITE_PRESETS)} presets")
    for cat in categories():
        n = sum(1 for p in SPRITE_PRESETS if p["category"] == cat)
        print(f"  {cat:<12} {n} sprite(s)")
    out = Path(__file__).resolve().parent / "_pixel_sprites_dump.json"
    export_json(out)
    print(f"JSON atlas written to: {out}")
