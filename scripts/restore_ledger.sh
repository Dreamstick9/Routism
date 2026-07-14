#!/usr/bin/env bash
# Restore the Routism billing ledger from a timestamped backup.
# Usage: scripts/restore_ledger.sh <backup_path>
# Env:   ROUTISM_LEDGER_PATH — destination ledger path (default: data/billing.db)
#        FORCE=1             — required confirmation to overwrite existing ledger
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER="${ROUTISM_LEDGER_PATH:-$ROOT/data/billing.db}"

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "Usage: $0 <backup_path>" >&2
  echo "  Set FORCE=1 to overwrite an existing ledger at ROUTISM_LEDGER_PATH." >&2
  exit 1
fi

BACKUP="$1"

if [[ ! -f "$BACKUP" ]]; then
  echo "ERROR: backup not found: $BACKUP" >&2
  exit 1
fi

BSIZE="$(wc -c <"$BACKUP" | tr -d ' ')"
if [[ -z "$BSIZE" || "$BSIZE" -le 0 ]]; then
  echo "ERROR: backup is empty: $BACKUP" >&2
  exit 1
fi

if [[ -e "$LEDGER" && "${FORCE:-}" != "1" ]]; then
  echo "ERROR: ledger already exists at: $LEDGER" >&2
  echo "Refusing to overwrite without FORCE=1." >&2
  exit 1
fi

mkdir -p "$(dirname "$LEDGER")"

# Safety: write to temp then move into place
TMP="${LEDGER}.restore.$$"
if ! cp -p "$BACKUP" "$TMP" 2>/dev/null; then
  cp "$BACKUP" "$TMP"
fi

# If overwriting, keep a pre-restore snapshot next to the ledger
if [[ -f "$LEDGER" ]]; then
  PRE="${LEDGER}.pre_restore_$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$LEDGER" "$PRE" 2>/dev/null || cp "$LEDGER" "$PRE"
  echo "Saved pre-restore copy: $PRE"
fi

mv -f "$TMP" "$LEDGER"

RSIZE="$(wc -c <"$LEDGER" | tr -d ' ')"
if [[ -z "$RSIZE" || "$RSIZE" -le 0 ]]; then
  echo "ERROR: restored ledger is empty: $LEDGER" >&2
  exit 1
fi

echo "OK restored size=${RSIZE} bytes from $BACKUP"
echo "$LEDGER"
exit 0
