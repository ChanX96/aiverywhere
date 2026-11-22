#!/bin/sh
# Read one memory-v1 record by ID; only the bound project instance is accessible.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

ident=${1:-}
project=${PWD}
home=${AIVERYWHERE_HOME:-}
shift || true
while [ $# -gt 0 ]; do
  case $1 in
    --project) project=${2:?missing project}; shift 2 ;;
    --home) home=${2:?missing home}; shift 2 ;;
    *) fail "unknown argument: $1" 2 ;;
  esac
done
[ -n "$ident" ] || fail "usage: read-memory.sh <id> [--project DIR] [--home DIR]" 2
valid_id "$ident" || fail "id must be 32 lowercase hex characters" 2
if [ -n "$home" ]; then AIVERYWHERE_HOME=$home; export AIVERYWHERE_HOME; fi
resolved=$(resolve_instance "$project")
project=${resolved%%|*}
instance=${resolved#*|}
[ -f "$instance/instance.json" ] || fail "instance is not initialized: $instance" 4
has_jq || fail "jq is required for read-memory.sh" 3
key=$(project_key "$instance" "$project")
file=$(memory_dir "$instance" "$key")/$ident.json
[ -f "$file" ] || fail "memory not found" 4
jq . "$file"
