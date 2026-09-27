package com.reliabilityplatform.checkout.orchestration;

import com.reliabilityplatform.checkout.client.InventoryClient;
import com.reliabilityplatform.checkout.client.InventoryReservationRequest;
import com.reliabilityplatform.checkout.client.InventoryReservationResponse;
import com.reliabilityplatform.checkout.client.NotificationClient;
import com.reliabilityplatform.checkout.client.NotificationTriggerRequest;
import com.reliabilityplatform.checkout.client.NotificationTriggerResponse;
import com.reliabilityplatform.checkout.client.PaymentAuthorizeRequest;
import com.reliabilityplatform.checkout.client.PaymentAuthorizeResponse;
import com.reliabilityplatform.checkout.client.PaymentClient;
import com.reliabilityplatform.checkout.error.DownstreamServiceException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CheckoutOrchestrationServiceTest {

    @Mock
    private PaymentClient paymentClient;

    @Mock
    private InventoryClient inventoryClient;

    @Mock
    private NotificationClient notificationClient;

    private CheckoutOrchestrationService orchestrationService;

    private static final CheckoutRequest VALID_REQUEST =
            new CheckoutRequest("sku_keyboard_001", 2, 2599, "USD", "customer@example.com");

    @BeforeEach
    void setUp() {
        orchestrationService = new CheckoutOrchestrationService(paymentClient, inventoryClient, notificationClient);
    }

    /** Echoes back whatever checkout_id was actually sent, like a well-behaved downstream service would. */
    private static void stubHappyPayment(PaymentClient paymentClient) {
        when(paymentClient.authorize(any())).thenAnswer(invocation -> {
            PaymentAuthorizeRequest req = invocation.getArgument(0);
            return new PaymentAuthorizeResponse("pay_1", req.checkoutId(), "AUTHORIZED", 2599, "USD");
        });
    }

    private static void stubHappyInventory(InventoryClient inventoryClient) {
        when(inventoryClient.reserve(any())).thenAnswer(invocation -> {
            InventoryReservationRequest req = invocation.getArgument(0);
            return new InventoryReservationResponse("res_1", req.checkoutId(), "sku_keyboard_001", 2, "RESERVED");
        });
    }

    @Test
    void happyPathCallsPaymentThenInventoryThenNotificationWithTheSameCheckoutId() {
        stubHappyPayment(paymentClient);
        stubHappyInventory(inventoryClient);
        when(notificationClient.notify(any())).thenAnswer(invocation -> {
            NotificationTriggerRequest req = invocation.getArgument(0);
            return new NotificationTriggerResponse(
                    "notif_1", req.checkoutId(), "ORDER_CONFIRMATION", "customer@example.com", "ACCEPTED");
        });

        CheckoutResponse response = orchestrationService.checkout(VALID_REQUEST);

        InOrder order = inOrder(paymentClient, inventoryClient, notificationClient);
        order.verify(paymentClient).authorize(any());
        order.verify(inventoryClient).reserve(any());
        order.verify(notificationClient).notify(any());

        ArgumentCaptor<PaymentAuthorizeRequest> paymentCaptor = ArgumentCaptor.forClass(PaymentAuthorizeRequest.class);
        ArgumentCaptor<InventoryReservationRequest> inventoryCaptor = ArgumentCaptor.forClass(InventoryReservationRequest.class);
        ArgumentCaptor<NotificationTriggerRequest> notificationCaptor = ArgumentCaptor.forClass(NotificationTriggerRequest.class);
        verify(paymentClient).authorize(paymentCaptor.capture());
        verify(inventoryClient).reserve(inventoryCaptor.capture());
        verify(notificationClient).notify(notificationCaptor.capture());

        String checkoutId = paymentCaptor.getValue().checkoutId();
        assertThat(checkoutId).startsWith("chk_");
        assertThat(inventoryCaptor.getValue().checkoutId()).isEqualTo(checkoutId);
        assertThat(notificationCaptor.getValue().checkoutId()).isEqualTo(checkoutId);

        assertThat(response.checkoutId()).isEqualTo(checkoutId);
        assertThat(response.status()).isEqualTo("COMPLETED");
        assertThat(response.payment()).isEqualTo(new PaymentResult("pay_1", "AUTHORIZED"));
        assertThat(response.inventory()).isEqualTo(new InventoryResult("res_1", "RESERVED"));
        assertThat(response.notification()).isEqualTo(new NotificationResult("notif_1", "ACCEPTED"));
    }

    @Test
    void paymentFailurePreventsInventoryAndNotificationCalls() {
        when(paymentClient.authorize(any()))
                .thenThrow(new DownstreamServiceException("payment-service", "boom"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class);

        verifyNoInteractions(inventoryClient);
        verifyNoInteractions(notificationClient);
    }

    @Test
    void inventoryFailurePreventsNotificationCall() {
        stubHappyPayment(paymentClient);
        when(inventoryClient.reserve(any()))
                .thenThrow(new DownstreamServiceException("inventory-service", "boom"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class);

        verifyNoInteractions(notificationClient);
    }

    @Test
    void notificationFailurePropagates() {
        stubHappyPayment(paymentClient);
        stubHappyInventory(inventoryClient);
        when(notificationClient.notify(any()))
                .thenThrow(new DownstreamServiceException("notification-service", "boom"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class);
    }

    @Test
    void unexpectedPaymentStatusIsTreatedAsDownstreamFailure() {
        when(paymentClient.authorize(any())).thenAnswer(invocation -> {
            PaymentAuthorizeRequest req = invocation.getArgument(0);
            return new PaymentAuthorizeResponse("pay_1", req.checkoutId(), "DECLINED", 2599, "USD");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("payment-service"));

        verifyNoInteractions(inventoryClient);
        verifyNoInteractions(notificationClient);
    }

    @Test
    void unexpectedInventoryStatusIsTreatedAsDownstreamFailure() {
        stubHappyPayment(paymentClient);
        when(inventoryClient.reserve(any())).thenAnswer(invocation -> {
            InventoryReservationRequest req = invocation.getArgument(0);
            return new InventoryReservationResponse("res_1", req.checkoutId(), "sku_keyboard_001", 2, "OUT_OF_STOCK");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("inventory-service"));

        verifyNoInteractions(notificationClient);
    }

    @Test
    void unexpectedNotificationStatusIsTreatedAsDownstreamFailure() {
        stubHappyPayment(paymentClient);
        stubHappyInventory(inventoryClient);
        when(notificationClient.notify(any())).thenAnswer(invocation -> {
            NotificationTriggerRequest req = invocation.getArgument(0);
            return new NotificationTriggerResponse(
                    "notif_1", req.checkoutId(), "ORDER_CONFIRMATION", "customer@example.com", "REJECTED");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("notification-service"));
    }

    @Test
    void nullPaymentIdIsTreatedAsDownstreamFailureAndPreventsInventoryAndNotificationCalls() {
        when(paymentClient.authorize(any())).thenAnswer(invocation -> {
            PaymentAuthorizeRequest req = invocation.getArgument(0);
            return new PaymentAuthorizeResponse(null, req.checkoutId(), "AUTHORIZED", 2599, "USD");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("payment-service"));

        verifyNoInteractions(inventoryClient);
        verifyNoInteractions(notificationClient);
    }

    @Test
    void blankPaymentIdIsTreatedAsDownstreamFailure() {
        when(paymentClient.authorize(any())).thenAnswer(invocation -> {
            PaymentAuthorizeRequest req = invocation.getArgument(0);
            return new PaymentAuthorizeResponse("   ", req.checkoutId(), "AUTHORIZED", 2599, "USD");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("payment-service"));

        verifyNoInteractions(inventoryClient);
        verifyNoInteractions(notificationClient);
    }

    @Test
    void mismatchedCheckoutIdFromPaymentIsTreatedAsDownstreamFailureAndPreventsInventoryAndNotificationCalls() {
        when(paymentClient.authorize(any()))
                .thenReturn(new PaymentAuthorizeResponse("pay_1", "chk_some-other-checkout", "AUTHORIZED", 2599, "USD"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("payment-service"));

        verifyNoInteractions(inventoryClient);
        verifyNoInteractions(notificationClient);
    }

    @Test
    void nullReservationIdIsTreatedAsDownstreamFailureAndPreventsNotificationCall() {
        stubHappyPayment(paymentClient);
        when(inventoryClient.reserve(any())).thenAnswer(invocation -> {
            InventoryReservationRequest req = invocation.getArgument(0);
            return new InventoryReservationResponse(null, req.checkoutId(), "sku_keyboard_001", 2, "RESERVED");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("inventory-service"));

        verifyNoInteractions(notificationClient);
    }

    @Test
    void mismatchedCheckoutIdFromInventoryIsTreatedAsDownstreamFailureAndPreventsNotificationCall() {
        stubHappyPayment(paymentClient);
        when(inventoryClient.reserve(any()))
                .thenReturn(new InventoryReservationResponse("res_1", "chk_some-other-checkout", "sku_keyboard_001", 2, "RESERVED"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("inventory-service"));

        verifyNoInteractions(notificationClient);
    }

    @Test
    void nullNotificationIdIsTreatedAsDownstreamFailure() {
        stubHappyPayment(paymentClient);
        stubHappyInventory(inventoryClient);
        when(notificationClient.notify(any())).thenAnswer(invocation -> {
            NotificationTriggerRequest req = invocation.getArgument(0);
            return new NotificationTriggerResponse(null, req.checkoutId(), "ORDER_CONFIRMATION", "customer@example.com", "ACCEPTED");
        });

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("notification-service"));
    }

    @Test
    void mismatchedCheckoutIdFromNotificationIsTreatedAsDownstreamFailure() {
        stubHappyPayment(paymentClient);
        stubHappyInventory(inventoryClient);
        when(notificationClient.notify(any()))
                .thenReturn(new NotificationTriggerResponse(
                        "notif_1", "chk_some-other-checkout", "ORDER_CONFIRMATION", "customer@example.com", "ACCEPTED"));

        assertThatThrownBy(() -> orchestrationService.checkout(VALID_REQUEST))
                .isInstanceOf(DownstreamServiceException.class)
                .satisfies(ex -> assertThat(((DownstreamServiceException) ex).getService()).isEqualTo("notification-service"));
    }
}
