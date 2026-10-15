"""Build the dashboard database from historical snapshots; --refresh downloads new data."""
import argparse
import json
import sqlite3
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "db" / "stocks.db"
RAW_DIR = BASE_DIR / "dashboard" / "data" / "raw"
SERIES = {
    "MSFT": ("MSFT.csv", "msft_daily", {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}),
    "NVDA": ("NVDA.csv", "nvda_daily", {"Close": "nvda_close", "Volume": "nvda_volume"}),
    "AMZN": ("AMZN.csv", "amzn_daily", {"Close": "amzn_close", "Volume": "amzn_volume"}),
    "GC=F": ("GOLD.csv", "gold_prices", {"Close": "gold_close"}),
    "CL=F": ("OIL.csv", "oil_prices", {"Close": "oil_close"}),
    "^VIX": ("VIX.csv", "vix_data", {"Close": "vix"}),
    "SPY": ("SPY.csv", "spy_data", {"Close": "spy_close"}),
}


def build(db_path=DB_PATH, refresh=False):
    tables = {}
    for ticker, (filename, table, columns) in SERIES.items():
        if refresh:
            import yfinance as yf
            frame = yf.download(ticker, start="2015-01-01", auto_adjust=True, progress=False)
            if frame.empty:
                raise RuntimeError(f"No data returned for {ticker}")
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame = frame.reset_index().rename(columns={"Date": "date"})
        else:
            frame = pd.read_csv(RAW_DIR / filename)
        frame = frame.rename(columns=columns)
        frame = frame[["date", *columns.values()]].copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        tables[table] = frame.sort_values("date").drop_duplicates("date")
    metadata = BASE_DIR / "dashboard/msft_forecaster/pipeline/models/xgboost_weekly_metadata.json"
    metrics = json.loads(metadata.read_text(encoding="utf-8"))["test_metrics"]
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        for name, frame in tables.items():
            frame.to_sql(name, connection, if_exists="replace", index=False)
        pd.DataFrame([{"model": "XGBoost", **metrics}]).to_sql("model_metrics", connection, if_exists="replace", index=False)
        connection.execute("DROP TABLE IF EXISTS predictions")
    return db_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    print(f"Database prepared: {build(refresh=args.refresh)}")
