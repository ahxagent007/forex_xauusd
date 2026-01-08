import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
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
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# =========================
# Backtest
# =========================
def backtest_ema_R(
    df: pd.DataFrame,
    ema_fast: int = 10,
    ema_trend: int = 200,
    atr_period: int = 14,
    sl_atr_mult: float = 2.0,
    tp_rr: float = 4.0,
    partial_rr: float = 1.5,
    partial_frac: float = 0.5,
    trail_atr_mult: float = 1.0,
    starting_balance: float = 10000.0,

    # Costs (BTC CFDs vary a lot by broker)
    spread_abs: float = 0.0,          # absolute spread in price units (e.g., 5.0 means $5 spread)
    commission_per_side: float = 0.0, # currency per 1.0 lot/contract per side (entry or exit)
    contract_size: float = 1.0,       # PnL multiplier: profit = price_move * volume * contract_size

    # Intrabar ambiguity: if SL and TP are both touched in same candle
    # "worst" = assume the worse outcome for you, "best" = assume best, "sl_first" = SL wins, "tp_first" = TP wins
    tie_break: str = "worst",
):
    """
    DataFrame required columns: time, open, high, low, close
    time can be datetime or int. Must be in ascending order.
    """

    df = df.copy()
    df = df.sort_values("time").reset_index(drop=True)

    # indicators
    df["ema_fast"] = ema(df["close"], ema_fast)
    df["ema_trend"] = ema(df["close"], ema_trend)
    df["atr"] = atr(df, atr_period)

    # signal uses CLOSED candles: compare bar i-1 and i-2
    # We'll compute signal at bar i (close of i), then enter at open of i+1
    df["cross_up"] = (df["close"].shift(2) <= df["ema_fast"].shift(2)) & (df["close"].shift(1) > df["ema_fast"].shift(1))
    df["cross_dn"] = (df["close"].shift(2) >= df["ema_fast"].shift(2)) & (df["close"].shift(1) < df["ema_fast"].shift(1))

    df["trend_buy"] = df["close"].shift(1) > df["ema_trend"].shift(1)
    df["trend_sell"] = df["close"].shift(1) < df["ema_trend"].shift(1)

    # portfolio
    balance = starting_balance
    equity_curve = []
    equity_times = []

    # position state (single position at a time, like your live code)
    pos = None  # dict with fields

    trades = []

    def side_to_sign(side: str) -> int:
        return 1 if side == "buy" else -1

    def entry_price_with_spread(side: str, open_price: float) -> float:
        # Buy enters at ask, sell enters at bid
        if side == "buy":
            return open_price + spread_abs / 2.0
        else:
            return open_price - spread_abs / 2.0

    def exit_price_with_spread(side: str, raw_exit_price: float) -> float:
        # Buy exits at bid, sell exits at ask
        if side == "buy":
            return raw_exit_price - spread_abs / 2.0
        else:
            return raw_exit_price + spread_abs / 2.0

    def pnl_for_move(side: str, entry: float, exitp: float, vol: float) -> float:
        sign = side_to_sign(side)
        return (exitp - entry) * sign * vol * contract_size

    def commission_cost(vol: float) -> float:
        # per-side commission
        return commission_per_side * vol

    def resolve_hit_order(side: str, hit_sl: bool, hit_tp: bool, hit_partial: bool):
        """
        Decide which event happens first if multiple are touched in same candle.
        For partial level and TP/SL, we handle partial first vs sl/tp carefully.
        We'll do conservative logic:
        - If both SL and TP hit same bar: tie_break rules apply.
        - For partial: if partial level and SL hit same bar, also ambiguous.
        """
        # returns a list of events in execution order (strings)
        events = []

        if not (hit_sl or hit_tp or hit_partial):
            return events

        # If SL & TP both hit:
        if hit_sl and hit_tp:
            if tie_break in ("sl_first", "worst"):
                events.append("sl")
            elif tie_break in ("tp_first", "best"):
                events.append("tp")
            else:
                events.append("sl")  # default conservative
            return events

        # Otherwise handle partial + one of sl/tp
        # In reality, price path matters. Conservative: if SL is touched, assume SL can happen before partial/tp.
        if hit_sl and not hit_tp:
            if hit_partial:
                if tie_break in ("worst", "sl_first"):
                    events.append("sl")
                else:
                    events.append("partial")
                    events.append("sl")
            else:
                events.append("sl")
            return events

        if hit_tp and not hit_sl:
            if hit_partial:
                # partial level is closer than TP, typically hit first
                events.append("partial")
                events.append("tp")
            else:
                events.append("tp")
            return events

        if hit_partial and not (hit_sl or hit_tp):
            events.append("partial")
            return events

        return events

    # Backtest loop
    for i in range(len(df) - 1):  # need i+1 open for entry
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        time_i = row["time"]
        equity_times.append(time_i)

        # mark-to-market equity (for curve)
        # if you want open PnL in equity, estimate using close:
        if pos is None:
            equity_curve.append(balance)
        else:
            # approximate unrealized using close with spread
            mkt_exit = exit_price_with_spread(pos["side"], row["close"])
            unreal = pnl_for_move(pos["side"], pos["entry_price"], mkt_exit, pos["vol_open"])
            equity_curve.append(balance + unreal)

        # Skip until indicators ready
        if np.isnan(row["atr"]) or np.isnan(row["ema_fast"]) or np.isnan(row["ema_trend"]):
            continue

        # =========================
        # Manage open position
        # =========================
        if pos is not None:
            side = pos["side"]
            sign = side_to_sign(side)

            # Levels in raw price terms (pre-spread); fills use exit_price_with_spread()
            sl = pos["sl"]
            tp = pos["tp"]
            entry = pos["entry_price"]
            r_price = pos["r_price"]
            partial_level = pos["partial_level"]  # entry +/- 1R

            # Candle high/low
            hi = row["high"]
            lo = row["low"]

            # Determine if levels touched intrabar (raw)
            if side == "buy":
                hit_sl = lo <= sl
                hit_tp = hi >= tp
                hit_partial = (not pos["partial_done"]) and (hi >= partial_level)
            else:
                hit_sl = hi >= sl
                hit_tp = lo <= tp
                hit_partial = (not pos["partial_done"]) and (lo <= partial_level)

            events = resolve_hit_order(side, hit_sl, hit_tp, hit_partial)

            for ev in events:
                if pos is None:
                    break

                if ev == "partial" and (not pos["partial_done"]):
                    # partial close at partial_level (raw), executed at realistic exit with spread
                    raw_exit = partial_level
                    exitp = exit_price_with_spread(side, raw_exit)

                    vol_close = pos["vol_open"] * partial_frac
                    vol_close = min(vol_close, pos["vol_open"])

                    pnl = pnl_for_move(side, entry, exitp, vol_close)
                    cost = commission_cost(vol_close)  # exit commission
                    balance += pnl - cost

                    pos["vol_open"] -= vol_close
                    pos["partial_done"] = True

                    # move SL to BE after partial
                    if pos["move_be_after_partial"]:
                        pos["sl"] = entry  # BE (you can add a buffer if you want)

                        pos["be_done"] = True

                    # record partial as a trade event (optional)
                    pos["events"].append(
                        {"time": time_i, "type": "partial", "price": exitp, "vol": vol_close, "pnl": pnl - cost}
                    )

                elif ev == "tp":
                    # close remaining at TP
                    raw_exit = tp
                    exitp = exit_price_with_spread(side, raw_exit)
                    vol_close = pos["vol_open"]

                    pnl = pnl_for_move(side, entry, exitp, vol_close)
                    cost = commission_cost(vol_close)
                    balance += pnl - cost

                    trades.append({
                        "entry_time": pos["entry_time"],
                        "exit_time": time_i,
                        "side": side,
                        "entry": entry,
                        "exit": exitp,
                        "vol": pos["vol_initial"],
                        "pnl": (balance - pos["balance_before"]),
                        "result": "tp",
                        "events": pos["events"],
                    })
                    pos = None
                    break

                elif ev == "sl":
                    # close remaining at SL
                    raw_exit = sl
                    exitp = exit_price_with_spread(side, raw_exit)
                    vol_close = pos["vol_open"]

                    pnl = pnl_for_move(side, entry, exitp, vol_close)
                    cost = commission_cost(vol_close)
                    balance += pnl - cost

                    trades.append({
                        "entry_time": pos["entry_time"],
                        "exit_time": time_i,
                        "side": side,
                        "entry": entry,
                        "exit": exitp,
                        "vol": pos["vol_initial"],
                        "pnl": (balance - pos["balance_before"]),
                        "result": "sl",
                        "events": pos["events"],
                    })
                    pos = None
                    break

            # ATR trailing after BE
            if pos is not None and pos["be_done"]:
                a = row["atr"]
                if side == "buy":
                    new_sl = row["close"] - a * trail_atr_mult
                    # tighten only
                    pos["sl"] = max(pos["sl"], new_sl)
                else:
                    new_sl = row["close"] + a * trail_atr_mult
                    pos["sl"] = min(pos["sl"], new_sl)

        # =========================
        # Entry (only if flat)
        # =========================
        if pos is None:
            # signal computed from closed candles at row i (using shifts)
            want_buy = bool(row["cross_up"]) and (bool(row["trend_buy"]) if True else True)
            want_sell = bool(row["cross_dn"]) and (bool(row["trend_sell"]) if True else True)

            # EMA200 filter already baked into trend_buy/trend_sell
            if want_buy or want_sell:
                side = "buy" if want_buy else "sell"

                # Enter at next bar open (with spread)
                raw_entry = float(next_row["open"])
                entryp = entry_price_with_spread(side, raw_entry)

                a = float(row["atr"])
                # ATR-based SL then TP=2R
                if side == "buy":
                    sl = entryp - a * sl_atr_mult
                    r_price = abs(entryp - sl)
                    tp = entryp + tp_rr * r_price
                    partial_level = entryp + partial_rr * r_price
                else:
                    sl = entryp + a * sl_atr_mult
                    r_price = abs(entryp - sl)
                    tp = entryp - tp_rr * r_price
                    partial_level = entryp - partial_rr * r_price

                # Position sizing:
                # If you want "calculate_lot_size" style sizing, you can map it here.
                # For backtest simplicity, we use fixed 1.0 volume unless you implement risk % sizing.
                vol = 1.0

                # Pay entry commission
                balance_before = balance
                balance -= commission_cost(vol)

                pos = {
                    "entry_time": next_row["time"],
                    "side": side,
                    "entry_price": entryp,
                    "sl": sl,
                    "tp": tp,
                    "r_price": r_price,
                    "partial_level": partial_level,
                    "partial_done": False,
                    "be_done": False,
                    "move_be_after_partial": True,

                    "vol_initial": vol,
                    "vol_open": vol,
                    "balance_before": balance_before,
                    "events": [{"time": next_row["time"], "type": "entry", "price": entryp, "vol": vol, "pnl": -commission_cost(vol)}],
                }

    # Close any open position at last close (optional)
    if pos is not None:
        last = df.iloc[-1]
        side = pos["side"]
        exitp = exit_price_with_spread(side, last["close"])
        vol_close = pos["vol_open"]
        pnl = pnl_for_move(side, pos["entry_price"], exitp, vol_close)
        cost = commission_cost(vol_close)
        balance += pnl - cost

        trades.append({
            "entry_time": pos["entry_time"],
            "exit_time": last["time"],
            "side": side,
            "entry": pos["entry_price"],
            "exit": exitp,
            "vol": pos["vol_initial"],
            "pnl": (balance - pos["balance_before"]),
            "result": "eod_close",
            "events": pos["events"],
        })
        pos = None

    # Build results
    equity = pd.Series(equity_curve, index=pd.Index(equity_times, name="time")).sort_index()
    trades_df = pd.DataFrame(trades)

    stats = compute_stats(trades_df, equity, starting_balance, balance)

    return trades_df, equity, stats


# =========================
# Stats
# =========================
def compute_stats(trades_df: pd.DataFrame, equity: pd.Series, start_bal: float, end_bal: float):
    if trades_df.empty:
        return {
            "start_balance": start_bal,
            "end_balance": end_bal,
            "net_profit": end_bal - start_bal,
            "num_trades": 0
        }

    pnl = trades_df["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    win_rate = (pnl > 0).mean()
    profit_factor = wins.sum() / abs(losses.sum()) if len(losses) else np.inf

    # Max drawdown from equity curve
    eq = equity.astype(float)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = dd.min()

    avg_pnl = pnl.mean()
    median_pnl = pnl.median()

    return {
        "start_balance": float(start_bal),
        "end_balance": float(end_bal),
        "net_profit": float(end_bal - start_bal),
        "num_trades": int(len(trades_df)),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "avg_pnl": float(avg_pnl),
        "median_pnl": float(median_pnl),
        "max_drawdown_pct": float(max_dd * 100.0),
    }


# =========================
# Example usage
# =========================
def start_backtest(symbol):
    time_frame = 'M1'
    prev_candle_size = 99000
    df = get_live_data(symbol=symbol, time_frame=time_frame, prev_n_candles=prev_candle_size)

    # Try to parse time column if it's string
    if df["time"].dtype == object:
        df["time"] = pd.to_datetime(df["time"])

    trades, equity, stats = backtest_ema_R(
        df,
        spread_abs=5.0,              # example: $5 spread
        commission_per_side=0.0,     # set your broker commission here
        contract_size=0.05,
        tie_break="worst",
    )

    print("=== STATS ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    print("\n=== LAST 10 TRADES ===")
    print(trades.tail(10))

    # Plot equity curve
    plt.figure()
    plt.plot(equity.index, equity.values)
    plt.title("Equity Curve")
    plt.xlabel("Time")
    plt.ylabel("Equity")
    plt.show()
