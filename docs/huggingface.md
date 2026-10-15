# Gradio Space deployment

Target: `Lucan5533/msft-stock-predictor`, created with Gradio -> Blank and the account's available ZeroGPU Free hardware.

```sh
python tools/package_space.py --output upload
```

Upload the contents of the generated folder at the Space root: `app.py`, `README.md`, `requirements.txt`, `packages.txt`, `AUTHORS.md` and the entire `dashboard/` directory. The generated README selects Gradio 6.30.0 and Python 3.12. The app uses CPU inference for the small XGBoost model; the example Torch tensor and GPU decorator are not required by this application.

The Gradio interface embeds the original dashboard at `/dashboard/`. Its Flask API is mounted below that path, with browser requests using the correct prefix. This keeps the original charts, theme toggle, filters and CSV downloads.

The quote comes from Yahoo Finance and refreshes every minute while visible. Completed daily candles are checked on access, at most once every five minutes. When a new completed session is available, the saved model runs again on the latest completed weekly features. The interface displays the input week, forecast week, quote timestamp and refresh errors. It never converts a quote refresh into an implied new model forecast.

The model estimates the following week's direction relative to the input week. During a trading week, its most recent complete input week is the preceding week; a new forecast for the next calendar week becomes available after the current week closes. It predicts direction, not an exact future price.

A free Space may sleep. On waking it refreshes on access; this is not an always-running scheduler. Yahoo Finance availability and delays can affect updates. Local data is recreated after a fresh container restart. No school APIs, login credentials or private documents are needed.

For a Hostinger portfolio, embed `https://lucan5533-msft-stock-predictor.hf.space/dashboard/?theme=dark` after the Space has passed its hosted build and runtime checks. No Python runtime is needed on Hostinger.

## Optional static export

`python tools/export_static.py --output dist` prepares an archived snapshot for offline demos. That export does not run a model or fetch market history in the visitor's browser. It is separate from the Gradio deployment.
