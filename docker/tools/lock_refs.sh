#!/usr/bin/env bash
# Pin Dockerfile.a1111's ARG *_REF defaults to the commits running in a container,
# so the next build reproduces a known-good image exactly.
#   usage: docker/tools/lock_refs.sh [container]   (default: tdeforum-a1111)
set -euo pipefail
container="${1:-tdeforum-a1111}"
here="$(cd "$(dirname "$0")/../.." && pwd)"
dockerfile="$here/Dockerfile.a1111"

refs="$(docker exec -i "$container" bash -s < "$here/docker/tools/versions.sh" | grep -E '^[A-Z0-9_]+_REF=[0-9a-f]{40}$' || true)"
if [ -z "$refs" ]; then
    echo "Could not read commits from $container (is it running?)" >&2
    exit 1
fi

while IFS='=' read -r key sha; do
    sed -i "s|^ARG ${key}=.*|ARG ${key}=${sha}|" "$dockerfile"
    echo "pinned ${key}=${sha}"
done <<< "$refs"

git -C "$here" --no-pager diff --stat -- Dockerfile.a1111 || true
