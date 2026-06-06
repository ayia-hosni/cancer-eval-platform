# Audit Service

![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![Port](https://img.shields.io/badge/port-8084-blue)
![HIPAA](https://img.shields.io/badge/HIPAA-Audit%20Trail-red)

HIPAA-compliant append-only audit log. Listens to every significant Kafka topic across the platform, writes an immutable audit entry to MongoDB for each event, and hashes all patient identifiers with HMAC-SHA256 before storage.

---

## Responsibilities

- **Audit all events** — subscribes to 10 Kafka topics spanning the full evaluation lifecycle
- **PHI protection** — patient IDs are **never stored in plaintext**; they are replaced with an HMAC-SHA256 hash before writing. The raw ID never touches the audit log
- **Payload integrity** — each audit entry stores a SHA-256 hash of the event payload; the raw payload is not persisted
- **Append-only** — the service has no update or delete paths; every correction must be a new entry

---

## Audited Events

| Kafka Topic | Event type |
|-------------|-----------|
| `patient.created` | New patient registered |
| `patient.updated` | Patient record updated |
| `evaluation.requested` | ML evaluation triggered |
| `ml.result.tcga` | TCGA profiler result received |
| `ml.result.risk` | Risk classifier result received |
| `ml.result.imaging` | Imaging classifier result received |
| `ml.result.survival` | Survival predictor result received |
| `ml.result.shap` | SHAP explainer result received |
| `ml.results.aggregated` | Evaluation results aggregated |
| `alert.triggered` | High/critical risk alert dispatched |

---

## Audit Log Entry Schema

Each entry in the `audit_log` MongoDB collection:

| Field | Type | Description |
|-------|------|-------------|
| `patientIdHash` | `String` | HMAC-SHA256(patientId) — indexed |
| `eventType` | `String` | Kafka topic name |
| `actor` | `String` | JWT `sub` claim or service name for ML events |
| `evaluationId` | `String` | Links to the evaluation, if applicable |
| `traceId` | `String` | W3C trace ID from the originating request |
| `timestamp` | `OffsetDateTime` | Event wall-clock time — indexed |
| `payloadHash` | `String` | SHA-256 of the full event payload |
| `topic` | `String` | Source Kafka topic |
| `metadata` | `Map` | Supplemental data (e.g., `payloadSize`) |

---

## Hashing Scheme

**Patient ID** → `HMAC-SHA256(patientId, AUDIT_HMAC_KEY)` stored as hex string.

**Event payload** → `SHA-256(serialisedJson)` stored as hex string. The raw payload is **not** persisted.

The HMAC key is read from the `AUDIT_HMAC_KEY` environment variable at startup. In production this is injected from HashiCorp Vault. Rotate the key only during a scheduled maintenance window — mid-operation rotation causes hash divergence between audit entries for the same patient.

Generate a key:
```bash
openssl rand -hex 32
```

---

## Data Store

**MongoDB** — collection `audit_log` in database `cancer_results`

Indexes:
- `patientIdHash` — for querying all events for a given patient (by their hash)
- `timestamp` — for time-range queries and TTL retention policy

A TTL index should be applied to enforce your data retention policy (e.g., 7 years for HIPAA). Add it in `infrastructure/mongo/init.js`:

```javascript
db.audit_log.createIndex({ timestamp: 1 }, { expireAfterSeconds: 220752000 }); // 7 years
```

---

## Kafka

| Topic | Direction | Consumer group |
|-------|-----------|---------------|
| All 10 topics listed above | **Consumes** | `audit-service-group` |

The service never produces to Kafka.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://cancer_user:cancer_pass@localhost:27017/cancer_results?authSource=admin` | MongoDB connection |
| `KAFKA_BOOTSTRAP` | `localhost:9092` | Kafka broker |
| `AUDIT_HMAC_KEY` | *(required in production)* | HMAC-SHA256 key for patient ID hashing. Generate with `openssl rand -hex 32` |
| `SPRING_PROFILES_ACTIVE` | `docker` | Active Spring profile |

---

## Running Locally

```bash
docker-compose up -d kafka mongodb

cd spring-services
mvn clean package -DskipTests

cd audit-service
MONGO_URI=mongodb://cancer_user:cancer_pass@localhost:27017/cancer_results?authSource=admin \
KAFKA_BOOTSTRAP=localhost:9092 \
AUDIT_HMAC_KEY=$(openssl rand -hex 32) \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

Service available at `http://localhost:8084`.

---

## Actuator Endpoints

| URL | What it shows |
|-----|---------------|
| `GET /actuator/health` | Liveness + MongoDB and Kafka status |
| `GET /actuator/prometheus` | Prometheus metrics |

---

## Security Notes

- Do **not** add query or export endpoints to this service without a documented access-control policy — the audit log contains sensitive event metadata
- Do **not** add update or delete endpoints — append-only is a HIPAA requirement
- If `AUDIT_HMAC_KEY` is missing or set to the default value at startup, the service should log a `WARN` and refuse to start in a non-`local` profile
