"""Runtime paths for Qader.

The app uses project-relative paths during development and EXE-relative paths
when frozen, so it can run on another Windows device without old machine paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    override = os.environ.get("QADER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return app_root() / "data" / "qader"


def dna_dir() -> Path:
    return data_dir() / "dna"


def logs_dir() -> Path:
    return app_root() / "logs"


def reports_dir() -> Path:
    return app_root() / "reports"


def config_dir() -> Path:
    return app_root() / "config"


def ensure_runtime_dirs() -> None:
    for path in (data_dir(), dna_dir(), logs_dir(), reports_dir(), config_dir()):
        path.mkdir(parents=True, exist_ok=True)

