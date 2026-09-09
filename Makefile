# pydsh Makefile
# 任务编排：make install → make tui / make test / make clean

SHELL := /bin/bash
ROOT := $(shell pwd)
PI_TUI := pydsh/infrastructure/tui/pi-tui
SETUP := bash scripts/setup.sh

.PHONY: help install tui test clean

# 默认目标
help:
	@echo "pydsh 自动化任务"
	@echo ""
	@echo "  make install    安装 Python + Node.js 依赖 & 编译 pi-tui 前端"
	@echo "  make tui        启动 pi-tui TUI 前端（需先配置 models.json）"
	@echo "  make test       运行全部测试"
	@echo "  make clean      清理编译产物与缓存"
	@echo ""

# ── 安装 ──────────────────────────────────────────────────────────────────────

install: $(PI_TUI)/node_modules $(PI_TUI)/dist/index.js
	@echo "[make] 依赖已就绪"

$(PI_TUI)/node_modules: $(PI_TUI)/package.json
	@echo "[make] 安装依赖..."
	@$(SETUP)

$(PI_TUI)/dist/index.js: $(PI_TUI)/node_modules
	@echo "[make] 编译 pi-tui 前端..."
	@cd $(PI_TUI) && npm run build

# ── 运行 ──────────────────────────────────────────────────────────────────────

tui: install
	@echo "[make] 启动 pi-tui TUI..."
	@pydsh --profile tui $(CURDIR)

# ── 测试 ──────────────────────────────────────────────────────────────────────

test: install
	@echo "[make] 运行测试..."
	@python -m pytest

# ── 清理 ──────────────────────────────────────────────────────────────────────

clean:
	@echo "[make] 清理..."
	@rm -rf $(PI_TUI)/dist $(PI_TUI)/node_modules
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	@rm -rf build dist .coverage htmlcov
	@echo "[make] 清理完成"