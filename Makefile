PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python

.PHONY: help venv install test test-shell acceptance lint build check clean

help:
	@printf '%s\n' \
	  'make install  创建 .venv 并安装开发依赖' \
	  'make test     运行标准库 unittest' \
	  'make acceptance 运行十个 CLI/宿主验收场景' \
	  'make lint     运行 ruff 和安装脚本语法检查' \
	  'make check    lint + test' \
	  'make build    构建 sdist 与 wheel' \
	  'make clean    删除构建产物'

venv:
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)

install: venv
	$(PY) -m ensurepip --upgrade >/dev/null
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m unittest discover -s tests -v

test-shell:
	sh tests/shell/memory.sh
	sh tests/shell/memory-conformance.sh

acceptance:
	$(PY) -m unittest tests.test_acceptance_matrix -v

lint:
	$(BIN)/ruff check .
	sh -n install.sh
	for script in skills/aiverywhere/scripts/*.sh tests/shell/memory.sh tests/shell/memory-conformance.sh; do sh -n "$$script" || exit; done

check: lint test test-shell

build:
	$(PY) -m build

clean:
	rm -rf build dist src/*.egg-info .ruff_cache
