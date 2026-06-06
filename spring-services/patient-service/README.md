# Patient Service

![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![Port](https://img.shields.io/badge/port-8081-blue)
![FHIR R4](https://img.shields.io/badge/FHIR-R4-orange)

FHIR R4 patient registry and evaluation trigger. Persists patient records to PostgreSQL, validates incoming FHIR JSON, and publishes `evaluation.requested` events to Kafka to kick off the 5-model ML pipeline.

---

## Responsibilities

- **FHIR CRUD** — create and retrieve `Patient` resources; stores raw FHIR JSON as PostgreSQL `jsonb`
- **FHIR validation** — parses and validates incoming payloads with HAPI FHIR R4
- **Feature extraction** — extracts clinical and genomic features from FHIR extensions for inclusion in the Kafka event
- **Evaluation trigger** — persists an `Evaluation` record (status `PENDING`) and publishes an `EvaluationEvent` to `evaluation.requested`
- **Redis caching** — patient lookups are cached for 15 minutes (`patients` cache, TTL 900 s)

---

## API Endpoints

All routes are prefixed `/fhir/r4` and require `Content-Type: application/fhir+json` on write operations.

### `POST /fhir/r4/Patient`

Create a patient from a FHIR R4 Patient resource.

**Request body** — FHIR R4 `Patient` JSON with gene-expression extensions:

```json
{
  "resourceType": "Patient",
  "id": "patient-001",
  "name": [{"family": "Smith", "given": ["Jane"]}],
  "birthDate": "1965-03-15",
  "gender": "female",
  "extension": [
    {"url": "http://cancer.platform/gene-expression/ESR1",    "valueDecimal": 4.2},
    {"url": "http://cancer.platform/gene-expression/ERBB2",   "valueDecimal": -0.8},
    {"url": "http://cancer.platform/gene-expression/Stage_num","valueDecimal": 2.0}
  ]
}
```

**Response** — `201 Created` with `Location: /fhir/r4/Patient/{fhirId}`

```json
{"id": "patient-001", "status": "created"}
```

---

### `GET /fhir/r4/Patient/{id}`

Retrieve a patient record. Returns the stored FHIR JSON with `Content-Type: application/fhir+json`.

| Status | Meaning |
|--------|---------|
| `200` | Patient found |
| `404` | No patient with that FHIR ID |

---

### `POST /fhir/r4/Patient/{id}/$evaluate`

Trigger ML evaluation for an existing patient. The operation is **asynchronous** — it returns `202 Accepted` immediately with a polling URL.

**Query parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `models` | No | Comma-separated list of models to run. Omit for all. Values: `tcga`, `risk`, `imaging`, `survival`, `shap` |

**Response** — `202 Accepted` with `Location: /fhir/r4/Evaluation/{evaluationId}`

```json
{
  "evaluationId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "message": "Evaluation queued. Poll /fhir/r4/Evaluation/550e8400-..."
}
```

---

### `GET /fhir/r4/Patient/{id}/evaluations`

List all past evaluations for a patient, ordered by `requestedAt` descending.

---

## Kafka

| Topic | Direction | Trigger |
|-------|-----------|---------|
| `patient.created` | **Publishes** | On every successful patient create |
| `evaluation.requested` | **Publishes** | On every `$evaluate` call |

The `EvaluationEvent` payload published to `evaluation.requested`:

```json
{
  "evaluationId": "...",
  "patientId": "patient-001",
  "patientFeatures": {"ESR1": 4.2, "Age": 58.0, "Stage_num": 2.0, "...": "..."},
  "modelTypes": ["all"],
  "traceId": "00-abc...-01",
  "priority": "NORMAL"
}
```

Producer is configured with `acks=all` and `retries=3` for durability.

---

## Data Store

**PostgreSQL** — schema `patient_svc`

| Table | Purpose |
|-------|---------|
| `patients` | Patient demographics + raw FHIR JSON (`jsonb`) |
| `evaluations` | Evaluation records with status tracking |

Schema is managed by **Flyway** migrations in `src/main/resources/db/migration/`. Never alter the schema with raw DDL.

**Redis** — patient cache (`patients` key space, TTL 15 min)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_URL` | `jdbc:postgresql://localhost:5432/cancer_platform` | PostgreSQL JDBC URL |
| `DB_USER` | `cancer_user` | PostgreSQL username |
| `DB_PASS` | *(required)* | PostgreSQL password |
| `KAFKA_BOOTSTRAP` | `localhost:9092` | Kafka broker |
| `REDIS_URL` | `redis://localhost:6379` | Redis for patient cache |
| `SPRING_PROFILES_ACTIVE` | `docker` | Active Spring profile |

---

## Running Locally

```bash
# Start infra
docker-compose up -d postgres kafka redis

# Build and run
cd spring-services
mvn clean package -DskipTests

cd patient-service
DB_URL=jdbc:postgresql://localhost:5432/cancer_platform \
DB_USER=cancer_user \
DB_PASS=cancer_pass \
KAFKA_BOOTSTRAP=localhost:9092 \
REDIS_URL=redis://localhost:6379 \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

Service available at `http://localhost:8081`.

---

## Actuator Endpoints

| URL | What it shows |
|-----|---------------|
| `GET /actuator/health` | Liveness, datasource, Redis, and Kafka status |
| `GET /actuator/health/liveness` | Kubernetes liveness probe |
| `GET /actuator/health/readiness` | Kubernetes readiness probe |
| `GET /actuator/prometheus` | Prometheus metrics |
