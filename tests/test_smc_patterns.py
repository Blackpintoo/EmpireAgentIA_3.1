import pandas as pd

from utils.smc_patterns import (
    compute_equilibrium,
    compute_ote_zone,
    detect_bos,
    detect_breaker_blocks,
    detect_choch,
    detect_equal_highs,
    detect_equal_lows,
    detect_fvg,
    detect_order_blocks,
    find_pivots,
)


def _df(rows):
    return pd.DataFrame(rows)


def test_find_pivots_identifies_high_and_low():
    df = _df(
        [
            {"open": 1, "high": 5, "low": 2, "close": 4},
            {"open": 4, "high": 6, "low": 3, "close": 5},
            {"open": 5, "high": 7, "low": 1.8, "close": 6},
            {"open": 6, "high": 4.5, "low": 0.5, "close": 1.2},
            {"open": 1.2, "high": 3.5, "low": 1.7, "close": 2.4},
            {"open": 2.4, "high": 4.2, "low": 1.9, "close": 3.6},
        ]
    )
    pivots = find_pivots(df, window=1)
    assert any(idx == 2 and typ == "high" for idx, _, typ in pivots)
    assert any(idx == 3 and typ == "low" for idx, _, typ in pivots)


def test_detect_bos_long_signal():
    df = _df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 100, "high": 105, "low": 100, "close": 104},
            {"open": 104, "high": 103, "low": 97, "close": 99},
            {"open": 99, "high": 104, "low": 95, "close": 96},
            {"open": 96, "high": 100, "low": 94, "close": 98},
            {"open": 98, "high": 110, "low": 96, "close": 111},
        ]
    )
    pivots = [
        (1, 105.0, "high"),
        (3, 95.0, "low"),
        (4, 100.0, "high"),
    ]
    events = detect_bos(df, pivots=pivots)
    assert any(ev.pattern == "BOS" and ev.direction == "LONG" for ev in events)


def test_detect_bos_short_signal():
    df = _df(
        [
            {"open": 120, "high": 125, "low": 118, "close": 124},
            {"open": 124, "high": 124, "low": 115, "close": 118},
            {"open": 118, "high": 119, "low": 112, "close": 114},
            {"open": 114, "high": 115, "low": 105, "close": 103},
            {"open": 103, "high": 104, "low": 100, "close": 98},
        ]
    )
    pivots = [
        (0, 125.0, "high"),
        (2, 112.0, "low"),
        (3, 115.0, "high"),
    ]
    events = detect_bos(df, pivots=pivots)
    assert any(ev.pattern == "BOS" and ev.direction == "SHORT" for ev in events)


def test_detect_choch_short():
    df = _df(
        [
            {"open": 100, "high": 110, "low": 99, "close": 108},
            {"open": 108, "high": 115, "low": 101, "close": 113},
            {"open": 113, "high": 114, "low": 105, "close": 112},
            {"open": 112, "high": 113, "low": 96, "close": 97},
            {"open": 97, "high": 108, "low": 94, "close": 96},
        ]
    )
    pivots = [
        (0, 110, "high"),
        (2, 105, "low"),
        (3, 114, "high"),
        (4, 108, "high"),
    ]
    events = detect_choch(df, pivots=pivots)
    assert any(ev.pattern == "CHoCH" and ev.direction == "SHORT" for ev in events)


def test_detect_fvg_long_gap():
    df = _df(
        [
            {"open": 100, "high": 102, "low": 99, "close": 101},
            {"open": 103, "high": 110, "low": 103, "close": 109},
            {"open": 109, "high": 115, "low": 108, "close": 114},
        ]
    )
    events = detect_fvg(df)
    assert any(ev.pattern == "FVG" and ev.direction == "LONG" for ev in events)


def test_detect_equal_highs_and_lows():
    df = _df(
        [
            {"open": 100, "high": 105, "low": 95, "close": 102},
            {"open": 102, "high": 105.001, "low": 96, "close": 103},
            {"open": 103, "high": 105.0007, "low": 97, "close": 104},
            {"open": 104, "high": 99, "low": 90, "close": 92},
            {"open": 92, "high": 99.5, "low": 90.001, "close": 94},
            {"open": 94, "high": 98.9, "low": 90.0008, "close": 95},
        ]
    )
    highs = detect_equal_highs(df, lookback=5, tolerance=0.02)
    lows = detect_equal_lows(df, lookback=5, tolerance=0.02)
    assert highs and highs[0].pattern == "EQH"
    assert lows and lows[0].pattern == "EQL"


def test_detect_order_and_breaker_blocks():
    df = _df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 100, "high": 103, "low": 95, "close": 97},  # bearish candle
            {"open": 97, "high": 120, "low": 96, "close": 119},
            {"open": 119, "high": 126, "low": 118, "close": 126},
        ]
    )
    pivots = [
        (1, 103, "high"),
        (2, 95, "low"),
        (3, 126, "high"),
    ]
    order_blocks = detect_order_blocks(df, lookback=4, pivots=pivots)
    assert any(ob.direction == "LONG" for ob in order_blocks)

    breakers = detect_breaker_blocks(df, pivots=pivots)
    assert any(bb.pattern == "BREAKER_BLOCK" and bb.direction == "LONG" for bb in breakers)


def test_compute_equilibrium_and_ote_zone():
    df = _df(
        [
            {"open": 10, "high": 15, "low": 9, "close": 14},
            {"open": 14, "high": 18, "low": 13, "close": 17},
            {"open": 17, "high": 20, "low": 16, "close": 19},
        ]
    )
    eq = compute_equilibrium(df)
    assert eq["high"] == 20
    assert eq["low"] == 9
    assert eq["equilibrium"] == (20 + 9) / 2

    ote = compute_ote_zone(df)
    assert ote is not None
    low, high = ote
    assert low < high
    assert low > eq["low"]
