#!/bin/zsh

set -u

ROOT_DIR="${0:A:h}"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_DIR="${QINGSHU_VENV_DIR:-$ROOT_DIR/.venv}"
PORT="${QINGSHU_PORT:-8000}"
BASE_URL="http://127.0.0.1:${PORT}"
SERVER_PID=""
HERMES_ENABLED_VALUE="${HERMES_ENABLED:-false}"
HERMES_ECONOMY_PROVIDER_VALUE="${HERMES_ECONOMY_PROVIDER:-deepseek}"
HERMES_ECONOMY_MODEL_VALUE="${HERMES_ECONOMY_MODEL:-deepseek-v4-pro}"
HERMES_DEEP_PROVIDER_VALUE="${HERMES_DEEP_PROVIDER:-deepseek}"
HERMES_DEEP_MODEL_VALUE="${HERMES_DEEP_MODEL:-deepseek-v4-pro}"

cd "$ROOT_DIR" || exit 1

echo ""
echo "================================================"
echo "  清数智算｜一键启动"
echo "================================================"
echo ""

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    SYSTEM_PYTHON="$(command -v python3)"
    if ! "$SYSTEM_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      echo "❌ 需要 Python 3.11 或更高版本。"
      echo "请先从 https://www.python.org/downloads/ 安装新版 Python。"
      read -k 1 "?按任意键关闭..."
      exit 1
    fi
    echo "首次运行：正在创建项目独立环境…"
    "$SYSTEM_PYTHON" -m venv "$VENV_DIR" || exit 1
    PYTHON_BIN="$VENV_DIR/bin/python"
  else
    echo "❌ 没有找到 Python 3。"
    echo "请先从 https://www.python.org/downloads/ 安装 Python 3.11 或更高版本。"
    read -k 1 "?按任意键关闭..."
    exit 1
  fi
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "❌ Python 路径不可执行：$PYTHON_BIN"
  read -k 1 "?按任意键关闭..."
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "首次运行：正在安装清数智算依赖…"
  "$PYTHON_BIN" -m pip install --upgrade pip || exit 1
  "$PYTHON_BIN" -m pip install -e "$ROOT_DIR" || exit 1
fi

mkdir -p "$ROOT_DIR/data"

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    echo ""
    echo "正在停止清数智算后端..."
    kill "$SERVER_PID" 2>/dev/null || true
    for _ in {1..30}; do
      if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      kill -9 "$SERVER_PID" 2>/dev/null || true
    fi
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "✅ 清数智算已经在运行，正在打开产品页面。"
else
  echo "正在启动清数智算，请稍等..."
  HERMES_BIN_VALUE="${HERMES_BIN:-hermes}"
  if [[ -z "${HERMES_ENABLED+x}" ]]; then
    if [[ -x "$HERMES_BIN_VALUE" ]] || command -v "$HERMES_BIN_VALUE" >/dev/null 2>&1; then
      HERMES_ENABLED_VALUE="true"
    else
      HERMES_ENABLED_VALUE="false"
    fi
  else
    HERMES_ENABLED_VALUE="$HERMES_ENABLED"
  fi
  DEFAULT_A_SHARE_SYMBOLS="${DEFAULT_A_SHARE_SYMBOLS:-000063.SZ,300308.SZ}" \
  DEFAULT_RESEARCH_SYMBOLS="${DEFAULT_RESEARCH_SYMBOLS:-000063.SZ,300308.SZ,NVDA}" \
  HERMES_ENABLED="$HERMES_ENABLED_VALUE" \
  HERMES_BIN="$HERMES_BIN_VALUE" \
  HERMES_ECONOMY_PROVIDER="$HERMES_ECONOMY_PROVIDER_VALUE" \
  HERMES_ECONOMY_MODEL="$HERMES_ECONOMY_MODEL_VALUE" \
  HERMES_DEEP_PROVIDER="$HERMES_DEEP_PROVIDER_VALUE" \
  HERMES_DEEP_MODEL="$HERMES_DEEP_MODEL_VALUE" \
  "$PYTHON_BIN" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --timeout-graceful-shutdown 3 \
    > "$ROOT_DIR/data/server.log" 2>&1 &
  SERVER_PID=$!

  READY=false
  for _ in {1..40}; do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
      READY=true
      break
    fi
    sleep 0.25
  done

  if [[ "$READY" != "true" ]]; then
    echo "❌ 启动失败。日志位置：$ROOT_DIR/data/server.log"
    tail -20 "$ROOT_DIR/data/server.log"
    read -k 1 "?按任意键关闭..."
    exit 1
  fi
  echo "✅ 启动成功。"
fi

if command -v open >/dev/null 2>&1; then
  open "$BASE_URL/demo" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$BASE_URL/demo" >/dev/null 2>&1 || true
fi

echo ""
echo "================================================"
echo "✅ 产品页面已打开"
echo "请保持这个窗口开启，数据与研究报告会自动更新。"
if [[ "$HERMES_ENABLED_VALUE" != "true" ]]; then
  echo "当前未检测到 Hermes，系统会使用无需模型费用的确定性研究模式。"
fi
echo "关闭这个窗口即可停止清数智算。"
echo "================================================"
echo ""

if [[ -n "$SERVER_PID" ]]; then
  wait "$SERVER_PID"
else
  read -k 1 "?清数智算由其他进程运行。按任意键关闭这个窗口..."
fi
