#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: remote-deploy.sh <git-sha> <release-source>" >&2
  exit 2
fi

SHA="$1"
SOURCE="$2"
BASE_ROOT="/srv/polymerlit"
REPO_ROOT="$BASE_ROOT/app"
RELEASES_ROOT="$BASE_ROOT/releases"
RELEASE_ROOT="$RELEASES_ROOT/$SHA"
CURRENT_LINK="$BASE_ROOT/current"
ENV_FILE="/srv/polymerlit/deploy.env"
TEMP_ROOT="$RELEASES_ROOT/.${SHA}.tmp"
DATA_ROOT="$BASE_ROOT/data"
DATA_WORKTREE="$BASE_ROOT/.data-worktree-$SHA"
DATA_STAGE_ROOT="$BASE_ROOT/.data-stage-$SHA"

if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid git SHA" >&2
  exit 2
fi
if [[ ! -f "$SOURCE" ]]; then
  echo "release source not found: $SOURCE" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "production environment file not found: $ENV_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

ARCHIVE="$SOURCE"
if [[ "$SOURCE" == *.bundle ]]; then
  BUNDLE_REF="refs/deploy/$SHA"
  git -C "$REPO_ROOT" fetch "$SOURCE" "$BUNDLE_REF"
  git -C "$REPO_ROOT" update-ref "$BUNDLE_REF" "$SHA"
  git -C "$REPO_ROOT" cat-file -e "${SHA}^{commit}"
  ARCHIVE="$BASE_ROOT/.release-${SHA}.tar.gz"
  git -C "$REPO_ROOT" archive --format=tar.gz --output="$ARCHIVE" "$SHA"
  rm -f "$SOURCE"
fi

PREVIOUS_SHA=""
if [[ -L "$CURRENT_LINK" ]]; then
  PREVIOUS_SHA="$(basename "$(readlink -f "$CURRENT_LINK")")"
fi

batch_changed=1
pdfs_changed=1
if [[ "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]] && git -C "$REPO_ROOT" cat-file -e "${PREVIOUS_SHA}^{commit}"; then
  git -C "$REPO_ROOT" diff --quiet "$PREVIOUS_SHA" "$SHA" -- batch_results && batch_changed=0
  git -C "$REPO_ROOT" diff --quiet "$PREVIOUS_SHA" "$SHA" -- source_pdfs && pdfs_changed=0
fi

cleanup_data_stage() {
  if [[ -d "$DATA_WORKTREE" ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$DATA_WORKTREE" >/dev/null 2>&1 || rm -rf "$DATA_WORKTREE"
  fi
  rm -rf "$DATA_STAGE_ROOT"
  rm -f "/tmp/polymerlit-${SHA}-deploy.sh"
}
trap cleanup_data_stage EXIT

if (( batch_changed || pdfs_changed )); then
  rm -rf "$DATA_WORKTREE" "$DATA_STAGE_ROOT"
  git -C "$REPO_ROOT" worktree prune
  git -C "$REPO_ROOT" worktree add --detach "$DATA_WORKTREE" "$SHA" >/dev/null
  mkdir -p "$DATA_STAGE_ROOT"

  if (( batch_changed )); then
    mkdir -p "$DATA_STAGE_ROOT/batch_results"
    if [[ -d "$DATA_WORKTREE/batch_results" ]]; then
      cp -a "$DATA_WORKTREE/batch_results/." "$DATA_STAGE_ROOT/batch_results/"
    fi
  fi
  if (( pdfs_changed )); then
    mkdir -p "$DATA_STAGE_ROOT/source_pdfs"
    if [[ -d "$DATA_WORKTREE/source_pdfs" ]]; then
      cp -a "$DATA_WORKTREE/source_pdfs/." "$DATA_STAGE_ROOT/source_pdfs/"
    fi
  fi

  git -C "$REPO_ROOT" worktree remove --force "$DATA_WORKTREE" >/dev/null
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

replace_data_directory() {
  local staged="$1"
  local target="$2"
  local backup="${target}.previous"
  mkdir -p "$(dirname "$target")"
  rm -rf "$backup"
  if [[ -e "$target" ]]; then
    mv "$target" "$backup"
  fi
  mv "$staged" "$target"
  rm -rf "$backup"
}

if (( batch_changed )); then
  replace_data_directory "$DATA_STAGE_ROOT/batch_results" "$DATA_ROOT/batch_results"
fi
if (( pdfs_changed )); then
  replace_data_directory "$DATA_STAGE_ROOT/source_pdfs" "$DATA_ROOT/source_pdfs"
fi

ln -sfn "$RELEASE_ROOT" "$CURRENT_LINK"
docker compose --env-file "$ENV_FILE" -f "$CURRENT_LINK/deploy/compose.production.yml" up -d --remove-orphans --force-recreate

if [[ -d "$RELEASE_ROOT/deploy/systemd" ]]; then
  install -m 0644 "$RELEASE_ROOT/deploy/systemd/polymerlit-cert-renew.service" /etc/systemd/system/polymerlit-cert-renew.service
  install -m 0644 "$RELEASE_ROOT/deploy/systemd/polymerlit-cert-renew.timer" /etc/systemd/system/polymerlit-cert-renew.timer
  systemctl daemon-reload
  systemctl enable --now polymerlit-cert-renew.timer
fi

for _ in $(seq 1 30); do
  if curl -fsS "${PUBLIC_URL:-http://127.0.0.1:${PUBLIC_PORT:-18120}}/api/health" >/dev/null; then
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 3
done

docker compose --env-file "$ENV_FILE" -f "$CURRENT_LINK/deploy/compose.production.yml" ps
exit 1
