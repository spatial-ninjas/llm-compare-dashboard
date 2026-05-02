#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-spatial-ninjas}"
REGION="${REGION:-europe-north1}"
SERVICE="${SERVICE:-llm-compare-dashboard}"
VERSION="${VERSION:-v0.5.0}"
REPOSITORY="${REPOSITORY:-dashboard}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:$VERSION"

ENV_FILE="${ENV_FILE:-deploy/cloudrun/env.yaml}"
STREAMLIT_SECRETS_FILE="${STREAMLIT_SECRETS_FILE:-deploy/cloudrun/secrets.toml}"

REQUIRED_SECRETS=(
  OPENAI_API_KEY
  GEMINI_API_KEY
  DATABASE_URL
  STREAMLIT_SECRETS_TOML
)

echo "Using project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "Enabling required services..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  >/dev/null

echo "Ensuring Artifact Registry repository exists..."
if ! gcloud artifacts repositories describe "$REPOSITORY" \
  --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format=docker \
    --location "$REGION"
fi

echo "Checking required local files..."
test -f "$ENV_FILE" || {
  echo "Missing env file: $ENV_FILE" >&2
  echo "Copy deploy/cloudrun/env.example.yaml to deploy/cloudrun/env.yaml and adjust values." >&2
  exit 1
}

test -f "$STREAMLIT_SECRETS_FILE" || {
  echo "Missing Streamlit secrets file: $STREAMLIT_SECRETS_FILE" >&2
  echo "Copy deploy/cloudrun/secrets.example.toml to deploy/cloudrun/secrets.toml and fill in real values." >&2
  exit 1
}

echo "Ensuring Secret Manager secrets exist..."
for SECRET in "${REQUIRED_SECRETS[@]}"; do
  if ! gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
    echo "Missing secret: $SECRET"
    echo "Create it first or add a version manually."
    echo
    echo "Example:"
    echo "  printf '%s' 'VALUE' | gcloud secrets create $SECRET --data-file=-"
    exit 1
  fi
done

echo "Adding new Streamlit secrets version..."
gcloud secrets versions add STREAMLIT_SECRETS_TOML \
  --data-file="$STREAMLIT_SECRETS_FILE" >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Granting runtime service account access to secrets..."
for SECRET in "${REQUIRED_SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member "serviceAccount:$RUNTIME_SA" \
    --role "roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
done

echo "Building image: $IMAGE"
gcloud builds submit --tag "$IMAGE"

echo "Deploying Cloud Run service..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --env-vars-file "$ENV_FILE" \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest \
  --set-secrets DATABASE_URL=DATABASE_URL:latest \
  --set-secrets /app/.streamlit/secrets.toml=STREAMLIT_SECRETS_TOML:latest

SERVICE_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --format='value(status.url)')"

echo
echo "Deployed:"
echo "  $SERVICE_URL"
echo
echo "Google OAuth redirect URI should be:"
echo "  $SERVICE_URL/oauth2callback"
echo
echo "Make sure this exact URI is listed in Google OAuth authorized redirect URIs."
