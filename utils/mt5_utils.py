import json
import os

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import matplotlib.  pyplot as plt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import datetime as dt
from scipy.signal import argrelextrema
from dotenv import load_dotenv

load_dotenv()

def print_time():
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))

def get_magic_number():
    with open('magic_number.json') as json_file:
        data = json.load(json_file)
        magic_number = data['magic_number']
        magic_number += 1
        data = {
            'magic_number': magic_number
        }
    json_file.close()

    with open('magic_number.json', 'w') as outfile:
        json.dump(data, outfile)
    json_file.close()

    return magic_number


def initialize_mt5():
    path = os.getenv("MT5_PATH")

    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    timeout = 10000
    portable = False
    if mt5.initialize(path=path, login=login, password=password, server=server, timeout=timeout, portable=portable):
        print("Initialization successful")
    else:
        print('Initialize failed')

    return mt5

def initialize_mt5_4000():
    path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

    # # NEW ACC LIVE
    login = 181244000
    password = 'ABCabc123!@#'
    server = 'Exness-MT5Trial6'
    #
    # # ## PRO NEW
    # login = 182331894
    # password = 'ABCabc123!@#'
    # server = 'Exness-MT5Trial6'

    timeout = 10000
    portable = False
    if mt5.initialize(path=path, login=login, password=password, server=server, timeout=timeout, portable=portable):
        print("Initialization successful")
    else:
        print('Initialize failed')


def MT5_error_code(code):
    # error codes ==> https://mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
    mt5_error = {
        '10019': 'Not Enough Money',
        '10016': 'Invalid SL',
        '10027': 'Autotrading Disabled',
        '10014': 'Invalid volume in the request',
        '10030': 'Invalid order filling type',
        '10021': 'There are no quotes to process the request',
        '10018': 'Market is closed'
    }

    try:
        error = mt5_error[str(code)]
    except:
        error = None
    return error

def get_live_data(symbol, time_frame, prev_n_candles):

    if time_frame == 'M1':
        TIME_FRAME = mt5.TIMEFRAME_M1
    elif time_frame == 'M5':
        TIME_FRAME = mt5.TIMEFRAME_M5
    elif time_frame == 'M2':
        TIME_FRAME = mt5.TIMEFRAME_M2
    elif time_frame == 'M10':
        TIME_FRAME = mt5.TIMEFRAME_M10
    elif time_frame == 'M15':
        TIME_FRAME = mt5.TIMEFRAME_M15
    elif time_frame == 'M30':
        TIME_FRAME = mt5.TIMEFRAME_M30
    elif time_frame == 'H1':
        TIME_FRAME = mt5.TIMEFRAME_H1
    elif time_frame == 'H2':
        TIME_FRAME = mt5.TIMEFRAME_H2
    elif time_frame == 'H4':
        TIME_FRAME = mt5.TIMEFRAME_H4
    elif time_frame == 'D1':
        TIME_FRAME = mt5.TIMEFRAME_D1
    elif time_frame == 'W1':
        TIME_FRAME = mt5.TIMEFRAME_W1

    PREV_N_CANDLES = prev_n_candles

    rates = mt5.copy_rates_from_pos(symbol, TIME_FRAME, 0, PREV_N_CANDLES)

    ticks_frame = pd.DataFrame(rates)
    #ticks_frame['time'] = pd.to_datetime(ticks_frame['time'], unit='s')

    return ticks_frame

def get_prev_data(symbol, time_frame, prev_start_min, prev_end_min):

    if time_frame == 'M1':
        TIME_FRAME = mt5.TIMEFRAME_M1
    elif time_frame == 'M5':
        TIME_FRAME = mt5.TIMEFRAME_M5
    elif time_frame == 'M10':
        TIME_FRAME = mt5.TIMEFRAME_M10
    elif time_frame == 'M15':
        TIME_FRAME = mt5.TIMEFRAME_M15
    elif time_frame == 'M30':
        TIME_FRAME = mt5.TIMEFRAME_M30
    elif time_frame == 'H1':
        TIME_FRAME = mt5.TIMEFRAME_H1
    elif time_frame == 'H4':
        TIME_FRAME = mt5.TIMEFRAME_H4
    elif time_frame == 'D1':
        TIME_FRAME = mt5.TIMEFRAME_D1

    #rates = mt5.copy_rates_from(symbol, TIME_FRAME, datetime.today(), PREV_N_CANDLES)
    rates = mt5.copy_rates_range(symbol, TIME_FRAME,
                                 datetime.now() - timedelta(minutes=prev_start_min),
                                 datetime.now() - timedelta(minutes=prev_end_min))


    ticks_frame = pd.DataFrame(rates)
    print(ticks_frame.head())

    ticks_frame['time'] = pd.to_datetime(ticks_frame['time'], unit='s')

    return ticks_frame

def trade_order(symbol, tp_point, sl_point, lot, action, magic=False):

    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = price + tp_point * point
            sl = price - sl_point * point
        else:
            sl = price - sl_point * point

    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = price - tp_point * point
            sl = price + sl_point * point
        else:
            sl = price + sl_point * point

    deviation = 20
    MAGIC_NUMBER = get_magic_number()
    if tp_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action,
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            # "type_time": mt5.ORDER_TIME_GTC,
            # "type_filling": mt5.ORDER_FILLING_IOC,
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol, MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def get_symbol_point(symbol):
    return mt5.symbol_info(symbol).point

def modify_position(order_number, symbol, new_stop_loss):
    print_time()
    # Create the request
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "sl": new_stop_loss,
        "position": order_number
    }
    # Send order to MT5
    order_result = mt5.order_send(request)
    if order_result[0] == 10009:
        print('ORDER UPDATED', order_number, symbol, new_stop_loss)
        return True
    else:
        print('ORDER UPDATE FAILED !!! ! !! ! ! ')
        print(order_result)
        return False
def trade_order_wo_sl(symbol, tp_point, lot, action, magic=False):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = price + tp_point * point


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = price - tp_point * point


    print(symbol, 'Spread pip: ', spread)


    deviation = 20
    MAGIC_NUMBER = get_magic_number()
    if tp_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "tp": tp,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            # "type_time": mt5.ORDER_TIME_GTC,
            # "type_filling": mt5.ORDER_FILLING_IOC,
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol, MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))
def trade_order_wo_tp(symbol, sl_point, lot, action, magic=False):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if sl_point:
            sl = price - sl_point * point


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if sl_point:
            sl = price + sl_point * point


    print(symbol, 'Spread pip: ', spread)

    spread_dict = {
        'EURUSD': 15,
        'EURJPY': 15,
        'USDJPY': 15,
        'XAUUSD': 150,
        'BTCUSD': 2300,
        'GBPUSD': 15,
        'AUDUSD': 15,
        'NZDUSD': 15,
        'USDCHF': 15,
        'EURGBP': 15,
        'USDCAD': 15,
    }



    deviation = 20
    MAGIC_NUMBER = get_magic_number()
    if sl_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action,
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol, MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))
def trade_order_wo_tp_price(symbol, sl, lot, action, magic=False):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

    print(symbol, 'Spread pip: ', spread)

    spread_dict = {
        'EURUSD': 15,
        'EURJPY': 15,
        'USDJPY': 15,
        'XAUUSD': 150,
        'BTCUSD': 2300,
        'GBPUSD': 15,
        'AUDUSD': 15,
        'NZDUSD': 15,
        'USDCHF': 15,
        'EURGBP': 15,
        'USDCAD': 15,
    }

    if spread > spread_dict[symbol]:
        print('High Spread')
        return None

    deviation = 20
    MAGIC_NUMBER = get_magic_number()

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": type,
        "price": price,
        "sl": sl,
        "deviation": deviation,
        "magic": MAGIC_NUMBER,
        "comment": action,
        # "type_time": mt5.ORDER_TIME_GTC,
        # "type_filling": mt5.ORDER_FILLING_IOC,
    }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))
            if result.retcode == 10019:
                # NOT ENOUGH MONEY
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": lot/2,
                    "type": type,
                    "price": price,
                    "sl": sl,
                    "deviation": deviation,
                    "magic": MAGIC_NUMBER,
                    "comment": action,
                    # "type_time": mt5.ORDER_TIME_GTC,
                    # "type_filling": mt5.ORDER_FILLING_IOC,
                }
                print(request)
                # send a trading request
                result = mt5.order_send(request)
                print(result)

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol, MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def trade_order_wo_tp_sl(symbol, lot, action, magic=False):

    #print(action)
    spread = 0
    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point
    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

    spread_dict = {
        'EURUSD': 15,
        'EURJPY': 15,
        'USDJPY': 15,
        'XAUUSD': 130,
        'BTCUSD': 1600,
        'GBPUSD': 15,
        'AUDUSD': 15,
        'NZDUSD': 15,
        'USDCHF': 15,
        'EURGBP': 15,
        'USDCAD': 15,
        'US30': 20
    }

    if spread > spread_dict[symbol]:
        print('!! HIGH spread ', spread)

    deviation = 20

    MAGIC_NUMBER = 3669

    request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action
        }
    #print(request)
    # send a trading request
    result = mt5.order_send(request)
    #print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol, ' LOT: ', lot)## update magic number
            if magic:
                update_magic_number(symbol, MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def trade_order_magic(symbol, tp_point, sl_point, lot, action, magic=False, code=0, MAGIC_NUMBER=0):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = price + tp_point * point
            sl = price - sl_point * point


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = price - tp_point * point
            sl = price + sl_point * point
    else:
        return None


    print(symbol, 'Spread pip: ', spread)

    spread_dict = {
        'BTCUSD': 2020,
        'EURUSD': 10,
        'AUDUSD': 10,
        'GBPUSD': 10,
        'NZDUSD': 15,
        'EURCHF': 20,
        'GBPCHF': 20,
        'AUDCHF': 20,
        'USDCHF': 15,
        'AUDCAD': 20,
        'NZDCAD': 20,
        'USDCAD': 15,
        'EURCAD': 30,
        'GBPCAD': 35,
        'EURNZD': 40,
        'EURGBP': 15,
        'EURAUD': 30,
        'GBPNZD': 45,
        'CADJPY': 30,
        'USDJPY': 10,
        'EURJPY': 20,
        'GBPJPY': 20,
        'CHFJPY': 30,
        'AUDJPY': 20,
        'XAUUSD': 120
    }

    if spread > spread_dict[symbol]:
        print('High Spread')
        return None

    deviation = 20
    # MAGIC_NUMBER = get_magic_number()
    if tp_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": type,
            "price": price,
            "tp": tp,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action,
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": type,
            "price": price,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": action,
            # "type_time": mt5.ORDER_TIME_GTC,
            # "type_filling": mt5.ORDER_FILLING_IOC,
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol+str(code), MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def trade_order_magic_value(symbol, tp_point, sl_value, lot, action, magic=False, code=0, MAGIC_NUMBER=0):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = price + tp_point * point
            sl = sl_value


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = price - tp_point * point
            sl = sl_value


    print(symbol, 'Spread pip: ', spread)

    spread_dict = {
        'EURUSD': 15,
        'XAUUSD': 150,
        'BTCUSD': 2000,
        'USDJPY': 15,
        'GBPUSD': 15,
        'EURJPY': 20
    }

    if spread > spread_dict[symbol]:
        print('High Spread')
        return None
    if tp_point <= spread:
        print('LOW TP !!!!!!')
        return None

    deviation = 20
    # MAGIC_NUMBER = get_magic_number()
    if tp_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "tp": tp,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "sl": sl,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            # "type_time": mt5.ORDER_TIME_GTC,
            # "type_filling": mt5.ORDER_FILLING_IOC,
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol+str(code), MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def trade_order_price(symbol, tp_price, sl_price, lot, action, magic=False, code=0, MAGIC_NUMBER=0):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point



    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point


    deviation = 20
    # MAGIC_NUMBER = get_magic_number()
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": type,
        "price": price,
        "tp": tp_price,
        "sl": sl_price,
        "deviation": deviation,
        "magic": MAGIC_NUMBER,
        "comment": "python script open",
        # "type_time": mt5.ORDER_TIME_GTC,
        # "type_filling": mt5.ORDER_FILLING_IOC,
    }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol+str(code), MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def trade_order_wo_sl_magic(symbol, tp_point, lot, action, magic=False, code=0):


    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid
        type = mt5.ORDER_TYPE_BUY

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = price + tp_point * point


    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = price - tp_point * point


    print(symbol, 'Spread pip: ', spread)

    spread_dict = {
        'EURUSD': 15,
        'XAUUSD': 150,
        'BTCUSD': 1900
    }

    if spread > spread_dict[symbol]:
        print('High Spread')
        return None

    deviation = 20
    MAGIC_NUMBER = get_magic_number()
    if tp_point:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "tp": tp,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            #"type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
        }
    else:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": type,
            "price": price,
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "python script open",
            # "type_time": mt5.ORDER_TIME_GTC,
            # "type_filling": mt5.ORDER_FILLING_IOC,
        }
    print(request)
    # send a trading request
    result = mt5.order_send(request)
    print(result)

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print('>>>>>>>>>>>> ## ## ## '+action+' done with bot ', symbol)## update magic number
            if magic:
                update_magic_number(symbol+str(code), MAGIC_NUMBER)
    except Exception as e:
        print('Result '+action+' >> ', str(e))

def get_order_positions_count(symbol):
    try:
        return len(mt5.positions_get(symbol=symbol))
    except:
        return 0

def get_all_positions(symbol):
    return mt5.positions_get(symbol=symbol)

def close_position(symbol, ticket):
    mt5.Close(symbol, ticket=ticket)

def close_all_positions(symbol):
    positions = get_all_positions(symbol)
    for pos in positions:
        close_position(symbol, pos.ticket)
def update_magic_number(symbol, MAGIC_NUMBER):
    #print('updating',symbol,MAGIC_NUMBER)
    file_name = 'time_counts/trade_number.json'
    json_data = {}
    with open(file_name) as json_file:
        json_data = json.load(json_file)

    json_data[symbol] = MAGIC_NUMBER

    with open(file_name, 'w') as outfile:
        json.dump(json_data, outfile)

def get_current_price(symbol):
    # Get current price
    price_info = mt5.symbol_info_tick(symbol)

    # Check if price information is retrieved successfully
    if price_info is None:
        print(f"Failed to get price information for {symbol}, error code =", mt5.last_error())
        return None

    # Extract bid and ask prices
    bid_price = price_info.bid
    ask_price = price_info.ask

    # Print the current bid and ask prices
    # print(f"Current bid price for {symbol}: {bid_price}")
    # print(f"Current ask price for {symbol}: {ask_price}")
    data = {
        'bid_price': bid_price,
        'ask_price': ask_price
    }

    return data

def get_balance():
    balance = mt5.account_info().balance
    return balance

def convert_price_diff_to_pips(symbol, price_diff):
    point = mt5.symbol_info(symbol).point
    return price_diff / point

def get_open_positions():
    # Get position objects
    positions = mt5.positions_get()
    # Return position objects
    return positions

def get_positions(symbol):
    # Get position objects
    positions = mt5.positions_get(symbol=symbol)
    # Return position objects
    return positions

def trade_with_price(action, symbol, lot, tp_price, sl_price):
    print(action, symbol, lot, tp_price, sl_price)
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    if action == 'buy':
        # Get current ask price
        tick = mt5.symbol_info_tick(symbol)
        ask_price = tick.ask

        # Build order request
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY,
            "price": ask_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": 69,
            "comment": "Buy with ORB"
        }
    elif action == 'sell':
        # Get current ask price
        tick = mt5.symbol_info_tick(symbol)
        ask_price = tick.bid

        # Build order request
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_SELL,
            "price": ask_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": 69,
            "comment": "SELL with ORB"
        }

    # Send the order
    result = mt5.order_send(order)
    #print('RESULT >>>>>>>>>>>>>> ',result)
    if result is None:
        print("❌ order_send() failed:", mt5.last_error())
        return

    try:
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(symbol, ' ', action+' not done', result.retcode, MT5_error_code(result.retcode))

        else:
            print("✅ order placed successfully")
            print("Order ticket:", result.order)
    except Exception as e:
        print('Result '+action+' >> ', str(e))
        print("❌ Order failed:", result.retcode)

    # # Check the result
    # if result.retcode == mt5.TRADE_RETCODE_DONE:
    #     print("✅ Buy order placed successfully")
    #     print("Order ticket:", result.order)
    # else:
    #     print("❌ Order failed:", result.retcode)


def trade_limit_with_price(action, symbol, lot, entry_price, tp_price, sl_price):
    print(action, symbol, lot, entry_price, tp_price, sl_price)
    if action == 'buy':
        # === Send BUY LIMIT Order ===
        order = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY_LIMIT,
            "price": entry_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": 28072023,
            "comment": "ORB BUY LIMIT",
            "type_time": mt5.ORDER_TIME_GTC,  # Good Till Canceled
            "type_filling": mt5.ORDER_FILLING_RETURN  # Required for pending orders
        }
    elif action == 'sell':
        # === Send BUY LIMIT Order ===
        order = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_SELL_LIMIT,
            "price": entry_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": 28072023,
            "comment": "ORB SELL LIMIT",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN
        }

    # Send order
    result = mt5.order_send(order)
    #print('RESULT >>>>>>>>>>>>>> ', result)
    if result is None:
        print("❌ order_send() failed:", mt5.last_error())
        return
    # === Result ===
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print("✅ LIMIT order placed successfully")
    else:
        print(f"❌ Failed to place order. Error code: {result.retcode}")
def trade_limit_with_point(action, symbol, lot, entry_price, tp_point, sl_point):
    print(action, symbol, lot, entry_price, tp_point, sl_point)
    if action == 'buy':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        bid_price = mt5.symbol_info_tick(symbol).bid

        spread = abs(price - bid_price) / point

        if tp_point:
            tp = entry_price + tp_point * point
            sl = entry_price - sl_point * point
        # === Send BUY LIMIT Order ===
        order = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY_LIMIT,
            "price": entry_price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 28072023,
            "comment": "ORB BUY LIMIT",
            "type_time": mt5.ORDER_TIME_GTC,  # Good Till Canceled
            "type_filling": mt5.ORDER_FILLING_RETURN  # Required for pending orders
        }
    elif action == 'sell':
        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        ask_price = mt5.symbol_info_tick(symbol).ask
        type = mt5.ORDER_TYPE_SELL

        spread = abs(price - ask_price) / point

        if tp_point:
            tp = entry_price - tp_point * point
            sl = entry_price + sl_point * point
        # === Send BUY LIMIT Order ===
        order = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_SELL_LIMIT,
            "price": entry_price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 28072023,
            "comment": "ORB SELL LIMIT",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN
        }

    # Send order
    result = mt5.order_send(order)
    #print('RESULT >>>>>>>>>>>>>> ', result)
    if result is None:
        print("❌ order_send() failed:", mt5.last_error())
        return
    # === Result ===
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print("✅ LIMIT order placed successfully")
    else:
        print(f"❌ Failed to place order. Error code: {result.retcode}")

def cancel_all_pending_orders():
    # Get all pending orders
    pending_orders = mt5.orders_get()

    if pending_orders is None:
        print("❌ Failed to retrieve orders:", mt5.last_error())
        return

    print(f"📦 Found {len(pending_orders)} total orders")

    # Loop and cancel only pending orders
    for order in pending_orders:
        if order.type in [
            mt5.ORDER_TYPE_BUY_LIMIT,
            mt5.ORDER_TYPE_SELL_LIMIT,
            mt5.ORDER_TYPE_BUY_STOP,
            mt5.ORDER_TYPE_SELL_STOP,
            mt5.ORDER_TYPE_BUY_STOP_LIMIT,
            mt5.ORDER_TYPE_SELL_STOP_LIMIT
        ]:
            cancel = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
                "symbol": order.symbol,
                "magic": order.magic,
                "comment": "Canceled by Python"
            }

            result = mt5.order_send(cancel)
            if result is None:
                print(f"❌ Failed to cancel order {order.ticket}: {mt5.last_error()}")
            elif result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ Order {order.ticket} canceled successfully")
            else:
                print(f"⚠️ Could not cancel order {order.ticket}. Retcode: {result.retcode}")

def calculate_lot_size(symbol, sl_diff, risk=1):

    #risk = 0.5

    balance = get_balance()

    pip_multiplier = {
        'GBPUSD': 10000,
        'USDCHF': 10000,
        'USDJPY': 10000,
        'US30': 1,
        'EURGBP': 10000,
        'AUDUSD': 10000,
        'XAUUSD': 100,
        'EURUSD': 10000,
        'BTCUSD': 1
    }

    sl_pip = round(sl_diff * pip_multiplier[symbol])

    pip_value = {
        'GBPUSD': 10,
        'USDCHF': 10.97,
        'USDJPY': 6.48,
        'US30': 1,
        'EURGBP': 12.48,
        'AUDUSD': 10,
        'XAUUSD': 1,
        'EURUSD': 10,
        'BTCUSD': 1
    }

    try:
        lot_size = round(balance * (risk / 100) / (pip_value[symbol] * sl_pip), 2)
    except:
        lot_size = 0.01

    return lot_size

def calculate_lot_size_point(symbol, sl_point):

    risk = 2

    balance = get_balance()

    pip_value = {
        'GBPUSD': 10,
        'USDCHF': 10.97,
        'USDJPY': 6.48,
        'US30': 1,
        'EURGBP': 12.48,
        'AUDUSD': 10,
        'XAUUSD': 1,
        'EURUSD': 10,
        'BTCUSD': 0.1
    }
    # Lot Size = (Account Balance × Risk %) / (Stop Loss (in pips) × Pip Value per lot)
    lot_size = round(balance * (risk / 100) / (pip_value[symbol] * sl_point), 2)

    return round(lot_size * 10, 2)

def get_spread_in_price(symbol):
    price = mt5.symbol_info_tick(symbol).ask
    bid_price = mt5.symbol_info_tick(symbol).bid

    spread = abs(price - bid_price)

    return spread

def get_spread_in_point(symbol):
    point = mt5.symbol_info(symbol).point
    price = mt5.symbol_info_tick(symbol).ask
    bid_price = mt5.symbol_info_tick(symbol).bid

    spread = abs(price - bid_price) / point

    return spread

def calculate_be_price(position, buffer_points=20):
    point = mt5.symbol_info(position.symbol).point

    if position.type == mt5.ORDER_TYPE_BUY:
        return position.price_open + buffer_points * point
    else:
        return position.price_open - buffer_points * point

def move_sl_to_be(position, buffer_points=20):
    be_price = calculate_be_price(position, buffer_points)

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,   # 🔴 REQUIRED
        "sl": be_price,                # new SL
        "tp": position.tp,             # 🔴 KEEP TP
    }

    result = mt5.order_send(request)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print("✅ SL moved to Break Even")
    else:
        print("❌ Failed to move SL:", result.comment)

    return result

def atr_sl_tp(entry, type, atr, sl_mult=1.3, tp_mult=3.0):
    if type == 0: # 0 BUY 1 SELL
        sl = entry - atr * sl_mult
        tp = entry + atr * tp_mult
    else:
        sl = entry + atr * sl_mult
        tp = entry - atr * tp_mult
    return sl, tp

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    return atr.iloc[-1]

def set_sl_tp(position, sl, tp):
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "sl": sl,
        "tp": tp
    }
    return mt5.order_send(request)