# Security

## Reporting a vulnerability

Email **dexter.yao23@gmail.com** with a description and reproduction steps. Please do not open
a public issue for anything exploitable. Expect a first reply within a week; this is a personal
project, not a staffed product.

## What is in scope

This is a single-user application intended to run on your own machine against a local Supabase
stack. Relevant classes of issue:

- Authentication or report-scope bypass that lets one account read or write another's data.
- Leakage of user-supplied material into logs, traces, prompts or the exported document beyond
  what the report itself is meant to contain.
- Anything that writes to the database or filesystem outside the paths the feature declares.

## What is not

- Running the stack exposed to a public network. It is not built or tested for that, and
  `make doctor` deliberately refuses a non-local configuration.
- Model output quality — wrong or invented report text is a correctness matter, not a security
  one. Report it as a normal issue.

## Handling of credentials and company data

API keys and account passwords are injected through environment variables only; `backend/.env`
is git-ignored and no key is ever committed. Real company material must never enter the
repository — the corpora under `backend/tests/fixtures/` are entirely synthetic, and a gitleaks
configuration (`.gitleaks.toml`) documents why the remaining scanner hits in the knowledge
packages are ESG metric identifiers rather than secrets.
