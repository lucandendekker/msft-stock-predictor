"""Gradio Space wrapping the original dashboard and its current-data Python API."""
import os
from pathlib import Path
import sys

import gradio as gr
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent / 'dashboard'))
from server import app as dashboard

with gr.Blocks(title='MSFT Stock Predictor', fill_height=True) as demo:
    gr.HTML('''<iframe title="MSFT market dashboard" src="/dashboard/?theme=dark"
        style="display:block;width:100%;height:calc(100dvh - 40px);min-height:720px;border:0;background:#0b0d0d"
        allowfullscreen></iframe>''')

application = FastAPI()
application.mount('/dashboard', WSGIMiddleware(dashboard))
application = gr.mount_gradio_app(application, demo, path='/')

if __name__ == '__main__':
    uvicorn.run(application, host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '7860')))
