#!/usr/bin/env bash
# =============================================================================
# run_tests.sh — hello-agents 全量测试执行脚本
#
# 用法：
#   ./tests/run_tests.sh                  # 全量（unit + integration + connectivity）
#   ./tests/run_tests.sh --unit           # 仅单元测试（无外部服务，最快）
#   ./tests/run_tests.sh --integration    # 仅集成测试（mock，不调真实 API）
#   ./tests/run_tests.sh --connectivity   # 仅连通性测试（调真实 API / 数据库）
#   ./tests/run_tests.sh --no-report      # 跳过生成 HTML 报告
#   ./tests/run_tests.sh --unit --no-cov  # 不统计覆盖率（更快）
#
# 报告输出：
#   reports/test_report.html    — pytest-html 测试报告
#   reports/coverage/           — 覆盖率 HTML 报告
# =============================================================================

set -euo pipefail

# ── 路径定位 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▶ $*${RESET}"; }
success() { echo -e "${GREEN}✅ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${RESET}"; }
error()   { echo -e "${RED}❌ $*${RESET}"; }
header()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}${CYAN}  $*${RESET}"; \
            echo -e "${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; }

# ── 参数解析 ──────────────────────────────────────────────────────────────────
RUN_UNIT=false
RUN_INTEGRATION=false
RUN_CONNECTIVITY=false
WITH_REPORT=true
WITH_COV=true

for arg in "$@"; do
  case $arg in
    --unit)          RUN_UNIT=true ;;
    --integration)   RUN_INTEGRATION=true ;;
    --connectivity)  RUN_CONNECTIVITY=true ;;
    --no-report)     WITH_REPORT=false ;;
    --no-cov)        WITH_COV=false ;;
    --help|-h)
      sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) warn "未知参数: $arg（忽略）" ;;
  esac
done

# 默认：全量
if ! $RUN_UNIT && ! $RUN_INTEGRATION && ! $RUN_CONNECTIVITY; then
  RUN_UNIT=true
  RUN_INTEGRATION=true
  RUN_CONNECTIVITY=true
fi

# ── 环境检查 ──────────────────────────────────────────────────────────────────
header "环境检查"

# Python
PYTHON=$(command -v python3 || command -v python || true)
[ -z "$PYTHON" ] && { error "未找到 Python"; exit 1; }
info "Python: $($PYTHON --version)"

# pytest
if ! $PYTHON -m pytest --version &>/dev/null; then
  warn "pytest 未安装，正在安装..."
  $PYTHON -m pip install pytest pytest-asyncio pytest-cov pytest-html -q
fi

# pytest-html / pytest-cov（可选）
$WITH_REPORT && $PYTHON -c "import pytest_html" 2>/dev/null || \
  { warn "pytest-html 未安装，自动安装..."; $PYTHON -m pip install pytest-html -q; }
$WITH_COV && $PYTHON -c "import pytest_cov" 2>/dev/null || \
  { warn "pytest-cov 未安装，自动安装..."; $PYTHON -m pip install pytest-cov -q; }

# .env
if [ -f "$PROJECT_ROOT/.env" ]; then
  info ".env 已检测到，将由测试文件自动加载"
else
  warn ".env 不存在，连通性测试可能跳过或失败"
fi

# 创建报告目录
mkdir -p "$PROJECT_ROOT/reports"

# ── 构建 pytest 参数 ──────────────────────────────────────────────────────────
PYTEST_ARGS=("-v" "--tb=short")

# 覆盖率
if $WITH_COV; then
  PYTEST_ARGS+=(
    "--cov=hello_agents"
    "--cov-report=term-missing"
    "--cov-report=html:reports/coverage"
  )
fi

# HTML 报告
if $WITH_REPORT; then
  PYTEST_ARGS+=(
    "--html=reports/test_report.html"
    "--self-contained-html"
  )
fi

# ── 确定要跑的测试路径 ────────────────────────────────────────────────────────
TEST_PATHS=()

if $RUN_UNIT; then
  TEST_PATHS+=("tests/unit/")
fi

if $RUN_INTEGRATION; then
  # 集成测试中排除连通性（连通性单独控制）
  TEST_PATHS+=(
    "tests/integration/test_agent.py"
    "tests/integration/test_context_builder.py"
    "tests/integration/test_web_search_tool.py"
  )
fi

if $RUN_CONNECTIVITY; then
  TEST_PATHS+=("tests/integration/test_env_connectivity.py")
fi

# ── 执行 ──────────────────────────────────────────────────────────────────────
START_TS=$(date +%s)

header "开始执行测试"
info "模式: unit=$RUN_UNIT  integration=$RUN_INTEGRATION  connectivity=$RUN_CONNECTIVITY"
info "路径: ${TEST_PATHS[*]}"
echo ""

set +e
$PYTHON -m pytest "${PYTEST_ARGS[@]}" "${TEST_PATHS[@]}"
EXIT_CODE=$?
set -e

END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))

# ── 结果汇总 ──────────────────────────────────────────────────────────────────
header "测试完成"
info "耗时: ${ELAPSED}s"

if [ $EXIT_CODE -eq 0 ]; then
  success "所有测试通过 🎉"
else
  error "存在测试失败（exit code: $EXIT_CODE）"
fi

if $WITH_REPORT && [ -f "$PROJECT_ROOT/reports/test_report.html" ]; then
  info "测试报告: file://$PROJECT_ROOT/reports/test_report.html"
fi
if $WITH_COV && [ -d "$PROJECT_ROOT/reports/coverage" ]; then
  info "覆盖率报告: file://$PROJECT_ROOT/reports/coverage/index.html"
fi

exit $EXIT_CODE
