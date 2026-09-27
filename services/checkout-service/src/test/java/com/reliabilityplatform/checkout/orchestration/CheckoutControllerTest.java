package com.reliabilityplatform.checkout.orchestration;

import com.reliabilityplatform.checkout.error.DownstreamServiceException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CheckoutController.class)
class CheckoutControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private CheckoutOrchestrationService orchestrationService;

    private static final String VALID_REQUEST_JSON = """
            {
              "sku": "sku_keyboard_001",
              "quantity": 2,
              "amount_cents": 2599,
              "currency": "USD",
              "recipient": "customer@example.com"
            }
            """;

    @Test
    void validRequestReturnsCompletedCheckoutResponse() throws Exception {
        CheckoutResponse canned = new CheckoutResponse(
                "chk_550e8400-e29b-41d4-a716-446655440000",
                "COMPLETED",
                new PaymentResult("pay_1", "AUTHORIZED"),
                new InventoryResult("res_1", "RESERVED"),
                new NotificationResult("notif_1", "ACCEPTED"));
        when(orchestrationService.checkout(any())).thenReturn(canned);

        mockMvc.perform(post("/checkouts")
                        .contentType("application/json")
                        .content(VALID_REQUEST_JSON))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith("application/json"))
                .andExpect(jsonPath("$.checkout_id").value("chk_550e8400-e29b-41d4-a716-446655440000"))
                .andExpect(jsonPath("$.status").value("COMPLETED"))
                .andExpect(jsonPath("$.payment.payment_id").value("pay_1"))
                .andExpect(jsonPath("$.payment.status").value("AUTHORIZED"))
                .andExpect(jsonPath("$.inventory.reservation_id").value("res_1"))
                .andExpect(jsonPath("$.inventory.status").value("RESERVED"))
                .andExpect(jsonPath("$.notification.notification_id").value("notif_1"))
                .andExpect(jsonPath("$.notification.status").value("ACCEPTED"));
    }

    @Test
    void missingSkuIsRejected() throws Exception {
        assertRejected("""
                {"quantity": 2, "amount_cents": 2599, "currency": "USD", "recipient": "customer@example.com"}
                """);
    }

    @Test
    void emptySkuIsRejected() throws Exception {
        assertRejected("""
                {"sku": "", "quantity": 2, "amount_cents": 2599, "currency": "USD", "recipient": "customer@example.com"}
                """);
    }

    @ParameterizedTest
    @ValueSource(ints = {0, -1})
    void nonPositiveQuantityIsRejected(int quantity) throws Exception {
        assertRejected("""
                {"sku": "sku_keyboard_001", "quantity": %d, "amount_cents": 2599, "currency": "USD", "recipient": "customer@example.com"}
                """.formatted(quantity));
    }

    @ParameterizedTest
    @ValueSource(ints = {0, -1})
    void nonPositiveAmountCentsIsRejected(int amountCents) throws Exception {
        assertRejected("""
                {"sku": "sku_keyboard_001", "quantity": 2, "amount_cents": %d, "currency": "USD", "recipient": "customer@example.com"}
                """.formatted(amountCents));
    }

    @ParameterizedTest
    @ValueSource(strings = {"usd", "US", "USDD", "123"})
    void invalidCurrencyIsRejected(String currency) throws Exception {
        assertRejected("""
                {"sku": "sku_keyboard_001", "quantity": 2, "amount_cents": 2599, "currency": "%s", "recipient": "customer@example.com"}
                """.formatted(currency));
    }

    @Test
    void missingRecipientIsRejected() throws Exception {
        assertRejected("""
                {"sku": "sku_keyboard_001", "quantity": 2, "amount_cents": 2599, "currency": "USD"}
                """);
    }

    @Test
    void emptyRecipientIsRejected() throws Exception {
        assertRejected("""
                {"sku": "sku_keyboard_001", "quantity": 2, "amount_cents": 2599, "currency": "USD", "recipient": ""}
                """);
    }

    @Test
    void downstreamFailureIsReturnedAsSafe502() throws Exception {
        when(orchestrationService.checkout(any()))
                .thenThrow(new DownstreamServiceException("payment-service", "connection refused to 10.0.0.5:8081"));

        mockMvc.perform(post("/checkouts")
                        .contentType("application/json")
                        .content(VALID_REQUEST_JSON))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.error").value("downstream_failure"))
                .andExpect(jsonPath("$.service").value("payment-service"))
                .andExpect(jsonPath("$.message").value("Downstream service request failed"))
                .andExpect(content().string(org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("10.0.0.5"))));
    }

    private void assertRejected(String requestJson) throws Exception {
        mockMvc.perform(post("/checkouts")
                        .contentType("application/json")
                        .content(requestJson))
                .andExpect(status().isBadRequest());
    }
}
