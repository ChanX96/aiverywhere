#!/bin/sh
# Shell-only acceptance for the project-local memory bundle.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
scripts=$root/skills/aiverywhere/scripts
temporary=$(mktemp -d "${TMPDIR:-/tmp}/aiverywhere-shell.XXXXXX")
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
project=$temporary/project
mkdir -p "$project"

init=$(sh "$scripts/init-instance.sh" "$project")
printf '%s\n' "$init" | jq -e '.status == "ok"' >/dev/null

valid="$temporary/valid.json"
printf '%s\n' '{"schema_version":1,"id":"0123456789abcdef0123456789abcdef","revision":1,"kind":"fact","title":"单位","text":"用万元。","source":"task-a","updated":"2026-11-22T10:00:00Z"}' > "$valid"
sh "$scripts/validate-memory.sh" < "$valid" | jq -e '.status == "valid"' >/dev/null
printf '%s\n' '{"schema_version":1,"id":"bad","revision":1,"kind":"fact","title":"x","text":"x","source":"s","updated":"2026-11-22T10:00:00Z"}' > "$temporary/invalid.json"
if sh "$scripts/validate-memory.sh" < "$temporary/invalid.json" >/dev/null 2>&1; then
  echo 'invalid record unexpectedly passed' >&2
  exit 1
fi
cat "$valid" "$valid" > "$temporary/multiple.json"
if sh "$scripts/validate-memory.sh" < "$temporary/multiple.json" >/dev/null 2>&1; then
  echo 'multiple records unexpectedly passed' >&2
  exit 1
fi
set +e
PATH=/nonexistent /bin/sh "$scripts/validate-memory.sh" < "$valid" > "$temporary/no-jq.json" 2>/dev/null
code=$?
set -e
[ "$code" -eq 3 ]
jq -e '.status == "unavailable"' "$temporary/no-jq.json" >/dev/null

export AIVERYWHERE_HOME="$project/.aiverywhere"
created=$(sh "$scripts/write-memory.sh" --project "$project" --kind fact --title '月报金额单位' \
  --text '本项目月报金额统一使用万元。' --source task-shell)
id=$(printf '%s\n' "$created" | jq -er .id)
sh "$scripts/list-memory.sh" --project "$project" --kind fact --query 月报 | jq -e --arg id "$id" 'length == 1 and .[0].id == $id' >/dev/null
sh "$scripts/read-memory.sh" "$id" --project "$project" | jq -e '.revision == 1 and (.text | contains("万元"))' >/dev/null
sh "$scripts/write-memory.sh" --project "$project" --id "$id" --revision 1 --kind fact --title '月报金额单位' \
  --text '本项目月报金额统一使用万元，保留两位小数。' --source task-shell-2 >/dev/null
if sh "$scripts/write-memory.sh" --project "$project" --id "$id" --revision 1 --kind fact --title '月报金额单位' \
  --text stale --source task-shell-3 >/dev/null 2>&1; then
  echo 'stale revision unexpectedly passed' >&2
  exit 1
fi
printf '%s\n' 'shell memory: PASS'
