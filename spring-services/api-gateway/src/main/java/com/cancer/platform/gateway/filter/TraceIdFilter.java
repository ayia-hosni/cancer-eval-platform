package com.cancer.platform.gateway.filter;

import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.util.UUID;

/** Injects W3C trace-id into every request. */
@Component
@Slf4j
public class TraceIdFilter implements GlobalFilter, Ordered {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String traceId = exchange.getRequest().getHeaders()
            .getFirst("traceparent");
        if (traceId == null) {
            traceId = "00-" + UUID.randomUUID().toString().replace("-","") + "-0000000000000001-01";
        }
        final String finalTraceId = traceId;
        ServerHttpRequest mutated = exchange.getRequest().mutate()
            .header("traceparent", finalTraceId)
            .header("X-Request-ID", UUID.randomUUID().toString())
            .build();
        log.debug("Request {} {} trace={}", mutated.getMethod(), mutated.getURI().getPath(),
            finalTraceId.substring(0, Math.min(finalTraceId.length(), 20)));
        return chain.filter(exchange.mutate().request(mutated).build());
    }

    @Override public int getOrder() { return -100; }
}
