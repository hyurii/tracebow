# Real CI failures (zero egress — no ngrok)

Tracebow ingests **real** failures from Jenkins and GitHub. CI systems run inside
your network and POST to `http://agent:8080`. No third-party tunnels.

## Jenkins (local)

1. Jenkins: http://localhost:8081 (`admin` / `admin`)
2. Job **`tracebow-demo-failure`** fails and notifies Tracebow on failure
3. Cron every 30 min, or **Build Now** for immediate test

```bash
./scripts/jenkins-seed-demo-job.sh
```

## GitHub Actions (self-hosted runner)

GitHub **cloud** runners cannot reach a private Tracebow instance. Use a
**self-hosted runner** in the same Docker Compose stack:

```bash
# PAT in .env as GITHUB_TOKEN (repo admin — registers runner)
./scripts/github-runner-up.sh
```

This starts a runner with labels `self-hosted`, `tracebow`, `zero-egress`.
Workflows post to `http://agent:8080` on failure — traffic stays on your network.

1. Push workflows (on your branch or `main`):
   - `.github/workflows/ci-demo-failure.yml`
   - `.github/workflows/tracebow-on-ci-demo-failure.yml`

2. Start runner: `./scripts/github-runner-up.sh`

3. Run: GitHub → Actions → **CI Demo Failure** → **Run workflow**

The runner contacts GitHub only to receive jobs (same as any self-hosted setup).
Failure logs are sent **directly** to Tracebow, not through external relays.

## No simulation

```bash
CI_DEMO_SIMULATOR_ENABLED=false
```

Do not use the `ci-demo-simulator` compose profile.

## Portal

http://localhost:3000/failures
