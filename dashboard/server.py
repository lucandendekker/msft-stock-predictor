"""
MSFT Direction Predictor — Dashboard API Server
================================================
Flask backend serving the frontend dashboard and REST API endpoints.

Run:
    pip install flask flask-cors pandas numpy joblib scikit-learn xgboost
    cd frontend
    python server.py

Endpoints:
    GET /                        → dashboard
    GET /api/stock/history       → MSFT OHLCV (last ?days=90)
    GET /api/stock/latest        → meest recente MSFT datapunt
    GET /api/indicators/latest   → Gold, Oil, VIX (meest recent)
    GET /api/indicators/history  → Gold, Oil, VIX (laatste ?days=90)
    GET /api/prediction/latest   → UP/DOWN voorspelling + confidence
    GET /api/model/metrics       → model-prestaties (accuracy, F1, etc.)
"""

import os
import sqlite3
from contextlib import closing
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from market_quote import latest_quote
from live_data import LiveData

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # project root
DB_PATH = BASE_DIR / "db" / "stocks.db"
MODEL_PATH = (
    Path(__file__).parent / "msft_forecaster" / "pipeline" / "models" / "xgboost_weekly.joblib"
)
STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.config['AUTO_REFRESH'] = os.environ.get('MSFT_AUTO_REFRESH', '1') == '1'
if app.config['AUTO_REFRESH']:
    DB_PATH = BASE_DIR / 'db' / 'stocks-live.db'
live = LiveData(DB_PATH)


@app.before_request
def refresh_market_data():
    if app.config['AUTO_REFRESH'] and request.path.startswith('/api/') and request.path != '/api/stock/quote':
        state = live.ensure()
        if not state.get('data_through'):
            return jsonify(status='error', message=state.get('refresh_error', 'Market data is not ready yet.')), 503


@app.route('/api/status')
def data_status():
    return jsonify(status='ok', data=live.state if app.config['AUTO_REFRESH'] else {'mode': 'historical'})
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


@app.after_request
def no_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


FEATURE_COLS = [
    "return_1w",
    "return_4w",
    "return_8w",
    "lag_return_1",
    "lag_return_2",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "price_range_pct",
    "rolling_std_5",
    "volume_ratio",
    "nvda_return_1w",
    "nvda_lag_return_1",
    "nvda_rel_strength",
    "nvda_volume_ratio",
    "amzn_return_1w",
    "amzn_lag_return_1",
    "amzn_rel_strength",
    "amzn_volume_ratio",
]

PEER_TICKERS = ["nvda", "amzn"]

DIRECTION_LABELS = {0: "DOWN", 1: "UP", 2: "SAME"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_model():
    """Load Timur's XGBoost weekly bundle (model + scaler + feature list)."""
    try:
        bundle = joblib.load(MODEL_PATH)
        logger.info("Loaded model: xgboost_weekly")
        return bundle["model"], bundle["scaler"], bundle["feature_columns"], "xgboost_weekly"
    except Exception as e:
        logger.error("Could not load model from %s: %s", MODEL_PATH, e)
        return None, None, None, None


def _rsi_weekly(series: pd.Series) -> pd.Series:
    """RSI using Wilder's EWM smoothing (com=13, min_periods=14)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, min_periods=14).mean()
    return 100 - (100 / (1 + avg_gain / avg_loss))


def build_weekly_features(conn, n_daily_rows: int = 400) -> pd.DataFrame:
    """Fetch daily MSFT + peer data, resample to weekly, compute all 20 features."""
    msft = pd.read_sql(
        f"SELECT date, open, high, low, close, volume FROM msft_daily ORDER BY date DESC LIMIT {n_daily_rows}",
        conn,
    ).sort_values("date")

    msft["date"] = pd.to_datetime(msft["date"])
    msft = msft.set_index("date")

    weekly = (
        msft.resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )

    close = weekly["close"]
    high = weekly["high"]
    low = weekly["low"]
    vol = weekly["volume"]

    weekly["return_1w"] = close.pct_change(1) * 100
    weekly["return_4w"] = close.pct_change(4) * 100
    weekly["return_8w"] = close.pct_change(8) * 100
    weekly["lag_return_1"] = weekly["return_1w"].shift(1)
    weekly["lag_return_2"] = weekly["return_1w"].shift(2)
    weekly["rsi_14"] = _rsi_weekly(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    weekly["macd"] = ema12 - ema26
    weekly["macd_signal"] = weekly["macd"].ewm(span=9, adjust=False).mean()
    weekly["macd_hist"] = weekly["macd"] - weekly["macd_signal"]

    weekly["price_range_pct"] = (high - low) / close * 100
    weekly["rolling_std_5"] = close.rolling(5).std()
    weekly["volume_ratio"] = vol / vol.rolling(20).mean()

    msft_return_1w = weekly["return_1w"]

    for peer in PEER_TICKERS:
        close_col = f"{peer}_close"
        volume_col = f"{peer}_volume"
        try:
            peer_df = pd.read_sql(
                f"SELECT date, {close_col}, {volume_col} FROM {peer}_daily ORDER BY date DESC LIMIT {n_daily_rows}",
                conn,
            ).sort_values("date")
            peer_df["date"] = pd.to_datetime(peer_df["date"])
            peer_df = peer_df.set_index("date")

            peer_w = peer_df.resample("W-FRI").agg({close_col: "last", volume_col: "sum"})
            weekly[close_col] = peer_w[close_col]
            weekly[volume_col] = peer_w[volume_col]

            peer_close = weekly[close_col]
            peer_volume = weekly[volume_col]

            weekly[f"{peer}_return_1w"] = peer_close.pct_change(1) * 100
            weekly[f"{peer}_lag_return_1"] = weekly[f"{peer}_return_1w"].shift(1)
            weekly[f"{peer}_rel_strength"] = msft_return_1w - weekly[f"{peer}_return_1w"]
            weekly[f"{peer}_volume_ratio"] = peer_volume / peer_volume.rolling(20).mean()
        except Exception as e:
            logger.warning("Peer features unavailable for %s: %s — using defaults", peer, e)
            weekly[f"{peer}_return_1w"] = 0.0
            weekly[f"{peer}_lag_return_1"] = 0.0
            weekly[f"{peer}_rel_strength"] = 0.0
            weekly[f"{peer}_volume_ratio"] = 1.0

    return weekly.dropna().reset_index()


# ── Routes ───────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    import json
    body = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    config = json.dumps({'apiBase': request.script_root, 'automatic': app.config['AUTO_REFRESH']}).replace('<', '\\u003c')
    body = body.replace('<!-- MSFT_RUNTIME -->', f'<script>window.MSFT_RUNTIME={config};window.MSFT_API_BASE=window.MSFT_RUNTIME.apiBase;</script>')
    return app.response_class(body, mimetype='text/html')


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(STATIC_DIR), filename)


@app.route("/api/stock/history")
def stock_history():
    days = request.args.get("days", 90, type=int)
    try:
        conn = get_conn()
        df = pd.read_sql(
            f"""
            SELECT m.date, m.open, m.high, m.low, m.close, m.volume,
                   g.gold_close, o.oil_close, v.vix,
                   n.nvda_close, a.amzn_close
            FROM msft_daily m
            LEFT JOIN gold_prices g ON m.date = g.date
            LEFT JOIN oil_prices  o ON m.date = o.date
            LEFT JOIN vix_data    v ON m.date = v.date
            LEFT JOIN nvda_daily  n ON m.date = n.date
            LEFT JOIN amzn_daily  a ON m.date = a.date
            WHERE m.open > 0 AND m.high > 0 AND m.low > 0 AND m.close > 0
            ORDER BY m.date DESC LIMIT {days}
        """,
            conn,
        ).sort_values("date")
        conn.close()
        import json as _json

        return app.response_class(
            _json.dumps({"status": "ok", "data": _json.loads(df.to_json(orient="records"))}),
            mimetype="application/json",
        )
    except Exception as e:
        logger.error(f"stock_history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/stock/latest")
def stock_latest():
    try:
        conn = get_conn()
        row = conn.execute("SELECT * FROM msft_daily ORDER BY date DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            return jsonify({"status": "ok", "data": dict(row)})
        return jsonify({"status": "error", "message": "Geen data gevonden"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/stock/quote')
def stock_quote():
    try:
        response = jsonify(latest_quote())
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        logger.exception('Market quote unavailable')
        response = jsonify(status='error', message='Market data is temporarily unavailable.')
        response.headers['Cache-Control'] = 'no-store'
        return response, 503


@app.route("/api/indicators/latest")
def indicators_latest():
    try:
        conn = get_conn()
        gold = conn.execute("SELECT * FROM gold_prices ORDER BY date DESC LIMIT 1").fetchone()
        oil = conn.execute("SELECT * FROM oil_prices ORDER BY date DESC LIMIT 1").fetchone()
        vix = conn.execute("SELECT * FROM vix_data ORDER BY date DESC LIMIT 1").fetchone()
        conn.close()
        return jsonify(
            {
                "status": "ok",
                "data": {
                    "gold": dict(gold) if gold else None,
                    "oil": dict(oil) if oil else None,
                    "vix": dict(vix) if vix else None,
                },
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/indicators/history")
def indicators_history():
    days = request.args.get("days", 90, type=int)
    try:
        conn = get_conn()
        gold = pd.read_sql(
            f"SELECT * FROM gold_prices ORDER BY date DESC LIMIT {days}", conn
        ).sort_values("date")
        oil = pd.read_sql(
            f"SELECT * FROM oil_prices ORDER BY date DESC LIMIT {days}", conn
        ).sort_values("date")
        vix = pd.read_sql(
            f"SELECT * FROM vix_data ORDER BY date DESC LIMIT {days}", conn
        ).sort_values("date")
        conn.close()
        return jsonify(
            {
                "status": "ok",
                "data": {
                    "gold": gold.to_dict(orient="records"),
                    "oil": oil.to_dict(orient="records"),
                    "vix": vix.to_dict(orient="records"),
                },
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/prediction/latest")
def prediction_latest():
    try:
        conn = get_conn()

        # Read from predictions table first (written by predict.py)
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        if "predictions" in tables:
            row = conn.execute(
                "SELECT p.*, (SELECT m.close FROM msft_daily m WHERE m.date<=p.date ORDER BY m.date DESC LIMIT 1) as close FROM predictions p "
                "ORDER BY p.date DESC LIMIT 1"
            ).fetchone()
            if row:
                conn.close()
                return jsonify(
                    {
                        "status": "ok",
                        "data": {
                            "date": row["date"],
                            "direction": DIRECTION_LABELS.get(
                                row["predicted_direction"], str(row["predicted_direction"])
                            ),
                            "prediction": row["predicted_direction"],
                            "probability": round(row["confidence"] * 100, 1),
                            "close": row["close"],
                            "model_name": row["model_used"],
                            "forecast_week_start": str((pd.Timestamp(row['date']) + pd.Timedelta(days=3)).date()),
                            "forecast_week_end": str((pd.Timestamp(row['date']) + pd.Timedelta(days=7)).date()),
                            "data_through": live.state.get('data_through') if app.config['AUTO_REFRESH'] else None,
                            "updated_at": live.state.get('updated_at') if app.config['AUTO_REFRESH'] else None,
                            "stale": live.state.get('stale', False) if app.config['AUTO_REFRESH'] else False,
                        },
                    }
                )

        # Fallback: compute on-the-fly if predictions table is empty
        df = build_weekly_features(conn)
        conn.close()

        if df.empty:
            return jsonify({"status": "error", "message": "Not enough data"}), 400

        model, scaler, feature_cols, model_name = load_model()
        if model is None:
            return (
                jsonify(
                    {
                        "status": "model_unavailable",
                        "message": "No trained model found.",
                    }
                ),
                503,
            )

        X = scaler.transform(df[feature_cols].iloc[[-1]])
        pred = int(model.predict(X)[0])
        prob = float(model.predict_proba(X)[0][pred])

        return jsonify(
            {
                "status": "ok",
                "data": {
                    "date": str(df["date"].iloc[-1].date()),
                    "direction": DIRECTION_LABELS.get(pred, str(pred)),
                    "prediction": pred,
                    "probability": round(prob * 100, 1),
                    "close": float(df["close"].iloc[-1]),
                    "model_name": model_name,
                },
            }
        )
    except Exception as e:
        logger.error("prediction_latest: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/model/metrics")
def model_metrics():
    """
    Retourneer opgeslagen model-metrics.
    Verbind de evaluatie-pipeline om dit te vullen met echte waarden.
    """
    try:
        conn = get_conn()
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        conn.close()

        metrics = []
        if "model_metrics" in tables:
            conn = get_conn()
            rows = pd.read_sql("SELECT * FROM model_metrics", conn)
            conn.close()
            metrics = rows.to_dict(orient="records")
        else:
            metrics = [
                {
                    "model": "XGBoost",
                    "accuracy": None,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                },
                {
                    "model": "Random Forest",
                    "accuracy": None,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                },
                {
                    "model": "Logistic Regression",
                    "accuracy": None,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                },
            ]

        return jsonify({"status": "ok", "data": metrics})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/prediction/history")
def prediction_history():
    """Return recorded predictions only, without synthetic performance history."""
    n = max(1, min(request.args.get("n", 10, type=int), 100))
    try:
        with closing(get_conn()) as conn:
            exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'").fetchone()
            if not exists:
                return jsonify(status="ok", data=[], accuracy=None, has_dummy=False)
            records = conn.execute("SELECT p.date, p.predicted_direction, p.confidence, p.actual_direction, (SELECT m.close FROM msft_daily m WHERE m.date<=p.date ORDER BY m.date DESC LIMIT 1) as close FROM predictions p ORDER BY p.date DESC LIMIT ?", (n,)).fetchall()
        rows = [{"date": row["date"], "predicted_direction": row["predicted_direction"],
                 "confidence": round(row["confidence"] * 100, 1), "actual_direction": row["actual_direction"],
                 "correct": None if row["actual_direction"] is None else row["predicted_direction"] == row["actual_direction"], "close": row["close"], "is_dummy": False} for row in records]
        return jsonify(status="ok", data=rows, accuracy=None, has_dummy=False)
    except Exception:
        logger.exception("Could not read prediction history")
        return jsonify(status="error", message="Prediction history is unavailable"), 500


if __name__ == "__main__":
    print(f"\n  Dashboard: http://localhost:{os.environ.get('PORT', '5002')}")
    print(f"  Database:  {DB_PATH}\n")
    app.run(debug=False, port=int(os.environ.get("PORT", "5002")), host=os.environ.get("HOST", "127.0.0.1"))
