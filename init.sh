#!/usr/bin/env bash
# Python / FastAPI 项目的 init.sh（改自 learn-harness-engineering/docs/zh/resources/templates/init.sh）
# 用法：复制到项目根，改名 init.sh，chmod +x init.sh，然后 ./init.sh
# 和原版的三处差别：① 自动找项目内 .venv；② pytest 空测试返回 5 不算失败；③ 启动命令按 FastAPI 给。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"          # Windows venv（git-bash 下也能跑）
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"                  # POSIX venv
else
  PY="$(command -v python || command -v python3)"
fi

APP_MODULE="${APP_MODULE:-app.main:app}"

echo "==> 当前目录: $PWD"
echo "==> 解释器: $PY"

echo "==> 同步依赖"
if [ -f requirements.txt ]; then
  if "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m pip install -q -r requirements.txt
  elif command -v uv >/dev/null 2>&1; then
    # uv 建的 venv 里没有 pip；git-bash 下 uv 只认 Windows 路径，故用 cygpath 转换
    UV_PY="$PY"; command -v cygpath >/dev/null 2>&1 && UV_PY="$(cygpath -w "$PY")"
    uv pip install -q --python "$UV_PY" -r requirements.txt
  else
    echo "    (既没有 pip 也没有 uv，跳过依赖安装)"
  fi
else
  echo "    (没有 requirements.txt，跳过)"
fi

echo "==> 运行基础验证"
# 退出码约定：0=通过，5=pytest 没收集到测试（空项目，不算失败），
# 输出里出现 "No module named pytest"=真没装，跳过；其余一律当失败并打印原始输出。
set +e
VERIFY_OUT="$("$PY" -m pytest -q 2>&1)"; VERIFY_CODE=$?
set -e
if [ "$VERIFY_CODE" -eq 0 ]; then
  echo "$VERIFY_OUT" | tail -3
elif [ "$VERIFY_CODE" -eq 5 ]; then
  echo "    (没有测试，跳过)"
elif echo "$VERIFY_OUT" | grep -q "No module named pytest"; then
  echo "    (没装 pytest，退回语法检查)"
else
  echo "$VERIFY_OUT" | tail -20
  echo "!! 基础验证失败（退出码 $VERIFY_CODE），先修环境再干活"
  exit "$VERIFY_CODE"
fi
if [ -d app ]; then
  "$PY" -m compileall -q app
fi

echo "==> 启动命令: $PY -m uvicorn $APP_MODULE --reload"
if [ "${RUN_START_COMMAND:-0}" = "1" ]; then
  exec "$PY" -m uvicorn "$APP_MODULE" --reload
fi
echo "设 RUN_START_COMMAND=1 可直接启动；改 APP_MODULE 换入口。"
