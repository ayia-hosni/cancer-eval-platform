package com.cancer.platform.patient.repository;

import com.cancer.platform.patient.model.Patient;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;
import java.util.UUID;

public interface PatientRepository extends JpaRepository<Patient, UUID> {
    Optional<Patient> findByFhirId(String fhirId);
    boolean existsByFhirId(String fhirId);
}
