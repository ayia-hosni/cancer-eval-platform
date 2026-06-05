package com.cancer.platform.patient.controller;

import com.cancer.platform.patient.model.Patient;
import com.cancer.platform.patient.model.Evaluation;
import com.cancer.platform.patient.service.PatientService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/fhir/r4")
@RequiredArgsConstructor
@Slf4j
public class PatientController {

    private final PatientService patientService;

    /** Create patient from FHIR R4 JSON bundle. */
    @PostMapping(value = "/Patient", consumes = "application/fhir+json")
    public ResponseEntity<Map<String, Object>> createPatient(@RequestBody String fhirJson) {
        Patient patient = patientService.createPatient(fhirJson);
        return ResponseEntity
            .created(URI.create("/fhir/r4/Patient/" + patient.getFhirId()))
            .body(Map.of("id", patient.getFhirId(), "status", "created"));
    }

    /** Fetch patient record. */
    @GetMapping("/Patient/{id}")
    public ResponseEntity<String> getPatient(@PathVariable String id) {
        return patientService.findByFhirId(id)
            .map(p -> ResponseEntity.ok().contentType(
                org.springframework.http.MediaType.parseMediaType("application/fhir+json"))
                .body(p.getFhirResource()))
            .orElse(ResponseEntity.notFound().build());
    }

    /** Trigger ML evaluation — async, returns 202 + Location header. */
    @PostMapping("/Patient/{id}/$evaluate")
    public ResponseEntity<Map<String, Object>> evaluate(
            @PathVariable String id,
            @RequestParam(required = false) List<String> models) {
        UUID evalId = patientService.triggerEvaluation(id, models);
        return ResponseEntity
            .accepted()
            .location(URI.create("/fhir/r4/Evaluation/" + evalId))
            .body(Map.of(
                "evaluationId", evalId.toString(),
                "status", "PENDING",
                "message", "Evaluation queued. Poll /fhir/r4/Evaluation/" + evalId
            ));
    }

    /** List evaluation results for a patient. */
    @GetMapping("/Patient/{id}/evaluations")
    public ResponseEntity<List<Evaluation>> getEvaluations(@PathVariable String id) {
        return ResponseEntity.ok(patientService.getEvaluations(id));
    }
}
