import argparse
import time

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.jarvis_assistant import JarvisAssistant, JarvisState
from mt5_ai.voice_io import VoiceIO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M1")
    parser.add_argument("--profile", default="scalping")
    parser.add_argument("--mode", choices=["paper", "demo", "live"], default="paper")
    parser.add_argument("--source", choices=["mt5", "csv"], default="mt5")
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--allow-live", action="store_true", help="Allow live trading with real money.")
    parser.add_argument("--speak", action="store_true", help="Enable voice output.")
    parser.add_argument("--listen", action="store_true", help="Enable voice input.")
    args = parser.parse_args()

    state = JarvisState(
        symbol=args.symbol,
        timeframe=args.timeframe,
        profile=args.profile,
        mode=args.mode,
        source=args.source,
        bars=args.bars,
    )
    assistant = JarvisAssistant(state=state, allow_live=args.allow_live)
    voice = VoiceIO(speak=args.speak, listen=args.listen)

    print("=" * 50)
    print("🤖 FRIDAY MT5 Trading System")
    print("=" * 50)
    print(f"Mode: {args.mode.upper()}")
    print(f"Live Trading: {'ENABLED' if args.allow_live else 'DISABLED'}")
    print(f"Voice Input: {'ENABLED' if args.listen else 'DISABLED'}")
    print(f"Voice Output: {'ENABLED' if args.speak else 'DISABLED'}")
    print("=" * 50)
    print("Type 'مساعدة' for commands.")
    print(assistant.handle("status"))

    try:
        while True:
            if voice.listen_enabled:
                print("\n🎤 Listening for voice command...")
                command = voice.listen_once(timeout=5) or ""
                if command:
                    print(f"You said: {command}")
                    # تحليل الأمر الصوتي
                    parsed = voice.parse_command(command)
                    if parsed:
                        print(f"Parsed action: {parsed}")
                        if parsed == "ANALYZE":
                            response = assistant.handle("حلل")
                        elif parsed in {"BUY", "SELL"}:
                            # تحويل الأمر إلى أمر تداول
                            response = assistant.handle("تداول")
                        elif parsed in {"PAPER", "DEMO", "LIVE"}:
                            response = assistant.handle(parsed)
                        else:
                            response = assistant.handle(command)
                    else:
                        response = assistant.handle(command)
                else:
                    continue
            else:
                command = input("\nJarvis> ")

            if command.strip().lower().startswith("watch") or command.strip().startswith("راقب"):
                print("Watching. Press Ctrl+C to stop.")
                try:
                    while True:
                        response = assistant.handle("حلل")
                        print(response)
                        voice.speak("تم التحليل")
                        time.sleep(15)
                except KeyboardInterrupt:
                    print("Watch stopped.")
                continue

            response = assistant.handle(command)
            if response == "__QUIT__":
                break

            print(response)
            if args.speak:
                # تحويل الاستجابة إلى كلام
                voice.speak(str(response)[:500])
    finally:
        assistant.close()


if __name__ == "__main__":
    main()
