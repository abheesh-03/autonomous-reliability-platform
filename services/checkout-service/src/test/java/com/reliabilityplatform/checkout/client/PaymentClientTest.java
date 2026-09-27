package com.reliabilityplatform.checkout.client;

import com.reliabilityplatform.checkout.config.DownstreamServiceProperties;
import com.reliabilityplatform.checkout.error.DownstreamServiceException;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.http.HttpMethod.POST;

class PaymentClientTest {

    private static final DownstreamServiceProperties PROPERTIES =
            new DownstreamServiceProperties("http://payment-service:8081", "unused", "unused");

    @Test
    void authorizeSerializesSnakeCaseRequestAndDeserializesSnakeCaseResponse() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        PaymentClient client = new PaymentClient(builder, PROPERTIES);

        server.expect(requestTo("http://payment-service:8081/payments/authorize"))
                .andExpect(method(POST))
                .andExpect(content().json("""
                        {"checkout_id":"chk_1","amount_cents":2599,"currency":"USD"}
                        """))
                .andRespond(withSuccess("""
                        {"payment_id":"pay_1","checkout_id":"chk_1","status":"AUTHORIZED","amount_cents":2599,"currency":"USD"}
                        """, MediaType.APPLICATION_JSON));

        PaymentAuthorizeResponse response = client.authorize(new PaymentAuthorizeRequest("chk_1", 2599, "USD"));

        assertThat(response.paymentId()).isEqualTo("pay_1");
        assertThat(response.checkoutId()).isEqualTo("chk_1");
        assertThat(response.status()).isEqualTo("AUTHORIZED");
        assertThat(response.amountCents()).isEqualTo(2599);
        assertThat(response.currency()).isEqualTo("USD");

        server.verify();
    }

    @Test
    void authorizeWrapsDownstreamServerErrorAsDownstreamServiceException() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        PaymentClient client = new PaymentClient(builder, PROPERTIES);

        server.expect(requestTo("http://payment-service:8081/payments/authorize"))
                .andExpect(method(POST))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.authorize(new PaymentAuthorizeRequest("chk_1", 2599, "USD")))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("payment-service"));
    }
}
