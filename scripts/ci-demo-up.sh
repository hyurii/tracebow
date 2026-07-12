#!/usr/bin/env bash
# Bootstrap Tracebow with Jenkins CI demo overlay.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.ci-demo.yml)
if [[ "${CI_DEMO_DEV:-}" == "1" ]]; then
  COMPOSE_FILES=(-f docker-compose.dev.yml -f docker-compose.ci-demo.yml)
fi

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example — set GITHUB_TOKEN before relying on GitHub webhooks."
  cp .env.example .env
fi

# Append CI demo defaults if missing
append_if_missing() {
  local key="$1" value="$2"
  if ! grep -q "^${key}=" .env 2>/dev/null; then
    echo "${key}=${value}" >> .env
  fi
}

append_if_missing JENKINS_URL "http://jenkins:8080"
append_if_missing JENKINS_USER "admin"
append_if_missing JENKINS_API_TOKEN "admin"
append_if_missing JENKINS_PORT "8081"
append_if_missing CI_DEMO_SIMULATOR_ENABLED "false"
append_if_missing CI_DEMO_SIMULATOR_GITHUB "false"

echo "Starting Tracebow + Jenkins CI demo..."
docker compose "${COMPOSE_FILES[@]}" up -d --build

if [[ "${CI_DEMO_SIMULATOR:-}" == "1" ]]; then
  echo "Starting failure simulator (profile ci-demo-simulator)..."
  docker compose "${COMPOSE_FILES[@]}" --profile ci-demo-simulator up -d failure-simulator
fi

if [[ -x "${ROOT}/scripts/jenkins-seed-demo-job.sh" ]]; then
  echo "Seeding Jenkins demo job..."
  "${ROOT}/scripts/jenkins-seed-demo-job.sh" || true
fi

cat <<EOF

CI demo is up.

  Portal:  http://localhost:\${PORTAL_PORT:-3000}/failures
  Agent:   http://localhost:\${API_PORT:-8080}/docs
  Jenkins: http://localhost:\${JENKINS_PORT:-8081}  (admin / admin)

Trigger a Jenkins failure: open Jenkins → tracebow-demo-failure → Build Now

Real GitHub failures: start a self-hosted runner (zero egress, no ngrok):

  ./scripts/github-runner-up.sh

Then run Actions → CI Demo Failure on GitHub (runner labels: tracebow, zero-egress).

Optional fake local webhooks only: CI_DEMO_SIMULATOR=1 ./scripts/ci-demo-up.sh

EOF
