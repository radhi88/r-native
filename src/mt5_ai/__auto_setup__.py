#!/usr/bin/env python3
"""Auto-execute MT5 setup on import"""
import os
import pathlib

base = pathlib.Path(r'C:\Users\Radhi\MT5\src\mt5_ai')
dirs = ['strategies', 'learning', 'genetics', 'integrations', 'interfaces', 'utils']

for d in dirs:
    (base / d).mkdir(parents=True, exist_ok=True)

# Write status
status_file = pathlib.Path(r'C:\Users\Radhi\MT5\setup_status.txt')
with open(status_file, 'w') as f:
    f.write("MT5 AI Directory Setup Status\n")
    f.write("=" * 50 + "\n\n")
    for d in dirs:
        path = base / d
        exists = path.is_dir()
        f.write(f"{'✓' if exists else '✗'} {d} - {'CREATED' if exists else 'FAILED'}\n")

print("Setup completed. Status written to setup_status.txt")
