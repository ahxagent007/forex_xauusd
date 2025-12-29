import time

from utils.indicators import ema
from utils.mt5_utils import get_live_data, trade_order_wo_tp_sl, close_all_positions, move_sl_to_be, \
    get_positions, calculate_atr, atr_sl_tp, set_sl_tp


def per_min_ema(symbol):
    time_frame = 'M1'

    prices = {
        's1': None,
        's2': 0,
        's3': 0
    }
    while True:
        df = get_live_data(symbol=symbol, time_frame=time_frame, prev_n_candles=300)

        df['EMA_10'] = ema(df, 10)
        df['EMA_200'] = ema(df, 200)

        current_price = df['close'].iloc[-1]
        current_ema_10 = df['EMA_10'].iloc[-2]
        current_ema_200 = df['EMA_200'].iloc[-2]

        if current_price > current_ema_200:
            ema_200_signal = 'buy'
        elif current_price < current_ema_200:
            ema_200_signal = 'sell'
        else:
            ema_200_signal = None

        if prices['s1'] is None:
            prices['s1'] = current_price
            prices['s2'] = current_price
            prices['s3'] = current_price
        else:
            prices['s3'] = prices['s2']
            prices['s2'] = prices['s1']
            prices['s1'] = current_price

        if (prices['s1'] > current_ema_10 and prices['s2'] < current_ema_10) or \
            (prices['s1'] > current_ema_10 and prices['s3'] < current_ema_10):
            ema_cross_signal = 'buy'
        elif (prices['s1'] < current_ema_10 and prices['s2'] > current_ema_10) or \
            (prices['s1'] < current_ema_10 and prices['s3'] > current_ema_10):
            ema_cross_signal = 'sell'
        else:
            ema_cross_signal = None
        #print(current_ema_10, current_ema_200)
        #print(prices)

        if ema_cross_signal is not None:
            lot = 0.1
            trade_order_wo_tp_sl(symbol, lot, ema_cross_signal, False)

            ## SET SL TP BASED ON ATR
            running_trade = get_positions(symbol)[0]
            atr = calculate_atr(df)
            sl, tp = atr_sl_tp(running_trade.price, running_trade.type, atr, sl_mult=1.3, tp_mult=3.0)
            set_sl_tp(running_trade, sl, tp)

            k = 0
            for i in range(0,30):
                if get_positions(symbol)[0].profit > 2:
                    move_sl_to_be(get_positions(symbol)[0])
                    break
                time.sleep(1)
                k += 1

            time.sleep(30-k)

            prev_profit = 0
            while True:
                positions = get_positions(symbol)
                if len(positions)<1:
                    break
                running_profit = positions[0].profit
                print(prev_profit, running_profit)
                if running_profit > prev_profit:
                    prev_profit = running_profit
                    time.sleep(30)
                else:
                    break

            close_all_positions(symbol)
            prices = {
                's1': None,
                's2': 0,
                's3': 0
            }

        time.sleep(1)

