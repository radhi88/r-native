"""
Multi-Timeframe Data Fetcher for Smart Algorithm Pro
Fetches OHLCV data for all required timeframes.
"""
from src.mt5_connector import MT5Connector

class MultiTFDataFetcher:
    def __init__(self, mt5_connector, symbol, tfs):
        self.mt5 = mt5_connector
        self.symbol = symbol
        self.tfs = tfs

    def fetch_all(self, n_bars=100):
        data = {}
        for tf in self.tfs:
            data[tf] = self.mt5.get_ohlcv(self.symbol, tf, n_bars)
        return data
