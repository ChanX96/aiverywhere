#!/bin/sh
# Create or update one memory-v1 record without Python.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

kind=''
title=''
text=''
source=''
ident=''
revision=''
shared=false
project=${PWD}
home=${AIVERYWHERE_HOME:-}
while [ $# -gt 0 ]; do
  case $1 in
    --kind) kind=${2:?missing kind}; shift 2 ;;
    --title) title=${2:?missing title}; shift 2 ;;
    --text) text=${2:?missing text}; shift 2 ;;
    --source) source=${2:?missing source}; shift 2 ;;
    --id) ident=${2:?missing id}; shift 2 ;;
    --revision) revision=${2:?missing revision}; shift 2 ;;
    --shared) shared=true; shift ;;
    --project) project=${2:?missing project}; shift 2 ;;
    --home) home=${2:?missing home}; shift 2 ;;
    *) fail "unknown argument: $1" 2 ;;
  esac
done
if [ -n "$home" ]; then AIVERYWHERE_HOME=$home; export AIVERYWHERE_HOME; fi
resolved=$(resolve_instance "$project")
project=${resolved%%|*}
instance=${resolved#*|}
[ -f "$instance/instance.json" ] || fail "instance is not initialized: $instance" 4
has_jq || fail "jq is required for write-memory.sh" 3
key=$(project_key "$instance" "$project")
directory=$(memory_dir "$instance" "$key")
if [ ! -d "$directory" ]; then
    mkdir -p "$directory" || fail "无法创建记忆目录；请检查实例目录权限" 3
    chmod 700 "$instance/data" "$instance/data/memory" "$directory" ||
        fail "无法设置记忆目录权限" 3
fi

if [ -n "$ident" ] && ! valid_id "$ident"; then
  fail "id must be 32 lowercase hex characters" 2
fi
if [ -n "$revision" ] && [ -z "$ident" ]; then
  fail "--revision requires --id" 2
fi
if [ -z "$source" ]; then
  source="host-$(date -u +%Y%m%d%H%M%S)-$$"
fi
if [ -z "$ident" ]; then
  if command -v uuidgen >/dev/null 2>&1; then
    ident=$(uuidgen | tr -d '-' | tr 'A-F' 'a-f')
  elif command -v openssl >/dev/null 2>&1; then
    ident=$(openssl rand -hex 16)
  else
    fail "cannot generate a stable id (need uuidgen or openssl)" 3
  fi
fi
valid_id "$ident" || fail "generated id is invalid" 5

lock="$directory/.lock"
if ! mkdir "$lock" 2>/dev/null; then
    if [ -e "$lock" ]; then
        fail "memory is locked; retry later" 6
    fi
    fail "memory directory is not writable (permission or read-only)" 3
fi
cleanup() { rmdir "$lock" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM

record="$directory/$ident.json"
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
temporary="$directory/.$ident.$$.tmp"
if [ -f "$record" ]; then
  [ -n "$revision" ] || fail "updating an existing memory requires --revision" 7
  current=$(jq -er '.revision' "$record" 2>/dev/null) || fail "cannot read existing memory" 7
  [ "$current" = "$revision" ] || fail "revision conflict: current is $current" 7
  jq -n --argjson schema 1 --arg id "$ident" --argjson revision "$((current + 1))" \
    --arg kind "$kind" --arg title "$title" --arg text "$text" --arg source "$source" \
    --arg updated "$timestamp" --argjson shared "$shared" \
    '{schema_version:$schema,id:$id,revision:$revision,kind:$kind,title:$title,text:$text,source:$source,updated:$updated,shared:$shared}' > "$temporary"
else
  [ -z "$revision" ] || fail "creating a memory must not pass --revision" 7
  jq -n --argjson schema 1 --arg id "$ident" --argjson revision 1 \
    --arg kind "$kind" --arg title "$title" --arg text "$text" --arg source "$source" \
    --arg updated "$timestamp" --argjson shared "$shared" \
    '{schema_version:$schema,id:$id,revision:$revision,kind:$kind,title:$title,text:$text,source:$source,updated:$updated,shared:$shared}' > "$temporary"
fi
chmod 600 "$temporary"
if ! sh "$script_dir/validate-memory.sh" < "$temporary" >/dev/null; then
  rm -f "$temporary"
  fail "memory record failed schema validation" 2
fi
if [ -f "$record" ]; then
  mv "$temporary" "$record"
else
  ln "$temporary" "$record" || { rm -f "$temporary"; fail "record already exists" 8; }
  rm -f "$temporary"
fi
chmod 600 "$record"
jq -c '{status:"ok",id:.id,revision:.revision,kind:.kind,title:.title,updated:.updated}' "$record"
