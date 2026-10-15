"""Refresh completed market sessions and run the saved weekly model atomically."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
from threading import Lock
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd
import pandas_market_calendars as mcal

from setup_db import SERIES, BASE_DIR
from msft_forecaster.predict import run_prediction

logger = logging.getLogger(__name__)


def completed_session(now=None):
    now = now or datetime.now(timezone.utc)
    schedule = mcal.get_calendar('NYSE').schedule(start_date=(now - timedelta(days=16)).date(), end_date=now.date())
    # Daily candles can take a few minutes to settle at the data provider.
    closed = schedule[schedule['market_close'] <= pd.Timestamp(now - timedelta(minutes=15))]
    if closed.empty:
        raise RuntimeError('No completed market session is available.')
    return closed.index[-1].date().isoformat()


def fetch_daily(ticker, cutoff):
    query = urlencode({'range': '2y', 'interval': '1d'})
    request = Request(f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe="")}?{query}', headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    result = payload['chart']['result'][0]
    prices = result['indicators']['quote'][0]
    adjusted = result['indicators'].get('adjclose', [{}])[0].get('adjclose', [])
    dates = pd.to_datetime(result['timestamp'], unit='s', utc=True).tz_convert(result['meta']['exchangeTimezoneName']).strftime('%Y-%m-%d')
    rows = []
    for i, date in enumerate(dates):
        if date > cutoff:
            continue
        close = prices['close'][i]
        if close is None or close <= 0:
            continue
        factor = adjusted[i] / close if i < len(adjusted) and adjusted[i] else 1
        row = {'date': date, 'Volume': prices['volume'][i] or 0}
        if any(prices[key][i] is None for key in ['open', 'high', 'low']):
            continue
        for key in ['open', 'high', 'low', 'close']:
            row[key.title()] = prices[key][i] * factor
        rows.append(row)
    if not rows:
        raise RuntimeError(f'No completed daily data returned for {ticker}.')
    frame = pd.DataFrame(rows).drop_duplicates('date').sort_values('date')
    if ticker in ['MSFT', 'NVDA', 'AMZN'] and frame['date'].iloc[-1] < cutoff:
        raise RuntimeError(f'{ticker} daily data is not yet available through {cutoff}.')
    return frame


class LiveData:
    def __init__(self, database):
        self.database = Path(database)
        self.lock = Lock()
        self.next_check = 0
        self.state = self._read_state()

    def _read_state(self):
        try:
            with closing(sqlite3.connect(self.database)) as connection:
                row = connection.execute('SELECT value FROM live_status LIMIT 1').fetchone()
                return json.loads(row[0]) if row else {}
        except (sqlite3.Error, OSError):
            return {}

    def ensure(self):
        with self.lock:
            if time.monotonic() < self.next_check:
                return self.state
            target = completed_session()
            self.next_check = time.monotonic() + 300
            if self.state.get('data_through') == target:
                self.state['refresh_error'] = None
                self.state['stale'] = False
                return self.state
            temporary = self.database.with_name(self.database.stem + '-refresh.sqlite')
            try:
                self.database.parent.mkdir(parents=True, exist_ok=True)
                tables = {}
                for ticker, (_, table, columns) in SERIES.items():
                    frame = fetch_daily(ticker, target).rename(columns=columns)
                    tables[table] = frame[['date', *columns.values()]]
                metrics = json.loads((BASE_DIR / 'dashboard/msft_forecaster/pipeline/models/xgboost_weekly_metadata.json').read_text())['test_metrics']
                with closing(sqlite3.connect(temporary)) as connection, connection:
                    for table, frame in tables.items():
                        frame.to_sql(table, connection, if_exists='replace', index=False)
                    pd.DataFrame([{'model': 'XGBoost', **metrics}]).to_sql('model_metrics', connection, if_exists='replace', index=False)
                    connection.execute('DROP TABLE IF EXISTS predictions')
                    connection.execute('CREATE TABLE predictions (date TEXT PRIMARY KEY, predicted_direction INTEGER, confidence REAL, model_used TEXT, actual_direction INTEGER)')
                    # Keep previously recorded real forecasts when refreshing data.
                    if self.database.exists():
                        try:
                            with closing(sqlite3.connect(self.database)) as previous:
                                history = pd.read_sql('SELECT * FROM predictions', previous)
                            for row in history.itertuples(index=False):
                                connection.execute('INSERT OR REPLACE INTO predictions(date,predicted_direction,confidence,model_used,actual_direction) VALUES(?,?,?,?,?)', (row.date, int(row.predicted_direction), float(row.confidence), row.model_used, None if pd.isna(row.actual_direction) else int(row.actual_direction)))
                        except (sqlite3.Error, pd.errors.DatabaseError):
                            pass
                prediction = run_prediction(temporary)
                if not prediction:
                    raise RuntimeError('The saved model did not produce a prediction.')
                start = pd.Timestamp(prediction['date']) + pd.Timedelta(days=3)
                end = start + pd.Timedelta(days=4)
                state = {'mode': 'automatic', 'data_through': target, 'updated_at': datetime.now(timezone.utc).isoformat(),
                         'feature_week_ending': prediction['date'], 'forecast_week_start': start.date().isoformat(),
                         'forecast_week_end': end.date().isoformat(), 'stale': False, 'refresh_error': None}
                with closing(sqlite3.connect(temporary)) as connection, connection:
                    connection.execute('CREATE TABLE IF NOT EXISTS live_status (value TEXT NOT NULL)')
                    connection.execute('DELETE FROM live_status')
                    connection.execute('INSERT INTO live_status(value) VALUES (?)', (json.dumps(state),))
                os.replace(temporary, self.database)
                self.state = state
                logger.info('Live model and daily data updated through %s', target)
            except Exception:
                logger.exception('Automatic market-data refresh failed')
                self.state = {**self.state, 'stale': True, 'refresh_error': 'Latest completed market data could not be refreshed.', 'expected_data_through': target}
            return self.state
