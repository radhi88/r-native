"""Full Windows device control for FRIDAY voice assistant."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import log_event


ROOT = Path(__file__).resolve().parents[3]

_APP_MAP: dict[str, str] = {
    # Browsers
    "chrome": "chrome",        "كروم": "chrome",
    "edge": "msedge",          "إيدج": "msedge",   "ايدج": "msedge",
    "firefox": "firefox",      "فايرفوكس": "firefox",
    "متصفح": "msedge",         "المتصفح": "msedge",  "browser": "msedge",
    # System
    "notepad": "notepad",      "مفكرة": "notepad",   "المفكرة": "notepad",
    "calc": "calc",            "حاسبة": "calc",       "آلة حاسبة": "calc",
    "explorer": "explorer",    "ملفات": "explorer",   "الملفات": "explorer",
    "taskmgr": "taskmgr",      "مدير المهام": "taskmgr",
    "powershell": "powershell",
    "cmd": "cmd",
    # MT5
    "mt5": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "metatrader": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "ميتاتريدر": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "ترمنال": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "الترمنال": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    # FRIDAY dashboards
    "dashboard": "http://127.0.0.1:8844",
    "داشبورد": "http://127.0.0.1:8844",
    "الداشبورد": "http://127.0.0.1:8844",
    "داشبورت": "http://127.0.0.1:8844",
    "الداشبورت": "http://127.0.0.1:8844",
    "لوحة التحكم": "http://127.0.0.1:8844",
    "الدماغ": "http://127.0.0.1:8844",
    "الشات": "http://127.0.0.1:8811",
    "chat": "http://127.0.0.1:8811",
    "agents": "http://127.0.0.1:8833",
    "الوكلاء": "http://127.0.0.1:8833",
}

_FRIDAY_SCRIPTS = [
    "friday_indicator_feature_engine", "friday_feature_outcome_learner",
    "friday_trade_outcome_learner", "friday_local_gateway",
    "friday_chat_app", "friday_scalper_live_dashboard",
    "friday_agents_browser", "friday_live_brain_state",
    "friday_autopilot_supervisor", "friday_realtime_scalper_demo_executor",
    "friday_touch_demo_executor", "friday_demo_position_governor_v2",
    "friday_orderflow_feature_engine",
]

_SET_VOLUME_PS = r"""
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorCls {}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    void _VG0();
    [return:MarshalAs(UnmanagedType.Interface)] object GetDefaultAudioEndpoint(int df, int role);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    [return:MarshalAs(UnmanagedType.Interface)] object Activate(ref Guid iid, uint clsctx, IntPtr p);
}
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    void _R0(); void _R1(); void _R2(); void _R3(); void _R4(); void _R5();
    int SetMasterVolumeLevelScalar(float level, IntPtr ctx);
}
public class WinVol {
    public static void Set(float pct) {
        var en = (IMMDeviceEnumerator)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")));
        var dev = (IMMDevice)en.GetDefaultAudioEndpoint(0,1);
        var iid = new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
        var vol = (IAudioEndpointVolume)dev.Activate(ref iid, 23, IntPtr.Zero);
        vol.SetMasterVolumeLevelScalar(pct, IntPtr.Zero);
    }
}
"@ -ErrorAction SilentlyContinue
[WinVol]::Set({pct}f)
"""


def _ps(cmd: str, timeout: int = 20) -> dict[str, Any]:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip()[:600],
            "stderr": result.stderr.strip()[:200],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class DeviceTools:
    """Full Windows device control: apps, system info, FRIDAY services, volume, PowerShell."""

    # ── App launching ──────────────────────────────────────────────────────────

    def open_app(self, name: str) -> dict[str, Any]:
        key = name.strip().lower()
        target = _APP_MAP.get(key, name.strip())
        log_event("DEVICE", f"open_app: {target[:60]}")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            if target.startswith("http"):
                subprocess.Popen(["cmd.exe", "/c", "start", "", target], creationflags=flags)
                return {"ok": True, "opened": target}
            if target.endswith(".ps1"):
                subprocess.Popen(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", target],
                    creationflags=flags,
                )
                return {"ok": True, "opened": target}
            subprocess.Popen(["cmd.exe", "/c", "start", "", target], creationflags=flags)
            return {"ok": True, "opened": target}
        except Exception as exc:
            log_event("DEVICE", f"open_app failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def open_folder(self, path: str) -> dict[str, Any]:
        expanded = os.path.expandvars(os.path.expanduser(path))
        log_event("DEVICE", f"open_folder: {expanded}")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            subprocess.Popen(["explorer.exe", expanded], creationflags=flags)
            return {"ok": True, "path": expanded}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def resolve_app_name(self, text: str) -> str | None:
        """Extract app name from voice command text."""
        t = text.strip().lower()
        for key in _APP_MAP:
            if key in t:
                return key
        return None

    # ── System info ────────────────────────────────────────────────────────────

    def system_info(self) -> dict[str, Any]:
        result = _ps(
            "$cpu = [math]::Round((Get-WmiObject Win32_Processor | "
            "  Measure-Object -Property LoadPercentage -Average).Average, 0); "
            "$os = Get-WmiObject Win32_OperatingSystem; "
            "$disk = Get-PSDrive C; "
            "$ram_used = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1); "
            "$ram_total = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1); "
            "$disk_free = [math]::Round($disk.Free / 1GB, 1); "
            "$disk_total = [math]::Round(($disk.Free + $disk.Used) / 1GB, 1); "
            "[PSCustomObject]@{cpu_pct=$cpu; ram_used_gb=$ram_used; ram_total_gb=$ram_total; "
            "disk_free_gb=$disk_free; disk_total_gb=$disk_total} | ConvertTo-Json"
        )
        if result["ok"] and result["stdout"]:
            try:
                data = json.loads(result["stdout"])
                return {"ok": True, **data}
            except Exception:
                pass
        return result

    # ── Volume ─────────────────────────────────────────────────────────────────

    def set_volume(self, level: int) -> dict[str, Any]:
        level = max(0, min(100, int(level)))
        pct = level / 100.0
        result = _ps(_SET_VOLUME_PS.format(pct=f"{pct:.2f}"), timeout=15)
        log_event("DEVICE", f"set_volume level={level} ok={result['ok']}")
        return {"ok": result["ok"], "volume": level}

    def get_volume(self) -> dict[str, Any]:
        result = _ps(
            "Add-Type -TypeDefinition @\""
            "using System; using System.Runtime.InteropServices;"
            "[ComImport,Guid('BCDE0395-E52F-467C-8E3D-C4579291692E')] class MMECls {}"
            "[Guid('A95664D2-9614-4F35-A746-DE8DB63617E6'),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]"
            "interface IMMEnum { void _V0(); [return:MarshalAs(UnmanagedType.Interface)] object GetDefaultAudioEndpoint(int d,int r); }"
            "[Guid('D666063F-1587-4E43-81F1-B948E807363F'),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]"
            "interface IMMDev { [return:MarshalAs(UnmanagedType.Interface)] object Activate(ref Guid i,uint c,IntPtr p); }"
            "[Guid('5CDF2C82-841E-4546-9722-0CF74078229A'),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]"
            "interface IAudioVol { void R0();void R1();void R2();void R3();void R4();void R5();"
            "void Set(float l,IntPtr c); int Get(out float l); }"
            "public class WV2 { public static float Read() {"
            "var en=(IMMEnum)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")));"
            "var dv=(IMMDev)en.GetDefaultAudioEndpoint(0,1);"
            "var g=new Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\");"
            "var v=(IAudioVol)dv.Activate(ref g,23,IntPtr.Zero); float l; v.Get(out l); return l; } }"
            "\"@ -EA SilentlyContinue; [math]::Round([WV2]::Read()*100)"
        )
        if result["ok"]:
            try:
                return {"ok": True, "volume": int(result["stdout"])}
            except Exception:
                pass
        return result

    # ── FRIDAY service control ─────────────────────────────────────────────────

    def friday_stop_all(self) -> dict[str, Any]:
        names_ps = ", ".join(f'"{s}"' for s in _FRIDAY_SCRIPTS)
        result = _ps(
            f"$scripts = @({names_ps}); "
            "Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { "
            "  $id=$_.Id; "
            "  $cmd=(Get-CimInstance Win32_Process -Filter \"ProcessId=$id\" -EA SilentlyContinue).CommandLine; "
            "  foreach($s in $scripts) { if ($cmd -like \"*$s*\") { Stop-Process -Id $id -Force -EA SilentlyContinue; break } } "
            "}"
        )
        log_event("DEVICE", "friday_stop_all")
        return {"ok": True, "action": "stopped_all_friday_processes"}

    def friday_start(self, service: str = "all") -> dict[str, Any]:
        scripts: dict[str, Path] = {
            "all":     ROOT / "start_friday_trading_full.ps1",
            "trading": ROOT / "start_friday_trading_full.ps1",
            "voice":   ROOT / "start_friday_voice.ps1",
        }
        script = scripts.get(service.lower(), scripts["all"])
        if not script.exists():
            return {"ok": False, "error": f"script not found: {script}"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            creationflags=flags,
        )
        log_event("DEVICE", f"friday_start service={service}")
        return {"ok": True, "action": f"started_{service}"}

    def friday_restart(self) -> dict[str, Any]:
        self.friday_stop_all()
        time.sleep(3)
        return self.friday_start("all")

    def friday_processes(self) -> dict[str, Any]:
        result = _ps(
            "Get-Process python -EA SilentlyContinue | ForEach-Object { "
            "  $id=$_.Id; "
            "  $cmd=(Get-CimInstance Win32_Process -Filter \"ProcessId=$id\" -EA SilentlyContinue).CommandLine; "
            "  [PSCustomObject]@{pid=$id; cmd=($cmd -replace '.+python.exe','').Trim()} "
            "} | ConvertTo-Json"
        )
        if result["ok"] and result["stdout"]:
            try:
                procs = json.loads(result["stdout"])
                if isinstance(procs, dict):
                    procs = [procs]
                return {"ok": True, "count": len(procs), "processes": procs[:15]}
            except Exception:
                pass
        return {"ok": True, "count": 0, "processes": []}

    # ── Screenshot ─────────────────────────────────────────────────────────────

    def screenshot(self) -> dict[str, Any]:
        """Take a screenshot of all monitors combined (virtual screen)."""
        path = str(ROOT / "data" / f"screenshot_{int(time.time())}.png")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        result = _ps(
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$screens=[System.Windows.Forms.Screen]::AllScreens; "
            "$left=($screens|%{$_.Bounds.Left}|Sort-Object|Select-Object -First 1); "
            "$top=($screens|%{$_.Bounds.Top}|Sort-Object|Select-Object -First 1); "
            "$right=($screens|%{$_.Bounds.Right}|Sort-Object -Desc|Select-Object -First 1); "
            "$bottom=($screens|%{$_.Bounds.Bottom}|Sort-Object -Desc|Select-Object -First 1); "
            "$w=$right-$left; $h=$bottom-$top; "
            "$b=New-Object System.Drawing.Bitmap($w,$h); "
            "$g=[System.Drawing.Graphics]::FromImage($b); "
            "$g.CopyFromScreen($left,$top,0,0,(New-Object System.Drawing.Size($w,$h))); "
            f"$b.Save('{path}'); "
            f"Write-Output '{path}'"
        )
        return {"ok": result["ok"], "path": path if result["ok"] else None}

    def screenshot_all_monitors(self) -> dict[str, Any]:
        """Take individual screenshots of each physical monitor. Returns list of paths."""
        ts = int(time.time())
        data_dir = ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        result = _ps(
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$screens=[System.Windows.Forms.Screen]::AllScreens; "
            "$i=1; $paths=@(); "
            "foreach($s in $screens) { "
            f"  $p=\"{str(data_dir).replace(chr(92), '/')}/screenshot_mon$i_{ts}.png\"; "
            "  $b=New-Object System.Drawing.Bitmap($s.Bounds.Width,$s.Bounds.Height); "
            "  $g=[System.Drawing.Graphics]::FromImage($b); "
            "  $g.CopyFromScreen($s.Bounds.Location,[System.Drawing.Point]::Empty,$s.Bounds.Size); "
            "  $b.Save($p); $paths+=$p; $i++ "
            "}; "
            "$paths -join '|'"
        )
        if result["ok"] and result["stdout"]:
            paths = [p.strip() for p in result["stdout"].split("|") if p.strip()]
            return {"ok": True, "count": len(paths), "paths": paths}
        return {"ok": False, "error": result.get("error", result.get("stderr", "unknown"))}

    # ── Arbitrary PowerShell ───────────────────────────────────────────────────

    def run_powershell(self, command: str) -> dict[str, Any]:
        log_event("DEVICE", f"run_powershell: {command[:100]}")
        return _ps(command, timeout=30)
