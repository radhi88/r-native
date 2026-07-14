from pathlib import Path
from datetime import datetime

path = Path("main.py")
if not path.exists():
    raise SystemExit("main.py not found")

text = path.read_text(encoding="utf-8", errors="replace")

backup = path.with_name("main.py.bak_keyboard_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print(f"Backup saved: {backup.name}")

old = '''    ui = JarvisUI("face.png")

    def runner():
        jarvis = JarvisOllama(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\\nShutting down.")
        except Exception:
            traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()
'''

new = '''    ui = JarvisUI("face.png")
    jarvis_holder = {"instance": None}

    def _shutdown_ui_cleanly():
        jarvis = jarvis_holder.get("instance")
        if jarvis is not None:
            try:
                jarvis._shutdown_requested = True
            except Exception:
                pass

        root = getattr(ui, "root", None)
        if root is not None:
            for method_name in ("quit", "destroy", "close"):
                try:
                    method = getattr(root, method_name, None)
                    if callable(method):
                        method()
                except Exception:
                    pass

    def runner():
        jarvis = JarvisOllama(ui)
        jarvis_holder["instance"] = jarvis
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\\nSYS: Shutdown requested.")
        except Exception:
            traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()

    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        print("\\nSYS: UI shutdown requested by Ctrl+C.")
        _shutdown_ui_cleanly()
    except BaseException as exc:
        if exc.__class__.__name__ == "KeyboardInterrupt":
            print("\\nSYS: UI shutdown requested by Ctrl+C.")
            _shutdown_ui_cleanly()
        else:
            raise
'''

if old not in text:
    print("[WARN] Exact main() block not found. Trying smaller replacement...")
    old2 = '''    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()
'''
    new2 = '''    threading.Thread(target=runner, daemon=True).start()
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        print("\\nSYS: UI shutdown requested by Ctrl+C.")
        try:
            ui.root.quit()
        except Exception:
            pass
        try:
            ui.root.destroy()
        except Exception:
            pass
'''
    if old2 not in text:
        raise SystemExit("Could not patch main.py automatically. Send me the bottom def main() block.")
    text = text.replace(old2, new2, 1)
    print("[OK] Smaller KeyboardInterrupt patch applied")
else:
    text = text.replace(old, new, 1)
    print("[OK] Clean shutdown patch applied")

path.write_text(text, encoding="utf-8")
print("Patch completed.")
