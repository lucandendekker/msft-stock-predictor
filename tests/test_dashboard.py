import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))

from setup_db import build
from msft_forecaster.predict import run_prediction

spec = importlib.util.spec_from_file_location('dashboard_server', ROOT / 'dashboard/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
server.app.config['AUTO_REFRESH'] = False


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    database = build(tmp_path / 'stocks.db')
    monkeypatch.setattr(server, 'DB_PATH', database)
    return database, server.app.test_client()


def test_offline_database_contains_required_tables(prepared):
    database, _ = prepared
    with sqlite3.connect(database) as connection:
        for table in ['msft_daily', 'nvda_daily', 'amzn_daily', 'gold_prices', 'oil_prices', 'vix_data', 'spy_data']:
            assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] > 100
        accuracy = connection.execute('SELECT accuracy FROM model_metrics').fetchone()[0]
        assert accuracy == pytest.approx(0.3958333333333333)


def test_dashboard_and_data_endpoints(prepared):
    _, client = prepared
    for path in ['/', '/static/app.js', '/static/style.css', '/api/stock/history?days=30', '/api/stock/latest', '/api/indicators/latest', '/api/model/metrics']:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:200])


def test_price_history_excludes_empty_rows_and_matches_snapshot(prepared):
    _, client = prepared
    history = client.get('/api/stock/history?days=9999').json['data']
    assert all(row[key] is not None and row[key] > 0 for row in history for key in ['open', 'high', 'low', 'close'])
    assert history[-1]['date'] == '2026-06-12'
    assert history[-1]['close'] == pytest.approx(390.739990234375)


def test_actual_model_prediction_is_stored(prepared):
    database, client = prepared
    result = run_prediction(database)
    assert result['direction'] in {'UP', 'DOWN', 'SAME'}
    assert 0 <= result['probability'] <= 100
    with sqlite3.connect(database) as connection:
        record = connection.execute('SELECT date, predicted_direction, actual_direction FROM predictions').fetchone()
    assert record[0] == result['date']
    assert record[1] == result['prediction']
    assert record[2] is None
    assert client.get('/api/prediction/latest').status_code == 200


def test_history_does_not_invent_predictions(prepared):
    database, client = prepared
    assert client.get('/api/prediction/history').json['data'] == []
    run_prediction(database)
    history = client.get('/api/prediction/history').json
    assert len(history['data']) == 1
    assert history['has_dummy'] is False
    assert history['accuracy'] is None
    assert history['data'][0]['is_dummy'] is False
    assert history['data'][0]['close'] == pytest.approx(390.739990234375)
    assert history['data'][0]['actual_direction'] is None
    assert history['data'][0]['correct'] is None


def test_current_quote_is_separate_from_historical_snapshot(prepared, monkeypatch):
    _, client = prepared
    quote = {'symbol': 'MSFT', 'currency': 'USD', 'price': 537.37, 'previous_close': 533.69,
             'change_percent': 0.6895, 'as_of': '2026-10-15T15:00:00+00:00',
             'source': 'Yahoo Finance', 'exchange_timezone': 'America/New_York'}
    monkeypatch.setattr(server, 'latest_quote', lambda: {'status': 'ok', 'data': quote})
    response = client.get('/api/stock/quote')
    assert response.status_code == 200
    assert response.json['data']['price'] == 537.37
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/stock/latest').json['data']['close'] == pytest.approx(390.739990234375)


def test_quote_failure_never_presents_historical_price_as_current(prepared, monkeypatch):
    _, client = prepared
    def unavailable():
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(server, 'latest_quote', unavailable)
    response = client.get('/api/stock/quote')
    assert response.status_code == 503
    assert response.json['status'] == 'error'
    assert 'data' not in response.json
