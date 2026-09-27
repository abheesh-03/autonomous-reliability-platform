package com.reliabilityplatform.checkout.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Base URLs for the downstream services checkout-service orchestrates.
 * Backed by CHECKOUT_PAYMENT_BASE_URL / CHECKOUT_INVENTORY_BASE_URL /
 * CHECKOUT_NOTIFICATION_BASE_URL (see application.yml).
 */
@ConfigurationProperties(prefix = "checkout.downstream")
public record DownstreamServiceProperties(
        String paymentBaseUrl,
        String inventoryBaseUrl,
        String notificationBaseUrl) {
}
