"""
Zone Detector for Smart Algorithm Pro
Detects supply and demand zones based on impulse candles and validation steps.
"""
import pandas as pd

class ZoneDetector:
    def __init__(self, df):
        """
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume', 'ATR']
        """
        self.df = df
        self.zones = []

    def find_impulse_candles(self, atr_mult=2):
        # Step 1: Find impulse candles (body > 2x ATR, high)
        df = self.df.copy()
        body = (df['close'] - df['open']).abs()
        impulse = body > (atr_mult * df['ATR'])
        return df[impulse]

    def identify_base(self, impulse_idx, window=5):
        # Step 2: Identify base (2-5 candles before impulse)
        start = max(0, impulse_idx - window)
        end = impulse_idx
        return self.df.iloc[start:end]

    def mark_boundaries(self, base_df):
        # Step 3: Mark boundaries (high/low of base)
        return base_df['high'].max(), base_df['low'].min()

    def validate_touches(self, zone_high, zone_low, after_idx, min_touches=2):
        # Step 4: Validate touches (price reacts 2+ times)
        touches = 0
        for i in range(after_idx, len(self.df)):
            if zone_low <= self.df['low'].iloc[i] <= zone_high or zone_low <= self.df['high'].iloc[i] <= zone_high:
                touches += 1
            if touches >= min_touches:
                return True
        return False

    def score_strength(self, impulse_idx, zone_high, zone_low):
        # Step 5: Score strength (freshness + proximity)
        # Placeholder: Simple freshness = 1 / (bars since impulse)
        freshness = 1 / (len(self.df) - impulse_idx + 1)
        # Proximity: Not implemented (depends on current price)
        return freshness

    def detect_zones(self):
        impulses = self.find_impulse_candles()
        for idx in impulses.index:
            base = self.identify_base(idx)
            if base.empty:
                continue
            zone_high, zone_low = self.mark_boundaries(base)
            if self.validate_touches(zone_high, zone_low, idx):
                strength = self.score_strength(idx, zone_high, zone_low)
                self.zones.append({
                    'impulse_idx': idx,
                    'zone_high': zone_high,
                    'zone_low': zone_low,
                    'strength': strength
                })
        return self.zones
