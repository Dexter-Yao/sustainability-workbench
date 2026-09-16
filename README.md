# Sustainability Workbench

A self-hosted drafting workbench for sustainability (ESG) reports, for the people who prepare
them — in-house reporting teams at companies of any size, and the consultants and accounting
firms who do it on their behalf.

Plenty of companies write one because a customer, a bank or a tender asked for it, not because
a regulator did. Either way the work is the same: it reads your policies, records, certificates
and reported figures, drafts the report section by section against a disclosure standard, and
exports to Word. Three rule sets ship today — Shanghai Stock Exchange (Simplified Chinese),
HKEX (Traditional Chinese), HKEX (English) — and they serve as the structure whether or not you
are listed.

It drafts; it does not assure. What comes out is a draft for professional review — not an
assurance opinion, not a compliance guarantee. Someone still has to read it and sign it off.

**[简体中文](./README.zh-CN.md)** · [Architecture](./docs/architecture.md) ·
[Setup](./SETUP.md) · [Handbook](./docs/handbook/README.md)

## Why not just hand the files to an LLM

A sustainability report is constrained by the standard it follows: which topics must be
covered, what each topic has to disclose, which metrics need numbers. Handing every file to a
model and asking for a report fails in two places — it writes things the company never did, and
it misses disclosures the standard requires.

Two constraints address that:

- **Agents select material; they don't write prose.** A File Agent reads each document into a
  summary; a Mapping Agent decides which materials a given chapter may draw on. Neither produces
  report text. Prose is generated block by block, and each block only sees the facts assigned to
  it.
- **A deterministic gate stands before delivery.** Code — not a model — checks completeness and
  consistency, and blocks the export with the location of anything that fails. The same report
  always gets the same verdict.

This is a workbench, not a one-click generator: you read the draft, revise it paragraph by
paragraph, rewrite whole sections, and decide when it ships.

## What it produces

Five preparation steps, then generate:

1. Company basics (required)
2. Topic materiality scoring — decides which topics enter the report
3. Quantitative metrics — emissions, workforce, waste
4. Guided topic questions
5. Document upload

The last four can be left empty. After generation you get two Word files: a final version, and a
review version carrying annotations about what still needs human confirmation.

The repository ships a fully synthetic corpus — two fictional companies, no real business data —
so you can run the whole flow end to end without supplying anything of your own.

A GRI package is present but sealed: it is not selectable when creating a report. It was built
against a route that needs wording changes before it can honestly claim conformance.

## Architecture

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

Paragraph-by-paragraph revision is optional and sits between drafting and the gate. Of the four
inputs only company basics is required; the rest may be left empty, and the system adjusts what
it writes rather than inventing filler.

Full detail in [docs/architecture.md](./docs/architecture.md).

Rules and language live in **knowledge packages** — one package per rule set per language.
Adding an exchange or a language means adding a package, not changing the generation pipeline.

## Getting started

See [SETUP.md](./SETUP.md). Short version, once the prerequisites are installed:

```bash
supabase start                          # local Postgres + auth + storage
cp backend/.env.example backend/.env    # fill from `supabase status`, add a model API key
make verify                             # backend and frontend tests
./scripts/dev/local-acceptance-stack.sh up   # starts backend, worker and frontend
```

Prerequisites: Node 22, uv, Docker, the Supabase CLI, and LibreOffice. `make doctor` checks all
of them before you start.

**Set aside about 6 GB and 15–30 minutes.** The repository is small (~13 MB), but the container
images, LibreOffice and the dependency trees are not, and most of that lands outside the project
directory. [SETUP.md](./SETUP.md) breaks the figure down and lists the two components you can
skip.

Supabase here is **not a cloud account** — `supabase start` runs Postgres, auth and storage in
local Docker containers on your own machine. Nothing leaves it, and there is nothing to sign up
for.

## For coding agents

Run these in order. Each step either succeeds or fails loudly; do not skip ahead.

```bash
make doctor                                  # verifies Node 22+, uv, Docker, Supabase CLI, LibreOffice
supabase start                               # must finish before any test run
cp backend/.env.example backend/.env         # then fill JWT_SECRET, SERVICE_ROLE_KEY, ANON_KEY from `supabase status`
                                             # and one model key (Azure OpenAI, or any OpenAI-compatible endpoint)
make verify                                  # backend pytest + frontend test/lint/build
make install-hooks                           # pre-push runs make verify
```

Then create the first account and start the stack:

```bash
make provision-owner ARGS="--email you@example.com"        # dry run: prints what it would do
SUSTAINABILITY_DESK_OWNER_PASSWORD='<12+ chars, mixed case and digits>' \
SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES \
  make provision-owner ARGS="--email you@example.com --apply"
./scripts/dev/local-acceptance-stack.sh up   # backend :8010, worker, frontend :3000
```

Four things that will waste your time if you do not know them:

- **`make verify` before `supabase start` gives a false green.** Persistence tests call
  `pytest.skip` when the database is unreachable, so the suite passes without ever exercising
  the database layer. Start the stack first.
- **The worker is not optional.** Material processing and report generation are Postgres queues
  consumed by a separate process. Without it the UI works and generation waits forever.
- **LibreOffice is a runtime dependency, not a test tool.** Word table-of-contents page numbers
  need a layout engine; python-docx does not paginate. Missing `soffice` means export fails.
- **Open `http://localhost:3000`, not `127.0.0.1`.** The Next dev server rejects other origins
  and the page stalls on an auth error.

No account can be created from the UI — sign-up is deliberately closed, so
`make provision-owner` is the only path to the first login.

Working on the code: read [CLAUDE.md](./CLAUDE.md) first (rules, invariants, what not to
change), then [docs/architecture.md](./docs/architecture.md). `AGENTS.md` is a byte-identical
copy for tools that look for that name.

Verify a change end to end without calling any model:

```bash
uv run --project backend pytest tests/test_local_e2e_fixture_corpora.py
```

It drives the built-in synthetic corpus through the real input path and renders a Word file.

## Stack

| Layer | What |
|---|---|
| Backend | Python / FastAPI, Postgres queue with a separate worker |
| Frontend | Next.js |
| Storage & auth | Supabase (Postgres + Auth + Storage) |
| Export | python-docx for rendering, LibreOffice for table-of-contents pagination |
| Models | Azure OpenAI by default; any OpenAI-compatible endpoint works without code changes |

## Licence

MIT. See [LICENSE](./LICENSE).

Generation quality depends on calibration, and calibration is specific to each firm's house
style and review standards. If you want help building an evaluation setup for your own
reports, or AI engineering support more broadly, get in touch — Dexter Yao,
dexter.yao23@gmail.com

Clause numbers and metric names are cited as fact; the wording of disclosure requirements is
rewritten rather than copied from official texts.
