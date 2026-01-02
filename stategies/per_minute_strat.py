import time

from utils.indicators import ema
from utils.mt5_utils import (
    get_live_data,
    get_positions,
    calculate_atr,
    atr_sl_tp,
    calculate_lot_size,
    trade_order_price,
    move_sl_to_be,
    move_sl,
    close_position,
)

BUY = 0
SELL = 1


def _profit_in_R(pos, current_price: float, r_price: float) -> float:
    """
    Return current profit in 'R' units using price movement / initial SL distance (r_price).
    """
    if r_price <= 0:
        return 0.0

    if pos.type == BUY:
        return (current_price - pos.price_open) / r_price
    else:
        return (pos.price_open - current_price) / r_price


def _atr_trailing_sl(pos, current_price: float, atr: float, atr_mult: float = 1.0):
    """
    Compute a trailing SL using ATR.
    For BUY: trail below price.
    For SELL: trail above price.
    """
    if atr is None or atr <= 0:
        return None

    if pos.type == BUY:
        return current_price - (atr * atr_mult)
    else:
        return current_price + (atr * atr_mult)


def per_min_ema(symbol: str):
    time_frame = "M1"

    # Per-position state
    trade_state = {}  # ticket -> dict(r_price, moved_be, partial_closed)

    # New candle gate
    last_closed_bar_time = None

    # Tunables
    sl_mult = 1.3
    tp_mult = 2.0            # scalping-friendly default; adjust as you like
    atr_trail_mult = 1.0     # trailing aggressiveness (1.0 = 1x ATR)
    partial_close_rr = 1.0   # partial close at +1.5R
    be_rr = 1.0              # move to BE at +1R
    partial_close_fraction = 0.5  # close 50% at +1.5R

    while True:
        df = get_live_data(symbol=symbol, time_frame=time_frame, prev_n_candles=300)
        if df is None or len(df) < 210:
            time.sleep(1)
            continue

        # Use ONLY closed candles for signals/ATR/EMA
        closed_time = df["time"].iloc[-2]  # last closed candle timestamp
        if closed_time == last_closed_bar_time:
            time.sleep(0.3)
            continue
        last_closed_bar_time = closed_time

        # Indicators (computed on candle history)
        df["EMA_10"] = ema(df, 10)
        df["EMA_200"] = ema(df, 200)

        close_prev = df["close"].iloc[-3]
        close_last = df["close"].iloc[-2]
        ema10_prev = df["EMA_10"].iloc[-3]
        ema10_last = df["EMA_10"].iloc[-2]
        ema200_last = df["EMA_200"].iloc[-2]

        # Trend filter using EMA200 (closed candle)
        trend = "buy" if close_last > ema200_last else "sell" if close_last < ema200_last else None

        # Stable cross detection (closed candles only)
        cross_up = (close_prev <= ema10_prev) and (close_last > ema10_last)
        cross_dn = (close_prev >= ema10_prev) and (close_last < ema10_last)

        signal = None
        if cross_up:
            signal = "buy"
        elif cross_dn:
            signal = "sell"

        # === POSITION MANAGEMENT: BE @ +1R, partial @ +1.5R, ATR trail ===
        positions = get_positions(symbol)

        # For management, it's better to use live bid/ask/tick price.
        # If you have a tick function, replace `current_price = close_last` with it.
        current_price = close_last

        atr = calculate_atr(df)  # ATR based on history (your util)
        for pos in positions:
            # Initialize state for this ticket
            if pos.ticket not in trade_state:
                # Initial R distance based on original SL distance (price units)
                # If SL missing, we can’t do R-based logic safely.
                if getattr(pos, "sl", None) is None or pos.sl == 0:
                    continue
                r_price = abs(pos.price_open - pos.sl)
                trade_state[pos.ticket] = {
                    "r_price": r_price,
                    "moved_be": False,
                    "partial_closed": False,
                }

            st = trade_state[pos.ticket]
            r_price = st["r_price"]
            rr = _profit_in_R(pos, current_price, r_price)

            # 1) Move SL to BE at +1R
            if (not st["moved_be"]) and rr >= be_rr:
                move_sl_to_be(pos)
                st["moved_be"] = True

            # 2) Partial close at +1.5R (once)
            if (not st["partial_closed"]) and rr >= partial_close_rr:
                vol = getattr(pos, "volume", None)
                if vol is not None and vol > 0:
                    close_vol = max(vol * partial_close_fraction, 0.01)  # 0.01 as common minimum
                    try:
                        # If your close_position supports volume:
                        close_position(pos, close_vol)  # <-- adjust if your signature differs
                        st["partial_closed"] = True
                    except TypeError:
                        # Fallback: if close_position(pos) only closes full, you need to implement a partial-close util.
                        # You can replace this with your own partial-close function.
                        # close_position(pos)  # WARNING: this would close the whole trade
                        st["partial_closed"] = True

            # 3) Trail SL by ATR (keep it from moving backward)
            # Typically you trail after BE (or after partial) to avoid getting wicked out early.
            if st["moved_be"]:
                new_sl = _atr_trailing_sl(pos, current_price, atr, atr_mult=atr_trail_mult)
                if new_sl is None:
                    continue

                # Only tighten SL, never loosen
                if pos.type == BUY:
                    if new_sl > pos.sl:
                        move_sl(pos, new_sl)
                else:
                    if new_sl < pos.sl:
                        move_sl(pos, new_sl)

        # Cleanup state for closed tickets
        open_tickets = {p.ticket for p in positions}
        for ticket in list(trade_state.keys()):
            if ticket not in open_tickets:
                trade_state.pop(ticket, None)

        # === ENTRY LOGIC (only if no open positions) ===
        if len(positions) == 0 and signal is not None and trend is not None and signal == trend:
            trade_type = BUY if signal == "buy" else SELL

            # Entry reference = last closed candle close (stable).
            # If you want exact market entry price, you need tick bid/ask.
            entry_price_ref = close_last

            atr_for_entry = calculate_atr(df)
            sl, tp = atr_sl_tp(entry_price_ref, trade_type, atr_for_entry, sl_mult=sl_mult, tp_mult=tp_mult)

            lot = calculate_lot_size(symbol, abs(entry_price_ref - sl))
            trade_order_price(symbol, tp, sl, lot, signal)

        time.sleep(0.2)
