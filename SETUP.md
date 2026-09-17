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

LibreOffice is optional. Without it, table-of-contents page numbers are resolved by whatever opens
the document; with it, they are computed at export and frozen into the file. Install it if you send
reports to people whose reader you cannot predict.

### How much space this needs

The repository itself is small (~13 MB, a thousand-odd files, nearly all source), but **set aside
about 2.5 GB** to run it. Most of that lands outside the project directory, where `du` on the
project folder will never show it:

| Where | What | Approx. |
|---|---|---|
| Outside the repo | Supabase container images (3, pulled on first start) | 1.5 GB |
| Outside the repo | Supabase data volumes | 80 MB |
| In the repo | Frontend dependencies (npm install output) | 560 MB |
| In the repo | Backend virtualenv (fresh `uv sync`) | 170 MB |
| In the repo | Frontend build cache (grows with use) | 150 MB+ |

The first install is mostly network transfer: roughly **15–30 minutes**, dominated by the image pull.

Three containers run: Postgres, auth and the gateway. Six more Supabase services — Studio, Edge
Runtime, Realtime, PostgREST, the mail catcher and the storage API — are switched off, which is
where most of the saving comes from. Uploaded files go to your own disk instead.

Two of those are worth knowing how to turn back on:

- **Database admin UI**: set `[studio] enabled` to `true` in `supabase/config.toml`, then restart.
- **Uploads in Supabase Storage**: clear `SUSTAINABILITY_DESK_LOCAL_STORAGE_ROOT` and drop
  `storage-api` from the exclusions in the `supabase-up` target.

Three components are **optional** — install them only when you need what they do:

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

Use this target rather than a bare `supabase start`: three of the exclusions are command-line
arguments rather than stored config, so typing `supabase start` by hand quietly pulls and runs
about 1.3 GB of services nothing here uses.

The first run pulls about 1.5 GB of images — 5–10 minutes depending on your connection; later
starts take seconds. When it finishes, `supabase status` prints the connection values used next.

## 3. Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Then fill in three values from the `supabase status` output:

The `SUSTAINABILITY_DESK_` prefix is the project's technical identifier and is deliberately
independent of the product name, so that renaming the product never breaks anyone's configuration.

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
