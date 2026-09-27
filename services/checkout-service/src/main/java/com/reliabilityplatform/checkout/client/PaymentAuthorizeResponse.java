package com.reliabilityplatform.checkout.client;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PaymentAuthorizeResponse(
        String paymentId,
        String checkoutId,
        String status,
        Integer amountCents,
        String currency) {
}
