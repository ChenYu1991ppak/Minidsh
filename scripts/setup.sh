#!/usr/bin/env bash
# pydsh 一键安装脚本
# 安装 Python + Node.js 依赖，编译 pi-tui 前端
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $*"; }
err()   { echo -e "${RED}[setup]${NC} $*"; }
step()  { echo -e "\n${BOLD}==>${NC} ${BOLD}$*${NC}"; }

# ── 0. 定位项目根目录 ────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── 1. 检查 Python ───────────────────────────────────────────────────────────

step "检查 Python 环境"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)
        if [ -n "$ver" ]; then
            major=$(echo "$ver" | python3 -c 'import sys,ast; t=ast.literal_eval(sys.stdin.read()); print(t[0])')
            minor=$(echo "$ver" | python3 -c 'import sys,ast; t=ast.literal_eval(sys.stdin.read()); print(t[1])')
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                PYTHON="$candidate"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "未找到 Python >= 3.11，请先安装 Python 3.11+"
    exit 1
fi
info "Python: $($PYTHON --version)"

# ── 2. 检查/安装 Node.js ─────────────────────────────────────────────────────

step "检查 Node.js 环境"

NEED_NODE=false
if ! command -v node &>/dev/null; then
    NEED_NODE=true
else
    NODE_MAJOR=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
    if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
        NEED_NODE=true
    fi
fi

if [ "$NEED_NODE" = true ]; then
    warn "未找到 Node.js >= 18，尝试自动安装..."
    if [ "$(uname -s)" = "Linux" ]; then
        if command -v apt-get &>/dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs
        elif command -v dnf &>/dev/null; then
            dnf install -y nodejs npm
        elif command -v yum &>/dev/null; then
            curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - && yum install -y nodejs
        else
            err "无法自动安装 Node.js（未知包管理器），请手动安装 Node.js >= 18"
            err "  https://nodejs.org/en/download/"
            exit 1
        fi
    elif [ "$(uname -s)" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            brew install node
        else
            err "请先安装 Homebrew (https://brew.sh) 或手动安装 Node.js"
            exit 1
        fi
    else
        err "不支持的操作系统，请手动安装 Node.js >= 18"
        exit 1
    fi
fi

info "Node.js: $(node -v)"
info "npm:     $(npm -v)"

# ── 3. 安装 Python 依赖 ──────────────────────────────────────────────────────

step "安装 Python 依赖"

"$PYTHON" -m pip install -e . --no-build-isolation

# ── 4. 安装 pi-tui 前端依赖 ──────────────────────────────────────────────────

step "安装 pi-tui 前端依赖"

PI_TUI_DIR="$PROJECT_ROOT/pydsh/infrastructure/tui/pi-tui"
cd "$PI_TUI_DIR"
npm install
npm run build
cd "$PROJECT_ROOT"

# ── 5. 引导配置 models.json ──────────────────────────────────────────────────

step "安装完成！"

echo ""
echo -e "  ${BOLD}下一步：配置模型${NC}"
echo ""
echo -e "  在 ${BOLD}~/.pydsh/models.json${NC} 中填入你的 API key："
echo ""
echo -e "  ${YELLOW}mkdir -p ~/.pydsh${NC}"
echo -e "  ${YELLOW}cat > ~/.pydsh/models.json << 'EOF'${NC}"
echo "  {"
echo "    \"currentModel\": \"deepseek\","
echo "    \"availableModels\": ["
echo "      {"
echo "        \"id\": \"deepseek\","
echo "        \"baseUrl\": \"https://api.deepseek.com\","
echo "        \"apiKey\": \"sk-your-api-key-here\","
echo "        \"model\": \"deepseek-chat\""
echo "      }"
echo "    ]"
echo "  }"
echo "  EOF"
echo ""
echo -e "  格式说明：${BOLD}docs/PRINCIPLES.md${NC} §8"
echo ""
echo -e "  配置完成后运行：${BOLD}make tui${NC}"
echo ""