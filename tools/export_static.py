"""Export the real historical dashboard and model output for a Static Space."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))
from setup_db import build
from msft_forecaster.predict import run_prediction


def export(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('static_export_server', ROOT / 'dashboard/server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server.app.config['AUTO_REFRESH'] = False
    routes = {
        '/api/stock/history': '/api/stock/history?days=9999',
        '/api/stock/latest': '/api/stock/latest',
        '/api/indicators/latest': '/api/indicators/latest',
        '/api/indicators/history': '/api/indicators/history?days=9999',
        '/api/prediction/latest': '/api/prediction/latest',
        '/api/prediction/history': '/api/prediction/history?n=100',
        '/api/model/metrics': '/api/model/metrics',
    }
    with tempfile.TemporaryDirectory(prefix='msft-static-') as temporary:
        server.DB_PATH = build(Path(temporary) / 'stocks.db')
        result = run_prediction(server.DB_PATH)
        if not result:
            raise RuntimeError('The saved model could not generate a prediction.')
        client = server.app.test_client()
        snapshot = {}
        for key, route in routes.items():
            response = client.get(route)
            if response.status_code != 200 or response.json.get('status') != 'ok':
                raise RuntimeError(f'Could not export {route}: {response.status_code}')
            snapshot[key] = response.json
    history = snapshot['/api/stock/history']['data']
    snapshot['metadata'] = {
        'format': 'msft-static-v1', 'mode': 'historical',
        'data_start': history[0]['date'], 'data_end': history[-1]['date'],
        'prediction_date': result['date'], 'rows': len(history),
        'source': 'Included group-project snapshots and saved weekly XGBoost model.',
    }
    data_dir = destination / 'data'
    data_dir.mkdir(exist_ok=True)
    (data_dir / 'snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    html = (ROOT / 'dashboard/static/index.html').read_text(encoding='utf-8')
    html = html.replace('/static/style.css?v=28', './style.css').replace('/static/app.js?v=47', './app.js')
    html = html.replace('/static/style.css', './style.css').replace('/static/app.js', './app.js')
    html = html.replace('<script src="./app.js">', '<script>window.MSFT_STATIC=true;</script>\n  <script src="./app.js">')
    (destination / 'index.html').write_text(html, encoding='utf-8')
    for filename in ['app.js', 'style.css']:
        shutil.copyfile(ROOT / 'dashboard/static' / filename, destination / filename)
    shutil.copyfile(ROOT / 'AUTHORS.md', destination / 'AUTHORS.md')
    (destination / 'README.md').write_text('''---
title: MSFT Stock Predictor
emoji: 📊
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
---

# MSFT Stock Predictor

An interactive historical dashboard from a collaborative BUas Data Science project.
The project emphasised Kanban, communication, coordination and shared delivery.

Explore historical Microsoft stock data, peer signals and the saved weekly XGBoost model's output.
Charts, filters and CSV export run in your browser. Model results are precomputed from the historical snapshot; this Space does not run a Python server or generate current market forecasts.

[Source code and teamwork case study](https://github.com/lucandendekker/msft-stock-predictor)
· [Portfolio](https://lucandendekker.nl/)

## Team

Lucan den Dekker, Gergely Gádor, Timur Kambarov and Qusai Al Qusaily.
The weekly model is credited to Timur in the original source. See AUTHORS.md.

Historical market data originated from the group's Yahoo Finance workflow.
This academic prototype is presented for the collaborative process and implementation.
''', encoding='utf-8')
    return snapshot['metadata']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist'))
    args = parser.parse_args()
    print(json.dumps(export(args.output), indent=2))
