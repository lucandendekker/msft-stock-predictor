from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dashboard'))
from live_data import completed_session, LiveData
from market_quote import normalize_quote


def test_uses_only_completed_sessions_with_provider_settlement_delay():
    assert completed_session(datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)) == '2026-10-14'
    assert completed_session(datetime(2026, 10, 15, 20, 10, tzinfo=timezone.utc)) == '2026-10-14'
    assert completed_session(datetime(2026, 10, 15, 20, 20, tzinfo=timezone.utc)) == '2026-10-15'
    assert completed_session(datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)) == '2026-10-16'


def test_quote_keeps_source_timestamp_and_previous_close():
    payload = {'chart': {'result': [{'meta': {'symbol': 'MSFT', 'currency': 'USD',
        'regularMarketPrice': 540, 'previousClose': 535, 'regularMarketTime': 1792079217,
        'exchangeTimezoneName': 'America/New_York'}}]}}
    quote = normalize_quote(payload)
    assert quote['price'] == 540
    assert quote['change_percent'] == pytest.approx(5 / 535 * 100)
    assert quote['as_of'].startswith('2026-10-15')
    payload['chart']['result'][0]['meta']['regularMarketPrice'] = -1
    with pytest.raises(ValueError):
        normalize_quote(payload)


def test_refresh_failure_is_explicit_and_preserves_previous_database(tmp_path, monkeypatch):
    database = tmp_path / 'stocks.db'
    service = LiveData(database)
    service.state = {'data_through': '2026-10-13', 'updated_at': '2026-10-14T00:00:00Z'}
    import live_data
    monkeypatch.setattr(live_data, 'completed_session', lambda: '2026-10-14')
    def unavailable(*args):
        raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(live_data, 'fetch_daily', unavailable)
    result = service.ensure()
    assert result['stale'] is True
    assert result['data_through'] == '2026-10-13'
    assert result['expected_data_through'] == '2026-10-14'
    assert result['refresh_error']
