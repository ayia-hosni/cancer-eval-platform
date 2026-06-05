package com.cancer.platform.orchestrator.model;

import lombok.*;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

@Document(collection = "ml_results")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class EvaluationResult {

    @Id
    private String id;

    private String evaluationId;
    private String patientId;
    private String traceId;
    private EvaluationStatus status;
    private List<ServiceResult> serviceResults;
    private Map<String, Object> aggregatedBundle;
    private double maxRiskScore;
    private String primaryRiskService;
    private OffsetDateTime createdAt;
    private OffsetDateTime completedAt;
    private long processingMs;

    public enum EvaluationStatus { COMPLETED, PARTIAL, FAILED }

    @Data @Builder @NoArgsConstructor @AllArgsConstructor
    public static class ServiceResult {
        private String service;
        private Map<String, Object> fhirObservation;
        private int processingMs;
        private String modelVersion;
        private boolean degraded;  // true if circuit breaker used fallback
    }
}
