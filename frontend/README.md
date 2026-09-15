<!-- ABOUTME: 前端最小运行说明，避免默认 Next.js 模板误导后续代理。 -->
<!-- ABOUTME: 具体项目规则以根目录 AGENTS.md 为准。 -->

# Frontend

```bash
cd frontend
npm install
npm run dev
npm run test
npm run lint
npm run build
```

浏览器 E2E 默认只运行匿名只读烟测：

```bash
npm run test:e2e
```

提供 `SUSTAINABILITY_DESK_E2E_EMAIL` 与 `SUSTAINABILITY_DESK_E2E_PASSWORD`（本机受控测试账号，见 `backend/data/test_accounts.yaml`）后，会额外运行登录态链路。可选的 `SUSTAINABILITY_DESK_E2E_SYNTHETIC_REPORT_ID` 必须指向专用合成报告；测试会阻断业务写入、模型调用与导出。目标页面实际使用的认证与 API origin 分别由 `SUSTAINABILITY_DESK_E2E_AUTH_ORIGIN`、`SUSTAINABILITY_DESK_E2E_API_ORIGIN` 显式声明，避免测试进程的本地环境与受测构建漂移。远程目标还需设置 `SUSTAINABILITY_DESK_E2E_BASE_URL`，并在确认目标是受控测试环境后显式设置 `SUSTAINABILITY_DESK_E2E_ALLOW_REMOTE_LOGIN=1`。认证建立项目不生成 trace、视频或截图，避免凭据进入测试产物。

涉及 Next.js API、路由或页面约定时，必须按根目录 `AGENTS.md` 要求读取本地 `node_modules/next/dist/docs/` 对应指南。
