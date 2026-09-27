package com.reliabilityplatform.checkout.client;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record InventoryReservationRequest(String checkoutId, String sku, Integer quantity) {
}
