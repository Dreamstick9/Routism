#!/usr/bin/env bash
# Backup Routism SQLite credit ledger (Model B).
# Usage:
#   ./scripts/backup_ledger.sh
#   ROUTISM_LEDGER_PATH=/path/to/billing.db ./scripts/backup_ledger.sh
#   ./scripts/backup_ledger.sh /custom/backup/dir
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER="${ROUTISM_LEDGER_PATH:-$ROOT/data/billing.db}"
DEST_DIR="${1:-$ROOT/data/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST_DIR"

if [[ ! -f "$LEDGER" ]]; then
  echo "error: ledger not found: $LEDGER" >&2
  exit 1
fi

BASE="$(basename "$LEDGER")"
OUT="$DEST_DIR/${BASE%.db}.$STAMP.db"

# Prefer SQLite online backup API when sqlite3 is available (safer under readers).
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$LEDGER" ".backup '$OUT'"
else
  cp -p "$LEDGER" "$OUT"
  # Copy WAL/SHM if present (best-effort when not using .backup)
  [[ -f "${LEDGER}-wal" ]] && cp -p "${LEDGER}-wal" "${OUT}-wal" || true
  [[ -f "${LEDGER}-shm" ]] && cp -p "${LEDGER}-shm" "${OUT}-shm" || true
fi

echo "backed up: $LEDGER -> $OUT"
ls -la "$OUT"
