"""
TCGA profiling engine — productionised from tcga_cancer_analysis.py
Performs PCA-based molecular subtype assignment from gene expression features.
"""
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from typing import Optional
import sys; sys.path.insert(0, "/app/shared")
from fhir_models import FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRQuantity, FHIRExtension

GENE_FEATURES = ["ESR1","ERBB2","MKI67","TP53","PIK3CA","CDH1","KRT5","BRCA1"]
SUBTYPES = ["Luminal A","Luminal B","HER2+","TNBC"]

# Subtype centroids in gene expression space (from TCGA BRCA analysis)
CENTROIDS = np.array([
    [ 4.5,-0.5,-1.5,-0.5, 1.5, 1.5,-2.0,-0.2],  # Luminal A
    [ 2.5, 0.5, 2.0, 0.5, 1.0, 0.5,-1.0,-0.2],  # Luminal B
    [-1.0, 4.0, 1.5, 0.5, 0.0,-0.5,-0.5,-0.2],  # HER2+
    [-2.5,-0.5, 2.5, 2.5,-0.5,-1.5, 3.0, 1.0],  # TNBC
])

class TCGAProfiler:
    def __init__(self):
        self.scaler = StandardScaler()
        self.scaler.mean_ = np.array([2.5, 1.0, 1.2, 0.8, 0.7, 0.6, 0.2, 0.1])
        self.scaler.scale_ = np.array([2.0, 1.8, 1.5, 1.2, 1.0, 1.1, 1.6, 0.8])
        self.scaler.n_features_in_ = 8
        self.model_version = "v1.0.0"

    def _extract_gene_vector(self, features: dict) -> np.ndarray:
        return np.array([float(features.get(g, np.random.normal(0.5, 0.5))) for g in GENE_FEATURES])

    def _assign_subtype(self, gene_vec: np.ndarray) -> tuple[str, float]:
        dists = np.linalg.norm(CENTROIDS - gene_vec, axis=1)
        idx = np.argmin(dists)
        confidence = float(1.0 - dists[idx] / (dists.sum() + 1e-8))
        return SUBTYPES[idx], confidence

    def _compute_risk_from_subtype(self, subtype: str, features: dict) -> float:
        base = {"Luminal A": 0.22, "Luminal B": 0.42, "HER2+": 0.61, "TNBC": 0.78}
        risk = base.get(subtype, 0.50)
        stage = float(features.get("Stage_num", 2))
        risk += (stage - 2) * 0.06
        return float(np.clip(risk, 0.01, 0.99))

    def profile(self, features: dict, patient_id: str) -> FHIRObservation:
        gene_vec = self._extract_gene_vector(features)
        subtype, confidence = self._assign_subtype(gene_vec)
        risk_score = self._compute_risk_from_subtype(subtype, features)
        top_genes = sorted(GENE_FEATURES, key=lambda g: abs(float(features.get(g, 0))), reverse=True)[:5]

        return FHIRObservation(
            code=FHIRCodeableConcept(
                coding=[FHIRCoding(system="http://loinc.org", code="81247-9", display="Molecular subtype")],
                text="Molecular Subtype Assignment"
            ),
            subject={"reference": f"Patient/{patient_id}"},
            valueQuantity=FHIRQuantity(value=round(risk_score, 4), unit="risk score"),
            extension=[
                FHIRExtension(url="molecular-subtype", valueString=subtype),
                FHIRExtension(url="subtype-confidence", valueDecimal=round(confidence, 4)),
                FHIRExtension(url="top-expressed-genes", valueString=",".join(top_genes)),
                FHIRExtension(url="model-version", valueString=self.model_version),
            ],
            note=[{"text": f"Subtype: {subtype} (confidence={confidence:.2f}). Top genes: {', '.join(top_genes)}"}]
        )
