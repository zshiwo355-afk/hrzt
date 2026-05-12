#!/usr/bin/env bash
# 打包项目源码（不含运行产物与敏感信息），生成 huanrenai-release-时间戳.zip
# 排除：venv、uploads、.env、本地缓存、仓库内已有 *.zip/*.rar 等大归档（勿打进发行包）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="huanrenai-release-$(date +%Y%m%d-%H%M).zip"

find . -type f \
  ! -path './.git/*' \
  ! -path './.venv/*' \
  ! -path './venv/*' \
  ! -path './ENV/*' \
  ! -path './.venv.bak/*' \
  ! -path './uploads/*' \
  ! -path './.cursor/*' \
  ! -path './.idea/*' \
  ! -path './.vscode/*' \
  ! -path './.pytest_cache/*' \
  ! -path './.mypy_cache/*' \
  ! -path './.ruff_cache/*' \
  ! -path '*/__pycache__/*' \
  ! -name '.env' \
  ! -name '.DS_Store' \
  ! -path './Untitled' \
  ! -name '*.pyc' \
  ! -name '*.zip' \
  ! -name '*.rar' \
  ! -name '*.7z' \
  ! -name '*.tar' \
  ! -name '*.tar.gz' \
  ! -path './data/model_cache/*' \
  | zip -q "$OUT" -@

ls -lh "$OUT"
echo "已生成: $ROOT/$OUT"
