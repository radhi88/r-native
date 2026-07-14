class EnsemblePredictor:
    def __init__(self, model_lstm, model_transformer):
        self.lstm = model_lstm
        self.tr = model_transformer

    def predict(self, x):
        p1 = self.lstm.predict(x, verbose=0)
        p2 = self.tr.predict(x, verbose=0)
        return (0.6 * p1) + (0.4 * p2)
