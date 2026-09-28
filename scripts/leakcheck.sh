#!/usr/bin/env bash
# Fails if any tracked or staged file matches a private denylist of names, keys and hosts.
# The denylist lives OUTSIDE the repo (default ~/.config/huntline/denylist.txt),
# one extended regex per line, so the list of things to hide is never published itself.
set -euo pipefail
LIST="${LEAKCHECK_LIST:-$HOME/.config/huntline/denylist.txt}"
cd "$(git rev-parse --show-toplevel)"
[ -f "$LIST" ] || { echo "leakcheck: no denylist at $LIST (skipping)"; exit 0; }

files=$(git ls-files -co --exclude-standard)
hits=$(echo "$files" | xargs -r grep -nIiE -f "$LIST" -- 2>/dev/null || true)
# Also check commit identities, which leak just as easily as file contents.
ids=$(git log --all --format='%an %ae %cn %ce' 2>/dev/null | grep -iE -f "$LIST" || true)

if [ -n "$hits$ids" ]; then
  echo "leakcheck: FAILED"
  [ -n "$hits" ] && echo "$hits" | cut -c1-160
  [ -n "$ids" ] && echo "commit identity: $ids"
  exit 1
fi
echo "leakcheck: clean ($(echo "$files" | wc -l) files)"
