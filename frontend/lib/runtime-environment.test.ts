// ABOUTME: App 构建环境边界测试：本机栈必须声明 sustainability-desk-local，生产必须显式声明项目。
// ABOUTME: 测试直接消费构建前脚本的同一断言，避免检查逻辑分叉。
import { describe, expect, it } from 'vitest'

import { assertFrontendEnvironment } from '../scripts/runtime-environment.mjs'

describe('frontend runtime environment', () => {
  it('accepts the local stack project', () => {
    expect(() => assertFrontendEnvironment({ environment: 'local', project: 'sustainability-desk-local' })).not.toThrow()
  })

  it('rejects a local build that declares another project', () => {
    expect(() => assertFrontendEnvironment({ environment: 'local', project: 'shared-dev' }))
      .toThrow('本地 App 必须声明 sustainability-desk-local')
  })

  it('requires production builds to declare a project', () => {
    expect(() => assertFrontendEnvironment({ environment: 'production', project: '' }))
      .toThrow('生产 App 必须声明 SUSTAINABILITY_DESK_SUPABASE_PROJECT')
    expect(() => assertFrontendEnvironment({ environment: 'production', project: 'my-prod' })).not.toThrow()
  })
})
