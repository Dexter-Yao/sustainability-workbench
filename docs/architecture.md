<!-- ABOUTME: Architecture: the main chain, two constraints, knowledge packages and runtime stages. -->
<!-- ABOUTME: Stage ids come from the observability stage vocabulary; they are not illustrative names. -->

# Architecture

**[简体中文](./architecture.zh-CN.md)**

## The main chain

```
Your input
├─ Company basics (name, reporting period)          ┐
├─ Topic materiality scoring (what enters the report)├─────────────┐
├─ Quantitative metrics (emissions, workforce, waste)┘             │
└─ Documents (policies, records, certificates)                     │
        │                                                          │
        ▼                                                          │
   File Agent            material.file_agent                       │
   reads each file → traceable dossier                             │
        │                                                          │
        ▼                                                          │
   Mapping Agent         material.mapping_agent                    │
   picks material per chapter; selects, never writes               │
        │                                                          ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ Controlled evidence set — each block sees only its assigned facts │
   └──────────────────────────────────────────────────────────────────┘
        │
        ▼
   Block-by-block drafting   generation.blocks → generation.commit
        │                            ▲
        ▼                            │ blocking issue → back for revision
   Diagnostic gate           delivery.export_gate
        │
        ▼
   Final + review Word       delivery.docx.word / .review
```

Paragraph-by-paragraph revision is optional and sits between drafting and the gate; a report the
gate stops goes back for revision.

Of the four inputs only company basics is required. The rest may be left empty, and the system
adjusts what it writes rather than inventing filler.

## Two constraints

### Agents select material; they do not write prose

A File Agent reads each document into a summary, and a Mapping Agent decides which materials a
given chapter may draw on. Neither **produces report text**. Prose is generated on a separate path,
block by block, and each block can only see the facts assigned to it — the guarantee that the
report will not describe things the company never did is structural, not an instruction in a
prompt.

### The diagnostic gate calls no model

Generation does not deliver straight to a file. The diagnostic layer checks completeness and
consistency in code, and stops anything with a blocking issue, naming where it is. No model is
involved, so the same report always gets the same verdict.

## Knowledge packages

One package = one rule set × one language. A package carries:

- The topic list and how materiality is determined
- The chapter skeleton and block-level generation specs
- Standard clauses and disclosure requirements
- The quantitative metric catalogue
- Prompts and Word layout parameters

Three packages ship today:

| Package | Standard | Language | Materiality |
|---|---|---|---|
| `sse_zh_hans` | Shanghai Stock Exchange | Simplified Chinese | Double materiality |
| `hkex_zh_hant` | HKEX | Traditional Chinese | Financial materiality first |
| `hkex_en` | HKEX | English | Same |

Another standard or another language means another package; the code does not branch. Traditional
Chinese and English are two independent packages, not one content set transliterated. Differences
between standards live in the data layer, so adding an exchange or a language leaves the generation
pipeline untouched.

## Runtime stages

Every run writes its trace against registered stages, so a failure points at a stage rather than
at "generation failed".

| Stage id | What it does |
|---|---|
| `material.file_agent` | Reads each document, producing a traceable summary |
| `material.image_agent` | Recognises image material and captions it |
| `material.mapping_agent` | Picks material per chapter |
| `generation.blocks` | Drafts prose block by block (pillar blocks and conclusion blocks in batches) |
| `generation.row` | Generates table rows |
| `generation.commit` | Writes back into the structured report |
| `delivery.export_gate` | Deterministic diagnosis; stops anything with a blocking issue |
| `delivery.render` | Renders Word |
| `delivery.docx.word` / `.review` | The final and review deliverables |

The stage vocabulary is assembled by
`backend/src/sustainability_desk/observability/registry.py`. Stage constants are declared next to
the implementation they name: importing registers them, and a conflict raises.
