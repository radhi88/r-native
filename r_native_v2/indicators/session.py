"""indicators/session.py — global trading session windows + suitability.

Derived from M1 best-practices research (cycle 39):
  • London-NY overlap (13:00-17:00 UTC) = the prime M1 scalp window
  • Asian session (00:00-07:00 UTC) = M15+ only, M1 too thin
  • London open (08:00-12:00 UTC) = M1 OK but spreads wider
  • NY post-overlap (17:00-22:00 UTC) = M1 OK with caution
  • Weekend / Friday close = no trading

Each session gets a SUITABILITY score per TF — used by the council to
decide whether the lower-TF entry is appropriate right now.
"""
from __future__ import annotations
from datetime import datetime, time, timezone
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionVerdict:
    name:        str          # "ASIAN" / "LONDON" / "NY_OVERLAP" / "NY_LATE" / "CLOSED"
    m1_ok:       bool         # is M1 entry advisable right now?
    m5_ok:       bool
    m15_ok:      bool
    confidence:  int          # 0-100 confidence in the session call
    reason:      str


def classify(now_utc: datetime | None = None) -> SessionVerdict:
    """Return today's effective trading session for a given UTC time."""
    now = now_utc or datetime.now(timezone.utc)
    wd = now.weekday()          # Mon=0 .. Sun=6
    hr = now.hour
    mn = now.minute

    # Weekend
    if wd == 5:   # Saturday: FX markets closed all day (closed since Fri 22:00 UTC)
        return SessionVerdict("CLOSED", False, False, False, 100,
                              "Saturday — market closed")
    if wd == 6 and hr < 22:   # Sunday before the 22:00 UTC open
        return SessionVerdict("CLOSED", False, False, False, 100,
                              "Sunday pre-open — market opens 22:00 UTC")
    # Friday close window — high gap risk
    if wd == 4 and hr >= 21:
        return SessionVerdict("CLOSED", False, False, True, 90,
                              "Friday 21:00+ UTC — pre-weekend close")
    # FIX: Sun 22:00+ and ALL of Mon–Fri fall through to the hourly logic below
    # (was wrongly CLOSED all Sunday + Monday<22:00, losing Sun-night + all Monday).

    # Active sessions (Mon afternoon → Fri afternoon)
    # NY overlap 13:00-17:00 UTC — the prime M1 scalp window
    if 13 <= hr < 17:
        return SessionVerdict("NY_OVERLAP", True, True, True, 100,
                              "London-NY overlap — peak liquidity, M1 ideal")
    # London 08:00-13:00 UTC
    if 8 <= hr < 13:
        return SessionVerdict("LONDON", True, True, True, 85,
                              "London session — M1 OK, spreads moderate")
    # NY late 17:00-21:00 UTC
    if 17 <= hr < 21:
        return SessionVerdict("NY_LATE", True, True, True, 75,
                              "NY post-overlap — M1 OK but momentum fading")
    # Asian 22:00-08:00 UTC
    if (hr >= 22) or (hr < 8):
        return SessionVerdict("ASIAN", False, False, True, 90,
                              "Asian session — too thin for M1/M5 scalps")
    # 21:00-22:00 transition
    return SessionVerdict("TRANSITION", False, True, True, 60,
                          "NY closing → Asian opening — avoid M1")


# News-blackout windows are handled separately by the news_blocker agent
# (kept independent so unrelated genomes still see a clean session call).

if __name__ == "__main__":
    v = classify()
    print(f"NOW = {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print(f"session = {v.name}  m1={v.m1_ok} m5={v.m5_ok} m15={v.m15_ok}  "
          f"confidence={v.confidence}%  reason={v.reason}")
