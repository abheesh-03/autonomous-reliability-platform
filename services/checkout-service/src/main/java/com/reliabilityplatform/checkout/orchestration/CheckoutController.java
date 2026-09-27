package com.reliabilityplatform.checkout.orchestration;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class CheckoutController {

    private final CheckoutOrchestrationService orchestrationService;

    public CheckoutController(CheckoutOrchestrationService orchestrationService) {
        this.orchestrationService = orchestrationService;
    }

    @PostMapping("/checkouts")
    public CheckoutResponse createCheckout(@Valid @RequestBody CheckoutRequest request) {
        return orchestrationService.checkout(request);
    }
}
