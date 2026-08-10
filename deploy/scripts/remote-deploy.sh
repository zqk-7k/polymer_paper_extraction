#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: remote-deploy.sh <git-sha> <release-archive>" >&2
  exit 2
fi

SHA="$1"
ARCHIVE="$2"
BASE_ROOT="/srv/polymerlit"
RELEASES_ROOT="$BASE_ROOT/releases"
RELEASE_ROOT="$RELEASES_ROOT/$SHA"
CURRENT_LINK="$BASE_ROOT/current"
ENV_FILE="/srv/polymerlit/deploy.env"
TEMP_ROOT="$RELEASES_ROOT/.${SHA}.tmp"

if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid git SHA" >&2
  exit 2
fi
if [[ ! -f "$ARCHIVE" ]]; then
  echo "release archive not found: $ARCHIVE" >&2
  exit 2
fi

mkdir -p "$RELEASES_ROOT"
rm -rf "$TEMP_ROOT"
mkdir -p "$TEMP_ROOT"
tar -xzf "$ARCHIVE" -C "$TEMP_ROOT"
rm -f "$ARCHIVE"

test -f "$TEMP_ROOT/deploy/compose.production.yml"
rm -rf "$RELEASE_ROOT"
mv "$TEMP_ROOT" "$RELEASE_ROOT"

COMPOSE_FILE="$RELEASE_ROOT/deploy/compose.production.yml"
export DEPLOY_TAG="$SHA"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build --pull api frontend
ln -sfn "$RELEASE_ROOT" "$CURRENT_LINK"
docker compose --env-file "$ENV_FILE" -f "$CURRENT_LINK/deploy/compose.production.yml" up -d --remove-orphans --force-recreate

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PUBLIC_PORT:-18120}/api/health" >/dev/null; then
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 3
done

docker compose --env-file "$ENV_FILE" -f "$CURRENT_LINK/deploy/compose.production.yml" ps
exit 1
