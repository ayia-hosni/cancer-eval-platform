# Notification Service

![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3-brightgreen)
![Port](https://img.shields.io/badge/port-8083-blue)
![WebSocket](https://img.shields.io/badge/WebSocket-STOMP-informational)

Real-time alert and dashboard update service. Listens to `ml.results.aggregated`, classifies the risk level, pushes WebSocket updates to connected clinician dashboards, and dispatches email/SMS alerts when the risk score exceeds configurable thresholds.

---

## Responsibilities

- **Risk classification** — maps `maxRiskScore` to a level: `LOW` / `MODERATE` / `HIGH` / `CRITICAL`
- **WebSocket push** — broadcasts every evaluation result to `/topic/evaluations/{patientId}` for real-time dashboard updates
- **Alert dispatch** — sends an alert to `/topic/alerts` when risk ≥ `RISK_THRESHOLD_HIGH` (default 0.75)
- **Email / SMS** — stub integration points for SendGrid (email) and Twilio (SMS); activate by setting the relevant API keys

---

## Risk Thresholds

| Level | Score range | Action |
|-------|-------------|--------|
| `LOW` | < 0.50 | WebSocket update only |
| `MODERATE` | 0.50 – 0.74 | WebSocket update only |
| `HIGH` | 0.75 – 0.89 | WebSocket update + alert dispatch |
| `CRITICAL` | ≥ 0.90 | WebSocket update + alert dispatch |

Thresholds are configurable via environment variables without redeployment.

---

## WebSocket API

The service uses **STOMP over SockJS** (`/ws` endpoint).

### Connect

```javascript
const socket = new SockJS('http://localhost:8083/ws');
const client = Stomp.over(socket);
client.connect({}, () => {
  // Subscribe to all evaluation results for a patient
  client.subscribe('/topic/evaluations/patient-001', (msg) => {
    console.log(JSON.parse(msg.body));
  });

  // Subscribe to high/critical alerts (all patients)
  client.subscribe('/topic/alerts', (msg) => {
    console.log(JSON.parse(msg.body));
  });
});
```

### `/topic/evaluations/{patientId}` — evaluation result

Published for every completed evaluation regardless of risk level:

```json
{
  "evaluationId": "550e8400-...",
  "maxRiskScore": 0.823,
  "riskLevel": "HIGH",
  "status": "COMPLETED"
}
```

### `/topic/alerts` — high/critical alert

Published only when `maxRiskScore ≥ RISK_THRESHOLD_HIGH`:

```json
{
  "patientId": "patient-001",
  "evaluationId": "550e8400-...",
  "riskScore": 0.823,
  "level": "HIGH",
  "message": "[HIGH] Patient patient-001 has risk score 82.3%. Immediate review recommended."
}
```

---

## Kafka

| Topic | Direction | Notes |
|-------|-----------|-------|
| `ml.results.aggregated` | **Consumes** (`notification-group`) | Triggers all notification logic |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP` | `localhost:9092` | Kafka broker |
| `RISK_THRESHOLD_HIGH` | `0.75` | Minimum score for HIGH alert dispatch |
| `RISK_THRESHOLD_CRITICAL` | `0.90` | Minimum score for CRITICAL alert dispatch |
| `SPRING_PROFILES_ACTIVE` | `docker` | Active Spring profile |

Optional (production only):

| Variable | Description |
|----------|-------------|
| `SENDGRID_API_KEY` | SendGrid key for email alerts |
| `TWILIO_ACCOUNT_SID` | Twilio SID for SMS alerts |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |

---

## Running Locally

```bash
docker-compose up -d kafka

cd spring-services
mvn clean package -DskipTests

cd notification-service
KAFKA_BOOTSTRAP=localhost:9092 \
RISK_THRESHOLD_HIGH=0.75 \
RISK_THRESHOLD_CRITICAL=0.90 \
SPRING_PROFILES_ACTIVE=local \
mvn spring-boot:run
```

Service available at `http://localhost:8083`. WebSocket endpoint: `ws://localhost:8083/ws`.

---

## Actuator Endpoints

| URL | What it shows |
|-----|---------------|
| `GET /actuator/health` | Liveness + Kafka consumer status |
| `GET /actuator/prometheus` | Prometheus metrics |
