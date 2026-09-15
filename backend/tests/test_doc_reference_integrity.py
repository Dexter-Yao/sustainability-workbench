# ABOUTME: evergreen 文档的引用完整性检查——文档提到的文件路径与代码标识符必须真实存在。
# ABOUTME: 只覆盖可机器判定的引用；语义自洽与行为断言仍需人工核对，本测试不冒充覆盖了那一层。
"""文档引用完整性。

文档体系里会出现代码中从未存在的实体名（如 `MaterialSourceRevision` /
`ParserArtifact` / `UserAssertionRevision`）、已被删除的测试文件与已改名的标识符。
这类错误**只能靠人读一遍才发现**，于是同一份文档被反复调查、反复发现新问题。

本测试把其中可机器判定的一层固化下来：文档里以反引号标注的**文件路径**与**代码标识符**
必须真的存在。语义层（自相矛盾、行为断言与实现不符、枚举数目）机器判不了，仍靠人工核对——
本测试不声称覆盖那一层。

**允许清单只许收缩**：新增豁免意味着文档又写了一个代码里没有的名字，必须在此显式说明理由。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: 受检文档：仓库根的 evergreen md 与 `docs/` 下全部文档。
#: 从文件系统枚举而非硬编码清单——硬编码时新增文档要靠人记得加进来，
#: 而漏加的那份恰恰是最没被检查过、最可能积累失效引用的一份。
#: 根目录三份面向读者的文档一并纳入：README 是仓库第一入口，断链代价高于内部文档，
#: 而它此前完全不受守护（实测曾链到不存在的 docs/architecture.md 而全绿）。
ROOT_AUDITED_DOCS = [
    "design.md",
    "README.md",
    "README.zh-CN.md",
    "SETUP.md",
    # Agent 规则本身也引用大量代码路径；它是接手者的第一入口，断链代价与 README 同级。
    # AGENTS.md 与 CLAUDE.md 文本一致（由 cmp 守护），只检一份即可。
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
]
#: `docs/` 及其子目录（如 docs/handbook/）全部纳入——子目录文档同样会引用代码路径与同级文档。
AUDITED_DOCS = [name for name in ROOT_AUDITED_DOCS if (ROOT / name).is_file()] + sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*.md")
)

#: 文档惯用的相对根：design.md 的 `lib/x.ts` 指 frontend/lib/x.ts，
#: schema 文档的 `contract/models.py` 指 backend/src/sustainability_desk/contract/models.py。
PATH_PREFIXES = [
    "",
    "frontend/",
    "backend/",
    "backend/src/sustainability_desk/",
    "docs/",
    "docs/",
]

#: 代码标识符的搜索范围。
CODE_PATHS = [
    "backend/",
    "frontend/app/",
    "frontend/components/",
    "frontend/lib/",
    "frontend/e2e/",
    "supabase/",
    "scripts/",
]

#: 文档中出现、但代码里**本就不该存在**的标识符——每条必须写明理由。
#: 只许收缩：要新增，先确认它真的属于以下三类之一，而不是又写错了一个名字。
ABSENT_BY_DESIGN: dict[str, str] = {
    "omitted_no_material": "已删除的省略语义，验收规程明确禁止回流（local-e2e-acceptance）",
    # 明确记录为「已删除」的历史字段，其不存在正是文档要表达的事实
    "GenerationPosture": "GenerationSpec 已删除该字段（schema 文档 §生成合同）",
    "GenerationConstraints": "GenerationSpec 已删除该字段（同上）",
    # 明确记录为「Agent 没有这个工具」的能力边界
    "list_files": "单文件 Agent 刻意不提供该工具（schema 文档 §File Agent v3 合同）",
    # 明确标注为未实现预留
    "sustainability_desk_ai": "design.md §5.6「AI 评审（预留）」，MVP 未实现",
    # 外部工具的输出字段名，不是本仓代码标识符
    "SERVICE_ROLE_KEY": "supabase status 的输出项名（SETUP.md 的 .env 对照表），非本仓标识符",
    "JWT_SECRET": "同上",
    "ANON_KEY": "同上",
}

#: 文档中出现、但**刻意已删除**的路径——文档正是要记录「它已不存在」这件事。
#: 与 ABSENT_BY_DESIGN 同理，只许收缩。
DELETED_BY_DESIGN: dict[str, str] = {
    "Reference/design_system/": "已删除；design.md §9 记录「不再维护独立可视化样例稿」",
    # 它不存在正是文档要陈述的事实：密钥只经环境变量注入，.env 被 gitignore，绝不入库。
    "backend/.env": "SECURITY.md 陈述该文件被 git 忽略、不得入库；存在才是问题",
}

#: 形如 `financial/dual`、`succeeded/failed` 的并列枚举会被路径正则误捕，非真实路径。
_NOT_A_PATH = re.compile(
    r"^(?:[a-z_]+/)+[a-z_]+$|"          # 全小写下划线的并列枚举
    r"^FileDossier\.|"                   # 合同版本并列
    r"\.[A-Z][A-Za-z]*$|"                # module.ClassName 形式的符号引用
    r"^word/[a-z]+\.xml$|"               # OOXML 包内部件（docx 内部路径，不是仓库文件）
    r"^frontend/test-results/|^traces/"  # 运行期产物：Playwright 输出目录、内部审计包内路径
)


def _path_exists(candidate: str) -> bool:
    stripped = candidate.rstrip("/")
    if "*" in stripped:
        for prefix in ["", "frontend/", "backend/", "backend/src/sustainability_desk/"]:
            result = subprocess.run(
                ["git", "ls-files", prefix + stripped],
                cwd=ROOT, capture_output=True, text=True,
            )
            if result.stdout.strip():
                return True
        return False
    # 允许省略扩展名（文档常写 `components/ui/Hint`）
    for prefix in PATH_PREFIXES:
        base = ROOT / (prefix + stripped)
        if base.exists():
            return True
        if any(base.with_suffix(suffix).exists() for suffix in (".ts", ".tsx", ".py")):
            return True
    return False


def _identifier_exists(token: str) -> bool:
    result = subprocess.run(
        ["git", "grep", "-l", "-F", "-e", token, "--", *CODE_PATHS],
        cwd=ROOT, capture_output=True, text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


@pytest.mark.parametrize("doc_relative_path", AUDITED_DOCS)
def test_documented_paths_exist(doc_relative_path: str) -> None:
    """文档引用的文件路径必须存在——引用一个已删除的文件比不引用更危险。"""

    text = (ROOT / doc_relative_path).read_text(encoding="utf-8")
    candidates = set(re.findall(r"`((?:[A-Za-z_][\w.-]*/)+[\w./*-]+)`", text))
    missing = sorted(
        candidate
        for candidate in candidates
        if not _NOT_A_PATH.search(candidate)
        and candidate not in DELETED_BY_DESIGN
        and not _path_exists(candidate)
    )
    assert not missing, (
        f"{doc_relative_path} 引用了不存在的路径：{missing}；"
        "确属已删除且文档正在记录该事实时，登记到 DELETED_BY_DESIGN 并写明理由"
    )


@pytest.mark.parametrize("doc_relative_path", AUDITED_DOCS)
def test_documented_identifiers_exist(doc_relative_path: str) -> None:
    """文档提到的类名/函数名/常量必须在代码中存在，或登记在 ABSENT_BY_DESIGN 并写明理由。"""

    text = (ROOT / doc_relative_path).read_text(encoding="utf-8")
    identifiers = {
        token
        for token in re.findall(r"`([A-Za-z_][A-Za-z0-9_]{2,})`", text)
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*", token)
        or re.fullmatch(r"[a-z_][a-z0-9_]*_[a-z0-9_]+", token)
        or re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", token)
    }
    missing = sorted(
        token
        for token in identifiers
        if token not in ABSENT_BY_DESIGN and not _identifier_exists(token)
    )
    assert not missing, (
        f"{doc_relative_path} 提到代码中不存在的标识符：{missing}；"
        "确属刻意不存在（已删除/未实现/能力边界）时登记到 ABSENT_BY_DESIGN 并写明理由"
    )
