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
from fhir_models import EvaluationRequest, MLResult, FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRExtension
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from shap_engine import SHAPExplainerEngine

log = logging.getLogger("shap-explainer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "shap-explainer"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
explainer = SHAPExplainerEngine()
producer = None

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

app = FastAPI(title="SHAP Feature Explainer", version=MODEL_VERSION, lifespan=lifespan)
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
    log.info(f"SHAP explained patient={req.patient_id} in {elapsed}ms")

@app.post("/api/ml/explain/shap", response_model=dict)
async def explain(req: EvaluationRequest):
    t0 = time.perf_counter()
    obs = explainer.explain(req.patient_features, req.patient_id)
    return {"observation": obs.model_dump(), "processing_ms": int((time.perf_counter()-t0)*1000)}

@app.get("/health")
async def health(): return {"status": "ok", "service": SERVICE}
@app.get("/ready")
async def ready(): return {"status": "ready", "n_features": explainer.n_features}
