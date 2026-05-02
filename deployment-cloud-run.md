# Cloud Run deployment

This document describes the repeatable deployment path for `llm-compare-dashboard` on Google Cloud Run.

## Overview

The deployment uses:

- Google Cloud Run for the Streamlit app container
- Artifact Registry for the container image
- Secret Manager for API keys, `DATABASE_URL`, and Streamlit OIDC secrets
- Supabase PostgreSQL for managed persistence
- Google OAuth/OIDC for sign-in
- hosted GeoPackage URL for route-network data

## One-time setup

### 1. Enable Google Cloud services

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Create Artifact Registry repository

```bash
gcloud artifacts repositories create dashboard \
  --repository-format=docker \
  --location=europe-north1
```

### 3. Create Secret Manager secrets

Create these once:

```text
OPENAI_API_KEY
GEMINI_API_KEY
DATABASE_URL
STREAMLIT_SECRETS_TOML
```

Example:

```bash
printf '%s' 'your-openai-key' | gcloud secrets create OPENAI_API_KEY --data-file=-
printf '%s' 'your-gemini-key' | gcloud secrets create GEMINI_API_KEY --data-file=-
printf '%s' 'postgresql+psycopg://...' | gcloud secrets create DATABASE_URL --data-file=-
gcloud secrets create STREAMLIT_SECRETS_TOML --data-file=deploy/cloudrun/secrets.toml
```

For Supabase, use the pooler/session connection string if appropriate, and make sure the scheme is:

```text
postgresql+psycopg://...
```

not:

```text
postgresql://...
```

### 4. Prepare Cloud Run environment file

Copy:

```bash
cp deploy/cloudrun/env.example.yaml deploy/cloudrun/env.yaml
```

Example:

```yaml
AUTH_ALLOWED_EMAILS: "person1@example.com,person2@example.com"

NETWORK_GPKG_PATH: ""
NETWORK_GPKG_URL: "https://spatial-ninjas-bucket.s3.eu-north-1.amazonaws.com/osm_southern_helsinki_slimmed_cropped.gpkg"
NETWORK_GPKG_SHA256: "f51a76e9335d4aa9d3bcd7938ccc0ee293fb872dd175acadd4cae21a2cb0055e"
NETWORK_CACHE_DIR: "/tmp/network"

NETWORK_EDGES_LAYER: "slimmed_cropped_edges"
NETWORK_NODES_LAYER: "slimmed_cropped_nodes"
```

Do not put API keys, database passwords, or OAuth secrets in this file.

### 5. Prepare Streamlit OIDC secrets

Copy:

```bash
cp deploy/cloudrun/secrets.example.toml deploy/cloudrun/secrets.toml
```

For the first deployment, use a placeholder Cloud Run redirect URI if the service URL is not known yet:

```toml
[auth]
redirect_uri = "https://your-cloud-run-service-url/oauth2callback"
cookie_secret = "replace-with-long-random-string"

[auth.google]
client_id = "your-google-oauth-client-id"
client_secret = "your-google-oauth-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

After the first deploy, update this file with the real Cloud Run URL.

Generate a cookie secret:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

## Build and deploy

Use the helper script:

```bash
export PROJECT_ID=spatial-ninjas
export REGION=europe-north1
export SERVICE=llm-compare-dashboard
export VERSION=v0.5.0

./scripts/deploy_cloud_run.sh
```

The script:

- builds the Docker image
- pushes it to Artifact Registry
- deploys to Cloud Run
- grants the runtime service account access to required secrets
- mounts `STREAMLIT_SECRETS_TOML` as `/app/.streamlit/secrets.toml`
- prints the deployed Cloud Run URL and OAuth redirect URI

## OAuth redirect URI setup

After the first deployment, get the Cloud Run URL:

```bash
gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --format='value(status.url)'
```

The redirect URI is:

```text
https://your-cloud-run-service-url/oauth2callback
```

Add this exact URI in:

```text
Google Cloud Console
→ APIs & Services
→ Credentials
→ OAuth 2.0 Client IDs
→ your Web application client
→ Authorized redirect URIs
```

Then update `deploy/cloudrun/secrets.toml` so `[auth].redirect_uri` matches exactly.

Upload a new secret version:

```bash
gcloud secrets versions add STREAMLIT_SECRETS_TOML \
  --data-file=deploy/cloudrun/secrets.toml
```

Update the Cloud Run service to use the latest mounted secret:

```bash
gcloud run services update "$SERVICE" \
  --region "$REGION" \
  --update-secrets /app/.streamlit/secrets.toml=STREAMLIT_SECRETS_TOML:latest
```

## Docker notes

The Dockerfile runs Streamlit on Cloud Run’s provided port:

```bash
streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8080}
```

Cloud Run requires the container to listen on `0.0.0.0` and the configured port.

Local Docker test:

```bash
docker build -t llm-compare-dashboard .
docker run --rm -p 8080:8080 --env-file .env -e PORT=8080 llm-compare-dashboard
```

To test local container auth, mount local Streamlit secrets:

```bash
docker run --rm -p 8080:8080 \
  --env-file .env \
  -e PORT=8080 \
  -v "$PWD/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" \
  llm-compare-dashboard
```

## Secret access permissions

Cloud Run runs as a service account. That service account needs:

```text
roles/secretmanager.secretAccessor
```

for:

```text
OPENAI_API_KEY
GEMINI_API_KEY
DATABASE_URL
STREAMLIT_SECRETS_TOML
```

The deployment script grants this automatically to the default runtime service account.

If permission errors occur, grant access manually:

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in OPENAI_API_KEY GEMINI_API_KEY DATABASE_URL STREAMLIT_SECRETS_TOML; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member "serviceAccount:$RUNTIME_SA" \
    --role "roles/secretmanager.secretAccessor"
done
```

## Verification

After deployment:

1. Open the Cloud Run URL in an incognito window.
2. Confirm dashboard content is hidden before login.
3. Sign in with an allowlisted Google account.
4. Confirm sidebar shows the signed-in email.
5. Create or update a prompt template.
6. Run a route-finding test.
7. Open route evaluation history and confirm the saved run appears.
8. Redeploy or restart the service.
9. Confirm prompt templates and route history persist.
10. Confirm a non-allowlisted Google account sees access denied.

## Common problems

### `ModuleNotFoundError: No module named 'psycopg2'`

Your `DATABASE_URL` probably starts with `postgresql://` or `postgres://`.

Use:

```text
postgresql+psycopg://...
```

### Supabase host cannot resolve

Use the Supabase pooler/session connection string instead of manually editing the direct database hostname.

### Google says `redirect_uri_mismatch`

The URI in Google OAuth settings and `[auth].redirect_uri` must match exactly, including:

- `https`
- host
- `/oauth2callback`
- no extra trailing slash

### `gcloud --set-env-vars` fails on comma-separated emails

Use `deploy/cloudrun/env.yaml` instead of inline `--set-env-vars`.
