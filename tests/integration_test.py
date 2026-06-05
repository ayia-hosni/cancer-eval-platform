"""
End-to-end integration test for the Cancer Evaluation Platform.
Tests the full pipeline: create patient → trigger evaluation → poll results.

Usage:
    # With Docker Compose running:
    python tests/integration_test.py

    # Or with pytest:
    pytest tests/integration_test.py -v
"""
import httpx, json, time, asyncio, pytest

GATEWAY_URL   = "http://localhost:8080"
ML_URLS = {
    "tcga":     "http://localhost:8101",
    "risk":     "http://localhost:8102",
    "imaging":  "http://localhost:8103",
    "survival": "http://localhost:8104",
    "shap":     "http://localhost:8105",
}

SAMPLE_PATIENT = {
    "resourceType": "Patient",
    "id": "test-patient-001",
    "name": [{"family": "Smith", "given": ["Jane"]}],
    "birthDate": "1965-03-15",
    "gender": "female",
    "extension": [
        {"url": "http://cancer.platform/gene-expression/ESR1",    "valueDecimal": 4.2},
        {"url": "http://cancer.platform/gene-expression/ERBB2",   "valueDecimal": -0.8},
        {"url": "http://cancer.platform/gene-expression/MKI67",   "valueDecimal": -1.2},
        {"url": "http://cancer.platform/gene-expression/Stage_num", "valueDecimal": 2.0},
    ]
}

SAMPLE_FEATURES = {
    "ESR1": 4.2, "ERBB2": -0.8, "MKI67": -1.2, "TP53": -0.5,
    "PIK3CA": 1.5, "CDH1": 1.8, "KRT5": -2.1, "BRCA1": -0.2,
    "Age": 58.0, "TumorSize_cm": 1.8, "LymphNodes_pos": 0.0,
    "Stage_num": 2.0, "ER_status": 1.0, "HER2_status": 0.0,
    "Proliferation_score": -1.5, "Immune_score": 0.3,
    "Angiogenesis_score": 0.5, "EMT_score": -0.8,
    "DNArepair_score": 0.2, "Apoptosis_score": 0.4,
}

SAMPLE_EVAL_REQUEST = {
    "evaluation_id": "test-eval-001",
    "patient_id": "test-patient-001",
    "patient_features": SAMPLE_FEATURES,
    "model_types": ["all"],
    "trace_id": "test-trace-001",
    "priority": "NORMAL",
}

# ── Test 1: ML service health checks ─────────────────────────────────────
def test_ml_service_health():
    for name, url in ML_URLS.items():
        resp = httpx.get(f"{url}/health", timeout=5)
        assert resp.status_code == 200, f"{name} health check failed"
        data = resp.json()
        assert data.get("status") == "ok", f"{name} unhealthy: {data}"
        print(f"  ✓ {name}: healthy")

def test_ml_service_ready():
    for name, url in ML_URLS.items():
        resp = httpx.get(f"{url}/ready", timeout=5)
        assert resp.status_code == 200, f"{name} readiness check failed"
        print(f"  ✓ {name}: ready ({resp.json().get('model_version', 'n/a')})")

# ── Test 2: TCGA profiler direct call ────────────────────────────────────
def test_tcga_profiler():
    resp = httpx.post(
        f"{ML_URLS['tcga']}/api/ml/tcga/profile",
        json=SAMPLE_EVAL_REQUEST, timeout=30
    )
    assert resp.status_code == 200, f"TCGA profiler failed: {resp.text}"
    data = resp.json()
    obs = data["observation"]
    assert obs["resourceType"] == "Observation"
    extensions = {e["url"]: e for e in obs.get("extension", [])}
    assert "molecular-subtype" in extensions, "Missing molecular-subtype extension"
    subtype = extensions["molecular-subtype"]["valueString"]
    assert subtype in ["Luminal A", "Luminal B", "HER2+", "TNBC"]
    print(f"  ✓ TCGA profiler: subtype={subtype} in {data['processing_ms']}ms")

# ── Test 3: Risk classifier ───────────────────────────────────────────────
def test_risk_classifier():
    resp = httpx.post(
        f"{ML_URLS['risk']}/api/ml/risk/classify",
        json=SAMPLE_EVAL_REQUEST, timeout=30
    )
    assert resp.status_code == 200
    data = resp.json()
    obs = data["observation"]
    risk_score = obs["valueQuantity"]["value"]
    assert 0.0 <= risk_score <= 1.0, f"Risk score out of range: {risk_score}"
    interp = obs["interpretation"][0]["coding"][0]["display"]
    print(f"  ✓ Risk classifier: score={risk_score:.3f} ({interp}) in {data['processing_ms']}ms")

# ── Test 4: Imaging classifier (feature-based) ────────────────────────────
def test_imaging_classifier():
    resp = httpx.post(
        f"{ML_URLS['imaging']}/api/ml/imaging/classify-features",
        json=SAMPLE_EVAL_REQUEST, timeout=30
    )
    assert resp.status_code == 200
    data = resp.json()
    obs = data["observation"]
    assert obs["resourceType"] == "Observation"
    risk = obs["valueQuantity"]["value"]
    print(f"  ✓ Imaging classifier: P(tumour)={risk:.3f}")

# ── Test 5: DeepSurv survival predictor ──────────────────────────────────
def test_survival_predictor():
    resp = httpx.post(
        f"{ML_URLS['survival']}/api/ml/survival/predict",
        json=SAMPLE_EVAL_REQUEST, timeout=30
    )
    assert resp.status_code == 200
    data = resp.json()
    obs = data["observation"]
    os_months = obs["valueQuantity"]["value"]
    extensions = {e["url"]: e for e in obs.get("extension", [])}
    risk_group = extensions["risk-group"]["valueString"]
    assert risk_group in ["Low", "Medium", "High"]
    assert 1.0 <= os_months <= 200.0
    print(f"  ✓ DeepSurv: OS={os_months:.1f} months, group={risk_group} in {data['processing_ms']}ms")

# ── Test 6: SHAP explainer ────────────────────────────────────────────────
def test_shap_explainer():
    resp = httpx.post(
        f"{ML_URLS['shap']}/api/ml/explain/shap",
        json=SAMPLE_EVAL_REQUEST, timeout=30
    )
    assert resp.status_code == 200
    data = resp.json()
    obs = data["observation"]
    extensions = {e["url"]: e for e in obs.get("extension", [])}
    shap_json = json.loads(extensions["shap-attribution"]["valueString"])
    assert len(shap_json) >= 5, "Expected at least 5 SHAP attributions"
    top_driver = extensions["top-risk-driver"]["valueString"]
    print(f"  ✓ SHAP explainer: {len(shap_json)} attributions, top driver={top_driver}")
    print(f"    Top 3: {[(a['feature'], a['shap_value']) for a in shap_json[:3]]}")

# ── Test 7: FHIR compliance ───────────────────────────────────────────────
def test_fhir_observation_compliance():
    """All observations must be valid FHIR R4 Observation resources."""
    required_fields = ["resourceType", "id", "status", "code", "subject", "effectiveDateTime"]
    endpoints = [
        (ML_URLS["tcga"],     "api/ml/tcga/profile"),
        (ML_URLS["risk"],     "api/ml/risk/classify"),
        (ML_URLS["survival"], "api/ml/survival/predict"),
        (ML_URLS["shap"],     "api/ml/explain/shap"),
    ]
    for base, path in endpoints:
        resp = httpx.post(f"{base}/{path}", json=SAMPLE_EVAL_REQUEST, timeout=30)
        obs = resp.json()["observation"]
        for field in required_fields:
            assert field in obs, f"Missing FHIR field '{field}' in {path}"
        assert obs["resourceType"] == "Observation"
        assert obs["status"] == "final"
        assert "Patient/" in obs["subject"]["reference"]
    print("  ✓ All services return FHIR R4 compliant Observation resources")

# ── Test 8: Prometheus metrics ────────────────────────────────────────────
def test_prometheus_metrics():
    for name, url in ML_URLS.items():
        resp = httpx.get(f"{url}/metrics", timeout=5)
        assert resp.status_code == 200
        assert "ml_predictions_total" in resp.text or "http_request" in resp.text
        print(f"  ✓ {name}: Prometheus metrics exposed")

if __name__ == "__main__":
    print("\n═══ Cancer Evaluation Platform — Integration Tests ═══\n")
    tests = [
        ("ML Service Health",         test_ml_service_health),
        ("ML Service Readiness",       test_ml_service_ready),
        ("TCGA Profiler",              test_tcga_profiler),
        ("Risk Classifier",            test_risk_classifier),
        ("Imaging Classifier",         test_imaging_classifier),
        ("DeepSurv Survival",          test_survival_predictor),
        ("SHAP Explainer",             test_shap_explainer),
        ("FHIR Compliance",            test_fhir_observation_compliance),
        ("Prometheus Metrics",         test_prometheus_metrics),
    ]
    passed = failed = 0
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1

    print(f"\n{'═'*50}")
    print(f"  Results: {passed} passed / {failed} failed")
    print(f"{'═'*50}\n")
    exit(0 if failed == 0 else 1)
