#!/usr/bin/env bash
# Marginalia 一键部署包装（Linux / macOS / Git Bash）
#
# 这个脚本**只做三件事**：找 Python、设 UTF-8、把参数转给 CLI。
# 所有判断逻辑都在 marginalia/setup.py 里——脚本不做业务决策，
# 这样 Windows 与 Unix 不会出现两套行为。
set -eo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# 中文输出的前提：不设这个，Windows 上会按 GBK 编码炸掉
export PYTHONUTF8=1
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"

# 按「真的能跑」探测，而不是按「PATH 里有」探测。
# Windows 上 python3 常是 Microsoft Store 占位符：command -v 成功、执行失败。
# 开发期实测踩过这个坑：脚本选中 python3 后整个部署直接失败。
probe_python() {
  local exe="$1"
  shift
  command -v "$exe" >/dev/null 2>&1 || return 1
  "$exe" "$@" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 9) else 1)' \
    >/dev/null 2>&1
}

PYRUN=""
if probe_python python3; then
  PYRUN="python3"
elif probe_python python; then
  PYRUN="python"
elif probe_python py -3; then
  PYRUN="py -3"
fi

if [ -z "$PYRUN" ]; then
  echo "✗ 找不到可用的 Python（需要 3.9+）。" >&2
  echo "  → 安装后重试；或直接运行 python -m marginalia setup <参数>" >&2
  exit 1
fi

# $PYRUN 只有三种受控取值，允许按词切分
# shellcheck disable=SC2086
exec $PYRUN -X utf8 -m marginalia setup "$@"
