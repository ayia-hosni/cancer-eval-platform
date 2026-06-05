---
name: ML model update
about: Propose updating a model version
labels: ml, model-update
---

## Service
<!-- e.g. risk-classifier, survival-predictor -->

## Current model version
<!-- e.g. v1.0.0 -->

## Proposed version
<!-- e.g. v1.1.0 -->

## Motivation
<!-- Why is this update needed? Drift? Better data? New architecture? -->

## Training data
- Dataset:
- Size (n patients):
- Date range:
- De-identified: [ ] Yes

## Validation metrics
| Metric | Current | Proposed |
|--------|---------|----------|
| Val AUC / C-index | | |
| Test AUC / C-index | | |
| Calibration (ECE) | | |
| p99 inference ms | | |

## Checklist
- [ ] Model weights uploaded to S3 under `models/{service}/{version}/`
- [ ] `metadata.json` written with training params + metrics
- [ ] Drift check: KS-test p-value on feature distributions
- [ ] Clinical review sign-off obtained
