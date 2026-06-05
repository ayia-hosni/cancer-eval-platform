"""
Breast Cancer Risk Classifier — FastAPI Service
Phase 2 of the ML roadmap: 5-model ensemble (LR, SVM, RF, GBM, KNN).
"""
import asyncio, json, logging, time, os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

import sys; sys.path.insert(0, "/app/shared")
from fhir_models import EvaluationRequest, FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRQuantity, FHIRExtension, MLResult, build_interpretation
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, model_risk_score, kafka_messages_consumed
from risk_engine import RiskClassifierEnsemble

log = logging.getLogger("risk-classifier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "risk-classifier"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
ensemble = RiskClassifierEnsemble()
producer = None

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

app = FastAPI(title="Cancer Risk Classifier", version=MODEL_VERSION, lifespan=lifespan)
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
    log.info(f"Classified patient={req.patient_id} risk={risk_score:.3f} in {elapsed}ms")

@app.post("/api/ml/risk/classify", response_model=dict)
async def classify(req: EvaluationRequest):
    t0 = time.perf_counter()
    obs = ensemble.classify(req.patient_features, req.patient_id)
    return {"observation": obs.model_dump(), "processing_ms": int((time.perf_counter()-t0)*1000)}

@app.get("/health")
async def health(): return {"status": "ok", "service": SERVICE}
@app.get("/ready")
async def ready(): return {"status": "ready", "model_version": MODEL_VERSION, "models": ensemble.model_names}
