# R Native — Launcher + Worker Architecture

> **Status**: SPEC (not yet implemented)
> **Goal**: Replace the current monolithic 1.3 GB single-process R Native with a 2-process design inspired by Algory.exe's parent+worker pattern.
> **Author**: Iteration response to user request (2026-05-23)

---

## 1. Why this exists

### Current state (monolithic)
- `python -m r_native.app` — single PySide6 process
- Everything in one address space: UI + GA engine + vault + MT5 IPC + Keras + TF
- **1329 MB RAM** observed after ~10 min of use
- If any subsystem crashes (e.g. MT5 IPC drop, OOM during GA campaign, Qt event-loop wedge) → **entire app dies**, user loses session state
- No way to update the worker without restarting the launcher

### Reference: Algory.exe (observed live)
| PID | Role | RAM | CPU after 10min |
|---|---|---|---|
| 19396 | Launcher (parent) | **8.9 MB** | 1.0s |
| 31720 | Worker (child of 19396) | **175.7 MB** | 197.6s |

Algory uses ~184 MB total. R Native uses 1329 MB. **~7× difference** for arguably similar functionality.

### Target after this work
- `RNativeLauncher.exe` (~30 MB RAM) — always-on, supervises the worker
- `RNativeWorker.exe` (~250 MB RAM) — replaceable, killable, restartable
- **Total ~280 MB** instead of 1.3 GB (~4.5× reduction)
- Worker crash ≠ app death — launcher restarts it within ~2s
- Hot-swap workers without losing tray icon / window position

---

## 2. Process responsibilities

### Launcher (`RNativeLauncher.exe`)
**Must do:**
- Start/stop/restart the worker subprocess
- Monitor worker heartbeat (TCP ping every 2s)
- Kill+respawn worker if heartbeat times out 3× consecutively (~6s dead)
- Provide a **tray icon** with menu: Show Worker · Restart Worker · Quit Both
- Show a **small status window** (200×80 px) with: worker PID, uptime, RAM, last heartbeat ts
- Persist user preferences (window pos, theme, auto-start) in `~/.r_native/launcher.json`
- Log all worker lifecycle events to `data/r_native/launcher.log`

**Must NOT do:**
- Load PySide6 widgets beyond tray + status window (keep < 50 MB)
- Touch MT5, GA engine, vault, or any FRIDAY service code
- Block the event loop on long ops (everything async)

**Stack:**
- PySide6 (QSystemTrayIcon + tiny QDialog only — no QMainWindow)
- `subprocess.Popen` for worker (with `creationflags=CREATE_NO_WINDOW`)
- `socket` (TCP client) for heartbeat polling
- Single-file, < 400 lines

### Worker (`RNativeWorker.exe`)
**Is exactly the current** `r_native/app.py` **plus**:
- Bind a TCP heartbeat server on `127.0.0.1:7711` (configurable)
- Respond to `GET /heartbeat` → `{ok: true, uptime, ram_mb, version}`
- Respond to `POST /shutdown` → graceful exit (saves state)
- Memory cleanup after each GA campaign — explicitly `del vault; gc.collect()`
- Optional: self-terminate after N campaigns (let launcher restart for a clean slate)

**Stack:**
- Existing `r_native/app.py` (PySide6 + MT5 + GA engine)
- Add a tiny `r_native/heartbeat_server.py` (Flask, runs in a daemon thread)

---

## 3. IPC contract

**Why TCP over a Unix-style mechanism:**
- Already familiar — `brain_server.py` uses Flask on `:5055`
- Cross-platform (we may want a Mac port)
- Trivial to debug with `curl`
- No new dependencies

**Port allocation:**
- `127.0.0.1:5055` — brain_server (existing)
- `127.0.0.1:7711` — RNative Worker heartbeat (new)
- `127.0.0.1:7712` — RNative Worker control RPC (new, optional)

**Heartbeat protocol:**
```
GET http://127.0.0.1:7711/heartbeat
→ { "ok": true,
    "uptime_sec": 123,
    "ram_mb": 248,
    "version": "1.2.0",
    "active_campaign": null,
    "vault_size": 42 }
```

**Launcher polling cadence:**
- Every 2.0s, GET /heartbeat with 1.5s timeout
- 3 consecutive failures → declare worker dead
- Spawn replacement, wait up to 30s for first successful heartbeat
- If replacement fails 3× in 1 minute → show error dialog, stop trying

**Graceful shutdown:**
```
POST http://127.0.0.1:7711/shutdown
→ { "ok": true, "saving": "vault" }
... worker saves state, exits within 10s ...
```

---

## 4. Build & distribution

### Two .exes from one repo
```
dist/RNative/
├── RNativeLauncher.exe    ← entry point (user double-clicks this)
├── RNativeWorker.exe      ← spawned by launcher
└── _internal/             ← shared Qt/Python runtime
```

**Why share `_internal/`:**
- PyInstaller multi-binary mode allows one bundled `_internal/` for both executables
- Saves ~200 MB (Qt + Python runtime not duplicated)
- Use PyInstaller spec file with multiple `EXE()` blocks

### Build script changes
- `r_native/build_exe.py` becomes `r_native/build_exes.py` (plural)
- Generates a single `.spec` file with two `EXE()` definitions
- Both reference same `Analysis` and `PYZ` for bundle sharing

---

## 5. Memory cleanup strategy

The 1.3 GB problem comes from:
- **Vault accumulation**: GA campaigns produce 200-300 genome dicts × ~3 MB each = 600-900 MB held in `self.vault` lists
- **MT5 cached bars**: `mt5.copy_rates_from_pos` calls accumulate Python objects
- **Qt model views**: TableWidget rows + DNA widget genes never released

**Worker mitigations:**
1. After each GA campaign — write vault to JSONL, then `vault = []; gc.collect()`
2. Limit MT5 bar cache to last 5 symbols, evict LRU
3. Optionally: worker self-terminates if `psutil.Process().memory_info().rss > 500 MB`, launcher restarts

**Expected steady-state:**
- Worker idle: 150-200 MB
- Worker during GA: 300-400 MB (campaign in flight)
- Worker after GA + cleanup: back to 150-200 MB

---

## 6. Resilience features

| Scenario | Current behavior | New behavior |
|---|---|---|
| Qt event loop wedges | UI freezes, no recovery | Launcher detects heartbeat timeout, restarts worker |
| MT5 IPC drops | Trading halts, manual restart | Worker can request restart from launcher via control RPC |
| OOM during GA | Process crashes, lose vault | Launcher restarts; vault was already persisted to JSONL |
| User wants to update | Quit + relaunch entire app | `POST /shutdown` + launcher spawns new worker.exe |
| Worker leaks memory | Linear growth to OOM | Auto-restart at 500 MB threshold |

---

## 7. Implementation phases

Suggested breakdown (each ~1-2h work):

### Phase 1: Worker heartbeat server (lowest risk, no UI changes)
- Add `r_native/heartbeat_server.py` (Flask in daemon thread)
- Add startup hook in `r_native/app.py` to launch it on `:7711`
- Test: `curl http://127.0.0.1:7711/heartbeat` returns ok
- **Backward-compatible** — current app keeps working

### Phase 2: Launcher process (skeleton)
- New `r_native_launcher/launcher.py` — tray + status window + subprocess.Popen
- Polls heartbeat, prints status
- Restarts on death
- **Can run side-by-side with current monolith for testing**

### Phase 3: Two-exe build
- Refactor `r_native/build_exe.py` into multi-EXE spec
- Bundle shared `_internal/`
- Output: `RNativeLauncher.exe` + `RNativeWorker.exe`

### Phase 4: Memory cleanup in worker
- After GA campaign: `vault = []; gc.collect()`
- MT5 bar cache LRU
- Optional auto-restart threshold

### Phase 5: Polish & migration
- Update README / install instructions
- Migrate user preferences from old layout
- Deprecate old monolithic .exe

### Phase 6 (optional): Hot-swap workers
- Launcher checks for `RNativeWorker.exe.new` on disk
- If newer than running worker → graceful shutdown + swap + restart
- Enables zero-touch updates

---

## 8. Risks & open questions

**Risk**: Tray icon usability on Windows depends on user not collapsing the tray overflow. Solution: also show a tiny always-on-top status window (can be hidden).

**Risk**: Multi-EXE PyInstaller setup is finicky. Solution: prototype Phase 3 first as a smoke test before committing to the full design.

**Open**: Should `brain_server.py` also become a child of the launcher? Currently it's started separately by `start_friday_trading_full.ps1`. Adding it under launcher supervision would give the same crash-resilience to brain_server. Defer to user.

**Open**: What's the launcher's behavior when MT5 itself isn't running? Should it offer to start MT5? Algory presumably does this — worth observing.

---

## 9. Estimated impact

**Code added**: ~600 lines (launcher + heartbeat + build refactor)
**Code modified**: ~50 lines in `r_native/app.py` (heartbeat hook, cleanup hooks)
**Effort**: ~6-10 hours total across all 5 mandatory phases (phase 6 optional)
**RAM saving**: 1300 MB → 280 MB (steady-state, observed Algory baseline)
**New failure modes**: Launcher↔worker IPC can fail; mitigated by heartbeat + auto-restart
**User-facing change**: One new tray icon. Existing UI unchanged.
