#!/bin/sh
set -e
if [ ! -f db/stocks.db ]; then
    python dashboard/setup_db.py
fi
python dashboard/msft_forecaster/predict.py
exec gunicorn --chdir dashboard --bind "0.0.0.0:${PORT:-7860}" \
    --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - server:app
