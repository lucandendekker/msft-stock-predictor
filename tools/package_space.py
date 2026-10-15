"""Prepare only runtime files for the Gradio Space; no credentials or local databases."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def package(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['app.py', 'AUTHORS.md']:
        shutil.copyfile(ROOT / name, destination / name)
    shutil.copytree(ROOT / 'dashboard', destination / 'dashboard', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (destination / 'requirements.txt').write_text((ROOT / 'requirements.txt').read_text() + '\ngradio==6.30.0\n', encoding='utf-8')
    # apt/xargs treats a Windows carriage return as part of the package name.
    (destination / 'packages.txt').write_bytes(b'libgomp1\n')
    (destination / 'README.md').write_text('''---
title: MSFT Stock Predictor
emoji: 📈
colorFrom: blue
colorTo: gray
sdk: gradio
sdk_version: 6.30.0
python_version: '3.12'
app_file: app.py
pinned: false
---

# MSFT Stock Predictor

Live market quotes and a saved XGBoost model estimating MSFT's weekly direction.
An academic group project focused on Kanban, collaboration and shared delivery.

The original dashboard is served at `/dashboard/` inside the Gradio app.
The latest available Yahoo Finance quote refreshes every minute while the page is visible.
Completed daily sessions and model output are refreshed on access when new data is available.
After waking from sleep, the first refresh may take a moment. Provider failures and stale data are shown explicitly.

The model uses the latest completed weekly features and estimates the following week's direction: DOWN, UP or SAME. The forecast week and feature date are displayed. It does not predict an exact future stock price, retrain itself, or guarantee a correct direction.

The app uses CPU inference for its small XGBoost model. No CUDA tensor or GPU decorator is needed. The selected ZeroGPU hardware is configured through Hugging Face settings.

## Team

Lucan den Dekker, Gergely Gádor, Timur Kambarov and Qusai Al Qusaily.
The weekly model is credited to Timur in the original source.

[Source code and teamwork](https://github.com/lucandendekker/msft-stock-predictor)
· [Portfolio](https://lucandendekker.nl/)
''', encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(package(parser.parse_args().output))
