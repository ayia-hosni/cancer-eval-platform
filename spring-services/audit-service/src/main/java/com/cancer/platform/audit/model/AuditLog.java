package com.cancer.platform.audit.model;

import lombok.*;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import java.time.OffsetDateTime;
import java.util.Map;

@Document(collection = "audit_log")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class AuditLog {

    @Id private String id;

    @Indexed
    private String patientIdHash;   // HMAC-SHA256 of real patient ID

    private String eventType;       // patient.created, evaluation.requested, etc.
    private String actor;           // JWT sub claim (service name for ML events)
    private String evaluationId;
    private String traceId;

    @Indexed
    private OffsetDateTime timestamp;

    private String payloadHash;     // SHA-256 of event payload
    private Map<String, Object>  metadata;
    private String topic;
}
