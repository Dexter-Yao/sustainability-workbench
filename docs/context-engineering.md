<!-- ABOUTME: 报告生成上下文工程的长期真相源，定义模型可见边界、装配流程与运行治理。 -->
<!-- ABOUTME: 数据形态以 schema-contract.md 为准；本文只管如何把权威事实投影为可生成、可评估的模型任务。 -->

# 上下文工程

## 1. 定位

上下文工程是 本产品 Harness 中把业务事实交付给模型的边界层。它连接 `Report / Section / Block`、用户资料、Prompt Profile、模型调用、解析、守卫、运行观测与评估，但不拥有这些事实。

```text
权威事实与配置
  → CompiledReportDefinition（确定性关系入口）
  → Planner 装配 canonical Report
  → 选择 node 与 task-specific runtime inputs
  → build_model_context（唯一模型白名单投影）
  → render_*_prompt（任务专用消息）
  → Pydantic AI 结构化调用
  → 解析与 L1 guardrail
  → 原子写回、有限重试或阻断
  → 完整 AI 调用轨迹 + typed eval / 人工反馈
```

数据契约以 `docs/schema-contract.md` 为准；议题边界以 `docs/topic-construction-guide.md` 为准。

## 2. 设计原则

1. **模型只看到完成当前任务所需的事实。** 原始应用状态不能直接进入 prompt。
2. **先解析，再投影。** 用户答案、定量指标、报告主体和准则要求先进入领域结构，再转换为任务专用 `ModelContext`。
3. **一项事实只有一个权威所有者。** 结构与块级生成配置在 `topic_sections`，填写项在 `topic_intake`，准则要求在 `standard_disclosure_requirements`，跨议题角色与表达规则在命名明确的 Prompt Profile。
4. **不同生成形态独立装配。** 公司摘要派生、段落、普通表定行与补行、固定目录表和自适应目录表可共享底层事实，不共享一份万能 prompt。
5. **确定性规则留在代码。** 显隐、必填、表格列、指标展示、输出解析和高确定性禁线不交给模型判断。
6. **System 承载任务与约束，User 承载经转义的用户资料及任务专用行种子。** XML 标签只由系统生成，用户文本不得伪造结构或指令。
7. **缺少用户资料是一条正常生成分支。** 它决定证据姿态、篇幅和可陈述范围，不属于故障或 fallback。
8. **模型输出必须经过类型解析与在线守卫。** 解析失败或守卫问题只允许有限重试，不能静默放行。
9. **Prompt Profile 必须声明适用范围。** 企业类型、报告版本、披露市场或语言发生实质变化时新增独立 Profile；不在一份 Profile 内累积条件分支。
10. **上下文片段各自只承担一种职责。** Prompt Profile 只定义兼容范围、上下文字段、角色、表达和输出格式；`GenerationEvidence` 定义模型实际看见的事实，`EvidencePosture` 定义事实强度，`GenerationTask` 定义本块主旨。typed 条件只在语义确有变化时替换对应片段，不以追加提示形成多重 owner。
11. **导航与模型上下文分层。** 定位节点、判断状态与决定可做什么，都由确定性编译定义与诊断回答；只有选定节点和任务后，Harness 才构建 task-specific `ModelContext`。任何一步都不注入完整 Report 或 MaterialWorkspace。

## 3. 配置与事实归属

| 信息 | 真相源 | 模型可见投影 |
|---|---|---|
| 报告结构、块任务、显隐、长度、输入白名单 | `backend/data/knowledge_packages/*/topic_sections/*.yaml` 的 `Block` / `GenerationSpec` | 当前块任务、篇幅、必要边界 |
| 用户填写项 | `backend/data/knowledge_packages/*/topic_intake/*.yaml` 与 `Report.intakeItems` | 题目、用户答案和补充说明 |
| 轻量版写作颗粒度 | `GenerationSpec.simplifiedWritingGuidance` | 仅轻量版 System |
| 准则披露要求 | `GenerationSpec.standardDisclosureRequirementKeys` → `standard_disclosure_requirements` | **当前不注入**（`build_model_context()` 恒为空元组）；渲染段与加载器投影已就绪，接通属待办，见 §5.5 |
| 报告主体 | `Report.fields` | 公司简称、年份、行业、主营业务概述等白名单短事实 |
| 定量指标 | 指标目录 + `Report.meta.quantitativeMetrics` | 指标名称、单位、必要维度与已填写值 |
| 资料搜集与清洗 | `MaterialWorkspace`、目标题定义与局部证据 | 仅当前资料任务所需的文件状态、证据片段、缺口、提案与确认 |
| 跨块结论 | `GenerationSpec.producesConclusion`（产出方唯一，编译期校验） | 仅结论正文本身，经 `<iro_context>` 以业务名称呈现 |
| 议题内已披露正文 | 报告 Section 树的支柱归属 + 在先支柱已 ready 的段落正文 | 仅支柱名与正文，经 `<prior_disclosure>` 呈现；不含 blockId 与生成状态 |
| Prompt Profile（每知识包一份） | `backend/data/knowledge_packages/<package_id>/prompt_profile.yaml`（`sse_zh_hans`、`hkex_zh_hant`、`hkex_en`、`gri_en` 各一份） | 角色、公开报告正文体裁、表达指导、输出格式与全部代码渲染标签（含 `selected_lead`/`supplement_lead` 等答案投影词） |
| 输出语言 | `package.yaml` 的 `language` → `ModelContext.output_language`；确定性指令表与长度单位在 `backend/src/sustainability_desk/contract/language.py` | System 首段 `<output_language>`；篇幅按字（中文）或词（英文）计 |
| 非实质答案 | `contract/language.py` 的 `NON_SUBSTANTIVE_ANSWERS`（按语言） | 「不确定／暂无／Not sure」类选项不投影为公司事实，只影响证据姿态 |

`IntakeItem.hint` 只服务人类填写界面，不进入模型。需要约束生成的题目边界写入 `generationBoundary`。内部 key、路径、source refs、provenance、原始评分、debug 和未进入模型的应用状态不得进入 `ModelContext`。

Prompt Profile 的 `profile_id` 表示稳定语义家族，`schema_version` 表示配置形状，`contractVersion` 表示参与生成的契约文件精确内容，`promptFingerprint` 表示一次调用实际渲染的消息与模型设置。四者职责不同，不用 Profile ID 代替内容版本哈希。

## 4. `ModelContext` 合同

`backend/src/sustainability_desk/llm/prompts.py::ModelContext` 是报告正文生成共享的任务上下文。生产调用向 `build_model_context()` 提供 `CompiledReportDefinition + canonical Report + selected canonical Block + task-specific runtime inputs`；Block 的稳定 ID 用于读取编译后的节点位置、议题范围、相邻职责、输入消费者、缺失分支和准则 owner，不再由 Context 层重新遍历 YAML 或猜测 Section 关系。`contract/evidence_resolution.py` 先把编译后的 intake/metric selector 与当前 Report 解析为同源实质证据状态，View、Journey 与 Context 均消费该领域结果；Context 再投影冻结 `GenerationEvidence`。Prompt、Guardrail、Judge `CaseInputs` 与专家 artifact 只消费这一份模型可见 Evidence，不得再次查询完整 Report 补事实。表格列规格、`RowSeed`、目录锚点及行级支持状态作为任务专用 typed payload 由对应 renderer 组合；公司业务摘要派生使用独立输入合同，不冒充正文生成分支。仅测试中的合成 block 可使用无编译节点的显式 selector fallback，生产 canonical node 必须解析成功。

模型可见内容包括：

- 当前任务的角色、公开报告正文体裁、报告主体、`SectionPlacement` 和有效 `section_task`。生产 canonical node 的 `SectionPlacement`、支柱语义与任务都从 `CompiledReportDefinition` 读取，只说明正文位于哪里和当前块写什么；合成测试 fallback 才从局部 typed Report 解析。H1 不进入段落调用，`PillarPurpose` 只保留为支柱解析、指标模块识别和合同检查所需的 typed 语义，不进入生成或 Judge Prompt。只有其他块与当前块共享同一 typed Evidence 时，才投影相应分工。
- 当前分支适用的证据姿态、公开披露距离与轻量版指导。
- 经输入白名单筛选和 XML 转义的用户资料。
- 选择题保留在 `Report` 中的原始答案可按 `IntakeItem.generationOptionLabels` 投影为任务所需的对外披露语义；该投影在 `ModelContext` 边界完成，不改写原始事实。
- 经白名单解析的议题重要性与 IRO 结论，不含原始得分。重要性只供 Planner 选择内容树，不在正文调用中重复；存在 IRO 条目时才把议题名与 IRO 结论投影给模型。合并 H2 必须通过 `assessmentTopicsByReportSectionId` 解析全部成员的独立 `AssessmentBrief`，不得按字符串相等只命中其中一个评分议题。
- 指标展示策略、必要定量事实和表格行种子等当前任务所需控制值。

`GenerationEvidence` 包含 `intake_facts`、经当前 `BlockMaterialDecision` 明确采用的 `mapped_materials`、`metric_evidence` 与同源计算的 `substantive_input_present`。`mapped_materials` 只携带 File Agent 已冻结的 `FileMaterial.content_markdown`，不携带 dossier、材料 UUID、scope、来源路径或 Mapping reason。指标目录始终保留名称、分类和单位；只有数值、用户备注或核算标准构成指标实质事实，缺值不渲染为“未填写”。无值指标正文由 `MetricNarrativePolicy` 与 `metric_narrative` `EvidencePosture` 共同拥有专项表达；后者显式覆盖普通 `context_only`，因此生成与 Judge 不依赖 Prompt 片段顺序判断优先级。指标名称只由 policy 投影，用户备注或核算标准作为事实单独呈现一次，不恢复单位、分类路径或空值状态。有实质事实时可注入轻量版专项指导和普通篇幅上限；普通无事实时投影 `context_only` 与必要的 `noFactGuidance`。输入显隐已拥有缺料行为的块不得再声明 `noFactGuidance`。

报告主体信息只用于称谓、术语和判断当前任务的相关性，不支撑企业具体做法。其中主营业务概述由公司简介压缩而来，业务事实本身已在「关于公司」正文完整披露，故它在其余块只作背景参照，不在正文复述。该边界由 `EvidencePosture.sourceUse` 单点投影，不恢复独立 `report_subject_usage`。普通 `context_only` 正文仍是公开报告正文：可采用审慎、概括、低承诺的企业报告语态，说明行业普遍、基础且正常经营所需的管理关注、原则、持续改进或方向性安排；不得把行业相关性、主营业务背景或指标目录改写为可核验的企业事实，也不得补充具体组织、制度、项目、设施、数值、频次、认证或结果。“逐步完善、持续推进、后续推进”是可用的低承诺表达，不是默认建议书句式。治理、战略和影响/风险/机遇管理支柱可各自使用少量报告体例校准示例；不同支柱不共享示例，表格、有事实段落和无值指标专项不接收该片段。

报告正文不使用完全固定文案替代模型生成。Harness 可以确定性控制输入投影、分支选择、结构化输出、显隐、重试和高确定性断言，但正文表达继续由模型在当前 typed context 内完成；法规原文、指标图和其他本来就属于确定性投影的内容不受此限制。

利益相关方沟通表属于确定性结构，不是正文生成任务。其适用议题、八类对象、多对多关系、受控方式和用户自定义方式由 `StakeholderEngagementProfile` 与 `stakeholder_engagement.yaml` 共同拥有；该 Profile 不进入 `ModelContext`、Prompt、生成输出 Schema、Guardrail 或 Judge。Planner 只做范围协调，网页与 Word 从同一 Profile 投影。

模型不可见内容包括：

- `Report` 原对象、数据库对象、权限状态和审计记录。
- block / metric / fixture 的内部定位 key 与文件路径。
- provenance、source refs、原始评分、调试数据、观测 metadata 和密钥。
- 人工标签、Judge 结论以及未进入当前任务的其他块内容。

### 4.1 资料 Agent 上下文边界

资料理解、章节映射和正文生成使用三个独立 context constructor；它们共享版本化领域对象，不共享万能
Prompt、完整 workspace JSON 或未裁剪的历史消息。

| 任务 | 启动上下文 | 可按需披露的能力 | 输出 | 禁止能力 |
| --- | --- | --- | --- | --- |
| File Agent | 当前原文件 capability、文件名与格式、`UserFileDeclarationRevision`、最少报告身份、由 `EffectiveReportScope` 裁剪的紧凑报告需要、产品任务与完成条件 | `convert_file` 转换当前文件；`read_file` 完整读取一份转换产物。单文件 Agent 没有 `list_files`、局部范围或视觉工具 | 候选相关性、相关性理由、一个或多个 `FileMaterial`、`AttentionItem` | 读取其他文件、最终采用决定、全部 Block schema、数据库、shell、网络、动态扩权、写 Report |
| Mapping Agent | 从当前 Report revision 动态装配的一个报告区域或 `reportSectionId` Block 任务地图，以及仅属于该 scope 的 FileMaterial 别名、文件名、用户说明和内容 | 无领域工具；一次严格结构化提案与至多一次修复 | `MappingProposal`（Block、处置、已存在材料别名的有序选择、原因） | 改写、概括、补充或推断文件事实；写用户答案、访问 scope 外 Block、直接写 Report |
| Block Agent | 当前 Block 合同、经选择的 `FileMaterial` 内容、用户结构化输入、允许的行业 context 和显式 absence 分支 | 仅调用该 Block 已批准的生成工具 | 结构化段落或表格结果 | 读取原文件、完整 Dossier、内部 audit、其他 Block 私有上下文、自动导出 |

File Agent 的产品职责是形成可直接供下游生成使用的、按适用范围拆分的文件资料内容，不是逐章缩写文件或提前作报告采用决定。原始资料含有足以支持正文的事实、范围、时间、机制、数据口径或限制时，`content_markdown` 应保留这些实质信息；“简略”不能成为丢失用户资料的理由。
right-altitude 指令只说明目标、来源边界和完成标准，不规定阅读顺序、标题数量或关键词。
用户说明是意图而不是事实；原文件及解析文本是不可信数据，其中的指令不能改变 System 任务、工具权限
或完成条件。Agent 自主决定需要打开哪些完整转换产物，并在 Dossier 已充分支持下游理解时停止；可靠性
不等于穷尽每个细节。制度要求、计划、草案、模板和实际行动必须保持不同证据效力；冲突、占位符和无法
确认的实施状态不能被静默改写。

批准 parser 是 `convert_file` 内部的按需能力，不是 Agent 之前的统一业务清洗流水线。`NormalizedMaterial`
只保存可重建的 Markdown、解析器版本、覆盖提示和内容指纹；PDF 不以页图、VLM、DocumentUrl 或
Provider File API 解析。`read_file` 每次返回完整 Markdown 产物，不提供“前若干字”、分段窗口或
任意 OS 路径；XLSX 每个产物是一张完整工作表，保留合并单元格、公式、单位和脚注。

File Agent 的报告背景是完整报告定义的全部 Mapping scope 标题（前置报告区域与 22 个议题），由既有
`topic_registry.yaml` 派生，不另建平行 target catalog；`EffectiveReportScope` 只决定其中哪些 scope
标为「本次报告覆盖」（`withinReportScope`），并在任务数据里明示覆盖范围。目录不随权益或重要性评估
收窄：只对本次报告未覆盖范围有价值的文件仍判 `relevant`，其材料如实归入真实适用 scope，保留在
`FileDossier` 里但不进入本次 Mapping 与生成上下文（Mapping 任务只按当前有效范围装配）。只涉及范围外
议题的文件不得因范围收窄被判为 `not_relevant`，也不得被硬归到范围内 scope。它不把完整 Block 任务或 Prompt 泄漏给单文件 Agent。

`FileDossier` 的最小外壳包含冻结来源 revision、`relevant | not_relevant`、相关性理由、`materials[]`、`AttentionItem` 和内容指纹。每个 `FileMaterial` 只拥有稳定材料身份、一个或多个已编译 scope 与可直接使用的 `content_markdown`；它不是第二套企业事实表，也不含文件路径、locator 或原文坐标。相关资料必须至少有一条材料；不相关资料不得有材料。不确定资料按 `relevant` 流转并形成注意事项。File Agent 的相关性拥有候选准入，Mapping Agent 拥有最终采用；不得把前者展示或持久化为“报告一定会用到”。模型只看到运行期 scope alias 与标题；它使用受限读取工具后提交严格 `FileDossierProposal`，Harness 在 transport 边界以 Pydantic 解析其原生嵌套值或 provider JSON 字符串字段，再构造 `FileDossierDraft`、将 alias 解析为 compiled scope id，并以已读状态和来源 revision 冻结 `FileDossier`。领域对象不得兼容解析模型字符串化数组、字符坐标或其他协议失配。

统一装配层从当前 `CompiledReportDefinition` 与实际 Report revision 派生任务，不维护平行 target
catalog：ESG 议题按 `reportSectionId` 形成 Scope，前置章节等非议题生成内容按报告区域形成 Scope，
并只保留当前 Report 中实际存在的 Block。每个 Block 的模型投影包含语义任务、可理解的信息需要和
缺失行为；内部 owner ID 留在 typed 合同与审计中，不作为模型理解任务的唯一线索。Agent 先看当前
Scope 任务地图与 FileDossier 材料范围共同派生冻结 `mapping_plan`。MaterialSetSnapshot 冻结全部已理解的 active 语义资料供审计和未采用说明；每个非空 scope 只接收其路由 dossier id，运行时再投影其中属于该 scope 的材料。没有材料路由到 scope 时不创建 Mapping Run，也不制造零资料决定。不存在“全局资料”布尔值：跨议题或前章材料必须显式列出多个已编译 scope。新增或变更资料仍交给其实际适用 scope 判断，以免入口路由造成 false negative。

Mapping System Prompt 只稳定声明角色、工作背景、输入边界和输出边界；具体 Scope、Block 和已路由材料由装配层放入运行时任务上下文。Mapping 不撰写、润色、概括、合并或创造企业事实，只为每个 Block 选择既有材料及其顺序和处置。模型输出 `MappingProposal`，其中只含 Block、处置、材料 alias 和原因；Harness 解析 alias、验证完整覆盖、scope 边界和材料身份后形成 `BlockMaterialDecision`。初次结构化提案后，parse 或语义校验失败最多携带结构化错误摘要修复一次；第二次仍失败则 fail closed 并持久化失败 receipt，不产生半套材料选择。

每个进入 mapping plan 的 Block 必须且只能形成一个 `BlockMaterialDecision`。当前唯一状态集合为 `supported`、`partially_supported`、`context_only`、`needs_attention`、`not_applicable`：前两种必须引用至少一条已路由材料；`context_only` 表示本次没有可采用的文件材料、轻量版按当前 Profile 仍可生成低承诺公开报告表达，`needs_attention` 保留不确定或冲突，`not_applicable` 只用于当前 Report 实例确实不适用的目标。未进入冻结 mapping plan 的 Block 不写 `BlockMaterialDecision`，而是确定性取得 `no_applicable_file_dossier` 处置。parser 或 Agent 技术失败是运行状态，不得伪装成 `context_only`、资料缺失或不适用。

ESG 定量信息不经过 File Agent 或 Mapping Agent。用户在线填写和专用 XLSX 模板导入先由定量 parser
写入 `QuantitativeMetrics` SSOT，再按 `quantitative_metric_ids` 确定性投影为 Block 的
`MetricEvidence`。Mapping 任务地图可以显示当前 Block 关联的指标名称与单位，帮助 Agent 判断
FileDossier 对指标管理方法、口径或数据质量机制的增量价值，但不向 Agent 提供指标值，也不允许它填写、
复制或覆盖结构化指标。正文生成时，用户结构化回答、`MetricEvidence` 与经采用的 `FileMaterial`
作为三个明确来源分支在唯一 `ModelContext` 中汇合。

经校验 Proposal 成为 `BlockMaterialDecision`，但不改变 File Agent 拥有的材料内容。用户表单保持独立
owner；Block 上下文同时读取结构化输入与被选择的材料内容。轻量版可自动采用材料，AttentionItem 不阻断生成。

正文 `ModelContext` 只投影当前 Block 真正需要的事实内容、来源标签、控制值、写作规则和 absence 分支。
完整 Dossier、原文件、对象路径、Prompt 版本治理字段、工具轨迹、成本、debug 和用户不应看到的 audit
信息均留在模型上下文之外。缺少企业事实的轻量版 paragraph 使用 `context_only`，不得从 block type
推导统一省略；确定性显隐为假、无数据表格或缺值可选句才可形成显式 omitted disposition。

File Agent 按文件有界并发，Mapping Agent 按适用章节有界并发，Block Agent 按适用 Block fan-out；所有
真实 HTTP 调用与重试共用一个全局信号量和预算计数器。Agent 之间不直接共享聊天历史，只通过持久化、
指纹绑定的 FileDossier、MaterialSetSnapshot、FileMaterial 和 BlockMaterialDecision 衔接。任务以租约、幂等键和输入指纹恢复，
不能把未完成 trace 或单个成功输出冒充完整覆盖。

一份追加式 Run/Event ledger 派生用户进度、普通 Word、审阅版 Word 和内部审计包。审阅版是从
`CustomerCommentaryPackage` 渲染到与普通 Word 同一 `DocumentRenderPlan` anchor 的真实 Word comment：封面总体说明锚定报告主体名称，正文只解释
该可见内容的文件级资料依据、已采用范围或审慎呈现原因，不包含待确认、建议操作、System Prompt、
内部路径、成本、私有工具策略或 debug。用户投影必须由独立白名单合同生成，不能通过“内部包删字段”得到。
内部审计包保存冻结领域对象、收据、确定性 Word 导出凭证与原始 trace 的稳定引用，并随受限 ZIP 交付可严格
解析的 JSONL 快照；ledger / observability 仍是实际模型上下文、Prompt、工具调用、重试与成本的唯一 owner。
两种投影都不记录、推断或展示模型思维过程。

运行时 Harness 只验证结构、文件版本、只读路径、至少一次真实读取、调用记录和收据，不再调用第二个
模型 Judge，也不以 locator 或逐句事实校验触发整份 Dossier 重写。语义质量通过代表性真实文件生成的
人工审阅 artifact、trace 与端到端报告结果评价。结构测试只能证明边界，不能替代产品质量评估。

`substantive_input_present` 由解析后的真实用户事实确定。无资料选项、未填写数值和行业参考不构成企业事实。它与 `evidence_posture` 同源，并决定低证据分支的陈述距离与段落上限。

低证据分支只说明基础关注方向和可逐步推进的通用工作；具体组织职责、对象、设备、废弃物类别、专项项目、命名机制或成熟体系仍需直接事实。本地就业、技能培训、志愿服务和物资支持仅在“乡村振兴与社会贡献”议题内作为经人工确认的正常状态示例，不扩展为跨议题规则。该边界由同一 typed `EvidencePosture` 投影给生成与 Judge，不以“行业普遍”作为推导企业实践的授权。

已有块级事实时，模型可以用与已填制度、流程或生命周期事实直接相关的行业通用流程类别组织内容；类别名无需逐字出现在用户答案中。具体文件、审批节点、责任矩阵、敏感对象、设施、专项项目和可核验实施状态仍须由用户事实支持。

相关用户事实也可以支撑一般性的正向管理推断：模型可将其归纳为通常的管理安排、运行过程和成效，不要求正文逐字复述输入。严格边界位于新增事实的方向和具体度：不得由一般性或正向资料推出负向事实；金额、日期、固定频次、特定对象、命名制度或系统、专项措施、项目和具体实施结果必须有直接事实。制度文件名、非公共缩写、用户简称及带引号的企业原则或口号还要通过当前 Evidence 的逐字来源 Guardrail；部门、岗位、委员会、办公室和工作组等组织职责表达不使用词面规则，相关事实边界由 EvidencePosture、Judge 与人工复核判断。ESG、IRO、ISO 等公共术语由受控公共语义处理，不使用通用缩写黑名单。

## 5. Prompt 与生成分支

### 5.1 段落

`render_prompt()` 生成 System/User 两条消息。段落 System 按稳定度组织 `<role>`、Profile 拥有的 `<report_body_contract>`、纯语言层的 `<expression_guidance>`、`<report_subject>`、`<section_placement>`、`<evidence_posture>`、`<section_task>`、必要的 `<topic_scope>` 与 `<prior_disclosure>`，再追加当前任务真正需要的准则、指标、内容清单边界、局部议题指导、`<output_contract>` 与 `<content_format>`；不再投影支柱职责，也不存在混装职责的 `<domain_rules>`。`report_body_contract` 只定义公开报告正文而非咨询建议；`section_placement` 只投影 H2–H4 稳定位置；`expression_guidance` 负责通用语言质量；`evidence_posture` 负责事实权限；`section_task` 只投影一次证据中性的 `GenerationTask.focus` 及必要的 `noFactGuidance`。
`<topic_scope>` 与 `<prior_disclosure>` 是两件事，必须分段：前者说相邻任务**负责**什么（事前边界，
内容尚未生成），后者说报告里**已经写了**什么（既成事实，来自在先支柱已 ready 的正文）。合并两段会让
模型分不清哪些是计划、哪些已发生，进而把尚未落定的内容当作已披露。`<prior_disclosure>` 只承载支柱名
与正文，不含 blockId、生成状态与节点结构。治理、战略或影响/风险/机遇管理支柱的普通 `context_only` 段落可在任务之后追加 `<context_only_calibration>`，生成与 Judge 从同一支柱语义 resolver 取得报告体例的低承诺示例；`metric_narrative` 只由无值指标专项使用，不投影该校准。纯重要性结论不进入 Prompt，只有实际 IRO 条目进入 `<iro_context>`；条目来源是用户在评分表确认的 IRO 优先，未确认时取本轮 IRO 表已确定的结论，两者都以业务名称（影响 / 风险与机遇）呈现，不暴露内部 kind 枚举。`<iro_context>` 以固定方向性前缀开头，只要求正文与既定方向一致、不得给出相反判断，不规定措辞与详略，也不因此坐实未由用户资料支持的做法；方向一致性不做词面断言。普通段落只显示篇幅上限；context-only 不显示普通篇幅，无值指标专项仍使用 60–160 字口径。User 只包含由 `GenerationEvidence` 渲染的 `<filled_content>`；没有模型可见事实时使用空元素，不重复写“用户未填写”。

内容清单答案与补充说明在 `<item>` 内结构分离：答案本体是企业事实正文行，补充说明以
「用户说明」独立行呈现（`Material.note`，与资料 userNote 同一渲染面），eval/Judge 经
`QuestionAnswer.supplement` 取得同一可见范围。补充说明中「暂无成文制度」「暂未设置」类状态说明
由 prompt profile 的 `evidence_postures.block_facts`（经 `resolve_evidence_posture` 解析）声明为披露口径信息而非可披露事实：正文不得出现对应的缺失、未做类陈述，
相应内容按已有做法与低承诺方向性安排表达；L1 `missing_or_negative_statement` 的重试指令携带同一
修复方向。多次尝试仍未成功时报告级失败以用户可行动语言投影（指出未完成的议题与填写建议，
不暴露守卫、断言与重试机制），块级成功语义由 `unsuccessful_generation_results` 单点判定。

### 5.2 表格

- 普通表格先使用固定种子或 AI 定行，再按受控 `RowSeed` 补全一行；列头、选项和 `genHint` 来自 schema，单行 User 由 `<row_seed>` 与 `<filled_content>` 组成。
- `rowSource=stakeholder_engagement` 的利益相关方表不进入上述生成分支，也不调用模型；完整性由确定性诊断检查，缺失适用议题时阻断正式导出。
- `preset_catalog` 的锚点由合同或用户选择确定，模型只填充已确定行。
- `adaptive_catalog` 先依据报告主体、绑定输入和参考目录识别候选锚点，再整表填充。
- 声明 `GenerationSpec.rowExpansion` 的表（如 IRO 表）把一个业务行展开为多个披露子行：一次调用产出该业务行的全部子行（嵌套结构化输出，候选按子行收窄），模型只看到各子行的业务名称与写作口径，rowSpan、占位格与列 key 不进入模型视野；共享列合并与行序由 `table_ops` 确定性展开。共享列与子行列的归属、各子行列一致性和候选收窄范围由 loader 在加载期校验。
- 目录表使用整表调用维持行间分工；普通表可按行 fan-out。两者都回写统一 `GsTable` 合同。

### 5.3 定量指标

`MetricNarrativePolicy` 只进入 `financial/dual` 且全部相关指标无值的动态指标 H4。它是产品授权，不是从缺值推导的企业事实：允许表述正在着手建立指标管理体系，以及推进统计、收集、校验、跟踪和后续披露；禁止写成体系已建立或成熟，也禁止监督改善、对比分析、实际成效、金额、频次、量化目标、专用系统、工具或项目。

目录有映射时，只在 policy 中投影一次正式指标名称，不附单位、分类路径或逐项边界；完整指标 Evidence 仍进入 trace。目录为空时，模型按议题、行业与企业基本语境提出简单、通用的指标名称。正文软区间为 60–160 字，优先两句组织；句式示例只校准信息顺序与承诺强度，不是固定模板，也不增加句数 Guardrail。多个候选覆盖相同信息层级，只在自然措辞上变化。

任一相关指标有值时生成清单中不存在该正文块。治理、战略与 IRO 不获得指标目录或 policy；`impact/non` 摘要通过章节 Evidence 获得指标目录，但不获得 policy。任何非指标 H4 都不得从指标缺值或“未统计、未披露”等信息推导统计体系或披露计划。

指标 H4 的动态标题与正文沿用一次结构化调用并成对选择、重试和保存。Prompt 只表达 typed policy 的当前分支任务；不在全局 Profile 或议题 guidance 复制同一规则。

### 5.4 动态标题

H4 标题不是第二个生成步骤。声明 `Section.titleGeneration` 的直属段落块继续使用一次正文调用，但 typed 输出中的每个候选必须成对返回 `displayTitle + content`；候选选择、守卫、重试与整节事务都以该配对为单位，禁止跨候选拼接标题和正文。`ModelContext.displayTitleTask` 只增加标题 guidance，继续复用正文已有事实、证据姿态和披露边界，不引入全文或应用状态。

五个 ESG H1 标题使用独立的报告级结构化任务，由用户显式触发；此外批量生成运行在导出闸前自动补齐本次运行产生的过期模块标题（仅过期时一次报告级调用，属生成运行既有授权，避免批量生成被自己的产出恒久阻断导出），手动入口与用户三项处理不变。输入仅含五个模块的 guidance、当前适用 H2 固定名称和已解析 H4 标题（appears_when 为假的隐藏 H4 不进入输入，也不以 stale 标题阻断本任务）；一次输出必须完整、唯一、按模块顺序返回五个标题。Planner、配置保存、恢复和 Word 导出都不得隐式调用模型。

动态标题写回 `Section.displayTitle`，并保存当前任务输入指纹。H4 正文变化会使本标题及所属 H1 标题过期；H4 标题变化也会使 H1 过期。过期标题阻断正式导出，但用户可重新生成、编辑标题，或显式“保留当前标题”以当前输入指纹重新确认。

### 5.5 Prompt Profile 与报告版本

- Prompt Profile 每知识包一份，`profile_id` 等于包 id（`sse_zh_hans`、`hkex_zh_hant`、`hkex_en`、`gri_en`），由报告的
  `report_profile_id → knowledge_package` 解析，加载期校验 id 一致。守卫词面规则按报告语言取
  `llm/guardrail_lexicon.py` 的词表实例；中文特有排版规则在英文词表中为 `None`。产品只有一条报告主链，
  Profile 不声明档位兼容轴，也没有生成入口兼容性硬闸；定量指标目录全量开放，不分披露详略档。
- 生成仅在本块存在实质用户事实时读取 `simplifiedWritingGuidance`；准则披露要求
  （`standardDisclosureRequirementKeys → standard_disclosure_requirements`）保留为数据资产与
  加载期校验，但注入 prompt 属整体待办，生成上下文恒不注入。
- 新准则或新语言的报告以新增知识包承载（包内自带 Prompt Profile），不做 Profile 继承层，
  不开放客户端自由选择 Profile：建报只提交 `report_profile_id`，服务端据注册表解析到包。

## 6. 控制流与运行边界

- `generate_all` 只处理同时满足“可生成”和“可见”的块；隐藏块不调用模型。
- 公司业务摘要（上下文工程步骤0）先于块生成算出：它进入每个块的 `<report_subject>`，故生成编排在块生成前
  确保其就绪，结果与来源指纹同体写入报告状态。是否需要派生与是否已过期由 `llm/derive` 单点判定——简介为空
  或本身已不长于目标长度时不调用模型，来源正文变化即重算。缺该背景不阻断生成。
- 块间有两条次序，其余默认无依赖。其一来自契约：声明 `GenerationSpec.producesConclusion` 的块先于其余块生成，
  其产出并入在途 Report（副本，不改传入），供其余块的 `ModelContext` 解析为方向参照；编排只读该声明，
  不认具体 block id。同一结论的产出方在编译期校验为唯一，多产出方 fail-closed。消费方不需声明——
  结论按议题归属由 `ModelContext` 自行解析。结论是方向增强而非前置条件：产出块隐藏、生成失败或缺某议题时，
  其余块照常生成，只是少一层方向校准；议题章节有自身用户资料与生成合同，不因前四章的一项评估缺失而阻断。
  当前唯一结论是 `topic_iro`（由 `sm.iro_table` 产出）。
- 其二来自报告结构：议题章节内按四支柱（治理→战略→影响、风险与机遇管理→指标与目标）分阶段生成，
  先落定支柱的已 ready 段落正文解析为 `PriorDisclosure`，经 `<prior_disclosure>` 进入后续支柱的
  `ModelContext`，使下游块不复述已披露内容。阶段依据取自 Section 树既有的支柱归属
  （`contract/prior_disclosure.py` 的 `pillar_rank_in_report`），**不新增契约声明**，也不复用
  `producesConclusion`（后者枚举仅 `topic_iro` 且编译期校验产出方唯一）。同一支柱内的块彼此无先后，
  仍全并发，故不互相参照——把尚未落定的内容当既成事实喂给模型比少一层参照更有害。
  上游块隐藏、失败或受控省略时下游照常生成，只是少一层参照。
- `collectionPriority` 只控制采集提示；阶段化硬义务只由 authoring owner 的 `required` / `requiredBefore`
  元数据经 `CompiledInputObligation` 投影，选项与选项组仍在输入边界确定性校验。absence 行为只由
  `ReportProfile` 与显式生成合同决定，不得从 `blockType` 推导；轻量版 paragraph 缺企业事实默认
  `context_only`，只有显隐为假、无数据表格或缺值确定性可选句可以显式省略。缺失策略不能绕过准备
  投影确认的企业注册名称、行业门类和报告期等最低身份信息。
- 独立生成单元通过 `llm/concurrency.py` 并发执行，由全局信号量限流并保持失败隔离。
- 段落、表格行和目录整表均使用 Pydantic AI 结构化输出，不从自由文本猜业务结构。
- L1 guardrail 处理泄漏、整段占位输出、无依据数字或正式名称、高确定性敏感表达和无实质输入时的段落上限。它只读取当前 `GenerationEvidence` 与合法报告主体字段，不扫描全 Report 寻找旁路支持。占位断言只匹配完整输出形态，不把正常正文中的单个词当作禁词。最多尝试三次，耗尽后阻断该块。
- 字数区间是软信号；结构、显隐、枚举、必填和安全边界是硬合同。

## 7. AI 观测、评估与反馈

`sustainability_desk.ai_observability.v3` 保存任务开始/结束、每次 `model_invocation` 和生成后的 `guardrail_evaluation`；`model_invocation` 另携带 `spanId`/`stageId`，结构性归属于工作单元的阶段 span（阶段事实见同名 `{run_id}.stages.jsonl`）。`model_invocation` 同时记录完整 `ModelContext` 任务投影、实际 system/user prompt、输出 Schema、SDK 消息历史、结构化输出、模型设置、调用计量与错误详情；不删减用户输入。即使 Agent 在工具或 Provider 阶段失败，也必须保存失败前已交换的部分消息和脱敏异常 cause chain。`providerRequests` 表示 SDK 已完成并计入 usage 的逻辑请求，`httpSendAttempts` 表示实际进入 HTTP transport 的发送尝试，`transportAttempts` 表示 外层瞬时 HTTP 状态重试，三者不得混用。`guardrail_evaluation` 以同一调用序号记录逐条问题证据、接受/拒绝状态及实际用于下一次尝试的重试指令。JSONL 目录权限为 `0700`、文件为 `0600`；产品数据库 `generation_runs` 仍只保存用量聚合，可选的 OTLP 镜像只是同一 JSONL 的投影。轨迹事实唯一的用户可见出口是报告正文页的溯源面板：经 `observability/block_trace_facts.py` 聚合为逐块计数与稳定 code，由 `block_provenance` 投影承载，不露 prompt、模型消息与任何标识符。

Provider SDK 已耗尽内部重试后抛出的 `ModelAPIError` 是本次 job 的终态，worker 不再叠加业务重试；界面只显示可行动的领域错误，原始 Provider 错误只留在受控观测轨迹中，用户可稍后显式重试。

File Agent 的每次受限工具调用保存 typed request、结果指纹、文件 revision、状态和稳定错误；其最终 `FileDossierDraft` 与 Mapping 的结构化 proposal、校验结果和最多一次修复指令写入受控观测轨迹。模型输出或工具参数未通过结构校验时，产品任务只保存可行动的领域错误，内部字段名与校验文本只进入受控观测轨迹。工具结果按需披露，不能为减少轮次把完整原文件、全部 Dossier 或审计字段复制进启动上下文。

资料 Agent 的产品运行状态、错误、重试和模型用量由 durable run/event owner 记录；用户视图只展示来源、
Dossier 结果、候选相关性、AttentionItem 和下一步。AI 观测使用资料领域 operation 与各自 typed context，
不伪装成正文 `ModelContext`，也不让原文件、完整 Dossier 或内部审计进入正文生成评估样本。

运行轨迹用于复现和归因，不是报告正文或人工结论的真相源。离线评估仍从生成当次的 typed `ModelContext`、块合同和结构化输出投影 `CaseInputs`；需要复核 Judge 时优先读取 `result.json.debug_cases`，缺失时可用完整轨迹核对当次实际输入、输出和守卫行为。AI 内容审阅与 Judge 校准分别使用固定 typed package；人类可见内容与 `machineLocator` 分离。

线上 guardrail 负责硬边界；离线 evaluator 与人工审阅负责语义质量和改进。人工反馈必须先核查输入证据，再决定修改全局语义、议题指导、合同、守卫或 Golden Dataset。

所有模型调用轨迹、评估与审阅数据只保存在本机。可选的 OTLP 镜像只接收无正文 APM；不得接收 prompt、报告内容、认证信息或自由文本。

## 8. 变更与验证规则

修改上下文工程时至少回答：

1. 哪个权威事实发生了变化，是否新增重复所有者。
2. 哪个生成分支会看到变化，其他分支是否保持隔离。
3. 模型实际消息是否仍为最小高信号集合。
4. 输出是否可被类型解析和守卫验证，模型调用是否由 AI 观测合同完整计量。
5. `CaseInputs`、Golden case 或确定性测试是否需要同源更新。
6. Prompt Profile 的适用范围与产品入口是否一致，是否误把未来版本映射到当前 Profile。

最小验证包括加载期引用校验、目标块生成测试、prompt/观测泄漏检查、guardrail 重试测试，以及受影响的前端、Word 或 eval 合同回归。
