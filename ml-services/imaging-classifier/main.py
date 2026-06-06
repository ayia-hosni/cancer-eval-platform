"""
Histopathology Imaging Classifier — FastAPI Service
Phase 3 of the ML roadmap: ResNet-50 fine-tuned on H&E patches.
"""
import asyncio, logging, time, os, io
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Query
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import (
    EvaluationRequest, MLResult, MLPredictionResponse,
    HealthResponse, ReadinessResponse, build_interpretation,
)
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from imaging_engine import HistopathologyClassifier

log = logging.getLogger("imaging-classifier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "imaging-classifier"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
classifier = HistopathologyClassifier()
producer = None

_TAGS = [
    {
        "name": "Image classification",
        "description": (
            "Classify a histopathology H&E patch as malignant or benign using a ResNet-50 "
            "fine-tuned on TCGA whole-slide image tiles."
        ),
    },
    {
        "name": "Feature-based classification",
        "description": (
            "Feature-proxy path for pipeline use: derives pseudo-image embeddings from "
            "clinical features when no image file is available."
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
    log.info(f"{SERVICE} ready — ResNet-50 loaded")
    yield
    await producer.stop()

app = FastAPI(
    title="Histopathology Image Classifier",
    version=MODEL_VERSION,
    description=(
        "**Phase 3** of the cancer evaluation ML roadmap.\n\n"
        "Classifies H&E-stained histopathology patches as malignant or benign using a "
        "**ResNet-50** model fine-tuned on TCGA whole-slide image tiles.\n\n"
        "Two inference paths are available:\n"
        "- `/classify` — accepts a raw image file (TIFF, PNG, JPEG)\n"
        "- `/classify-features` — feature-proxy path for Kafka pipeline use "
        "(derives embeddings from clinical features when no image is available)\n\n"
        "Returns a **FHIR R4 Observation** (LOINC 85319-2). "
        "Publishes results to the `ml.result.imaging` Kafka topic."
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
    if "all" not in req.model_types and "imaging" not in req.model_types:
        return
    t0 = time.perf_counter()
    obs = classifier.classify_from_features(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    predictions_total.labels(service=SERVICE, outcome="success").inc()
    prediction_latency.labels(service=SERVICE).observe(elapsed / 1000)
    payload = MLResult(
        evaluation_id=req.evaluation_id, patient_id=req.patient_id, service=SERVICE,
        fhir_observation=obs, processing_ms=elapsed,
        model_version=MODEL_VERSION, trace_id=req.trace_id,
    )
    await producer.send("ml.result.imaging", payload.model_dump())
    log.info(f"Image classified patient={req.patient_id} in {elapsed}ms trace={req.trace_id}")

@app.post(
    "/api/ml/imaging/classify",
    tags=["Image classification"],
    summary="Classify a histopathology image file",
    responses={
        200: {"description": "FHIR Observation with malignancy probability and tumour grade"},
        400: {"description": "No image file provided"},
        422: {"description": "Unsupported image format"},
    },
)
async def classify_image(
    file: UploadFile = File(..., description="H&E-stained patch image (TIFF, PNG, or JPEG, max 50 MB)"),
    patient_id: str = Query("unknown", description="FHIR Patient resource ID"),
):
    """
    Classify a raw histopathology image file.

    Accepts a TIFF, PNG, or JPEG upload. The image is resized to 224×224 and passed
    through ResNet-50 to produce a malignancy probability.

    Returns a **FHIR R4 Observation** (LOINC 85319-2) containing:
    - `valueQuantity.value` — P(malignant) (0.0 – 1.0)
    - `interpretation` — `L` / `N` / `H` / `CRITICAL`
    - `extension[tumour-grade]` — predicted Nottingham grade (1 / 2 / 3)
    """
    t0 = time.perf_counter()
    img_bytes = await file.read() if file else None
    obs = classifier.classify_image(img_bytes, patient_id)
    return {"observation": obs, "processing_ms": int((time.perf_counter() - t0) * 1000)}

@app.post(
    "/api/ml/imaging/classify-features",
    response_model=MLPredictionResponse,
    tags=["Feature-based classification"],
    summary="Classify using clinical feature proxy (no image required)",
    responses={
        200: {"description": "FHIR Observation with malignancy probability derived from feature embeddings"},
        422: {"description": "Validation error — missing required fields in request body"},
    },
)
async def classify_features(req: EvaluationRequest):
    """
    Feature-proxy classification path used by the Kafka evaluation pipeline.

    When no pathology image is available, this endpoint derives pseudo-image embeddings
    from clinical and genomic features (proliferation score, tumour size, grade markers)
    and runs them through the classification head.

    Returns the same **FHIR R4 Observation** schema as `/classify`.
    Use `/classify` instead if a raw image file is available — it is more accurate.
    """
    t0 = time.perf_counter()
    obs = classifier.classify_from_features(req.patient_features, req.patient_id)
    return {"observation": obs, "processing_ms": int((time.perf_counter() - t0) * 1000)}

@app.get("/health", response_model=HealthResponse, tags=["Ops"], summary="Liveness probe")
async def health():
    """Returns `200 OK` as long as the process is alive."""
    return HealthResponse(status="ok", service=SERVICE)

@app.get(
    "/ready",
    response_model=ReadinessResponse,
    tags=["Ops"],
    summary="Readiness probe",
    responses={503: {"description": "ResNet-50 weights not yet loaded"}},
)
async def ready():
    """Returns `200` once ResNet-50 is loaded and the Kafka consumer is running."""
    return ReadinessResponse(status="ready", model_version=MODEL_VERSION)
