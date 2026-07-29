#!/usr/bin/env bash
# Copy curated markdown from repo docs/ into website/docs-content/ for the docs UI.
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
  ARCHITECTURE.md
  BENCHMARKS.md
  OPENCODE.md
  HERMES.md
  HOLMESGPT.md
  HARNESS_BENCH.md
  STRESS_BENCH.md
  TROUBLESHOOTING.md
  SECURITY.md
  CI.md
  AB_ANTHROPIC_VS_FIREWORKS.md
)

for f in "${FILES[@]}"; do
  if [[ -f "$SRC/$f" ]]; then
    cp "$SRC/$f" "$DEST/$f"
    echo "synced $f"
  else
    echo "missing $SRC/$f" >&2
  fi
done

# Strip absolute marketing self-links noise is fine; keep files as-is.
echo "docs-content ready → $DEST"
