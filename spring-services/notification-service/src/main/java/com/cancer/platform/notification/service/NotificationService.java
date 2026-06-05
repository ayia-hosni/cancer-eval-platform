package com.cancer.platform.notification.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;
import java.util.Map;

@Service
@RequiredArgsConstructor
@Slf4j
public class NotificationService {

    private final SimpMessagingTemplate wsTemplate;

    @Value("${risk.threshold.high:0.75}")
    private double highThreshold;

    @Value("${risk.threshold.critical:0.90}")
    private double criticalThreshold;

    @KafkaListener(topics = "ml.results.aggregated", groupId = "notification-group")
    public void handleAggregatedResult(Map<String, Object> result) {
        String patientId = (String) result.get("patientId");
        double maxRisk   = ((Number) result.getOrDefault("maxRiskScore", 0.0)).doubleValue();
        String evalId    = (String) result.get("evaluationId");

        String level = classifyRisk(maxRisk);
        if (maxRisk >= highThreshold) {
            dispatchAlert(patientId, evalId, maxRisk, level);
        }

        // Always push to WebSocket for dashboard update
        wsTemplate.convertAndSend(
            "/topic/evaluations/" + patientId,
            Map.of("evaluationId", evalId, "maxRiskScore", maxRisk,
                   "riskLevel", level, "status", result.get("status"))
        );
        log.info("Notification sent patientId={} risk={:.3f} level={}", patientId, maxRisk, level);
    }

    private void dispatchAlert(String patientId, String evalId, double risk, String level) {
        // WebSocket alert channel
        wsTemplate.convertAndSend(
            "/topic/alerts",
            Map.of("patientId", patientId, "evaluationId", evalId,
                   "riskScore", risk, "level", level,
                   "message", buildAlertMessage(patientId, risk, level))
        );
        // Email/SMS dispatch would go here via SendGrid / Twilio clients
        log.warn("ALERT dispatched level={} patientId={} risk={:.3f}", level, patientId, risk);
    }

    private String classifyRisk(double score) {
        if (score >= criticalThreshold) return "CRITICAL";
        if (score >= highThreshold)     return "HIGH";
        if (score >= 0.50)              return "MODERATE";
        return "LOW";
    }

    private String buildAlertMessage(String patientId, double risk, String level) {
        return String.format("[%s] Patient %s has risk score %.1f%%. Immediate review recommended.",
            level, patientId, risk * 100);
    }
}
