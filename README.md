# Tracebow

**Local, Zero-Egress AI Platform for CI/CD Root Cause Analysis**

Tracebow is a fully self-hosted, containerized AI application that performs unified root cause analysis across Jenkins, GitHub Actions, Jira, and Slack. It employs Retrieval-Augmented Generation (RAG) with autonomous agents to diagnose pipeline failures — all running within your infrastructure with **zero data egress**.

No proprietary code or private logs are ever sent to external APIs.

## Features

- **Zero Egress**: All inference and data processing runs locally — nothing leaves your network
- **Run Anywhere**: Mac laptops (Apple Silicon), Windows + Docker Desktop, cheap standard EC2 (t3/m5/c6i)
- **Cross-Platform Correlation**: Jenkins logs + GitHub PRs + Jira tickets + Slack threads
- **Agentic RCA**: Autonomous C-P-A loop (Context → Planning → Action)
- **Hybrid RAG**: Dense vector + BM25 + Graph RAG for blast radius mapping
- **Dual-Model Strategy**: phi4-mini for deep RCA reasoning, llama3.2:3b for fast chat/summarization
- **Go CLI Agent**: Lightweight binary drops into any CI pipeline — no Python needed on runners
- **MCP Integration**: Model Context Protocol for dynamic tool use

## Quick Start

```bash
cp .env.example .env        # edit values as needed
docker compose up -d        # CPU-only, works everywhere

# Developer Portal: http://localhost:3000
# API docs:         http://localhost:8080/docs
```

### With NVIDIA GPU (Linux)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Or set in `.env`:

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
```

## Hardware Compatibility

| Environment | What Ollama uses | Expected latency (3B model) |
|---|---|---|
| Mac (M1–M4) | Metal GPU via unified memory | Seconds |
| Windows + NVIDIA GPU | CUDA | Seconds |
| Windows / Linux CPU | AVX2 | 30–60 s |
| Cheap EC2 (t3, m5, c6i) | AVX2 (Intel Xeon / AMD EPYC) | 1–3 min |
| Linux + NVIDIA GPU | CUDA (via docker-compose.gpu.yml) | Seconds |

Ollama auto-detects available hardware — no code changes needed.

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
                      ┌────────────────────┐
                      │   CI/CD Pipeline   │
                      │ (Jenkins / GitHub) │
                      └────────┬───────────┘
                               │ failure → tracebow-cli --log=build.log
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Developer Portal (React)                          │
│                    http://localhost:3000                             │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│              Agent Orchestration + MCP Tool Layer                    │
│              (Python / FastAPI)                                       │
│              http://localhost:8080                                    │
└──┬──────────┬──────────┬──────────┬──────────┬──────────────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐  ┌───────┐  ┌───────┐  ┌──────┐  ┌───────┐
│Ollama│  │Qdrant │  │Neo4j  │  │Jenkins│  │GitHub │
│ LLM  │  │Vector │  │Graph  │  │ MCP   │  │ MCP   │
└──────┘  └───────┘  └───────┘  └──────┘  └───────┘

LLM Models (via Ollama):
  phi4-mini        → deep coding / stack trace / RCA reasoning
  llama3.2:3b      → fast chat / Jira+Slack RAG summarization
  nomic-embed-text → embeddings
```

## License

Apache 2.0 (Community) / Commercial (Enterprise)
