# Evaluation Orchestrator

![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![Port](https://img.shields.io/badge/port-8082-blue)
![Resilience4j](https://img.shields.io/badge/Resilience4j-2.2-blueviolet)

Fan-out coordinator for the 5-model ML pipeline. Listens for `evaluation.requested` events, waits for results from all 5 ML services within a configurable timeout, aggregates them into a FHIR Bundle, persists to MongoDB, and publishes `ml.results.aggregated`.

---

## Responsibilities

- **Fan-out** — registers `CompletableFuture` slots for each of the 5 ML services when an evaluation starts
- **Result collection** — listens to all 5 `ml.result.*` topics and completes the corresponding futures as results arrive
- **Timeout handling** — after `ML_TIMEOUT_SECONDS` (default 15 s), any outstanding futures are marked `degraded`; the evaluation is persisted as `PARTIAL` rather than blocking forever
- **Aggregation** — assembles a FHIR R4 `Bundle` of all Observations, derives `maxRiskScore`, and saves the `EvaluationResult` to MongoDB
- **Circuit breaker** — Resilience4j instance `ml-service` (sliding window 10, failure threshold 50%, open wait 30 s)
- **Publishing** — emits `ml.results.aggregated` to trigger Notification and Audit services

---

## Kafka

| Topic | Direction | Notes |
|-------|-----------|-------|
| `evaluation.requested` | **Consumes** (`orchestrator-group`) | Registers pending futures |
| `ml.result.tcga` | **Consumes** (`orchestrator-results-group`) | TCGA profiler result |
| `ml.result.risk` | **Consumes** (`orchestrator-results-group`) | Risk classifier result |
| `ml.result.imaging` | **Consumes** (`orchestrator-results-group`) | Imaging classifier result |
| `ml.result.survival` | **Consumes** (`orchestrator-results-group`) | Survival predictor result |
| `ml.result.shap` | **Consumes** (`orchestrator-results-group`) | SHAP explainer result |
| `ml.results.aggregated` | **Publishes** | Aggregated bundle + max risk score |

The `ml.results.aggregated` payload:

```json
{
  "evaluationId": "...",
  "patientId": "patient-001",
  "maxRiskScore": 0.823,
  "status": "COMPLETED",
  "traceId": "00-abc...-01"
}
```

---

## Evaluation States

| Status | Meaning |
|--------|---------|
| `COMPLETED` | All 5 ML services responded within the timeout |
| `PARTIAL` | One or more services timed out; degraded Observations included with `dataAbsentReason: "Service timeout"` |
| `FAILED` | Unrecoverable error during aggregation |

---

## Data Store

**MongoDB** — collection `ml_results` in database `cancer_results`

Each `EvaluationResult` document contains:

| Field | Type | Description |
|-------|------|-------------|
| `evaluationId` | `String` | Links back to the `evaluations` table in PostgreSQL |
| `patientId` | `String` | FHIR Patient ID |
| `status` | `Enum` | `COMPLETED` / `PARTIAL` / `FAILED` |
| `serviceResults` | `List` | Per-service FHIR Observation + processing time + model version |
| `aggregatedBundle` | `Map` | FHIR R4 `Bundle` of all Observations |
| `maxRiskScore` | `double` | Highest risk score across all services |
| `createdAt` / `completedAt` | `OffsetDateTime` | Timing |

---

## Circuit Breaker Configuration

```yaml
resilience4j.circuitbreaker.instances.ml-service:
  sliding-window-size: 10
  failure-rate-threshold: 50      # open after 50% failures
  wait-duration-in-open-state: 30s
  permitted-number-of-calls-in-half-open-state: 3
```

Circuit breaker states are visible at `GET /actuator/circuitbreakers`.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://cancer_user:cancer_pass@localhost:27017/cancer_results?authSource=admin` | MongoDB connection |
| `KAFKA_BOOTSTRAP` | `localhost:9092` | Kafka broker |
| `REDIS_URL` | `redis://localhost:6379` | Redis (cache) |
| `ML_TIMEOUT_SECONDS` | `15` | Max wait for all 5 ML results before partial aggregation |
| `SPRING_PROFILES_ACTIVE` | `docker` | Active Spring profile |

---

## Running Locally

```bash
docker-compose up -d kafka mongodb redis

cd spring-services
mvn clean package -DskipTests

cd evaluation-orchestrator
MONGO_URI=mongodb://cancer_user:cancer_pass@localhost:27017/cancer_results?authSource=admin \
KAFKA_BOOTSTRAP=localhost:9092 \
ML_TIMEOUT_SECONDS=15 \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

Service available at `http://localhost:8082`.

---

## Actuator Endpoints

| URL | What it shows |
|-----|---------------|
| `GET /actuator/health` | Liveness + MongoDB and Kafka status |
| `GET /actuator/circuitbreakers` | Resilience4j CB state for `ml-service` |
| `GET /actuator/prometheus` | Prometheus metrics |
