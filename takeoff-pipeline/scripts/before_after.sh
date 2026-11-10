#!/usr/bin/env bash
# Run the current test suite and the evidence script against the code as
# received (git tag `original`) and against this working tree.
#
#   scripts/before_after.sh                 # tests + evidence, both trees
#   scripts/before_after.sh -k d1           # extra args go to pytest
#
# Needs git and pytest. Set PYTHON to choose the interpreter.
set -uo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
py="${PYTHON:-python3}"
orig="$(mktemp -d)"
trap 'rm -rf "$orig"' EXIT

# The untouched pipeline, with this tree's tests and evidence script on top.
top="$(git -C "$here" rev-parse --show-toplevel)"
git -C "$top" archive original takeoff-pipeline | tar -x -C "$orig" --strip-components=1
cp -R "$here/tests/." "$orig/tests/"
cp "$here/scripts/evidence.py" "$orig/scripts/evidence.py"

for side in ORIGINAL FIXED; do
  dir="$orig"; [ "$side" = FIXED ] && dir="$here"
  echo
  echo "==================== $side ($dir)"
  (cd "$dir" && "$py" -m pytest -q -p no:cacheprovider "$@" | tail -n 25)
  (cd "$dir" && "$py" -m scripts.evidence)
done
