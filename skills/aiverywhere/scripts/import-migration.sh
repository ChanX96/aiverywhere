#!/bin/sh
# Import an AIVERYWHERE migration package without Python.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$script_dir/common.sh"

package=''
project=${PWD}
home=${AIVERYWHERE_HOME:-}
while [ $# -gt 0 ]; do
  case $1 in
    --package) package=${2:?missing package}; shift 2 ;;
    --project) project=${2:?missing project}; shift 2 ;;
    --home) home=${2:?missing home}; shift 2 ;;
    *) fail "unknown argument: $1" 2 ;;
  esac
done
[ -n "$package" ] || fail "usage: import-migration.sh --package FILE [--project DIR] [--home DIR]" 2
[ -f "$package" ] || fail "package not found: $package" 4
if [ -n "$home" ]; then AIVERYWHERE_HOME=$home; export AIVERYWHERE_HOME; fi
resolved=$(resolve_instance "$project")
project=${resolved%%|*}
instance=${resolved#*|}
[ -f "$instance/instance.json" ] || fail "instance is not initialized: $instance" 4
has_jq || fail "迁移导入需要 jq 做清单和记忆校验" 3
key=$(project_key "$instance" "$project")
temporary=$(mktemp -d "${TMPDIR:-/tmp}/aiverywhere-import.XXXXXX") || fail "cannot create temporary directory"
cleanup() { rm -rf "$temporary"; }
trap cleanup EXIT HUP INT TERM

tar -tzf "$package" > "$temporary.list" || fail "迁移包不是有效 tar.gz" 2
tar -tvzf "$package" > "$temporary.types" || fail "迁移包不是有效 tar.gz" 2
while IFS= read -r line; do
  case $line in
    -*) ;;
    *) fail "迁移包只允许普通文件" 2 ;;
  esac
done < "$temporary.types"
while IFS= read -r name; do
  case $name in
    '') continue ;;
    /*|../*|*/../*|*/..) fail "迁移包包含越界路径" 2 ;;
  esac
done < "$temporary.list"
tar -xzf "$package" -C "$temporary" || fail "迁移包解压失败" 2
manifest=$temporary/manifest.json
[ -f "$manifest" ] || fail "迁移包缺少 manifest.json" 2
[ "$(jq -er '.format' "$manifest")" = "aiverywhere-migration/1" ] || fail "不支持的迁移格式" 2
[ "$(jq -er '.skill_contract' "$manifest")" = "1" ] || fail "迁移包 skill 契约版本不兼容" 2

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 -r "$1" | awk '{print $1}'
  else fail "需要 sha256sum、shasum 或 openssl 校验迁移包" 3; fi
}

jq -r '.files[] | [.path,.size,.sha256] | @tsv' "$manifest" > "$temporary.files"
while IFS="$(printf '\t')" read -r relative size digest; do
  case $relative in ''|/*|../*|*/../*|*/..) fail "迁移清单路径越界" 2 ;; esac
  file=$temporary/$relative
  [ -f "$file" ] || fail "迁移清单文件缺失：$relative" 2
  actual_size=$(wc -c < "$file" | tr -d ' ')
  [ "$actual_size" = "$size" ] || fail "迁移文件大小不匹配：$relative" 2
  actual_digest=$(sha256_file "$file")
  [ "$actual_digest" = "$digest" ] || fail "迁移文件校验失败：$relative" 2
done < "$temporary.files"
jq -r '.files[].path' "$manifest" > "$temporary.paths"
# Every archive member except the manifest must be declared, and vice versa.
while IFS= read -r name; do
  [ "$name" = "manifest.json" ] && continue
  grep -Fqx -- "$name" "$temporary.paths" || fail "迁移包包含未声明文件：$name" 2
done < "$temporary.list"

directory=$(memory_dir "$instance" "$key")
mkdir -p "$directory"
memory_imported=0
memory_skipped=0
memory_conflicts=0
workflow_imported=0
skill_imported=0
while IFS= read -r relative; do
  [ -n "$relative" ] || continue
  file=$temporary/$relative
  case $relative in
    memory/*.json)
      sh "$script_dir/validate-memory.sh" < "$file" >/dev/null || fail "迁移记忆格式无效：$relative" 2
      target=$directory/$(basename "$relative")
      if [ -f "$target" ]; then
        if cmp -s "$file" "$target"; then memory_skipped=$((memory_skipped + 1))
        else memory_conflicts=$((memory_conflicts + 1)); fi
      else
        cp "$file" "$target"; chmod 600 "$target"; memory_imported=$((memory_imported + 1))
      fi
      ;;
    workflow/*.md)
      target_dir=$instance/overrides/$key/workflow
      mkdir -p "$target_dir"; target=$target_dir/$(basename "$relative")
      if [ -f "$target" ]; then
        cmp -s "$file" "$target" || memory_conflicts=$((memory_conflicts + 1))
      else
        cp "$file" "$target"; chmod 600 "$target"; workflow_imported=$((workflow_imported + 1))
      fi
      ;;
    skill/*)
      relative_skill=${relative#skill/}
      [ "$relative_skill" = "references/workflow/finish.md" ] && continue
      target=$instance/skills/aiverywhere/$relative_skill
      if [ -f "$target" ]; then
        cmp -s "$file" "$target" || memory_conflicts=$((memory_conflicts + 1))
      else
        mkdir -p "$(dirname "$target")"
        cp "$file" "$target"
        case $relative_skill in scripts/*) chmod 755 "$target" ;; *) chmod 644 "$target" ;; esac
        skill_imported=$((skill_imported + 1))
      fi
      ;;
    *) fail "迁移包含未知分区：$relative" 2 ;;
  esac
done < "$temporary.paths"

printf 'import-ok memory=%s memory_skipped=%s conflicts=%s workflow=%s skill=%s\n' \
  "$memory_imported" "$memory_skipped" "$memory_conflicts" "$workflow_imported" "$skill_imported"
