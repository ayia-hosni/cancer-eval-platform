# Contributing

## Branch naming

| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feature/<ticket>-<description>` | `feature/CEP-42-add-brca2-gene` |
| Bug fix | `fix/<ticket>-<description>` | `fix/CEP-99-shap-null-pointer` |
| ML model | `ml/<service>-<version>` | `ml/risk-classifier-v1.2` |
| Hotfix | `hotfix/<description>` | `hotfix/cve-critical-patch` |

## Commit message format (Conventional Commits)

```
<type>(<scope>): <short summary>

<body — what changed and why>

<footer — breaking changes, closes #issue>
```

**Types:** `feat` · `fix` · `ml` · `perf` · `refactor` · `test` · `ci` · `docs` · `chore`  
**Scopes:** `risk-classifier` · `survival-predictor` · `patient-service` · `orchestrator` · `audit` · `infra` · `fhir`

### Examples

```
feat(risk-classifier): add confidence interval to ensemble output

Adds 10th/90th percentile CI from ensemble variance to the FHIR
Observation extension block. Enables clinicians to assess prediction
certainty alongside the risk score.

Closes #47
```

```
ml(survival-predictor): upgrade DeepSurv to v1.2 (C-index +0.018)

Retrained on 1,200 patients (prev 800). Added EMT_score and
DNArepair_score features. Val C-index improved from 0.784 to 0.802.
Model weights uploaded to S3: models/survival-predictor/v1.2/

Closes #61
```

```
fix(audit-service): correct HMAC key rotation on Vault token refresh

HMAC key was not refreshed when Vault token renewed, causing patient
ID hashes to diverge between audit log and query layer.
```

## Local setup

```bash
# 1. Clone and set up pre-commit
git clone https://github.com/your-org/cancer-eval-platform
cd cancer-eval-platform
pip install pre-commit
pre-commit install       # installs hooks into .git/hooks/
pre-commit install --hook-type commit-msg   # conventional commits check

# 2. Copy env template
cp .env.example .env
# Edit .env — fill in local passwords (never commit .env)

# 3. Start dependencies
docker-compose up -d zookeeper kafka postgres mongodb redis

# 4. Run ML engines smoke test
python tests/integration_test.py
```

## What NOT to commit

| Never commit | Use instead |
|-------------|-------------|
| `.env` files | `.env.example` |
| Model weights (`*.pt`, `*.pkl`) | S3 path in `metadata.json` |
| Patient data | Synthetic datasets in `tests/fixtures/` |
| API keys / tokens | GitHub Secrets or Vault |
| Large datasets (>500 KB) | DVC or S3 |
