package com.cancer.platform.patient.repository;

import com.cancer.platform.patient.model.Evaluation;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.UUID;

public interface EvaluationRepository extends JpaRepository<Evaluation, UUID> {
    List<Evaluation> findByPatientFhirIdOrderByRequestedAtDesc(String patientFhirId);
}
