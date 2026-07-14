from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


AUTO_SYMBOL_TOKENS = {"*", "all", "auto", "available", "market", "mt5"}

PRIORITY_SYMBOLS = (
    "XAUUSDm",
    "XAGUSDm",
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "USDCHFm",
    "USDCADm",
    "AUDUSDm",
    "NZDUSDm",
    "EURJPYm",
    "GBPJPYm",
    "BTCUSDm",
    "ETHUSDm",
    "USOILm",
    "UKOILm",
)


class MT5SymbolError(RuntimeError):
    pass


def csv_symbols(value: str | None) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()

    for raw in str(value or "").replace(";", ",").split(","):
        symbol = raw.strip()
        if not symbol:
            continue

        key = symbol.upper()
        if key in seen:
            continue

        seen.add(key)
        symbols.append(symbol)

    return symbols


def wants_all_symbols(value: str | None) -> bool:
    parts = {
        part.strip().lower()
        for part in str(value or "").replace(";", ",").split(",")
        if part.strip()
    }
    return bool(parts & AUTO_SYMBOL_TOKENS)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _asdict(item: Any) -> dict[str, Any]:
    if hasattr(item, "_asdict"):
        try:
            return dict(item._asdict())
        except Exception:
            return {}
    return {}


def _field(item: Any, key: str, default: Any = None) -> Any:
    data = _asdict(item)
    if key in data:
        return data.get(key)
    return getattr(item, key, default)


def _last_error(mt5_module: Any) -> Any:
    try:
        return mt5_module.last_error()
    except Exception as exc:
        return f"last_error unavailable: {exc}"


def _error_text(error: Any) -> str:
    return str(error or "")


def _is_incompatible_mt5_error(error: Any) -> bool:
    text = _error_text(error).lower()
    return (
        "incompatible versions" in text
        or "please install the latest version" in text
        or "terminal: incompatible" in text
    )


def _sort_key(item: Any, priority: dict[str, int]) -> tuple[int, str, str]:
    name = str(_field(item, "name", "") or "")
    path = str(_field(item, "path", "") or "")
    return (priority.get(name.upper(), 10_000), path, name)


def _ensure_mt5_initialized(mt5_module: Any) -> None:
    """
    Best-effort initializer.

    If main.py already initialized MT5, this does nothing.
    If not initialized, it tries FRIDAY_MT5_PATH first, then normal initialize().
    """

    try:
        info = mt5_module.terminal_info()
        if info is not None:
            return
    except Exception:
        pass

    mt5_path = (
        os.getenv("FRIDAY_MT5_PATH")
        or os.getenv("MT5_PATH")
        or os.getenv("METATRADER5_PATH")
        or ""
    ).strip().strip('"')

    try:
        if mt5_path:
            ok = mt5_module.initialize(path=mt5_path)
        else:
            ok = mt5_module.initialize()
    except Exception as exc:
        raise MT5SymbolError(f"MT5 initialize raised exception: {exc}") from exc

    if not ok:
        error = _last_error(mt5_module)
        raise MT5SymbolError(
            "MT5 initialize failed.\n"
            f"MT5 last_error: {error}\n\n"
            "Fix:\n"
            "1) Open the correct MT5 terminal manually.\n"
            "2) Login to the account.\n"
            "3) Update MT5 terminal.\n"
            "4) Update Python package:\n"
            "   python -m pip install --upgrade --force-reinstall MetaTrader5\n"
            "5) If you have more than one MT5 terminal, set:\n"
            r'   $env:FRIDAY_MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"'
        )


def _safe_symbol_select(mt5_module: Any, symbol: str, select: bool = True) -> bool:
    if not select:
        return True

    try:
        return bool(mt5_module.symbol_select(symbol, True))
    except Exception:
        return False


def _select_symbols_best_effort(
    symbols: list[str],
    mt5_module: Any | None,
    *,
    select: bool = True,
    strict_select: bool | None = None,
) -> list[str]:
    """
    For explicit/default symbols:
    - Try symbol_select if MT5 is available.
    - Do not return empty just because symbol_select failed, unless strict mode is enabled.
    """

    if strict_select is None:
        strict_select = _env_bool("FRIDAY_STRICT_SYMBOL_SELECT", False)

    symbols = csv_symbols(",".join(symbols))
    if not symbols:
        return []

    if not select or mt5_module is None:
        return symbols

    selected: list[str] = []
    failed: list[str] = []

    for symbol in symbols:
        if _safe_symbol_select(mt5_module, symbol, select=True):
            selected.append(symbol)
        else:
            failed.append(symbol)

    if selected:
        return selected

    if strict_select:
        raise MT5SymbolError(
            "None of the requested MT5 symbols could be selected.\n"
            f"Requested: {symbols}\n"
            f"MT5 last_error: {_last_error(mt5_module)}"
        )

    # Non-strict fallback: keep symbols so the caller can continue.
    return symbols


def _limit_symbols(symbols: list[str], limit: int | None) -> list[str]:
    if limit and limit > 0:
        return symbols[:limit]
    return symbols


def _symbols_cache_path() -> Path:
    raw = os.getenv("FRIDAY_SYMBOLS_CACHE", "").strip().strip('"')
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "runtime" / "friday_symbols_cache.json"


def _read_cached_symbols() -> list[str]:
    try:
        data = json.loads(_symbols_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return []

    raw_symbols = data.get("symbols", data) if isinstance(data, dict) else data
    if not isinstance(raw_symbols, list):
        return []

    return csv_symbols(",".join(str(symbol) for symbol in raw_symbols))


def _write_cached_symbols(symbols: list[str]) -> None:
    symbols = csv_symbols(",".join(symbols))
    if not symbols:
        return

    path = _symbols_cache_path()
    payload = {
        "count": len(symbols),
        "symbols": symbols,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def _format_symbols_for_log(symbols: list[str]) -> str:
    preview = symbols[:30]
    suffix = "" if len(symbols) <= len(preview) else f", ... +{len(symbols) - len(preview)} more"
    return ", ".join(preview) + suffix


def _symbol_discovery_fallback(
    mt5_module: Any | None,
    *,
    select: bool = True,
    limit: int | None = None,
    reason: Any = None,
) -> list[str]:
    raw = os.getenv("FRIDAY_SYMBOLS_FALLBACK", "")
    source = "FRIDAY_SYMBOLS_FALLBACK"
    symbols = csv_symbols(raw)

    if not symbols:
        symbols = _read_cached_symbols()
        source = "cached MT5 symbols"

    if not symbols:
        symbols = csv_symbols(os.getenv("FRIDAY_DEFAULT_SYMBOLS", ""))
        source = "FRIDAY_DEFAULT_SYMBOLS"

    if not symbols:
        symbols = list(PRIORITY_SYMBOLS)
        source = "priority fallback"

    symbols = _select_symbols_best_effort(symbols, mt5_module, select=select)
    symbols = _limit_symbols(symbols, limit)

    if symbols:
        print(
            "[FRIDAY] MT5 auto symbol discovery failed; "
            f"using {source} ({len(symbols)}): {_format_symbols_for_log(symbols)}"
        )
        if reason:
            print(f"[FRIDAY] MT5 discovery error: {reason}")

    return symbols


def _build_symbols_get_error(mt5_module: Any) -> MT5SymbolError:
    error = _last_error(mt5_module)

    if _is_incompatible_mt5_error(error):
        return MT5SymbolError(
            "MT5 symbols_get failed because the MT5 terminal and Python MetaTrader5 package "
            "are incompatible.\n\n"
            f"MT5 last_error: {error}\n\n"
            "Immediate workaround:\n"
            "Run the executor with explicit symbols instead of auto-discovery:\n"
            "  python friday_touch_demo_executor.py --symbols XAUUSDm\n\n"
            "Permanent fix:\n"
            "  cd C:\\Users\\Radhi\\MT5\n"
            "  .\\.venv\\Scripts\\activate\n"
            "  Get-Process terminal64,terminal -ErrorAction SilentlyContinue | Stop-Process -Force\n"
            "  python -m pip install --upgrade --force-reinstall MetaTrader5\n\n"
            "Then update MT5 terminal itself:\n"
            "  MT5 -> Help -> Check Desktop Updates -> Latest Release\n\n"
            "If you have multiple MT5 installations, set the exact terminal path:\n"
            r'  $env:FRIDAY_MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"'
        )

    return MT5SymbolError(
        "MT5 symbols_get failed.\n"
        f"MT5 last_error: {error}\n\n"
        "Use explicit symbols to bypass auto-discovery:\n"
        "  python friday_touch_demo_executor.py --symbols XAUUSDm\n"
    )


def discover_mt5_symbols(
    mt5_module: Any | None = None,
    *,
    visible_only: bool | None = None,
    tradable_only: bool = True,
    select: bool = True,
    limit: int | None = None,
) -> list[str]:
    """
    Discover symbols from MT5 Market Watch / terminal.

    Note:
    This uses mt5.symbols_get(), so it requires compatible MT5 terminal + Python package.
    If your terminal/package versions are incompatible, use explicit symbols instead:
        --symbols XAUUSDm
    """

    if mt5_module is None:
        import MetaTrader5 as mt5_module

    _ensure_mt5_initialized(mt5_module)

    if visible_only is None:
        visible_only = _env_bool("FRIDAY_SYMBOLS_VISIBLE_ONLY", False)

    if limit is None:
        limit = _env_int("FRIDAY_MAX_SYMBOLS", 0)

    try:
        raw_symbols = mt5_module.symbols_get()
    except Exception as exc:
        fallback = _symbol_discovery_fallback(
            mt5_module,
            select=select,
            limit=limit,
            reason=exc,
        )
        if fallback:
            return fallback
        raise MT5SymbolError(f"MT5 symbols_get raised exception: {exc}") from exc

    if raw_symbols is None:
        fallback = _symbol_discovery_fallback(
            mt5_module,
            select=select,
            limit=limit,
            reason=_last_error(mt5_module),
        )
        if fallback:
            return fallback
        raise _build_symbols_get_error(mt5_module)

    priority = {name.upper(): idx for idx, name in enumerate(PRIORITY_SYMBOLS)}
    selected: list[str] = []
    seen: set[str] = set()

    for info in sorted(raw_symbols, key=lambda item: _sort_key(item, priority)):
        name = str(_field(info, "name", "") or "").strip()
        if not name:
            continue

        key = name.upper()
        if key in seen:
            continue

        visible = bool(_field(info, "visible", False))
        trade_mode = int(_field(info, "trade_mode", 0) or 0)

        if visible_only and not visible:
            continue

        if tradable_only and trade_mode <= 0:
            continue

        if select and not _safe_symbol_select(mt5_module, name, select=True):
            continue

        seen.add(key)
        selected.append(name)

        if limit and len(selected) >= limit:
            break

    if not selected:
        fallback = _symbol_discovery_fallback(
            mt5_module,
            select=select,
            limit=limit,
            reason=_last_error(mt5_module),
        )
        if fallback:
            return fallback

        raise MT5SymbolError(
            "No tradable MT5 symbols were discovered.\n"
            "Try explicit symbols:\n"
            "  python friday_touch_demo_executor.py --symbols XAUUSDm\n"
            f"MT5 last_error: {_last_error(mt5_module)}"
        )

    _write_cached_symbols(selected)
    return selected


def resolve_symbols(
    value: str | None,
    mt5_module: Any | None = None,
    *,
    default: list[str] | tuple[str, ...] | None = None,
    visible_only: bool | None = None,
    tradable_only: bool = True,
    select: bool = True,
    limit: int | None = None,
) -> list[str]:
    """
    Symbol resolver behavior:

    1) If value/env has auto/all/*:
       Uses MT5 symbols_get discovery.

    2) If value/env has explicit symbols:
       Uses those symbols.

    3) If no value/env/default:
       Uses PRIORITY_SYMBOLS by default to avoid symbols_get crash.
       This is safer for your setup because auto-discovery is failing due MT5 version mismatch.
    """

    raw = value if value not in (None, "") else os.getenv("FRIDAY_SYMBOLS", "")

    # auto/all/* means: discover all available from MT5
    if wants_all_symbols(raw):
        return discover_mt5_symbols(
            mt5_module,
            visible_only=visible_only,
            tradable_only=tradable_only,
            select=select,
            limit=limit,
        )

    # explicit symbols from CLI/env
    symbols = csv_symbols(raw)
    if symbols:
        return _select_symbols_best_effort(
            symbols,
            mt5_module,
            select=select,
        )

    # caller-provided default
    if default:
        return _select_symbols_best_effort(
            list(default),
            mt5_module,
            select=select,
        )

    # safer default: do NOT call symbols_get unless user requested auto/all/*
    return _select_symbols_best_effort(
        list(PRIORITY_SYMBOLS),
        mt5_module,
        select=select,
    )
