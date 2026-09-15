<!-- ABOUTME: 账户、权益与报告范围的领域合同：本机单用户模式下谁拥有账号事实、权益如何投影为能力、报告范围如何派生。 -->
<!-- ABOUTME: 本文只定义事实 owner 与边界；可执行值以 backend/data/entitlement_profiles.yaml 与 accounts/ 代码为准。 -->

# 账户体系设计

## 1. 目的与边界

本文界定账户、认证身份、权益 Grant 与报告范围四类事实的 owner 与投影规则。当前形态是**本机单用户模式**：
一个本机 Supabase 认证栈、一个权益档位、由后端命令建立的账号；不含公开注册、邮箱或手机号验证、协议同意、
支付、计费、多租户与组织级权限。恢复多用户能力时，这些须作为独立能力重新设计，不从本文复原。

## 2. 事实 owner

| 事实 | owner |
| --- | --- |
| 产品账号 | `accounts`（邮箱、组织名、状态、引导已读） |
| 认证身份到账号的映射 | `account_identities`（`identity_issuer='primary'` + 认证主体 id） |
| 当前及历史权益 | `account_entitlement_grants`（每个账号只有一条未结束 Grant） |
| 账号级审计事件 | `account_events` |
| 内部运营权限 | `account_operator_permissions`（当前只有 `internal_audit_reviewer`） |
| 权益档位的可执行合同 | `backend/data/entitlement_profiles.yaml`，经 `accounts/entitlement_profiles.py` 解析 |

权益档位不推导 `data_classification`——后者是「这份报告里实际是什么数据」的事实断言，由建报时显式声明。

## 3. 认证与账号建立

- 认证只有邮箱加密码，由本机 Supabase 认证栈签发 JWT；后端按 `SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET`
  自行校验，不回调认证服务。
- 账号只由 ops 命令建立，有两个**互不混用**的出口，各自创建认证身份、`accounts` 行、身份映射与
  初始 Grant 并写 `account_events`：
  - `ops.provision_owner_account`：产品持有人**自己的账号**，邮箱由调用方 `--email` 给出，
    不进任何注册表文件。认证栈关闭公开注册，故新环境的第一个可登录账号只能由本命令建立。
    Grant 的 `granted_by` 为 `provision_owner_account`，与内部测试身份可区分。
  - `ops.bootstrap_internal_accounts`：**内部受控测试身份**，按 `backend/data/test_accounts.yaml`
    建立，角色是封闭枚举（见 §6）。
- 两条命令都默认只报告目标，写入需显式 `--apply`；`provision_owner_account` 另需
  `SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES`。密码只经环境变量注入单次进程，不落文件；
  测试身份的密码本机保存在 macOS Keychain，持有人账号的密码由持有人自行保管。
- 已存在的身份一律复用：不重置密码、不降级现有 Grant。
- 认证配置关闭公开注册与邮件确认（`supabase/config.toml`）。界面没有注册页，这是刻意设计。

## 4. 权益与能力投影

当前只有一个档位 `local_single_user@1`，字段仅两项：

| 字段 | 含义 |
| --- | --- |
| `active_report_limit` | 账号可同时保留的活跃报告数；达限时列表页预先置灰「新建报告」 |
| `section_regeneration_limit` | 单份报告每个章节的重写额度 |

报告形态（章节集合、交付物种类、资料 Agent、Word 导出）在单档模式下是常量，由
`accounts/report_execution_scope.py` 的 `execution_scope_for_profile()` 拥有，不在档位里重复声明。

能力只经 `AccountContext.capabilities()` 与 `report_capabilities()` 投影给 API 与前端：Grant 过期或账号
非 active 时生成、重写、导出与资料 Agent 一律关闭，已有内容仍可查看与编辑（`can_edit_existing`）。
前端不得从档位 id 或范围类型反推能力。

Grant 变更只经 `accounts.grants.grant_profile` 写入（显式结束当前 Grant、创建新 Grant、写账户事件）；
当前没有面向用户的开通、续期、撤销或注销动作。

## 5. 报告范围

`EffectiveReportScope` 不是新业务实体：它由权益档位派生，声明当前报告可执行的输入、资料、生成与
交付边界。单档模式下范围恒为 `full_simplified`：全部轻量版章节、Word 与审阅稿两种交付物、
评分收集与写入报告、附录与利益相关方沟通事实全部开放。`project_report()` 是范围裁剪的唯一出口；
新增受限范围时只在能力表增行，不在消费端加分支。

`reports.created_under_profile_id` 记录建报时的档位，`report_profile_id` 记录报告产品 Profile
（当前恒为 `sse_zh_hans@1`），两列取值不同是预期：前者归权益，后者归报告语义。

## 6. 测试身份

测试身份只由 `backend/data/test_accounts.yaml` 登记：`internal_automation` 承载自动 E2E 与数据清理，
`internal_manual` 供人工完整路径验收。两者都授予 `local_single_user@1`。`ops.clear_test_report_data`
只清理注册表内账号名下、`data_classification=synthetic` 的报告。

## 7. 未来扩展的约束

若引入多用户、Workspace、成员权限、支付或配额引擎：账号与身份映射保持现有 owner；权益字段只增不改语义；
报告范围继续由权益派生而非客户端指定；注册、验证与同意留痕作为独立能力设计，并把当前档位作为迁移起点。
