package com.cancer.platform.patient.model;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "evaluations", schema = "patient_svc")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class Evaluation {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "patient_fhir_id", nullable = false)
    private String patientFhirId;

    @Column(name = "status")
    @Enumerated(EnumType.STRING)
    private EvaluationStatus status;

    @Column(name = "requested_at", updatable = false)
    private OffsetDateTime requestedAt;

    @Column(name = "completed_at")
    private OffsetDateTime completedAt;

    @Column(name = "result_bundle", columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private String resultBundle;

    public enum EvaluationStatus { PENDING, IN_PROGRESS, COMPLETED, FAILED, PARTIAL }

    @PrePersist
    protected void onCreate() { requestedAt = OffsetDateTime.now(); }
}
