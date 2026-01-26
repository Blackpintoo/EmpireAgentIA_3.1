import pandas as pd

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_gain = up.rolling(window=period, min_periods=period).mean()
    avg_loss = down.rolling(window=period, min_periods=period).mean()
    rs = (avg_gain / avg_loss).replace([float('inf'), -float('inf')], 0).fillna(0)
    return 100 - (100 / (1 + rs))

def compute_ema(series, period=21):
    return series.ewm(span=period, adjust=False).mean()

def compute_atr(df, period=14):
    high_low = (df['high'] - df['low']).abs()
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=period).mean()

def compute_macd(series, fast_period=12, slow_period=26, signal_period=9):
    ema_fast = compute_ema(series, fast_period)
    ema_slow = compute_ema(series, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_obv(df):
    close = pd.to_numeric(df['close'], errors='coerce')
    vol = pd.to_numeric(df.get('tick_volume', df.get('volume', 0)), errors='coerce').fillna(0)
    sign = close.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (vol * sign).cumsum()
