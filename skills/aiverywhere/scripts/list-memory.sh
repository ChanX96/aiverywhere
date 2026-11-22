#!/bin/sh
# List memory-v1 records for the current project. No semantic index; the model chooses.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

kind=''
query=''
limit=50
project=${PWD}
home=${AIVERYWHERE_HOME:-}
while [ $# -gt 0 ]; do
  case $1 in
    --kind) kind=${2:?missing kind}; shift 2 ;;
    --query) query=${2:?missing query}; shift 2 ;;
    --limit) limit=${2:?missing limit}; shift 2 ;;
    --project) project=${2:?missing project}; shift 2 ;;
    --home) home=${2:?missing home}; shift 2 ;;
    *) fail "unknown argument: $1" 2 ;;
  esac
done
case $kind in ''|fact|skill|clue) ;; *) fail "kind must be fact, skill or clue" 2 ;; esac
case $limit in ''|*[!0-9]*) fail "limit must be a positive integer" 2 ;; esac
[ "$limit" -ge 1 ] || fail "limit must be a positive integer" 2
if [ -n "$home" ]; then AIVERYWHERE_HOME=$home; export AIVERYWHERE_HOME; fi
resolved=$(resolve_instance "$project")
instance=${resolved#*|}
[ -f "$instance/instance.json" ] || fail "instance is not initialized: $instance" 4
has_jq || fail "jq is required for list-memory.sh" 3
key=$(project_key "$instance")
directory=$(memory_dir "$instance" "$key")
[ -d "$directory" ] || { printf '[]\n'; exit 0; }
lower=$(printf '%s' "$query" | tr '[:upper:]' '[:lower:]')
temporary=$(mktemp "${TMPDIR:-/tmp}/aiverywhere-list.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
for file in "$directory"/*.json; do
  [ -f "$file" ] || continue
  jq -c --arg kind "$kind" --arg query "$lower" \
    'select((.kind == $kind or $kind == "") and
            ($query == "" or ((.title|ascii_downcase|contains($query)) or (.text|ascii_downcase|contains($query)))))
     | {id,title,kind,revision,updated,shared}' "$file" 2>/dev/null >> "$temporary" || true
done
jq -s --argjson limit "$limit" 'sort_by(.updated, .revision) | reverse | .[:$limit]' "$temporary"
