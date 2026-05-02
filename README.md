# llm-compare-dashboard

Current release: **v0.4.1**

This project is a Streamlit app for comparing OpenAI and Gemini responses, metadata, saved run history, and SSAL-native route-finding evaluations.

The app can be run locally on your own computer and opened in your browser:

```bash
streamlit run app.py
```

It can also be configured for shared deployment by loading the route-network GeoPackage from a hosted object URL instead of relying on a sibling local `research` checkout.

![Main dashboard view](docs/screenshot-main.png)

> [!IMPORTANT]
> Never commit API keys, `.env`, `history.db`, `.cache/`, or any other secrets/local state to Git.
> If an API key is accidentally committed, assume it is compromised, revoke it, and generate a new one.

## Version note

This repository is currently at `v0.4.1`.

This patch release builds on the `v0.4.0` route prompt-template workflow by adding remote GeoPackage loading with local cache fallback for route-finding deployments.

> [!NOTE]
> The dashboard installs the shared research code from the published `spatial-ninjas-research` package. Route-finding mode can now load the GeoPackage network either from a local path or from a remote hosted object with local cache reuse.
>
> For local development, the easiest setup is still often to keep the `research` repo as a sibling folder:
>
> ```text
> spatial-ninjas/
>   research/
>   llm-compare-dashboard/
> ```
>
> In that setup, `NETWORK_GPKG_PATH` can point to the GeoPackage inside the sibling `research` checkout. This sibling checkout is needed for route-network data convenience, not for importing the Python research package.

## Concepts used in this README

**SSAL** means Simplified Semantic Adjacency List. In this project, it is a text representation of a road/routing network. Each node lists its outgoing neighbouring nodes and edge attributes such as length, street name, direction flag, and coordinates. The dashboard sends this SSAL text to the model as route-finding context.

**OD pair** means origin-destination node pair. It is the selected start node and target node for one route-finding task.

**Ground truth** means the deterministic shortest route computed by the shared research-side graph code, currently using Dijkstra shortest path over the loaded SSAL-derived graph.

**Candidate route** means the route returned by a model response. The dashboard compares candidate routes against the ground-truth route and highlights invalid, missing, or diverging segments when evaluator output is available.

## What the dashboard does

The dashboard has three modes:

```text
General prompt comparison
  Send the same free-form prompt to OpenAI and Gemini.

Route finding
  Select an OD pair, generate an SSAL-based route prompt, run both providers,
  evaluate the returned routes, and save the route-specific metrics.

Route evaluation history
  Review saved route evaluations, filter previous runs, inspect rows,
  replay routes on maps, and export route-history data.
```

Current dashboard capabilities include:

- **General provider comparison**
  - side-by-side OpenAI/Gemini prompt comparison
  - model/settings controls, response metadata, token usage, latency, and retry info
  - persistent local SQLite history and JSON export

- **SSAL-native route finding**
  - `NetworkBundle` loading through the installed `research` package
  - local GeoPackage loading through `NETWORK_GPKG_PATH`
  - remote GeoPackage loading through `NETWORK_GPKG_URL` with local cache reuse
  - optional GeoPackage checksum verification through `NETWORK_GPKG_SHA256`
  - Dijkstra ground-truth route generation
  - parallel OpenAI/Gemini route calls
  - route evaluation with saved metrics and JSON export

- **Route prompt-template workflow**
  - built-in and saved prompt-template selector
  - editable prompt-template panel with validation before provider calls
  - save-as-new, update-selected, reset-to-default, and unsaved-change indicators
  - prompt template/profile metadata stored with saved route tasks

- **Route visualisation**
  - pre-call reference-route map preview
  - full-network context, selected origin/destination markers, and route-node tooltips
  - post-evaluation OpenAI/Gemini route maps
  - highlighted invalid, missing, and diverging route segments

- **Route evaluation history**
  - saved route-evaluation table with filters
  - selected-evaluation summary cards
  - segment inspection from saved evaluator output
  - map replay and route-history JSON export

## Why this exists

The goal is to make model comparison and route-navigation experiments reproducible.

Instead of manually copying prompts between providers or writing one-off scripts, the dashboard keeps the workflow in one app:

- run the same prompt against OpenAI and Gemini
- save provider calls and route evaluations to local SQLite history
- generate SSAL-based route prompts from a shared route network
- compare model-generated routes against Dijkstra ground truth
- inspect route outputs visually and segment-by-segment
- reuse prompt templates across repeated route experiments
- export history for offline research evaluation

## Relationship to the research package

The route-finding workflow depends on reusable modules from [`spatial-ninjas/research`](https://github.com/spatial-ninjas/research).

For normal installation and deployment, the dashboard uses the published PyPI package:

```txt
spatial-ninjas-research==0.1.0
```

The PyPI distribution name is `spatial-ninjas-research`, while the Python import package remains `research`:

```python
from research.graph import dijkstra_shortest_path
from research.evaluation import evaluate_route_response
from research.network_loader import load_network_bundle_from_gpkg
```

The dashboard also uses the research-side network cache helper for remote GeoPackage loading:

```python
from research.network_loader import fetch_or_reuse_cached_file
```

Large GeoPackage data files are not distributed through the PyPI package. The package provides reusable code; the GeoPackage network data is configured separately through environment variables.

For local development, you can still use an editable checkout if you are changing both repositories together.

Expected local development layout:

```text
spatial-ninjas/
  research/
  llm-compare-dashboard/
```

From inside `llm-compare-dashboard`:

```bash
pip uninstall spatial-ninjas-research
pip install -e ../research
```

This editable install is a development override. Deployment should use the versioned package from PyPI.

## Current app modes

### General prompt comparison

The general mode sends one prompt to both providers and displays the outputs side by side.

It includes:

- OpenAI model selection
- Gemini model selection
- max response token setting
- Gemini thinking budget setting:
  - `dynamic`
  - `off`
  - `custom`
- status steps while provider calls run
- provider finished/failed messages with attempt counts
- response cards for OpenAI and Gemini
- metadata expanders
- optional raw response expanders
- rough OpenAI cost estimate
- current browser-session history
- persistent saved-history table
- per-comparison JSON export
- saved-history JSON export

The general view saves two generic provider rows per run:

```text
one OpenAI row
one Gemini row
```

### Route finding

The route-finding mode loads the configured SSAL-native routing network, lets you choose an origin and destination node, generates a route-finding prompt, calls both providers, evaluates the returned routes, and saves the results.

It is organized around four main workflows:

- **Route setup and reference route**
  - `NetworkBundle` loading from a local or cached GeoPackage
  - local-first network resolution using `NETWORK_GPKG_PATH`
  - remote fallback using `NETWORK_GPKG_URL`
  - optional checksum verification using `NETWORK_GPKG_SHA256`
  - cached network loading with `st.cache_resource`
  - default origin node `1004552350`
  - default destination node `9713069615`
  - Dijkstra ground-truth path, length, and edge-count display

- **Prompt-template workflow**
  - dedicated right-side route prompt-template panel
  - built-in default route prompt template
  - saved local route prompt-template selector
  - editable route prompt template
  - prompt-template validation before provider calls
  - save-as-new and update-selected template controls
  - unsaved-change indicators for edited templates
  - reset-to-built-in-default control
  - generated prompt preview and download

- **Route maps**
  - pre-call map preview for the selected Dijkstra reference route
  - full-network map context in route preview
  - selected origin/destination markers
  - toggleable Dijkstra reference route-node markers
  - side-by-side OpenAI and Gemini route maps after evaluation
  - candidate route and ground-truth route overlays
  - selected origin/destination markers on provider result maps
  - toggleable candidate and ground-truth route-node markers
  - highlighted invalid, missing, and diverging candidate segments when evaluator output is available
  - route-focused bounds for provider result maps

- **Provider calls, evaluation, and persistence**
  - OpenAI and Gemini API calls in parallel
  - status steps while the route test runs
  - provider finished/failed messages with attempt counts
  - route evaluation using `research.evaluation.evaluate_route_response()`
  - route task persistence with prompt template/profile metadata
  - route evaluation persistence
  - detailed provider/evaluation cards
  - current route-test JSON export

A route result is shown as satisfactory only when:

```text
status == evaluated
valid_json == true
valid_path == true
exact_path_match == true
```

Other evaluated results are shown as needing review rather than as green success.

### Route evaluation history

The route evaluation history mode is for reviewing saved route-specific evaluation rows without running new provider calls.

It is organized around three main workflows:

- **Saved evaluation browsing**
  - compact saved-evaluation overview table loaded from local SQLite history
  - provider filter
  - satisfactory / needs-review status filter
  - detailed history table in a collapsed expander
  - saved route-history JSON export for offline research evaluation

- **Selected evaluation summary**
  - selected-evaluation summary card
  - route-level metrics such as candidate length, ground-truth length, relative length error, node overlap, and edge overlap
  - candidate/reference edge counts
  - prompt template and SSAL profile metadata where available

- **Route inspection and replay**
  - route segment inspection table
  - raw evaluator output expander for debugging
  - map replay for selected saved evaluations
  - full-network context in replay maps
  - selected origin/destination markers in replay maps
  - candidate route, ground-truth route, route-node markers, and segment highlights as separate toggleable map layers
  - indexed candidate and ground-truth route-node tooltips
  - route-focused bounds for replay maps
  - toggleable network metadata overlay inside rendered maps

The segment inspection table breaks a saved candidate route into ordered node-to-node segments and labels each segment using evaluator output saved in `raw_evaluation_json.candidate_validation`.

Current segment statuses include:

```text
ok
extra_segment
unknown_from_node
unknown_to_node
missing_edge
```

The dashboard does not re-validate graph edges for segment inspection. It formats the saved evaluator output produced by `research.evaluation`, so route parsing, unknown-node detection, missing-edge detection, and graph validation remain in the shared research evaluator.

This keeps the API-call workflow separate from result review. The history view is display-only: it does not include destructive actions such as clearing saved evaluations.

## Release notes

### v0.4.1

Added remote GeoPackage loading with local cache fallback for route-finding deployments.

Highlights:

- route-finding mode can now load the GeoPackage from a hosted object URL
- local `NETWORK_GPKG_PATH` remains the first priority for local development
- remote fallback uses `NETWORK_GPKG_URL`
- downloaded GeoPackages are cached under `NETWORK_CACHE_DIR`
- optional `NETWORK_GPKG_SHA256` verification is supported
- cached files can be reused across Streamlit reruns and normal client refreshes
- `.env.example` and README now document local/deployment-compatible network configuration

Notes:

- this release does not change route evaluation semantics
- the dashboard still loads the resolved local or cached GeoPackage through `research.network_loader.load_network_bundle_from_gpkg()`
- remote download/cache handling is delegated to `research.network_loader.fetch_or_reuse_cached_file()`
- managed database support, authentication, and deployment packaging remain separate follow-up work

### v0.4.0

Added a reusable route prompt-template workflow for route-finding experiments.

Breaking change:

- the built-in default route prompt was updated to match the current SSAL representation
- new route-finding runs may not be directly comparable with earlier runs that used the old default prompt wording

Highlights:

- built-in default route prompt now describes the current SSAL shape correctly
- current default SSAL profile is named and shown in the UI
- route prompt templates are validated before provider calls
- validation catches missing required placeholders, unknown placeholders, and malformed braces
- route-finding mode now has a dedicated right-side prompt-template panel
- built-in default template remains available as a selectable option
- user-created prompt templates can be saved locally and reused
- saved templates can be edited and updated
- edited templates can be saved as new prompt variants
- unsaved template edits are highlighted in the UI
- generated prompt preview and download are preserved next to the template editor
- route tasks store the selected prompt template name, template snapshot, SSAL profile name, and SSAL hash
- route-history display/export includes prompt/profile metadata where useful

Notes:

- this release focuses on prompt-template experiments, not selectable SSAL-profile generation
- the dashboard records the SSAL profile associated with a template/run, but still uses the current fixed SSAL representation
- selectable/customisable SSAL profiles are left for a follow-up issue

### v0.3.1

Added the first usable network-exploration and route-node inspection workflow on top of the `v0.3.0` map comparison release.

Highlights:

- full-network context is now available on route maps
- selected origin and destination markers are shown on preview, result, and replay maps
- route-finding preview shows a compact reference-route summary with:
  - ground-truth length
  - number of ground-truth edges
- Dijkstra reference route nodes can be inspected as a toggleable map layer
- provider candidate route nodes can be inspected as toggleable map layers
- ground-truth route nodes can be inspected as toggleable map layers
- route-node tooltips include node ID, route index, route type, and relevant provider/evaluation metadata
- route-history replay maps now have parity with route-finding maps:
  - full-network context
  - selected origin/destination markers
  - candidate/reference route-node layers
  - segment highlights
- map bounds behavior was refined:
  - pre-call preview maps fit to the full network
  - provider result maps fit to the relevant candidate/reference route area
  - history replay maps fit to the selected saved route area

Notes:

- this completes the first usable map workflow for both route comparison and pre-call route/network exploration
- richer follow-ups such as map-click OD selection, easier node-ID copying, and grouped repeated-run route comparison are intentionally left for later issues

### v0.3.0

Added route-map visualisation for route comparison and highlighted route replay.

Highlights:

- reusable Folium route maps integrated into the dashboard
- pre-call Dijkstra reference-route map preview in route-finding mode
- side-by-side OpenAI and Gemini route maps after route evaluation
- map replay for saved route evaluations in route history
- candidate route, ground-truth route, and segment highlights as separate toggleable map layers
- highlighted invalid, missing, unknown-node, and diverging route segments based on evaluator output
- shared route-map helper module for path parsing, segment-row formatting, highlighting, map embedding, and safe filenames
- toggleable metadata overlay inside rendered maps
- map embedding uses `st.iframe` data URLs instead of deprecated `st.components.v1.html`
- increased default token budgets for route responses

Known remaining map work at the time of `v0.3.0`:

- full loaded-network layer was not implemented yet
- route node markers and node-ID inspection/copying were still future work
- map-based OD-pair exploration was not complete yet

These items are addressed at a first usable level in `v0.3.1`.

### v0.2.1

Added route segment inspection for saved route evaluations.

Highlights:

- compact saved-evaluation overview table in the route history view
- selected-evaluation summary card with route-level metrics
- segment inspection table for saved candidate routes
- segment labels for matching, extra, unknown-node, and missing-edge cases
- raw evaluator output expander for debugging
- route segment inspection uses saved `research.evaluation` output instead of revalidating graph edges in the dashboard

### v0.2.0

Added the dedicated route-evaluation history view.

Highlights:

- separate `Route evaluation history` mode
- saved route-evaluation table
- provider and status filters
- selected-row inspection
- route-history JSON export from the history view
- route-finding mode kept focused on running new route tests

## Setup

### 1. Clone the dashboard repo

For normal use, clone this repository:

```bash
git clone https://github.com/spatial-ninjas/llm-compare-dashboard.git
cd llm-compare-dashboard
```

The shared research utilities are installed from PyPI through `requirements.txt`.

If you are developing the dashboard and research package together, or if you want to use the local GeoPackage from the research repo, you may keep both repositories side by side:

```text
spatial-ninjas/
  research/
  llm-compare-dashboard/
```

The sibling `research` checkout is optional for Python imports, but useful for local network data through `NETWORK_GPKG_PATH`.

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

This installs the published research package:

```txt
spatial-ninjas-research==0.1.0
```

To verify that the dashboard is using the installed package:

```bash
python - <<'PY'
import research
print(research.__version__)
print(research.__file__)
PY
```

The printed path should normally point inside `.venv/.../site-packages/research`.

For local editable development against a sibling research checkout, override the package with:

```bash
pip uninstall spatial-ninjas-research
pip install -e ../research
```

### 4. Run smoke tests for imports

After installing dependencies, verify that the dashboard can import the shared packages:

```bash
python -c "from research.graph import build_graph_from_ssal; print('graph ok')"
python -c "from research.evaluation import evaluate_route_response; print('evaluation ok')"
python -c "from research.network_loader import load_network_bundle_from_gpkg; print('network loader ok')"
python -c "from research.network_loader import fetch_or_reuse_cached_file; print('network cache helper ok')"
python -c "from dashboard.views.general import render_general_view; print('general view ok')"
python -c "from dashboard.views.route_finding import render_route_finding_view; print('route view ok')"
python -c "from dashboard.views.route_history import render_route_history_view; print('route history view ok')"
python -c "from dashboard.route_visualization import RouteVisualization; print('route visualization ok')"
python -c "from dashboard.route_map_helpers import build_segment_rows_from_evaluation; print('route map helpers ok')"
```

You can also compile the main dashboard modules:

```bash
python -m py_compile \
  app.py \
  dashboard/api_clients.py \
  dashboard/db.py \
  dashboard/network.py \
  dashboard/route_prompts.py \
  dashboard/route_visualization.py \
  dashboard/route_map_helpers.py \
  dashboard/views/general.py \
  dashboard/views/route_finding.py \
  dashboard/views/route_history.py
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
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Route-finding network data
#
# Local development path. Takes priority if the file exists.
# This may point to a sibling research checkout for now.
NETWORK_GPKG_PATH=../research/data/raw/routing_networks/osm_southern_helsinki_slimmed_cropped.gpkg

# Remote deployment fallback. Used when NETWORK_GPKG_PATH is missing or invalid.
NETWORK_GPKG_URL=https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_SHA256=f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e
NETWORK_CACHE_DIR=.cache/network

# Layers inside the GeoPackage.
NETWORK_EDGES_LAYER=slimmed_cropped_edges
NETWORK_NODES_LAYER=slimmed_cropped_nodes
```

It is fine to keep `NETWORK_GPKG_PATH`, `NETWORK_GPKG_URL`, and `NETWORK_GPKG_SHA256` configured at the same time.

The dashboard resolves the network in this order:

1. If `NETWORK_GPKG_PATH` points to an existing file, use it.
2. Otherwise, if `NETWORK_GPKG_URL` is set, fetch or reuse a cached remote file.
3. Otherwise, show a configuration error.

For local development, `NETWORK_GPKG_PATH` can use the GeoPackage from a sibling `research` checkout. In deployment, that local path may not exist, so the dashboard falls back to `NETWORK_GPKG_URL` and stores the downloaded file under `NETWORK_CACHE_DIR`.

If `NETWORK_GPKG_SHA256` is provided, the downloaded or cached file must match it. A mismatch is reported as a configuration error instead of silently loading the file.

### 6. Run the app

```bash
streamlit run app.py
```

Open the local URL shown by Streamlit, usually:

```text
http://localhost:8501
```

## Route-finding network configuration

The route-finding mode loads the routing network through the installed `research` package.

The loading path is:

```text
local path or cached remote GeoPackage
  ↓
research.network_loader.load_network_bundle_from_gpkg()
  ↓
SSAL text
  ↓
SSAL-derived graph
  ↓
NetworkBundle
```

The dashboard does not parse the GeoPackage or build the graph itself. It reuses the shared research-side network loader so the dashboard and research evaluator use the same SSAL-native representation.

### Network resolution order

The dashboard resolves the GeoPackage in this order:

1. If `NETWORK_GPKG_PATH` points to an existing local file, use it.
2. Otherwise, if `NETWORK_GPKG_URL` is set, fetch or reuse a cached remote file.
3. Otherwise, show a configuration error.

This means local development can keep using a sibling research checkout, while deployment can use a hosted GeoPackage object.

Recommended local/deployment-compatible configuration:

```env
# Local development path. Takes priority if it exists.
NETWORK_GPKG_PATH=../research/data/raw/routing_networks/osm_southern_helsinki_slimmed_cropped.gpkg

# Remote fallback. Used when the local path is missing or invalid.
NETWORK_GPKG_URL=https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_SHA256=f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e
NETWORK_CACHE_DIR=.cache/network

# Layers inside the GeoPackage.
NETWORK_EDGES_LAYER=slimmed_cropped_edges
NETWORK_NODES_LAYER=slimmed_cropped_nodes
```

### Hosted object setup

The remote GeoPackage may be hosted on S3 or any HTTPS-accessible object URL.

Expected setup:

```text
canonical GeoPackage uploaded to hosted object storage
  ↓
dashboard configured with NETWORK_GPKG_URL
  ↓
optional NETWORK_GPKG_SHA256 verifies the file
  ↓
NETWORK_CACHE_DIR stores the cached local copy
```

For the current hosted object, the default `.env.example` uses:

```env
NETWORK_GPKG_URL=https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_SHA256=f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e
```

If the hosted object is private, the deployment environment must provide access through a presigned URL, platform credentials, or another fetch mechanism supported by `research.network_loader.fetch_or_reuse_cached_file()`.

### Cache behavior

Remote files are fetched or reused through:

```python
research.network_loader.fetch_or_reuse_cached_file()
```

The resolved local or cached file is then loaded through:

```python
research.network_loader.load_network_bundle_from_gpkg()
```

The route network bundle is cached with Streamlit resource caching, so normal client refreshes do not repeatedly reload the GeoPackage or rebuild the network bundle.

If a cached file already exists and passes checksum validation, the dashboard can reuse it even if the remote URL is temporarily unavailable. If the cache is removed, the remote URL and checksum must be valid for remote loading to succeed.

When the route mode is opened, it loads the configured GeoPackage into a cached `NetworkBundle`. The route mode displays short network status in the sidebar and fuller debug details in the collapsed debug panel:

- GeoPackage path
- edge layer
- node layer
- SSAL hash
- node count
- SSAL preview

If network loading fails, the route-finding view shows a clear Streamlit error and reminds the user to check:

```text
NETWORK_GPKG_PATH
NETWORK_GPKG_URL
NETWORK_GPKG_SHA256
NETWORK_CACHE_DIR
NETWORK_EDGES_LAYER
NETWORK_NODES_LAYER
```

## Route prompt template workflow

The route-finding prompt is generated from:

```text
prompt_template + ssal_text + origin + destination
```

Route finding mode includes a dedicated prompt-template panel. It supports:

- selecting the built-in default prompt template
- selecting locally saved prompt templates
- editing the current template text
- validating placeholders before provider calls
- saving the current editor text as a new template
- updating an existing saved template
- resetting the editor to the built-in default
- previewing and downloading the generated prompt

The default prompt asks the model to return strict JSON using the route schema expected by the research evaluator:

```json
{
  "origin": "1004552350",
  "destination": "9713069615",
  "total_length": 123.4,
  "route": [
    {"node": "1004552350", "edge_name": "start"},
    {"node": "...", "edge_name": "[STREET NAME]"},
    {"node": "9713069615", "edge_name": "[STREET NAME]"}
  ],
  "status": "success"
}
```

The editable prompt template supports these placeholders:

```text
{origin}
{destination}
{ssal_text}
```

Literal JSON or SSAL braces must be escaped as `{{` and `}}`.

Template validation runs before provider calls. The route test button is disabled if the current template is invalid. Validation catches:

- missing required placeholders
- unknown placeholders
- malformed formatting braces

The current default SSAL profile is:

```text
default_length_name_oneway_coords
```

The dashboard records the SSAL profile name with saved route tasks. It does not yet let the user choose or regenerate alternative SSAL representations. Selectable/customisable SSAL profiles are planned as follow-up work.

Reusable templates do not store full SSAL text. Saved route tasks store a snapshot of the actual prompt template text used for the run, so old experiments remain reproducible even if a saved template is later edited.

## Persistence model

The app creates `history.db` in the same folder as `app.py`.

The persistence model separates generic provider calls, reusable prompt templates, and route-specific evaluation data:

```text
runs
  one row per OpenAI/Gemini API call

route_prompt_templates
  one row per saved reusable route prompt template

route_tasks
  one row per route prompt/task

route_evaluations
  one row per evaluated provider response for a route task
```

### `runs`

Used by both general mode and route mode.

Stores:

- prompt
- provider
- model
- request success flag
- latency
- token metadata
- finish/status info
- response text
- error text
- raw JSON
- Gemini thinking metadata
- retry attempt count

`save_run()` returns the inserted run ID so route evaluations can link back to provider calls.

### `route_prompt_templates`

Stores reusable local route prompt templates:

- name
- description
- template text
- expected SSAL profile name
- creation/update timestamps
- built-in flag reserved for future migration flexibility

The built-in default prompt is kept in `dashboard.route_prompts` rather than seeded into SQLite.

### `route_tasks`

Stores one route-finding task:

- origin
- destination
- SSAL hash
- prompt template snapshot
- prompt template name
- SSAL profile name
- Dijkstra ground-truth path
- Dijkstra ground-truth length

### `route_evaluations`

Stores one evaluated provider response for one route task:

- task ID
- run ID
- provider/model
- valid JSON flag
- valid path flag
- exact path match flag
- candidate route path/length
- ground-truth path/length
- relative/absolute length errors
- declared-length errors
- node/edge overlap
- error text
- raw evaluator JSON

The route evaluation history view uses the saved candidate path, ground-truth path, and raw evaluator JSON to render segment inspection without duplicating route validation logic in the dashboard.

The app auto-migrates older `history.db` files by adding missing generic-history columns and creating route-specific tables when needed.

## Export behavior

### General mode

General mode supports:

- exporting the latest comparison as JSON
- exporting saved generic provider history as JSON

### Route modes

Route finding supports:

- exporting the latest route test as JSON

Route evaluation history supports:

- exporting saved route-history rows as JSON

The saved route-history export is compatible with the research repo’s offline history evaluator. Exported route rows include top-level route metadata:

```json
{
  "id": 123,
  "created_at": "2026-04-28 10:00:00",
  "provider": "OpenAI",
  "model": "gpt-5.4-mini",
  "finish_status": "completed",
  "max_output_tokens": 2048,
  "origin": "1004552350",
  "destination": "9713069615",
  "ssal_hash": "abc123...",
  "prompt_template_name": "Built-in default route prompt",
  "ssal_profile_name": "default_length_name_oneway_coords",
  "prompt": "...",
  "response_text": "{...model route JSON...}",
  "error_text": null
}
```

The required fields for offline route evaluation are:

```text
origin
destination
response_text
```

## Files

```text
llm-compare-dashboard/
  app.py                         Streamlit entrypoint, app version, and mode router
  requirements.txt               Python dependencies, including spatial-ninjas-research
  .env.example                   Environment variable template
  history.db                     Local SQLite DB, created automatically and ignored by Git
  .cache/                        Optional local cache for remotely fetched network data, ignored by Git

  dashboard/
    api_clients.py               OpenAI/Gemini API wrappers and retry behavior
    db.py                        SQLite persistence helpers and prompt-template storage
    network.py                   Local/remote NetworkBundle loading and GeoPackage cache resolution
    route_prompts.py             Built-in route prompt template, SSAL profile metadata, and validation
    route_visualization.py       Reusable Folium route visualisation helpers
    route_map_helpers.py         Shared map embedding, network-layer, and segment-highlight helpers
    views/
      general.py                 General prompt-comparison view
      route_finding.py           Route-finding view for new route tests
      route_history.py           Saved route-evaluation history view

  scripts/
    smoke_route_visualization.py Standalone route visualisation smoke script

  docs/
    screenshot-main.png          README screenshot
```

## Route visualisation smoke test

The reusable route visualisation interface can be checked without running provider calls:

```bash
python scripts/smoke_route_visualization.py
open route_visualization_test.html
```

The smoke map disables online base-map tiles by default, so it avoids OpenStreetMap tile-server blocking when opened from a local HTML file.

## Network loading manual verification

These checks are useful when changing route-network configuration or deployment setup.

### Local path priority

Configure a valid local path and a valid remote fallback:

```env
NETWORK_GPKG_PATH=../research/data/raw/routing_networks/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_URL=https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg
NETWORK_GPKG_SHA256=f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e
```

Expected result:

```text
The local path is used first.
Remote download is not needed.
Route-finding mode loads normally.
```

### Remote fallback

Make `NETWORK_GPKG_PATH` invalid while keeping `NETWORK_GPKG_URL` and `NETWORK_GPKG_SHA256` valid.

Expected result:

```text
The remote GeoPackage is downloaded or reused from NETWORK_CACHE_DIR.
Route-finding mode loads normally.
```

### Cache reuse

After the remote file has been cached, temporarily make both `NETWORK_GPKG_PATH` and `NETWORK_GPKG_URL` unavailable.

Expected result:

```text
The existing cached file can still be reused if it passes checksum validation.
Route-finding mode loads normally.
```

### Checksum mismatch

Remove the cached file, keep `NETWORK_GPKG_URL` valid, and set an invalid `NETWORK_GPKG_SHA256`.

Expected result:

```text
Network loading fails with a clear checksum/configuration error.
The dashboard does not silently load a file with the wrong checksum.
```

### Streamlit resource caching

Open route-finding mode and refresh the client.

Expected result:

```text
load_route_network_bundle() is cached by Streamlit resource caching.
The network bundle is not reloaded on normal client refresh.
```

## Notes

- The OpenAI cost display is only a rough estimate based on the hard-coded model pricing table in the app.
- Gemini can return transient overload errors such as `503 UNAVAILABLE`; the API client retries transient failures automatically with exponential backoff.
- Gemini may consume tokens as `thoughts_tokens`, which can explain short visible outputs when `max_output_tokens` is small.
- Route-finding mode runs OpenAI and Gemini calls in parallel because those calls are network-bound.
- The dashboard shows per-call usage metadata. It does not show a provider-wide “tokens left” counter.
- Saved-history export is available in the general and route-evaluation history views, but destructive “clear history” controls are intentionally not shown in the current UI.
- Route comparison maps are available in route-finding results and route-evaluation history.
- Route maps now include full-network context, selected origin/destination markers, route-node marker layers, and segment highlights.
- Route finding now includes a reusable prompt-template selector/editor with validation and local template persistence.
- Route finding can load the GeoPackage from either a local path or a remote hosted object with cache reuse.
- Future map improvements may include map-click OD selection, easier node-ID copying, and grouped repeated-run route comparison.
- Keep `.env` out of Git.
- Keep `history.db` out of Git.
- Keep `.cache/` out of Git.
