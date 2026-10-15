# Market quote and archived snapshot

The current MSFT quote is fetched independently from Yahoo Finance's chart endpoint (`range=1d&interval=1m`). The API caches successful responses for 60 seconds and preserves the provider's quote timestamp. This is the latest available regular-session quote, not a guarantee of tick-by-tick or delay-free prices. If fetching fails, the dashboard explicitly marks the quote unavailable or its last received value as stale.

Charts, model features, prediction date and model probabilities belong to the historical group-project snapshot. Updating the market quote does not retrain or rerun the model on current market data.

During validation on 15 October 2026, the original MSFT CSV was found to contain an empty OHLC row for 10 June 2026 and a partial candle for 12 June 2026. The MSFT rows for 10–12 June were replaced with completed daily candles retrieved from the original provider:

- 10 June: close 397.3599853515625 USD.
- 11 June: close 390.3399963378906 USD.
- 12 June: close 390.739990234375 USD.

The previously displayed 387.2099914550781 USD was an archived partial-day quote, not the final closing price. Historical charts and the model-output export were regenerated after the correction. Archived test metrics remain the model's original recorded evaluation; they are not a new backtest of the repaired snapshot.

Source: [Yahoo Finance MSFT history](https://finance.yahoo.com/quote/MSFT/history/), chart endpoint `/v8/finance/chart/MSFT?period1=1781049600&period2=1781308800&interval=1d`.
