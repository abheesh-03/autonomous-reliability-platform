package com.reliabilityplatform.checkout.client;

import com.reliabilityplatform.checkout.config.DownstreamServiceProperties;
import com.reliabilityplatform.checkout.error.DownstreamServiceException;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * HTTP transport to inventory-service. Only handles the HTTP call and
 * response deserialization — interpreting the returned business status
 * is the orchestration service's responsibility.
 */
@Component
public class InventoryClient {

    static final String SERVICE_NAME = "inventory-service";

    private final RestClient restClient;

    public InventoryClient(RestClient.Builder restClientBuilder, DownstreamServiceProperties properties) {
        this.restClient = restClientBuilder.baseUrl(properties.inventoryBaseUrl()).build();
    }

    public InventoryReservationResponse reserve(InventoryReservationRequest request) {
        InventoryReservationResponse response;
        try {
            response = restClient.post()
                    .uri("/inventory/reservations")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(InventoryReservationResponse.class);
        } catch (RestClientException e) {
            throw new DownstreamServiceException(SERVICE_NAME, "Request to " + SERVICE_NAME + " failed", e);
        }

        if (response == null) {
            throw new DownstreamServiceException(SERVICE_NAME, SERVICE_NAME + " returned an empty response");
        }

        return response;
    }
}
