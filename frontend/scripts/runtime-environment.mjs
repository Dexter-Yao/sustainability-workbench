// ABOUTME: App 构建的环境边界，只校验 release 声明的环境与项目。
// ABOUTME: 浏览器认证地址在运行时由同源 API 发布，构建期不得另存一份 NEXT_PUBLIC Auth 配置。
export function assertFrontendEnvironment({ environment, project }) {
  if (environment === 'production') {
    if (!project) throw new Error('生产 App 必须声明 SUSTAINABILITY_DESK_SUPABASE_PROJECT')
    return
  }
  if (environment === 'local' && project !== 'sustainability-desk-local') {
    throw new Error('本地 App 必须声明 sustainability-desk-local')
  }
}
