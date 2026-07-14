"""
Indicator Engine for Smart Algorithm Pro
Implements EMA, RSI, ADX, ATR, MACD, MFI, Volume%, Spread for multi-timeframe analysis.
"""
import pandas as pd
import numpy as np

class IndicatorEngine:
    def __init__(self, data):
        """
        data: dict of {tf: DataFrame}, each DataFrame must have columns: ['open', 'high', 'low', 'close', 'volume', 'spread']
        """
        self.data = data  # {tf: DataFrame}
        self.results = {tf: {} for tf in data}

    def calculate_ema(self, tf, fast=8, slow=21):
        df = self.data[tf]
        self.results[tf]['EMA_FAST'] = df['close'].ewm(span=fast, adjust=False).mean()
        self.results[tf]['EMA_SLOW'] = df['close'].ewm(span=slow, adjust=False).mean()

    def calculate_rsi(self, tf, period=14):
        df = self.data[tf]
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        self.results[tf]['RSI'] = rsi

    def calculate_adx(self, tf, period=14):
        df = self.data[tf]
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff().abs()
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=period).mean()
        plus_di = 100 * plus_dm.rolling(window=period).mean() / atr
        minus_di = 100 * minus_dm.rolling(window=period).mean() / atr
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.rolling(window=period, min_periods=period).mean()
        self.results[tf]['ADX'] = adx

    def calculate_atr(self, tf, period=14):
        df = self.data[tf]
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=period).mean()
        self.results[tf]['ATR'] = atr

    def calculate_macd(self, tf, fast=12, slow=26, signal=9):
        df = self.data[tf]
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - signal_line
        self.results[tf]['MACD'] = macd
        self.results[tf]['MACD_SIGNAL'] = signal_line
        self.results[tf]['MACD_HIST'] = hist

    def calculate_mfi(self, tf, period=14):
        df = self.data[tf]
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0)
        pos_mf = positive_flow.rolling(window=period, min_periods=period).sum()
        neg_mf = negative_flow.rolling(window=period, min_periods=period).sum()
        mfi = 100 * pos_mf / (pos_mf + neg_mf)
        self.results[tf]['MFI'] = mfi

    def calculate_volume_percent(self, tf, period=14):
        df = self.data[tf]
        avg_vol = df['volume'].rolling(window=period, min_periods=period).mean()
        vol_pct = 100 * (df['volume'] - avg_vol) / avg_vol
        self.results[tf]['VOLUME_PCT'] = vol_pct

    def calculate_spread(self, tf):
        df = self.data[tf]
        self.results[tf]['SPREAD'] = df['spread']

    def calculate_all(self):
        for tf in self.data:
            self.calculate_ema(tf)
            self.calculate_rsi(tf)
            self.calculate_adx(tf)
            self.calculate_atr(tf)
            self.calculate_macd(tf)
            self.calculate_mfi(tf)
            self.calculate_volume_percent(tf)
            self.calculate_spread(tf)

    def get_results(self, tf=None):
        if tf:
            return self.results[tf]
        return self.results
