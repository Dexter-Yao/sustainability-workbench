#!/usr/bin/env bash
# ABOUTME: 本机手动验收全栈编排：Supabase 前提检查 + 后端 API + 双 worker + 前端，一条命令起停。
# ABOUTME: 命令由 Agent 执行、用户只在浏览器操作页面（docs/local-e2e-acceptance.md §9）；worker 在位=真实模型调用。
#
# 用法：
#   scripts/dev/local-acceptance-stack.sh up          # 启动全栈（前端 dev 模式）
#   scripts/dev/local-acceptance-stack.sh up --build  # 前端用生产 build（next build && start，最接近正式运行形态）
#   scripts/dev/local-acceptance-stack.sh status      # 各进程与端口探活 + OTLP 后端 上报状态
#   scripts/dev/local-acceptance-stack.sh down        # 停止全部由本脚本启动的进程
#
# 注意事项（与 docs/local-e2e-acceptance.md 对齐）：
# - 前提：本地 Supabase 栈已运行（54321/54322）；backend/.env 存在且含模型密钥。
# - 浏览器一律使用 http://localhost:3000（127.0.0.1 需 next.config.ts allowedDevOrigins，已放行但仍以 localhost 为准）。
# - OTLP 后端 上报：backend/.env 配有 SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT/HEADERS 时自动开启；
#   SUSTAINABILITY_DESK_ENVIRONMENT=local 会把 span 记到 sustainability-desk-lightweight-report-nonprod 应用，与生产隔离。
#   本地 JSONL 始终是真相，OTLP 后端 只是镜像；不需要上报时从 backend/.env 移除这两行即可。
# - worker 在位=真实模型调用：上传资料后点「下一步：资料处理」即开始逐份 File Agent；「生成报告」入队生成。
# - 新迁移（supabase/migrations/）需已应用到本地库；缺列会在账户/资料接口报 UndefinedColumn。
# - 验收数据见 docs/local-e2e-acceptance.md「浏览器手动验收」（数据用 scripts/dev/acceptance_data.py prepare 生成）。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
backend_dir="$repo_root/backend"
frontend_dir="$repo_root/frontend"
log_dir="$repo_root/backend/out/local-stack-logs"
pid_dir="$log_dir/pids"

api_port=8010
frontend_port=3000
supabase_api_port=54321
supabase_db_port=54322

mkdir -p "$log_dir" "$pid_dir"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

port_alive() { curl -s -o /dev/null --max-time 3 "http://localhost:$1$2"; }

start_one() {
  local name="$1"; shift
  local workdir="$1"; shift
  local pid_file="$pid_dir/$name.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    say "· $name 已在运行 (pid $(cat "$pid_file"))"
    return
  fi
  ( cd "$workdir" && nohup "$@" > "$log_dir/$name.log" 2>&1 & echo $! > "$pid_file" )
  say "· $name 启动 (pid $(cat "$pid_file"))，日志 $log_dir/$name.log"
}

stop_one() {
  local name="$1"
  local pid_file="$pid_dir/$name.pid"
  if [[ -f "$pid_file" ]]; then
    local pid; pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      # uv run 会派生子进程；按进程组停干净。
      kill -- -"$(ps -o pgid= -p "$pid" | tr -d ' ')" 2>/dev/null || kill "$pid" 2>/dev/null || true
      say "· $name 已停止"
    fi
    rm -f "$pid_file"
  fi
}

check_prerequisites() {
  [[ -f "$backend_dir/.env" ]] || die "缺少 backend/.env（模型密钥与持久化配置）"
  port_alive "$supabase_api_port" "/auth/v1/health" || port_alive "$supabase_api_port" "/" \
    || die "本地 Supabase 栈未运行（:$supabase_api_port 无响应）；先启动 supabase 本地栈"
  # 迁移就位检查：material_sources.purpose 列已删除，该列仍存在即迁移未应用。
  ( cd "$backend_dir" && uv run python - <<'PY'
import asyncio, asyncpg
async def main():
    conn = await asyncpg.connect("postgresql://postgres:postgres@127.0.0.1:54322/postgres")
    stale = await conn.fetchval(
        "select count(*) from information_schema.columns"
        " where table_name='material_sources' and column_name='purpose'")
    await conn.close()
    raise SystemExit(2 if stale else 0)
asyncio.run(main())
PY
  ) || die "本地库缺少最新迁移（material_sources.purpose 应已删除）；请按 supabase/migrations/ 应用后重试"
  say "✓ 前提检查通过（Supabase 栈、.env、迁移）"
}

otlp_status() {
  if grep -q "^SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT=" "$backend_dir/.env" 2>/dev/null; then
    local env_name
    env_name="$(grep "^SUSTAINABILITY_DESK_ENVIRONMENT=" "$backend_dir/.env" | cut -d= -f2)"
    if [[ "$env_name" == "production" ]]; then
      say "⚠ OTLP 后端 上报：已启用，且 SUSTAINABILITY_DESK_ENVIRONMENT=production —— 本机不应冒充生产，请检查 .env"
    else
      say "✓ OTLP 后端 上报：已启用（本地 JSONL 仍是真相）"
    fi
  else
    say "· OTLP 后端 上报：未启用（backend/.env 无 SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT，观测只落本地 JSONL）"
  fi
}

cmd_up() {
  local build_mode="${1:-}"
  check_prerequisites
  otlp_status
  # OTLP 后端 上报键显式注入环境（等价 systemd EnvironmentFile；.env 的 load_dotenv 在
  # llm.client import 时才执行，晚于 exporter 初始化，不能依赖）。
  local otlp_env=()
  if grep -q "^SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT=" "$backend_dir/.env"; then
    otlp_env=(
      "$(grep '^SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT=' "$backend_dir/.env")"
      "$(grep '^SUSTAINABILITY_DESK_OTLP_TRACES_HEADERS=' "$backend_dir/.env")"
    )
  fi
  start_one backend "$backend_dir" \
    env ${otlp_env[@]+"${otlp_env[@]}"} SUSTAINABILITY_DESK_SERVICE_ROLE=api uv run uvicorn sustainability_desk.api.app:app --host 0.0.0.0 --port "$api_port"
  # 消费协程数即 File Agent 与 Mapping 的并发上限；
  # 默认 4 会把 File Agent 与 Mapping 的并发压到个位数，本机 12C/36G 无此必要。
  start_one material-worker "$backend_dir" \
    env ${otlp_env[@]+"${otlp_env[@]}"} SUSTAINABILITY_DESK_SERVICE_ROLE=material-worker \
    SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY=30 uv run python -m sustainability_desk.material.agent_worker
  if [[ "$build_mode" == "--build" ]]; then
    say "· 前端生产 build（最接近正式运行形态，无 HMR 与 dev 断言）…"
    ( cd "$frontend_dir" && npm run build ) || die "前端 build 失败"
    start_one frontend "$frontend_dir" npm run start -- --port "$frontend_port"
  else
    start_one frontend "$frontend_dir" npm run dev -- --port "$frontend_port"
  fi
  say "等待就绪…"
  for _ in $(seq 1 30); do
    if port_alive "$api_port" "/api/runtime/client-config" && port_alive "$frontend_port" "/login"; then
      say "✓ 全栈就绪：http://localhost:$frontend_port （请用 localhost 访问）"
      say "  验收数据与流程：docs/local-e2e-acceptance.md「浏览器手动验收」（数据用 scripts/dev/acceptance_data.py prepare 生成）"
      say "  注意：worker 在位——「下一步：资料处理」与「生成报告」会真实消耗模型调用。"
      return
    fi
    sleep 2
  done
  die "就绪超时；查看 $log_dir/*.log"
}

cmd_status() {
  otlp_status
  for name in backend material-worker frontend; do
    local_pid_file="$pid_dir/$name.pid"
    if [[ -f "$local_pid_file" ]] && kill -0 "$(cat "$local_pid_file")" 2>/dev/null; then
      say "✓ $name 运行中 (pid $(cat "$local_pid_file"))"
    else
      say "✗ $name 未运行"
    fi
  done
  port_alive "$api_port" "/api/runtime/client-config" && say "✓ 后端 :$api_port 响应正常" || say "✗ 后端 :$api_port 无响应"
  port_alive "$frontend_port" "/login" && say "✓ 前端 :$frontend_port 响应正常" || say "✗ 前端 :$frontend_port 无响应"
  port_alive "$supabase_api_port" "/auth/v1/health" && say "✓ Supabase 栈 :$supabase_api_port 响应正常" || say "✗ Supabase 栈 :$supabase_api_port 无响应"
}

cmd_down() {
  for name in frontend material-worker backend; do
    stop_one "$name"
  done
  say "✓ 已全部停止（本地 Supabase 栈由你自行管理，未触碰）"
}

case "${1:-}" in
  up) cmd_up "${2:-}" ;;
  status) cmd_status ;;
  down) cmd_down ;;
  *) sed -n '5,22p' "$0"; exit 1 ;;
esac
