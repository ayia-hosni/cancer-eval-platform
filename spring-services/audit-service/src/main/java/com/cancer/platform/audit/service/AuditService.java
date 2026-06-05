package com.cancer.platform.audit.service;

import com.cancer.platform.audit.model.AuditLog;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.*;

@Service
@RequiredArgsConstructor
@Slf4j
public class AuditService {

    private final MongoTemplate mongoTemplate;
    private final ObjectMapper objectMapper;

    // In production: rotate this key via Vault
    private static final String HMAC_KEY = System.getenv()
        .getOrDefault("AUDIT_HMAC_KEY", "change-me-in-production-use-vault");

    @KafkaListener(
        topics = {"patient.created","patient.updated","evaluation.requested",
                  "ml.result.tcga","ml.result.risk","ml.result.imaging",
                  "ml.result.survival","ml.result.shap","ml.results.aggregated","alert.triggered"},
        groupId = "audit-service-group"
    )
    public void auditEvent(Map<String, Object> event, 
                           org.springframework.messaging.handler.annotation.Header(
                               org.springframework.kafka.support.KafkaHeaders.RECEIVED_TOPIC) String topic) {
        try {
            String patientId  = extractPatientId(event);
            String evalId     = (String) event.getOrDefault("evaluationId", "");
            String traceId    = (String) event.getOrDefault("traceId", "");
            String payloadStr = objectMapper.writeValueAsString(event);

            var entry = AuditLog.builder()
                .patientIdHash(hmac(patientId))
                .eventType(topic)
                .actor(extractActor(event, topic))
                .evaluationId(evalId)
                .traceId(traceId)
                .timestamp(OffsetDateTime.now())
                .payloadHash(sha256(payloadStr))
                .topic(topic)
                .metadata(Map.of("payloadSize", payloadStr.length()))
                .build();

            mongoTemplate.insert(entry, "audit_log");
            log.debug("Audited topic={} patientHash={}", topic, hmac(patientId).substring(0, 8));
        } catch (Exception e) {
            log.error("Failed to audit event from topic={}: {}", topic, e.getMessage());
        }
    }

    private String extractPatientId(Map<String, Object> event) {
        for (String key : List.of("patientId", "patient_id", "id")) {
            if (event.containsKey(key)) return String.valueOf(event.get(key));
        }
        return "unknown";
    }

    private String extractActor(Map<String, Object> event, String topic) {
        if (topic.startsWith("ml.result")) return (String) event.getOrDefault("service", "ml-service");
        return (String) event.getOrDefault("actor", "system");
    }

    private String hmac(String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(HMAC_KEY.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] bytes = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (Exception e) { return "hash-error"; }
    }

    private String sha256(String data) {
        try {
            var md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(data.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { return "hash-error"; }
    }
}
