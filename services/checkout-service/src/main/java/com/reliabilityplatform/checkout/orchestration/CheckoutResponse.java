package com.reliabilityplatform.checkout.orchestration;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record CheckoutResponse(
        String checkoutId,
        String status,
        PaymentResult payment,
        InventoryResult inventory,
        NotificationResult notification) {
}
