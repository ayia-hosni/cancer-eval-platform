# Branch Protection Rules

Configure these in: Settings → Branches → Add rule

## `main` branch (production)
- [x] Require pull request before merging
  - Required approvals: **2** (1 engineer + 1 security/clinical lead)
- [x] Require status checks to pass:
  - `ML Services CI / Lint + Unit Tests`
  - `Spring Boot Services CI / Build + Test (patient-service)`
  - `ML Services CI / Security Scan`
- [x] Require branches to be up to date before merging
- [x] Require signed commits (GPG)
- [x] Include administrators
- [x] Restrict who can push: only Release Managers

## `develop` branch (staging)
- [x] Require pull request before merging
  - Required approvals: **1**
- [x] Require status checks to pass:
  - `ML Services CI / Lint + Unit Tests`
  - `Spring Boot Services CI / Build + Test (*)`
- [x] Require branches to be up to date before merging
- [ ] Restrict push (any developer can push feature branches here)

## Feature branches: `feature/*`, `fix/*`, `ml/*`
- No protection required — CI runs on all PRs automatically.
