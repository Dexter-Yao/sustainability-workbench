<!-- ABOUTME: 议题构建作业指南，用于逐议题新增、重构或审查 ESG 议题章节、输入题、表格、生成配置、断言与测试。 -->
<!-- ABOUTME: 本文定义可执行工作流与验收门；数据契约以 schema-contract.md 为准，生成机制以 context-engineering.md 为准。 -->

# 议题构建指南（Evergreen）

## 1. 文档定位

本指南用于逐个处理 ESG 议题。目标不是写一份说明文档，而是建立一套可复用的议题构建规程：每个议题都必须能从官方议题、报告章节、轻量版用户问题、结构化表格、逐 block 准则内容、LLM 上下文、在线 L1 断言、离线测试和特殊事项 TODO 形成连续链路。

本指南不替代以下真相源：

- 数据契约：`docs/schema-contract.md`
- 上下文工程：`docs/context-engineering.md`
- 议题注册：`backend/data/knowledge_packages/<package_id>/topic_registry.yaml`
- 议题结构与生成配置：`backend/data/knowledge_packages/<package_id>/topic_sections/<topic_id>.yaml`
- 议题内容清单：`backend/data/knowledge_packages/<package_id>/topic_intake/<topic_id>.yaml`
- 准则披露要求资产：`backend/data/knowledge_packages/<package_id>/standard_disclosure_requirements/<topic_id>.yaml`

以上四类文件按知识包组织（`backend/data/knowledge_packages/<package_id>/`，现有 `sse_zh_hans`、`hkex_zh_hant`、`hkex_en`、`gri_en`）；一个议题只属于一个包，跨包同名议题互不共享。港交所两包是同一骨架的两种语言，id 集合由 `backend/tests/test_hkex_package_twins.py` 守护，改一包的结构必须同步另一包。

## 2. 每个议题的交付物

处理一个议题时，应至少形成或更新以下内容：

| 交付物 | 位置 | 验收标准 |
|---|---|---|
| 议题身份 | `topic_registry.yaml` | 官方议题名、维度、报告二级章节、两题一章关系、适用性规则一致 |
| 轻量版用户问题 | `topic_intake_common.yaml` + `topic_intake/<topic_id>.yaml` | common 模板承载四道跨议题固定题；议题文件承载专家定义的议题专属题，题数按专家意见和 block/table 映射确定 |
| 报告章节与 block | `topic_sections/<topic_id>.yaml` | ESG 维度下的二级议题章节清晰；block 职责不重叠；显隐由 `appears_when` 表达 |
| 准则披露要求映射 | `standard_disclosure_requirements/<topic_id>.yaml` | 保留合规准则披露要求为数据资产与加载期校验；注入 prompt 属整体待办（生成恒不注入） |
| 表格结构 | `table.colDefs` | 重要表格一表一建模；列 key、选项、行数、默认覆盖、短句格式明确 |
| 生成边界 | `generation` | `GenerationTask`、`inputs`、`simplifiedWritingGuidance`、`targetChars` / `rowCount`、`standardDisclosureRequirementKeys`、`redlines` 明确；事实权限由运行时 `EvidencePosture` 单点投影 |
| 在线 L1 断言 | 通用模块或 block 配置 | 高确定性错误可阻断并驱动最多 3 次重试 |
| 离线测试 | `backend/tests/`、必要时 `frontend/*test.ts` | 加载、显隐、必填阻断、表格结构、L1 谓词、前端题目流可回归 |

## 3. 阶段 0：议题身份与边界

### 3.1 输入

- 现有 `topic_registry.yaml`、已建模相邻议题 YAML。

### 3.2 操作

1. 分别确认评分议题 `assessmentTopicId`、报告 H2 `reportSectionId` 与报告 H1 `reportModuleId`；三类实体不得共用字段或依赖字符串恰好相同。
2. 五个轻量版报告模块固定为“环境可持续”“人与社区”“创新与产品责任”“可持续价值链”“负责任治理”；议题章节是其 H2。
3. 如存在“两题一章”，评分议题保持独立，报告章节可合并。例如“乡村振兴”“社会贡献”是两个评分议题，但报告正文执行“乡村振兴与社会贡献”一章。
4. 如评估议题已在前章固定结构中披露，不得重复建 ESG H2。`利益相关方沟通` 属于该类：`reportSectionId: null` 且 `materialityDetermination` 固定为影响重要性，由 `report_contract.yaml` 中既有利益相关方沟通 H2 承载，不进入用户评分和矩阵。
5. 确认适用性规则。默认适用议题应进入轻量版报告，不再按矩阵分数过滤；少数条件议题由报告配置和 planner 控制。
6. 不保留旧议题名兼容层或 aliases；出现旧名应直接清理或阻断。

### 3.3 校验

- Excel 缺少任一适用 `scored` 议题、包含非官方名称、重复议题、固定分类议题或当前配置不适用议题时，必须阻断并提示原因。
- 风险管理属轻量版主链，进入矩阵、评估表与正文；科技伦理由适用性题控制（当前唯一一条议题适用性规则）。
- 嵌入前章的固定评估议题不得出现在 `topic_sections`、`topic_intake` 或 `standard_disclosure_requirements` 中。
- 注册表只保存 `AssessmentTopic → ReportSection → ReportModule` 单向关系；加载期必须拒绝孤立 H2、未知模块、合并 H2 成员维度或适用性不一致，以及五模块成员漂移。
- 任何边界不清的内容不得用相似字段名合并，应进入 TODO 或先行确认。

### 3.4 议题正文边界规则

以下规则跨全部议题适用，逐议题的核心内容与相邻议题划分以
所属知识包的 `topic_registry.yaml`、`topic_sections/` 与
`standard_disclosure_requirements/` 为准，不另维护人工对照表——
零代码消费的对照表会与实现漂移而无人察觉。

1. 当前议题只能展开当前议题的治理、战略、影响/风险/机遇管理、指标与目标和用户填写事实。
2. 相邻议题只能作为背景、协同对象或边界提示出现，不得在当前议题内展开相邻议题的制度、指标、事件、案例或绩效。
3. 定量信息收集页事实不自动进入全部议题正文；只有当前报告类型已开放、且生成块通过
   `generation.inputs.quantitativeMetrics` 明确声明的指标，才能按受控投影进入该块。ESG 关键绩效表、
   证明材料、台账、审计底稿、认证证书等仍不自动进入议题正文。
4. 未填写的数值、事件、处罚、认证、覆盖率、金额、目标完成情况、供应商数量、人员数量、投诉数量、
   事故数量不得编造。
5. 条件议题或条件块由报告配置、用户选择和 `appears_when` 控制；不得由 LLM 自行判断是否显示。
6. 若确需复用其他议题事实，应使用经确认的跨议题摘要事实层（见下），不得直接读取其他议题原始填报。

**跨议题摘要事实层规则**——如后续需要让某议题引用其他议题事实，应先建立单独的摘要事实层并满足：

1. 摘要事实应为业务语义摘要，不暴露其他议题原始题目、内部 key、source refs、路径、debug、
   provenance 或评分原始结构。
2. 摘要事实应声明来源议题、目标议题、允许用途和去重规则。
3. 目标议题只能引用摘要结论，不得展开来源议题的完整治理、指标或事件。
4. 若来源议题事实缺失，目标议题不得推断或补写。
5. 尽职调查是首个明确适用该规则的议题：可承接供应商机制调查、环境/社会/人权/商业道德尽调，
   但当前不直接读取供应链、商业行为或环境合规原始填报。

## 4. 阶段 1：基本 schema 建模

### 4.1 Schema 范围

议题基础 schema 不等同于新增 Pydantic 字段。优先使用既有 `Report`、`Section`、`Block`、`IntakeItem`、`GenerationSpec`、`GsTable` 模型，通过 YAML 数据实例表达议题差异。只有当现有模型无法表达稳定业务对象时，才考虑修改 `backend/src/sustainability_desk/contract/models.py` 并同步前端生成类型。

每个议题的基础 schema 包含：

- `topic_registry.yaml` 中的评分议题、报告章节、报告模块、重要性判定方式、适用性和单向归属关系。
- `reportSectionId` 的语义：独立 ESG 议题章节使用具体 `reportSectionId`；嵌入固定章节的评分议题使用 `null`，且不建立议题工作纸。
- `topic_intake/<topic_id>.yaml` 中的内容清单项。
- `topic_sections/<topic_id>.yaml` 中的章节树、block、表格和生成配置。
- `standard_disclosure_requirements/<topic_id>.yaml` 中的准则披露要求映射。
- 必要时的报告级配置字段，例如科技伦理适用性。

### 4.2 类型链要求

议题数据应尽可能沿同一条类型链流动：

`YAML/Pydantic 模型` → `JSON Schema` → `frontend/lib/schema.ts` → `API payload` → `frontend state` → `LLM ModelContext` → `Report` → `Word 导出`

不得在任一层临时猜 shape。若前端或 API 需要新增 shape，应优先从 Pydantic schema 派生；不能派生时，必须记录原因和后续统一方向。

### 4.3 校验

- 新增或修改模型字段时，必须更新 schema 文档与生成类型。
- 新增 YAML 字段前，先确认 Pydantic 是否已有受控字段；不得用宽松 `meta` 承载稳定业务概念。
- `topic_validate` 应能在加载期发现 intake、disclosure、appears_when 和写作模式引用错误。
- 前端示例实例、测试 fixture 与当前官方议题名保持一致，不保留旧语义。

## 5. 阶段 2：轻量版用户问题设计

### 5.1 轻量版问题合同

轻量版议题问题不是逐议题自由扩展表单。除 `stakeholder_communication` 外，每个有独立报告章节的议题由两类问题组成：

1. `<prefix>.q_governance_roles`
2. `<prefix>.q_governance_policies`
3. `<prefix>.q_governance_certifications`
4. `<prefix>.q_strategy_content`
5. 专家定义的议题专属题：`<prefix>.q_<business_semantic>`

第 1、2、3、4 题由包内 `topic_intake_common.yaml` 展开；议题专属题由 `topic_intake/<topic_id>.yaml` 按专家反馈和真实 block/table 需求维护。不保留 `q_iro_*` 兼容层；新增 key 应使用业务语义命名。若问题清单无法可靠承载某项内容，应单独排期，并标记为材料门控候选、资产路线或专项数据层。

Block 映射规则：

- 治理支柱读取三道治理 common 题，覆盖组织职责、制度流程、认证资质。
- 战略支柱读取 `<prefix>.q_strategy_content`；战略风险/机遇表也可读取战略辅助题。
- 影响、风险与机遇管理支柱读取对应议题专属题；显隐条件必须基于真实题目和选项。
- 每个支柱节必须至少有一个不挂 `appears_when` 的无条件内容单元，否则可选资料不齐时支柱整节从正文与目录消失、违反准则四支柱结构。参考模板各议题在本支柱均有一条"依据治理模块上传制度提炼管理框架"的基础条目，对应无条件基础块读取 `q_governance_policies`/`q_governance_roles` 并配 `noFactGuidance`；该不变量由 `tests/test_non_climate_topic_modeling_batch.py::test_every_topic_pillar_section_has_an_unconditional_content_unit` 强制。
- 每个议题来源模板在 `section` 外必须且只能声明一个 `metricDisclosure.catalogMetricKeys[]`；空数组明确表示目录无映射，不表示隐藏。key 必须来自定量指标目录且不得重复。
- 来源 YAML 不手写指标 H3、图片、AI 正文、重要性条件或指标 key 副本。严格 parser 统一编译“指标与目标”H3、确定性图片和动态 H4；所有 AI 生成段落只声明 `generation.task`，不得预置模板占位 `content`。

### 5.2 设计原则

1. 每道议题专属题必须服务一组明确目的，并映射到具体 block、表格或显隐条件。
2. 中小企业优先使用选择题；补充说明框用于承接企业自有事实。
3. 不要求用户填写其通常无法判断的信息，例如量化财务影响、情景分析、第三方验证状态、人次、金额、减排量、复杂核算口径。
4. 负面或缺失选项只用于显隐和分支，不得直接变成正文里的“未做、缺失、未披露”。
5. `required` 只约束可见的结构产物或导出完整性，不把普通资料缺失升级为报告级阻断。块是否可生成由解析后的 selector、`blockType` 与显隐合同决定；若同一道多选题需要每类至少选择一项，应使用 `optionGroups` 表达分组最小选择要求。
6. 题干和选项应使用当前议题语言，避免误入相邻议题。例如气候议题中应避免把能源管理、环境合规、水资源管理、循环经济作为本议题正文边界。
7. 议题正文生成边界遵循 §3.4；如需让某议题复用其他议题事实，应先建立经确认的跨议题摘要事实层。

### 5.3 必填检查

议题专属题落地前必须回答：

- 这题服务哪些 block、表格、`appears_when` 或导出 gate？
- 用户不知道答案时是否仍可选择一个合理选项？
- 该题答案是否会诱发模型写负面缺失信息？
- 该题是否包含其他议题的术语或事实边界？
- 该题是否真的需要 `required: true`？

### 5.4 输出

`topic_intake/<topic_id>.yaml` 只保留专家定义的议题专属题、表格辅助题和特殊条件题。每个 item 必须包含稳定 key、题干、题型、选项或文本口径、hint、maxChars；key 使用 `<prefix>.q_<business_semantic>`，不得用 `q_iro_*` 作为通用容器承载不同业务事实。

## 6. 阶段 3：章节、block 与显隐

### 6.1 结构规则

1. 先定报告结构，再定输入题。题目不得反向牵引章节结构。
2. 每个议题章节是五个 ESG 报告模块之一的 H2。来源 `section.children` 必须且只能按“治理 → 战略 → 影响、风险与机遇管理”声明三个 H3；`metricDisclosure` 是唯一“指标与目标”H3 来源，`conciseDisclosure` 声明影响重要性或非重要性时的 H2 直属摘要。Planner 只按聚合重要性选择四要素或摘要分支，不创建通用占位正文。
3. 合并 H2 的成员重要性按两维结果聚合：任一成员具有财务重要性即采用四要素树，否则采用摘要分支。成员维度与适用性必须在注册表加载期一致。
4. 前四章、议题章节、附录是不同建模面，不得为了复用而混成单一工作纸或单一 schema 形态。
5. 每个 generative/constrained block 只能承担一个清晰写作职责；职责写入 `content` brief 或表格 caption，供 topic scope map 使用。段落 `content.text` 只写高层职责，具体事项由本块实际输入提供。
6. 具有独立段落语义的四要素内容单元可以声明 H4 `titleGeneration`，其生产者必须是直属段落生成块；表格、图片、固定内容和摘要分支不承担动态标题生成。
7. 前四章固定章节虽不放在 `topic_sections`，但同样遵守轻量版结构收缩规则：同一章节内同一 `intakeItems` 只由一个生成块消费；固定说明、slot 表格和 assessment 投影能表达的内容不改为无输入 LLM 块。
8. 支柱结构收缩纪律（回归归各 `backend/tests/test_*_topic_modeling*.py`）：
   同一支柱内同一 `intakeItems` 不被多个生成块无区分地反复消费，合法多视图必须由块职责与互斥
   `evidence_output_facets` 证明；缺少实质用户资料时，每个非指标支柱原则上 1 个主生成段落或 1 张表，
   有强业务必要时最多 2 个生成单元；结构问题先合并或删除 block、再调 prompt/context，不通过
   「不要重复」类提示掩盖。
  本节只约束**同一支柱内**。跨支柱的重复由生成侧时序处理：议题内按四支柱分阶段，先落定支柱的正文经
  `<prior_disclosure>` 进入后续支柱的任务视图（见 `docs/context-engineering.md` §6）。
  该机制与本节纪律同向——跨支柱重复的根因是「指令指向的内容当时还不存在」，加去重提示词无用。
  同支柱内仍无此机制，故本节的块职责互斥要求不因此放松。

### 6.2 显隐规则

1. 显隐必须由 planner、`fields`、`intakeItems`、`appears_when` 或证据门控（`material_gated`）表达，不交给 LLM 判断。
2. “无内容”优先隐藏、使用固定模板或一个简短的高层概述；主营业务只支持判断议题相关性。
3. 条件块进入生成前必须先通过 `visible`。隐藏块不得进 prompt、诊断和导出。
4. 如果一个模块下已有更具体事实块，通用兜底段应隐藏，避免重复和逻辑冲突。
5. **证据门控条件块**（`generation.inputs.evidence.kind: material_gated`）：块的存在性由证据判定——
   Mapping 判定 supported/partially_supported 的文件资料，或声明的 `intakeItems` 有实质答案，任一满足即出具；
   两者皆无时生成编排在 Mapping 之后、模型调用之前确定性置 `state="omitted"`，随 renderability 从正文与目录
   消失（复用表格受控省略同一落库与渲染链）。它与 `appears_when` 的分工：`appears_when` 在树装配期按已知
   条件裁剪（Mapping 只为可见块分配材料）；材料能否支撑一个块只有 Mapping 之后才知道，故由本机制承载，
   二者不可互替。适用判据（对齐 §5.2/§5.3 的问题检查）：
   - 该块要的材料类别（台账/记录/合同/凭证）能否被 File Agent 从 `content_markdown` 语义识别、被 Mapping 在
     章节级 scope 下按 `focus` 与 intake 提示路由到本块；
   - 无材料、无对应题时用户是否还有其他触达路径；彻底没有则先留 TODO；
   - 需要字段级精确抽取（编号、金额、日期）的内容不得由本机制承载精确值，只能写有据叙述，该边界写入
     `simplifiedWritingGuidance`；
   - 纯图片凭证（jpg/png）只能走排版素材图片链，不产出语义材料，不满足本门控。

### 6.3 校验

- `appears_when` 引用的字段和 intake key 必须可解析；`material_gated` 声明的 `intakeItems` 同样经编译期校验。
- 缺少实质企业证据时的行为由编译合同的 `absence_behavior` 派生：`fixed`/`slot` 确定性渲染；`material_gated`
  选择器的块受控省略（`omit_if_unsupported`）；其余 `constrained`/`generative` 块一律进入 `context_only`
  方向性生成——**`blockType: constrained` 本身不是省略信号**（现存条件块由外层 section 的 `appears_when`
  实现消失）。各分支均不阻断
  报告其他路径或 Word 导出。
- 报告范围差异必须由配置驱动，不得复制两套相似章节。

## 7. 阶段 4：准则内容梳理与逐块映射

### 7.1 准则披露要求入库

从准则与模板中抽取披露要求时，只把合规披露要求放入 `standard_disclosure_requirements/<topic_id>.yaml`。ReferenceTemplate-only 内容不是合规准则披露要求；当前不进入该库，未来如需模板参考，应单独建模：

- `standardDisclosureRequirementTitle`
- `standardDisclosureRequirementText`
- `disclosureRequirementObligationLevel`

不得把条款来源路径、内部 key、source refs、raw 文本、debug、provenance 或评分原始结构传入 prompt。

**锚点必须是准则原文，不得以参考模板充当合规锚点。** 一个条目对应一个官方披露要点（或一条指引条款），要求正文取自准则原文，义务等级按原文措辞派生：「应当」→ `required`、「鼓励」→ `encouraged`、「如有」「如涉及」→ `conditional`；同一要点内子项义务等级不同且系统处置不同时才拆条。出处标签使用受控格式：

- `excerptFrom`：上交所包 `上交所·指南第X号·披露要点N` 或 `上交所·指南第X号·第N章`；港交所包
  `港交所·附錄C2·<條文>`（繁體）与 `HKEX·Appendix C2·<provision>`（英文），條文为 `一般披露 A1`、
  `關鍵績效指標 A1.5`、`D部 第19段` 及其英文对应。
- `sourceClauseReferenceLabels` 的 SSE 条目：`指南第X号·披露要点N（指引第14号第X条）`；该要点在指引中无对应条款时（如碳信用类要点）省略括注。港交所条目 `{standard: HKEX, clauseRef: <條文>}`。

格式由 `backend/tests/test_standard_disclosure_requirement_source_labels.py` 守卫，其 `TEMPLATE_ANCHORED_TOPICS` 是尚未重锚定议题的台账，完成一个即移除一个。生成侧写作约束（「不得推断」「必须来自相关事实」等）不属于准则要求正文，应写入 `simplifiedWritingGuidance` 或 `task.focus`。

### 7.2 逐 block 映射

每个挂准则映射的生成块必须明确：

- 本块需要哪些准则披露要求 key。
- 哪些准则内容当前无承载块（留待材料门控候选或后续工作流）。
- 哪些词或内容属于相邻议题，应作为 redline 或 TODO。

生成不读取 `standard_disclosure_requirements` 进入 prompt（注入属整体待办）。唯一块任务写入 `generation.task.focus`，单议题特殊低证据边界写入 `task.noFactGuidance`；显隐和输入边界写入 `appears_when` 与 `generation.inputs`。`focus` 必须在有无事实时都成立，不得要求无依据的责任分工、组织结构、既有体系或实施结果。`simplifiedWritingGuidance` 只保留正式术语映射、跨块边界、对象来源、表格行合同或需要直接证据支持的具体度边界。低证据写作示例由支柱语义集中拥有并按支柱条件投影，不复制到议题 YAML，也不替代模型正文。

### 7.3 校验

- `standardDisclosureRequirementKeys` 必须能解析；加载期失败应 fail-loud。
- 一个准则披露要求不得为了省事映射到整个议题所有 block；只映射到真正需要覆盖该要求的块（如举报机制 key 只挂举报块）。
- 用户可见准则批注与准则披露要求映射分开维护，不复用内部字段。
- 每条 `required` 要求必须在包内 `standard_disclosure_requirement_coverage.yaml` 有显式审定状态（五态见该文件头注）；`bound_to_block` 必须真被某个块引用。审计由 `backend/tests/test_standard_disclosure_requirement_coverage.py` 逐议题参数化执行——新增或改名 requirement key 时，要求库、块绑定、审定表三者必须同批更新。

## 8. 阶段 5：表格建模

### 8.1 建模策略

1. 重要表格优先一表一建模，尤其是准则或评审会逐列检查的表。
2. 能用现有 generative table 表达的，不新建表格引擎；先使用 `rowCount`、`colDefs`、`options`、`genHint`、写作模式参考和 L1 断言。
3. 表格列值应短、并列、可扫描。首列名称长短保持一致；措施列使用短句或换行分隔。
4. 当评审风险来自“漏项”时，默认全量覆盖，再由用户删减。例如价值链影响可默认覆盖上游价值链、公司运营、下游价值链。
5. 表格中统一用“公司”指代报告主体；公司简称通常留给段落。

### 8.2 表格验收

每张表必须检查：

- 是否需要固定行、AI 定行，还是用户加行。
- 每列是否有明确 `cellType`、`options` 和必要的 `genHint`。
- 哪些列需要 block 级 L1 断言，例如必含选项、禁止公司简称、最大长度、分行格式。
- 生成失败时应阻断、保留 failed 行，还是隐藏表格。
- Word 导出是否保持表头、跨列标题、换行和列宽可读。

## 9. 阶段 6：LLM 生成配置与上下文边界

### 9.1 block 生成配置

每个生成块的 `generation` 至少应说明：

- `task.focus`，以及仅在单议题确有特殊低证据边界时使用的 `task.noFactGuidance`
- `inputs.evidence`：普通块使用 `explicit` 并声明 `intakeItems[]`；指标块的 `quantitativeMetrics[]` 由 `metricDisclosure` 编译；`conciseDisclosure` 使用 `report_section`
- 仅当前块额外需要的 `inputs.fields`
- `targetChars` 或 `rowCount`
- `simplifiedWritingGuidance`（仅限正式术语、跨块边界、对象来源、表格合同或议题特有具体度边界）
- `standardDisclosureRequirementKeys`（准则披露要求映射，数据资产；注入 prompt 属整体待办，内容 scope 不写在这里）
- 必要且可确定性检查的 `redlines`

`GenerationTask` 是任务语义的唯一 owner；`focus` 说明当前块要覆盖的对象与边界，不写成“围绕某标题形成正文”，不预设企业已有某项安排，也不规定没有稳定结构依据的句式。不得从 `Block.content`、支柱标题或块类型推断任务，也不得在 Profile、EvidencePosture 和议题 guidance 重复描述同一职责。结构性必含要求使用 typed output、显隐合同或确定性校验；事实型专项块由 `appears_when` 控制时，不再用 `noFactGuidance` 重复描述缺料行为。

`conciseDisclosure` 不重复维护题目或指标 key。`report_section` 读取同一 H2 的有效内容清单答案，并从该 H2 的已编译 `metricDisclosure` 继承完整指标目录；无值目录不构成实质企业事实，且摘要不继承 `MetricNarrativePolicy`，因此不得生成指标体系、统计或披露计划。

### 9.2 上下文边界

1. System 从适用 Prompt Profile 取得角色、表达规则和正文格式，再承载报告主体、H2–H4 章节位置、必要的共享证据分工、唯一任务、证据姿态及各类 typed 专项片段；`PillarPurpose.writingFocus` 不进入模型可见 Prompt。普通 context-only 段落可按解析后的正式支柱选择该支柱的少量校准示例，不跨支柱混用。未来新的报告受众（上市公司、出海企业等）须使用与其适用范围一致的独立 Profile。
2. User 只承载由 `GenerationEvidence` 投影的用户事实和指标证据，经转义后进入 `<filled_content>`；Guardrail、Judge 与专家 artifact 消费同一 Evidence。
3. 不得把 audit、provenance、raw、manifest、fingerprint、source_refs、path、debug、内部字段结构或评分原始结构直接传入 prompt。

### 9.3 生成语义边界

轻量版报告全局遵守两条语义边界：

- 缺少本块事实不解释为企业存在能力短板或负面状态；可以表达行业普遍、基础和正常经营所需的安排，但不坐实存在性不确定的特定对象、设备、废弃物类别、专项项目、命名机制或成熟体系。
- 相关事实可以支撑一般性的正向管理归纳；新增负向事实，或金额、日期、固定频次、特定对象、正式名称、专项措施、项目和具体实施结果等可独立核验信息，需要当前 Evidence 的直接支持。

## 10. 阶段 7：L1 断言与测试

### 10.1 断言与测试的分工

- L1 断言是在线运行期 gate：生成后立即检查，高确定性失败时阻断并触发有界重试，最多 3 次。
- 测试是离线回归机制：验证 YAML 装配、显隐、阻断、断言谓词和前端流程是否持续有效。
- 二者可以共用样例，但不属于同一层；不能用离线测试替代运行期断言，也不能用 L1 替代覆盖率测试。

### 10.2 L1 断言来源

通用断言放在统一模块；议题或 block 特有断言优先通过配置进入：

- 通用：内部字段泄漏、本地路径、Markdown、空输出、缺失/负面表述、未支撑数字、未支撑正式名称、表格必填单元格。
- block 配置：仅保留仍可能进入当前 Context、且确属单一议题的 `generation.redlines`。
- 必要时扩展：表格列格式、固定选项必含、正式名称来源、称谓统一和长度上限。

### 10.3 断言准入标准

新增 L1 断言前必须满足：

- 错误可由规则高确定性识别。
- 误杀成本可接受，或可配置到具体 block。
- 失败信息可转化为模型可执行的重试指令。
- 断言有对应单测。

宽泛风格判断、事实优劣、表达好坏、行业充分性不应直接做 L1；应进入 eval 样例、人工评审或 block prompt 调整。

### 10.4 测试清单

每个议题至少考虑以下测试：

- `topic_registry`：官方名称、维度、适用性、合章映射。
- `topic_validate`：Evidence selector、`standardDisclosureRequirementKeys`、`appears_when` 引用与章节归属可解析，摘要能继承本 H2 的内容清单和指标目录。
- planner：科技伦理等适用性装配正确。
- intake：题目、选项、`optionGroups`、required、前端展示顺序正确。
- generation context：内部字段不进入 prompt；准则要求 key 由覆盖判定与块级 span 消费，当前不注入 prompt（见 §7.2）。
- L1：新增 redline、正式名称来源或 block 特有断言可阻断，其他议题证据不能旁路放行。
- table：列 key、行数、必填、结构化输出、Word 导出可读。
- frontend：矩阵、评估表、议题页面题目名称与官方议题一致。

## 11. 阶段 8：特殊事项 TODO

不适合当前议题批次立即实现的内容，必须单独排期记录，不得散落在 prompt、注释或测试 fixture 中。

应进入 TODO 的事项包括：

- 依赖未来数据库、客户主数据、上传资料、KPI 总表或外部集成的数据链路。
- 需要跨议题统一设计的表格、指标、图表和导出样式。
- 承载方式（证据门控/指标/资产路线）未完全定义的披露要求。
- 需要人工决策的业务边界、适用性判断或产品流程。
- 当前只完成骨架但后续需精细化的一表一建模。

TODO 条目必须包含议题 id、事项、为何暂缓、后续需要的输入或决策。

## 12. 议题完成验收清单

处理完一个议题后，逐项确认：

- 官方议题名、维度、报告二级章节和合章关系正确。
- 基础 schema 能通过 Pydantic、生成类型、API、前端状态、LLM 上下文和导出链路表达，不需要各层猜 shape。
- 轻量版用户问题可由中小企业回答，且每题用途明确。
- 难以填写、易诱发编造的问题已删除或改成选择题/默认表格。
- 所有生成块都有清晰职责、输入、写作口径、由 `EvidencePosture` 投影的事实权限和字数/行数边界；有合规准则资产的块另有准则映射。
- 普通资料缺失按当前 `ReportProfile` 与显式生成合同局部省略或方向性生成，不从 `blockType` 推导；
  只有权威结构诊断、权益或真正必需的产物结构可以阻断。
- 表格列定义、默认覆盖、短句格式、主体称谓和失败行为明确。
- L1 断言覆盖高确定性错误，测试覆盖断言谓词和装配链路。
- 前端题目、矩阵、评估表、报告正文、Word 导出使用同一官方名称和同一结构链路。
- 未处理事项已进入 TODO，而不是隐藏在临时注释或 agent 记忆中。
- `uv run pytest` 及必要前端测试通过；若未运行，需说明原因。
