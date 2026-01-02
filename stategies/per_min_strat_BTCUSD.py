"""
EMA scalping bot (MT5) with TRUE R-based management:
- SL from ATR
- TP at 2R (exact)
- Partial close at 1R
- Move SL to BE after partial (same moment)
- Trail SL by ATR after BE

Notes:
- Uses CLOSED candles for signals (no repaint)
- Uses tick Bid/Ask for realistic RR checks (important for BTC)
- Partial close respects volume_min / volume_step
"""

import time
import math
import MetaTrader5 as mt5

from utils.indicators import ema
from utils.mt5_utils import (
    get_live_data,
    get_positions,
    calculate_atr,
    calculate_lot_size,
    trade_order_price,
    move_sl_to_be,
    move_sl,
)

BUY = 0
SELL = 1


# ----------------------------
# MT5 helpers
# ----------------------------
def _ensure_symbol(symbol: str) -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")


def _tick(symbol: str):
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        raise RuntimeError(f"symbol_info_tick({symbol}) failed: {mt5.last_error()}")
    return t


def _symbol_volume_rules(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) failed: {mt5.last_error()}")
    return float(info.volume_min), float(info.volume_step), float(info.volume_max)


def _round_volume_down(symbol: str, vol: float) -> float:
    """
    Round DOWN to volume_step, clamp to [min, max].
    Returns 0.0 if below min volume.
    """
    vmin, vstep, vmax = _symbol_volume_rules(symbol)

    vol = max(min(float(vol), vmax), 0.0)
    if vol < vmin:
        return 0.0

    # round down to step
    steps = math.floor((vol - vmin) / vstep + 1e-12)
    rounded = vmin + steps * vstep

    rounded = max(min(rounded, vmax), vmin)
    return float(f"{rounded:.8f}")


# -----------------------------------
# Partial close by sending opposite deal
# -----------------------------------
def close_position(pos, close_vol: float, deviation: int = 200, magic: int = 0, comment: str = "partial_close"):
    symbol = getattr(pos, "symbol", None)
    ticket = getattr(pos, "ticket", None)
    ptype = getattr(pos, "type", None)
    pvol = float(getattr(pos, "volume", 0.0))

    if not symbol or ticket is None or ptype is None or pvol <= 0:
        raise ValueError("pos must have symbol, ticket, type, volume")

    _ensure_symbol(symbol)

    # clamp + round
    req_vol = min(float(close_vol), pvol)
    req_vol = _round_volume_down(symbol, req_vol)
    if req_vol <= 0:
        raise ValueError(f"Requested close_vol too small after rounding for {symbol}")

    t = _tick(symbol)
    if ptype == BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = t.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = t.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": req_vol,
        "type": order_type,
        "position": int(ticket),
        "price": float(price),
        "deviation": int(deviation),
        "magic": int(magic),
        "comment": str(comment),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,  # common for crypto CFDs
    }

    result = mt5.order_send(request)
    if result is None:
        raise RuntimeError(f"order_send returned None: {mt5.last_error()}")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"Close failed retcode={result.retcode}, comment={result.comment}, last_error={mt5.last_error()}")
    return result


# ----------------------------
# R helpers
# ----------------------------
def _profit_in_R(pos, exit_price: float, r_price: float) -> float:
    if r_price <= 0:
        return 0.0
    if pos.type == BUY:
        return (exit_price - pos.price_open) / r_price
    else:
        return (pos.price_open - exit_price) / r_price


def _sl_tp_from_atr_and_R(entry: float, trade_type: int, atr: float, sl_atr_mult: float, tp_rr: float):
    """
    SL = entry +/- ATR*sl_atr_mult
    TP = entry +/- (tp_rr * R), where R = |entry - SL|
    This makes TP exactly tp_rr * R (e.g. 2R).
    """
    if atr is None or atr <= 0:
        raise ValueError("ATR invalid")

    if trade_type == BUY:
        sl = entry - atr * sl_atr_mult
        r = abs(entry - sl)
        tp = entry + tp_rr * r
    else:
        sl = entry + atr * sl_atr_mult
        r = abs(entry - sl)
        tp = entry - tp_rr * r

    return sl, tp


def _atr_trailing_sl(pos, ref_price: float, atr: float, atr_mult: float):
    if atr is None or atr <= 0:
        return None
    if pos.type == BUY:
        return ref_price - atr * atr_mult
    else:
        return ref_price + atr * atr_mult


# ----------------------------
# Main Strategy
# ----------------------------
def per_min_ema(symbol: str = "BTCUSD"):
    time_frame = "M1"

    # ===== Tunables you requested =====
    TP_RR = 2.0                 # TP at 2R (true R-based)
    PARTIAL_RR = 1.0            # take partial profit at +1R
    PARTIAL_FRACTION = 0.5      # close 50% at +1R

    SL_ATR_MULT = 1.3           # SL distance from ATR
    TRAIL_ATR_MULT = 1.0        # trailing aggressiveness (after BE/partial)
    MOVE_BE_AFTER_PARTIAL = True

    # Trend filter (recommended)
    USE_EMA200_FILTER = True

    # execution
    LOOP_SLEEP = 0.25
    COOLDOWN_AFTER_ENTRY = 1.0

    # per-ticket state
    trade_state = {}  # ticket -> {"r_price": float, "partial_done": bool, "be_done": bool}
    last_closed_bar_time = None

    _ensure_symbol(symbol)

    while True:
        df = get_live_data(symbol=symbol, time_frame=time_frame, prev_n_candles=350)
        if df is None or len(df) < 210:
            time.sleep(1)
            continue

        # act once per NEW closed candle
        closed_time = df["time"].iloc[-2]
        if closed_time == last_closed_bar_time:
            time.sleep(LOOP_SLEEP)
            continue
        last_closed_bar_time = closed_time

        # indicators on history
        df["EMA_10"] = ema(df, 10)
        df["EMA_200"] = ema(df, 200)

        close_prev = df["close"].iloc[-3]
        close_last = df["close"].iloc[-2]
        ema10_prev = df["EMA_10"].iloc[-3]
        ema10_last = df["EMA_10"].iloc[-2]
        ema200_last = df["EMA_200"].iloc[-2]

        # cross on closed candles
        cross_up = (close_prev <= ema10_prev) and (close_last > ema10_last)
        cross_dn = (close_prev >= ema10_prev) and (close_last < ema10_last)
        signal = "buy" if cross_up else "sell" if cross_dn else None

        # trend filter
        trend = None
        if USE_EMA200_FILTER:
            if close_last > ema200_last:
                trend = "buy"
            elif close_last < ema200_last:
                trend = "sell"

        atr = calculate_atr(df)

        # ----------------------------
        # Manage open positions
        # ----------------------------
        positions = get_positions(symbol)
        open_tickets = {p.ticket for p in positions}
        for ticket in list(trade_state.keys()):
            if ticket not in open_tickets:
                trade_state.pop(ticket, None)

        t = _tick(symbol)
        bid, ask = t.bid, t.ask

        for pos in positions:
            sl_price = getattr(pos, "sl", None)
            if sl_price is None or sl_price == 0:
                continue

            # realistic exit price
            exit_price = bid if pos.type == BUY else ask

            # init state
            if pos.ticket not in trade_state:
                r_price = abs(pos.price_open - sl_price)
                trade_state[pos.ticket] = {"r_price": r_price, "partial_done": False, "be_done": False}

            st = trade_state[pos.ticket]
            rr = _profit_in_R(pos, exit_price, st["r_price"])

            # Partial close at +1R (once)
            if (not st["partial_done"]) and rr >= PARTIAL_RR:
                vmin, _, _ = _symbol_volume_rules(symbol)

                # only partial close if enough size
                if pos.volume >= 2.0 * vmin:
                    target_close = pos.volume * PARTIAL_FRACTION
                    close_vol = _round_volume_down(symbol, target_close)

                    # must be valid and less than full volume
                    if close_vol >= vmin and close_vol < pos.volume:
                        close_position(pos, close_vol, deviation=200, comment="partial_close_1R")

                st["partial_done"] = True

                # Move SL to BE right after partial (recommended)
                if MOVE_BE_AFTER_PARTIAL and (not st["be_done"]):
                    move_sl_to_be(pos)
                    st["be_done"] = True

            # If you prefer BE at +1R even without partial, uncomment:
            # if (not st["be_done"]) and rr >= 1.0:
            #     move_sl_to_be(pos)
            #     st["be_done"] = True

            # Trail SL by ATR AFTER BE (or after partial)
            if st["be_done"]:
                ref_price = bid if pos.type == BUY else ask
                new_sl = _atr_trailing_sl(pos, ref_price, atr, TRAIL_ATR_MULT)
                if new_sl is None:
                    continue

                # only tighten
                if pos.type == BUY:
                    if new_sl > pos.sl:
                        move_sl(pos, new_sl)
                else:
                    if new_sl < pos.sl:
                        move_sl(pos, new_sl)

        # ----------------------------
        # Entry logic (one position at a time)
        # ----------------------------
        if len(positions) == 0 and signal is not None:
            if USE_EMA200_FILTER:
                if trend is None or signal != trend:
                    time.sleep(LOOP_SLEEP)
                    continue

            trade_type = BUY if signal == "buy" else SELL

            # stable entry reference (last closed candle)
            entry_ref = close_last

            # TRUE 2R TP based on ATR-derived SL
            sl, tp = _sl_tp_from_atr_and_R(
                entry=entry_ref,
                trade_type=trade_type,
                atr=atr,
                sl_atr_mult=SL_ATR_MULT,
                tp_rr=TP_RR,
            )

            lot = calculate_lot_size(symbol, abs(entry_ref - sl))
            trade_order_price(symbol, tp, sl, lot, signal)

            time.sleep(COOLDOWN_AFTER_ENTRY)

        time.sleep(LOOP_SLEEP)


