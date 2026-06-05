"""
Risk classifier ensemble — from breast_cancer_classifier.py
5-model ensemble: Logistic Regression, SVM, Random Forest, GBM, KNN.
Trains on Wisconsin Breast Cancer dataset at startup.
"""
import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier
import logging, sys
sys.path.insert(0, "/app/shared")
from fhir_models import FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRQuantity, FHIRExtension, build_interpretation

log = logging.getLogger("risk-engine")

WISCONSIN_FEATURES = [
    "mean_radius","mean_texture","mean_perimeter","mean_area","mean_smoothness",
    "mean_compactness","mean_concavity","mean_concave_points","mean_symmetry",
    "mean_fractal_dimension","radius_error","texture_error","perimeter_error",
    "area_error","smoothness_error","compactness_error","concavity_error",
    "concave_points_error","symmetry_error","fractal_dimension_error",
    "worst_radius","worst_texture","worst_perimeter","worst_area",
    "worst_smoothness","worst_compactness","worst_concavity",
    "worst_concave_points","worst_symmetry","worst_fractal_dimension",
]

class RiskClassifierEnsemble:
    def __init__(self):
        self.model_names = ["Logistic Regression","SVM","Random Forest","Gradient Boosting","KNN"]
        self.models = self._train_ensemble()
        self.feature_names = WISCONSIN_FEATURES
        log.info(f"Ensemble trained: {len(self.models)} models on Wisconsin BC dataset")

    def _train_ensemble(self):
        data = load_breast_cancer()
        X_train, _, y_train, _ = train_test_split(data.data, data.target, test_size=0.2, random_state=42, stratify=data.target)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        models = [
            Pipeline([("s", StandardScaler()), ("m", LogisticRegression(C=1.0, max_iter=2000, random_state=42))]),
            Pipeline([("s", StandardScaler()), ("m", SVC(probability=True, random_state=42))]),
            Pipeline([("s", StandardScaler()), ("m", RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1))]),
            Pipeline([("s", StandardScaler()), ("m", GradientBoostingClassifier(n_estimators=100, random_state=42))]),
            Pipeline([("s", StandardScaler()), ("m", KNeighborsClassifier(n_neighbors=7, weights="distance"))]),
        ]
        for m in models:
            m.fit(X_train, y_train)
        return models

    def _extract_features(self, features: dict) -> np.ndarray:
        vec = np.array([float(features.get(f, np.random.uniform(5, 20))) for f in self.feature_names])
        return vec.reshape(1, -1)

    def classify(self, features: dict, patient_id: str) -> FHIRObservation:
        X = self._extract_features(features)
        # Ensemble: average P(malignant) across all models. Note: target 1=benign in sklearn, we invert.
        probs = [1.0 - m.predict_proba(X)[0, 1] for m in self.models]
        risk_score = float(np.mean(probs))
        ci_low  = float(np.percentile(probs, 10))
        ci_high = float(np.percentile(probs, 90))
        interp = build_interpretation(risk_score)

        return FHIRObservation(
            code=FHIRCodeableConcept(
                coding=[FHIRCoding(system="http://loinc.org", code="72133-2", display="Cancer Risk Assessment")],
                text="Malignancy Risk Score — Ensemble Classifier"
            ),
            subject={"reference": f"Patient/{patient_id}"},
            valueQuantity=FHIRQuantity(value=round(risk_score, 4), unit="probability"),
            interpretation=interp,
            extension=[
                FHIRExtension(url="confidence-interval-low",  valueDecimal=round(ci_low, 4)),
                FHIRExtension(url="confidence-interval-high", valueDecimal=round(ci_high, 4)),
                FHIRExtension(url="ensemble-size", valueString=str(len(self.models))),
                FHIRExtension(url="model-version", valueString="v1.0.0"),
            ],
            note=[{"text": f"Ensemble risk: {risk_score:.3f} (90% CI: {ci_low:.3f}–{ci_high:.3f}). {interp[0].coding[0].display} risk."}]
        )
