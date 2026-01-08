import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import MetaTrader5 as mt5

from utils.mt5_utils import get_live_data, initialize_mt5


# =========================
# Indicators
# =========================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


# =========================
# MT5 symbol specs
# =========================
def get_symbol_specs(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) failed. Check symbol name.")

    contract_size = float(getattr(info, "trade_contract_size", 1.0))
    point = float(getattr(info, "point", 0.01))
    spread_points = float(getattr(info, "spread", 0.0))

    volume_min = float(getattr(info, "volume_min", 0.01))
    volume_step = float(getattr(info, "volume_step", 0.01))
    volume_max = float(getattr(info, "volume_max", 100.0))

    spread_abs = spread_points * point  # spread in price units

    return {
        "contract_size": contract_size,
        "point": point,
        "spread_abs": spread_abs,
        "volume_min": volume_min,
        "volume_step": volume_step,
        "volume_max": volume_max,
    }

def round_volume(vol: float, vmin: float, vstep: float, vmax: float) -> float:
    if vol < vmin:
        return 0.0
    steps = np.floor((vol - vmin) / vstep + 1e-12)
    v = vmin + steps * vstep
    return float(np.clip(v, vmin, vmax))


# =========================
# Pullback + rejection logic
# =========================
def is_bull_rejection(row, ema20, ema50, min_body_frac: float = 0.35):
    """
    Bullish rejection:
    - low touches zone (<= ema50)
    - close > ema20 (reclaim)
    - body is not tiny
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    body_frac = body / rng

    touches_zone = l <= ema50
    reclaim = c > ema20
    bullish = c > o
    ok_body = body_frac >= min_body_frac

    return touches_zone and reclaim and bullish and ok_body

def is_bear_rejection(row, ema20, ema50, min_body_frac: float = 0.35):
    """
    Bearish rejection:
    - high touches zone (>= ema50)
    - close < ema20 (reject)
    - body not tiny
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    body_frac = body / rng

    touches_zone = h >= ema50
    reject = c < ema20
    bearish = c < o
    ok_body = body_frac >= min_body_frac

    return touches_zone and reject and bearish and ok_body


# =========================
# Backtest
# =========================
def backtest_xau_m5_pullback(
    df: pd.DataFrame,
    starting_balance: float = 10000.0,
    risk_per_trade: float = 0.01,      # 1% risk
    commission_per_side: float = 0.0,  # per 1.0 lot per side

    spread_abs: float = 0.0,           # price units (auto from MT5 recommended)
    contract_size: float = 1.0,

    volume_min: float = 0.01,
    volume_step: float = 0.01,
    volume_max: float = 100.0,

    ema_trend: int = 200,
    ema_fast: int = 20,
    ema_slow: int = 50,
    atr_period: int = 14,

    sl_atr_mult: float = 1.8,          # XAU M5 likes room; try 1.5–2.5
    tp_rr: float = 1.5,                # realistic for pullbacks; try 1.2–2.0
    trail_after_rr: float = 1.0,       # start trailing after +1R
    trail_atr_mult: float = 1.2,       # trail distance (try 1.0–2.0)

    tie_break: str = "worst",          # if SL & TP hit same candle
):
    """
    Required df columns: time, open, high, low, close
    - Entries at next candle open (with spread)
    - Intrabar execution uses high/low
    - One position at a time (like your bot)
    """

    df = df.copy().sort_values("time").reset_index(drop=True)

    # Indicators
    df["ema200"] = ema(df["close"], ema_trend)
    df["ema20"] = ema(df["close"], ema_fast)
    df["ema50"] = ema(df["close"], ema_slow)
    df["atr"] = atr(df, atr_period)

    balance = starting_balance
    equity_curve, equity_times = [], []
    trades = []

    pos = None  # dict: side, entry, sl, tp, vol, etc.

    def entry_price_with_spread(side: str, open_price: float) -> float:
        # Buy enters ask; sell enters bid
        return open_price + spread_abs / 2.0 if side == "buy" else open_price - spread_abs / 2.0

    def exit_price_with_spread(side: str, raw_exit_price: float) -> float:
        # Buy exits bid; sell exits ask
        return raw_exit_price - spread_abs / 2.0 if side == "buy" else raw_exit_price + spread_abs / 2.0

    def pnl(side: str, entry: float, exitp: float, vol: float) -> float:
        sign = 1 if side == "buy" else -1
        return (exitp - entry) * sign * vol * contract_size

    def commission(vol: float) -> float:
        return commission_per_side * vol

    def resolve_hit(hit_sl: bool, hit_tp: bool):
        if hit_sl and hit_tp:
            return "sl" if tie_break in ("worst", "sl_first") else "tp"
        if hit_sl:
            return "sl"
        if hit_tp:
            return "tp"
        return None

    for i in range(len(df) - 1):
        row = df.iloc[i]
        nxt = df.iloc[i + 1]

        equity_times.append(row["time"])

        # Mark-to-market equity
        if pos is None:
            equity_curve.append(balance)
        else:
            mkt_exit = exit_price_with_spread(pos["side"], row["close"])
            equity_curve.append(balance + pnl(pos["side"], pos["entry"], mkt_exit, pos["vol_open"]))

        # Wait for indicators
        if np.isnan(row["atr"]) or np.isnan(row["ema200"]) or np.isnan(row["ema20"]) or np.isnan(row["ema50"]):
            continue

        # -------------------------
        # Manage open position
        # -------------------------
        if pos is not None:
            side = pos["side"]
            hi, lo = row["high"], row["low"]

            sl = pos["sl"]
            tp = pos["tp"]

            if side == "buy":
                hit_sl = lo <= sl
                hit_tp = hi >= tp
            else:
                hit_sl = hi >= sl
                hit_tp = lo <= tp

            outcome = resolve_hit(hit_sl, hit_tp)
            if outcome == "sl":
                exitp = exit_price_with_spread(side, sl)
                vol_close = pos["vol_open"]
                balance += pnl(side, pos["entry"], exitp, vol_close) - commission(vol_close)
                trades.append({**pos, "exit_time": row["time"], "exit": exitp, "result": "sl", "pnl": balance - pos["balance_before"]})
                pos = None
                continue

            if outcome == "tp":
                exitp = exit_price_with_spread(side, tp)
                vol_close = pos["vol_open"]
                balance += pnl(side, pos["entry"], exitp, vol_close) - commission(vol_close)
                trades.append({**pos, "exit_time": row["time"], "exit": exitp, "result": "tp", "pnl": balance - pos["balance_before"]})
                pos = None
                continue

            # ATR trailing AFTER certain RR is reached
            # RR = move in price / R
            if pos is not None:
                a = float(row["atr"])
                entry = pos["entry"]
                R = pos["R"]

                # estimate current RR using close (approx)
                cur_exit = exit_price_with_spread(side, row["close"])
                rr = (cur_exit - entry) / R if side == "buy" else (entry - cur_exit) / R

                if rr >= trail_after_rr:
                    if side == "buy":
                        new_sl = float(row["close"]) - a * trail_atr_mult
                        pos["sl"] = max(pos["sl"], new_sl)
                    else:
                        new_sl = float(row["close"]) + a * trail_atr_mult
                        pos["sl"] = min(pos["sl"], new_sl)

        # -------------------------
        # Entry (flat only)
        # -------------------------
        if pos is None:
            ema200 = float(row["ema200"])
            ema20v = float(row["ema20"])
            ema50v = float(row["ema50"])
            a = float(row["atr"])

            trend_long = row["close"] > ema200
            trend_short = row["close"] < ema200

            # Entry signals on current closed candle, enter next open
            long_sig = trend_long and is_bull_rejection(row, ema20v, ema50v)
            short_sig = trend_short and is_bear_rejection(row, ema20v, ema50v)

            if long_sig or short_sig:
                side = "buy" if long_sig else "sell"
                entry = entry_price_with_spread(side, float(nxt["open"]))

                # SL from ATR
                if side == "buy":
                    sl = entry - a * sl_atr_mult
                    R = abs(entry - sl)
                    tp = entry + tp_rr * R
                else:
                    sl = entry + a * sl_atr_mult
                    R = abs(entry - sl)
                    tp = entry - tp_rr * R

                if R <= 0:
                    continue

                # Risk-based sizing
                risk_amount = balance * risk_per_trade
                vol = risk_amount / (R * contract_size)
                vol = round_volume(vol, volume_min, volume_step, volume_max)
                if vol <= 0:
                    continue

                balance_before = balance
                balance -= commission(vol)  # entry commission

                pos = {
                    "entry_time": nxt["time"],
                    "side": side,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "R": R,
                    "vol_initial": vol,
                    "vol_open": vol,
                    "balance_before": balance_before,
                }

    equity = pd.Series(equity_curve, index=pd.Index(equity_times, name="time")).sort_index()
    trades_df = pd.DataFrame(trades)
    return trades_df, equity


# =========================
# Stats + Runner
# =========================
def compute_stats(trades_df: pd.DataFrame, equity: pd.Series, start_bal: float):
    if trades_df.empty:
        return {"start_balance": start_bal, "end_balance": float(equity.iloc[-1]), "num_trades": 0}

    pnl = trades_df["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    win_rate = float((pnl > 0).mean())
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf")

    eq = equity.astype(float)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = float(dd.min())

    return {
        "start_balance": float(start_bal),
        "end_balance": float(eq.iloc[-1]),
        "net_profit": float(eq.iloc[-1] - start_bal),
        "num_trades": int(len(trades_df)),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": float(max_dd * 100.0),
        "avg_trade_pnl": float(pnl.mean()),
    }


def start_backtest_xau_pullback(symbol="XAUUSD", candles=60000):
    initialize_mt5()

    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Can't select symbol {symbol}")

    specs = get_symbol_specs(symbol)
    print("MT5 SPECS:", specs)

    df = get_live_data(symbol=symbol, time_frame="M5", prev_n_candles=candles)
    if df["time"].dtype == object:
        df["time"] = pd.to_datetime(df["time"])

    trades, equity = backtest_xau_m5_pullback(
        df,
        starting_balance=10000.0,
        risk_per_trade=0.01,

        commission_per_side=0.0,
        spread_abs=specs["spread_abs"],
        contract_size=specs["contract_size"],
        volume_min=specs["volume_min"],
        volume_step=specs["volume_step"],
        volume_max=specs["volume_max"],

        sl_atr_mult=1.8,
        tp_rr=1.5,
        trail_after_rr=1.0,
        trail_atr_mult=1.2,

        tie_break="worst",
    )

    stats = compute_stats(trades, equity, 10000.0)

    print("\n=== STATS ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    print("\n=== LAST 10 TRADES ===")
    print(trades.tail(10))

    plt.figure()
    plt.plot(equity.index, equity.values)
    plt.title(f"Equity Curve - {symbol} M5 Pullback")
    plt.xlabel("Time")
    plt.ylabel("Equity")
    plt.show()

    return trades, equity, stats
