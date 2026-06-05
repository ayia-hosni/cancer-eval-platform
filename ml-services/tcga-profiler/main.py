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
from fhir_models import EvaluationRequest, FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRQuantity, FHIRExtension, MLResult, build_interpretation
from kafka_base import make_producer, consume_topic
from metrics import predictions_total, prediction_latency, model_risk_score, kafka_messages_consumed
from tcga_engine import TCGAProfiler

log = logging.getLogger("tcga-profiler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE = "tcga-profiler"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
profiler = TCGAProfiler()
producer = None

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

app = FastAPI(title="TCGA Multi-Omics Profiler", version=MODEL_VERSION, lifespan=lifespan)
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
    log.info(f"Profiled patient={req.patient_id} subtype={result_obs.note[0]['text'] if result_obs.note else 'unknown'} in {elapsed}ms")

@app.post("/api/ml/tcga/profile", response_model=dict)
async def profile_patient(req: EvaluationRequest):
    t0 = time.perf_counter()
    result = profiler.profile(req.patient_features, req.patient_id)
    elapsed = int((time.perf_counter() - t0) * 1000)
    return {"observation": result.model_dump(), "processing_ms": elapsed, "model_version": MODEL_VERSION}

@app.get("/health")
async def health(): return {"status": "ok", "service": SERVICE}

@app.get("/ready")
async def ready(): return {"status": "ready", "model_version": MODEL_VERSION}
