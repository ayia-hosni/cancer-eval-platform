# Cancer Patient Evaluation Platform

Distributed microservice system for AI-powered cancer patient assessment.
Productionises the 5-model ML roadmap (Phases 1–5) into deployable services.

## Architecture

```
Clinician / EHR
      │  FHIR R4 JSON
      ▼
API Gateway (Spring Cloud Gateway :8080)
      │  JWT validation · Rate limiting · Trace injection
      ▼
Patient Service (Spring Boot :8081)
      │  FHIR CRUD · PostgreSQL · Kafka publisher
      ▼  evaluation.requested
Kafka ──────────────────────────────────────────┐
      │                                         │
      ▼  (consumed by all 5 FastAPI services)   │
┌─────────────────────────────────┐             │
│ TCGA Profiler       :8101       │             │
│ Risk Classifier     :8102       │             │  ml.result.*
│ Imaging Classifier  :8103       │─────────────▶
│ Survival Predictor  :8104       │             │
│ SHAP Explainer      :8105       │             │
└─────────────────────────────────┘             │
                                                ▼
Evaluation Orchestrator (Spring Boot :8082) ◀──┘
      │  Aggregates 5 results · MongoDB · Resilience4j CB
      ▼  ml.results.aggregated
Notification Service (Spring Boot :8083)
      │  WebSocket · Email · SMS alerts
      ▼
Audit Service (Spring Boot :8084)
      │  HIPAA append-only log · MongoDB · HMAC patient IDs
```

## ML Services → Roadmap Mapping

| Service | Port | Source script | FHIR output |
|---------|------|---------------|-------------|
| TCGA Profiler | 8101 | `tcga_cancer_analysis.py` | DiagnosticReport (molecular subtype) |
| Risk Classifier | 8102 | `breast_cancer_classifier.py` | Observation (LOINC 72133-2) |
| Imaging Classifier | 8103 | `resnet_histopathology.py` | Observation (LOINC 85319-2) |
| Survival Predictor | 8104 | `deepsurv_cancer.py` | Observation (LOINC 75859-9) |
| SHAP Explainer | 8105 | SHAP section | Observation (LOINC 73727-0) |

## Quick Start

### Prerequisites
- Docker + Docker Compose
- 8 GB RAM minimum (16 GB recommended)

### Start the full stack
```bash
docker-compose up -d
```

### Wait for services to be ready (~90 seconds)
```bash
docker-compose ps
# All services should show "healthy"
```

### Run integration tests (ML services only — no Java compile needed)
```bash
pip install httpx pytest
python tests/integration_test.py
```

### Test a FastAPI ML service directly
```bash
curl -X POST http://localhost:8102/api/ml/risk/classify \
  -H "Content-Type: application/json" \
  -d '{
    "evaluation_id": "eval-001",
    "patient_id": "patient-001",
    "patient_features": {
      "ESR1": 4.2, "ERBB2": -0.8, "MKI67": -1.5,
      "Age": 58.0, "Stage_num": 2.0, "ER_status": 1.0
    },
    "model_types": ["all"],
    "trace_id": "trace-001"
  }'
```

### Expected response
```json
{
  "observation": {
    "resourceType": "Observation",
    "id": "...",
    "status": "final",
    "code": {"coding": [{"system": "http://loinc.org", "code": "72133-2"}]},
    "subject": {"reference": "Patient/patient-001"},
    "valueQuantity": {"value": 0.2341, "unit": "probability"},
    "interpretation": [{"coding": [{"code": "L", "display": "Low"}]}],
    "extension": [
      {"url": "confidence-interval-low",  "valueDecimal": 0.189},
      {"url": "confidence-interval-high", "valueDecimal": 0.284},
      {"url": "ensemble-size", "valueString": "5"}
    ]
  },
  "processing_ms": 124
}
```

## Monitoring

| URL | Service |
|-----|---------|
| http://localhost:8090 | Kafka UI |
| http://localhost:8101/metrics | TCGA Profiler metrics (Prometheus) |
| http://localhost:8102/metrics | Risk Classifier metrics |
| http://localhost:8081/actuator/health | Patient Service health |
| http://localhost:8082/actuator/circuitbreakers | Circuit breaker states |

## Kafka Topics

| Topic | Publisher | Consumers |
|-------|-----------|-----------|
| `evaluation.requested` | Patient Service | All 5 FastAPI services |
| `ml.result.tcga` | TCGA Profiler | Evaluation Orchestrator |
| `ml.result.risk` | Risk Classifier | Evaluation Orchestrator |
| `ml.result.imaging` | Imaging Classifier | Evaluation Orchestrator |
| `ml.result.survival` | Survival Predictor | Evaluation Orchestrator |
| `ml.result.shap` | SHAP Explainer | Evaluation Orchestrator |
| `ml.results.aggregated` | Evaluation Orchestrator | Notification + Audit |

## Project Structure

```
cancer-eval-platform/
├── docker-compose.yml
├── README.md
├── infrastructure/
│   ├── postgres/init.sql        # Schema for patient records
│   └── mongo/init.js            # Collections for ML results + audit
├── ml-services/
│   ├── shared/                  # Pydantic FHIR models, Kafka base, metrics
│   ├── tcga-profiler/           # Phase 1: TCGA multi-omics profiling
│   ├── risk-classifier/         # Phase 2: 5-model ensemble
│   ├── imaging-classifier/      # Phase 3: ResNet-50 histopathology
│   ├── survival-predictor/      # Phase 4: DeepSurv neural Cox PH
│   └── shap-explainer/          # Phase 5: SHAP feature attribution
├── spring-services/
│   ├── api-gateway/             # Spring Cloud Gateway
│   ├── patient-service/         # FHIR CRUD + Kafka publisher
│   ├── evaluation-orchestrator/ # Fan-out + aggregation
│   ├── notification-service/    # WebSocket + alerts
│   └── audit-service/           # HIPAA audit trail
├── k8s/                         # Kubernetes manifests (EKS production)
└── tests/
    └── integration_test.py      # End-to-end test suite
```

## Building Spring Boot Services

```bash
cd spring-services
mvn clean package -DskipTests

# Or build individual service:
cd spring-services/patient-service
mvn clean package -DskipTests
docker build -t cancer-platform/patient-service:latest .
```

## Environment Variables

Each service reads from environment. See `docker-compose.yml` for the full list.
Key variables:
- `KAFKA_BOOTSTRAP` — Kafka broker address
- `DB_URL` — PostgreSQL JDBC URL (patient-service)
- `MONGO_URI` — MongoDB connection string (orchestrator, audit)
- `REDIS_URL` — Redis URL
- `MODEL_VERSION` — Active ML model version (FastAPI services)
- `ML_TIMEOUT_SECONDS` — Evaluation fan-out timeout (orchestrator)
- `RISK_THRESHOLD_HIGH` — Risk score threshold for HIGH alerts (0.75)
- `RISK_THRESHOLD_CRITICAL` — Risk score threshold for CRITICAL alerts (0.90)
