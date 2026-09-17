# ABOUTME: 本地开发与验证的统一入口，保持各子项目原生工具链。
# ABOUTME: 日常开发连接本机 Supabase 栈（sustainability-desk-local）；生产环境不得通过这些目标启动。

.PHONY: install-hooks doctor supabase-up supabase-down dev-backend dev-worker dev-frontend verify provision-owner preflight-test-baseline provision-test-accounts

install-hooks:
	@bash scripts/dev/install-hooks.sh

doctor:
	@bash scripts/dev/doctor.sh

# 起本机 Supabase 栈，并排除本产品用不到的三个服务（共约 900 MB 镜像）：
#   postgrest — 全仓零 /rest/v1 调用，后端一律 asyncpg 直连
#   mailpit   — 从不发信：首个账号由 provision_owner_account 以 email_confirm=True 建，
#               且 config.toml 的 enable_confirmations=false
#   realtime  — 已在 config.toml 关闭（前端只用 supabase-js 的认证部分）
#   storage-api — 私有对象默认存本机磁盘（persistence/local_storage_transport.py）；
#               产品对它的全部用法只有写、读、删三件事，文件系统本来就做。
#               要把对象放回 Supabase：清空 SUSTAINABILITY_DESK_LOCAL_STORAGE_ROOT
#               并从下面的排除项里去掉 storage-api。
# 排除项是 `supabase start` 的参数而非持久化配置，故必须走这个目标；
# 裸敲 `supabase start` 会把它们又拉起来。
supabase-up:
	@supabase start -x postgrest,mailpit,storage-api

supabase-down:
	@supabase stop

dev-backend:
	@cd backend && SUSTAINABILITY_DESK_ENVIRONMENT=local SUSTAINABILITY_DESK_SUPABASE_PROJECT=sustainability-desk-local uv run uvicorn sustainability_desk.api.app:app --host 127.0.0.1 --port 8010 --reload

# 资料处理与报告生成都是 Postgres 队列，由本目标的独立进程消费：不启动它，
# 「下一步：资料处理」与「生成报告」会永远停在等待中（API 进程自身不跑生成）。
dev-worker:
	@cd backend && SUSTAINABILITY_DESK_ENVIRONMENT=local SUSTAINABILITY_DESK_SUPABASE_PROJECT=sustainability-desk-local SUSTAINABILITY_DESK_SERVICE_ROLE=material-worker uv run python -m sustainability_desk.material.agent_worker

dev-frontend:
	@cd frontend && npm run dev

verify:
	@cd backend && uv run pytest -q
	@cd frontend && npm test && npm run lint && npm run build

provision-test-accounts:
	@cd backend && uv run python -m sustainability_desk.ops.bootstrap_internal_accounts --registry data/test_accounts.yaml $(ARGS)

# 用自己的邮箱建立首个可登录账号（认证栈关闭公开注册，新环境的第一个账号只能这样建）。
# 默认 dry run；写入需 ARGS="--email you@example.com --apply" 并设
# SUSTAINABILITY_DESK_OWNER_PASSWORD 与 SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES。
provision-owner:
	@cd backend && uv run python -m sustainability_desk.ops.provision_owner_account $(ARGS)

preflight-test-baseline:
	@cd backend && uv run python -m sustainability_desk.ops.test_baseline_preflight --registry data/test_accounts.yaml
