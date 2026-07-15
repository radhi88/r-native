"""Local company-logo assets: ticker -> domain map + data-URL helpers.

Logos are plain files in <project root>/assets/logos/<TICKER>.(svg|png|ico|jpg),
fetched once by scripts/fetch_logos.py (run manually). This module only reads
local files — no network — so pages render instantly and offline.

Public API:
  TICKER_DOMAINS                dict[ticker, company domain]
  ASSETS_DIR                    pathlib.Path of the logo folder
  logo_data_url(ticker) -> str | None   base64 data URL for <img src=...>
  logo_html(ticker, size=28) -> str     inline <img> tag, '' when absent
"""
from __future__ import annotations

import base64
import functools
import pathlib

ASSETS_DIR = pathlib.Path(__file__).resolve().parents[1] / "assets" / "logos"

# Extension preference (svg first) and mime types for data URLs.
_EXT_ORDER: tuple[str, ...] = (".svg", ".png", ".ico", ".jpg")
_MIME: dict[str, str] = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
}

# ~137 top US tickers: full S&P 100, a few other mega-cap favorites, the 11
# SPDR sector ETFs, and major broad-market ETFs mapped to their issuer's site.
TICKER_DOMAINS: dict[str, str] = {
    # --- Mega-cap tech / communication ---
    "AAPL": "apple.com",
    "MSFT": "microsoft.com",
    "GOOGL": "abc.xyz",
    "GOOG": "abc.xyz",
    "AMZN": "amazon.com",
    "NVDA": "nvidia.com",
    "META": "meta.com",
    "TSLA": "tesla.com",
    "AVGO": "broadcom.com",
    "ORCL": "oracle.com",
    "CRM": "salesforce.com",
    "ADBE": "adobe.com",
    "NFLX": "netflix.com",
    # --- Semiconductors & hardware ---
    "AMD": "amd.com",
    "INTC": "intel.com",
    "QCOM": "qualcomm.com",
    "TXN": "ti.com",
    "MU": "micron.com",
    "ANET": "arista.com",
    "CSCO": "cisco.com",
    "IBM": "ibm.com",
    # --- Software / internet ---
    "NOW": "servicenow.com",
    "INTU": "intuit.com",
    "PANW": "paloaltonetworks.com",
    "PLTR": "palantir.com",
    "UBER": "uber.com",
    "ABNB": "airbnb.com",
    "PYPL": "paypal.com",
    "BKNG": "bookingholdings.com",
    # --- Financials ---
    "BRK-B": "berkshirehathaway.com",
    "JPM": "jpmorganchase.com",
    "V": "visa.com",
    "MA": "mastercard.com",
    "BAC": "bankofamerica.com",
    "WFC": "wellsfargo.com",
    "GS": "goldmansachs.com",
    "MS": "morganstanley.com",
    "C": "citigroup.com",
    "AXP": "americanexpress.com",
    "BLK": "blackrock.com",
    "SCHW": "schwab.com",
    "USB": "usbank.com",
    "COF": "capitalone.com",
    "BK": "bny.com",
    "SPGI": "spglobal.com",
    "MET": "metlife.com",
    "AIG": "aig.com",
    # --- Health care ---
    "LLY": "lilly.com",
    "UNH": "unitedhealthgroup.com",
    "JNJ": "jnj.com",
    "ABBV": "abbvie.com",
    "MRK": "merck.com",
    "PFE": "pfizer.com",
    "TMO": "thermofisher.com",
    "ABT": "abbott.com",
    "DHR": "danaher.com",
    "AMGN": "amgen.com",
    "ISRG": "intuitive.com",
    "GILD": "gilead.com",
    "BMY": "bms.com",
    "CVS": "cvshealth.com",
    "MDT": "medtronic.com",
    # --- Consumer & retail ---
    "WMT": "walmart.com",
    "COST": "costco.com",
    "HD": "homedepot.com",
    "PG": "pg.com",
    "KO": "coca-colacompany.com",
    "PEP": "pepsico.com",
    "MCD": "mcdonalds.com",
    "NKE": "nike.com",
    "SBUX": "starbucks.com",
    "TGT": "target.com",
    "LOW": "lowes.com",
    "DIS": "disney.com",
    "CMCSA": "comcast.com",
    "T": "att.com",
    "VZ": "verizon.com",
    "TMUS": "t-mobile.com",
    "PM": "pmi.com",
    "MO": "altria.com",
    "MDLZ": "mondelezinternational.com",
    "CL": "colgatepalmolive.com",
    "KHC": "kraftheinzcompany.com",
    # --- Energy ---
    "XOM": "exxonmobil.com",
    "CVX": "chevron.com",
    "COP": "conocophillips.com",
    # --- Industrials / materials / autos ---
    "GE": "ge.com",
    "HON": "honeywell.com",
    "CAT": "caterpillar.com",
    "DE": "deere.com",
    "BA": "boeing.com",
    "LMT": "lockheedmartin.com",
    "RTX": "rtx.com",
    "GD": "gd.com",
    "UPS": "ups.com",
    "FDX": "fedex.com",
    "UNP": "up.com",
    "MMM": "3m.com",
    "EMR": "emerson.com",
    "LIN": "linde.com",
    "GM": "gm.com",
    "F": "ford.com",
    "ACN": "accenture.com",
    # --- Utilities / real estate / media ---
    "NEE": "nexteraenergy.com",
    "DUK": "duke-energy.com",
    "SO": "southerncompany.com",
    "AMT": "americantower.com",
    "SPG": "simon.com",
    "CHTR": "charter.com",
    # --- SPDR sector ETFs (State Street) ---
    "XLK": "ssga.com",
    "XLF": "ssga.com",
    "XLV": "ssga.com",
    "XLE": "ssga.com",
    "XLI": "ssga.com",
    "XLY": "ssga.com",
    "XLP": "ssga.com",
    "XLU": "ssga.com",
    "XLRE": "ssga.com",
    "XLB": "ssga.com",
    "XLC": "ssga.com",
    # --- Broad-market / thematic ETFs by issuer ---
    "SPY": "ssga.com",
    "DIA": "ssga.com",
    "GLD": "ssga.com",
    "QQQ": "invesco.com",
    "VOO": "vanguard.com",
    "VTI": "vanguard.com",
    "VIG": "vanguard.com",
    "BND": "vanguard.com",
    "VNQ": "vanguard.com",
    "IVV": "ishares.com",
    "IWM": "ishares.com",
    "AGG": "ishares.com",
    "TLT": "ishares.com",
    "SLV": "ishares.com",
    "SCHD": "schwab.com",
    "SMH": "vaneck.com",
    "ARKK": "ark-funds.com",
    "JEPI": "jpmorgan.com",
}


@functools.lru_cache(maxsize=512)
def logo_data_url(ticker: str) -> str | None:
    """Base64 data URL for the ticker's local logo file, or None when absent.

    Looks for <TICKER>.(svg|png|ico|jpg) in ASSETS_DIR (svg preferred).
    Never raises: unreadable/empty files simply return None.
    """
    tk = str(ticker).upper().strip()
    if not tk:
        return None
    for ext in _EXT_ORDER:
        path = ASSETS_DIR / f"{tk}{ext}"
        try:
            if not path.is_file():
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if not data:
            continue
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{_MIME[ext]};base64,{b64}"
    return None


def logo_html(ticker: str, size: int = 28) -> str:
    """Inline <img> tag for the ticker's logo, or '' when no logo file exists.

    Safe to drop into st.markdown(..., unsafe_allow_html=True).
    """
    url = logo_data_url(ticker)
    if not url:
        return ""
    return (
        f'<img src="{url}" width="{int(size)}" '
        'style="vertical-align:middle;border-radius:4px">'
    )
