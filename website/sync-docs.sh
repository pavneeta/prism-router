#!/usr/bin/env bash
# Copy curated user/operator markdown from repo docs/ into website/docs-content/.
# Does not sync docs/internal/ (GitHub-only eng docs).
# Run from repo root or website/. Vercel buildCommand runs this before publish.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(basename "$(pwd)")" == "website" ]]; then
  ROOT="$(cd .. && pwd)"
fi
SRC="$ROOT/docs"
DEST="$ROOT/website/docs-content"

mkdir -p "$DEST"
FILES=(
  README.md
  USAGE.md
  BENCHMARKS.md
  OPENCODE.md
  CURSOR.md
  HERMES.md
  HOLMESGPT.md
  TROUBLESHOOTING.md
  SECURITY.md
  TOGETHER.md
  RAILWAY.md
)

# Remove stale synced copies (e.g. former eng docs no longer in the catalog).
shopt -s nullglob
for existing in "$DEST"/*.md; do
  base="$(basename "$existing")"
  keep=0
  for f in "${FILES[@]}"; do
    if [[ "$base" == "$f" ]]; then
      keep=1
      break
    fi
  done
  if [[ "$keep" -eq 0 ]]; then
    rm -f "$existing"
    echo "removed stale $base"
  fi
done
shopt -u nullglob

for f in "${FILES[@]}"; do
  if [[ -f "$SRC/$f" ]]; then
    cp "$SRC/$f" "$DEST/$f"
    echo "synced $f"
  else
    echo "missing $SRC/$f" >&2
  fi
done

echo "docs-content ready → $DEST"
