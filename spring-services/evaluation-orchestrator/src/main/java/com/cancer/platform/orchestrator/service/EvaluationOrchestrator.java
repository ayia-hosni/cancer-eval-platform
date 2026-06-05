package com.cancer.platform.orchestrator.service;

import com.cancer.platform.orchestrator.model.EvaluationResult;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class EvaluationOrchestrator {

    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final MongoTemplate mongoTemplate;
    private final ObjectMapper objectMapper;

    // Pending results: evaluationId -> map of service -> CompletableFuture<ServiceResult>
    private final ConcurrentHashMap<String, Map<String, CompletableFuture<EvaluationResult.ServiceResult>>>
        pendingEvaluations = new ConcurrentHashMap<>();

    private static final List<String> ML_SERVICES =
        List.of("tcga", "risk", "imaging", "survival", "shap");

    @Value("${ml.timeout.seconds:15}")
    private int timeoutSeconds;

    /** Consume evaluation.requested — fan out to all 5 ML Kafka topics. */
    @KafkaListener(topics = "evaluation.requested", groupId = "orchestrator-group")
    public void handleEvaluationRequest(Map<String, Object> event) {
        String evaluationId = (String) event.get("evaluationId");
        String patientId    = (String) event.get("patientId");
        String traceId      = (String) event.getOrDefault("traceId", UUID.randomUUID().toString());
        log.info("Orchestrating evaluationId={} patientId={}", evaluationId, patientId);

        // Set up futures for each service
        Map<String, CompletableFuture<EvaluationResult.ServiceResult>> futures = new ConcurrentHashMap<>();
        ML_SERVICES.forEach(s -> futures.put(s, new CompletableFuture<>()));
        pendingEvaluations.put(evaluationId, futures);

        // Fan out — the ML services consume evaluation.requested directly from Kafka
        // (they are already subscribed to that topic). No extra fan-out needed.
        // Schedule aggregation after timeout
        CompletableFuture.runAsync(() -> {
            try {
                Thread.sleep(timeoutSeconds * 1000L);
                aggregateAndPublish(evaluationId, patientId, traceId, futures);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
    }

    /** Consume results from all 5 ML result topics. */
    @KafkaListener(topics = {"ml.result.tcga","ml.result.risk","ml.result.imaging",
                              "ml.result.survival","ml.result.shap"},
                   groupId = "orchestrator-results-group")
    public void handleMlResult(Map<String, Object> result) {
        String evaluationId = (String) result.get("evaluationId");
        String service      = ((String) result.getOrDefault("service", "unknown"))
                                .replace("-", "").replace("predictor","").replace("classifier","")
                                .replace("profiler","").replace("explainer","");

        var futures = pendingEvaluations.get(evaluationId);
        if (futures == null) return;

        @SuppressWarnings("unchecked")
        Map<String, Object> obs = (Map<String, Object>) result.get("fhirObservation");
        var serviceResult = EvaluationResult.ServiceResult.builder()
            .service((String) result.get("service"))
            .fhirObservation(obs)
            .processingMs(((Number) result.getOrDefault("processingMs", 0)).intValue())
            .modelVersion((String) result.getOrDefault("modelVersion", "unknown"))
            .degraded(false)
            .build();

        // Match service key
        String key = ML_SERVICES.stream()
            .filter(s -> service.toLowerCase().contains(s))
            .findFirst().orElse(service);

        var future = futures.get(key);
        if (future != null) future.complete(serviceResult);

        // Check if all services have responded
        boolean allDone = futures.values().stream().allMatch(CompletableFuture::isDone);
        if (allDone) {
            aggregateAndPublish(evaluationId,
                (String) result.get("patientId"),
                (String) result.getOrDefault("traceId", ""),
                futures);
        }
    }

    private void aggregateAndPublish(
            String evaluationId, String patientId, String traceId,
            Map<String, CompletableFuture<EvaluationResult.ServiceResult>> futures) {

        if (!pendingEvaluations.containsKey(evaluationId)) return; // already processed
        pendingEvaluations.remove(evaluationId);

        List<EvaluationResult.ServiceResult> results = futures.entrySet().stream()
            .map(e -> e.getValue().isDone()
                ? e.getValue().join()
                : EvaluationResult.ServiceResult.builder()
                    .service(e.getKey()).degraded(true)
                    .fhirObservation(Map.of("resourceType","Observation",
                        "status","registered",
                        "dataAbsentReason", Map.of("text","Service timeout")))
                    .build())
            .collect(Collectors.toList());

        double maxRisk = results.stream()
            .filter(r -> r.getFhirObservation() != null)
            .mapToDouble(r -> extractRiskScore(r.getFhirObservation()))
            .max().orElse(0.0);

        EvaluationResult evalResult = EvaluationResult.builder()
            .evaluationId(evaluationId)
            .patientId(patientId)
            .traceId(traceId)
            .status(results.stream().anyMatch(EvaluationResult.ServiceResult::isDegraded)
                ? EvaluationResult.EvaluationStatus.PARTIAL
                : EvaluationResult.EvaluationStatus.COMPLETED)
            .serviceResults(results)
            .maxRiskScore(maxRisk)
            .aggregatedBundle(Map.of(
                "resourceType", "Bundle", "type", "collection",
                "entry", results.stream().map(r -> Map.of("resource", r.getFhirObservation())).toList()
            ))
            .createdAt(OffsetDateTime.now())
            .completedAt(OffsetDateTime.now())
            .build();

        mongoTemplate.save(evalResult);

        // Publish aggregated result
        kafkaTemplate.send("ml.results.aggregated", patientId, Map.of(
            "evaluationId", evaluationId, "patientId", patientId,
            "maxRiskScore", maxRisk, "status", evalResult.getStatus().name(),
            "traceId", traceId
        ));

        log.info("Aggregated evaluationId={} maxRisk={:.3f} status={}",
            evaluationId, maxRisk, evalResult.getStatus());
    }

    @SuppressWarnings("unchecked")
    private double extractRiskScore(Map<String, Object> obs) {
        try {
            var vq = (Map<String, Object>) obs.get("valueQuantity");
            if (vq != null) return ((Number) vq.get("value")).doubleValue();
        } catch (Exception ignored) {}
        return 0.0;
    }
}
