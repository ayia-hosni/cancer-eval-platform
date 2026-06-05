"""
Histopathology Imaging Classifier — FastAPI Service
Phase 3 of the ML roadmap: ResNet-50 fine-tuned on H&E patches.
"""
import asyncio, logging, time, os, io
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import EvaluationRequest, MLResult, build_interpretation
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from imaging_engine import HistopathologyClassifier

log = logging.getLogger("imaging-classifier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "imaging-classifier"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
classifier = HistopathologyClassifier()
producer = None

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

app = FastAPI(title="Histopathology Image Classifier", version=MODEL_VERSION, lifespan=lifespan)
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
    log.info(f"Image classified patient={req.patient_id} in {elapsed}ms")

@app.post("/api/ml/imaging/classify")
async def classify_image(file: UploadFile = File(None), patient_id: str = "unknown"):
    t0 = time.perf_counter()
    img_bytes = await file.read() if file else None
    obs = classifier.classify_image(img_bytes, patient_id)
    return {"observation": obs, "processing_ms": int((time.perf_counter()-t0)*1000)}

@app.post("/api/ml/imaging/classify-features")
async def classify_features(req: EvaluationRequest):
    obs = classifier.classify_from_features(req.patient_features, req.patient_id)
    return {"observation": obs}

@app.get("/health")
async def health(): return {"status": "ok", "service": SERVICE}
@app.get("/ready")
async def ready(): return {"status": "ready", "model": "ResNet-50", "version": MODEL_VERSION}
