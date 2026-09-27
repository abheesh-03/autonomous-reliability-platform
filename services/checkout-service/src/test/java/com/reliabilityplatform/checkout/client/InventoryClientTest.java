package com.reliabilityplatform.checkout.client;

import com.reliabilityplatform.checkout.config.DownstreamServiceProperties;
import com.reliabilityplatform.checkout.error.DownstreamServiceException;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.http.HttpMethod.POST;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class InventoryClientTest {

    private static final DownstreamServiceProperties PROPERTIES =
            new DownstreamServiceProperties("unused", "http://inventory-service:8082", "unused");

    @Test
    void reserveSerializesSnakeCaseRequestAndDeserializesSnakeCaseResponse() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        InventoryClient client = new InventoryClient(builder, PROPERTIES);

        server.expect(requestTo("http://inventory-service:8082/inventory/reservations"))
                .andExpect(method(POST))
                .andExpect(content().json("""
                        {"checkout_id":"chk_1","sku":"sku_keyboard_001","quantity":2}
                        """))
                .andRespond(withSuccess("""
                        {"reservation_id":"res_1","checkout_id":"chk_1","sku":"sku_keyboard_001","quantity":2,"status":"RESERVED"}
                        """, MediaType.APPLICATION_JSON));

        InventoryReservationResponse response =
                client.reserve(new InventoryReservationRequest("chk_1", "sku_keyboard_001", 2));

        assertThat(response.reservationId()).isEqualTo("res_1");
        assertThat(response.checkoutId()).isEqualTo("chk_1");
        assertThat(response.sku()).isEqualTo("sku_keyboard_001");
        assertThat(response.quantity()).isEqualTo(2);
        assertThat(response.status()).isEqualTo("RESERVED");

        server.verify();
    }

    @Test
    void reserveWrapsDownstreamServerErrorAsDownstreamServiceException() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        InventoryClient client = new InventoryClient(builder, PROPERTIES);

        server.expect(requestTo("http://inventory-service:8082/inventory/reservations"))
                .andExpect(method(POST))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.reserve(new InventoryReservationRequest("chk_1", "sku_keyboard_001", 2)))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("inventory-service"));
    }
}
