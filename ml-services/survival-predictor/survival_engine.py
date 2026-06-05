"""
DeepSurv engine — productionised from deepsurv_cancer.py.
Neural Cox PH model trained on synthetic TCGA-like multi-omics cohort.
"""
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler
import logging, sys
sys.path.insert(0, "/app/shared")
from fhir_models import FHIRObservation, FHIRCoding, FHIRCodeableConcept, FHIRQuantity, FHIRExtension

log = logging.getLogger("survival-engine")

FEATURES = [
    "ESR1","ERBB2","MKI67","TP53","PIK3CA","CDH1","KRT5","BRCA1",
    "Age","TumorSize_cm","LymphNodes_pos","Stage_num","ER_status","HER2_status",
    "Proliferation_score","Immune_score","Angiogenesis_score","EMT_score",
    "DNArepair_score","Apoptosis_score"
]
N_FEATURES = len(FEATURES)

class DeepSurvNet(nn.Module):
    def __init__(self, in_f=N_FEATURES, hidden=[64,64,32], dropout=0.4):
        super().__init__()
        layers = []
        prev = in_f
        for i, h in enumerate(hidden):
            layers += [nn.Linear(prev, h), nn.BatchNorm1d(h), nn.ReLU(inplace=True)]
            if i < len(hidden)-1: layers.append(nn.Dropout(dropout))
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)
    def forward(self, x): return self.net(x).squeeze(-1)

class DeepSurvPredictor:
    def __init__(self):
        self.device = torch.device("cpu")
        self.net, self.scaler = self._train()
        log.info("DeepSurv trained on synthetic TCGA cohort (800 patients, 20 features)")

    def _generate_training_data(self, n=800, seed=42):
        rng = np.random.default_rng(seed)
        subtypes = rng.choice(["Luminal A","Luminal B","HER2+","TNBC"], n, p=[0.4,0.25,0.2,0.15])
        X = rng.normal(0, 1, (n, N_FEATURES)).astype(np.float32)
        X[:, FEATURES.index("Age")] = rng.normal(57, 11, n)
        X[:, FEATURES.index("Stage_num")] = rng.choice([1,2,3,4], n, p=[0.2,0.45,0.25,0.1]).astype(float)
        log_h = (
            0.04*X[:, FEATURES.index("Age")]/10 +
            0.20*np.abs(X[:, FEATURES.index("TumorSize_cm")]) +
            0.35*(X[:, FEATURES.index("Stage_num")]-2) +
            0.12*X[:, FEATURES.index("MKI67")] +
            -0.10*X[:, FEATURES.index("ESR1")] +
            0.15*X[:, FEATURES.index("Proliferation_score")] +
            0.08*X[:, FEATURES.index("TP53")]
        )
        rate = np.exp(log_h) / 80.0
        t = rng.exponential(1.0/np.clip(rate, 1e-4, 1)).clip(1, 180)
        e = (t < rng.uniform(24, 180, n)).astype(float)
        return X, t.astype(np.float32), e.astype(np.float32)

    def _train(self):
        X, t, e = self._generate_training_data()
        scaler = StandardScaler()
        X_s = scaler.fit_transform(X).astype(np.float32)
        net = DeepSurvNet().to(self.device)
        opt = torch.optim.Adam(net.parameters(), lr=5e-4, weight_decay=1e-4)
        Xt = torch.tensor(X_s); tt = torch.tensor(t); et = torch.tensor(e)
        net.train()
        for ep in range(60):
            opt.zero_grad()
            lh = net(Xt)
            order = torch.argsort(tt, descending=True)
            lh_s = lh[order]; e_s = et[order]
            lcs = torch.logcumsumexp(lh_s, dim=0)
            loss = -torch.mean((lh_s - lcs) * e_s)
            loss.backward(); nn.utils.clip_grad_norm_(net.parameters(), 1.0); opt.step()
        net.eval()
        return net, scaler

    def _risk_group(self, log_h: float) -> str:
        if log_h > 1.0: return "High"
        if log_h > 0.0: return "Medium"
        return "Low"

    def _predicted_os(self, log_h: float) -> float:
        # Approximate OS from log hazard using exponential distribution
        return float(np.clip(60.0 * np.exp(-log_h * 0.8), 3, 180))

    def _km_json(self, log_h: float) -> str:
        import json
        t_pts = list(range(0, 181, 6))
        rate = np.exp(log_h) / 80.0
        s_pts = [round(np.exp(-rate * t), 3) for t in t_pts]
        return json.dumps({"time_months": t_pts, "survival_probability": s_pts})

    def predict(self, features: dict, patient_id: str) -> FHIRObservation:
        x_raw = np.array([float(features.get(f, 0.0)) for f in FEATURES], dtype=np.float32).reshape(1, -1)
        x_scaled = self.scaler.transform(x_raw).astype(np.float32)
        with torch.no_grad():
            log_h = float(self.net(torch.tensor(x_scaled)).item())
        os_months = self._predicted_os(log_h)
        risk_group = self._risk_group(log_h)
        risk_score = float(np.clip((log_h + 2) / 4, 0, 1))  # normalise to [0,1]

        return FHIRObservation(
            code=FHIRCodeableConcept(
                coding=[FHIRCoding(system="http://loinc.org", code="75859-9", display="Survival Estimate")],
                text="Predicted Overall Survival — DeepSurv Neural Cox PH"
            ),
            subject={"reference": f"Patient/{patient_id}"},
            valueQuantity=FHIRQuantity(value=round(os_months, 1), unit="months"),
            extension=[
                FHIRExtension(url="risk-group", valueString=risk_group),
                FHIRExtension(url="log-hazard", valueDecimal=round(log_h, 4)),
                FHIRExtension(url="risk-score", valueDecimal=round(risk_score, 4)),
                FHIRExtension(url="km-curve-json", valueString=self._km_json(log_h)),
                FHIRExtension(url="model-version", valueString="v1.0.0"),
            ],
            note=[{"text": f"DeepSurv predicted OS={os_months:.1f} months. Risk group: {risk_group}. Log-hazard={log_h:.3f}"}]
        )
