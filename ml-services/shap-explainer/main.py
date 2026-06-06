"""
SHAP Explainer Service — FastAPI Service
Phase 5 of the ML roadmap: model-agnostic KernelSHAP feature attribution.
Auto-invoked for any risk score >= 0.60.
"""
import asyncio, logging, time, os, json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import (
    EvaluationRequest, MLResult, FHIRObservation, FHIRCoding,
    FHIRCodeableConcept, FHIRExtension, MLPredictionResponse,
    HealthResponse, ReadinessResponse,
)
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from shap_engine import SHAPExplainerEngine

log = logging.getLogger("shap-explainer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "shap-explainer"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
explainer = SHAPExplainerEngine()
producer = None

_TAGS = [
    {
        "name": "Explanation",
        "description": (
            "Compute per-feature SHAP values to explain *why* a given risk score was produced. "
            "Automatically triggered for risk scores ≥ 0.60."
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
    log.info(f"{SERVICE} ready — KernelSHAP on {explainer.n_features} features")
    yield
    await producer.stop()

app = FastAPI(
    title="SHAP Feature Explainer",
    version=MODEL_VERSION,
    description=(
        "**Phase 5** of the cancer evaluation ML roadmap.\n\n"
        "Applies [KernelSHAP](https://arxiv.org/abs/1705.07874) (model-agnostic) to the "
        "5-model risk ensemble to produce a per-feature attribution score for every prediction.\n\n"
        "The explainer is automatically invoked by the Evaluation Orchestrator for any "
        "risk score ≥ 0.60 to give clinicians an interpretable breakdown of the contributing factors.\n\n"
        "Returns a **FHIR R4 Observation** (LOINC 73727-0) with the full SHAP attribution JSON "
        "embedded in an extension. Publishes results to `ml.result.shap`."
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
    if "all" not in req.model_types and "shap" not in req.model_types:
        return
    t0 = time.perf_counter()
    obs = explainer.explain(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    predictions_total.labels(service=SERVICE, outcome="success").inc()
    prediction_latency.labels(service=SERVICE).observe(elapsed / 1000)
    payload = MLResult(
        evaluation_id=req.evaluation_id, patient_id=req.patient_id, service=SERVICE,
        fhir_observation=obs.model_dump(), processing_ms=elapsed,
        model_version=MODEL_VERSION, trace_id=req.trace_id,
    )
    await producer.send("ml.result.shap", payload.model_dump())
    log.info(f"SHAP explained patient={req.patient_id} in {elapsed}ms trace={req.trace_id}")

@app.post(
    "/api/ml/explain/shap",
    response_model=MLPredictionResponse,
    tags=["Explanation"],
    summary="Compute SHAP feature attributions",
    responses={
        200: {"description": "FHIR Observation with full SHAP attribution JSON and top risk driver"},
        422: {"description": "Validation error — missing required fields in request body"},
    },
)
async def explain(req: EvaluationRequest):
    """
    Compute KernelSHAP attributions for the supplied feature vector.

    Runs KernelSHAP over the 5-model ensemble to determine which clinical and
    genomic features drove the risk score up or down.

    Returns a **FHIR R4 Observation** (LOINC 73727-0) containing:
    - `extension[shap-attribution]` — JSON array of `{feature, shap_value, direction}` objects,
      sorted by absolute SHAP value descending
    - `extension[top-risk-driver]` — name of the single most influential feature
    - `extension[baseline-risk]` — expected risk score with no feature information (intercept)

    **Interpretation:** a positive `shap_value` means the feature pushed the risk score *up*;
    negative means it pushed it *down*. Values are in probability units (same scale as the risk score).
    """
    t0 = time.perf_counter()
    obs = explainer.explain(req.patient_features, req.patient_id)
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
    responses={503: {"description": "KernelSHAP explainer not yet initialised"}},
)
async def ready():
    """Returns `200` once the KernelSHAP explainer is initialised and the Kafka consumer is running."""
    return ReadinessResponse(status="ready", model_version=MODEL_VERSION)
