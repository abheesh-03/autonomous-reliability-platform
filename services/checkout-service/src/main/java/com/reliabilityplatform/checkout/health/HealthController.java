package com.reliabilityplatform.checkout.health;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    private static final String SERVICE_NAME = "checkout-service";

    @GetMapping("/health")
    public HealthResponse health() {
        return new HealthResponse("UP", SERVICE_NAME);
    }
}
