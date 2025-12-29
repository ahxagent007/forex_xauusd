import pandas as pd


def ema(prices_df, span):
    ema = prices_df['close'].ewm(span=span).mean()
    #a = ema.shift(1)
    return ema

