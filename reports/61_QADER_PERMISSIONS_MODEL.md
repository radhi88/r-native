# Report 61 - Qader Permissions Model

Generated: 2026-05-14

## Permissions

Stored in:

```text
data/qader/permissions.json
```

| Permission | Default | Notes |
|---|---:|---|
| `can_read_mt5` | false | Required for MT5 read-only bars/account status |
| `can_scan_market` | false | Required for scanner actions |
| `can_run_dry_run` | false | Required for fixed dry-run cycles |
| `can_run_demo_controlled` | false | Dangerous; confirmation required |
| `can_place_live_orders` | false | Locked in this build |
| `can_use_microphone` | false | Required for STT |
| `can_use_speaker` | false | Required for TTS |
| `can_save_memory` | true | Stores preferences only |
| `can_modify_strategy_dna` | false | Required for approved genome changes |
| `can_write_reports` | true | Allows report output |
| `can_archive_files` | false | Only for future safe archive workflows |
| `can_apply_code_updates` | false | Dangerous; approval required |

## Guard Implementation

`src/qader_app/assistant/permissions_guard.py`

Every checked action logs to:

```text
logs/qader_audit.jsonl
```

Denied actions return a user-facing reason and do not execute.

## Locked Live Trading

`can_place_live_orders` is forcibly set to `false` by `PermissionsStore`, even if a user or imported file tries to set it to true.

Live trading was not enabled, and no code path in Qader requests it.

