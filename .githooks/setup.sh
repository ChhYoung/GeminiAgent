#!/usr/bin/env bash
# 克隆仓库后执行一次，启用 .githooks/ 中的 git hooks
set -e
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
echo "✅ Git hooks 已启用（.githooks/）"
