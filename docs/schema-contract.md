<!-- ABOUTME: 报告 schema 契约索引；定义稳定领域语义、SSOT 路径和当前轻量版议题问题合同。 -->
<!-- ABOUTME: 可执行模型以 backend/src/sustainability_desk/contract/models.py 为准；本文只保留跨模块必须共享的契约。 -->

# Schema Contract

## 定位

本文是长期维护的 schema 契约索引，回答三个问题：

1. 哪些文件是事实源。
2. 哪些对象和字段语义不能漂移。
3. 轻量版议题问题、正文块、ESG 定量数据表如何连接。

可执行 schema 以 `backend/src/sustainability_desk/contract/models.py` 的 Pydantic 模型为准；YAML 是数据实例；上下文工程见 `docs/context-engineering.md`。

## SSOT 路径

| 语义 | SSOT |
| --- | --- |
| Pydantic 数据模型 | `backend/src/sustainability_desk/contract/models.py` |
| 报告产品 Profile 与知识包绑定 | `backend/data/report_profiles.yaml`（`knowledge_package` 字段） |
| 知识包清单（准则框架 × 语言，`id`/`language`/`framework`/`pillar_titles`/`disclosure_basis`） | `backend/data/knowledge_packages/<package_id>/package.yaml`（现有 `sse_zh_hans`、`hkex_zh_hant`、`hkex_en`、`gri_en`） |
| 语言约定（长度单位、月份显示、列表分隔、非实质答案词表、Word 语言标签） | `backend/src/sustainability_desk/contract/language.py` |
| 知识包加载与报告→包解析 | `backend/src/sustainability_desk/contract/knowledge_packages.py` |
| 报告固定骨架 | `backend/data/knowledge_packages/<package_id>/report_contract.yaml` |
| 评分议题、报告 H2、报告 H1 模块及其关系 | `backend/data/knowledge_packages/<package_id>/topic_registry.yaml` |
| 利益相关方类型、沟通方式目录与默认议题映射 | `backend/data/knowledge_packages/<package_id>/stakeholder_engagement.yaml` |
| 议题固定问题模板 | `backend/data/knowledge_packages/<package_id>/topic_intake_common.yaml` |
| 议题个性化 IRO 问题 | `backend/data/knowledge_packages/<package_id>/topic_intake/<topic>.yaml` |
| 议题章节、block、table、generation inputs | `backend/data/knowledge_packages/<package_id>/topic_sections/<topic>.yaml` |
| ESG 定量指标目录 | `backend/data/knowledge_packages/<package_id>/quantitative_metrics.json` |
| 上下文投影规则 | `backend/src/sustainability_desk/llm/prompts.py` |
| 报告生成 Prompt Profile（每包一份，`profile_id` = 包 id） | `backend/data/knowledge_packages/<package_id>/prompt_profile.yaml` |
| Prompt Profile 类型与兼容性 | `backend/src/sustainability_desk/llm/prompt_profiles.py` |
| Word 格式 Profile（每包一份，`profile_id` = 包 id，`language` = 包语言） | `backend/data/knowledge_packages/<package_id>/format_profile.yaml` |
| 准则披露要求映射 | `backend/data/knowledge_packages/<package_id>/standard_disclosure_requirements/<topic>.yaml` |
| 准则要求覆盖审定（人工审定的承载处置） | `backend/data/knowledge_packages/<package_id>/standard_disclosure_requirement_coverage.yaml` |
| 报告级披露义务（指南第一号结构性与流程性义务） | `backend/data/knowledge_packages/<package_id>/report_level_disclosure_obligations.yaml` |
| 准则披露覆盖判定 | `backend/src/sustainability_desk/contract/disclosure_coverage.py` |
| 持久化数据合同 | `supabase/migrations/` 下的单份基线 |
| 资料工作区领域合同与报告写入适配 | `backend/src/sustainability_desk/material/intake/`、`backend/src/sustainability_desk/material/input_adapter.py` |
| Account、权益与报告范围合同 | `docs/account-system.md` |
| 契约版本标识 | `backend/src/sustainability_desk/contract/contract_version.py` |
| 确定性合同编译与关系索引 | `backend/src/sustainability_desk/contract/compiled_definition.py` |
| 合同审计 | `backend/src/sustainability_desk/contract/audit.py` |

原则：SSOT 不复制。引用必须使用与实体一致的 ID：评分输入用 `assessmentTopicId`，报告章节用 `reportSectionId`，内容清单用 `contentScopeId`；展示文本在加载期或投影时解析得到。

### CompiledReportDefinition

`CompiledReportDefinition` 是上述 authoring sources 的深度只读编译快照，不是新的 YAML、数据库实体或报告树。编译器按固定骨架、议题注册表、内容清单、议题章节、指标目录和准则要求的顺序建立稳定节点身份、父子位置、输入消费者、指标消费者、显隐合同、生成合同和议题关系；准则要求也必须先通过严格 Pydantic authoring 合同，内部 `<ref>` 标记在编译边界移除。未知引用、无效显隐路径、无效准则形状和跨议题准则引用一律 fail-closed。`load_compiled_report_definition()` 是生产唯一入口：先编译，再以 `ContractAudit` 阻断 `error` finding；Planner、生成、诊断和正文上下文都读取该有效定义，不再各自反向遍历并猜测关系。需要构造运行态 `Report` 时只能从快照复制出独立可变实例，不能原地修改编译缓存。

确定性检查分两层：严格 loader/compiler 在形成定义前拒绝无效 YAML、类型、引用、表格和标题生产者；`ContractAudit` 再审计已经成功编译的跨节点关系、consumer、共享证据职责和重复确定性披露。前者失败不会伪装成 audit finding，后者的 `error` 使生产 loader 失败；需要业务裁决的 `review` 由 owner 合同或回归测试消除，不用中央 allowlist 长期压制。`contract_version` 仅标识 authoring 文件内容；`compiled_semantics_version` 单独标识 compiler、支柱语义与缺失行为的解释版本，二者不得互相冒充。


## 核心对象

### Report

内容层 `Report` 是一次报告实例；产品实体 `reports` 的 Account 归属、`report_type` 与权益语义见 `docs/account-system.md`，不在本文重复定义。

- `fields`：报告主体字段，如公司简称、行业、主营业务。
- `intakeItems`：用户围绕议题填写的问题与答案。
- `sections`：报告章节树。
- `meta.quantitativeMetrics`：用户在 ESG 定量数据表中的填写值。
- `disclosureProfile`：报告内容的准则与披露配置；它不是产品实体的 `reports.report_type`。
- `assessmentInput`：用户实际提供的评分、阈值、报告年度与可选 IRO；只保存 `scored` 议题，不重复名称、维度、H2 映射、固定分类或计数。
- `assessment`：Resolver 每次从 `assessmentInput + topic_registry.yaml` 现算的判别联合结果；`scored` 成员保留分值，`fixed` 成员只保留固定重要性。矩阵只投影 `scored`，结果表与计数投影完整结果。
- `stakeholderEngagement`：利益相关方沟通的唯一可写真相。`scopeAssessmentTopicIds` 记录上次范围协调时的适用评分议题集合；八个固定顺序的 `entries` 保存利益相关方—评分议题多对多关系、受控方式 ID 和按类别保存的自定义方式。中文名称只由议题注册表和方式目录投影，不在 Profile 重复保存。
- `inputGuidance`：模板态的用户输入体验合同。以稳定配置路径为 key，按 design.md §2.2.1 分两段承载用户可见说明：`helpText`（≤60 字）只解释如何填写并常驻页面，`termExplanation`（≤80 字）承载术语解释与准则背景并折进 ⓘ；`defaultRule` 只在新建报告时推导可编辑初值。三者都不进入报告正文、用户状态快照或 `ModelContext`。两段文本直接写给用户看，不得使用「用户……」这类第三人称或作者视角措辞。当前默认规则只覆盖报告年份及其自然年起止，说明路径可覆盖基础信息、重要性评分和定量指标页面的非议题输入。
- 说明文本的跨端一致性由投影保证而非人工同步：Excel 模板（基础资料、定量、议题问题）一律从同一份合同字段投影，Excel 无折叠形态时两段顺序拼接为一格；任何一端另写文案都会被 `test_workbook_guidance_column_is_projected_from_the_same_catalog_text` 拦下。
- `assessmentScoreScale`：模板态的双重重要性原始评分尺度，声明开闭区间与步长。Excel 导入、在线录入、上游输入与实例校验都从此尺度派生；得分只用于分类和矩阵，不进入 `ModelContext`。
- 动态评分模板是用户输入投影，不是第二份合同：下载时以科技伦理适用性筛选 `topic_registry.yaml`（唯一一条适用性规则），并以 `assessmentScoreScale` 填写说明与单元格校验。模板可含品牌说明区，但导入表必须有同一行的「议题 / 财务 / 影响」表头，名称仍精确匹配官方评分议题并完整覆盖当前适用清单。

### Field

`Field` 是报告字段定义及其当前值。

- `appears_when`：字段显隐条件；条件为真时才展示，`required` 也只在可见时参与阶段化输入门禁。
- `required`：用户字段是否为必要配置。全部 `source=user_input` 字段由 compiler 投影为输入义务；必要字段默认在进入工作台前完成，派生字段和模板字段不进入该索引。
- `consolidation_scope`：枚举单选（仅公司本部
  （无并表子公司）/ 母公司及全部并表子公司 / 特殊口径），配套条件字段 `consolidation_scope_note`
  （仅「特殊口径」时可见，一句话说明）。选项决定「关于本报告」披露范围段落的模板变体
  （`about.scope*` 六个 slot，按合并范围 × 有无简称互斥选中，行为合同见
  `backend/tests/test_about_scope_variants.py`）；未选择与枚举化前的历史自由文本值经 `ne` 条件
  落入默认「与合并财务报表口径一致」句，段落不消失。该字段同时是定量收资模板的只读口径说明
  与其上下文指纹成分（`note` 不参与，避免作废在途工作簿）。

  **定量指纹只覆盖使已填数值失效的事实**——企业边界与报告期间；不含合同版本、编译语义
  版本与指标目录清单。指纹回答「用户填的数还成不成立」，不回答「目录变没变」：新增一项
  指标不改变既有数值的口径，把目录算进指纹会让全部存量报告在合同升级当天变成 `stale`
  而被导出闸拦下，用户须回去对从没见过的指标逐个声明「不填」才能恢复。目录变更由完整性
  校验负责，且未作答不是错误——定量信息是选填页（`design.md` 裁定「整表留空＝暂不提交
  保持现状」），只有「作答了却既没填数值也没给无值原因」才是半完成状态。工作簿导入是例外：它是往返产物，行缺失意味着文件
  被改坏或传错，完整性由 `assets/quantitative_parser.py` 自行按目录判定。

### Section

`Section` 是报告结构节点。

- `key`：章节路径。
- `title`：稳定结构标题，不含自动编号；左侧导航、定位和动态标题失效回退始终读取该字段。
- `reportModuleId`：仅 H1 报告模块使用。
- `reportSectionId`：仅正式 H2 报告章节使用；不得存放评分议题 ID。
- `displayTitle`：实例级用户可见标题，保存 `text / origin / inputFingerprint`。正文预览、Word、Schema HTML、审阅 artifact 与 Judge 输入统一按 `displayTitle.text → titleContent → title` 解析。
- `titleGeneration`：H4 标题任务，只能引用该 H4 的直属段落生成块；标题与正文由同一次结构化输出成对产生。
- `blocks` / `children`：正文块和子章节。
- `appears_when`：章节显隐条件。

评分议题、报告 H2 与报告 H1 模块是三种实体。注册表只保存 `AssessmentTopic → ReportSection → ReportModule` 单向关系，加载后生成不可变反向索引；合并 H2 的成员维度与适用性必须一致。轻量版当前五个模块与 H2 成员由 YAML authoring contract 拥有，完整列表只作为测试快照守护，不形成第二条生产 owner。

每个适用 H2 都保留。财务重要性或双重重要性 H2 装配固定四要素 H3；影响重要性或非重要性 H2 只装配 H2 直属摘要，不创建 H3/H4。合并 H2 只要任一成员具有财务重要性即采用四要素结构。四要素分支中的独立段落单元可声明动态 H4；固定导语、表格和图片不承担标题生成。

### Block

`Block` 是最小生成和导出单元。

- `type`：结构类型，当前主要为 `paragraph`、`table`、`image`。
- `blockType`：内容确定性，`fixed`、`slot`、`constrained`、`generative`。
- `source`：事实来源，`template`、`user_input`、`derived`、`user_doc`、`assessment`、`ai`。
- `generation`：生成合同，只声明输入和约束，不直接读取 Report。
- `appears_when`：block 或 table row 显隐条件。
- `required`：只表示必须存在的产物结构或导出完整性，不表示普通资料是否充足。

`blockType` 只描述内容确定性，不拥有缺失资料时的产品行为。`fixed` 由合同确定性渲染，`slot`
读取结构化 Report 值；其余 Block 的 absence 行为由当前 `ReportProfile` 与显式生成合同共同决定，
不得从 `constrained` 或 `generative` 自动推导省略。轻量版适用 paragraph 缺少企业事实时进入
`generate_context_only`，形成审慎、概括、低承诺的公开报告表达，不把行业相关性、
主营业务背景或指标目录坐实为可核验的企业事实，也不得把正文写成面向企业的建议、行动方案或待办清单。`absence_behavior` 由内容执行方式**确定性派生**，不在来源合同里逐块声明
（`contract/compiled_definition.py`），两值互斥：`blockType ∈ {fixed, slot}` →
`render_deterministically`；其余一律 `generate_context_only`。即**没有任何块走「无事实即省略」**——
不得从 `constrained` 或 `generative` 自动推导省略，也不要以为无数据表格或缺值可选句会自动省略
（它们走 `generate_context_only`，由块自身合同表达空表/省略语义）。每个适用 Block 都必须留下
生成记录。

### Image

`ImageModel` 承载图片块的人类可见内容和确定性派生视觉。图片内容来源三选一、互斥：`evidenceAssetId`、`derivedVisualization`、`layoutAssetIds`（须 `layoutAssetSlot=true`）。

- `caption` / `placeholder`：人工图片或占位图的题注与占位说明。
- `derivedVisualization`：由结构化 `Report` 数据派生的图片规格；当前支持 `kind=quantitative_metric_summary`。
- `derivedVisualization.metricKeys`：本图允许读取的 ESG 定量指标 key，必须来自定量指标目录（单一目录，不分档）。
- `derivedVisualization.featuredMetricKeys`：当指标较多时优先展示为重点卡片的指标 key；未声明时按 `metricKeys` 顺序取前项。
- `derivedVisualization.displayMode`：视觉密度，`auto` 根据已填写指标数量选择突出卡片、紧凑卡片或卡片 + 明细表。
- `derivedVisualization.groupBy`：仅在明确设计分组图时使用；默认 `none`，普通指标摘要只展示末级稳定指标名称。
- `derivedVisualization.emptyBehavior`：全部指标无填写值时的行为；议题指标摘要默认 `hide`，避免导出空图。

派生视觉是导出 / 预览渲染合同，不是 LLM 写作合同。图内只展示报告年度、指标名称、值和单位；报告年度在整图中只出现一次，不展示 schema key、内部注释、解释性标签或支柱标题，支柱标题由 `Section.title` 自动渲染。

### IntakeItem

`IntakeItem` 是一道用户填写题。

- `key`：唯一键，必须稳定。
- `contentScopeId`：内容事实所属范围；正式议题工作纸通常等于 `reportSectionId`，但字段语义不再冒充评分议题 ID。
- `prompt`：面向用户的题干。
- `kind`：`text`、`single_select`、`multi_select`。
- `options`：选择题选项。
- `generationOptionLabels`：选择项到模型可见业务标签的受控映射。`Report.answer` 仍保存用户实际选择，`ModelContext` 只读取映射后的披露语义；用于内部业务表述与对外披露表述需要分离的场景，不用于关键词过滤。
- `optionGroups`：多选题的选项分组约束；当同一道题需要表达“每组至少选择 N 项”时使用，分组选项必须来自 `options`。
- `collectionPriority`：纯用户采集引导，取值为 `core | recommended | optional`。它只决定界面的优先提示，不拥有 block 生成、Journey、工作台或导出门禁。
- `requiredBefore`：仅在某项内容确实属于硬输入义务时声明，取值为 `workbench | generation | export`；
  不得从 `collectionPriority` 反推。轻量版首次生成只阻断服务端准备投影确认的企业注册名称、行业门类、
  报告期等最低身份信息；主要业务、重要性、定量信息、文件和普通内容清单均为可选增强信息。
- `hint`：用户可见填写提示（≤60 字），只解释如何填写并常驻页面，不承载“不得生成、不得编造、系统不得”等生成约束。
- `termExplanation`：用户可见的术语解释与准则背景（≤80 字），按 design.md §2.2.1 折进 ⓘ；与 `hint` 同为面向用户的文本，两者不得复述同一件事，也都不进入 `ModelContext`。
- `generationBoundary`：agent-readable 生成边界，用于描述该题答案在生成侧的使用边界；经当前 Evidence 选择器过滤后进入 System `<intake_generation_boundaries>`，不进入用户填写界面，也不作为用户已填写事实。
- `answer` / `supplement`：用户答案；选择题的补充说明必须作为事实进入生成上下文。

### CompiledInputObligation

`CompiledInputObligation` 是 compiler 从既有 authoring owner 生成的只读阶段索引，不是第二份必填清单，也不持久化用户值。用户字段由 `Field.required` 拥有，公司简介等内容项由 `IntakeItem.requiredBefore` 拥有，读者反馈联系方式由对应值字段上的 `ReportInputMetadata` 共址拥有；compiler 统一投影稳定目标、owner、值路径、可见条件和截止阶段，并拒绝重复目标或路径。工作台 readiness、正式生成门禁、导出诊断与资料 adapter 必须消费该索引；`missingContentPolicy`、资料是否命中和界面采集优先级均不能取消必要义务。

### MaterialWorkspace

`MaterialWorkspace` 是报告级来源、声明、Agent 运行、资料快照和映射结果的聚合边界，不是
`Report`、`StoredReportStateV4` 或 Plate 的组成部分。权威 owner 如下：

- `MaterialSource`（表 `material_sources`）保存不可变原文件身份、私有存储引用、格式、SHA-256 和
  准入事实；`UserFileDeclarationRevision` 保存说明文本（上传时可为空表示待补充，非空时 10–140 字；
  缺说明的 active 文件阻断报告生成）、`role`、用户标签及排版素材标题；二者的当前报告
  关系由 `ReportMaterialBinding` 拥有。用户声明是意图，不是企业事实。
- `ReportMaterialBinding` 使用 `active | removed | superseded` 表达当前关系。普通移出和恢复不删除
  原文件、Dossier、旧映射或旧报告 lineage；替换产生新的来源 revision。永久隐私删除是另一项
  未实现的权限与存储操作，不能复用移出接口。
- 资料集确认：`MaterialWorkspace` 持有 `material_set_confirmed_at` 与确认时 active binding 集
  （bindingId + 来源 sha256 + 声明 revisionId）的指纹。File Agent 只在用户显式确认（POST
  `/api/reports/{report_id}/file-intake/confirm`，说明未齐则 409）后统一入队；上传、改说明、移出、恢复不再各自触发分析。
  确认有效性为读取时派生（重算当前集合指纹比对），任何集合变更自动失效，无失效写路径；重新确认经
  file-agent 幂等键天然只重跑变化文件。生成资格同时受"资料确认"准备阻断项与
  `unfinished_file_agent_work()`（返回 `total` 与 `never_enqueued_binding_ids`）双层把守，
  零文件报告不受影响。
- 准入策略由服务端 `ReportFileIngressPolicy` 拥有并投影到前端：每报告最多 30 份 active 去重文件
  （`REPORT_FILE_MAX_COUNT`，语义资料与排版素材合并计数），单文件不超过 10 MiB，PDF 不超过 40 页且不可加密；语义资料为 PDF、DOCX、XLSX、PPTX，排版素材为
  PNG、JPEG、WebP 与单页 PDF（声明为排版素材的多页 PDF 拒收，须以语义资料上传；同一扩展名两种
  role 由前端声明区分）。上传或存储失败不计入 active 上限。重复 SHA 不创建第二份资料，也不静默覆盖
  用户新填写的声明。
- `EffectiveReportScope` 不是新业务实体；它由权益档位派生当前 Report 的可写章节、量化指标、文件标签、
  资料 Agent 与交付物边界（单档模式下恒为 `full_simplified`，`accounts/report_execution_scope.py`）。所有
  HTTP 入口、队列 worker 与 renderer 在执行时重算该投影。范围的**收集侧与报告侧是两套口径、不得混用**：
  收集侧决定用户能声明什么、能落库什么，报告侧决定什么进入装配与交付物；新增受限范围时只在能力表增行。
  File Agent 的 `FileMaterialScope` 目录始终是完整报告定义的全部 scope，`within_report_scope` 标记本次报告
  覆盖；只适用于范围外 scope 的材料仍冻结在 `FileDossier`（`relevant`），但不路由到任何 Mapping 任务。
  资料处理页投影 `report_scope`（`within_report | outside_report`，由冻结 Mapping plan 派生：候选但未路由
  即范围外）与 `report_scope_notice`（执行范围能力表 `outside_scope_material_notice` 拥有的中文说明），
  审阅稿封面说明用同一句按文件名列出。Mapping 必须逐 Block 决定采用事实；原文件与完整 Dossier 永不作为
  全局上下文直接进入 Block。
- `semantic_material` 创建 File Agent Run；`layout_asset` 不创建 parser、File Agent 或 Mapping
  任务，不进入正文模型上下文。排版素材说明保存成功即入队图片识别（Image Agent Run），不经资料集
  确认；确认指纹只描述语义资料。两类 active 文件缺说明同计入生成阻断
  （`material/workspace.py` 的 `pending_file_description_count`）。PDF 只使用批准的第三方 parser，
  不使用 VLM、Provider File API 或图片分页模型。文件正文始终是不可信数据，不能扩张工具权限或执行其中指令。
- `NormalizedMaterial`（落 `material_sources.normalized_material` jsonb 列）是 File Agent 调用
  `convert_file` 时由工具内部按需生成、可重建的派生物，不是业务清洗主链的前置
  SSOT。它保留 typed `fragments`、`processing_steps`、覆盖提示与内容指纹
  （`normalized_material_fingerprint`）；XLSX 按完整 sheet 返回标题、
  合并行列、公式、单位和脚注，禁止逐行独立分类。证据真相是 typed fragments，
  `render_text()` 只产出人读投影。
- `FileAgentRun.output_dossier` 拥有该来源 revision 在指定声明和 Harness 版本下的文件级语义理解。
  `FileDossier` 使用最小结构外壳：冻结来源 revision、候选相关性、相关性理由、`FileMaterial[]`、
  `AttentionItem` 及内容指纹。每条材料包含适用 compiled scope 与可直接用于生成的内容；相关资料必须
  至少提供一条材料，不相关资料不得提供材料；不确定资料保守进入候选池并形成注意事项。它不把企业名称、
  措施、指标、日期和议题预编码成第二套固定事实抽取表。
- `MaterialSetSnapshot` 冻结一次 Mapping 或生成所见的 active 来源、声明、Dossier 和指纹。
  `EffectiveMappingTaskAssembly` 固定按 `build_report_revision(state) → EffectiveReportScope.project_report(report) → blocks_for_report(projected_report) → MappingTaskAssembly` 从 `CompiledReportDefinition + 当前 Report revision` 派生唯一任务计划：
  ESG 议题按 `reportSectionId` 分组，前置章节等非议题生成内容按报告区域分组，并过滤当前实例不存在的
  Block；不维护平行 target YAML。File Agent 入队、Snapshot 路由和 Mapping worker 必须共同调用此投影；worker 在模型调用前后重新装配，并在冻结 scope 的 ID、Block 集或语义任务不一致时 fail closed。Snapshot 保留相关与不相关 Dossier 供审计和未采用说明；Mapping
  Run 的唯一输入形状是由此派生的 `MappingRunInput(scope, dossier_ids)`：它不承载手写事实、Block 决定、
  定量值或原文件正文，且 `dossier_ids` 只包含 `relevant` 候选。Mapping worker 只能按这些 id 从快照对应的
  FileDossier 重建 `MappingDossierEntry`；因此前端、测试 runner 和用户输入都没有直接填写 Mapping 结果的
  数据合同。材料只路由到其显式 scope；系统不要求 File Agent 再拥有“全局资料”分类，也不把用户标签当排除条件。
- Mapping 模型只输出 scope 内 `BlockMaterialDecision` 候选：每个 Block 的处置、已存在材料 alias 的有序选择和原因；Harness 校验结构、快照、scope、完整覆盖和材料身份。Mapping 不创建、改写、合并或推断事实，不是报告正文草稿，也不得通过关键词、正则、预设事实模板或评分阈值生成。
- 准备总览页的资料进度是上述运行事实的只读投影：File Agent 未终态时才显示“文件正在理解”；文件已终态而 Mapping 未终态时显示“报告范围正在匹配资料”。两阶段不能以同一文件数量互相冒充，但任一阶段未完成时均保持 `processing`，以阻止过早生成。
- 用户在线填写或通过专用 XLSX 模板导入的 ESG 定量信息由 `QuantitativeMetrics` 独立拥有，先经专用
  parser 进入 Report state，再按编译合同中的 `quantitative_metric_ids` 确定性投影给 Block。Mapping
  任务地图只把指标名称和单位作为报告任务背景，不向 Mapping Agent 提供指标值，也不允许
  Mapping 回写、复制或覆盖结构化指标；两条事实分支只在生成 `ModelContext` 中汇合。
- 结构化输入工作簿家族共五个 `StructuredInputKind`：`assessment`、
  `quantitative_metrics`、`topic_questions`（议题引导问题，题目集取装配后 Report revision 的
  `intakeItems` 议题子集）、`report_basics`（user_input 字段 + 报告级四题 + 披露准则 + 附录联系；
  行计划与合同字段全集在生成时互核 fail-loud）与 `unified_workbook`（前四者的整册聚合）。
  共同合同：模板由后端按当前报告状态动态投影并**预填现有内容**（下载即状态快照），隐藏元数据页
  携带 kind 专属 context fingerprint；导入 parse-first、累计全部单元格错误、整簿拒绝、单事务
  CAS 原子替换 + 审计。`topic_questions`/`report_basics` 是模板范围内**整批替换**（空即清空，
  预填保证往返安全）；统一工作簿导入按 sheet 归属拆分重建子工作簿（值拷贝 + 注入对应 kind
  元数据）复用四个既有解析器，评分/定量整表留空视为暂不提交、保持现状。
- 统一工作簿存在**两个模板血统**，导入按工作簿元数据自我声明分支，两侧均为
  全等校验、互不放宽：report-bound 模板（`GET /api/reports/{id}/…/unified-workbook/template`，
  预填现状、元数据绑定该报告与其 context fingerprint，供 E2E 与程序化通道使用）；账户级
  **空白母版**（`GET /api/structured-inputs/unified-workbook/blank-template`，
  产品 UI 的唯一下载入口）——元数据 `report_id` 为全零 UUID 哨兵，fingerprint 由当前合同对
  空状态确定性重算（下载与导入两侧各自可复现；合同升级即按版本不一致拒绝旧母版），可导入
  任意一份报告。子工作簿元数据始终按目标报告上下文注入，来源血统不外泄给子解析器。
  UI 侧全部 Excel 导入通道先经统一覆盖确认（措辞归 design.md §3.1）。
- 报告级主输入路径（`primary_input_mode: materials | questions`）是**报告级事实**，落
  `StoredReportStateV4.meta.primaryInputMode`（议题级 `topic_primary_input_modes` 留在资料工作区，
  二者是不同层的事实）。它不改写任何已填
  输入——`intakeItems` 与资料证据轨在生成侧本就允许任一为空——但**它裁定议题级 generation 义务
  是否阻断**：只有「本范围声明了该义务 且 用户选择直接作答」时才阻断。
  该裁定必须由生成闸（`report_preparation.topic_obligations_block_generation`）与导出闸
  （`EffectiveReportScope.diagnostics_scope(primary_input_mode=...)`）读同一侧事实，否则出现
  「生成得了却导不出」。因此它不能留在资料工作区：诊断闸不依赖资料工作区，读不到那里的状态。
- **`StoredReportStateV4` 的字段所有权在合同侧声明，不在写入函数体里枚举**
  （`contract/stored_report_state.py` 的 `SERVER_OWNED_STATE_FIELDS`）：
  `assessmentInput`、`structuredInputFreshness`、`companyBusinessSummary`、
  `meta.materialityStrategy`、`meta.quantitativeMetrics`、`meta.primaryInputMode` 归服务端，
  只由各自的专用写入器改写；generic 客户端通道（`PUT /api/reports/{report_id}/state`）
  只能原样往返。`put_state` 的 `writes` 参数在入口解析「本次是谁的写入」：generic 传空集，
  专用写入器只声明自己那一个字段，因而写得进去又碰不到别人的地盘；未登记字段出现在 `writes`
  里立即 fail-loud。保全与 CAS 在同一事务同一行锁内，**锁内旧值定义上不陈旧**——这是前端基线
  给不出的保证。**默认方向是「受保护」**：本合同新增报告级字段时若未登记为前端拥有，
  generic 通道就抹不掉它——反向的「白名单枚举、新增字段默认裸奔」会让客户端整体 PUT 把服务端
  字段写回 null。执行性防护见 `backend/tests/test_reports_persistence.py`。
- 用户对 `AttentionItem` 的处置由 `MaterialSourceReviewPosture`（`reviewed_accepted |
  excluded_by_user`）承载，经 `POST /api/reports/{report_id}/material-sources/{source_id}/review-decision`
  记录并绑定当次解析指纹，供后续运行冻结消费。用户表单仍拥有基本信息、重要性、定量
  信息和议题问答；资料链不得把 File Agent 材料写成“用户已回答”
  （证据来源由 `AssertionBasis` 的 `material_evidence | user_assertion` 区分，不可互相冒充）。

File Agent、Mapping Scope、Block generation 和 Export 均保存输入指纹、幂等键与追加式事件，
但**状态词汇是三套、不是一套**：File Agent 与 Mapping 用 `PipelineRunStatus` 六值
`queued → running → succeeded | needs_attention | failed | superseded`；Image Agent 与 Block
generation 无 `needs_attention`，为五值（`persistence/material_agent_pipeline.py`）。跨这几条链写通用代码前先确认目标表的实际值域。
（`needs_attention` 当前只有 File Agent 产生，其重入队出口 `requeue_file_agent_run` 无调用点。）
worker 使用租约从未完成
节点恢复；指纹未变的已验证结果可复用。新增或修改文件只重跑对应 File Agent，并由章节 scope 自主判断
影响；移出文件可沿既有 lineage 确定性失效引用它的 Mapping、Block 与新报告结果，旧报告仍可追溯。

轻量版由 `ReportProfile` 允许零文件、非阻断 `AttentionItem`、经校验的 `BlockMaterialDecision` 自动采用资料内容及无事实段落
`context_only`；其公开报告体裁由已选 Prompt Profile 单点定义。

用户显式调用报告级生成命令后，系统冻结准备输入、`MaterialSetSnapshot`、Profile 和报告合同，创建
完整 `ReportRevision`。上传文件或完成 Mapping 不自动改写正文。每个适用 Block 必须保存生成结果或
明确 disposition；新 revision 成功前，上一版 Report、Word 和 lineage 保持可用。普通 Word、审阅版
Word 和内部审计包都绑定同一 Report revision 与 renderer/template 指纹；前两者必须消费同一
`DocumentRenderPlan`，目录仅在正文全部写入后最终化。封面与目录属于无页码的前置 Word 节，正文节从“关于本报告”的第 1 页开始；审阅版的封面说明和页脚生成时间都从冻结 revision
投影，不成为报告事实或新的状态 owner。

追加式 Run/Event ledger 是运行事实 owner。公共进度、审阅版和内部审计包只是不同权限下的投影：审阅版
由 `CustomerCommentaryPackage` 白名单渲染，封面说明锚定报告主体名称，正文按批注覆盖政策（只批注系统做过判断的单元，豁免名单见 `report_review_packages.COMMENTARY_EXEMPT_SECTION_KEYS`）在可见 anchor 上说明文件级资料来源、采用范围、定量指标或
审慎呈现原因；另由 `MaterialProcessingNotice`（`sustainability_desk.material_processing_notice.v3`）投影目录前的资料处理说明前置页，
与批注读同一份冻结 `dossiers`，逐份列出面向用户的须留意事项与提示；再由 `StandardsComplianceNotice`
（`sustainability_desk.standards_compliance_notice.v1`）投影其后的准则对照说明前置页，内容来自导出闸同一份
`Diagnostics.coverage` 判定（判定一次、闸与交付同源），列出准则允许的省略与建议留意事项。两个前置页都排在封面之后、目录之前，
标题走普通段落而非 Heading 样式，因此不占章号也不进目录，正式稿与审阅稿的章号、目录逐条一致；正式稿不含这两页。
这些**投影给用户的可见文本**都不得包含 Prompt、内部路径、内部判断代码
（`AttentionItem.code`）、来源 id、指纹、成本、私有工具策略或 debug。这一条约束的是渲染产物，不是 typed 包本身——`CustomerCommentaryPackage` 与 `MaterialProcessingNotice` 确实带 `render_plan_fingerprint` / `package_fingerprint`（`report_review_packages.py`），它们用于绑定 revision 与渲染计划、只进包不进正文。内部包冻结声明
历史、Dossier、FileMaterial、BlockMaterialDecision、收据、交付物引用、确定性导出凭证和 trace 引用，并在受限 ZIP
内复制可严格解析的原始 JSONL 快照；ledger / observability 仍是实际模型上下文、Prompt、工具轨迹、校验、
重试与成本的唯一 owner。两种投影都不保存或推断模型思维过程。

`FileDossier.v7` 是当前文件级来源合同：它不保存模型选择的 parser node、字符 offset 或原文摘录；每条
`FileMaterial` 绑定冻结 `source_revision` 和显式 compiled scope。历史 `FileDossier.v4/v5/v6` 只可用于
受限审计读取，不能进入新 Mapping 或新 Report revision；原文件存在时必须重新运行当前 File Agent。

File Agent 只通过受限工具读取文件，再提交严格的 `FileDossierProposal`。Harness 在 transport 边界以 Pydantic `Json` 类型解析 provider 的 JSON 字符串字段或原生嵌套值，再构造并验证唯一业务 `FileDossierDraft`，最后冻结 `FileDossier`；业务领域对象不承担 `json.loads`、静默截断或未知字段兼容。
Mapping Agent 不调用工具，直接提交严格的 `MappingProposal`：它只含 Block 处置、既有资料 alias 与理由；Harness
将 alias 解析为当前快照的 `FileMaterial` 身份后校验 scope、完整覆盖和处置形状。字符串化数组、内部 UUID、解析
locator、字符 offset、数组索引和未知字段均在协议边界 fail closed，领域对象不承担 `json.loads`、静默截断或其他
模型格式补救。

当前 v3 合同将单文件工具收敛为 `convert_file` 与 `read_file`：前者按需运行批准 parser，后者完整读取
一个转换产物；单文件 Agent 没有 `list_files`、局部范围或视觉工具。Harness 不做运行时第二模型评审，
四文件质量样本由人工结合 trace 与最终报告审阅。不得用单个成功 Dossier 或结构校验替代产品质量判断。

### GenerationInputs

`GenerationInputs` 把 Evidence 选择与额外报告主体字段分开，使用 `extra="forbid"` 的判别联合：

- `evidence.kind=explicit`：普通块只读取显式声明的 `intakeItems[]` 与 `quantitativeMetrics[]`。
- `evidence.kind=report_section`：仅用于 `conciseDisclosure`，所属 `reportSectionId` 由章节关系确定性继承；读取同一 H2 的有效内容清单答案，并从该 H2 唯一的 `metricDisclosure` 编译结果继承完整指标目录。指标值、备注和核算标准仍只来自用户填写，指标目录本身不构成实质企业事实，也不授予指标体系建设口径。
- `fields[]`：仅声明当前块额外需要的报告主体字段；Profile 的全局主体字段不在各块重复配置。

选择器类型、摘要用途、章节归属和引用 key 均在加载期校验。不存在“已声明但无消费者”的可选字段，也不保留旧 `contentScopeId` 兼容分支。

禁止在 prompt 临时拼接未声明事实。所有上下文先解析为结构化 `ModelContext`，再渲染给模型。

### Block.footnote

`Block.footnote` 声明挂在该块最后一段末尾的脚注正文（`list[Inline]`，与 `content` 同形态，
可含 `{kind: ref}`）。脚注是宿主段落的**从属事实**，不是独立块——独立成块会让它参与章节编号、
渲染计划与批注锚点，而它在交付物里并不占正文位置。

编号、上标样式与分隔细实线由 Word 母版承载，契约只声明「这段有一条脚注、内容是什么」；
导出实现与使用边界见 `export/footnotes.py` 模块文档串，格式参数见知识包内 `format_profile.yaml`（如 `backend/data/knowledge_packages/sse_zh_hans/format_profile.yaml`）。
保真由导出合同验证独立验证（声明数 = 引用数、原文只在 `footnotes.xml`、两稿一致）。

### 议题重要性评估节的两个分支

`sm.materiality` 节按 `meta.materialityStrategy` 分为互斥两套文本：

- **已评分**（`materialityStrategy` 为 `None`）：`sm.materiality_intro` + 四步流程 + 评估结果类块。
- **未评分**（`complete_coverage`）：`sm.unscored_purpose` / `_identification` / `_screening` /
  `_coverage` 四段确定性叙述，文本经人工审定。

触发条件用 `meta.materialityStrategy`（报告级事实），**不用** `includes_materiality_assessment`
（账户权益）——后者恒为 `True`，分支不可达；且权益按设计不进 Report，`appears_when` 无法也不应读取它。

`sm.unscored_coverage` 的议题数量与准则名称都是派生事实，不写死：前者
（`assessment.applicableTopicCount`）随科技伦理适用性与披露档位变化，后者
（`disclosureProfile.selectedStandardNames`）随企业上市地变化。前端镜像该派生并由
`backend/tests/fixtures/applicable_scoring_topic_count_golden.json` 两端消费防漂移。

### GenerationSpec

`GenerationSpec` 是 block 级生成合同。与轻量版写作口径相关的字段职责如下：

- `task.focus`：当前块唯一任务，以可适配不同企业和证据强度的内容焦点表达，不复述标题、不预填企业事实、不规定非必要句式。`section_task` 直接从这里投影；`topic_scope` 只引用与当前块共享 typed Evidence 的其他块任务，不从 `Block.content`、块类型或支柱名称反向推断。
- `task.noFactGuidance`：仅在单一议题确有特殊无事实边界、且块本身并非由输入显隐条件控制时声明；不保存通用无资料套话或“无事实不生成”重复指令。
- `standardDisclosureRequirementKeys`：本块承载的准则披露要求 key。**当前不进入 prompt**（注入属待办），但已被两个确定性消费者读取：交付前的披露覆盖判定（`contract/disclosure_coverage.py`）与块级 span 的 `sustainability_desk.standard_requirement_keys` 属性。一个要求可由多块承载，一块也可承载多个要求。
- `simplifiedWritingGuidance`：轻量版产品定位下的写作颗粒度、公开披露距离和事实承诺边界；仅在轻量版且本块存在实质用户事实时注入。
- `templateResidueBans`：参考模板残留物的字面拦截清单——模板原型公司的示例数值、口号与模板给编写者的批注（`《》、《》`、`XXX`、`代入上传的制度名称`、`范文：`）。只登记「出现在任何公司报告里都是错的」的串。**议题词汇、报告年份与通用管理表述不属此列**：它们在合法正文中正常出现，词面拦截无法区分「混入」与「并列提及」，只会误伤（报告年份串在同年报告里必然误判；`反商业贿赂`/`阳光采购` 会拦下反不正当竞争议题的正常并列表述；`设立专职部门` 会拦下「暂未设立专职部门」）。跨议题内容归属与事实强度是语义边界，归 `evidence_posture` 与 judge。
- `evidenceGatedFacts`：本块声明的「须有证据方可陈述」的敏感事实词面（如处罚、超标、整改）。只有模型可见证据含该词面时输出才可出现它；证据否定而输出肯定即拦截。否定与肯定的语言线索归守卫词表（`llm/guardrail_lexicon.py`），词面本身归块合同，不在跨议题守卫模块硬编码。
- 无据负向断言（把风险方向坐实为已发生事件）**不在词面层拦**：正则对同类表述基本漏放，却会误伤「公司不存在商业贿赂行为」「公司未受到监管处罚」这类合法否定句。该判定归 `evidence_posture.assertionStyle`、`disclosureStance=risk_disclosure` 的公开披露口径与 groundedness judge；`generation_guardrails` 的 守卫词表 `missing_statement_patterns`（`llm/guardrail_lexicon.py`，按报告语言分组） 分支早已写明「正则无法区分外部风险描述与公司自身短板」，例外补丁与该判断自相矛盾。
- `inputs` 与 `appears_when`：输入白名单和显隐 SSOT。

已删除 `promptKey`、`GenerationPosture`、`GenerationConstraints`、`mustInclude` 与 `regenerable`。结构完整性由 Schema、typed output、显隐合同和确定性 Guardrail 拥有，不通过未消费的自由文本字段表达。轻量版写作口径不得复制到 `standard_disclosure_requirements`；`Block.content` 只服务确定性内容或人类展示，不拥有生成任务。

前四章固定章节的生成块同样使用 `GenerationSpec`，但其章节结构真相源是知识包内 `report_contract.yaml`，不是 `topic_sections`。同一固定章节内的同一 `intakeItems` 不应被多个生成块重复消费；通用说明、可选 slot 和 assessment 派生表优先用确定性结构表达。

### 准则披露覆盖判定

`diagnose()` 在既有 issue 之外产出 `Diagnostics.coverage`（`DisclosureCoverageReport`），对每个纳入报告的议题逐条判定其准则要求的承载结果，并判定报告级义务。判定确定性、无 LLM，**轻量版不产生 `Issue`、不阻断导出**，只经审阅稿准则对照说明页告知用户。

判定的核心语义裁定：**证据门控省略（`state="omitted"`）是合法成功态，但对 `required` 要求而言，「省略并说明原因」合规，「静默省略」需用户留意。** 准则本身内置大量合规出口（《指引》第七条充分说明、尚未设定目标的说明、不具备定量能力时的定性替代、「如有」「如涉及」条件项），因此：

- `conditional` 要求被省略 → `requirement_conditional_not_triggered`，条件不满足即合规，不产生留意项；
- `required` 要求的全部承载块被省略 → `requirement_omitted_needs_statement`，进审阅稿留意事项并给出下一步动作；
- 审定为 `excluded_for_simplified` / `integrated_report_level` → `requirement_excluded_by_design`，按理由码投影为「准则允许的省略」信息项，不是缺口。

判定与导出闸读同一份结果（判定一次、闸与交付同源），并写入导出闸 span 的 `sustainability_desk.coverage_finding_codes` 与 `sustainability_desk.coverage_findings_total`——轻量版不阻断，但必须留痕。

## 议题合同

### 注册关系

`topic_registry.yaml` 同时定义：

- 评分表 / 矩阵中的官方评分议题。
- 报告正文中的二级议题章节。
- 评分议题到正文议题的映射。
- `sectionPrefix`，用于生成统一题 key。

`乡村振兴` 与 `社会贡献` 是两个评分议题，但共用正文议题 `rural_revitalization_social_contribution`。`stakeholder_communication` 只存在于评分表、矩阵和重要性评估表；正文归入第四章 `sm.stakeholder`，不单独建 `topic_sections` 或 `topic_intake`。

### 轻量版议题问题合同

除 `stakeholder_communication` 外，每个有独立正文议题章节的轻量版议题由两类问题组成：

1. 四道跨议题固定题，由 `topic_intake_common.yaml` 统一展开。
2. 专家定义的议题专属题，由 `topic_intake/<topic>.yaml` 维护，题数不再固定为两道。

| 支柱 | 题目 key | 来源 |
| --- | --- | --- |
| 治理 | `<prefix>.q_governance_roles` | `topic_intake_common.yaml` |
| 治理 | `<prefix>.q_governance_policies` | `topic_intake_common.yaml` |
| 治理 | `<prefix>.q_governance_certifications` | `topic_intake_common.yaml` |
| 战略 | `<prefix>.q_strategy_content` | `topic_intake_common.yaml` |
| 议题专属 | `<prefix>.q_<business_semantic>` | `topic_intake/<topic>.yaml` |

固定题不得在各议题 YAML 重复维护。议题专属题必须按专家反馈和报告 block/table 需求命名，不使用 `q_iro_*` 作为通用承载层，避免 key 名称与实际业务语义漂移。题干和选项应避免把示例范围写成可被模型误读的企业事实；涉及对象类别时，优先使用结构化选项或改写为“如有，请说明具体对象和内容”。

当前轻量版不引入嵌套子问题。若同一道多选题存在分组最小选择要求，使用 `optionGroups` 在 schema 层表达，不在 prompt 中临时解释。选择题的补充说明继续承载金额、原因、计划、资质、有效期、事件概况、培训范围等附加事实；模型生成合同必须禁止在缺少具体填写时编造金额、日期、比例、次数、人数、处罚、认证或完成情况。

当企业内部管理概念不适合原样进入公开报告时，优先保留结构化原始选择，并通过 `generationOptionLabels` 投影对外披露语义。例如供应商评价中的“成本竞争力”仍是用户可选的内部管理事实，模型侧投影为“长期价值与可持续运营效率”。不得通过全局禁词、运行时字符串替换或要求模型自行猜测二者关系。

### Block 到问题的映射

轻量版默认映射：

- 治理块读取三道治理题。
- 战略段落、战略风险/机遇表读取 `<prefix>.q_strategy_content`。目录表中的自由文本仅作为整表参考资料使用，影响表格的行业相关性、表达方向和优先级；不得被逐行照搬或机械分摊到每个目录行。若固定目录表配置 `presetRowSelection`，实际行集合只由其绑定的结构化多选答案确定；补充说明只能为已选行提供写作资料，不能激活未选行。
- IRO 段落、IRO 表格、表格辅助块和显隐条件读取对应议题专属题。每道议题专属题必须至少被一个 block/table/condition 读取，或在 TODO 中明确标记为资产路线或专项数据层。
- 每个议题来源模板必须且只能声明一个 `metricDisclosure.catalogMetricKeys[]`。严格 parser 校验 key 后统一编译“指标与目标”H3、确定性指标图和动态 H4；来源 YAML 不手写这些运行态块或重要性条件。
- Planner 是重要性分支的唯一所有者：`financial/dual` 装配四要素，`impact/non` 只装配 H2 直属摘要。**但存在第三种装配模式 `complete_coverage`**（`meta.materialityStrategy`，`planner.py`）：该模式直接使用未裁剪的议题模板、**完全绕过 `_assemble_report_section`**，因而不走上述四要素/摘要分支——语义是「本公司适用的全部议题一律完整装配」。它与 `assessmentInput` **互斥**：写入评分即退出该模式（`structured_input_service.py`），同时携带两者会被 Planner 拒绝。它有专属 readiness 豁免（评分不构成门禁）与专属诊断 `materiality_complete_coverage`。摘要通过 `report_section` 继承本 H2 的内容清单和指标目录，但不继承 `MetricNarrativePolicy`，不得把无值状态推导为指标体系、统计计划或披露承诺。
- `financial/dual` 下任一目录指标有值时只显示已填指标图，不生成 AI 正文；全部无值时生成动态 H4 标题与简短正文。目录为空不表示隐藏，模型可在受控策略下提出少量通用指标名称，但不写回产品目录。

气候、能源、污染物等议题的战略风险/机遇表属于战略支柱，不强行归入 IRO。若表格需要结构化辅助题，该辅助题仍应按真实章节用途映射到对应表格。

## 知识包词表

包内文本就是该包语言，代码只按 id 分支、按包读显示词：

- 支柱 `Pillar`（`governance`/`strategy`/`iro_management`/`metrics_targets`）是 `Section.pillar` 与要求库分组的 id，
  显示标题来自 `package.yaml` 的 `pillar_titles`；维度 id（`environment`/`social`/`governance`）与显示名来自
  `topic_registry.yaml` 的 `dimensions`。
- `report_contract.yaml` 的 `assessmentVocabulary`（重要性类别、矩阵轴、IRO 类别、影响分类）与
  `quantitativeMetricsVocabulary`（温室气体核算准则选项、「其他」哨兵、审阅备注模板与分隔符）是评估表与
  KPI 表的显示与校验词表；`sm.topic_table`/`sm.iro_table` 的选项与工作簿下拉必须与之一致（测试守卫）。
- `IntakeItem.hint`（≤60 字）与 `termExplanation`（≤80 字）是字符上限，三包共用。

## ESG 定量数据表合同

指标目录 SSOT 是知识包内 `quantitative_metrics.json`；原表格叶子名保存在 `metricLabel`，脱离层级单独展示时若会失义，则由显式 `standaloneLabel` 补全，不按关键词猜测。议题到目录指标的唯一映射是来源模板的 `metricDisclosure.catalogMetricKeys[]`；用户逐项确认的唯一事实是 `Report.meta.quantitativeMetrics`。每个当前适用指标必须保存“数值”或受控 `noValueReason` 二者之一，`0` 是有效值；无值原因只表达该指标的收资状态，不是绩效数值，不进入正文数值、图表或附录 KPI 行。只有用户填写了声明 `requiresGreenhouseGasAccountingStandard` 的指标数值时，温室气体核算标准才成为必填。

目录条目可带 `kpiCode`（准则对 KPI 的编号，如港交所 `A1.1`、`D28(a)`）；附录 KPI 表按合同 `colDefs` 的列键
（`category`/`kpi_code`/`metric`/`unit`/`value`/`remark`）投影，没有 `kpi_code` 列的包不显示编号。附录第一列的议题名
先对照包内报告章节标题，只有 `category` 不是章节名时才取连字符前段（上交所「人力资本发展-子类」约定）。

附录 `appendix.esg_key_performance_metrics` 是固定派生表，不是第二个录入面：前端加载报告时按目录与 `meta` 重建预览，服务端 Word 导出前再次重建。该表的 `table.children` 不进入状态快照，也不得在报告正文页直接编辑；旧快照中的同名表行一律视为可丢弃缓存。

每个已声明指标都以受控口径进入 `ModelContext`，即使用户未填写值。模型可见字段仅限：

- 来源：`ESG 定量数据表`
- 分类路径（`sheet` **不进**模型上下文：`MetricEvidence` 只有 6 个字段，
  层级信息由 `category_path` 承载，`llm/` 全目录无 `sheet`）
- 指标名称
- 单位
- 填写值；仅在用户实际填写时出现
- 用户备注；仅有备注时写入
- 温室气体核算标准；仅适用且用户填写时写入

禁止进入 prompt：

- metric key
- department
- issueNotes
- sourceComment
- raw meta
- 内部路径或 provenance

未提供填写值时，模型上下文只保留指标名称、单位、披露维度与写作边界，不出现“填写值：未填写”。缺值不得被推断为公司未统计、未开展、不存在或为零；模型不得编造金额、日期、比例、次数、人数、完成情况或认证事实。

`FieldType` 值域九项：`string`、`number`、`year`、`month`、`date`、`email`、`percent`、`url`、`enum`。前端录入控件从 `Field.type` 派生：`number`、`percent`、`year`、`month`、`date`、`email`、`url` 分别使用受限控件并在写入边界校验（`email` 另有跨端 golden fixture 对齐的严格校验）；定量指标值只允许十进制数，不允许单位、千分位、科学计数法或说明文字。文本问卷、部门与备注仍按其文本语义输入，不被数值规则误限。

指标摘要图只读取 `Report.meta.quantitativeMetrics.metrics.<key>.value` 的已填写值；`0` 是有效填写值，空字符串和缺失值视为未填写。报告年度来自 `fields.reporting_year`，缺失时可使用 `Report.assessment.reportingYear`，再缺失时显示为“报告年度”。派生图不读取用户备注、部门、issueNotes、sourceComment 或 provenance。目录指标名为“其他”时，报告展示层必须补全稳定显示名称，避免正文图孤立显示“其他”。

同一指标与目标支柱中，`image.derivedVisualization` 是报告期数值的唯一正文承载。来源模板编译器从唯一 `metricDisclosure` 同时生成图片和正文条件：任一相关指标有值时只显示已填项图片，生成清单不存在指标正文块；全部无值时图片隐藏，动态 H4 与正文在同一次结构化调用中成对生成。附录始终从全部已填轻量版指标确定性投影，不按重要性过滤，也不展示空项。

## 显隐与表格

`appears_when` 是 parse-first 条件，不是 prompt 指令。

- 条件路径受**编译期白名单**限定（`contract/visibility.py`，白名单在
  `contract/compiled_definition.py`）：`fields.*.value`、`intakeItems.*`、
  `quantitativeMetrics.*`、`meta.materialityStrategy`、
  `appendixPackage.*`、`assessment.*`（含 `counts.*` 与 `topics.*.materiality`）、
  `blocks.*.state`。白名单外的路径编译期即拒绝，不是运行时静默为假。
  当前生产 YAML 实际用到的主要是 `appendixPackage.*`（16 处）与 `assessment.counts.*`（8 处）；
  `quantitativeMetrics.*` 目前零使用——**不要据「文档只列了三类」把合法路径当非法**。
- 算子七个：`exists`、`not_exists`、`eq`、`ne`、`gt`、`in`、`contains_any`。
- 输入条件为假时，生成入口、诊断和导出统一跳过该节点；Prompt 不保留对应的防御性缺料分支。
- 指标图片、正文 evidence 与显隐条件只能由 `metricDisclosure` 编译，不得由渲染器反向匹配或在 Prompt 中另建分支。
- 重要性决定 H3 是否装配；指标填值状态只决定 H3 内部展示图片还是动态 H4。各端只消费编译后的 Report 条件。
- table row 可以有独立 `generation` 和 `appears_when`。
- 表格保留在所属支柱中；不得为了满足题数约束把战略表或指标表强行归入 IRO。
- 表格是与段落同等的一等 `Block(type=table)` 对象；所有表格共用一套 `GsTable` schema 与三线表渲染（列/行不同、样式统一）。
- 风险/机遇矩阵表有两套成型列语义，按议题选用，**不得自行发明第三套或漂移为“具体内容”等弱语义列名**：① 通用六列（`风险与机遇类型`、`风险与机遇名称`、`潜在影响`、`财务影响`、`影响的时间范围`、`应对措施`），当前用于反商业贿赂、能源管理、污染物排放三个议题；② 气候按 TCFD 独立成型（`风险类型`/`机遇类型`、`风险名称`/`机遇名称`、`潜在影响`、`影响价值链`、`影响时限`、`财务影响`、`应对及管理措施`），见 `backend/data/knowledge_packages/sse_zh_hans/topic_sections/climate_change.yaml`——多出的价值链与时限维度是 TCFD 要求，不是漂移。
- 表格生成形态由 `generation.rowMode` 区分（锚点列=首个 ai_text 之前的前导列，AI 列=其余）：缺省走定行（AI/`fixedRowSeeds`）+ 逐行补全；`preset_catalog` 的候选目录由 `fixedRowSeeds` 声明，实际行集合可由 `presetRowSelection{intakeItemKey,selectionMode,unansweredBehavior}` 在调用模型前确定，再整表一次填充；`adaptive_catalog` 由前置步骤依据业务 + `referenceCatalog` 识别候选锚点，再由 harness 投影为可填充锚点；第三值 `expanded_rows` 按 `RowExpansion` 把每业务行展开为多子行（`models.py` 有完整契约，当前 YAML 暂无使用，但它是已建成的一等形态，不是待实现项）。LLM 只补全确定后的行，不参与固定目录显隐判断。生成层设计见 `context-engineering.md` §5。
- `sm.stakeholder_table` 使用 `rowSource=stakeholder_engagement`，`table.children` 只拥有表头。Planner、网页和 Word 均从 `Report.stakeholderEngagement` 确定性投影八行；适用议题来自当前注册表范围，并排除尽职调查、利益相关方沟通和风险管理（`contract/stakeholder_engagement.py`）。范围新增时按默认矩阵补入，范围移除时清除，范围未变化时保留用户主动删除的关系。
- 利益相关方表允许同一议题关联多个对象；正式导出前，每个适用议题必须至少被一个对象覆盖。沟通方式按沟通渠道、参与机制、合作活动排序，受控方式在前，同类别自定义方式在后。

## 持久化数据合同

持久化层（本地 `supabase start` 的 Supabase 栈）存用户状态与审计证据，不存契约结构；DDL 事实源是 `supabase/migrations/`。

账户、Grant、Profile、报告所有权与整节生成账本的长期语义统一由 `docs/account-system.md` 承载；本文只记录结构化 Report 状态与内容 schema 的边界。

- 轻量版 `report_states.state` 只接受后端独立领域模型 `StoredReportStateV4`。API 与数据库读写边界均先用该模型严格解析；同一模型导出 JSON Schema、前端生成类型和 Ajv 运行时 parser，浏览器本地状态与服务端响应不得各自维护手写宽松解析器。V4 保存字段值、问卷答案、`assessmentInput`、利益相关方 Profile、`sectionTitles`、生成正文、普通表格用户行、素材图片放置（`imageBlocks`：承载块 → 按序 `layoutAssetIds`，由生成 worker 依 `evidence_assets.placement_scope_id` 经契约承载位映射确定性写入；题注与替代文本归 `evidence_assets` owner，不入 state）；题目定义、`collectionPriority`、章节树、块合同、列、显隐、编译定义、派生表行与 Plate 文本骨架不入库。旧版本、损坏 JSON、缺失版本与任何层级的未知字段均明确拒绝，不提供迁移、别名、双读或兼容分支；`state_seq` 乐观锁冲突返回 409。
- HTTP 错误响应是用户可见投影，不是异常的字符串化。主形态是 `sustainability_desk.contract.api_error` 的
  `ApiErrorDetail`（包在 `{detail: {...}}` 里）：`code` 是稳定的领域标识，供前端决定引导动作；
  `message` 是代码侧确定性生成的中文文案。
  **另有一个刻意保留的顶层形态**：`StructuredInputPreconditionResponse`
  （`contract/report_api.py`）在 409 前置条件不满足时直接返回顶层 `{code, message}`，
  以免伪造一份当前状态快照；同一个 `contract_upgrade_required` 因此可能以两种形态出现，
  前端 `lib/api-error.ts` 据此保留顶层兜底分支。**「唯一形态」不成立，但下面的安全属性
  对所有形态一律成立**——两种形态都只承载稳定 code 与代码侧中文文案。
  内部标识（account_id、report_id、对象路径、上游响应体、SQL 约束名、profile_id）一律只进日志与 trace，
  不得出现在任何用户可见文本里——包括错误响应，也包括 200 响应中的失败原因字段
  （`error_message`、`parse_failure_reason` 与 `MaterialProcessingError.reason` 同属用户文案）。
  异常消息一旦成为用户文案，任何人日后往异常里加个标识符即造成泄露（典型形态：`detail=str(exc)` 把
  携带账户 id 的异常消息透传成界面提示；认证上游原始响应体经密码分支透传；存储与数据库故障文本经
  资料失败原因投影）。低结构的上游响应必须在入口解析成领域事实（如「密码强度不足」），下游据类型
  分支，不得对错误文本做子串匹配。
  框架默认错误响应同受此约束：FastAPI 的 `RequestValidationError` 默认返回
  `[{loc, msg, input, ctx}]`，其中 `input` 回显用户刚提交的字段值、`loc` 暴露服务端模型结构、
  `msg` 是英文内部措辞。`contract.api_error.register_error_handlers` 在 app 组合根把它接回
  `ApiErrorDetail`（`code=request_body_invalid`），字段路径只进日志；`user_messages()` 覆盖 str、dict
  与 list 三种 `detail` 形态。
  `tests/test_api_error_contract.py` 是该契约的执行性防护：它从 `app.routes` 反射枚举**全部**写入端点，
  把路径参数替换成不存在的 id 后逐条打，扫描响应中的内部标识痕迹。覆盖面必须保持「默认打开」——
  手写 URL 靠人登记的探测清单会让新链路整条走在守卫之外。

- 驱动报告导航、状态序号与内容写回的核心响应（报告摘要/列表、状态快照、保存序号、重写额度、生成新鲜度、整节生成和模块标题生成）由后端严格 Pydantic 响应模型单点定义，并导出 JSON Schema、生成 TypeScript 与 Ajv parser；浏览器消费前必须 parse-first，不得以 `as` 信任网络 JSON。展示型或一次性低风险接口尚未纳入该组时，不得宣称全 API 已完成同源合同。
- 资料链与报告状态分表持久化：`MaterialSource`、声明 revision、binding、`NormalizedMaterial`、File Agent Run、
`FileDossier`、`FileMaterial`、AttentionItem、MaterialSetSnapshot、Mapping Run、`BlockMaterialDecision`、
Report Revision、Artifact 和追加式事件各自保存自己的事实；不得塞入 `report_states.state` 或复制为
  一个万能 workspace JSON。任务 payload 在领取边界 parse-first，只保存引用和指纹，不复制正文。
- 排版素材图片链：`layout_asset` 经 `image_agent_runs`（与 `file_agent_runs` 同构裁剪，
  幂等键 `image-agent:{binding}:{fingerprint}`）单次 VLM 识别产出 `ImageDossier`
  （`sustainability_desk.image_dossier.v1`：summary/category/caption/alt_text/scope_id），
  同事务提升为 `evidence_assets` 行（`caption_source='user'` 的用户题注不被重跑覆盖；
  `category` 落识别类别，只用于素材归档与人工核对，不驱动生成分支）。素材一律以原图进报告，
  不做结构化转录重绘。`material_sources.source_label` 是可编辑展示名，
  不进声明 revision、不参与确认指纹，改名不触发任何 Agent 重跑。
- HTTP 公共投影由后端 Pydantic response model 单点定义，并导出 JSON Schema、TypeScript 与浏览器
  运行时 parser。统一文件入口、准备总览页、报告生成进度和 Artifact 下载不得由 URL 或浏览器本地状态
  推断文件议题、运行阶段或成功状态；`/materials/profile` 与 `/materials/topics/*` 不再承担分类 owner。
- 私有 `materials` Storage bucket 只保存原文件。对象路径和短时签名 URL 是存储边界数据，不进入模型
  上下文或审阅包。普通“移出报告”只改变 binding；`POST .../remove` 与 `POST .../restore` 不物理删除
  Storage 对象。永久隐私删除必须未来另设明确授权、级联失效与存储审计合同。
- 轻量版报告 lineage 保持「来源 revision → FileDossier（含 FileMaterial）→ BlockMaterialDecision →
Block revision → Artifact」。用户结构化输入走自己的事实分支，在 Block 上汇合；不得把 File Agent 内容
改写为 Mapping 事实，也不得先写成用户答案。资料表、对象路径、完整 provenance、Prompt、成本和 debug 不得成为正文生成旁路。
- 报告正文页的逐块溯源是只读投影 `ReportBlockProvenanceProjection`（`contract/block_provenance.py`，
  `sustainability_desk.block_provenance.v1`，`GET /api/reports/{report_id}/generations/latest/block-provenance`）：
  由最近一次成功运行的修订快照（生成基线正文）、该运行冻结快照的 `BlockMaterialDecision` 与 FileDossier
  （文件名与采用的 FileMaterial 单元数）、编译合同解析的填写题与已填指标（与审阅批注同一
  `consumed_metrics` / `block_evidence_basis` 规则）以及本地观测轨迹（`observability/block_trace_facts.py`
  聚合的尝试次数、守卫结论、守卫 issue key、事实数、阶段状态）装配（`block_provenance.py`）。只含稳定 code、
  文件名、显示名与计数；不含 run/span/模型/路径/prompt。轨迹缺失或不可解析是合法状态
  `trace_availability=unavailable`，不是错误；「是否改过 / 改了什么」由前端用本地 Report 与
  `generated_content` 派生，服务端不持第二份真相。`report_lineage_edges` 当前没有生产写入方，
  `GET .../report-lineage` 对真实报告返回空（处置待排期）。
- File/Image Agent 与 Mapping worker 使用带租约、尝试次数、输入指纹和幂等键的 durable job；单文件和
  单章节失败彼此隔离，租约超时可恢复。三类 run 的失败语义一致：worker 失败按错误类型分流——瞬时错误
  （模型行为异常、网络、存储等）在 attempt 余量内回置 queued 等待重新 claim，并保留本次
  failure_code/receipt 作为失败痕迹（下次终结覆盖）；权益失效、持久化合同不一致与冻结输入契约错误
  （`AccountEntitlementError`/`MaterialAgentPipelinePersistenceError`/`ValueError`）是确定性失败，
  与 attempt 用尽一样直接落终态 failed。claim SQL 只认领 queued，failed 保持无歧义终态。
  任务状态由服务端迁移，模型只能提交 typed proposal，不能自行决定持久化状态、权限或报告生成。
- 契约（章节树、议题合同、准则要求、提示词配置）保持后端 YAML SSOT；`reports.contract_version` 建报时钉住 `contract_version()` 内容摘要（`cv-<12hex>`），契约文件任何变更自动产生新版本，契约升级须是显式操作。恢复运行时 Report 的固定链路为「当前模板 + 状态事实 → `/api/plan` 装配动态章节 → 按稳定 key 回填状态 → 重建定量指标投影」；请求携带已钉住版本，不一致时 `/api/plan` 返回 `409 contract_upgrade_required`，不得静默升级或迁移。
- `report_events` 是只追加操作审计流水。`generation_runs` 是产品生成任务的可变聚合投影：任务开始插入 `running`，结束在 `finally` 更新为 `succeeded/failed`，并从本任务的 `model_invocation` 事件聚合调用、token、耗时与传输尝试；该数据库投影不保存 prompt、模型正文、用户资料或认证主体，完整调用内容由权限受限的 AI 观测 JSONL 单独持有，账户归属只通过 `reports.account_id` 推导。
- 报告级生成事件合同 `sustainability_desk.report_generation.v1` 的 `event_type` 含 `export_blocked`：生成成功提交前对新报告状态跑与工作台「导出前检查」同一道 `diagnose`，存在阻断级问题时正文与 revision 照常保存，但本次不产出任何用户可见交付物（`_validate_completion` 拒绝携带 artifact），并追加 `action_required` 的 `export_blocked` 事件，阻断明细以 `blocking_issues` 列入事件 payload，引导用户补齐输入后重新生成并导出正式稿；无阻断时照常写入三类交付物并发 `artifacts_ready`（迁移 `20260804000001_generation_export_blocked_event.sql` 扩展事件枚举）。
- `section_regeneration_batches.input_fingerprint` 冻结该次完整成功生成实际消费的页面 `ModelContext` 集合指纹。当前输入与最近成功批次指纹不一致时，正文标为 stale 但保持可见且不自动重写；只有用户显式成功重写才替换正文并按既有规则计入额度，失败、检查新鲜度或路径切换均不计数。
- `report_events` 由服务端写入，但**不止业务动作**：除建报、保存、归档、生成、导出等业务事件外，还包含**前端产品遥测**（`page_reached` / `page_error`，`persistence/product_telemetry.py`，以 `actor='user'` 落库，由浏览器 POST 触发）与 `/api/export` 导出闸的 `workbench_export_blocked`（事件名沿用旧称，与生成侧 `export_blocked` 是两回事）。遥测事件不是业务审计事实，消费审计流水时须按 `event_type` 过滤，不要把它们当成用户业务动作。注意 `event_type` **无 CHECK 约束**（仅 `actor` 受约束为 `user|system|llm`），值域会持续增长，本行的枚举是当前快照而非封闭清单。正文生成成功或用户编辑后的有效内容统一为 `ready`；不存在段落、表格行或整表的“采纳”状态与客户端采纳事件。
- 导出存档：`/api/export?report_id=` 成功导出后，docx 以 `exports/{report_id}/{utc时间戳}.docx` 上传 exports 桶，`report_exported` 事件携带 sha256 指纹与字节数；上传失败不阻断下载但事件仍落库（`archived=false`）。
- Account 权益、报告类型和 `section_regeneration_batches` 的配额语义只在 `docs/account-system.md` 定义；本文不得复制 Profile 数值或授权流程。
- 浏览器认证客户端只负责邮箱密码登录、会话刷新和退出（`lib/password-auth.ts`）；业务数据统一经 FastAPI。`anon`、`authenticated` 没有业务表直接写权限；业务表继续开启 Account 范围 RLS 作为纵深防御，FastAPI 以仅存于服务端的 service role 访问且应用层必须断言 Account 与 Report 所有权。
- 认证：本机 Supabase 认证栈签发的 JWT。后端 `api/auth.py` 对 ES256/RS256 使用 JWKS 公钥校验，对 HS256 使用共享密钥校验，并从合法 claims 解析 `user_id`；配置由 `persistence/settings.py`（`SUSTAINABILITY_DESK_*` 环境变量）承载，未配置时持久化端点 503。
