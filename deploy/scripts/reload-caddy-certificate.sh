#!/usr/bin/env bash
set -euo pipefail

docker exec polymerlit-gateway-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
