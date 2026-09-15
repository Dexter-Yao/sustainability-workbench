<!-- ABOUTME: 本仓库的 Agent 规则：文档归属、当前形态、建模原则与硬约束。 -->
<!-- ABOUTME: 面向零前置上下文的接手者——先读本文，再读 docs/architecture.md。 -->

# 项目级规则

## 这是什么

可持续发展（ESG）报告编制工作台，本机单用户形态。用户填企业信息、做议题重要性评分、
填定量指标、答议题问题、传资料，系统**分章节生成正文**，人工逐段修订后导出 Word。

支持三套准则：上交所（简体）、港交所（繁體 / 英文）。准则与语言由**知识包**承载，
一包一准则一语言，代码不按准则分支。

主链与运行时阶段见 `docs/architecture.md`；安装与运行见 `SETUP.md`。

## 文档定位

- 本文件只记录本仓专属约束，不重复通用编码规则。
- 根目录 `AGENTS.md` 与 `CLAUDE.md` 必须文本一致；修改后运行 `cmp AGENTS.md CLAUDE.md`。
- 长期文档只有下列几份，不新增目录导航型文档或 index；每份只负责一类事实：

| 文档 | 唯一负责的事实 |
| --- | --- |
| `docs/architecture.md` | 主链、两条约束、知识包与运行时阶段（零上下文入口） |
| `docs/schema-contract.md` | 数据契约：SSOT 路径、核心对象、议题合同、定量数据表、显隐与持久化边界 |
| `docs/context-engineering.md` | 生成上下文工程：模型可见边界、装配流程、Prompt 分支、控制流与观测合同 |
| `docs/topic-construction-guide.md` | 逐议题构建规程与验收门 |
| `docs/account-system.md` | 账户、认证身份、权益 Grant 与报告范围 |
| `docs/handbook/` | 用户手册：ESG 通识、术语、议题总表（不含逐页操作步骤） |
| `design.md` | 视觉、交互与页面语义 |

- 过程性 spec 只在仍需评审或执行期间存在；实施完成后并入上述文档后删除。
- **真实企业资料一律不入库。** 仓库内的公司资料全部是合成语料（晟原、晉澧两家虚构公司）。

## 当前形态

- **本机单用户**：一个权益档 `local_single_user@1`，无注册、无云端、无付费分级。
  界面没有注册页，第一个账号用 `make provision-owner` 建（见 `SETUP.md`）。
- **生成模型**可换：默认走 Azure OpenAI，也可用任何 OpenAI 兼容服务
  （`backend/.env.example` 的 `OPENAI_COMPAT_*`）。注册表见 `llm/model_registry.py`，
  密钥只以环境变量名登记，绝不写值。
- **技术标识是 `sustainability_desk`**（Python 包名、`SUSTAINABILITY_DESK_` 环境变量前缀、
  `sustainability_desk.*.vN` 契约串），刻意与品牌无关，任何情况下不从产品名派生。
  用户可见名 **Sustainability Workbench** 收敛在三个出口：
  `frontend/lib/product-name.ts`、`backend/src/sustainability_desk/contract/product_name.py`、
  各知识包 `format_profile.yaml` 的 `footer.provider_name` / `footer.repository_url`。
  再改名只改这三处。
- **在售三包**：`sse_zh_hans`、`hkex_zh_hant`、`hkex_en`；港交所两包是同一骨架的两种语言
  （`tests/test_hkex_package_twins.py` 守护）。包内议题、准则条款与版式参数是产品资产，
  不按「待翻译」处理。
  **封存包**（`package.yaml` 的 `sealed: true`）留在仓库并继续受编译审计守护，但建报不可选；
  当前封存 `gri_en`。**它若解封须走 with reference 路线**：编制依据只能说「参考」，
  写成 in accordance 的「依据…编制」即越界合规主张——覆盖正文、界面与审阅稿文案。

## 验证

- `make verify`：后端 pytest + 前端 test/lint/build。**必须先 `supabase start`**——
  栈没起时持久化用例走 `pytest.skip` 静默跳过，你会看到全绿但数据库层一条没验过。
- 后端 `uv run --project backend ruff check src tests` 不在 verify 内，需单独跑。
- 守护测试：`test_doc_reference_integrity.py` 检查根目录与 `docs/` 全部文档的路径与标识符
  （受检清单从文件系统枚举，新增文档自动纳入）；`test_schema_baseline.py` 断言 schema 只有
  一份基线；`design.md` 的 § 编号被代码注释引用，压缩内容不得改编号。
- 合成语料的无头校验：`uv run --project backend pytest tests/test_local_e2e_fixture_corpora.py`
  ——拿内置语料跑通产品自身的输入链路并渲染出 Word，不调用模型。

## 建模原则

以下三条统领实现取舍；下节「硬约束」是它们在具体链路上的展开，冲突时以本节为准。

- **Parse-First**：低结构输入在入口或阶段边界解析成携带业务判断的领域对象，下游直接消费类型
  而非重新解释原始形态。判据：业务分支依据的是字段类型还是字符串子串？后者即未完成解析。
  已达标的范式：`material/intake/parsers.py`、`material/intake/routing.py`、`assets/*_parser.py`。
- **Agent-readable**：模型——既包括产品内的 LLM，也包括正在改本仓库的 coding agent——面对的是
  从权威事实派生的任务视图，不承担底层实现细节、坐标计算或嵌套编码格式。
  已达标的范式：`table_schema.py` 把 rowSpan/占位格/行序完全隔离在模型视野外；
  `prompts.py` 的列规格只露 header 与业务提示，不露列 key 与内部结构。
- **Harness**：确定性转换与验证留在代码侧，模型只做判断、取舍与解释；偏航时靠 trace 停止，
  而不是不断增加局部补丁。判据：新增一条规则时，问它是**这条链路的结构问题**还是**这个议题的
  内容问题**——前者进代码，后者进配置。词面黑名单只用于安全、合规与业务红线。
  已达标的范式：`observability/{registry,stages,stage_trace}.py`——阶段与实现同址声明、
  四条运行期不变量、必经阶段缺失即阻断（产出静默缺失比失败更危险）。

上述「已达标范式」是改动时的参照标准，不是改造对象。

## 本项目硬约束

- Report / Section / Block Schema 是业务真相源；报告正文页的文档投影与块级编辑动作只是受控投影。
  任何填写、生成、编辑、诊断与导出都必须能回写或读取结构化 `Report`，不得把投影或编辑日志当真相源。
- 范围投影（`report_execution_scope`）的**收集侧与报告侧是两套口径，不得混用**：`collects_*`
  决定用户能否填写并落库，`includes_*` 决定该事实是否进入报告装配与交付物。凡按范围裁剪
  「允许写入的集合」时，必须用报告侧口径重建 Report——让只作展示的输入参与装配，会使章节塌缩、
  已生成的块被判成范围外，用户随即卡在自己无法修正的 403 上。
- **校验与失效判定必须区分「用户没做」与「系统变了」，且不得让用户为系统的变化买单。**
  指纹只覆盖会使既有答案失效的事实（企业边界、报告期间），不覆盖目录增减与版本号；未作答不是错误，
  只有「作答了却没说清填的是什么」才是。把合同版本或指标目录算进定量指纹，会让全部存量报告在
  合同升级当天判 `stale` 被导出闸拦下，且用户无自助修复路径。
- **提议处理存量数据前，先数出受影响的条数再决定做不做。**
- Word 导出保真是一级风险，必须作为独立合同验证；不得依赖开放式编辑器导出能力。
- LLM 上下文边界必须保持：红字元指令、内部字段、路径、provenance、debug、raw、source refs、
  评分原始结构不得进入 prompt 或最终 Word 正文。
- 用户可见文本边界与 LLM 上下文边界同级：HTTP 错误响应、200 响应里的失败原因字段与界面提示，
  一律只承载稳定 `code` 与代码侧生成的文案；account_id、report_id、对象路径、上游原始响应体、
  SQL 约束名与 profile_id 只进日志和 trace。**异常消息不是用户文案来源**——`detail=str(exc)`
  会把「异常消息」隐式变成用户契约。防护见 `backend/tests/test_api_error_contract.py`。
- 批量 LLM 运行默认低粒度并发；公司/模型、章节、block、表格行应尽可能 fan-out，真实 LLM 并发
  由全局信号量封顶。不完整 trace 不得冒充完整覆盖。
- 用户已明确授权的目标生成按既定流程执行；为调查或复现新增的重复生成、批量调用必须先说明模型、
  预计调用规模、目的与可跳过性并获得确认。
- 模型内容调查先读 `sustainability_desk.ai_observability.v3` 的本地 JSONL 核对当次完整
  `ModelContext`、实际提示词、SDK 消息历史、结构化输出与 Guardrail 判定；阶段级归因读同名
  `{run_id}.stages.jsonl`。观测轨迹用于复现和归因，不是报告当前正文或人工结论的真相源。
- 用户资料或结构化答案缺失是一种生成分支，不称为 fallback，不作为故障语义处理。
- 前四章、议题章节、附录是不同建模面；不得为了复用而混成单一工作纸或单一 schema 形态。

## 调查与建模纪律

- **报告实际产出了什么内容，先查 trace，不在代码里推演。** 合同只说明可能性，trace 才是当次事实；
  二者不一致时以 trace 为准。轨迹在观测根 `ai-observability/<日期>/{run_id}.jsonl`（阶段事实同名
  `.stages.jsonl`）。**运行为何停在某一步，先读该次 stages 轨迹的阶段状态与属性。**
- **查库前先读 schema，不凭印象写表名与列名。** 臆测表名最伤：轮询里查询异常退出会被当成
  「尚未结束」——**静默失败会伪装成运行中**，监控脚本必须能区分「条件未满足」与「查询本身出错」。
- 引用具体事实前，当场读取对应真相源；不得凭记忆推断列名、章节归属、条款范围或模板内容。
- 先框定范围再动手；不默认全量、不擅自扩展到未确认议题。
- 先区分业务概念，再命名或合并字段；不得因字段名相似就视为同一数据链路。
- 英文标识应由真实中文名规范派生；避免 generic、new、old、legacy、wrapper、enhanced 等弱语义命名。
- **新写代码的注释与 docstring 用英文；存量中文注释不单独翻译**，随语言的系统性转换一并处理。
  理由：只翻注释会造出「英文注释指着中文标识符和中文 YAML」的三语混合，比现状更难读。
  模块头的 `# ABOUTME(en):` 已中英并列，是外来者定位职责的入口。注意 `backend/src` 里约 1900 行
  中文出现在**代码字符串**而非注释中（守卫模式、错误文案、prompt 正文），改动即改行为。
- 触及 SSOT、公开 API、生成契约、导出契约或数据迁移时，先给出具体改动文本并等待批准。
- 结论必须可追溯到文件路径与必要行号；建模决策必须有明确依据。
- **上交的决策问题必须自带证据链。** 给不出文件路径与行号就说明调查尚未完成，继续查，不得上交。

## 前端技术约束

- 本项目 Next.js 版本存在破坏性变化；修改 `frontend/app` 路由、页面、Next 自身的 API（next/navigation、next/font 等）或 Next 配置前，
  必须读取 `frontend/node_modules/next/dist/docs/` 中对应指南，并遵守弃用提示。
- **视觉改动必须在本机 `localhost` 上看过截图再提交。** 不据裸 DOM 判断版面。
- **界面文案一律走字典**（`frontend/lib/i18n/{zh-Hans,en}.ts`），组件内不写字面量文案。
  `dictionary.test.ts` 守护中英键集对等且英文字典不含汉字。
- **口径类的全局替换，扫描范围必须含 `public/` 且不限文件类型。** 用 `git grep -il` 扫跟踪文件全集。

## 推送前验证

- `hooks/pre-push` 在每次 `git push` 前跑通 `make verify` 全链路，任一段失败即中止推送。
  新 clone 后执行 `make install-hooks` 恢复（等价于 `git config core.hooksPath hooks`）。
- **LibreOffice 是导出的运行时硬依赖，不只是验收工具。** `export/toc.py` 的
  `finalize_toc_page_numbers` 在每次导出末尾无条件调用：Word 目录域的页码要靠排版引擎跑一遍分页
  才算得出，python-docx 不做排版。缺 `soffice` 直接 `TocFinalizationError`。移除它等于交付物
  没有目录页码，是产品决策而非依赖清理。
- **钩子先断言数据库与 LibreOffice 前置，不满足就拒绝推送，这是刻意设计。** 持久化用例在本机
  Supabase 栈未启动时走 `pytest.skip`，Word 导出的视觉验收用例在缺少 `soffice` 时走 skipif；
  二者缺失时 pytest 不报错、只把用例跳过，全绿结果会掩盖「持久化与导出从未被验证」。
  前置不满足时先 `supabase start` 或装 LibreOffice，不要绕过。
