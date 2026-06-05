"""
DeepSurv Survival Predictor — FastAPI Service
Phase 4 of the ML roadmap: Neural Cox PH survival prediction.
"""
import asyncio, logging, time, os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import EvaluationRequest, MLResult
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, kafka_messages_consumed
from survival_engine import DeepSurvPredictor

log = logging.getLogger("survival-predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "survival-predictor"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
predictor = DeepSurvPredictor()
producer = None

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

app = FastAPI(title="DeepSurv Survival Predictor", version=MODEL_VERSION, lifespan=lifespan)
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
    log.info(f"Survival predicted patient={req.patient_id} in {elapsed}ms")

@app.post("/api/ml/survival/predict", response_model=dict)
async def predict(req: EvaluationRequest):
    t0 = time.perf_counter()
    obs = predictor.predict(req.patient_features, req.patient_id)
    return {"observation": obs.model_dump(), "processing_ms": int((time.perf_counter()-t0)*1000)}

@app.get("/health")
async def health(): return {"status": "ok", "service": SERVICE}
@app.get("/ready")
async def ready(): return {"status": "ready", "model": "DeepSurv", "version": MODEL_VERSION}
