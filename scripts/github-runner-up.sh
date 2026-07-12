#!/usr/bin/env bash
# Register and start a self-hosted GitHub Actions runner on the Tracebow Docker network.
# Zero-egress: workflows POST to http://agent:8080 (no ngrok).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.ci-demo.yml)
if [[ "${CI_DEMO_DEV:-}" == "1" ]]; then
  COMPOSE_FILES=(-f docker-compose.dev.yml -f docker-compose.ci-demo.yml)
fi

# shellcheck disable=SC1091
set -a
[[ -f .env ]] && source .env
set +a

REPO="${GITHUB_REPO:-hyurii/tracebow}"

if [[ -z "${GITHUB_RUNNER_TOKEN:-}" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "Install GitHub CLI (gh) or export GITHUB_RUNNER_TOKEN from:" >&2
    echo "  gh api --method POST repos/${REPO}/actions/runners/registration-token --jq .token" >&2
    exit 1
  fi
  echo "Fetching runner registration token for ${REPO}..."
  GITHUB_RUNNER_TOKEN=$(gh api --method POST "repos/${REPO}/actions/runners/registration-token" --jq .token)
  export GITHUB_RUNNER_TOKEN
fi

echo "Starting self-hosted GitHub runner (profile github-runner)..."
docker compose "${COMPOSE_FILES[@]}" --profile github-runner up -d github-runner

cat <<EOF

GitHub self-hosted runner is starting.

  Labels: self-hosted, tracebow, zero-egress
  Tracebow: http://agent:8080 (internal)

Verify in GitHub → Settings → Actions → Runners.

Then run workflow: Actions → CI Demo Failure → Run workflow
(branch must include the updated workflow YAML on ${REPO}).

EOF
