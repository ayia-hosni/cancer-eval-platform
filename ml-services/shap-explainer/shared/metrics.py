"""Prometheus metrics helpers shared across FastAPI services."""
from prometheus_client import Counter, Histogram, Gauge

predictions_total = Counter(
    "ml_predictions_total", "Total predictions made",
    ["service", "outcome"]
)
prediction_latency = Histogram(
    "ml_prediction_latency_seconds", "Prediction latency",
    ["service"], buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
)
model_risk_score = Histogram(
    "ml_risk_score_distribution", "Distribution of risk scores",
    ["service"], buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)
kafka_messages_consumed = Counter(
    "ml_kafka_messages_consumed_total", "Kafka messages consumed",
    ["service", "topic"]
)
