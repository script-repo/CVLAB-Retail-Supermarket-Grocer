# Security Policy

## Reporting a vulnerability

Please report security issues privately. Open a
[GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, or open a regular issue **without** sensitive details and ask
a maintainer for a private channel. We aim to acknowledge reports within a few
business days.

## Secrets and configuration

This project never hard-codes credentials. All secrets are supplied at runtime:

- Local development: a gitignored `cv-lab/backend/.env` (copy from `.env.example`).
- Kubernetes: `Secret` objects (`nai-credentials`, `objects-credentials`).
  See `cv-lab/deploy/k8s/*.example.yaml`.

Before committing, make sure you are not adding any of the following:

- `.env` files, kubeconfigs, API keys, passwords, or bearer tokens
- Private keys or certificates (`*.key`, `*.pem`)
- Filled-in `nai-secret.yaml` / `objects-secret.yaml`

The repository ships a secret-scan GitHub Actions workflow
(`.github/workflows/secret-scan.yml`) and the `.gitignore` blocks the common
secret file patterns. Consider enabling
[GitHub secret scanning + push protection](https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning)
on your fork.

## Privacy note

The included computer-vision use cases are designed to be privacy-preserving
(anonymous detection/tracking, no facial recognition or biometric identification).
If you extend the project, keep that posture and comply with the laws applicable
to camera/CCTV analytics in your jurisdiction.
