# Cancer Patient Evaluation Platform

![Java](https://img.shields.io/badge/Java-21-blue)
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-brightgreen)
![Kafka](https://img.shields.io/badge/Kafka-7.6-black)
![FHIR R4](https://img.shields.io/badge/FHIR-R4-orange)
![HIPAA](https://img.shields.io/badge/HIPAA-Audit%20Trail-red)

Distributed microservice platform for AI-powered cancer patient assessment. Clinicians submit a FHIR R4 patient record; five ML models run in parallel and return structured FHIR Observations covering molecular subtype, recurrence risk, histopathology grade, survival prognosis, and SHAP-attributed feature explanations — all within a configurable SLA window.

Productionises the 5-model ML roadmap (Phases 1–5) into independently deployable, horizontally scalable services.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [ML Services](#ml-services--roadmap-mapping)
- [Running Locally](#running-locally)
  - [Option 1 — Docker Compose](#option-1--docker-compose)
  - [Option 2 — Individual services](#option-2--individual-services)
  - [Option 3 — Kubernetes (local)](#option-3--kubernetes-local)
- [Monitoring](#monitoring)
- [Kafka Topics](#kafka-topics)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

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

**Component responsibilities**

| Component | Role |
|-----------|------|
| **API Gateway** | Single ingress — JWT auth, rate limiting, distributed tracing headers |
| **Patient Service** | FHIR R4 CRUD, persists to PostgreSQL, publishes `evaluation.requested` events |
| **Evaluation Orchestrator** | Fan-out coordinator — waits for all 5 ML results with Resilience4j circuit breakers, aggregates into MongoDB |
| **Notification Service** | Watches `ml.results.aggregated`; fires WebSocket push, email, or SMS when risk exceeds thresholds |
| **Audit Service** | HIPAA-compliant append-only audit log; patient IDs are HMAC-hashed before storage |
| **ML Services (×5)** | FastAPI workers; each consumes `evaluation.requested`, runs its model, publishes a FHIR Observation back to Kafka |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API / Orchestration | Spring Boot 3.3, Spring Cloud Gateway, Resilience4j |
| ML Services | FastAPI, scikit-learn, PyTorch, SHAP |
| Messaging | Apache Kafka 7.6 (Confluent), Zookeeper |
| Databases | PostgreSQL 16 (patient records), MongoDB 7 (ML results + audit) |
| Cache | Redis 7.2 |
| Data standard | FHIR R4 — HAPI FHIR 7.2 (Java), Pydantic models (Python) |
| Observability | Prometheus metrics, Spring Actuator, Kafka UI |
| Runtime | Docker Compose (local), Kubernetes / EKS (production) |
| Java version | 21 (virtual threads enabled) |
| Python version | 3.11+ |

---

## ML Services → Roadmap Mapping

| Service | Port | Phase | Model | FHIR output |
|---------|------|-------|-------|-------------|
| TCGA Profiler | 8101 | 1 | Multi-omics subtype classifier (`tcga_cancer_analysis.py`) | DiagnosticReport — molecular subtype (Luminal A/B, HER2+, TNBC) |
| Risk Classifier | 8102 | 2 | 5-model ensemble (`breast_cancer_classifier.py`) | Observation LOINC 72133-2 — recurrence risk probability |
| Imaging Classifier | 8103 | 3 | ResNet-50 histopathology (`resnet_histopathology.py`) | Observation LOINC 85319-2 — tumour probability from image features |
| Survival Predictor | 8104 | 4 | DeepSurv neural Cox PH (`deepsurv_cancer.py`) | Observation LOINC 75859-9 — predicted OS in months + risk group |
| SHAP Explainer | 8105 | 5 | SHAP feature attribution | Observation LOINC 73727-0 — per-feature contribution scores |

---

## Running Locally

Three options depending on your goal:

| Option | Best for |
|--------|----------|
| [Docker Compose](#option-1--docker-compose) | Full stack in one command — no Java or Python install needed |
| [Individual services](#option-2--individual-services) | Fast iteration while developing a single service |
| [Kubernetes (local)](#option-3--kubernetes-local) | Validating k8s manifests before pushing to EKS |

---

### Option 1 — Docker Compose

**Prerequisites**

- Docker Desktop ≥ v24 (or Docker Engine + Compose plugin)
- 8 GB RAM minimum allocated to Docker (16 GB recommended — ML models are loaded in-process)

**1. Create your environment file**

```bash
cp .env.example .env
```

For local development the defaults in `docker-compose.yml` are sufficient. For anything shared, set real values for `POSTGRES_PASSWORD`, `MONGO_INITDB_ROOT_PASSWORD`, `DB_PASS`, and `AUDIT_HMAC_KEY` in `.env` before continuing.

**2. Start the full stack**

```bash
docker-compose up -d
```

Startup order: Zookeeper → Kafka → PostgreSQL → MongoDB → Redis → 5 ML services → 5 Spring Boot services → Kafka UI.

**3. Wait for everything to be healthy (~90 s)**

```bash
docker-compose ps
# Every service should show "healthy" or "running"
```

If a service stays in `starting`, tail its logs:

```bash
docker-compose logs -f <service-name>
# e.g. docker-compose logs -f risk-classifier
```

**4. Run integration tests**

```bash
pip install httpx pytest
python tests/integration_test.py
```

The suite covers health checks, readiness, direct ML endpoint calls, FHIR R4 compliance, and Prometheus metrics exposure.

**5. Smoke-test a single ML endpoint**

```bash
curl -X POST http://localhost:8102/api/ml/risk/classify \
  -H "Content-Type: application/json" \
  -d '{
    "evaluation_id": "eval-001",
    "patient_id":    "patient-001",
    "patient_features": {
      "ESR1": 4.2, "ERBB2": -0.8, "MKI67": -1.5,
      "Age": 58.0, "Stage_num": 2.0, "ER_status": 1.0
    },
    "model_types": ["all"],
    "trace_id": "trace-001"
  }'
```

Expected response:

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
      {"url": "ensemble-size",            "valueString":  "5"}
    ]
  },
  "processing_ms": 124
}
```

**Teardown**

```bash
docker-compose down      # stop containers, keep data volumes
docker-compose down -v   # stop containers and delete all data volumes
```

---

### Option 2 — Individual services

Use this when you're actively developing one service and want fast iteration without rebuilding every image.

**Prerequisites**

- Java 21 + Maven 3.9+ (Spring Boot services)
- Python 3.11+ (ML FastAPI services)
- Docker Compose running the infrastructure tier

**1. Start infrastructure only**

```bash
docker-compose up -d zookeeper kafka postgres mongodb redis
# Wait ~30 s, then confirm all are healthy:
docker-compose ps
```

The Compose file exposes Postgres on `localhost:5432`, Kafka on `localhost:9092`, Redis on `localhost:6379` — no host changes needed.

**2. Run a Spring Boot service**

```bash
# Build all modules once from the parent POM
cd spring-services
mvn clean package -DskipTests

# Then run the service you're working on
cd patient-service
DB_URL=jdbc:postgresql://localhost:5432/cancer_platform \
DB_USER=cancer_user \
DB_PASS=cancer_pass \
KAFKA_BOOTSTRAP=localhost:9092 \
REDIS_URL=redis://localhost:6379 \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

**3. Run a Python ML service**

```bash
cd ml-services/risk-classifier
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

KAFKA_BOOTSTRAP=localhost:9092 \
REDIS_URL=redis://localhost:6379 \
SERVICE_NAME=risk-classifier \
uvicorn main:app --reload --port 8102
```

Repeat for any other ML service, substituting the directory and port from the [ML Services table](#ml-services--roadmap-mapping).

**4. Build a Docker image for a single service**

```bash
# Spring Boot
cd spring-services/patient-service
mvn clean package -DskipTests
docker build -t cancer-platform/patient-service:latest .

# Python
cd ml-services/risk-classifier
docker build -t cancer-platform/risk-classifier:latest .
```

---

### Option 3 — Kubernetes (local)

Use this to validate the manifests in `k8s/` against a real cluster before pushing to EKS.

**Prerequisites**

- `kubectl` v1.29+
- `minikube` v1.32+ **or** `kind` v0.22+ (pick one)
- Docker (used as the cluster driver)

#### 3a. Start a local cluster

**minikube**

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
eval $(minikube docker-env)   # point your shell's Docker daemon at minikube's
```

**kind**

```bash
kind create cluster --name cancer-platform
kubectl cluster-info --context kind-cancer-platform
```

#### 3b. Build and load images

```bash
# Build Spring Boot JARs
cd spring-services && mvn clean package -DskipTests && cd ..

# Build images
docker build -t cancer-platform/patient-service:latest  ./spring-services/patient-service
docker build -t cancer-platform/risk-classifier:latest  ./ml-services/risk-classifier
# Repeat for each service you want to deploy

# Load into minikube (skip for kind)
minikube image load cancer-platform/patient-service:latest
minikube image load cancer-platform/risk-classifier:latest

# Load into kind (skip for minikube)
kind load docker-image cancer-platform/patient-service:latest --name cancer-platform
kind load docker-image cancer-platform/risk-classifier:latest --name cancer-platform
```

#### 3c. Create namespaces

```bash
kubectl apply -f k8s/namespace.yaml
# Creates: cancer-core (Spring services), cancer-ml (ML services), cancer-infra (Kafka/DBs)
```

#### 3d. Create required Secrets

`patient-service` reads DB credentials from a Secret named `postgres-secret` in `cancer-core`:

```bash
kubectl create secret generic postgres-secret \
  --namespace cancer-core \
  --from-literal=url=jdbc:postgresql://<postgres-host>:5432/cancer_platform \
  --from-literal=username=cancer_user \
  --from-literal=password=cancer_pass
```

> For a fully self-contained local cluster, deploy Kafka, PostgreSQL, MongoDB, and Redis inside the cluster (Helm charts recommended), or point the manifests at the Docker Compose infra running on your host IP.

#### 3e. Apply manifests

```bash
kubectl apply -f k8s/patient-service-deployment.yaml
kubectl apply -f k8s/risk-classifier-deployment.yaml
```

#### 3f. Verify

```bash
kubectl get pods -n cancer-core
kubectl get pods -n cancer-ml

# Stream logs
kubectl logs -n cancer-ml deployment/risk-classifier -f

# Check HPA for risk-classifier (minReplicas=2, maxReplicas=8, CPU target=70%)
kubectl get hpa -n cancer-ml
```

#### 3g. Access services locally

```bash
# Port-forward individual services
kubectl port-forward -n cancer-core svc/patient-service 8081:8080 &
kubectl port-forward -n cancer-ml   svc/risk-classifier 8102:8000 &

# minikube: tunnel LoadBalancer/NodePort services to localhost
minikube tunnel
```

#### 3h. Teardown

```bash
# minikube
minikube delete

# kind
kind delete cluster --name cancer-platform
```

---

## Monitoring

| URL | What it shows |
|-----|---------------|
| `http://localhost:8090` | Kafka UI — topics, consumer lag, message browser |
| `http://localhost:8081/actuator/health` | Patient Service — liveness + datasource status |
| `http://localhost:8082/actuator/circuitbreakers` | Evaluation Orchestrator — Resilience4j CB states per ML service |
| `http://localhost:810x/metrics` | Any ML service — Prometheus counters and latency histograms |
| `http://localhost:810x/health` | Any ML service — `{"status": "ok"}` liveness probe |
| `http://localhost:810x/ready` | Any ML service — readiness probe, includes `model_version` |

## API Documentation (Swagger UI)

Every FastAPI ML service auto-generates interactive OpenAPI docs. Accessible while the stack is running:

| Service | Swagger UI | ReDoc |
|---------|------------|-------|
| TCGA Profiler | `http://localhost:8101/docs` | `http://localhost:8101/redoc` |
| Risk Classifier | `http://localhost:8102/docs` | `http://localhost:8102/redoc` |
| Imaging Classifier | `http://localhost:8103/docs` | `http://localhost:8103/redoc` |
| Survival Predictor | `http://localhost:8104/docs` | `http://localhost:8104/redoc` |
| SHAP Explainer | `http://localhost:8105/docs` | `http://localhost:8105/redoc` |

The raw OpenAPI JSON schema for each service is available at `/openapi.json`.

---

## Kafka Topics

| Topic | Publisher | Consumers | Notes |
|-------|-----------|-----------|-------|
| `evaluation.requested` | Patient Service | All 5 ML services | Triggered on FHIR patient create/update |
| `ml.result.tcga` | TCGA Profiler | Evaluation Orchestrator | Molecular subtype result |
| `ml.result.risk` | Risk Classifier | Evaluation Orchestrator | Ensemble risk score |
| `ml.result.imaging` | Imaging Classifier | Evaluation Orchestrator | Histopathology probability |
| `ml.result.survival` | Survival Predictor | Evaluation Orchestrator | OS months + risk group |
| `ml.result.shap` | SHAP Explainer | Evaluation Orchestrator | Feature attribution JSON |
| `ml.results.aggregated` | Evaluation Orchestrator | Notification Service, Audit Service | All 5 results merged |

---

## Environment Variables

### Infrastructure

| Variable | Default | Used by |
|----------|---------|---------|
| `POSTGRES_DB` | `cancer_platform` | PostgreSQL init |
| `POSTGRES_USER` | `cancer_user` | PostgreSQL init |
| `POSTGRES_PASSWORD` | *(set in .env)* | PostgreSQL init |
| `MONGO_INITDB_ROOT_USERNAME` | `cancer_user` | MongoDB init |
| `MONGO_INITDB_ROOT_PASSWORD` | *(set in .env)* | MongoDB init |
| `REDIS_URL` | `redis://redis:6379` | All services |
| `KAFKA_BOOTSTRAP` | `kafka:9092` | All services |

### Spring Boot services

| Variable | Default | Used by |
|----------|---------|---------|
| `DB_URL` | `jdbc:postgresql://postgres:5432/cancer_platform` | Patient Service |
| `DB_USER` | `cancer_user` | Patient Service |
| `DB_PASS` | *(set in .env)* | Patient Service |
| `MONGO_URI` | `mongodb://...@mongodb:27017/cancer_results` | Orchestrator, Audit Service |
| `ML_TIMEOUT_SECONDS` | `15` | Evaluation Orchestrator |
| `RISK_THRESHOLD_HIGH` | `0.75` | Notification Service |
| `RISK_THRESHOLD_CRITICAL` | `0.90` | Notification Service |
| `AUDIT_HMAC_KEY` | *(generate with `openssl rand -hex 32`)* | Audit Service |
| `SPRING_PROFILES_ACTIVE` | `docker` | All Spring services |

### ML FastAPI services

| Variable | Default | Used by |
|----------|---------|---------|
| `SERVICE_NAME` | *(service name)* | All ML services |
| `MODEL_VERSION` | `v1.0.0` | All ML services |

---

## Project Structure

```
cancer-eval-platform/
├── docker-compose.yml               # Full local stack
├── .env.example                     # Copy to .env before starting
├── infrastructure/
│   ├── postgres/init.sql            # Patient records schema
│   └── mongo/init.js                # ML results + audit collections
├── ml-services/
│   ├── shared/                      # Pydantic FHIR models, Kafka base, Prometheus metrics
│   ├── tcga-profiler/               # Phase 1 — TCGA multi-omics subtype
│   ├── risk-classifier/             # Phase 2 — 5-model ensemble
│   ├── imaging-classifier/          # Phase 3 — ResNet-50 histopathology
│   ├── survival-predictor/          # Phase 4 — DeepSurv neural Cox PH
│   └── shap-explainer/              # Phase 5 — SHAP feature attribution
├── spring-services/
│   ├── pom.xml                      # Parent POM (Java 21, Spring Boot 3.3)
│   ├── api-gateway/                 # Spring Cloud Gateway — port 8080
│   ├── patient-service/             # FHIR CRUD + Kafka publisher — port 8081
│   ├── evaluation-orchestrator/     # Fan-out + aggregation — port 8082
│   ├── notification-service/        # WebSocket + alerts — port 8083
│   └── audit-service/               # HIPAA audit trail — port 8084
├── k8s/
│   ├── namespace.yaml               # cancer-core, cancer-ml, cancer-infra
│   ├── patient-service-deployment.yaml
│   └── risk-classifier-deployment.yaml  # Includes HPA (2–8 replicas)
└── tests/
    └── integration_test.py          # End-to-end pytest suite (9 tests)
```

---

## Troubleshooting

**A service is stuck in `starting` and never becomes `healthy`**

Kafka and Zookeeper take ~20 s to elect a leader. Services that depend on Kafka (`patient-service`, `evaluation-orchestrator`, all ML services) will retry on startup. Give the stack 90 s before investigating.

```bash
docker-compose logs -f kafka          # watch Kafka boot
docker-compose logs -f risk-classifier
```

**ML service starts but predictions fail with a Kafka timeout**

Check that `KAFKA_BOOTSTRAP` inside the container resolves to the Kafka broker. Inside Docker Compose the hostname is `kafka`; from your host it is `localhost:9092`.

**`mvn spring-boot:run` fails with `Connection refused` to PostgreSQL**

The Compose infra services expose ports only after their healthchecks pass. Run `docker-compose ps` and confirm `postgres` shows `healthy` before starting Spring Boot manually.

**`minikube image load` is slow**

Use `--overwrite=false` to skip images already loaded, or switch to `kind` which uses `containerd` and loads images faster for repeated builds.

**`kubectl get pods` shows `ImagePullBackOff`**

This means the cluster cannot pull the image. For local clusters you must load images manually (step 3b) and ensure the deployment manifest has `imagePullPolicy: Never` (or `IfNotPresent`).

**FHIR validation errors in the audit log**

All ML services return FHIR R4 `Observation` resources. Required fields: `resourceType`, `id`, `status`, `code`, `subject`, `effectiveDateTime`. Run `python tests/integration_test.py` — the `test_fhir_observation_compliance` test will identify which service is missing fields.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch conventions, commit message format, and the pre-commit hook setup (`pre-commit install`).

Security issues — see [SECURITY.md](SECURITY.md).