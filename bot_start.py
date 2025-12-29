from stategies.per_minute_strat import per_min_ema
from utils.mt5_utils import initialize_mt5

initialize_mt5()

per_min_ema('XAUUSD')