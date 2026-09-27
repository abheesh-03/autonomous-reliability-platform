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

class NotificationClientTest {

    private static final DownstreamServiceProperties PROPERTIES =
            new DownstreamServiceProperties("unused", "unused", "http://notification-service:8083");

    @Test
    void notifySerializesSnakeCaseRequestAndDeserializesSnakeCaseResponse() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        NotificationClient client = new NotificationClient(builder, PROPERTIES);

        server.expect(requestTo("http://notification-service:8083/notifications"))
                .andExpect(method(POST))
                .andExpect(content().json("""
                        {"checkout_id":"chk_1","kind":"ORDER_CONFIRMATION","recipient":"customer@example.com"}
                        """))
                .andRespond(withSuccess("""
                        {"notification_id":"notif_1","checkout_id":"chk_1","kind":"ORDER_CONFIRMATION","recipient":"customer@example.com","status":"ACCEPTED"}
                        """, MediaType.APPLICATION_JSON));

        NotificationTriggerResponse response = client.notify(
                new NotificationTriggerRequest("chk_1", "ORDER_CONFIRMATION", "customer@example.com"));

        assertThat(response.notificationId()).isEqualTo("notif_1");
        assertThat(response.checkoutId()).isEqualTo("chk_1");
        assertThat(response.kind()).isEqualTo("ORDER_CONFIRMATION");
        assertThat(response.recipient()).isEqualTo("customer@example.com");
        assertThat(response.status()).isEqualTo("ACCEPTED");

        server.verify();
    }

    @Test
    void notifyWrapsDownstreamServerErrorAsDownstreamServiceException() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        NotificationClient client = new NotificationClient(builder, PROPERTIES);

        server.expect(requestTo("http://notification-service:8083/notifications"))
                .andExpect(method(POST))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.notify(
                new NotificationTriggerRequest("chk_1", "ORDER_CONFIRMATION", "customer@example.com")))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("notification-service"));
    }
}
