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
