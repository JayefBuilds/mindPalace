#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEST_DIR="${1:-$HOME/agentforge-backups/$TIMESTAMP/mindPalace}"

mkdir -p "$DEST_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[mindpalace-backup] docker is required"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[mindpalace-backup] docker compose is required"
  exit 1
fi

mapfile -t VOLUMES < <(cd "$PROJECT_DIR" && docker compose config --volumes)

if [[ "${#VOLUMES[@]}" -eq 0 ]]; then
  echo "[mindpalace-backup] no compose volumes found"
  exit 1
fi

for volume in "${VOLUMES[@]}"; do
  archive="$DEST_DIR/${volume}.tar.gz"
  echo "[mindpalace-backup] backing up $volume -> $archive"
  docker run --rm \
    -v "${volume}:/volume:ro" \
    -v "${DEST_DIR}:/backup" \
    alpine:3.20 \
    sh -lc "cd /volume && tar -czf \"/backup/${volume}.tar.gz\" ."
done

echo "[mindpalace-backup] wrote ${#VOLUMES[@]} volume archive(s) to $DEST_DIR"
