package com.reliabilityplatform.checkout.client;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record NotificationTriggerResponse(
        String notificationId,
        String checkoutId,
        String kind,
        String recipient,
        String status) {
}
