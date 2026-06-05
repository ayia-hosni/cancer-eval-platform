-- Patient service schema
CREATE SCHEMA IF NOT EXISTS patient_svc;

CREATE TABLE patient_svc.patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fhir_id         VARCHAR(64) UNIQUE NOT NULL,
    family_name     TEXT NOT NULL,
    given_name      TEXT NOT NULL,
    birth_date      DATE,
    gender          VARCHAR(16),
    fhir_resource   JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE patient_svc.observations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_fhir_id VARCHAR(64) NOT NULL REFERENCES patient_svc.patients(fhir_id),
    loinc_code      VARCHAR(32),
    value_json      JSONB,
    observation_type VARCHAR(64),
    recorded_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE patient_svc.evaluations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_fhir_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) DEFAULT 'PENDING',
    requested_at    TIMESTAMPTZ DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    result_bundle   JSONB
);

CREATE INDEX idx_patients_fhir_id    ON patient_svc.patients(fhir_id);
CREATE INDEX idx_obs_patient         ON patient_svc.observations(patient_fhir_id);
CREATE INDEX idx_eval_patient_status ON patient_svc.evaluations(patient_fhir_id, status);
