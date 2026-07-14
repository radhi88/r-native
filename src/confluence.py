"""
Confluence Matrix for Smart Algorithm Pro
Aggregates indicator signals into 3 groups and computes final score and signal.
"""
import numpy as np

class ConfluenceMatrix:
    def __init__(self, indicator_results):
        """
        indicator_results: dict of {tf: {indicator: series/array}}
        """
        self.indicator_results = indicator_results  # {tf: {indicator: series}}
        self.group_scores = None
        self.final_score = None
        self.final_signal = None

    def group_a(self, tf):
        ind = self.indicator_results[tf]
        score = 0
        # EMA Cross
        if ind['EMA_FAST'].iloc[-1] > ind['EMA_SLOW'].iloc[-1]:
            score += 0.25
        # RSI
        rsi = ind['RSI'].iloc[-1]
        if 50 < rsi < 70:
            score += 0.25
        # ADX
        if ind['ADX'].iloc[-1] > 25:
            score += 0.2
        # MACD Histogram
        if ind['MACD_HIST'].iloc[-1] > 0:
            score += 0.2
        # Price vs EMA
        price = ind['close'].iloc[-1]
        if price > ind['EMA_SLOW'].iloc[-1]:
            score += 0.1
        return score

    def group_b(self, tf):
        ind = self.indicator_results[tf]
        score = 0
        # MFI
        if ind['MFI'].iloc[-1] > 50:
            score += 0.35
        # Volume%
        if ind['VOLUME_PCT'].iloc[-1] > 0:
            score += 0.35
        # Volume Trend (current vs avg)
        if ind['VOLUME_PCT'].iloc[-1] > ind['VOLUME_PCT'].rolling(10).mean().iloc[-1]:
            score += 0.2
        # Divergence (placeholder)
        # Could be implemented as needed
        return score

    def group_c(self, tf):
        # Placeholder: Structure/Breakout logic to be implemented
        # For now, return 0
        return 0

    def calculate_group_scores(self, tfs):
        scores = {'A': [], 'B': [], 'C': []}
        for tf in tfs:
            scores['A'].append(self.group_a(tf))
            scores['B'].append(self.group_b(tf))
            scores['C'].append(self.group_c(tf))
        # Weighted average per group
        self.group_scores = {
            'A': np.mean(scores['A']),
            'B': np.mean(scores['B']),
            'C': np.mean(scores['C'])
        }
        return self.group_scores

    def calculate_final_score(self):
        if self.group_scores is None:
            raise ValueError('Call calculate_group_scores first')
        self.final_score = (
            self.group_scores['A'] * 0.4 +
            self.group_scores['B'] * 0.3 +
            self.group_scores['C'] * 0.3
        ) * 100
        return self.final_score

    def calculate_final_signal(self, spread=0):
        if self.final_score is None:
            raise ValueError('Call calculate_final_score first')
        if spread > 150:
            self.final_signal = 'BLOCK'
        elif self.final_score >= 70:
            self.final_signal = 'BUY/SELL'
        elif self.final_score >= 50:
            self.final_signal = 'WAIT (weak)'
        else:
            self.final_signal = 'WAIT (none)'
        return self.final_signal

    def get_results(self):
        return {
            'group_scores': self.group_scores,
            'final_score': self.final_score,
            'final_signal': self.final_signal
        }
