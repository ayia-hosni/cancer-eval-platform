"""
DeepSurv Survival Predictor — FastAPI Service
Phase 4 of the ML roadmap: Neural Cox PH survival prediction.
"""
import asyncio, logging, time, os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import (
    EvaluationRequest, MLResult, MLPredictionResponse,
    HealthResponse, ReadinessResponse,
)
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from survival_engine import DeepSurvPredictor

log = logging.getLogger("survival-predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "survival-predictor"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
predictor = DeepSurvPredictor()
producer = None

_TAGS = [
    {
        "name": "Prediction",
        "description": (
            "Predict overall survival in months and assign a risk group "
            "(**Low** / **Medium** / **High**) using a DeepSurv neural Cox proportional-hazards model."
        ),
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
    log.info(f"{SERVICE} ready — DeepSurv C-index (val) ~0.78")
    yield
    await producer.stop()

app = FastAPI(
    title="DeepSurv Survival Predictor",
    version=MODEL_VERSION,
    description=(
        "**Phase 4** of the cancer evaluation ML roadmap.\n\n"
        "Uses a [DeepSurv](https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-018-0684-2) "
        "neural Cox proportional-hazards model to predict overall survival (OS) in months "
        "and assign a risk group (Low / Medium / High).\n\n"
        "Validation C-index: **~0.78** on a held-out cohort of 240 patients.\n\n"
        "Publishes results to the `ml.result.survival` Kafka topic."
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
    if "all" not in req.model_types and "survival" not in req.model_types:
        return
    t0 = time.perf_counter()
    obs = predictor.predict(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    predictions_total.labels(service=SERVICE, outcome="success").inc()
    prediction_latency.labels(service=SERVICE).observe(elapsed / 1000)
    payload = MLResult(
        evaluation_id=req.evaluation_id, patient_id=req.patient_id, service=SERVICE,
        fhir_observation=obs.model_dump(), processing_ms=elapsed,
        model_version=MODEL_VERSION, trace_id=req.trace_id,
    )
    await producer.send("ml.result.survival", payload.model_dump())
    log.info(f"Survival predicted patient={req.patient_id} in {elapsed}ms trace={req.trace_id}")

@app.post(
    "/api/ml/survival/predict",
    response_model=MLPredictionResponse,
    tags=["Prediction"],
    summary="Predict overall survival",
    responses={
        200: {"description": "FHIR Observation with OS months, risk group, and 1/3/5-year survival probabilities"},
        422: {"description": "Validation error — missing required fields in request body"},
    },
)
async def predict(req: EvaluationRequest):
    """
    Predict overall survival from clinical and genomic features.

    Returns a **FHIR R4 Observation** (LOINC 75859-9) containing:
    - `valueQuantity.value` — predicted median OS in months (range 1 – 200)
    - `extension[risk-group]` — `Low` (OS > 60 mo) / `Medium` (24–60 mo) / `High` (< 24 mo)
    - `extension[survival-1yr]` — estimated 1-year survival probability
    - `extension[survival-3yr]` — estimated 3-year survival probability
    - `extension[survival-5yr]` — estimated 5-year survival probability

    Key input features: `Age`, `Stage_num`, `MKI67`, `ESR1`, `TumorSize_cm`, `LymphNodes_pos`.
    """
    t0 = time.perf_counter()
    obs = predictor.predict(req.patient_features, req.patient_id)
    return MLPredictionResponse(
        observation=obs,
        processing_ms=int((time.perf_counter() - t0) * 1000),
        model_version=MODEL_VERSION,
    )

@app.get("/health", response_model=HealthResponse, tags=["Ops"], summary="Liveness probe")
async def health():
    """Returns `200 OK` as long as the process is alive."""
    return HealthResponse(status="ok", service=SERVICE)

@app.get(
    "/ready",
    response_model=ReadinessResponse,
    tags=["Ops"],
    summary="Readiness probe",
    responses={503: {"description": "DeepSurv model weights not yet loaded"}},
)
async def ready():
    """Returns `200` once DeepSurv weights are loaded and the Kafka consumer is running."""
    return ReadinessResponse(status="ready", model_version=MODEL_VERSION)
