"""Shared FHIR Pydantic models used by all FastAPI services."""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
import uuid

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
    evaluation_id: str
    patient_id: str
    patient_features: dict          # clinical + genomic features
    image_key: Optional[str] = None # S3 key for pathology image
    model_types: List[str] = ["all"]
    trace_id: str
    priority: str = "NORMAL"

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
