"""Shared FHIR Pydantic models used by all FastAPI services."""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
import uuid

_SAMPLE_FEATURES = {
    "ESR1": 4.2, "ERBB2": -0.8, "MKI67": -1.2, "TP53": -0.5,
    "PIK3CA": 1.5, "CDH1": 1.8, "KRT5": -2.1, "BRCA1": -0.2,
    "Age": 58.0, "TumorSize_cm": 1.8, "LymphNodes_pos": 0.0,
    "Stage_num": 2.0, "ER_status": 1.0, "HER2_status": 0.0,
    "Proliferation_score": -1.5, "Immune_score": 0.3,
}

class FHIRCoding(BaseModel):
    system: str
    code: str
    display: Optional[str] = None

class FHIRCodeableConcept(BaseModel):
    coding: List[FHIRCoding]
    text: Optional[str] = None

class FHIRQuantity(BaseModel):
    value: float
    unit: str
    system: str = "http://unitsofmeasure.org"

class FHIRExtension(BaseModel):
    url: str
    valueString: Optional[str] = None
    valueDecimal: Optional[float] = None

class FHIRObservation(BaseModel):
    resourceType: str = "Observation"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "final"
    code: FHIRCodeableConcept
    subject: dict
    effectiveDateTime: str = Field(default_factory=lambda: datetime.utcnow().isoformat()+"Z")
    valueQuantity: Optional[FHIRQuantity] = None
    interpretation: Optional[List[FHIRCodeableConcept]] = None
    extension: Optional[List[FHIRExtension]] = None
    note: Optional[List[dict]] = None

class EvaluationRequest(BaseModel):
    evaluation_id: str = Field(..., description="Unique ID for this evaluation run", example="eval-001")
    patient_id: str = Field(..., description="FHIR Patient resource ID", example="patient-001")
    patient_features: dict = Field(
        ...,
        description="Clinical and genomic feature vector. All values are z-scored relative to the training cohort. Missing features default to 0.0 (population mean).",
        example=_SAMPLE_FEATURES,
    )
    image_key: Optional[str] = Field(None, description="S3 object key for the H&E pathology image (imaging-classifier only)", example="images/patient-001/slide_01.tiff")
    model_types: List[str] = Field(
        ["all"],
        description='Which models to invoke. Use `["all"]` to run every model, or a subset: `["risk"]`, `["tcga"]`, `["imaging"]`, `["survival"]`, `["shap"]`.',
        example=["all"],
    )
    trace_id: str = Field(..., description="Distributed trace ID propagated from the API Gateway", example="trace-abc123")
    priority: str = Field("NORMAL", description="Processing priority. `NORMAL` or `URGENT`.", example="NORMAL")

class MLPredictionResponse(BaseModel):
    """Standard response envelope returned by every ML service endpoint."""
    observation: FHIRObservation = Field(..., description="FHIR R4 Observation resource containing the model result")
    processing_ms: int = Field(..., description="Wall-clock inference time in milliseconds", example=124)
    model_version: Optional[str] = Field(None, description="Active model artifact version", example="v1.0.0")

class HealthResponse(BaseModel):
    status: str = Field(..., example="ok")
    service: str = Field(..., example="risk-classifier")

class ReadinessResponse(BaseModel):
    status: str = Field(..., example="ready")
    model_version: Optional[str] = Field(None, example="v1.0.0")

class MLResult(BaseModel):
    evaluation_id: str
    patient_id: str
    service: str
    fhir_observation: dict
    processing_ms: int
    model_version: str
    trace_id: str

def build_interpretation(score: float) -> List[FHIRCodeableConcept]:
    if score >= 0.90:
        code, display = "CRITICAL", "Critical"
    elif score >= 0.75:
        code, display = "H", "High"
    elif score >= 0.50:
        code, display = "N", "Moderate"
    else:
        code, display = "L", "Low"
    return [FHIRCodeableConcept(
        coding=[FHIRCoding(
            system="http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            code=code, display=display
        )]
    )]
