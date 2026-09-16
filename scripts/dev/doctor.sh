#!/usr/bin/env bash
# ABOUTME: 本地开发前置检查，只验证工具、本机栈端口和环境标识，不读取或打印密钥。
# ABOUTME: 任何失败均明确退出，避免带着错误环境继续启动服务。
set -euo pipefail

required=(node npm uv docker supabase curl)
for command_name in "${required[@]}"; do
  command -v "$command_name" >/dev/null || { echo "缺少命令: $command_name" >&2; exit 1; }
done

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if (( node_major < 22 )); then
  echo "Node.js 需要 22 或以上，当前为 $(node --version)" >&2
  exit 1
fi

# LibreOffice 是导出的运行时硬依赖，不是验收工具：Word 目录页码要靠排版引擎跑一遍分页
# 才算得出，python-docx 不做排版，故 finalize_toc_page_numbers 在每次导出末尾无条件调用，
# 缺 soffice 直接 TocFinalizationError。这里与 pre-push 一致按失败处理，不降级为提示——
# 提示会让用户一路装到「生成成功、导出失败」才发现。
if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then
  echo "缺少 LibreOffice（soffice）：Word 导出的运行时依赖，缺它导出必然失败" >&2
  echo "  macOS 安装： brew install --cask libreoffice" >&2
  exit 1
fi
# pandoc 只用于重生成合成语料的 docx 派生产物，不在产品运行路径上，故保持提示级。
command -v pandoc >/dev/null 2>&1 \
  || echo "提示: 未找到 pandoc，晟原语料的 docx 派生产物无法重生成（不影响产品运行）"

# 以下两项都是按需安装的可选组件，缺失不影响主链，但缺了又没人提醒时
# 用户会撞上一个没有指引的失败 + 一次意外的大体积下载，故在此如实报出。
# 探测**项目 venv**而非系统 python：OCR 装在 backend/.venv 里，用系统解释器判断会
# 对每个用户都误报「未安装」——一条恒假的提示比没有提示更糟。venv 尚未创建时跳过本项，
# 那种情况下用户还没跑过 uv sync，提示 OCR 没有意义。
if [[ -x "backend/.venv/bin/python" ]]; then
  backend/.venv/bin/python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('rapidocr') else 1)" >/dev/null 2>&1 \
    || echo "提示: 未安装 OCR 组件（约 220 MB），扫描成图片的 PDF 无法识别；需要时执行 uv sync --extra ocr"
fi
[[ -d "$HOME/Library/Caches/ms-playwright" || -d "$HOME/.cache/ms-playwright" ]] \
  || echo "提示: 未安装 Playwright 浏览器（约 540 MB），npm run test:e2e 会失败；需要时执行 npx playwright install chromium"

if [[ "${SUSTAINABILITY_DESK_ENVIRONMENT:-local}" == "production" ]]; then
  echo "本地开发入口拒绝 SUSTAINABILITY_DESK_ENVIRONMENT=production" >&2
  exit 1
fi
if [[ "${SUSTAINABILITY_DESK_SUPABASE_PROJECT:-sustainability-desk-local}" != "sustainability-desk-local" ]]; then
  echo "本地开发必须使用 sustainability-desk-local（本机 Supabase 栈）" >&2
  exit 1
fi

if ! nc -z 127.0.0.1 54322 >/dev/null 2>&1; then
  echo "提示: 本机 Supabase 栈未启动（127.0.0.1:54322 不可达），先执行 supabase start"
fi

for port in 3000 8010; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "提示: 端口 $port 已有监听进程"
  fi
done

echo "本地开发前置检查通过"
