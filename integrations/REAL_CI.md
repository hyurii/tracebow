# Real CI failures (no simulator)

Tracebow ingests **real** failures from Jenkins and GitHub — not synthetic webhooks.

## Jenkins (local, already wired)

1. Jenkins runs at http://localhost:8081 (`admin` / `admin`)
2. Job **`tracebow-demo-failure`** fails on purpose and POSTs to Tracebow on failure
3. Cron: every 30 minutes; or **Build Now** for immediate test
4. Console logs are pre-fetched during RCA (requires `JENKINS_*` in `.env`)

```bash
./scripts/jenkins-seed-demo-job.sh   # create/update job + trigger build
```

## GitHub Actions (requires push + reachable Tracebow URL)

GitHub-hosted runners **cannot** call `http://localhost:8080`. You need:

1. **Push** the workflow files to GitHub:
   - `.github/workflows/ci-demo-failure.yml`
   - `.github/workflows/tracebow-on-ci-demo-failure.yml`

2. **Expose** your local agent, e.g.:
   ```bash
   ngrok http 8080
   # or: tailscale funnel 8080
   ```

3. **Repository secrets** (Settings → Secrets → Actions):
   | Secret | Value |
   |--------|--------|
   | `TRACEBOW_WEBHOOK_URL` | `https://<public-host>/api/v1/webhooks/github` |
   | `TRACEBOW_ANALYZE_URL` | (optional) `https://<public-host>/api/v1/analyze` |

4. **Run** Actions → **CI Demo Failure** → **Run workflow**

The follow-up workflow `Tracebow RCA on CI Demo Failure` notifies Tracebow when the demo job fails.

## Disable all simulation

In `.env`:

```bash
CI_DEMO_SIMULATOR_ENABLED=false
CI_DEMO_SIMULATOR_GITHUB=false
```

Do **not** start the `ci-demo-simulator` compose profile.

## Portal

Failures: http://localhost:3000/failures

Only **jenkins** rows from real Jenkins builds and **github** rows from real workflow runs should appear after simulator is off.
