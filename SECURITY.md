# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (main) | Yes |
| < latest | Best effort |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in Tracebow, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email **tracebow@proton.me** with:

1. A description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if you have one)

We will acknowledge receipt within **48 hours** and aim to provide a fix or mitigation within **7 days** for critical issues.

## Security Practices

Tracebow follows industry-standard security practices:

- **SAST**: CodeQL, Semgrep, and Bandit scan every push and pull request
- **SCA**: Snyk, OSV-Scanner, pip-audit, npm audit, and govulncheck check dependencies for known CVEs
- **Container Scanning**: Trivy and Snyk scan Docker images for OS and application vulnerabilities
- **License Compliance**: Trivy license scanning prevents copyleft transitive dependencies
- **IaC Scanning**: Checkov and Snyk IaC validate Dockerfiles, compose files, and GitHub Actions
- **Secret Detection**: Gitleaks runs on every commit (pre-commit) and in CI
- **Dependency Updates**: Dependabot opens PRs weekly for outdated dependencies across all ecosystems
- **Code Quality**: SonarCloud monitors code smells, duplication, and security hotspots

## Architecture Security

- **Zero egress**: All AI inference and data processing runs locally — no data leaves your network
- **Air-gap ready**: After initial image and model pulls, Tracebow operates with no outbound Internet
- **No telemetry**: Tracebow does not phone home or collect usage data
- **Secrets management**: All credentials are passed via environment variables, never hardcoded
