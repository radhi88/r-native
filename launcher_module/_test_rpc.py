"""H.6 end-to-end RPC smoke test. Spawn fake worker, send /shutdown via RPC, verify clean exit."""
import sys
import time
import subprocess
import urllib.request

PROJECT = r"C:\Users\Radhi\MT5"

WORKER_CODE = r"""
import sys, time
sys.path.insert(0, r"{root}")
from r_native import heartbeat_server
done = [False]
def shutdown():
    print("[fake-worker] shutdown_hook fired", flush=True)
    done[0] = True
heartbeat_server.start(port=7714, shutdown_hook=shutdown,
                       state_getter=lambda: {{"fake": True}})
print("[fake-worker] running, awaiting RPC", flush=True)
deadline = time.time() + 20
while not done[0] and time.time() < deadline:
    time.sleep(0.2)
print("[fake-worker] clean exit", flush=True)
""".format(root=PROJECT)

p = subprocess.Popen([sys.executable, "-c", WORKER_CODE],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print(f"[test] spawned fake worker PID {p.pid}")
time.sleep(1.8)

# Verify heartbeat works
hb = urllib.request.urlopen("http://127.0.0.1:7714/heartbeat", timeout=2).read().decode()
print(f"[test] heartbeat OK: {hb[:160]}")

# Send /shutdown via RPC
req  = urllib.request.Request("http://127.0.0.1:7714/shutdown", method="POST")
resp = urllib.request.urlopen(req, timeout=2).read().decode()
print(f"[test] /shutdown response: {resp}")

# Verify clean exit
for _ in range(20):
    if p.poll() is not None:
        break
    time.sleep(0.3)

if p.poll() is None:
    print("[test] FAIL — worker did not exit after /shutdown")
    p.kill()
    sys.exit(1)
else:
    print(f"[test] PASS — worker exited cleanly (code {p.returncode})")

out, _ = p.communicate(timeout=5)
print("--- worker stdout ---")
print(out)
