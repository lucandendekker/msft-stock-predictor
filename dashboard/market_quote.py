"""Latest available regular-session MSFT quote, independently of model snapshots."""
from datetime import datetime, timezone
import json
import math
from threading import Lock
import time
from urllib.request import Request, urlopen

_cache = None
_lock = Lock()


def normalize_quote(payload):
    meta = payload['chart']['result'][0]['meta']
    price = meta['regularMarketPrice']
    previous = meta.get('previousClose', meta.get('chartPreviousClose'))
    timestamp = meta['regularMarketTime']
    if meta['symbol'] != 'MSFT' or meta['currency'] != 'USD' or any(not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0 for value in [price, previous, timestamp]):
        raise ValueError('Invalid market data')
    return {'symbol': 'MSFT', 'currency': 'USD', 'price': price, 'previous_close': previous,
            'change_percent': (price / previous - 1) * 100,
            'as_of': datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            'source': 'Yahoo Finance', 'exchange_timezone': meta.get('exchangeTimezoneName', 'America/New_York')}


def latest_quote():
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < 60:
            return _cache[1]
        request = Request('https://query1.finance.yahoo.com/v8/finance/chart/MSFT?range=1d&interval=1m', headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(request, timeout=8) as response:
            data = normalize_quote(json.load(response))
        result = {'status': 'ok', 'data': data, 'fetched_at': datetime.now(timezone.utc).isoformat()}
        _cache = (time.monotonic(), result)
        return result
