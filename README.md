# llm-compare-dashboard

This project is a local Streamlit app for comparing OpenAI and Gemini responses, metadata, and saved run history.

That means it is a small Python web app that runs on your own computer and opens in your browser. It is not deployed as a public website or backend service. You start it locally with `streamlit run app.py`, and Streamlit provides the user interface.

![Main dashboard view](docs/screenshot-main.png)

> [!IMPORTANT]
> Never commit API keys, `.env`, or any other secrets to Git.
> Make sure `.env` is listed in `.gitignore` before you start.
> If a key is accidentally committed, assume it is compromised, revoke it, and generate a new one.

## Why this exists

The purpose of the app is to make it easy to compare OpenAI and Gemini on the same prompt in one place.

Instead of writing separate scripts or manually copying prompts between providers, the app lets you:

- send the same prompt to both models
- view the responses side by side
- inspect token and latency metadata
- keep a persistent local history of earlier runs

The dashboard is also being prepared for a route-finding evaluation mode. That mode will reuse the sibling `research` repository for SSAL-native graph loading, Dijkstra ground truth, and route-response evaluation.

## Relationship to the research repo

The route-finding workflow depends on reusable modules from the sibling [`research`](https://github.com/spatial-ninjas/research) repository.

Expected local folder layout:

```text
spatial-ninjas/
  research/
  llm-compare-dashboard/
```

The dashboard installs `research` as an editable local dependency through `requirements.txt`:

```txt
-e ../research
```

This lets the dashboard import the shared evaluator foundation directly, for example:

```python
from research.graph import build_graph_from_ssal
from research.evaluation import evaluate_route_response
from research.network_loader import load_network_bundle_from_gpkg
```

If your folder layout is different, either adjust the editable dependency path in `requirements.txt` or install the research repo manually with the correct path.

## What the app does

For each run, the app sends your prompt to both providers, shows the results in the browser, and stores the run in a local SQLite database.

The app also includes controls for:

- model selection
- output token limits
- Gemini thinking settings
- viewing raw responses
- exporting saved history

## Features

- Send one prompt to both providers
- Compare responses side by side
- Adjustable `max_output_tokens`
- Gemini thinking controls:
  - `dynamic`
  - `off`
  - `custom`
- Gemini retry logic for transient failures such as `503 UNAVAILABLE`
- Visible attempt count in the result cards
- Basic metadata display:
  - latency
  - input/output/total tokens
  - Gemini thoughts tokens
  - finish/status info when available
- Current browser-session history
- Persistent SQLite history saved to `history.db`
- Export saved history as JSON
- Clear saved history from the UI
- Inspect saved prompts, responses, metadata, and errors from earlier runs
- Local route-finding network configuration for the upcoming SSAL-native route mode

## Persisted metadata

Each saved provider call stores the usual request metadata plus these extra fields when available:

- `thinking_mode`
- `thinking_budget`
- `thoughts_tokens`
- `attempts`

The app auto-migrates older `history.db` files by adding missing columns on startup.

## Files

- `app.py` — the Streamlit app
- `requirements.txt` — Python dependencies
- `.env.example` — environment variable template
- `history.db` — created automatically on first run

## Setup

### 1. Clone or place both repos in the expected layout

The default local dependency path assumes this layout:

```text
spatial-ninjas/
  research/
  llm-compare-dashboard/
```

From inside `llm-compare-dashboard`, `../research` should point to the sibling research repo.

### 2. Create and activate a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This also installs the sibling `research` repo in editable mode through:

```txt
-e ../research
```

### 4. Run smoke tests for the research dependency

After installing dependencies, verify that the dashboard can import the shared research package:

```bash
python -c "from research.graph import build_graph_from_ssal; print('ok')"
```

Recommended additional checks:

```bash
python -c "from research.evaluation import evaluate_route_response; print('evaluation ok')"
python -c "from research.network_loader import load_network_bundle_from_gpkg; print('network loader ok')"
```

### 5. Create `.env`

Copy `.env.example` to `.env` and fill in your API keys.

macOS / Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```env
# API keys
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Route-finding network data
NETWORK_GPKG_PATH=../research/data/raw/routing_networks/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_URL=
NETWORK_GPKG_SHA256=
NETWORK_EDGES_LAYER=slimmed_cropped_edges
NETWORK_NODES_LAYER=slimmed_cropped_nodes
NETWORK_CACHE_DIR=.cache/network
```

For local development, `NETWORK_GPKG_PATH` should point to the GeoPackage file in the sibling `research` repo.

Later deployment-oriented workflows can use `NETWORK_GPKG_URL`, `NETWORK_GPKG_SHA256`, and `NETWORK_CACHE_DIR` to download and cache the network file.

### 6. Run the app

```bash
streamlit run app.py
```

Open the local URL shown by Streamlit, usually:

`http://localhost:8501`

## Route-finding network configuration

The route-finding mode is expected to resolve network data in this order:

```text
If NETWORK_GPKG_PATH exists:
  use the local GeoPackage file

Else if NETWORK_GPKG_URL is set:
  download or reuse the cached GeoPackage file

Else:
  show a dashboard error explaining that network data is not configured
```

Current route-finding environment variables:

- `NETWORK_GPKG_PATH` — local path to the GeoPackage network file
- `NETWORK_GPKG_URL` — optional remote GeoPackage URL for hosted/deployed environments
- `NETWORK_GPKG_SHA256` — optional checksum for downloaded/cached network files
- `NETWORK_EDGES_LAYER` — GeoPackage edge layer name
- `NETWORK_NODES_LAYER` — GeoPackage node layer name
- `NETWORK_CACHE_DIR` — cache directory for downloaded network files

The default local path assumes the sibling `research` repo contains the Southern Helsinki routing-network artifact.

## Sidebar settings

The sidebar includes:

* OpenAI model
* Gemini model
* Max response tokens
* Gemini thinking budget
  * `dynamic`: let Gemini decide
  * `off`: disable Gemini thinking
  * `custom`: set an explicit Gemini thinking token budget
* Saved rows to show
* Show raw API responses
* Show rough OpenAI cost estimate

If `custom` Gemini thinking is selected, an additional slider appears for the custom thinking budget.

## Persistence model

The app creates `history.db` in the same folder as `app.py` and stores one row per provider call.

Each click of **Run both models** saves:

* one OpenAI row
* one Gemini row

That means prompts, responses, token metadata, retries, and errors persist across refreshes and restarts.

## What the app shows

For each run, the UI shows:

* provider response text
* visible attempt count
* metadata JSON
* optional raw API response JSON
* a quick comparison table across providers

The saved-history section also lets you inspect earlier runs in detail.

## Notes

* The OpenAI cost display is only a rough estimate based on the hard-coded model pricing table in the app.
* Gemini can return transient overload errors such as `503 UNAVAILABLE`; the app retries those automatically with exponential backoff.
* Gemini may also consume tokens as `thoughts_tokens`, which can explain short visible outputs when `max_output_tokens` is small.
* This app shows per-call usage metadata. It does not show a provider-wide “tokens left” counter.
* Keep `.env` out of Git.
* Keep `history.db` out of Git.
* If you already have an older `history.db`, the app upgrades it automatically by adding the newer metadata columns.
