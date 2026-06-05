package com.cancer.platform.patient.service;

import com.cancer.platform.patient.dto.EvaluationEvent;
import com.cancer.platform.patient.model.Patient;
import com.cancer.platform.patient.model.Evaluation;
import com.cancer.platform.patient.repository.PatientRepository;
import com.cancer.platform.patient.repository.EvaluationRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

@Service
@RequiredArgsConstructor
@Slf4j
public class PatientService {

    private final PatientRepository patientRepo;
    private final EvaluationRepository evalRepo;
    private final FhirValidationService fhirService;
    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final ObjectMapper objectMapper;

    @Transactional
    @CachePut(value = "patients", key = "#result.fhirId")
    public Patient createPatient(String fhirJson) {
        var fhirPatient = fhirService.parseAndValidate(fhirJson);
        var patient = Patient.builder()
            .fhirId(fhirPatient.getIdElement().getIdPart())
            .familyName(fhirPatient.getNameFirstRep().getFamily())
            .givenName(fhirPatient.getNameFirstRep().getGivenAsSingleString())
            .birthDate(fhirPatient.hasBirthDate()
                ? fhirPatient.getBirthDate().toInstant()
                    .atZone(java.time.ZoneId.systemDefault()).toLocalDate()
                : null)
            .gender(fhirPatient.hasGender() ? fhirPatient.getGender().toCode() : null)
            .fhirResource(fhirJson)
            .build();

        patient = patientRepo.save(patient);

        // Publish patient.created event
        var event = Map.of("patientId", patient.getFhirId(),
            "action", "CREATED", "traceId", UUID.randomUUID().toString());
        kafkaTemplate.send("patient.created", patient.getFhirId(), event);
        log.info("Patient created fhirId={}", patient.getFhirId());
        return patient;
    }

    @Cacheable(value = "patients", key = "#fhirId")
    public Optional<Patient> findByFhirId(String fhirId) {
        return patientRepo.findByFhirId(fhirId);
    }

    @Transactional
    public UUID triggerEvaluation(String patientFhirId, List<String> modelTypes) {
        var patient = patientRepo.findByFhirId(patientFhirId)
            .orElseThrow(() -> new NoSuchElementException("Patient not found: " + patientFhirId));

        var evaluation = Evaluation.builder()
            .patientFhirId(patientFhirId)
            .status(Evaluation.EvaluationStatus.PENDING)
            .build();
        evaluation = evalRepo.save(evaluation);

        var features = fhirService.extractClinicalFeatures(
            fhirService.parseAndValidate(patient.getFhirResource())
        );

        var event = EvaluationEvent.builder()
            .evaluationId(evaluation.getId().toString())
            .patientId(patientFhirId)
            .patientFeatures(features)
            .modelTypes(modelTypes != null ? modelTypes : List.of("all"))
            .traceId(UUID.randomUUID().toString())
            .priority("NORMAL")
            .build();

        kafkaTemplate.send("evaluation.requested", patientFhirId, event);
        log.info("Evaluation triggered evaluationId={} patientId={}", evaluation.getId(), patientFhirId);
        return evaluation.getId();
    }

    public List<Evaluation> getEvaluations(String patientFhirId) {
        return evalRepo.findByPatientFhirIdOrderByRequestedAtDesc(patientFhirId);
    }
}
