#!/bin/sh
# Create a project-local .aiverywhere instance and the standard skill link.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
skill_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd -P)
project=${1:-$PWD}
link=yes
shift || true
while [ $# -gt 0 ]; do
  case $1 in
    --project) project=${2:?missing project}; shift 2 ;;
    --no-link) link=no; shift ;;
    *) printf '%s\n' '{"status":"error","error":"unknown argument"}'; exit 2 ;;
  esac
done
project=$(CDPATH='' cd -- "$project" && pwd -P) || {
  printf '%s\n' '{"status":"error","error":"project directory is not accessible"}'
  exit 2
}
home=${AIVERYWHERE_HOME:-$project/.aiverywhere}
case $home in
  /*) ;;
  *) home=$project/$home ;;
esac
if [ -f "$home/instance.json" ]; then
  existing=$(cd -- "$home" && pwd -P)
  if [ "$existing" != "$home" ]; then
    home=$existing
  fi
fi
command -v jq >/dev/null 2>&1 || {
  printf '%s\n' '{"status":"error","error":"jq is required for init-instance.sh"}'
  exit 3
}
mkdir -p "$home/data/memory/default" "$home/data/logs/default" "$home/data/artifacts" "$home/work"
chmod 700 "$home" "$home/data" "$home/data/memory" "$home/data/memory/default" \
  "$home/data/logs" "$home/data/logs/default" "$home/data/artifacts" "$home/work"
if [ ! -f "$home/instance.json" ]; then
  temporary=$home/.instance.json.$$
  jq -n --arg project "$project" --arg home "$home" \
    '{schema_version:1, project_key:"default", project_root:$project, instance_root:$home}' \
    > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$home/instance.json"
else
  chmod 600 "$home/instance.json"
fi
if [ "$link" = yes ]; then
  mkdir -p "$project/.agents/skills"
  skill_link=$project/.agents/skills/aiverywhere
  if [ -L "$skill_link" ]; then
    target=$(CDPATH='' cd -- "$skill_link" 2>/dev/null && pwd -P || true)
    if [ "$target" != "$skill_dir" ]; then
      old_file=$(CDPATH='' cd -- "$(dirname -- "$skill_link")" && pwd -P)/$(basename -- "$(readlink "$skill_link")")
      if [ "$(basename -- "$old_file")" = "SKILL.md" ] && [ "$(basename -- "$(dirname -- "$old_file")")" = "data" ]; then
        rm -f "$skill_link"
        ln -s "$skill_dir" "$skill_link"
      else
        printf '%s\n' '{"status":"error","error":"existing skill link points elsewhere"}'
        exit 4
      fi
    fi
  elif [ -d "$skill_link" ]; then
    entries=$(find "$skill_link" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')
    if [ "$entries" = "1" ] && [ -L "$skill_link/SKILL.md" ]; then
      rm -rf "$skill_link"
      ln -s "$skill_dir" "$skill_link"
    else
      printf '%s\n' '{"status":"error","error":"existing skill directory is not a legacy SKILL.md link"}'
      exit 4
    fi
  elif [ -e "$skill_link" ]; then
    printf '%s\n' '{"status":"error","error":"existing skill path is not a symlink"}'
    exit 4
  else
    ln -s "$skill_dir" "$skill_link"
  fi
fi
jq -n --arg home "$home" --arg project "$project" --arg skill "$skill_dir" \
  '{status:"ok", home:$home, project:$project, skill:$skill,
    memory:($home + "/data/memory/default")}'
