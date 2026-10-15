#!/bin/sh
set -e
if [ ! -f db/stocks.db ]; then
    python dashboard/setup_db.py
fi
python dashboard/msft_forecaster/predict.py
exec python dashboard/server.py
