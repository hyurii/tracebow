# Tracebow

[![CI](https://github.com/tracebow/tracebow/actions/workflows/ci.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/ci.yml)
[![Security](https://github.com/tracebow/tracebow/actions/workflows/security.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/security.yml)
[![Snyk](https://github.com/tracebow/tracebow/actions/workflows/snyk.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/snyk.yml)
[![Known Vulnerabilities](https://snyk.io/test/github/tracebow/tracebow/badge.svg)](https://snyk.io/test/github/tracebow/tracebow)

**Local, Zero-Egress AI Platform for CI/CD Root Cause Analysis**

Tracebow is a fully self-hosted, containerized AI application that performs root cause analysis across Jenkins, GitHub Actions, Jira, and Slack. It runs a LangGraph orchestrator on **local LLMs via Ollama**, builds knowledge in a **Git-backed Markdown wiki** (not a vector DB), and stores telemetry in **PostgreSQL**. Everything runs inside your network with **zero data egress**.

No proprietary code or private logs are ever sent to external APIs.

## Features

- **Zero Egress**: All inference and data processing runs locally — nothing leaves your network
- **Run Anywhere**: Mac, Windows + Docker Desktop, standard EC2 (t3/m5/c6i), all CPU inference
- **LangGraph Orchestrator**: Deterministic state machine — `ingest → search_wiki → (reuse runbook) or (reason + write runbook)`
- **Git-Backed LLM Wiki**: Human-readable Markdown runbooks under version control — readable, diffable, reviewable, portable
- **Native Python Tools**: LangGraph `@tool` functions for Jenkins / GitHub / Jira / Slack — no separate MCP servers to run
- **PostgreSQL Telemetry**: Every failure + RCA is persisted as a first-class row — browse, query, audit
- **Go CLI Agent**: Single-file binary drops into any CI pipeline — no Python on runners
- **Optional Wiki Backup**: Push the wiki to any SSH Git remote — GitHub, GitLab, Gitea, Bitbucket, or self-hosted — with a deploy key, configured per-install from the portal
- **Dual-Model Strategy**: `phi4-mini` for deep RCA reasoning, `llama3.2:3b` for chat/summarization

## Privacy & Security

**Air-gapped ready:** After the initial `docker compose up` has pulled container images and Ollama has finished downloading models into your local volume, Tracebow can run in a **fully air-gapped** environment with **no outbound Internet access**. No vector DB embeddings, no external API calls, no telemetry leaves the host.

The optional wiki backup push is the **only** outbound network call, is explicitly opt-in per install, and only uses the deploy key and remote URL you configure in the portal.

## Quick Start

Defaults are set in `docker-compose.yml` (`x-tracebow-agent-environment`). Copy `.env.example` to `.env` if you want to override anything (integration credentials, wiki path, backup schedule, etc.).

```bash
docker compose up -d
```

**First run:** Startup may take several minutes the first time while Ollama downloads **phi4-mini** and **llama3.2:3b** into the Ollama data volume. The stack can look idle during large pulls; that is expected.

Then open:

- **Developer Portal** at http://localhost:3000
- **API docs** at http://localhost:8080/docs
- **Wiki browser** at http://localhost:3000/wiki

### Pin a version

Override the `TRACEBOW_VERSION` variable to pin to a specific release:

```bash
TRACEBOW_VERSION=0.2.1 docker compose up -d
```

### Development

For local development with source code builds and all debug ports exposed:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

| | `docker-compose.yml` (customer) | `docker-compose.dev.yml` |
|---|---|---|
| Images | Pre-built from `ghcr.io/tracebow/*` | Built from local `./agent` and `./portal` |
| Source code required | No | Yes |
| Debug ports (Postgres, Redis) | Not exposed | All exposed |
| Resource limits | Enforced | Not set (dev flexibility) |

## Hardware

Ollama runs on **CPU** in Docker for this project.

**Minimum: 8 GB RAM** (e.g. t3.large, m5.large, or a MacBook with 8 GB+). The full stack (Ollama with two models loaded, Postgres, Redis, Celery worker, FastAPI) uses roughly 4-5 GB at idle — considerably lighter than the previous vector+graph DB stack.

| Resource | Recommendation |
|----------|----------------|
| RAM | 8 GB minimum, 16 GB recommended for production |
| CPU | 2+ cores (4 recommended) |
| Disk | 15 GB free (model weights + Postgres data + wiki repo) |

All memory limits are set per-container in `docker-compose.yml` (`deploy.resources.limits`) to prevent any single service from crashing the host. Tune `CELERY_WORKER_CONCURRENCY` (default 2) to match available cores.

## Go CLI Agent

The `tracebow-cli` binary is a single-file executable that CI runners call on failure to push logs to the Tracebow server. Zero dependencies, zero interpreter.

### Build

```bash
cd tracebow-cli
make all          # outputs linux-amd64, darwin-arm64, darwin-amd64, windows-amd64
```

### Usage in GitHub Actions

```yaml
- name: Tracebow RCA
  if: failure()
  run: |
    ./tracebow-cli \
      --repo=${{ github.repository }} \
      --pr=${{ github.event.pull_request.number }} \
      --job=${{ github.workflow }} \
      --log=build.log \
      --backend=http://your-server:8080/api/v1/analyze
```

### Usage in Jenkinsfile

```groovy
post {
    failure {
        sh '''
            ./tracebow-cli \
                --repo=${GIT_URL} \
                --job=${JOB_NAME} \
                --url=${BUILD_URL} \
                --log=${WORKSPACE}/build.log \
                --backend=http://your-server:8080/api/v1/analyze
        '''
    }
}
```

## Architecture

```
CI Pipelines (Jenkins / GitHub Actions)
  |  failure -> tracebow-cli --log=build.log
  |             or webhook POST
  v
+-----------------------------------------------------------+
|  Developer Portal (React)    http://localhost:3000        |
|  - Dashboard / Failures / Wiki / Chat / Settings          |
+-----------------------------+-----------------------------+
                              |  /api/v1/*
+-----------------------------v-----------------------------+
|  FastAPI (agent)             http://localhost:8080        |
|  Validates, persists Failure row, enqueues Celery task    |
+----------+-----------------------------------+------------+
           | enqueue                           | poll result
           v                                   v
  +----------------+                 +-------------------+
  |     Redis      |                 |    PostgreSQL     |
  |  (broker +     |                 |  Failures,        |
  |   result cache)|                 |  Stacktraces,     |
  |    :6379       |                 |  RcaReports,      |
  +-------+--------+                 |  WikiSettings,    |
          | consume                  |  BackupLog        |
          v                          |    :5432          |
  +-----------------------------+    +-------------------+
  |  Celery Worker              |
  |  queue: rca                 |
  |  - runs LangGraph           |
  |    orchestrator             |
  |  - persists RcaReport + Stacktrace
  |                             |
  |  +--------+   +----------+  |
  |  | Ollama |   | LLM Wiki |  |
  |  | LLM    |   | (git)    |  |
  |  +--------+   +----------+  |
  +-----------------------------+

  Celery Beat  -> optional wiki backup push (per schedule)

LLM Models (via Ollama):
  phi4-mini     -> deep coding / stack trace / RCA reasoning
  llama3.2:3b   -> fast chat / Jira+Slack summarization
```

### LangGraph flow

The agent is a **deterministic state machine**, not a free-form ReAct loop:

```
ingest (parse logs, extract stacktrace)
  -> search_wiki (token match against /wiki/**/*.md)
      -> hit?  -> read_wiki -> summarize -> done   (wiki_hit branch)
      -> miss? -> reason_with_tools -> write_wiki -> done   (novel_reasoned branch)
```

Every RCA either **reuses** an existing runbook (cheap, fast, consistent) or **produces one** (Markdown file committed to the wiki repo). Over time the wiki becomes the institutional memory for CI/CD failures.

### Services

| Service | Role | Port |
|---------|------|------|
| **agent** | FastAPI — accepts requests, persists failures, enqueues tasks | 8080 |
| **celery-worker** | Runs LangGraph RCA / backup tasks | — |
| **celery-beat** | Periodic wiki backup push (if enabled) | — |
| **postgres** | Telemetry store (failures, RCAs, wiki/backup settings) | 5432 |
| **redis** | Celery broker + result cache | 6379 |
| **ollama** | Local LLM inference (CPU) | 11434 |
| **portal** | React developer UI + wiki viewer | 3000 |

### Request flow

1. CI pipeline fails — webhook or CLI sends payload to FastAPI
2. FastAPI writes a `Failure` row to Postgres and enqueues a Celery task via Redis — returns `202 Accepted` with `task_id`
3. Celery worker runs the LangGraph orchestrator — either reuses a runbook from the wiki or reasons with native tools (Jenkins/GitHub/Jira/Slack) and commits a new runbook
4. Worker persists the `Stacktrace` + `RcaReport` rows, stores the final summary in Redis under the task id
5. Portal polls `GET /api/v1/tasks/{task_id}` until status is `SUCCESS`, then fetches the enriched failure from `GET /api/v1/failures/{id}`

### The LLM Wiki

Runbooks live under `/wiki/runbooks/` (and any folders you create) as plain Markdown:

```
/wiki
├── README.md
├── runbooks/
│   ├── maven-dependency-conflict.md
│   ├── flaky-testcontainers.md
│   └── ...
└── policies/
    └── ...
```

- **Human-readable and diffable** — no opaque embeddings to debug
- **Version controlled** — every change is a commit, with author + timestamp
- **Portable** — `cp -r /wiki/.` out of the container and you own the knowledge base
- **Optional backup** — configure any SSH Git remote (GitHub, GitLab, Gitea, Bitbucket, self-hosted) and a deploy key from the portal's Settings → Backup panel; a Celery beat task runs `git push` on your schedule

### PostgreSQL schema (abridged)

| Table | Purpose |
|-------|---------|
| `failures` | One row per CI/CD failure: repo, job, url, source, triggered_at |
| `stacktraces` | Parsed stacktrace excerpt + line count per failure |
| `rca_reports` | Summary, branch (`wiki_hit` / `novel_reasoned`), wiki path, tool trace, model, latency |
| `wiki_settings` | Optional backup config: remote URL, branch, schedule, encrypted deploy key |
| `wiki_backup_logs` | Success/failure + timestamp of each backup push |

Alembic migrations live under `agent/alembic/versions/`.

### Scaling workers

```bash
docker compose up -d --scale celery-worker=2
```

Each `celery-worker` container runs `CELERY_WORKER_CONCURRENCY` (default 2) processes. Two containers = 4 workers. Tune `CELERY_RCA_RATE_LIMIT` to match your Ollama throughput.

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Key knobs:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://tracebow:tracebow@postgres:5432/tracebow` | Postgres DSN (async) |
| `REDIS_URL` | `redis://redis:6379/0` | Redis (broker + result cache) |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| `OLLAMA_ENABLED` | `true` | Flip to `false` to run a deterministic stub (useful in CI/tests) |
| `WIKI_PATH` | `/wiki` | Wiki repo root inside the agent/worker containers |
| `WIKI_DEFAULT_BRANCH` | `main` | Default branch for the wiki repo |
| `WIKI_ENCRYPTION_KEY` | — | Fernet key used to encrypt the deploy key before storing |
| `JENKINS_URL` / `JIRA_URL` / `GITHUB_TOKEN` / `SLACK_TOKEN` | — | Integration credentials used by native tools |

Integration credentials can also be managed in the portal under Settings.

## Models

Tracebow ships only LLMs whose weights and training are produced by **Western providers**. Defaults:

- **`phi4-mini`** — Microsoft (US) — deep RCA reasoning
- **`llama3.2:3b`** — Meta (US) — chat / summarization

**Allowed providers:** Microsoft, Meta, Mistral AI (FR), IBM (Granite), Google DeepMind (Gemma).

**Forbidden by default:** Qwen, DeepSeek, Yi, ChatGLM/GLM, Baichuan, MiniMax, InternLM. A CI guard (`scripts/check_model_provenance.py`, run by the `model-provenance` job) fails the build if any of those names are referenced in a committed `docker-compose*.yml`.

The constraint is on the *provenance of the weights*, not where Ollama runs — Ollama is always local. Rationale and the full allow / deny list live in the project's local architecture notes; the policy is enforced in CI.

## Enterprise Customization

Tracebow is designed to be model-agnostic *within the allowed-providers policy above*. While we ship **phi4-mini** as the default for its strong logic-to-size tradeoff, we can help you integrate other Western-origin models (for example Mistral, Codestral, IBM Granite, Google Gemma, or internal fine-tuned weights derived from them) to meet security or compliance requirements.

Need a custom model, a custom embedding provider for an external wiki mirror, or first-class support for a non-Git knowledge store? Contact our engineering team at **tracebow@proton.me** to discuss custom integration and enterprise support.

## License

Tracebow is [Fair Source](https://fair.io/) licensed under the **[Functional Source License, Version 1.1 (FSL-1.1-ALv2)](LICENSE.md)**.

- **Free to use** for any non-competing purpose — including running it inside a multi-billion dollar company's internal CI/CD pipeline.
- **Non-Compete clause** — the only restriction is that you may not use Tracebow to build a competing commercial product or service.
- **Converts to Apache 2.0** automatically on **April 10, 2028** (two years from initial release). Every release follows the same two-year conversion schedule.

If you are a competitor or a large enterprise that requires a commercial license, please contact us at **tracebow@proton.me**.

## Security

See [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.

All security tooling configurations are public in this repository as a trust signal. Scan results feed into GitHub's Security tab (Code Scanning, Dependabot alerts). No API keys or tokens are stored in code — all secrets live in GitHub Actions encrypted secrets, and the wiki deploy key is encrypted at rest in Postgres with Fernet before being written.

### What runs on every push/PR

| Category | Tools | Scope |
|---|---|---|
| **SAST** | CodeQL, Semgrep | Python, TypeScript, Go |
| **SCA** | Snyk, OSV-Scanner, pip-audit, npm audit, govulncheck | All lockfiles and dependencies |
| **Containers** | Trivy (vulns + licenses), Snyk Docker | agent and portal images |
| **IaC** | Checkov, Snyk IaC | Dockerfiles, compose files, GitHub Actions |
| **Secrets** | Gitleaks | All committed files |
| **Quality** | SonarCloud | Code smells, duplication, security hotspots |
| **Dependencies** | Dependabot | Weekly PRs for Python, npm, Go, Docker, Actions |

### Setup for maintainers

These tools work out of the box with zero configuration for most scans. The following secrets and settings unlock the full pipeline:

| What | Where to configure | How |
|---|---|---|
| **SNYK_TOKEN** | Repo > Settings > Secrets > Actions | [Create a free Snyk account](https://app.snyk.io/), copy your API token from Account Settings |
| **SONAR_TOKEN** | Repo > Settings > Secrets > Actions | [Connect repo at sonarcloud.io](https://sonarcloud.io/), copy token from My Account > Security |
| **Dependabot** | Repo > Settings > Code security | Enable "Dependabot alerts" and "Dependabot security updates" |
| **Code Scanning** | Repo > Settings > Code security | Enable "Code scanning" (auto-enabled for public repos) |
| **Pre-commit (local)** | Developer machine | `pip install pre-commit && pre-commit install` (or `uv tool install pre-commit`) |

Without **`SNYK_TOKEN`** or **`SONAR_TOKEN`**, the corresponding jobs authenticate with an empty token and **fail** (unless you add a job-level `if: secrets.SNYK_TOKEN != ''` / `secrets.SONAR_TOKEN != ''` to skip them). Fork PRs skip Snyk and Sonar jobs entirely via workflow `if` conditions. Everything else (CodeQL, Semgrep, Trivy, OSV-Scanner, Checkov, Dependabot, pip-audit, npm audit, govulncheck, gitleaks) runs with zero additional setup on any public GitHub repo.
