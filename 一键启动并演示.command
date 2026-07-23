#!/bin/zsh

set -u

ROOT_DIR="${0:A:h}"
PYTHON_BIN="/Users/chr/.hermes/hermes-agent/venv/bin/python"
PORT="${QINGSHU_PORT:-8000}"
BASE_URL="http://127.0.0.1:${PORT}"
SERVER_PID=""

cd "$ROOT_DIR" || exit 1

echo ""
echo "================================================"
echo "  清数智算｜一键启动"
echo "================================================"
echo ""

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "❌ 没找到运行环境：$PYTHON_BIN"
  echo "请把这个提示发给开发人员。"
  read -k 1 "?按任意键关闭..."
  exit 1
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
  DEFAULT_A_SHARE_SYMBOLS="${DEFAULT_A_SHARE_SYMBOLS:-000063.SZ,300308.SZ}" \
  DEFAULT_RESEARCH_SYMBOLS="${DEFAULT_RESEARCH_SYMBOLS:-000063.SZ,300308.SZ,NVDA}" \
  HERMES_ENABLED="${HERMES_ENABLED:-true}" \
  HERMES_ECONOMY_PROVIDER="${HERMES_ECONOMY_PROVIDER:-deepseek}" \
  HERMES_ECONOMY_MODEL="${HERMES_ECONOMY_MODEL:-deepseek-chat}" \
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

open "$BASE_URL/demo" >/dev/null 2>&1 || true

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
