#!/usr/bin/env bash
#
# Online backup of the SQLite database.
#
# Safe to run while the API and the collection worker are writing: it uses
# SQLite's online backup API (".backup"), which takes a consistent snapshot even
# under a concurrent writer and WAL mode. The copy is integrity-checked, gzipped,
# and old archives are pruned.
#
# Usage:
#   scripts/backup_db.sh [DB_PATH] [BACKUP_DIR] [KEEP]
#
# Defaults (overridable via args or env):
#   DB_PATH     $KOSPI_DB_PATH     or <repo>/data/kospi.db
#   BACKUP_DIR  $KOSPI_BACKUP_DIR  or <repo>/data/backups
#   KEEP        $KOSPI_BACKUP_KEEP or 14   (newest archives to retain)
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${1:-${KOSPI_DB_PATH:-$ROOT_DIR/data/kospi.db}}"
BACKUP_DIR="${2:-${KOSPI_BACKUP_DIR:-$ROOT_DIR/data/backups}}"
KEEP="${3:-${KOSPI_BACKUP_KEEP:-14}}"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "backup_db: sqlite3 not found on PATH" >&2
  exit 1
fi
if [ ! -f "$DB_PATH" ]; then
  echo "backup_db: database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/kospi-$stamp.db"

# Consistent snapshot via the online backup API (not a raw file copy).
sqlite3 "$DB_PATH" ".backup '$dest'"

# Refuse to keep a corrupt backup.
check="$(sqlite3 "$dest" 'PRAGMA integrity_check;')"
if [ "$check" != "ok" ]; then
  echo "backup_db: integrity check FAILED for $dest: $check" >&2
  rm -f "$dest"
  exit 1
fi

gzip -f "$dest"
echo "backup_db: wrote ${dest}.gz"

# Retention: keep the newest $KEEP archives, prune the rest.
ls -1t "$BACKUP_DIR"/kospi-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
  echo "backup_db: pruned $old"
done
