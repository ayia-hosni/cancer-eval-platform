package com.cancer.platform.patient.service;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.parser.IParser;
import ca.uhn.fhir.validation.FhirValidator;
import ca.uhn.fhir.validation.ValidationResult;
import lombok.extern.slf4j.Slf4j;
import org.hl7.fhir.r4.model.Patient;
import org.springframework.stereotype.Service;

@Service
@Slf4j
public class FhirValidationService {

    private final FhirContext fhirContext = FhirContext.forR4();
    private final FhirValidator validator = fhirContext.newValidator();
    private final IParser jsonParser = fhirContext.newJsonParser().setPrettyPrint(true);

    public Patient parseAndValidate(String fhirJson) {
        Patient patient = jsonParser.parseResource(Patient.class, fhirJson);
        ValidationResult result = validator.validateWithResult(patient);
        if (!result.isSuccessful()) {
            String errors = result.getMessages().stream()
                .filter(m -> m.getSeverity().ordinal() >= 2)
                .map(m -> m.getMessage())
                .reduce("", (a, b) -> a + "; " + b);
            log.warn("FHIR validation warnings: {}", errors);
        }
        return patient;
    }

    public String serialize(org.hl7.fhir.r4.model.IBaseResource resource) {
        return jsonParser.encodeResourceToString(resource);
    }

    public Map<String, Object> extractClinicalFeatures(Patient patient) {
        var features = new java.util.HashMap<String, Object>();
        if (patient.hasBirthDate()) {
            long age = java.time.Period.between(
                patient.getBirthDate().toInstant()
                    .atZone(java.time.ZoneId.systemDefault()).toLocalDate(),
                java.time.LocalDate.now()
            ).getYears();
            features.put("Age", (double) age);
        }
        patient.getExtension().forEach(ext -> {
            String url = ext.getUrl();
            if (url.contains("gene-expression") && ext.getValue() != null) {
                features.put(url.substring(url.lastIndexOf("/") + 1),
                    Double.parseDouble(ext.getValue().primitiveValue()));
            }
        });
        // Defaults for missing genomic features
        features.putIfAbsent("Stage_num", 2.0);
        features.putIfAbsent("MKI67", 0.5);
        features.putIfAbsent("ESR1", 1.0);
        return features;
    }
}
