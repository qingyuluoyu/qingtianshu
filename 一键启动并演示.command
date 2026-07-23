#!/bin/zsh

set -u

ROOT_DIR="${0:A:h}"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_DIR="${QINGSHU_VENV_DIR:-$ROOT_DIR/.venv}"
RUNTIME_DIR="${QINGSHU_RUNTIME_DIR:-$ROOT_DIR/.qingshu-runtime}"
PORT="${QINGSHU_PORT:-8000}"
BASE_URL="http://127.0.0.1:${PORT}"
SERVER_PID=""

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

echo "正在检查并更新清数智算运行环境…"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYTHON_BIN" -e "$ROOT_DIR" || exit 1
else
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || {
      echo "❌ 当前 Python 环境缺少 pip，且无法自动安装。"
      read -k 1 "?按任意键关闭..."
      exit 1
    }
  fi
  "$PYTHON_BIN" -m pip install --disable-pip-version-check -e "$ROOT_DIR" || exit 1
fi

mkdir -p "$RUNTIME_DIR"

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
  "$PYTHON_BIN" -m app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --no-browser \
    > "$RUNTIME_DIR/server.log" 2>&1 &
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
    echo "❌ 启动失败。日志位置：$RUNTIME_DIR/server.log"
    tail -20 "$RUNTIME_DIR/server.log"
    read -k 1 "?按任意键关闭..."
    exit 1
  fi
  echo "✅ 启动成功。"
fi

if command -v open >/dev/null 2>&1; then
  open "$BASE_URL/today" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$BASE_URL/today" >/dev/null 2>&1 || true
fi

echo ""
echo "================================================"
echo "✅ 产品页面已打开"
echo "请保持这个窗口开启，数据与研究报告会自动更新。"
echo "关闭这个窗口即可停止清数智算。"
echo "================================================"
echo ""

if [[ -n "$SERVER_PID" ]]; then
  wait "$SERVER_PID"
else
  read -k 1 "?清数智算由其他进程运行。按任意键关闭这个窗口..."
fi
