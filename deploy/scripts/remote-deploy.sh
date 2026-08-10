#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: remote-deploy.sh <git-sha>" >&2
  exit 2
fi

SHA="$1"
APP_ROOT="/srv/polymerlit/app"
ENV_FILE="/srv/polymerlit/deploy.env"
COMPOSE_FILE="$APP_ROOT/deploy/compose.production.yml"

cd "$APP_ROOT"
git fetch --depth=1 origin "$SHA"
git checkout --detach "$SHA"

export DEPLOY_TAG="$SHA"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build --pull api frontend
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PUBLIC_PORT:-18120}/api/health" >/dev/null; then
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 3
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
exit 1
