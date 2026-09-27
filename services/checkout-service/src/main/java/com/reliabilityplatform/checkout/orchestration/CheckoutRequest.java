package com.reliabilityplatform.checkout.orchestration;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record CheckoutRequest(
        @NotBlank @Size(max = 100) String sku,

        @NotNull @Positive Integer quantity,

        @NotNull @Positive Integer amountCents,

        @NotBlank @Pattern(regexp = "^[A-Z]{3}$") String currency,

        @NotBlank @Size(max = 254) String recipient) {
}
