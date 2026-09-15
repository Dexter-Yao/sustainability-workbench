#!/usr/bin/env bash
# ABOUTME: 把 git 的钩子目录指向仓库内受版本控制的 hooks/，使 pre-push 验证可随仓库分发。
# ABOUTME: 幂等，重新 clone 或换机后重跑即可；不改写 .git/hooks 下的任何既有文件。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

git config core.hooksPath hooks
chmod +x hooks/* 2>/dev/null || true

echo "已将 core.hooksPath 指向 hooks/"
echo "  启用的钩子：pre-push（跑 make verify 全链路，约 3.5 分钟）"
echo "  单次跳过：  SUSTAINABILITY_DESK_SKIP_PREPUSH=1 git push"
