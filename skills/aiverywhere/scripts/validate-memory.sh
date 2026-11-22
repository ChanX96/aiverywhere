#!/bin/sh
# Validate exactly one memory-v1 record from standard input.
set -eu

if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' '{"status":"unavailable","error":"jq is not installed"}'
  exit 3
fi

rules='
  length == 1 and
  (.[0] | type == "object") and
  (.[0] | keys_unsorted - ["schema_version","id","revision","kind","title","text","source","updated","shared"] | length == 0) and
  (.[0].schema_version == 1) and
  (.[0].id | type == "string" and test("^[0-9a-f]{32}$")) and
  (.[0].revision | type == "number" and . == floor and . >= 1) and
  (.[0].kind | type == "string" and (. == "fact" or . == "skill" or . == "clue")) and
  (.[0].title | type == "string" and length >= 1 and length <= 160 and test("\\S")) and
  (.[0].text | type == "string" and length >= 1 and length <= 8000 and test("\\S")) and
  (.[0].source | type == "string" and length >= 1 and length <= 200) and
  (.[0].updated | type == "string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
  (.[0].shared == null or (.[0].shared | type == "boolean"))
'
if jq -e -s "$rules" >/dev/null 2>&1; then
  printf '%s\n' '{"status":"valid"}'
  exit 0
fi
printf '%s\n' '{"status":"invalid","error":"memory-v1 validation failed"}'
exit 2
