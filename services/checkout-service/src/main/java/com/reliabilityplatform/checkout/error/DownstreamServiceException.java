package com.reliabilityplatform.checkout.error;

/**
 * Raised whenever a call to a downstream service (payment, inventory, or
 * notification) fails — a non-2xx response, a connection failure, an
 * unusable/empty response body, or an unexpected business status. Always
 * carries the name of the offending service so it can be reported safely.
 */
public class DownstreamServiceException extends RuntimeException {

    private final String service;

    public DownstreamServiceException(String service, String message) {
        super(message);
        this.service = service;
    }

    public DownstreamServiceException(String service, String message, Throwable cause) {
        super(message, cause);
        this.service = service;
    }

    public String getService() {
        return service;
    }
}
