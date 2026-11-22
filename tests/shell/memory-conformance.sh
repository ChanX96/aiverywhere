#!/bin/sh
# Run the shared memory-v1 vectors against the Shell validator.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
validator=$root/skills/aiverywhere/scripts/validate-memory.sh
vectors=$root/tests/fixtures/memory-v1-vectors.json
command -v jq >/dev/null 2>&1 || {
  printf '%s\n' '{"status":"unavailable","error":"jq is required for conformance"}'
  exit 3
}
temporary=$(mktemp "${TMPDIR:-/tmp}/aiverywhere-vectors.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
failed=0
count=$(jq '.cases | length' "$vectors")
i=0
while [ "$i" -lt "$count" ]; do
  expected=$(jq -r --argjson i "$i" '.cases[$i].valid | tostring' "$vectors")
  jq -c --argjson i "$i" '.cases[$i].record' "$vectors" > "$temporary"
  if sh "$validator" < "$temporary" >/dev/null 2>&1; then actual=true; else actual=false; fi
  if [ "$actual" != "$expected" ]; then
    printf 'memory vector failed: %s (expected %s, got %s)\n' \
      "$(jq -r --argjson i "$i" '.cases[$i].name' "$vectors")" "$expected" "$actual" >&2
    failed=1
  fi
  i=$((i + 1))
done
[ "$failed" -eq 0 ]
printf '%s\n' 'memory conformance: PASS'
