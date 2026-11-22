#!/bin/sh
# Create a project-local .aiverywhere instance and the standard skill link.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
skill_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

json_path() {
  case $1 in
    *[[:cntrl:]]*) fail "路径包含控制字符，无法写入 instance.json" 2 ;;
  esac
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}
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
mkdir -p "$home" || fail "无法创建实例目录：$home" 2
home=$(canonical_dir "$home") || fail "实例目录不可访问：$home" 2
key=$(project_key "$home" "$project")
mkdir -p "$home/data/memory/$key" "$home/data/logs/default" "$home/data/artifacts" "$home/work"
chmod 700 "$home" "$home/data" "$home/data/memory" "$home/data/memory/$key" \
  "$home/data/logs" "$home/data/logs/default" "$home/data/artifacts" "$home/work"
if [ ! -f "$home/instance.json" ]; then
  temporary=$home/.instance.json.$$
  if has_jq; then
    jq -n --arg project "$project" --arg home "$home" --arg key "$key" \
      '{schema_version:1, project_key:$key, project_root:$project, instance_root:$home}' \
      > "$temporary"
  else
    printf '{"schema_version":1,"project_key":"%s","project_root":"%s","instance_root":"%s"}\n' \
      "$(json_path "$key")" "$(json_path "$project")" "$(json_path "$home")" > "$temporary"
  fi
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
if has_jq; then
  jq -n --arg home "$home" --arg project "$project" --arg skill "$skill_dir" --arg key "$key" \
    '{status:"ok", home:$home, project:$project, skill:$skill,
      project_key:$key, memory:($home + "/data/memory/" + $key)}'
else
  printf '{"status":"ok","home":"%s","project":"%s","skill":"%s","project_key":"%s","memory":"%s"}\n' \
    "$(json_path "$home")" "$(json_path "$project")" "$(json_path "$skill_dir")" \
    "$(json_path "$key")" "$(json_path "$home/data/memory/$key")"
fi
