# 晟原精密 · 合成企业 corpus

面向报告示例与本地端到端演练的**全合成**企业资料。无真实主体、无真实企业数据，
因此纳入版本控制；真实企业资料一律不入库。

- 走**上传文件**路径（`primaryInputMode = materials`），议题引导问题留空
- 结构化输入走产品自带的**统一填报工作簿**，不手写文件去凑字段

## 目录

| 路径 | 内容 |
|---|---|
| `materials/` | 26 份语义资料源文（Markdown，其中《食堂周菜单示例》是与报告无关的对照件），版本控制的可读真相 |
| `materials_docx/` | 由源文转出的 26 份 docx，**上传用**（派生产物）；排版素材在 `../layout_assets/` |
| `fill_workbook.py` | 生成填写后的统一工作簿 |
| `build_materials.py` | Markdown → docx |
| `shengyuan-unified-workbook.xlsx` | 填写后的工作簿，可直接导入 |

```bash
cd backend
uv run python tests/fixtures/local_e2e/shengyuan/fill_workbook.py     # 重生成工作簿
uv run python tests/fixtures/local_e2e/shengyuan/build_materials.py   # 重生成 docx
```

企业身份、议题打分、intake 以该 fixture 为准，**本目录不复制、不改写**。

---

## 一、事实基准

所有材料的数字、日期、人名、制度名以本节为准；任何新增须先写入本节。
冲突即缺陷——审阅稿会把正文标注到具体源文件，两份文件说法不一读者可见。

### 身份

晟原精密电子股份有限公司（简称晟原精密），2008 年成立，制造业 / 计算机、通信和其他电子设备制造业。
主营高速连接器、精密冲压端子与结构件，应用于消费电子、新能源汽车、工业控制。
主生产基地：江苏省苏州市工业园区晟原路 18 号。官网 `www.example-shengyuan.com`，
邮箱 `esg@example-shengyuan.com`，电话 `0512-00000000`（均为 example 占位）。

报告期 2025-01-01 ~ 2025-12-31，报告年度 2025，2026-04 董事会批准。
董事会会议 8 次、出席率 96%，涉科技伦理敏感活动：是。

> 时间基准：今天是 2026 年 8 月，最新可编年报即 2025 年度。报告期内事件一律落在 2025 年内；
> 历史沿革（2008 成立、历年认证）可早于 2025 但须自洽。

### 定量锚点

| 事实 | 值 | | 事实 | 值 |
|---|---|---|---|---|
| 员工总数 | 860（男 520 / 女 340） | | 范围一排放 | 12,800 tCO₂e |
| 学历 | 博 2 / 硕 48 / 本 310 / 本以下 500 | | 范围二排放（市场法） | 26,400 tCO₂e |
| 离职率 | 8.5%（离职 72 ÷ 平均在册 846） | | 范围一+二 | 39,200 tCO₂e |
| 人均培训学时 / 覆盖率 | 12 / 86% | | 综合能源消费量 | 18,600 tce |
| 活跃供应商 | 186（内地 168 / 港澳台 4 / 国外 14） | | 其中电力 | 12,100 tce |
| 供应商退出 | 6 | | 其中天然气 / 柴油 | 6,474 / 26 tce |
| 产品召回 | 0 | | 太阳能（光伏自用） | 1,200 tce |
| 客户投诉 | 6 件，完成率 100% | | 取水总量 | 12,500 吨 |
| 廉洁培训 | 4 场 / 128 人次 | | 工业废水 | 8,600 m³ |
| **营业收入** | **6.5 亿元（650 百万元）** | | 废弃物 | 42.6 t（一般 39.4 / 危废 3.2） |
| 温室气体核算标准 | ISO 14064-1:2018 | | 其中回收利用 | 18.0 t（金属 15 / 有色 2 / 纸 1） |

**范围三**：口径正在建立，未披露，材料中不得出现数值。

**营业收入的来由**：`economic_environment_r44` 是**耗水**强度（吨/百万营业收入，
口径为耗水量÷营收），而 fixture 的 `r43` 耗水总量为 null、`r42` 取水总量才是 12,500——
**0.59 无法反推营收**。故直接定为 6.5 亿元：人均产值 75.6 万元/年，符合精密电子制造业区间。
材料中只写「用水强度按年度营业收入折算」，不展开计算式，不给耗水总量。

### 组织与人名

董事长沈立、总经理陆勤（可持续发展委员会主任委员）、副总经理周敏（分管生产/质量/EHS）、
可持续发展办公室主任何静、质量部部长郑洲、EHS 主管汪磊、人力资源部部长韩雪、
采购部部长徐涛、客户服务部经理蒋岚、法务合规专员秦朗。

治理架构：

```
董事会 → 可持续发展委员会（2024 设立，2025 开 3 次会）→ 可持续发展办公室
        → 环境与能源 / 员工与安全 / 供应链 / 合规与商业道德 四个工作组
```

工作组季度报办公室，办公室月度汇总报委员会，委员会年度报董事会。

### 制度与认证

制度 SY-EHS-001/002/003、SY-QA-001、SY-PUR-001/002、SY-HR-001/002、
SY-LEG-001/002、SY-CS-001、SY-GOV-001，版本与修订日期见各材料文件头。

认证：ISO 9001（2010 首次）、ISO 14001（2015）、ISO 45001（2018）、IATF 16949（2019），
证书编号为虚构的 `SY-*` 形式。

### 语气

860 人的制造企业，不是行业领袖。制度健全但不完美（如范围三口径在建）。
写具体度（「2025 年 3 月修订」而非「近期」）。不编造荣誉、奖项、排名、媒体报道。

---

## 二、统一填报工作簿

基础资料、议题重要性评分、ESG 定量信息三类结构化输入**走产品自带模板**，不手写：

```
blank_unified_workbook_template()   # structured_input_service.py:1309，纯函数，无需起栈
POST /unified-workbook/import       # 整册按覆盖语义写入
```

母版 30 个 sheet：总览、基础资料、重要性评分表、定量填写说明 + 定量三表、
22 个议题问答 sheet、隐藏的 `_模板元数据`。

### 可写单元格

| sheet | 可写范围 | 约束 |
|---|---|---|
| 基础资料 | **仅 F 列**（F8–F38） | F10/F16/F18/F19/F21/F22/F26/F27 是枚举下拉，值须精确匹配 |
| 重要性评分表 | B、C 列，**仅 10–17、19–29、31–34** | 9/18/30 是 E/S/G 分组标题行；值域 (0,5]、步长 0.1 |
| 定量三表 | E 数值 / F 无值原因 / G 部门 / H 备注 | F 枚举：`not_collected` `not_available` `not_applicable` `will_supplement` |
| 议题问答 22 sheet | **留空**（走文件路径） | |
| `_模板元数据` | **一格不动** | 导入按全零 report_id + fingerprint 校验血统 |

指标行：经济+环境 9–39（31 项）、社会 9–42（34 项）、治理 9–12（4 项），共 69 项。
**唯一自动计算行 `经济+环境!E13`**（r07 = 范围一＋范围二），E 列已有说明文字，不得覆盖。

已实测 openpyxl `load → save → load` 往返保真：30 sheet 齐全、隐藏元数据逐字不变、
10 条数据验证全部保留。→ 定点写入安全，不必重建工作簿。

### 必填项中的两个关键格

`intake:company_profile`（≥100 字）—— 提示语写明「作为『关于公司』章节和主营业务概述的基础材料」，
**公司简介填这里**，不靠上传 docx 承载。

`intake:sustainability_governance_structure` 与 `..._duties` —— 可持续发展治理架构与职责分工，
由工作簿驱动，不由上传的制度文件驱动，须写足层级、岗位与汇报线。

### 定量指标：按官方 key 填，不沿用 fixture 赋值

fixture 的定量指标存在**错位**（源头缺陷，非本 corpus 引入）。以
`backend/data/quantitative_metrics.json` 的 `metricLabel` 为准：

| key | 官方定义 | fixture 塞的值 | 本 corpus 应填 |
|---|---|---|---|
| `r03` | 营业收入（百万元） | **空** | **650** |
| `r11` | 传统能源/**电力消耗量** | 18,600「综合能耗」 | **12,100** |
| `r17` | 传统能源/其他 | 12,100「外购电力」 | **6,500**（天然气 6,474 + 柴油 26） |
| `r19` | 清洁能源/**太阳能消耗量** | 6,500「天然气和柴油」 | **1,200** |
| `r22` | 清洁能源/其他 | 1,200「屋顶光伏」 | 空 |

12,100（电力）+ 6,500（直接能源）= **18,600**，与综合能耗锚点一致。

> **轻量版没有独立的天然气/柴油行**：`r14` 柴油与 `r15` 天然气是 `lightweight=False`，
> 不在轻量版工作簿内。直接能源（天然气 6,474 + 柴油 26 = 6,500）合并填入
> `r17` 传统能源/其他。这也解释了 eval fixture 为何把值挤在这几个 key 上。

### 两条 fail-loud 约束（实测撞到过）

- **每项指标必须且只能填「数值」或「无值原因」之一**（`quantitative_parser.py:326`）。
  69 项里未纳入本 corpus 的一律给 `not_collected`，不能留空。
- **填了温室气体数值就必须选核算标准**：`定量填写说明!B8` 下拉，本 corpus 取
  `ISO 14064-1:2018及《工业企业温室气体排放核算和报告通则》（GB/T 32150-2015）`。

### 评分表映射

23 行按 `topic_registry.yaml` 的 `officialName` 与 fixture `topic_scores` **全部命中，零缺口**。
阈值 4.0（任一轴），**23 个议题全部为重要议题**。
（`risk_management` 位于行 33，尽职调查在行 34；
行号是硬编码的工作簿坐标，议题清单变动时 `SCORES` 与 `SCORE_ROW_TO_TOPIC` 必须同步重测。）
（「乡村振兴」与「社会贡献」在 registry 中是两个独立 id，与 sheet 行名一一对应。）

---

## 三、上传约束

| 项 | 值 |
|---|---|
| 单份报告最大文件数 | 30（`material/workspace.py:80`），当前 25 份在限内 |
| 语义资料格式 | `.pdf` `.docx` `.xlsx` `.pptx` |
| 排版素材格式 | `.png` `.jpg` `.jpeg` `.webp` `.pdf`（单页） |

`materials/` 是 Markdown 源文，上传前转 **docx**（一对一，不合并）。
台账类的年度值与工作簿必须一致——否则审阅稿旁注会指向互相矛盾的两处。

---

## 四、维护

- 数字变更先改本文「定量锚点」，再改材料；材料不得自带新数字
- 模板结构变化时重新生成空白母版比对，不维护母版副本
- 材料由多个 agent 并行编写时，**其自检结论必须独立复核**：
  已发生过台账合计行是"编"的而非算的（自报"偏差 0"，实际列加总不符）
- `materials_docx/` 是派生产物，改内容改 `materials/*.md` 后重跑 `build_materials.py`

## 五、已验证（经产品自身解析链路）

| 检查 | 结果 |
|---|---|
| 隐藏元数据血统 | 5 项与 `blank_unified_workbook_expected_metadata()` 全等 |
| `split_unified_workbook` | 四部分全部拆出（basics / scoring / quantitative / topic_questions） |
| 基础资料解析 | 19 个 field + 4 条 intake；治理架构 520 字、职责 598 字、公司简介 760 字 |
| 评分解析 | **scored 23 / unmatched 0** |
| 定量解析 | 69 项全部通过；35 项有值（含 `r07` 自动求和 = 39,200 ✓） |
| docx 转换 | 25 份，表格结构保留（台账 13–19 个表），无内容过少文件 |

---

## 六、跑完整链路

> **改过导出侧代码就必须先重启本机栈，再跑本流程。** report-worker 常驻、不热重载，
> 渲染发生在它进程内：栈启动后落盘的 `export/`、`format_profiles/` 改动一律不生效，
> 而链路仍会正常跑完并产出旧形态交付物——跑完才发现白跑。
> 先 `./scripts/dev/local-acceptance-stack.sh down && ... up`，`status` 确认 pid 已换。

```bash
cd backend
# 1) 重生成派生产物（docx 与工作簿）
uv run python tests/fixtures/local_e2e/shengyuan/build_materials.py
uv run python tests/fixtures/local_e2e/shengyuan/fill_workbook.py
# 2) 重生成结构化输入（指纹与 sha256 现算）
PYTHONPATH=tests/fixtures/local_e2e/shengyuan \
  uv run python tests/fixtures/local_e2e/shengyuan/build_run_fixtures.py
# 3) 起本机栈，在浏览器里走完整流程
cd .. && ./scripts/dev/local-acceptance-stack.sh up
```

起栈后打开 <http://localhost:3000>：新建报告 → 按本文的事实基准填写 → 上传
`materials_docx/` 下的资料 → 生成 → 导出 Word。`scripts/dev/acceptance_data.py`
可按本语料预填两份工作簿（口令经 `SUSTAINABILITY_DESK_ACCEPTANCE_PASSWORD` 注入）。

无头校验走 `tests/test_local_e2e_fixture_corpora.py`：它拿本语料跑通产品自身的输入
链路并渲染出 Word，不调用模型，`uv run pytest tests/test_local_e2e_fixture_corpora.py`
即可。

生成的两份 fixture 由 `build_run_fixtures.py` 现算，不手写：

- `shengyuan_report_inputs.yaml`：51 条 inputWrites（17 项基础资料与治理长文本 + 34 项定量指标，
  r07 由范围一＋范围二自动求和故不写）、23 个议题打分
- `shengyuan_materials.yaml`：26 份 docx 与 4 份合成排版素材，走 **v3** 清单合同
  （v2 硬性锁定 15 份文件；v3 支持 1–30 份且不需要 selectionDomains，
  标签统一 `uncertain`，归属由 File Agent 从内容判定）

`expected_definition_fingerprint` 由 `LightweightReportInputAdapter.target_fingerprint()` 现算；
`expected_target_fingerprint` 是乐观锁，取空值指纹 `adapter.fingerprint(None, None)`
——断言写入时该目标仍为空。

---

## 七、完整链路结果

### 修复后完整跑（参考基准）

全链路 exit 0，五阶段全 completed，**18.4 分钟**。

| 指标 | 首跑 | 本次 |
|---|---|---|
| 报告块数 | 88 | **190** |
| concise_summary 块 | 22 | **0** |
| 页数 | 59 | **92** |
| 正文字数 | ~18,769 | **~29,015** |
| 表格 | 9 | 12 |
| 内嵌图 | 1 | **18** |
| 审阅批注 | 85 | **174** |

### 阶段耗时与并发度（本次实测）

| 阶段 | 数量 | 墙钟 | 串行需 | 峰值并发 | 并发度 |
|---|---|---|---|---|---|
| File Agent | 25 | 455s | 2193s | **6** | 4.8x |
| Mapping Agent | 21 | 170s | 922s | **6** | 5.4x |
| 块级生成 | 89 | 388s | 4697s | **88** | 12.1x |
| 行级生成 | 22 | 67s | 748s | 22 | 11.2x |

**瓶颈是 worker 协程池，不是模型。** File Agent 与 Mapping 峰值恒为 6：
常驻 worker 默认 4（`material/agent_worker.py:36`）+ 实验 CLI drain 默认 2
（`eval/experiments.py:1133`）。块级生成能跑到 88，证明架构 fan-out 本身没问题。

全程 180+ 次模型调用，**0 次 429/5xx、0 次传输重试**——即便峰值 88 并发。
全局信号量 `MAX_INFLIGHT_LLM_CALLS=100` 未被触及。


真实上传 25 份资料同样要排队约 6 分钟。
