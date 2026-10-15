"""Gradio Space wrapping the original dashboard and its current-data Python API."""
import os
from pathlib import Path
import sys

import gradio as gr
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware
import uvicorn
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / 'dashboard'))
from server import app as dashboard
from server import live, DB_PATH
from msft_forecaster.predict import build_features, load_model
from contextlib import closing
import sqlite3
import json

try:
    import spaces
except ImportError:
    if os.environ.get('SPACES_ZERO_GPU', '').lower() in ('1', 'true'):
        raise
    class LocalSpaces:
        @staticmethod
        def GPU(**kwargs):
            return lambda function: function
    spaces = LocalSpaces()

ZERO_GPU = os.environ.get('SPACES_ZERO_GPU', '').lower() in ('1', 'true')


def gpu_weekly_prediction(features):
    """Execute the saved tree ensemble on an allocated CUDA device."""
    import torch
    import xgboost as xgb
    if not torch.cuda.is_available():
        raise RuntimeError('The allocated GPU is unavailable. Please retry the update.')
    model, _, _, _ = load_model()
    if model is None:
        raise RuntimeError('The saved weekly model could not be loaded.')
    booster = model.get_booster()
    booster.set_param({'device': 'cuda'})
    probabilities = booster.predict(xgb.DMatrix(np.asarray(features, dtype=np.float32)))
    device = json.loads(booster.save_config())['learner']['generic_param']['device']
    if not device.startswith('cuda'):
        raise RuntimeError('XGBoost did not initialise the allocated GPU.')
    values = probabilities[0]
    predicted = int(np.argmax(values))
    return predicted, float(values[predicted])


def prepare_forecast():
    """Fetch data and prepare small inputs before requesting GPU time."""
    state = live.ensure()
    if not state.get('data_through') or state.get('stale'):
        raise gr.Error('Current market data could not be refreshed. Please retry shortly.')
    with closing(sqlite3.connect(DB_PATH)) as connection:
        features = build_features(connection)
    model, scaler, columns, _ = load_model()
    if model is None or features.empty:
        raise gr.Error('The weekly model or completed-week data is unavailable.')
    row = features.iloc[[-1]]
    inputs = scaler.transform(row[columns])
    start = pd.Timestamp(row['date'].iloc[0]) + pd.Timedelta(days=3)
    end = start + pd.Timedelta(days=4)
    return {'inputs': inputs.tolist(), 'week_start': str(start.date()), 'week_end': str(end.date()), 'data_through': state['data_through']}


@spaces.GPU(duration=30)
def show_forecast(prepared):
    """A directly registered Gradio GPU event, not a nested GPU helper."""
    if not prepared:
        raise gr.Error('Market data is not ready. Press Update to retry.')
    if ZERO_GPU:
        direction, probability = gpu_weekly_prediction(prepared['inputs'])
    else:
        model, _, _, _ = load_model()
        inputs = np.asarray(prepared['inputs'])
        direction = int(model.predict(inputs)[0])
        probability = float(model.predict_proba(inputs)[0][direction])
    label = {0: 'DOWN', 1: 'UP', 2: 'SAME'}[direction]
    return f'**Weekly estimate: {label}** · Model probability: **{probability * 100:.1f}%** · Forecast week: {prepared["week_start"]} to {prepared["week_end"]} · Daily data through {prepared["data_through"]}.'

with gr.Blocks(title='MSFT Stock Predictor', fill_height=True) as demo:
    refresh = gr.Button('Update market data & weekly forecast', variant='primary')
    forecast = gr.Markdown('Loading the latest available weekly estimate…')
    prepared = gr.State()
    refresh.click(prepare_forecast, outputs=prepared).then(show_forecast, inputs=prepared, outputs=forecast)
    demo.load(prepare_forecast, outputs=prepared).then(show_forecast, inputs=prepared, outputs=forecast)
    gr.HTML('''<iframe title="MSFT market dashboard" src="/dashboard/?theme=dark"
        style="display:block;width:100%;height:calc(100dvh - 40px);min-height:720px;border:0;background:#0b0d0d"
        allowfullscreen></iframe>''')

application = FastAPI()
application.mount('/dashboard', WSGIMiddleware(dashboard))
application = gr.mount_gradio_app(application, demo, path='/', ssr_mode=False)

if __name__ == '__main__':
    uvicorn.run(application, host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '7860')))
