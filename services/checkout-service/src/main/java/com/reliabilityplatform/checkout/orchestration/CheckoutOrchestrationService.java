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
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * Synchronously orchestrates a checkout: authorize payment, reserve
 * inventory, then trigger an order-confirmation notification — in that
 * exact order, stopping immediately on the first failure. There is
 * intentionally no rollback/compensation for steps that already
 * succeeded (e.g. an authorized payment is not reversed if inventory
 * reservation or notification subsequently fails) — that is deliberately
 * out of scope for this phase.
 */
@Service
public class CheckoutOrchestrationService {

    private static final String ORDER_CONFIRMATION = "ORDER_CONFIRMATION";
    private static final String PAYMENT_AUTHORIZED = "AUTHORIZED";
    private static final String INVENTORY_RESERVED = "RESERVED";
    private static final String NOTIFICATION_ACCEPTED = "ACCEPTED";
    private static final String CHECKOUT_COMPLETED = "COMPLETED";

    private final PaymentClient paymentClient;
    private final InventoryClient inventoryClient;
    private final NotificationClient notificationClient;

    public CheckoutOrchestrationService(
            PaymentClient paymentClient,
            InventoryClient inventoryClient,
            NotificationClient notificationClient) {
        this.paymentClient = paymentClient;
        this.inventoryClient = inventoryClient;
        this.notificationClient = notificationClient;
    }

    public CheckoutResponse checkout(CheckoutRequest request) {
        String checkoutId = generateCheckoutId();

        PaymentAuthorizeResponse payment = paymentClient.authorize(
                new PaymentAuthorizeRequest(checkoutId, request.amountCents(), request.currency()));
        validateDownstreamResponse(
                payment.paymentId(), payment.checkoutId(), checkoutId,
                payment.status(), PAYMENT_AUTHORIZED, "payment-service");

        InventoryReservationResponse inventory = inventoryClient.reserve(
                new InventoryReservationRequest(checkoutId, request.sku(), request.quantity()));
        validateDownstreamResponse(
                inventory.reservationId(), inventory.checkoutId(), checkoutId,
                inventory.status(), INVENTORY_RESERVED, "inventory-service");

        NotificationTriggerResponse notification = notificationClient.notify(
                new NotificationTriggerRequest(checkoutId, ORDER_CONFIRMATION, request.recipient()));
        validateDownstreamResponse(
                notification.notificationId(), notification.checkoutId(), checkoutId,
                notification.status(), NOTIFICATION_ACCEPTED, "notification-service");

        return new CheckoutResponse(
                checkoutId,
                CHECKOUT_COMPLETED,
                new PaymentResult(payment.paymentId(), payment.status()),
                new InventoryResult(inventory.reservationId(), inventory.status()),
                new NotificationResult(notification.notificationId(), notification.status()));
    }

    private static String generateCheckoutId() {
        return "chk_" + UUID.randomUUID();
    }

    /**
     * Validates a downstream response before proceeding to the next step:
     * the required id must be present, the echoed checkout_id must match
     * the one we sent, and the business status must be the expected one.
     * Jackson will happily deserialize an incomplete 200 response with
     * null fields, so this cannot be left to the client layer.
     */
    private static void validateDownstreamResponse(
            String id,
            String returnedCheckoutId,
            String expectedCheckoutId,
            String actualStatus,
            String expectedStatus,
            String service) {

        if (id == null || id.isBlank()) {
            throw new DownstreamServiceException(service, "Missing id in response from " + service);
        }
        if (!expectedCheckoutId.equals(returnedCheckoutId)) {
            throw new DownstreamServiceException(service, "checkout_id mismatch in response from " + service);
        }
        if (!expectedStatus.equals(actualStatus)) {
            throw new DownstreamServiceException(
                    service,
                    "Unexpected status from " + service + ": " + actualStatus);
        }
    }
}
