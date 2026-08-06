"""
scripts/event_generator.py

Standalone CLI utility for signaling a running `OrderSupervisorWorkflow`
with a mock order event, outside of the FastAPI request/response cycle.
Useful for local development, demos, and manual testing.

Usage:
    python -m scripts.event_generator <order_id> payment_received \
        --amount 49.99 --currency USD

    python -m scripts.event_generator <order_id> shipment_delayed \
        --carrier UPS --new-eta 2026-07-10T12:00:00+00:00 --reason "weather"

    python -m scripts.event_generator <order_id> customer_message \
        --message "Where is my order?" --channel email

Run `python -m scripts.event_generator --help` or
`python -m scripts.event_generator <event_type> --help` for full options.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Callable

from temporalio.service import RPCError

from client import get_temporal_client
from shared.constants import workflow_id_for_order
from shared.dataclasses import OrderEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("event_generator")


# --------------------------------------------------------------------------
# Event-type -> payload builders
# --------------------------------------------------------------------------
#
# Each builder takes the parsed argparse.Namespace and returns the
# `payload` dict that will be wrapped in an OrderEvent(type=..., payload=...)
# and sent via the `submit_event` signal.


def _build_payment_received(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "amount": args.amount,
        "currency": args.currency,
        "payment_method": args.payment_method,
        "transaction_id": args.transaction_id,
    }


def _build_shipment_created(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "carrier": args.carrier,
        "tracking_number": args.tracking_number,
        "estimated_delivery": args.eta,
    }


def _build_shipment_delayed(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "carrier": args.carrier,
        "tracking_number": args.tracking_number,
        "new_estimated_delivery": args.new_eta,
        "reason": args.reason,
    }


def _build_customer_message(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "message": args.message,
        "channel": args.channel,
    }


def _build_refund_requested(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "amount": args.amount,
        "currency": args.currency,
        "reason": args.reason,
    }


def _build_order_delivered(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "carrier": args.carrier,
        "tracking_number": args.tracking_number,
        "delivered_at": args.delivered_at,
        "signed_by": args.signed_by,
    }


# --------------------------------------------------------------------------
# Event-type registry: name -> (payload builder, subparser configurator)
# --------------------------------------------------------------------------

PAYLOAD_BUILDERS: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "payment_received": _build_payment_received,
    "shipment_created": _build_shipment_created,
    "shipment_delayed": _build_shipment_delayed,
    "customer_message": _build_customer_message,
    "refund_requested": _build_refund_requested,
    "order_delivered": _build_order_delivered,
}


def _add_payment_received_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--amount", type=float, required=True, help="Payment amount")
    sub.add_argument("--currency", default="USD", help="Currency code (default: USD)")
    sub.add_argument("--payment-method", default="card", help="e.g. card, paypal, wallet")
    sub.add_argument(
        "--transaction-id",
        default=None,
        help="External transaction id (auto-generated if omitted)",
    )


def _add_shipment_created_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--carrier", default="UPS", help="Shipping carrier")
    sub.add_argument(
        "--tracking-number", default=None, help="Tracking number (auto-generated if omitted)"
    )
    sub.add_argument("--eta", default=None, help="Estimated delivery, ISO 8601")


def _add_shipment_delayed_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--carrier", default="UPS", help="Shipping carrier")
    sub.add_argument(
        "--tracking-number", default=None, help="Tracking number (auto-generated if omitted)"
    )
    sub.add_argument("--new-eta", required=True, help="New estimated delivery, ISO 8601")
    sub.add_argument("--reason", default="carrier delay", help="Reason for the delay")


def _add_customer_message_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--message", required=True, help="Message text from the customer")
    sub.add_argument("--channel", default="email", help="e.g. email, sms, chat")


def _add_refund_requested_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--amount", type=float, required=True, help="Refund amount requested")
    sub.add_argument("--currency", default="USD", help="Currency code (default: USD)")
    sub.add_argument("--reason", default="customer request", help="Reason for the refund")


def _add_order_delivered_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--carrier", default="UPS", help="Shipping carrier")
    sub.add_argument(
        "--tracking-number", default=None, help="Tracking number (auto-generated if omitted)"
    )
    sub.add_argument("--delivered-at", default=None, help="Delivery timestamp, ISO 8601")
    sub.add_argument("--signed-by", default=None, help="Name on the delivery signature, if any")


ARG_CONFIGURATORS: dict[str, Callable[[argparse.ArgumentParser], None]] = {
    "payment_received": _add_payment_received_args,
    "shipment_created": _add_shipment_created_args,
    "shipment_delayed": _add_shipment_delayed_args,
    "customer_message": _add_customer_message_args,
    "refund_requested": _add_refund_requested_args,
    "order_delivered": _add_order_delivered_args,
}


def _fill_defaults(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Fill in auto-generated values (ids, timestamps) left as None."""
    import uuid
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()

    if event_type == "payment_received" and payload.get("transaction_id") is None:
        payload["transaction_id"] = f"txn_{uuid.uuid4().hex[:12]}"

    if event_type in ("shipment_created", "shipment_delayed", "order_delivered"):
        if payload.get("tracking_number") is None:
            payload["tracking_number"] = f"1Z{uuid.uuid4().hex[:14].upper()}"

    if event_type == "shipment_created" and payload.get("estimated_delivery") is None:
        payload["estimated_delivery"] = now_iso

    if event_type == "order_delivered" and payload.get("delivered_at") is None:
        payload["delivered_at"] = now_iso

    return payload


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="event_generator",
        description="Signal a running OrderSupervisorWorkflow with a mock order event.",
    )
    parser.add_argument("order_id", help="Order id (used to derive the workflow id)")

    subparsers = parser.add_subparsers(
        dest="event_type",
        required=True,
        help="Type of event to send",
    )

    for event_type, configure_args in ARG_CONFIGURATORS.items():
        sub = subparsers.add_parser(event_type, help=f"Send a '{event_type}' event")
        configure_args(sub)

    return parser


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------


async def _send_event(order_id: str, event_type: str, payload: dict[str, Any]) -> None:
    client = await get_temporal_client()
    workflow_id = workflow_id_for_order(order_id)
    handle = client.get_workflow_handle(workflow_id)

    order_event = OrderEvent(type=event_type, payload=payload)

    logger.info(
        "Signaling workflow %r with event type=%r payload=%r",
        workflow_id,
        event_type,
        payload,
    )

    try:
        await handle.signal("submit_event", order_event)
    except RPCError as exc:
        # Fix H1: mirrors api/routers/runs.py::_signal_or_404's pattern —
        # the Temporal Python SDK surfaces "signal to nonexistent workflow"
        # as temporalio.service.RPCError (status NOT_FOUND), not a
        # dedicated WorkflowNotFoundError (which doesn't exist in
        # temporalio.exceptions).
        if "not found" in str(exc).lower():
            logger.error(
                "Workflow %r not found or not running. Has a run been created for order %r?",
                workflow_id,
                order_id,
            )
            sys.exit(1)
        raise

    logger.info("Event delivered to workflow %r.", workflow_id)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    payload_builder = PAYLOAD_BUILDERS[args.event_type]
    payload = payload_builder(args)
    payload = _fill_defaults(args.event_type, payload)

    asyncio.run(_send_event(args.order_id, args.event_type, payload))


if __name__ == "__main__":
    main()
