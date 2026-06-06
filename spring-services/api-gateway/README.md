# API Gateway

![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![Port](https://img.shields.io/badge/port-8080-blue)

Single ingress point for all external traffic. Handles JWT validation, rate limiting, W3C trace injection, and route forwarding to downstream Spring Boot services and the WebSocket endpoint.

---

## Responsibilities

- **Routing** — forwards requests to `patient-service` and `evaluation-orchestrator` based on path predicates
- **Rate limiting** — Redis token-bucket limiter (100 req/s sustained, 200 burst) on all FHIR routes
- **Circuit breaker** — Resilience4j CB per downstream service; falls back to `/fallback` on open
- **Trace injection** — `TraceIdFilter` generates a W3C `traceparent` header on every inbound request that lacks one; propagates `X-Request-ID` downstream
- **WebSocket proxy** — forwards `/ws/**` to `notification-service` for STOMP connections

---

## Routes

| Path prefix | Upstream service | Notes |
|-------------|-----------------|-------|
| `/fhir/r4/Patient/**` | `patient-service:8080` | Rate-limited + circuit-broken |
| `/fhir/r4/Evaluation/**` | `evaluation-orchestrator:8080` | Pass-through |
| `/ws/**` | `notification-service:8080` (WebSocket) | STOMP / SockJS |

All routes append `X-Platform: cancer-eval-platform` to the response.

---

## Kafka

This service does **not** produce or consume Kafka messages directly. Trace IDs injected here are propagated through Kafka message payloads by downstream publishers.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PATIENT_SERVICE_URL` | `http://patient-service:8080` | Patient Service upstream |
| `EVALUATION_SERVICE_URL` | `http://evaluation-orchestrator:8080` | Orchestrator upstream |
| `REDIS_URL` | `redis://redis:6379` | Redis for rate-limiter token buckets |
| `SPRING_PROFILES_ACTIVE` | `docker` | Active Spring profile |

---

## Running Locally

Start infrastructure first, then:

```bash
cd spring-services
mvn clean package -DskipTests

cd api-gateway
PATIENT_SERVICE_URL=http://localhost:8081 \
EVALUATION_SERVICE_URL=http://localhost:8082 \
REDIS_URL=redis://localhost:6379 \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

Gateway listens on `http://localhost:8080`.

---

## Actuator Endpoints

| URL | What it shows |
|-----|---------------|
| `GET /actuator/health` | Liveness + downstream connectivity |
| `GET /actuator/gateway/routes` | Active route definitions |
| `GET /actuator/prometheus` | Prometheus metrics |

---

## Key Implementation Notes

**`TraceIdFilter`** (`filter/TraceIdFilter.java`) runs at order `-100` (before all other filters). It generates a W3C `traceparent` header in the format `00-<32-hex-trace-id>-<16-hex-span-id>-01` if one is not already present on the request.

Rate limiter uses a **Redis token bucket** — the bucket state is stored in Redis so it survives gateway restarts and works across multiple gateway replicas. Ensure Redis is healthy before the gateway starts or rate-limiting will fail open.
