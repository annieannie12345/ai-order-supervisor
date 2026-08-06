export const toolOptions = [
  "send_customer_message",
  "create_internal_note",
  "escalate_issue",
  "mark_for_review",
  "schedule_next_wakeup",
  "close_workflow"
] as const;

export const eventTemplates = [
  {
    type: "payment_confirmed",
    label: "Payment confirmed",
    payload: { amount: 49.99, currency: "USD", transaction_id: "txn_demo" }
  },
  {
    type: "payment_failed",
    label: "Payment failed",
    payload: { amount: 49.99, currency: "USD", reason: "card_declined" }
  },
  {
    type: "shipment_created",
    label: "Shipment created",
    payload: {
      carrier: "UPS",
      tracking_number: "1ZDEMO",
      estimated_delivery: "2026-07-10T12:00:00+00:00"
    }
  },
  {
    type: "shipment_delayed",
    label: "Shipment delayed",
    payload: {
      carrier: "UPS",
      tracking_number: "1ZDEMO",
      new_estimated_delivery: "2026-07-12T12:00:00+00:00",
      reason: "weather"
    }
  },
  {
    type: "customer_message_received",
    label: "Customer message",
    payload: { message: "Can you tell me where my order is?", channel: "email" }
  },
  {
    type: "refund_requested",
    label: "Refund requested",
    payload: { amount: 49.99, currency: "USD", reason: "delivery delay" }
  },
  {
    type: "delivered",
    label: "Delivered",
    payload: { delivered_at: "2026-07-11T17:30:00+00:00", signed_by: "Jane Doe" }
  }
] as const;
