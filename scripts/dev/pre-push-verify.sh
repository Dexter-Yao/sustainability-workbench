#!/usr/bin/env bash
# ABOUTME: git pre-push 的验证入口，跑通 make verify 全链路后才允许推送到远程。
# ABOUTME: 先断言数据库与 LibreOffice 前置，避免持久化与导出用例静默跳过后伪装成全绿。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -n "${SUSTAINABILITY_DESK_SKIP_PREPUSH:-}" ]]; then
  echo "pre-push: 已由 SUSTAINABILITY_DESK_SKIP_PREPUSH 显式跳过验证" >&2
  exit 0
fi

started_at=$(date +%s)

# --- 前置断言 ---------------------------------------------------------------
# 这两项缺失时 pytest 不报错，只把对应用例 skip 掉；不拦住就会推走一份
# 「持久化与导出从未被验证」的全绿结果。
echo "== 0/3 前置检查 =="

if ! nc -z 127.0.0.1 54322 >/dev/null 2>&1; then
  cat >&2 <<'HINT'
   ✗ 本机 Supabase 栈未启动（127.0.0.1:54322 不可达）

   9 个文件的持久化用例会静默 skip 并显示全绿：账户、报告、生成运行、
   报告事件与归档、数据库访问边界、API 错误契约、手机号注册、
   章节生成批次、材料快照排序。

   先启动再推送：  supabase start
HINT
  exit 1
fi
echo "   ✓ Supabase 栈可达"

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then
  cat >&2 <<'HINT'
   ✗ 未找到 LibreOffice（soffice）

   Word 导出的视觉验收用例会静默 skip。Word 导出保真是一级风险，
   不接受「未验证」冒充「已通过」。

   注意：LibreOffice 对**使用者**是可选的（没装则目录页码由阅读器打开时解析），
   但对**改代码的人**是必需的——预先算好页码这条路径同样要被验证过才能推送。

   安装后再推送：  brew install --cask libreoffice
HINT
  exit 1
fi
echo "   ✓ LibreOffice 可用"

# --- 验证链路 ---------------------------------------------------------------
# 与 make verify 同一套命令；此处拆开只为逐段显示进度与耗时。
echo "== 1/3 backend pytest =="
(cd backend && uv run pytest -q)

echo "== 2/3 frontend 测试 / lint / 构建 =="
(cd frontend && npm test && npm run lint && npm run build)

echo "== 3/3 完成 =="
echo "验证通过，用时 $(( $(date +%s) - started_at )) 秒，允许推送。"
