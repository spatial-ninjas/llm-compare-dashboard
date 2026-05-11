# llm-compare-dashboard

Current release: **v0.5.2**

`llm-compare-dashboard` is a Streamlit app for comparing OpenAI and Gemini responses and evaluating LLM route-generation behavior over an SSAL-native Southern Helsinki route network.

It supports:

- general side-by-side provider comparison
- SSAL-based route-finding prompts
- selectable SSAL profiles for coordinate-aware and coordinate-free route-prompt experiments
- Dijkstra ground-truth comparison
- saved provider runs, route tasks, route evaluations, and prompt templates
- route-history review and map replay
- local SQLite or managed PostgreSQL persistence
- optional Google OIDC sign-in with email allowlist

```bash
streamlit run app.py
```

![Main dashboard view](docs/screenshot-main.png)

> [!IMPORTANT]
> Never commit API keys, `.env`, `.streamlit/secrets.toml`, `deploy/cloudrun/secrets.toml`, `history.db`, `.cache/`, or any other secrets/local state to Git.

## Quick start

Clone and install:

```bash
git clone https://github.com/spatial-ninjas/llm-compare-dashboard.git
cd llm-compare-dashboard

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Create local config:

```bash
cp .env.example .env
```

Fill in at least:

```env
OPENAI_API_KEY=...
GEMINI_API_KEY=...
```

Then run:

```bash
streamlit run app.py
```

By default:

- persistence uses local SQLite `history.db`
- authentication is disabled
- route network data is loaded from `NETWORK_GPKG_PATH` if available, otherwise from `NETWORK_GPKG_URL`

## Main concepts

**SSAL** means Simplified Semantic Adjacency List. It is the compact graph text shown to the model.

**SSAL profile** means the selected shape of the SSAL text used in a route prompt, such as the default coordinate-aware representation or a compact coordinate-free representation.

**OD pair** means origin-destination node pair.

**Ground truth** means the deterministic Dijkstra shortest path over the loaded SSAL-derived graph.

**Candidate route** means the route returned by a model response.

## App modes

### General prompt comparison

Sends the same free-form prompt to OpenAI and Gemini, then saves provider responses, metadata, token usage, latency, and errors.

### Route finding

Selects an OD pair, chooses an SSAL profile, generates an SSAL route prompt, calls both providers, evaluates returned routes against Dijkstra ground truth, and saves route-specific metrics.

The default SSAL profile keeps the coordinate-aware representation used by earlier releases. A compact coordinate-free profile is also available for experiments where the model should focus on graph connectivity, edge length, street names, and oneway flags without endpoint coordinates.

### Route evaluation history

Reviews saved route evaluations, filters previous runs, inspects route segments, replays routes on maps, and exports route-history data.

## Relationship to `spatial-ninjas-research`

The dashboard uses the published research package:

```txt
spatial-ninjas-research==0.1.0
```

The PyPI distribution is `spatial-ninjas-research`; the Python import package is `research`:

```python
from research.graph import dijkstra_shortest_path
from research.evaluation import evaluate_route_response
from research.network_loader import load_network_bundle_from_gpkg
from research.network_loader import fetch_or_reuse_cached_file
```

Large GeoPackage files are not distributed through the PyPI package. Network data is configured separately with environment variables.

For local development across both repos, use a sibling checkout:

```text
spatial-ninjas/
  research/
  llm-compare-dashboard/
```

Then from inside `llm-compare-dashboard`:

```bash
pip uninstall spatial-ninjas-research
pip install -e ../research
```

## Configuration

### API keys

```env
OPENAI_API_KEY=...
GEMINI_API_KEY=...
```

### Network data

Route finding resolves the GeoPackage in this order:

1. use `NETWORK_GPKG_PATH` if it points to an existing local file
2. otherwise fetch or reuse `NETWORK_GPKG_URL`
3. otherwise show a configuration error

Recommended local/deployment-compatible setup:

```env
NETWORK_GPKG_PATH=../research/data/raw/routing_networks/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_URL=https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_SHA256=f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e
NETWORK_CACHE_DIR=.cache/network

NETWORK_EDGES_LAYER=slimmed_cropped_edges
NETWORK_NODES_LAYER=slimmed_cropped_nodes
```

For Cloud Run, use:

```env
NETWORK_CACHE_DIR=/tmp/network
```

### Database

If `DATABASE_URL` is unset or empty, the dashboard uses local SQLite:

```env
DATABASE_URL=
```

For deployment, use PostgreSQL:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:port/database
```

For Supabase, copy the pooler connection string if appropriate and use the SQLAlchemy psycopg v3 scheme:

```text
postgresql+psycopg://...
```

Existing local `history.db` data is not automatically migrated to PostgreSQL.

### Authentication

Authentication is optional.

```env
AUTH_ALLOWED_EMAILS=person1@example.com,person2@example.com
```

Behavior:

```text
No OIDC secrets + empty AUTH_ALLOWED_EMAILS
  -> local no-auth mode

No OIDC secrets + AUTH_ALLOWED_EMAILS set
  -> configuration warning

OIDC secrets + empty AUTH_ALLOWED_EMAILS
  -> Google sign-in required, any signed-in user allowed

OIDC secrets + AUTH_ALLOWED_EMAILS set
  -> Google sign-in required, only listed emails allowed
```

Local Streamlit OIDC secrets go in `.streamlit/secrets.toml`:

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "replace-with-a-long-random-string"

[auth.google]
client_id = "your-google-oauth-client-id"
client_secret = "your-google-oauth-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Do not commit real secrets.

## Deployment

The current shared deployment target is:

```text
Google Cloud Run       Streamlit app container
Supabase PostgreSQL    managed database through DATABASE_URL
Secret Manager         API keys, DATABASE_URL, Streamlit OIDC secrets
Hosted GeoPackage      route-network data through NETWORK_GPKG_URL
```

Deployment files:

```text
deploy/cloudrun/
  env.example.yaml
  secrets.example.toml
```

Local real deployment files, not committed:

```text
deploy/cloudrun/env.yaml
deploy/cloudrun/secrets.toml
```

Deploy with:

```bash
export PROJECT_ID=spatial-ninjas
export REGION=europe-north1
export SERVICE=llm-compare-dashboard
export VERSION=v0.5.2

./scripts/deploy_cloud_run.sh
```

After the first deploy, add the printed redirect URI to the Google OAuth client:

```text
https://your-cloud-run-service-url/oauth2callback
```

Full deployment instructions are in:

```text
docs/deployment-cloud-run.md
```

## Smoke checks

Import checks:

```bash
python -c "import authlib; print('authlib ok')"
python -c "from research.evaluation import evaluate_route_response; print('evaluation ok')"
python -c "from research.network_loader import load_network_bundle_from_gpkg; print('network loader ok')"
python -c "from dashboard.auth import require_auth; print('auth ok')"
python -c "from dashboard.views.route_finding import render_route_finding_view; print('route view ok')"
python -c "from dashboard.views.route_history import render_route_history_view; print('route history view ok')"
```

Compile:

```bash
python -m py_compile \
  app.py \
  dashboard/api_clients.py \
  dashboard/auth.py \
  dashboard/db.py \
  dashboard/network.py \
  dashboard/route_prompts.py \
  dashboard/route_visualization.py \
  dashboard/route_map_helpers.py \
  dashboard/views/general.py \
  dashboard/views/route_finding.py \
  dashboard/views/route_history.py
```

Route visualisation smoke test:

```bash
python scripts/smoke_route_visualization.py
open route_visualization_test.html
```

## Files

```text
llm-compare-dashboard/
  app.py                         Streamlit entrypoint and mode router
  Dockerfile                     Cloud Run container image definition
  requirements.txt               Python dependencies
  .env.example                   Local environment variable template

  dashboard/
    api_clients.py               OpenAI/Gemini API wrappers
    auth.py                      Google OIDC auth gate and allowlist helpers
    db.py                        SQLite/PostgreSQL persistence helpers
    network.py                   local/remote NetworkBundle loading
    route_prompts.py             route prompt templates, SSAL profiles, and validation
    route_visualization.py       Folium route visualisation helpers
    route_map_helpers.py         map embedding and segment-highlight helpers
    views/
      general.py                 general prompt comparison
      route_finding.py           new route tests
      route_history.py           saved route evaluation history

  deploy/cloudrun/
    env.example.yaml             example Cloud Run environment variables
    secrets.example.toml         example Cloud Run Streamlit OIDC secrets

  scripts/
    deploy_cloud_run.sh          repeatable Cloud Run deployment helper
    smoke_route_visualization.py route visualisation smoke script

  docs/
    deployment-cloud-run.md      full Cloud Run deployment guide
    screenshot-main.png          README screenshot
```

## Release notes

### v0.5.2

Patched route-finding mode with lightweight selectable SSAL profiles for prompt experiments.

Highlights:

- kept the existing default coordinate-aware SSAL profile
- added a compact coordinate-free profile with length, street name, and oneway fields
- added an optional `{ssal_schema_description}` prompt-template placeholder
- updated the built-in route prompt so the schema shown to the model matches the selected SSAL profile
- loads the route prompt/evaluation `NetworkBundle` from the selected SSAL profile options
- keeps map rendering on the default coordinate-aware bundle so coordinate-free experiments do not break visualisation

Notes:

- this is a narrow post-freeze patch for coordinate-free SSAL experiments, not the full user-defined SSAL profile system
- route evaluation semantics and correctness metrics are unchanged

### v0.5.1

Patched route-history export to include route evaluation/task metadata and evaluator metrics while omitting the full prompt to keep exported JSON compact.

### v0.5.0

Added managed database persistence and optional Google OIDC authentication for shared dashboard deployments.

Highlights:

- `DATABASE_URL`-configured persistence
- local SQLite default
- PostgreSQL support through SQLAlchemy
- provider runs, prompt templates, route tasks, route evaluations, route history, and exports on the shared DB layer
- optional Google OIDC sign-in
- `AUTH_ALLOWED_EMAILS` allowlist
- signed-in user display and logout flow
- Authlib dependency for Streamlit OIDC

Notes:

- existing local `history.db` data is not automatically migrated to PostgreSQL
- authentication is disabled when Streamlit OIDC secrets are not configured
- route evaluation semantics are unchanged
