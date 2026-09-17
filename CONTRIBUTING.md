# Contributing

This is a personal project with one maintainer. Being straight with you about what is useful:

**Bug reports are welcome** — especially ones with reproduction steps against the bundled
synthetic corpus, since that is the only company data I can debug against. Include the
knowledge package (`sse_zh_hans`, `hkex_zh_hant`, `hkex_en`) and, if generation is involved,
what you configured as the model.

**Questions about adapting it to another exchange or language are welcome.** That path runs
through knowledge packages rather than through the generation pipeline; see
[docs/architecture.md](./docs/architecture.md).

**Large feature pull requests are likely to sit unmerged.** Not out of disinterest — the
codebase carries invariants that are not obvious from the diff (scope projection has two
separate meanings, the export gate must stay deterministic, model-visible context has a hard
boundary). Open an issue describing the change before writing it, and I will tell you honestly
whether I will merge it.

## Before you submit

```bash
make supabase-up    # first — persistence tests skip silently without it and the suite lies
make verify         # backend pytest + frontend test/lint/build
```

There is deliberately no lint step here: the repository pins no `ruff` version and carries no
`[tool.ruff]` config, so "clean" would mean whatever version you happened to resolve (0.12 passes,
0.16 reports hundreds of findings from rules this project never adopted). Adding it properly means
pinning a version, writing the config and clearing the backlog — worth doing, but as its own change.

`make install-hooks` wires `make verify` into pre-push.

Read [CLAUDE.md](./CLAUDE.md) for the rules the code is held to. It is written for AI coding
agents but is the most direct statement of the project's constraints for humans too.
