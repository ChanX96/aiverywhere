#!/bin/sh
# Resolve the default and project-specific workflow module directories.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
skill_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

project=${PWD}
home=${AIVERYWHERE_HOME:-}
while [ $# -gt 0 ]; do
  case $1 in
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
key=$(project_key "$instance" "$project")
printf 'instance=%s\n' "$instance"
printf 'project=%s\n' "$project"
printf 'project_key=%s\n' "$key"
overrides=$instance/overrides/$key/workflow
printf 'default=%s\n' "$skill_dir/references/workflow"
printf 'overrides=%s\n' "$overrides"
if [ -f "$overrides/finish.md" ]; then
  printf 'warning=finish override is ignored; finish is fixed\n'
fi
