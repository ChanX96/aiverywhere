#!/bin/sh
# Install aiverywhere for any host agent, with an optional command-line install.
set -eu

: "${HOME:?HOME 未设置}"
REPO="${AIVERYWHERE_REPO:-https://github.com/ChanX96/aiverywhere}"
REPO="${REPO%/}"
REF="${AIVERYWHERE_REF:-main}"
HOME_DIR="${AIVERYWHERE_HOME:-$HOME/.aiverywhere}"
HOME_EXPLICIT=0
[ -n "${AIVERYWHERE_HOME:-}" ] && HOME_EXPLICIT=1
PROJECT_DIR="$PWD"
BIN_DIR="${AIVERYWHERE_BIN_DIR:-$HOME/.local/bin}"
VENV="${AIVERYWHERE_VENV:-}"
SOURCE="${AIVERYWHERE_SOURCE:-}"
WITH_CLI="ask"
LINK="ask"
ASSUME_YES=0
DRY_RUN=0
TTY_FD=""

usage() {
    cat <<'EOF'
用法：install.sh [选项]

默认把 skill bundle 安装到项目 .aiverywhere/，并把项目链接到
.agents/skills/aiverywhere。仅宿主路径不需要 Python、pip 或 venv。

选项：
  --cli              额外安装 Python CLI、命令和模型配置
  --no-cli           只安装宿主 bundle（默认交互询问）
  --yes, --no-input  不提问，使用默认值（仅宿主；--cli 时需模型环境变量）
  --home DIR         实例根（默认 <项目>/.aiverywhere）
  --project DIR      要链接技能的项目（默认当前目录）
  --bin-dir DIR      命令链接目录（默认 ~/.local/bin）
  --source TARGET    pip 安装源：本地目录、wheel 或 Python 包名
  --ref REF          从 GitHub 获取的分支或标签（默认 main）
  --no-link          不创建项目技能链接
  --dry-run          只打印将执行的命令
  -h, --help         显示本帮助

环境变量：
  AIVERYWHERE_REPO   源码仓库地址
  AIVERYWHERE_REF    分支或标签
  AIVERYWHERE_HOME   默认实例根
  AIVERYWHERE_VENV   虚拟环境目录（默认 <home>/venv）
  AIVERYWHERE_BIN_DIR 命令链接目录
  AIVERYWHERE_SOURCE 默认安装源
  AIVERYWHERE_PYTHON 指定 Python 解释器
  PIP_INDEX_URL      pip 镜像（例如清华 PyPI 镜像）

示例：
  curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
  curl -fsSL .../install.sh | sh -s -- --cli
  curl -fsSL .../install.sh | sh -s -- --yes --home "$HOME/.aiverywhere"
EOF
}

fail() {
    printf '安装失败：%s\n' "$*" >&2
    exit 1
}

note() {
    printf '%s\n' "$*"
}

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '+ %s\n' "$*"
    else
        "$@"
    fi
}

expand_path() {
    # shellcheck disable=SC2088  # case patterns match one leading literal tilde
    case "$1" in
        "~") printf '%s' "$HOME" ;;
        "~/"*) printf '%s/%s' "$HOME" "${1#\~/}" ;;
        *) printf '%s' "$1" ;;
    esac
}

absolute_path() {
    case "$1" in
        /*) printf '%s' "$1" ;;
        *) printf '%s/%s' "$PWD" "$1" ;;
    esac
}

ask() {
    ASK_QUESTION=$1
    ASK_DEFAULT=$2
    ASK_ANSWER=""
    if [ "$ASSUME_YES" -eq 0 ] && [ -n "$TTY_FD" ]; then
        printf '%s ' "$ASK_QUESTION" >&2
        if [ "$TTY_FD" = 3 ]; then
            IFS= read -r ASK_ANSWER <&3 || ASK_ANSWER=""
        else
            IFS= read -r ASK_ANSWER || ASK_ANSWER=""
        fi
    fi
    [ -n "$ASK_ANSWER" ] || ASK_ANSWER=$ASK_DEFAULT
    printf '%s' "$ASK_ANSWER"
}

confirm() {
    CONFIRM_ANSWER=$(ask "$1" "$2")
    case "$CONFIRM_ANSWER" in
        [Yy]*) return 0 ;;
        [Nn]*) return 1 ;;
        *) [ "$2" = "y" ] ;;
    esac
}

find_python() {
    for CANDIDATE in ${AIVERYWHERE_PYTHON:-} python3 python3.14 python3.13 python3.12 python3.11; do
        [ -n "$CANDIDATE" ] || continue
        command -v "$CANDIDATE" >/dev/null 2>&1 || continue
        if "$CANDIDATE" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            printf '%s' "$CANDIDATE"
            return 0
        fi
    done
    return 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --cli) WITH_CLI="yes" ;;
        --no-cli|--host-only) WITH_CLI="no" ;;
        --yes|--no-input|-y) ASSUME_YES=1 ;;
        --home)
            shift
            [ $# -gt 0 ] || fail "--home 需要目录"
            HOME_DIR=$1
            HOME_EXPLICIT=1
            ;;
        --project)
            shift
            [ $# -gt 0 ] || fail "--project 需要目录"
            PROJECT_DIR=$1
            ;;
        --bin-dir)
            shift
            [ $# -gt 0 ] || fail "--bin-dir 需要目录"
            BIN_DIR=$1
            ;;
        --source)
            shift
            [ $# -gt 0 ] || fail "--source 需要安装源"
            SOURCE=$1
            ;;
        --ref)
            shift
            [ $# -gt 0 ] || fail "--ref 需要分支或标签"
            REF=$1
            ;;
        --no-link) LINK="no" ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) fail "未知参数：$1（使用 --help 查看用法）" ;;
    esac
    shift
done

PROJECT_DIR=$(absolute_path "$(expand_path "$PROJECT_DIR")")
if [ "$HOME_EXPLICIT" -eq 0 ]; then
    HOME_DIR="$PROJECT_DIR/.aiverywhere"
fi
HOME_DIR=$(absolute_path "$(expand_path "$HOME_DIR")")
BIN_DIR=$(absolute_path "$(expand_path "$BIN_DIR")")
[ -n "$VENV" ] && VENV=$(absolute_path "$(expand_path "$VENV")")
[ -d "$PROJECT_DIR" ] || fail "项目目录不存在：$PROJECT_DIR"

if [ -t 0 ] && [ -t 1 ]; then
    TTY_FD=0
elif (exec 3</dev/tty) 2>/dev/null; then
    # Test in a subshell: dash exits the whole script on a failed exec in a
    # compound-list condition. Re-open in the parent only after the probe.
    if exec 3</dev/tty 2>/dev/null; then
        TTY_FD=3
    fi
fi

case "$WITH_CLI" in
    ask)
        if confirm "将 aiverywhere 命令加入 PATH 并配置模型？[y/N] " "n"; then
            WITH_CLI="yes"
        else
            WITH_CLI="no"
        fi
        ;;
esac

script_dir=$PWD
case "$0" in
    */*) script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || script_dir=$PWD ;;
esac

# The host-only path is pure POSIX Shell: copy the skill bundle, bind a project
# instance, and never create a Python environment.
if [ "$WITH_CLI" = "no" ]; then
    case "$LINK" in
        ask) LINK="yes" ;;
    esac
    skill_source=$script_dir/skills/aiverywhere
    bundle_tmp=""
    if [ ! -f "$skill_source/SKILL.md" ]; then
        command -v curl >/dev/null 2>&1 || fail "仅宿主安装需要 curl 以下载 skill bundle"
        command -v tar >/dev/null 2>&1 || fail "仅宿主安装需要 tar 以解包 skill bundle"
        bundle_tmp=$(mktemp -d) || fail "无法创建临时目录"
        trap 'rm -rf "$bundle_tmp"' EXIT HUP INT TERM
        note "下载 skill bundle：$REPO/archive/$REF.tar.gz"
        curl -fsSL "$REPO/archive/$REF.tar.gz" | tar -xz -C "$bundle_tmp" ||
            fail "skill bundle 下载失败"
        skill_source=$(find "$bundle_tmp" -type f -path '*/skills/aiverywhere/SKILL.md' -print -quit | sed 's#/SKILL.md$##')
        [ -f "$skill_source/SKILL.md" ] || fail "下载内容中没有 skills/aiverywhere/SKILL.md"
    fi
    target=$HOME_DIR/skills/aiverywhere
    same=0
    if [ -d "$target" ]; then
        source_real=$(CDPATH='' cd -- "$skill_source" && pwd -P)
        target_real=$(CDPATH='' cd -- "$target" && pwd -P)
        [ "$source_real" = "$target_real" ] && same=1
    fi
    note "aiverywhere 宿主安装"
    note "  安装根：$HOME_DIR"
    note "  项目：  $PROJECT_DIR"
    note "  技能源：$skill_source"
    run mkdir -p "$HOME_DIR/skills" || fail "无法创建安装根：$HOME_DIR"
    preserved=""
    if [ "$same" -eq 0 ] && [ -f "$target/SKILL.md" ]; then
        preserved=$(mktemp "${TMPDIR:-/tmp}/aiverywhere-skill.XXXXXX") || fail "无法保存活动 skill"
        cp "$target/SKILL.md" "$preserved"
    fi
    if [ "$same" -eq 0 ]; then
        run rm -rf "$target"
        run cp -R "$skill_source" "$target" || fail "无法复制 skill bundle"
        if [ -n "$preserved" ]; then
            cp "$preserved" "$target/SKILL.md"
            rm -f "$preserved"
        fi
        run chmod +x "$target/scripts/"*.sh || fail "无法设置脚本权限"
    fi
    if [ "$DRY_RUN" -eq 0 ]; then
        if [ "$LINK" = "no" ]; then
            AIVERYWHERE_HOME="$HOME_DIR" sh "$target/scripts/init-instance.sh" "$PROJECT_DIR" --no-link ||
                fail "初始化实例失败"
        else
            AIVERYWHERE_HOME="$HOME_DIR" sh "$target/scripts/init-instance.sh" "$PROJECT_DIR" ||
                fail "初始化实例失败"
        fi
    fi
    note ""
    note "aiverywhere 宿主安装完成；未安装 Python 或 CLI"
    note "  实例：  $HOME_DIR"
    note "  技能：  ${PROJECT_DIR}/.agents/skills/aiverywhere"
    note "  记忆：  $HOME_DIR/data/memory/"
    note ""
    note "宿主读取技能目录即可工作；需要 CLI 时重新运行并加 --cli。"
    exit 0
fi

if [ -z "$SOURCE" ]; then
    if [ -f "$script_dir/pyproject.toml" ] && [ -f "$script_dir/src/aiverywhere/__init__.py" ] &&
       grep -Eq '^[[:space:]]*name[[:space:]]*=[[:space:]]*"aiverywhere"' "$script_dir/pyproject.toml"; then
        SOURCE=$script_dir
        note "使用本地源码：$SOURCE"
    else
        SOURCE="aiverywhere @ $REPO/archive/$REF.tar.gz"
    fi
fi

# CLI is an optional extra layer on top of the same skill bundle and instance.
case "$LINK" in
    ask)
        if confirm "在本项目创建通用技能链接 .agents/skills/aiverywhere？[Y/n] " "y"; then
            LINK="yes"
        else
            LINK="no"
        fi
        ;;
esac
skill_source=$script_dir/skills/aiverywhere
if [ -f "$skill_source/SKILL.md" ]; then
    target=$HOME_DIR/skills/aiverywhere
    same=0
    if [ -d "$target" ]; then
        source_real=$(CDPATH='' cd -- "$skill_source" && pwd -P)
        target_real=$(CDPATH='' cd -- "$target" && pwd -P)
        [ "$source_real" = "$target_real" ] && same=1
    fi
    run mkdir -p "$HOME_DIR/skills" || fail "无法创建安装根：$HOME_DIR"
    preserved=""
    if [ "$same" -eq 0 ] && [ -f "$target/SKILL.md" ]; then
        preserved=$(mktemp "${TMPDIR:-/tmp}/aiverywhere-skill.XXXXXX") || fail "无法保存活动 skill"
        cp "$target/SKILL.md" "$preserved"
    fi
    if [ "$same" -eq 0 ]; then
        run rm -rf "$target"
        run cp -R "$skill_source" "$target" || fail "无法复制 skill bundle"
        if [ -n "$preserved" ]; then
            cp "$preserved" "$target/SKILL.md"
            rm -f "$preserved"
        fi
        run chmod +x "$target/scripts/"*.sh || fail "无法设置脚本权限"
    fi
    if [ "$DRY_RUN" -eq 0 ]; then
        if [ "$LINK" = "no" ]; then
            AIVERYWHERE_HOME="$HOME_DIR" sh "$target/scripts/init-instance.sh" "$PROJECT_DIR" --no-link ||
                fail "初始化实例失败"
        else
            AIVERYWHERE_HOME="$HOME_DIR" sh "$target/scripts/init-instance.sh" "$PROJECT_DIR" ||
                fail "初始化实例失败"
        fi
    fi
else
    note "未找到本地 skill bundle；CLI 将退回到原来的 Python 技能初始化"
fi

PYTHON=$(find_python) || fail "需要 Python 3.11 或更高版本；请先安装 Python，或用 AIVERYWHERE_PYTHON 指定解释器"
[ -n "$VENV" ] || VENV="$HOME_DIR/venv"

note "aiverywhere 安装器"
note "  安装根：$HOME_DIR"
note "  项目：  $PROJECT_DIR"
note "  Python：$PYTHON"
note "  安装源：$SOURCE"

run mkdir -p "$HOME_DIR" || fail "无法创建安装根：$HOME_DIR"
if [ ! -x "$VENV/bin/python" ]; then
    note "创建虚拟环境：$VENV"
    run "$PYTHON" -m venv "$VENV" || fail "无法创建虚拟环境。Debian/Ubuntu 可先安装 python3-venv"
else
    "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' ||
        fail "现有虚拟环境的 Python 低于 3.11：${VENV}；请删除后重试"
    if [ "$DRY_RUN" -eq 0 ] && ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
        "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || fail "虚拟环境缺少 pip：$VENV"
    fi
fi

run "$VENV/bin/python" -m pip install --upgrade --disable-pip-version-check "$SOURCE" ||
    fail "Python 包安装失败。可设置 PIP_INDEX_URL 使用镜像，或检查网络与安装源"

BIN="$VENV/bin/aiverywhere"
if [ "$DRY_RUN" -eq 0 ] && [ ! -x "$BIN" ]; then
    fail "安装后未找到命令：$BIN"
fi

run "$BIN" --home "$HOME_DIR" --project "$PROJECT_DIR" init ||
    fail "初始化失败。请检查 $HOME_DIR 是否可写"
if [ "$LINK" = "yes" ]; then
    run "$BIN" --home "$HOME_DIR" --project "$PROJECT_DIR" link ||
        fail "技能链接失败。请检查项目中是否已有同名技能文件"
fi

if [ "$WITH_CLI" = "yes" ]; then
    run mkdir -p "$BIN_DIR" || fail "无法创建命令目录：$BIN_DIR"
    if [ -e "$BIN_DIR/aiverywhere" ] && [ ! -L "$BIN_DIR/aiverywhere" ]; then
        fail "$BIN_DIR/aiverywhere 已存在且不是本安装器的链接，未覆盖"
    fi
    if [ -L "$BIN_DIR/aiverywhere" ]; then
        LINK_TARGET=$(readlink "$BIN_DIR/aiverywhere" 2>/dev/null || true)
        if [ "$LINK_TARGET" != "$BIN" ]; then
            fail "$BIN_DIR/aiverywhere 已指向 ${LINK_TARGET}，未覆盖"
        fi
        run rm -f "$BIN_DIR/aiverywhere"
    fi
    run ln -s "$BIN" "$BIN_DIR/aiverywhere" || fail "无法创建命令链接：$BIN_DIR/aiverywhere"
    if [ "$DRY_RUN" -eq 0 ] && [ "$ASSUME_YES" -eq 0 ] && [ -n "$TTY_FD" ]; then
        if [ "$TTY_FD" = 3 ]; then
            "$BIN" --home "$HOME_DIR" --project "$PROJECT_DIR" setup <&3 ||
                fail "模型配置未完成；可稍后运行 aiverywhere setup"
        else
            "$BIN" --home "$HOME_DIR" --project "$PROJECT_DIR" setup ||
                fail "模型配置未完成；可稍后运行 aiverywhere setup"
        fi
    elif [ "$DRY_RUN" -eq 0 ]; then
        "$BIN" --home "$HOME_DIR" --project "$PROJECT_DIR" setup --no-input ||
            fail "自动配置需要 --model 或 AIVERYWHERE_MODEL，以及凭据；也可稍后运行 aiverywhere setup"
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) note "提示：$BIN_DIR 不在 PATH。可执行：export PATH=\"$BIN_DIR:\$PATH\"" ;;
    esac
fi

note ""
note "aiverywhere 已安装"
if [ -f "$HOME_DIR/skills/aiverywhere/SKILL.md" ]; then
    note "  宿主入口：$HOME_DIR/skills/aiverywhere/SKILL.md"
else
    note "  宿主入口：$HOME_DIR/data/SKILL.md"
fi
if [ "$LINK" = "yes" ]; then
    note "  项目链接：$PROJECT_DIR/.agents/skills/aiverywhere"
fi
if [ "$WITH_CLI" = "yes" ]; then
    note "  命令：    $BIN_DIR/aiverywhere"
else
    note "  命令行：  未加入 PATH；需要时重新运行并加 --cli，或使用 $BIN"
fi
note ""
note "任意宿主 agent 读取上面的 SKILL.md 即可工作；新项目可运行 aiverywhere link。"
