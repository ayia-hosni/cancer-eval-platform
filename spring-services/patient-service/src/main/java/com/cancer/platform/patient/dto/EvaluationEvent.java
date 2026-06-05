package com.cancer.platform.patient.dto;

import lombok.*;
import java.util.List;
import java.util.Map;

@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class EvaluationEvent {
    private String evaluationId;
    private String patientId;
    private Map<String, Object> patientFeatures;
    private String imageKey;
    private List<String> modelTypes;
    private String traceId;
    private String priority;
}
