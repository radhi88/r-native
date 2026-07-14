class VoiceIO:
    # أوامر التداول المدعومة
    TRADE_COMMANDS = {
        # شراء
        "اشتري": "BUY",
        "buy": "BUY",
        "شراء": "BUY",
        "تداول شراء": "BUY",
        # بيع
        "بيع": "SELL",
        "sell": "SELL",
        "بيعة": "SELL",
        "تداول بيع": "SELL",
        # تحليل
        "حلل": "ANALYZE",
        "تحليل": "ANALYZE",
        "analyze": "ANALYZE",
        # وضع التداول
        "ورقي": "PAPER",
        "paper": "PAPER",
        "ديمو": "DEMO",
        "demo": "DEMO",
        "حقيقي": "LIVE",
        "live": "LIVE",
    }

    def __init__(self, speak=False, listen=False):
        self.speak_enabled = speak
        self.listen_enabled = listen
        self.engine = None
        self.recognizer = None
        self.microphone_cls = None

        if speak:
            try:
                import pyttsx3

                self.engine = pyttsx3.init()
            except Exception:
                self.speak_enabled = False

        if listen:
            try:
                import speech_recognition as sr

                self.recognizer = sr.Recognizer()
                self.microphone_cls = sr.Microphone
            except Exception:
                self.listen_enabled = False

    def parse_command(self, text):
        """يحلل الأمر الصوتي ويعيد الأمر المناسب"""
        if not text:
            return None
        text = text.strip().lower()
        
        # فحص أوامر التداول
        for cmd, action in self.TRADE_COMMANDS.items():
            if cmd in text:
                return action
        
        return None

    def speak(self, text):
        if not self.speak_enabled or self.engine is None:
            return False
        self.engine.say(text)
        self.engine.runAndWait()
        return True

    def listen_once(self, timeout=5):
        if not self.listen_enabled or self.recognizer is None or self.microphone_cls is None:
            return None

        with self.microphone_cls() as source:
            audio = self.recognizer.listen(source, timeout=timeout)

        try:
            # دعم العربية والإنجليزية
            try:
                return self.recognizer.recognize_google(audio, language="ar-SA")
            except:
                return self.recognizer.recognize_google(audio, language="en-US")
        except Exception:
            return None

    def status(self):
        return {
            "speak": self.speak_enabled,
            "listen": self.listen_enabled,
            "trade_commands": list(self.TRADE_COMMANDS.keys()),
        }
