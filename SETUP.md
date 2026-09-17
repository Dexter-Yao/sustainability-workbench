<!-- ABOUTME: Full local install and configuration steps; the README keeps only the shortest path. -->
<!-- ABOUTME: Step order carries dependencies — steps 3 and 4 cannot be swapped; the reason is in step 4. -->

# Setup

For someone running this project for the first time. Everything stays on your machine; no external
database is involved.

**[简体中文](./SETUP.zh-CN.md)**

Platform: macOS or Linux (the preflight script uses `nc` and `lsof`).

## 1. Install the prerequisites

| Tool | What it is for | What happens without it |
|---|---|---|
| Node 22+ | Frontend | `make doctor` fails |
| [uv](https://docs.astral.sh/uv/) | Python dependencies and runner | Backend will not start |
| Docker | Runs the local Supabase stack | `supabase start` fails |
| [Supabase CLI](https://supabase.com/docs/guides/cli) | Local Postgres, auth and storage | No database |
| LibreOffice (optional) | Pre-computes TOC page numbers at export | Page numbers are resolved by the reader on open |
| pandoc (optional) | Rebuilds the .docx derivatives of the synthetic corpus | Only affects rebuilding that corpus |

LibreOffice is an enhancement, not a hard dependency. Each table-of-contents entry is a `PAGEREF`
field pointing at a bookmark in the same document, carrying a dirty flag; Word and LibreOffice
resolve the page numbers on open (measured identical to the pre-computed values, entry by entry).
The only difference is whether the number is already there or is computed as the document opens.
Install it if you send reports to other people and want the numbers frozen at export time.

### How much space this needs

The repository itself is small (~13 MB, a thousand-odd files, nearly all source), but **set aside
about 3.3 GB** to run it. Most of that lands outside the project directory, where `du` on the
project folder will never show it:

| Where | What | Approx. |
|---|---|---|
| Outside the repo | Supabase container images (4, pulled on first start) | 2.3 GB |
| Outside the repo | Supabase data volumes | 80 MB |
| In the repo | Frontend dependencies (npm install output) | 560 MB |
| In the repo | Backend virtualenv (uv sync output) | 170 MB |
| In the repo | Frontend build cache (grows with use) | 150 MB+ |

The first install is mostly network transfer: roughly **15–30 minutes**, dominated by the image pull.

Five Supabase services are switched off because this product does not use them — Studio, Edge
Runtime, Realtime, PostgREST and the local mail catcher, together about 2.6 GB of images. Nothing
here calls an edge function or a realtime subscription; the backend talks to Postgres over asyncpg
rather than PostgREST; and no email is ever sent, because the first account is created already
confirmed. Four containers remain: Postgres, auth, storage and the gateway.

If you want the database admin UI, set `[studio] enabled` back to `true` in `supabase/config.toml`
and restart the stack.

Three more are **not installed by default**:

- **LibreOffice** (~800 MB): see above.
- **Scanned-document OCR** (~220 MB): `uv sync --extra ocr`. Without it, text-based PDF, Word and
  Excel files still parse; only **image-only scanned PDFs** fail, with an explicit message naming
  the missing component rather than silently returning nothing.
- **Playwright browsers** (~540 MB): only needed for `npm run test:e2e`; install with
  `npx playwright install chromium`.

macOS:

```bash
brew install node uv docker supabase/tap/supabase pandoc
brew install --cask libreoffice   # optional: pre-compute TOC page numbers at export
```

Linux (Debian / Ubuntu). The Supabase CLI is not in the distribution repositories, so fetch it
separately:

```bash
# Node 22: distribution packages are usually older, so use NodeSource
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv
sudo apt install -y docker.io pandoc
sudo apt install -y libreoffice-writer                   # optional, and much smaller than the macOS cask
# Supabase CLI: grab the .deb for your architecture (see its Releases page for versions)
curl -fsSLO https://github.com/supabase/cli/releases/latest/download/supabase_linux_amd64.deb \
  && sudo dpkg -i supabase_linux_amd64.deb
```

Then run the check once:

```bash
make doctor
```

## 2. Start the local Supabase stack

```bash
make supabase-up
```

Use this target rather than a bare `supabase start`: two of the exclusions are command-line
arguments rather than stored config, so typing `supabase start` by hand quietly pulls and runs
about 900 MB of services nothing here uses.

The first run pulls about 2.3 GB of images — 8–15 minutes depending on your connection; later
starts take seconds. When it finishes, `supabase status` prints the connection values used next.

## 3. Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Then fill in three values from the `supabase status` output:

| Variable in `.env` | Which `supabase status` field |
|---|---|
| `SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET` | `JWT_SECRET` |
| `SUSTAINABILITY_DESK_SUPABASE_SERVICE_KEY` | `SERVICE_ROLE_KEY` |
| `SUSTAINABILITY_DESK_PUBLIC_SUPABASE_ANON_KEY` | `ANON_KEY` |

The database and API addresses (`DATABASE_URL`, `SUPABASE_URL`) already hold local defaults in the
template and usually need no change.

You also need one model credential. The default is Azure OpenAI:

```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<resource-name>.cognitiveservices.azure.com/
```

Any OpenAI-compatible service works too (self-hosted vLLM, Ollama, a proxy gateway): uncomment the
three `OPENAI_COMPAT_*` lines in `.env.example`. No code changes needed. DeepSeek, Zhipu GLM,
Alibaba Qwen and Moonshot are also registered out of the box — set the matching key.

## 4. Run the tests

```bash
make verify
```

**This must come after steps 2 and 3; the order cannot be swapped.** `make verify` runs pytest
directly and does not itself check that the database is reachable. With the stack down, the
account, report, generation and export tests take `pytest.skip` and pass silently. The result is
that **you see all green while the database layer was never exercised**. Start the stack first, and
the pass means something.

## 5. Start the services

```bash
./scripts/dev/local-acceptance-stack.sh up
```

That starts three processes — backend (:8010), the material-processing worker, and the frontend
(:3000) — and returns once they are ready. To check or stop them:

```bash
./scripts/dev/local-acceptance-stack.sh status
./scripts/dev/local-acceptance-stack.sh down
```

You can also start them by hand in three terminals, which makes logs easier to follow while
debugging:

```bash
make dev-backend     # http://127.0.0.1:8010
make dev-worker      # queue consumer
make dev-frontend    # http://localhost:3000
```

**The worker is not optional.** Material processing and report generation are Postgres queues
consumed by that process. With only the backend and frontend running, the UI logs in and accepts
uploads, but "Generate report" waits forever.

## 6. Create the first account

The auth stack has public sign-up switched off (there is no registration page), so the first
account is created from the command line:

```bash
# See what it would do first
make provision-owner ARGS="--email you@example.com"

# Then apply
SUSTAINABILITY_DESK_OWNER_PASSWORD='<12+ chars, mixed case and digits>' \
SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES \
  make provision-owner ARGS="--email you@example.com --apply"
```

The password must be at least 12 characters and contain lowercase, uppercase and digits. Missing
variables produce an explicit error rather than silently creating an account you cannot sign in
with; an existing account is reused and its password is never reset.

Then open <http://localhost:3000> and sign in. **Use `localhost`, not `127.0.0.1`**: the Next dev
server rejects origins other than its start hostname, and `127.0.0.1` leaves the page stuck on an
authentication error.

## Troubleshooting

**"Generate report" waits forever** — the worker is not running. Check with
`./scripts/dev/local-acceptance-stack.sh status` that `material-worker` is up.

**TOC page numbers show as 0 or need refreshing** — expected without LibreOffice; the reader
resolves them on open. Install LibreOffice to have them computed at export time.

**`make verify` is green but you are unsure the database was covered** — see step 4. Persistence
tests skip silently when the stack is down. Confirm with `supabase status`, then run it again.

**The page says the report was created under an older contract version** — that report predates a
contract change. Create a new one.

**Backend code changed but behaviour did not** — the stack script's backend process does not
hot-reload. Run `down` then `up`.
