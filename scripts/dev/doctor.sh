#!/usr/bin/env bash
# ABOUTME: Local development preflight — checks tools, local stack ports and the environment label only.
# ABOUTME: Never reads or prints secrets. Any hard failure exits, so nothing starts against a wrong environment.
# ABOUTME(zh): 本地开发前置检查；输出为英文，与产品界面语言无关——它是给装机者看的工具信息。
set -euo pipefail

required=(node npm uv docker supabase curl)
for command_name in "${required[@]}"; do
  command -v "$command_name" >/dev/null || { echo "Missing command: $command_name" >&2; exit 1; }
done

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if (( node_major < 22 )); then
  echo "Node.js 22 or newer is required; found $(node --version)" >&2
  exit 1
fi

# LibreOffice only pre-computes table-of-contents page numbers, so it is an enhancement rather than
# a hard dependency: each entry is a PAGEREF field pointing at a bookmark in the same document and
# carries a dirty flag, which Word and LibreOffice resolve on open (measured identical to the
# pre-computed numbers, entry by entry). The only difference is whether the number is already there
# or is computed as the document opens — not worth demanding a whole 800 MB office suite.
command -v soffice >/dev/null 2>&1 || command -v libreoffice >/dev/null 2>&1 \
  || echo "Note: LibreOffice is not installed (~800 MB). Word TOC page numbers will be resolved by the reader on open; install it if you want them frozen at export time."
# pandoc only regenerates the .docx derivatives of the synthetic corpus; not on the product path.
command -v pandoc >/dev/null 2>&1 \
  || echo "Note: pandoc not found. The .docx derivatives of the synthetic corpus cannot be rebuilt (the product itself is unaffected)."

# Both of the following are install-on-demand; missing them does not break the main flow, but with
# nobody to say so the user hits an unguided failure plus an unannounced large download.
# Probe the PROJECT venv, not the system interpreter: OCR installs into backend/.venv, so checking
# system Python would warn every user forever — a permanently false note is worse than none.
# Skip entirely when the venv does not exist yet; at that point the user has not run uv sync.
if [[ -x "backend/.venv/bin/python" ]]; then
  backend/.venv/bin/python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('rapidocr') else 1)" >/dev/null 2>&1 \
    || echo "Note: OCR components are not installed (~220 MB). Scanned (image-only) PDFs cannot be read; run 'uv sync --extra ocr' when you need them."
fi
[[ -d "$HOME/Library/Caches/ms-playwright" || -d "$HOME/.cache/ms-playwright" ]] \
  || echo "Note: Playwright browsers are not installed (~540 MB). 'npm run test:e2e' will fail; run 'npx playwright install chromium' when you need it."

# A missing or unfilled backend/.env is the most common first-run failure, and its symptom
# (503 from persistence endpoints) does not point at the cause. Only existence and leftover
# placeholders are checked here; the values themselves are asserted by the backend at startup.
if [[ ! -f backend/.env ]]; then
  echo "Note: backend/.env not found. Persistence endpoints will return 503 — copy backend/.env.example and fill it in (SETUP.md step 3)."
elif grep -qE '^[A-Z_]+=<' backend/.env 2>/dev/null; then
  echo "Note: backend/.env still contains <...> placeholders; the features that read them will fail."
fi

if [[ "${SUSTAINABILITY_DESK_ENVIRONMENT:-local}" == "production" ]]; then
  echo "The local development entry point refuses SUSTAINABILITY_DESK_ENVIRONMENT=production" >&2
  exit 1
fi
if [[ "${SUSTAINABILITY_DESK_SUPABASE_PROJECT:-sustainability-desk-local}" != "sustainability-desk-local" ]]; then
  echo "Local development must use the sustainability-desk-local Supabase stack" >&2
  exit 1
fi

if ! nc -z 127.0.0.1 54322 >/dev/null 2>&1; then
  echo "Note: the local Supabase stack is not running (127.0.0.1:54322 unreachable). Run 'supabase start' first."
fi

for port in 3000 8010; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Note: port $port already has a listener"
  fi
done

echo "Local development preflight passed"
