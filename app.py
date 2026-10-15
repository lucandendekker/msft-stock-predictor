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


if os.environ.get('SPACE_ID'):
    import spaces
    gpu_weekly_prediction = spaces.GPU(duration=30)(gpu_weekly_prediction)


def refresh_forecast():
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
    if os.environ.get('SPACE_ID'):
        direction, probability = gpu_weekly_prediction(inputs.tolist())
    else:
        direction = int(model.predict(inputs)[0])
        probability = float(model.predict_proba(inputs)[0][direction])
    start = pd.Timestamp(row['date'].iloc[0]) + pd.Timedelta(days=3)
    end = start + pd.Timedelta(days=4)
    label = {0: 'DOWN', 1: 'UP', 2: 'SAME'}[direction]
    return f'**Weekly estimate: {label}** · Model probability: **{probability * 100:.1f}%** · Forecast week: {start.date()} to {end.date()} · Daily data through {state["data_through"]}.'

with gr.Blocks(title='MSFT Stock Predictor', fill_height=True) as demo:
    refresh = gr.Button('Update market data & weekly forecast', variant='primary')
    forecast = gr.Markdown('Loading the latest available weekly estimate…')
    refresh.click(refresh_forecast, outputs=forecast)
    demo.load(refresh_forecast, outputs=forecast)
    gr.HTML('''<iframe title="MSFT market dashboard" src="/dashboard/?theme=dark"
        style="display:block;width:100%;height:calc(100dvh - 40px);min-height:720px;border:0;background:#0b0d0d"
        allowfullscreen></iframe>''')

application = FastAPI()
application.mount('/dashboard', WSGIMiddleware(dashboard))
application = gr.mount_gradio_app(application, demo, path='/', ssr_mode=False)

if __name__ == '__main__':
    uvicorn.run(application, host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '7860')))
