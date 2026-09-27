package com.reliabilityplatform.checkout.error;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Translates downstream service failures into a safe HTTP 502 response.
 * The full failure detail is logged for operators; only a fixed, generic
 * message is ever returned to the client.
 */
@RestControllerAdvice
public class CheckoutExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(CheckoutExceptionHandler.class);

    @ExceptionHandler(DownstreamServiceException.class)
    public ResponseEntity<DownstreamErrorResponse> handleDownstreamServiceException(DownstreamServiceException ex) {
        log.warn("Downstream failure calling {}: {}", ex.getService(), ex.getMessage(), ex);

        DownstreamErrorResponse body = new DownstreamErrorResponse(
                "downstream_failure",
                ex.getService(),
                "Downstream service request failed");

        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(body);
    }
}
