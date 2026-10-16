#!/usr/bin/env bash
# Block until the A1111 API answers (Docker healthcheck, or /internal/ping for
# images built before the healthcheck existed).
#   usage: docker/tools/wait_healthy.sh [container] [timeout_s] [api_url]
set -u
container="${1:-tdeforum-a1111}"
timeout="${2:-600}"
api="${3:-http://127.0.0.1:7865}"
start=$(date +%s)

while :; do
    elapsed=$(( $(date +%s) - start ))
    state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo missing)"
    if [ "$state" != "running" ]; then
        echo "$container is $state"; exit 1
    fi
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
    if [ "$health" = "healthy" ] || { [ "$health" = "none" ] && curl -fsS "$api/internal/ping" >/dev/null 2>&1; }; then
        echo "$container ready after ${elapsed}s"; exit 0
    fi
    if [ "$elapsed" -ge "$timeout" ]; then
        echo "$container not ready after ${elapsed}s (health: $health). Try: make logs"; exit 1
    fi
    sleep 2
done
