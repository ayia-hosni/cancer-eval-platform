## Summary
<!-- What does this PR do? One paragraph. -->

## Type of change
- [ ] Bug fix
- [ ] New feature / service
- [ ] ML model update (include val metrics)
- [ ] Infrastructure / config change
- [ ] Refactor / cleanup
- [ ] Documentation

## ML changes (if applicable)
| Metric | Before | After |
|--------|--------|-------|
| Val AUC / C-index | | |
| Test AUC / C-index | | |
| p99 inference latency | | |

## FHIR compliance
- [ ] New/modified Observation resources validated against FHIR R4 schema
- [ ] LOINC codes correct (reference: https://loinc.org)
- [ ] Extension URLs follow `http://cancer.platform/...` convention

## Security checklist
- [ ] No secrets, credentials, or PHI in code or commit history
- [ ] No model weights committed (use S3 / DVC)
- [ ] `.env` files excluded (only `.env.example` updated if needed)
- [ ] Patient IDs hashed in logs (HMAC-SHA256)
- [ ] Audit trail covers new patient data access paths

## Tests
- [ ] Unit tests added / updated
- [ ] Integration test `tests/integration_test.py` passes locally
- [ ] CI green on this branch

## How to test
```bash
# Steps to reproduce locally
```

## Related issues
Closes #
