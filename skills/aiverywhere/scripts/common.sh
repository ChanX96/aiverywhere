# shellcheck shell=sh
# POSIX helpers shared by the memory scripts. Source this file; do not execute it.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
}

has_jq() {
  command -v jq >/dev/null 2>&1
}

canonical_dir() {
  (CDPATH='' cd -- "$1" 2>/dev/null && pwd -P)
}

find_project_root() {
  directory=$(canonical_dir "${1:-$PWD}") || fail "项目目录不可访问" 2
  current=$directory
  while :; do
    if [ -f "$current/.aiverywhere/instance.json" ]; then
      printf '%s\n' "$current"
      return 0
    fi
    [ "$current" = "/" ] && break
    parent=$(dirname -- "$current")
    [ "$parent" = "$current" ] && break
    current=$parent
  done
  printf '%s\n' "$directory"
}

resolve_instance() {
  project=$(find_project_root "${1:-$PWD}")
  if [ -n "${AIVERYWHERE_HOME:-}" ]; then
    home=$AIVERYWHERE_HOME
  elif [ -f "$project/.aiverywhere/instance.json" ]; then
    home=$project/.aiverywhere
  elif [ -f "${HOME:-/nonexistent}/.aiverywhere/instance.json" ]; then
    home=${HOME}/.aiverywhere
  else
    home=$project/.aiverywhere
  fi
  home=$(canonical_dir "$home" 2>/dev/null || printf '%s' "$home")
  printf '%s\n' "$project|$home"
}

project_key() {
  instance=$1
  if has_jq && [ -f "$instance/instance.json" ]; then
    jq -er '.project_key // "default"' "$instance/instance.json"
  else
    printf 'default\n'
  fi
}

memory_dir() {
  printf '%s\n' "$1/data/memory/$2"
}

valid_id() {
  case $1 in
    *[!0-9a-f]*|'') return 1 ;;
  esac
  [ "${#1}" -eq 32 ]
}
