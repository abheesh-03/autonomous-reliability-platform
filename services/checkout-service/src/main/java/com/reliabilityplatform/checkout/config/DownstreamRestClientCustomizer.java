package com.reliabilityplatform.checkout.config;

import java.time.Duration;

import org.springframework.boot.http.client.ClientHttpRequestFactoryBuilder;
import org.springframework.boot.http.client.ClientHttpRequestFactorySettings;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Bounds every downstream RestClient's connect/read timeout.
 *
 * Without this, a downstream dependency stopped WHILE a keep-alive
 * connection to it is already pooled leaves a request hanging on an
 * already-established, now-abandoned TCP connection: no RST is ever
 * sent for a connection that was already open (unlike a fresh connect
 * attempt, which fails in well under 100ms once the dependency is
 * down), so without an explicit read timeout the client has nothing
 * to fail on until the OS's own TCP retransmission timeout, which can
 * take minutes. Discovered and measured directly (hung past 90s with
 * no response) via Phase 4's real, controlled Docker Compose failure
 * injection (scripts/simulate-failure.sh stopping inventory-service
 * immediately after a successful request) — not a hypothetical.
 *
 * Applies to PaymentClient, InventoryClient, and NotificationClient
 * alike, since Spring Boot applies every RestClientCustomizer bean to
 * the one auto-configured RestClient.Builder each of them receives —
 * no change needed in any of those three classes.
 */
@Component
public class DownstreamRestClientCustomizer implements RestClientCustomizer {

    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(3);
    private static final Duration READ_TIMEOUT = Duration.ofSeconds(5);

    @Override
    public void customize(RestClient.Builder builder) {
        ClientHttpRequestFactorySettings settings = ClientHttpRequestFactorySettings.defaults()
                .withConnectTimeout(CONNECT_TIMEOUT)
                .withReadTimeout(READ_TIMEOUT);
        builder.requestFactory(ClientHttpRequestFactoryBuilder.detect().build(settings));
    }
}
