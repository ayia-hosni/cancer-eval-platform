"""
Breast Cancer Risk Classifier — FastAPI Service
Phase 2 of the ML roadmap: 5-model ensemble (LR, SVM, RF, GBM, KNN).
"""
import asyncio, json, logging, time, os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import (
    EvaluationRequest, FHIRObservation, FHIRCoding, FHIRCodeableConcept,
    FHIRQuantity, FHIRExtension, MLResult, MLPredictionResponse,
    HealthResponse, ReadinessResponse, build_interpretation,
)
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, model_risk_score, kafka_messages_consumed
from risk_engine import RiskClassifierEnsemble

log = logging.getLogger("risk-classifier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "risk-classifier"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
ensemble = RiskClassifierEnsemble()
producer = None

_TAGS = [
    {
        "name": "Prediction",
        "description": "Run the 5-model ensemble to produce a recurrence-risk score as a FHIR R4 Observation.",
    },
    {
        "name": "Ops",
        "description": "Liveness and readiness probes consumed by Kubernetes.",
    },
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = await make_producer()
    asyncio.create_task(consume_topic(
        "evaluation.requested", f"{SERVICE}-group", handle_evaluation
    ))
    log.info(f"{SERVICE} ready — {len(ensemble.models)} models in ensemble")
    yield
    await producer.stop()

app = FastAPI(
    title="Cancer Risk Classifier",
    version=MODEL_VERSION,
    description=(
        "**Phase 2** of the cancer evaluation ML roadmap.\n\n"
        "Runs a 5-model ensemble (Logistic Regression, SVM, Random Forest, Gradient Boosting, KNN) "
        "over clinical and genomic features and returns a recurrence-risk probability as a "
        "[FHIR R4 Observation](https://www.hl7.org/fhir/observation.html) (LOINC 72133-2).\n\n"
        "The service also subscribes to the `evaluation.requested` Kafka topic and publishes "
        "results to `ml.result.risk` automatically when triggered by the Patient Service."
    ),
    contact={"name": "Cancer Platform Team", "email": "platform@your-org.com"},
    license_info={"name": "Private — Internal Use Only"},
    openapi_tags=_TAGS,
    lifespan=lifespan,
)
Instrumentator().instrument(app).expose(app)

async def handle_evaluation(event: dict):
    kafka_messages_consumed.labels(service=SERVICE, topic="evaluation.requested").inc()
    req = EvaluationRequest(**event)
    if "all" not in req.model_types and "risk" not in req.model_types:
        return
    t0 = time.perf_counter()
    obs = ensemble.classify(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    risk_score = obs.valueQuantity.value if obs.valueQuantity else 0.5
    predictions_total.labels(service=SERVICE, outcome="success").inc()
    prediction_latency.labels(service=SERVICE).observe(elapsed / 1000)
    model_risk_score.labels(service=SERVICE).observe(risk_score)
    payload = MLResult(
        evaluation_id=req.evaluation_id, patient_id=req.patient_id, service=SERVICE,
        fhir_observation=obs.model_dump(), processing_ms=elapsed,
        model_version=MODEL_VERSION, trace_id=req.trace_id,
    )
    await producer.send("ml.result.risk", payload.model_dump())
    log.info(f"Classified patient={req.patient_id} risk={risk_score:.3f} in {elapsed}ms trace={req.trace_id}")

@app.post(
    "/api/ml/risk/classify",
    response_model=MLPredictionResponse,
    tags=["Prediction"],
    summary="Classify recurrence risk",
    responses={
        200: {"description": "FHIR Observation with risk score and 80% confidence interval"},
        422: {"description": "Validation error — missing required fields in request body"},
    },
)
async def classify(req: EvaluationRequest):
    """
    Run the 5-model ensemble on the supplied feature vector.

    Returns a **FHIR R4 Observation** containing:
    - `valueQuantity.value` — ensemble mean risk probability (0.0 – 1.0)
    - `interpretation` — `L` (< 0.50) / `N` (0.50–0.74) / `H` (0.75–0.89) / `CRITICAL` (≥ 0.90)
    - `extension[confidence-interval-low/high]` — 10th / 90th percentile across the ensemble
    - `extension[ensemble-size]` — number of models that voted

    The result is **not** published to Kafka from this endpoint; use the Kafka flow
    (via `evaluation.requested`) for the full pipeline.
    """
    t0 = time.perf_counter()
    obs = ensemble.classify(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    return MLPredictionResponse(observation=obs, processing_ms=elapsed, model_version=MODEL_VERSION)

@app.get("/health", response_model=HealthResponse, tags=["Ops"], summary="Liveness probe")
async def health():
    """Returns `200 OK` as long as the process is alive. Used by the Kubernetes liveness probe."""
    return HealthResponse(status="ok", service=SERVICE)

@app.get(
    "/ready",
    response_model=ReadinessResponse,
    tags=["Ops"],
    summary="Readiness probe",
    responses={503: {"description": "Service not ready — model weights not yet loaded"}},
)
async def ready():
    """
    Returns `200` once the ensemble models are loaded and the Kafka consumer is running.
    The Kubernetes readiness probe gates traffic on this endpoint.
    """
    return ReadinessResponse(status="ready", model_version=MODEL_VERSION)
