// ABOUTME: Next.js 启动/构建前加载 .env 并执行 Supabase 项目防误连检查。
// ABOUTME: 只读取公开 URL 与环境名称，不输出 anon key 或任何服务端密钥。
import nextEnv from '@next/env'

import { assertFrontendEnvironment } from './runtime-environment.mjs'

const { loadEnvConfig } = nextEnv
loadEnvConfig(process.cwd())
assertFrontendEnvironment({
  environment: process.env.SUSTAINABILITY_DESK_ENVIRONMENT || 'local',
  project: process.env.SUSTAINABILITY_DESK_SUPABASE_PROJECT || 'sustainability-desk-local',
})
