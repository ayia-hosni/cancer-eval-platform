# Security Policy

## HIPAA Compliance Notice

This platform handles Protected Health Information (PHI).
Any security vulnerability that could expose PHI must be treated as **CRITICAL**.

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: security@your-org.com  
PGP key: [link to your key]

Include:
- Affected service(s)
- Steps to reproduce
- Potential impact (especially PHI exposure risk)
- Suggested fix (if known)

We will acknowledge within 24 hours and aim to patch within 72 hours for CRITICAL issues.

## Scope

| In scope | Out of scope |
|----------|--------------|
| SQL/NoSQL injection | Social engineering |
| PHI exposure via logs or API | Physical security |
| JWT / auth bypass | Third-party services (Kafka, MongoDB) |
| Model inversion attacks | DDoS |
| SHAP payload XSS in dashboard | |

## Security Controls

| Control | Implementation |
|---------|---------------|
| PHI encryption at rest | PostgreSQL pgcrypto (AES-256) |
| PHI in logs | HMAC-SHA256 patient ID hashing |
| Secrets management | HashiCorp Vault (prod), `.env` files (dev only) |
| Container security | Non-root user, read-only filesystem, no capabilities |
| Dependency scanning | Trivy (containers), OWASP (Java) on every PR |
| Secret scanning | Gitleaks pre-commit hook + GitHub Advanced Security |
