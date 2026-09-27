package com.reliabilityplatform.checkout.error;

/** Safe, structured error body returned for downstream failures. Never
 * contains stack traces, internal URLs, exception class names, or raw
 * downstream response bodies. */
public record DownstreamErrorResponse(String error, String service, String message) {
}
