# Tracebow

[![CI](https://github.com/tracebow/tracebow/actions/workflows/ci.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/ci.yml)
[![Security](https://github.com/tracebow/tracebow/actions/workflows/security.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/security.yml)
[![Snyk](https://github.com/tracebow/tracebow/actions/workflows/snyk.yml/badge.svg)](https://github.com/tracebow/tracebow/actions/workflows/snyk.yml)
[![Known Vulnerabilities](https://snyk.io/test/github/tracebow/tracebow/badge.svg)](https://snyk.io/test/github/tracebow/tracebow)

**Local, Zero-Egress AI Platform for CI/CD Root Cause Analysis**

Tracebow is a fully self-hosted, containerized AI application that performs unified root cause analysis across Jenkins, GitHub Actions, Jira, and Slack. It employs Retrieval-Augmented Generation (RAG) with autonomous agents to diagnose pipeline failures -- all running within your infrastructure with **zero data egress**.

No proprietary code or private logs are ever sent to external APIs.

## Features

- **Zero Egress**: All inference and data processing runs locally -- nothing leaves your network
- **Run Anywhere**: Mac, Windows + Docker Desktop, cheap standard EC2 (t3/m5/c6i), all CPU inference
- **Cross-Platform Correlation**: Jenkins logs + GitHub PRs + Jira tickets + Slack threads
- **Agentic RCA**: Autonomous C-P-A loop (Context -> Planning -> Action)
- **Hybrid RAG**: Dense vector + BM25 + Graph RAG for blast radius mapping
- **Dual-Model Strategy**: phi4-mini for deep RCA reasoning, llama3.2:3b for fast chat/summarization
- **Go CLI Agent**: Lightweight binary drops into any CI pipeline -- no Python needed on runners
- **MCP Integration**: Model Context Protocol for dynamic tool use
- **Durable Task Queue**: RabbitMQ broker + Celery workers -- guaranteed delivery, retries, backpressure

## Privacy & Security

**Air-gapped ready:** After the initial `docker compose up` has pulled container images and Ollama has finished downloading models into your local volume, Tracebow can run in a **fully air-gapped** environment with **no outbound Internet access**. Containers do not require ongoing cloud calls for inference or RAG once artifacts are local.

## Quick Start

Defaults are set in `docker-compose.yml` (`x-tracebow-agent-environment`). Adjust them there if you need different ports, passwords, or integration credentials.

```bash
docker compose up -d
```

**First run:** Startup may take several minutes the first time while Ollama downloads **phi4-mini**, **llama3.2:3b**, and **nomic-embed-text** into the Ollama data volume. The stack can look idle during large pulls; that is expected.

Then open:
- **Developer Portal** at http://localhost:3000
- **API docs** at http://localhost:8080/docs

To enable the Flower task monitoring dashboard (debug/support diagnostics only) with the **customer** compose file:

```bash
docker compose --profile debug up -d
```

`docker-compose.dev.yml` already starts Flower by default—no `--profile debug` needed there.

### Pin a version

Override the `TRACEBOW_VERSION` variable to pin to a specific release:

```bash
TRACEBOW_VERSION=0.2.1 docker compose up -d
```

### Development

For local development with source code builds, Flower always on, and all debug ports exposed:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

| | `docker-compose.yml` (customer) | `docker-compose.dev.yml` |
|---|---|---|
| Images | Pre-built from `ghcr.io/tracebow/*` | Built from local `./agent` and `./portal` |
| Source code required | No | Yes |
| Flower | Off by default (`--profile debug` to enable) | Always on |
| Debug ports (RabbitMQ mgmt, Neo4j browser, Redis, etc.) | Not exposed | All exposed |
| Resource limits | Enforced | Not set (dev flexibility) |

## Hardware

Ollama runs on **CPU** in Docker for this project.

**Minimum: 8 GB RAM** (e.g. t3.large, m5.large, or a MacBook with 8 GB+). The full stack (Ollama with three models loaded, Neo4j, ChromaDB, RabbitMQ, Redis, Celery workers) uses roughly 5-6 GB at idle.

| Resource | Recommendation |
|----------|----------------|
| RAM | 6 GB minimum, 16 GB recommended for production |
| CPU | 2+ cores (4 recommended)|
| Disk | 20 GB free (model weights + vector/graph data) |

All memory limits are set per-container in `docker-compose.yml` (`deploy.resources.limits`) to prevent any single service from crashing the host. Tune `CELERY_WORKER_CONCURRENCY` (default 4) to match available cores.

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
|  Developer Portal (React)    http://localhost:3000         |
+-----------------------------+-----------------------------+
                              |  /api/v1/*
+-----------------------------v-----------------------------+
|  FastAPI (agent)             http://localhost:8080         |
|  Validates, enqueues, returns task_id (202 Accepted)      |
+----------+---------------------------------+--------------+
           | enqueue                         | poll results
           v                                v
  +----------------+              +----------------+
  |   RabbitMQ     |              |     Redis      |
  |   (broker)     |              |   (results +   |
  |   :5672        |              |    cache)      |
  |   mgmt :15672  |              |   :6379        |
  +-------+--------+              +----------------+
          | consume                       ^
          v                               | store result
  +-----------------------------------------------+
  |  Celery Workers (N)                            |
  |  Queues: rca, default, maintenance             |
  |  Rate-limited to protect Ollama                |
  |                                                |
  |  +--------+  +--------+  +-------+            |
  |  | Ollama |  |ChromaDB|  | Neo4j |            |
  |  | LLM    |  | Vector |  | Graph |            |
  |  +--------+  +--------+  +-------+            |
  +------------------------------------------------+

  Celery Beat   -> periodic health checks + maintenance
  Flower        -> real-time worker monitoring (:5555)

LLM Models (via Ollama):
  phi4-mini        -> deep coding / stack trace / RCA reasoning
  llama3.2:3b      -> fast chat / Jira+Slack RAG summarization
  nomic-embed-text -> embeddings
```

### Services

| Service | Role | Port |
|---------|------|------|
| **agent** | FastAPI — accepts requests, enqueues tasks | 8080 |
| **celery-worker** | Processes RCA / chat / maintenance tasks | — |
| **celery-beat** | Periodic task scheduler | — |
| **flower** | Celery monitoring dashboard | 5555 |
| **rabbitmq** | Message broker (durable queues, backpressure) | 5672 / 15672 |
| **redis** | Result backend + embedding cache | 6379 |
| **ollama** | Local LLM inference (CPU) | 11434 |
| **chromadb** | Vector store for RAG | 8000 |
| **neo4j** | Knowledge graph (blast radius) | 7474 / 7687 |
| **portal** | React developer UI | 3000 |

### Request flow

1. CI pipeline fails — webhook or CLI sends payload to FastAPI
2. FastAPI validates and enqueues a Celery task via RabbitMQ — returns `202 Accepted` with `task_id`
3. Celery worker picks up the task — runs retrieval (ChromaDB + Neo4j) — LLM synthesis (Ollama) — stores result in Redis
4. Client polls `GET /api/v1/tasks/{task_id}` until status is `SUCCESS`

### Scaling workers

```bash
# Scale to 8 worker processes
docker compose up -d --scale celery-worker=2
```

Each `celery-worker` container runs `CELERY_WORKER_CONCURRENCY` (default 4) processes. Two containers = 8 workers. Tune `CELERY_RCA_RATE_LIMIT` to match your Ollama throughput.

## Enterprise Customization

Tracebow is designed to be model-agnostic. While we ship **phi4-mini** as the default for its strong logic-to-size tradeoff, we can help you integrate and tune other models (for example Mistral, IBM Granite, or internal fine-tuned weights) to meet security or compliance requirements.

Need a custom model, a different embedding provider, or a private MCP server? Contact our engineering team at **tracebow@proton.me** to discuss custom integration and enterprise support.

## License

Tracebow is [Fair Source](https://fair.io/) licensed under the **[Functional Source License, Version 1.1 (FSL-1.1-ALv2)](LICENSE.md)**.

- **Free to use** for any non-competing purpose -- including running it inside a multi-billion dollar company's internal CI/CD pipeline.
- **Non-Compete clause** -- the only restriction is that you may not use Tracebow to build a competing commercial product or service.
- **Converts to Apache 2.0** automatically on **April 10, 2028** (two years from initial release). Every release follows the same two-year conversion schedule.

If you are a competitor or a large enterprise that requires a commercial license, please contact us at **tracebow@proton.me**.

## Security

See [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.

All security tooling configurations are public in this repository as a trust signal. Scan results feed into GitHub's Security tab (Code Scanning, Dependabot alerts). No API keys or tokens are stored in code — all secrets live in GitHub Actions encrypted secrets.

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
