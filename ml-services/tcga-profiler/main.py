"""
TCGA Multi-Omics Profiler — FastAPI Service
Phase 1 of the ML roadmap: molecular subtype assignment + gene expression profiling.
"""
import asyncio, json, logging, time, os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import make_asgi_app

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import (
    EvaluationRequest, FHIRObservation, FHIRCoding, FHIRCodeableConcept,
    FHIRQuantity, FHIRExtension, MLResult, MLPredictionResponse,
    HealthResponse, ReadinessResponse, build_interpretation,
)
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, model_risk_score, kafka_messages_consumed
from tcga_engine import TCGAProfiler

log = logging.getLogger("tcga-profiler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "tcga-profiler"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
profiler = TCGAProfiler()
producer = None

_TAGS = [
    {
        "name": "Profiling",
        "description": (
            "Assign a TCGA molecular subtype to the patient using multi-omics gene expression. "
            "Subtypes: **Luminal A**, **Luminal B**, **HER2+**, **TNBC**."
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
    log.info(f"{SERVICE} started — model version {MODEL_VERSION}")
    yield
    await producer.stop()

app = FastAPI(
    title="TCGA Multi-Omics Profiler",
    version=MODEL_VERSION,
    description=(
        "**Phase 1** of the cancer evaluation ML roadmap.\n\n"
        "Assigns a [TCGA](https://www.cancer.gov/tcga) molecular breast-cancer subtype "
        "(Luminal A, Luminal B, HER2+, TNBC) from a gene-expression feature vector and returns "
        "a **FHIR R4 DiagnosticReport** with the subtype, confidence score, and top differentiating genes.\n\n"
        "The service subscribes to the `evaluation.requested` Kafka topic and publishes results "
        "to `ml.result.tcga` automatically."
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
    if "all" not in req.model_types and "tcga" not in req.model_types:
        return
    t0 = time.perf_counter()
    result_obs = profiler.profile(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    predictions_total.labels(service=SERVICE, outcome="success").inc()
    prediction_latency.labels(service=SERVICE).observe(elapsed / 1000)
    payload = MLResult(
        evaluation_id=req.evaluation_id,
        patient_id=req.patient_id,
        service=SERVICE,
        fhir_observation=result_obs.model_dump(),
        processing_ms=elapsed,
        model_version=MODEL_VERSION,
        trace_id=req.trace_id,
    )
    await producer.send("ml.result.tcga", payload.model_dump())
    log.info(f"Profiled patient={req.patient_id} in {elapsed}ms trace={req.trace_id}")

@app.post(
    "/api/ml/tcga/profile",
    response_model=MLPredictionResponse,
    tags=["Profiling"],
    summary="Assign TCGA molecular subtype",
    responses={
        200: {"description": "FHIR Observation with molecular subtype and confidence score"},
        422: {"description": "Validation error — missing required fields in request body"},
    },
)
async def profile_patient(req: EvaluationRequest):
    """
    Assign a TCGA molecular subtype from the supplied gene-expression features.

    Returns a **FHIR R4 Observation** containing:
    - `extension[molecular-subtype]` — one of `Luminal A`, `Luminal B`, `HER2+`, `TNBC`
    - `extension[subtype-confidence]` — classifier confidence (0.0 – 1.0)
    - `extension[top-genes]` — comma-separated list of top differentiating genes

    Key input features: `ESR1`, `ERBB2`, `MKI67`, `KRT5`, `CDH1`, `TP53`, `BRCA1`.
    Missing features default to 0.0 (population mean after z-scoring).
    """
    t0 = time.perf_counter()
    result = profiler.profile(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    return MLPredictionResponse(observation=result, processing_ms=elapsed, model_version=MODEL_VERSION)

@app.get("/health", response_model=HealthResponse, tags=["Ops"], summary="Liveness probe")
async def health():
    """Returns `200 OK` as long as the process is alive."""
    return HealthResponse(status="ok", service=SERVICE)

@app.get(
    "/ready",
    response_model=ReadinessResponse,
    tags=["Ops"],
    summary="Readiness probe",
    responses={503: {"description": "Model not yet loaded"}},
)
async def ready():
    """Returns `200` once the subtype classifier is loaded and the Kafka consumer is running."""
    return ReadinessResponse(status="ready", model_version=MODEL_VERSION)
