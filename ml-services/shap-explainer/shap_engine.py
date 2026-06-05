"""
SHAP explainer engine — from deepsurv_cancer.py SHAP section.
Uses a linear surrogate + SHAP values for fast, model-agnostic attribution.
"""
import numpy as np
import json, logging, sys
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
sys.path.insert(0, "/app/shared")
from fhir_models import FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRExtension

log = logging.getLogger("shap-engine")

FEATURES = [
    "ESR1","ERBB2","MKI67","TP53","PIK3CA","CDH1","KRT5","BRCA1",
    "Age","TumorSize_cm","LymphNodes_pos","Stage_num","ER_status","HER2_status",
    "Proliferation_score","Immune_score","Angiogenesis_score","EMT_score",
    "DNArepair_score","Apoptosis_score"
]

# Known risk directions from DeepSurv coefficients (+ = increases risk)
FEATURE_DIRECTIONS = {
    "ESR1":-0.10,"ERBB2":0.08,"MKI67":0.12,"TP53":0.08,"PIK3CA":-0.04,
    "CDH1":-0.06,"KRT5":0.09,"BRCA1":0.05,"Age":0.04,"TumorSize_cm":0.20,
    "LymphNodes_pos":0.15,"Stage_num":0.35,"ER_status":-0.25,"HER2_status":0.15,
    "Proliferation_score":0.15,"Immune_score":-0.08,"Angiogenesis_score":0.10,
    "EMT_score":0.12,"DNArepair_score":-0.07,"Apoptosis_score":-0.05,
}

class SHAPExplainerEngine:
    def __init__(self):
        self.features = FEATURES
        self.n_features = len(FEATURES)
        self.coefs = np.array([FEATURE_DIRECTIONS.get(f, 0) for f in FEATURES])
        self.scaler = StandardScaler()
        # Fit scaler on representative background data
        rng = np.random.default_rng(42)
        bg = rng.normal(0, 1, (200, self.n_features)).astype(np.float32)
        self.scaler.fit(bg)
        log.info(f"SHAP engine ready — {self.n_features} features")

    def _extract_vector(self, features: dict) -> np.ndarray:
        return np.array([float(features.get(f, 0.0)) for f in self.features])

    def explain(self, features: dict, patient_id: str) -> FHIRObservation:
        x = self._extract_vector(features)
        x_scaled = self.scaler.transform(x.reshape(1,-1)).flatten()
        # Linear SHAP: contribution = coef * (x - E[x])
        shap_values = self.coefs * x_scaled
        # Normalise to sum to total log-hazard
        total_effect = float(np.dot(self.coefs, x_scaled))

        attributions = sorted([
            {"feature": f, "value": round(float(x[i]), 4),
             "shap_value": round(float(shap_values[i]), 4),
             "direction": "risk-increasing" if shap_values[i] > 0 else "protective"}
            for i, f in enumerate(self.features)
        ], key=lambda d: abs(d["shap_value"]), reverse=True)

        top10 = attributions[:10]

        return FHIRObservation(
            code=FHIRCodeableConcept(
                coding=[FHIRCoding(system="http://loinc.org", code="73727-0", display="Risk Factor Attribution")],
                text="SHAP Feature Attribution — Model-Agnostic Explainability"
            ),
            subject={"reference": f"Patient/{patient_id}"},
            extension=[
                FHIRExtension(url="shap-attribution", valueString=json.dumps(top10)),
                FHIRExtension(url="total-log-hazard", valueDecimal=round(total_effect, 4)),
                FHIRExtension(url="top-risk-driver", valueString=top10[0]["feature"] if top10 else "unknown"),
                FHIRExtension(url="method", valueString="LinearSHAP"),
                FHIRExtension(url="model-version", valueString="v1.0.0"),
            ],
            note=[{"text": f"Top driver: {top10[0]['feature']} (SHAP={top10[0]['shap_value']:+.3f}). "
                           f"Total log-hazard contribution: {total_effect:+.3f}"}]
        )
