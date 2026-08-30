import time

import click

from snaplii.client import GatewayClient
from snaplii.output import print_json

_TERMINAL_STATUSES = {"FINISHED", "CANCELLED", "FAILED"}

# Human-readable text for the fail_reason enum on FAILED (and swept CANCELLED)
# rows, so the agent can tell the user what actually went wrong instead of
# echoing an enum name.
_FAIL_MESSAGES = {
    "INSUFFICIENT_BALANCE": "Snaplii Cash balance was insufficient when the transfer was sent. Top up in the Snaplii app, then create a new transfer.",
    "EXPIRED_UPSTREAM": "The pending transfer expired upstream before it could be sent. No money moved — create a new transfer.",
    "UPSTREAM_MISSING": "The upstream order could not be found when settling. Contact Snaplii support with the order number.",
    "STATE_CONFLICT": "The transfer hit a state conflict while settling (e.g. a finish and a cancel raced). Contact Snaplii support with the order number before retrying.",
    "GATEWAY_BUG": "The gateway hit an internal error settling this transfer. Contact Snaplii support with the order number.",
    "SESSION_EXPIRED": "The gateway's upstream session expired while settling. Contact Snaplii support with the order number.",
    "KEY_REVOKED": "The API key that created this transfer was revoked before it settled, so it was not sent.",
    "SCOPE_REVOKED": "The API key lost its transfer (P2P) scope before this transfer settled, so it was not sent.",
    "QUOTE_EXPIRED": "The transfer quote expired before it settled. Create a new transfer.",
    "CREATE_UNRESOLVED": "The create never resolved upstream. Create a new transfer (a fresh request is safe here).",
    "RECIPIENT_INVALID": "The recipient could not receive this transfer.",
    "TOO_MANY_PENDING": "The account has too many pending transfers upstream. Wait for them to settle, then retry.",
    "REJECTED": "The transfer was declined by Snaplii's risk checks.",
    "AUTO_FINISH_DISABLED": "Automatic sending is disabled on this gateway, so the pending transfer expired without being sent.",
    "CANCELLED_BY_AGENT": "Cancelled at the agent's request.",
    "UNKNOWN": "The transfer failed for an unclassified reason. Contact Snaplii support with the order number.",
}
for _code in ("LEDGER_MCAP7004", "LEDGER_MCAP7005", "LEDGER_MCAP7006", "LEDGER_MCAP7007"):
    _FAIL_MESSAGES[_code] = ("A ledger step failed while settling this transfer. "
                             "Contact Snaplii support with the order number.")


def decorate_transfer(resp):
    """Attach agent-facing helper fields to a TransferResponse dict:

    - cross_currency_notice when the recipient's amount/currency differ from
      what the sender pays (disclose to the user; cancellable until
      auto_finish_at)
    - fail_message translating fail_reason into meaningful text
    """
    if not isinstance(resp, dict):
        return resp
    if (resp.get("received_amount") and resp.get("amount")
            and (resp.get("received_currency") != resp.get("currency")
                 or resp.get("received_amount") != resp.get("amount"))):
        notice = (
            f"The recipient receives {resp['received_amount']} "
            f"{resp.get('received_currency') or ''} for your {resp['amount']} "
            f"{resp.get('currency') or ''} (rate {resp.get('conversion_rate') or '?'})."
        )
        if resp.get("status") in ("CREATING", "PENDING"):
            notice += (" Disclose this to the user — they can still cancel until "
                       "auto_finish_at.")
        resp["cross_currency_notice"] = notice
    reason = resp.get("fail_reason")
    if reason and "fail_message" not in resp:
        msg = _FAIL_MESSAGES.get(reason)
        if msg:
            resp["fail_message"] = msg
    return resp


@click.group("transfer")
def transfer_group():
    """P2P transfers — send Snaplii Cash to a phone number.

    A new transfer stays cancellable until auto_finish_at (~5 minutes), then
    the gateway sends it automatically. 'finish' sends it immediately.
    """


@transfer_group.command("create")
@click.option("--to-phone", required=True, help="Recipient's phone number (any format)")
@click.option("--amount", required=True,
              help='Amount to send as a string, e.g. "12.50" (minimum 1.00)')
@click.option("--remark", default=None,
              help="Optional note to the recipient (max 200 characters)")
@click.option("--idempotency-key", default=None,
              help="ONLY to retry the identical request (after a 202 CREATING or an "
                   "indeterminate timeout). Omit otherwise — a fresh key is generated "
                   "per request.")
@click.pass_context
def create_cmd(ctx, to_phone, amount, remark, idempotency_key):
    """Create a transfer (cancellable ~5 min, then sends automatically)."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.transfer_create(to_phone=to_phone, amount=amount, remark=remark,
                                  idempotency_key=idempotency_key)
    resp = decorate_transfer(resp)
    if isinstance(resp, dict) and resp.get("status") == "CREATING":
        resp["next_step"] = (
            "The create has not resolved yet. After retry_after_seconds, re-run "
            "'snaplii transfer create' with --idempotency-key set to the SAME key "
            "above (NEVER a fresh key — that can double the transfer), or find the "
            "resolved row with 'snaplii transfer list'."
        )
    print_json(resp)


@transfer_group.command("cancel")
@click.option("--order-no", required=True, help="Order number from 'transfer create'")
@click.pass_context
def cancel_cmd(ctx, order_no):
    """Cancel a PENDING transfer (allowed until auto_finish_at)."""
    client: GatewayClient = ctx.obj["client"]
    resp = decorate_transfer(client.transfer_cancel(order_no))
    if isinstance(resp, dict) and resp.get("status") == "CANCELLING":
        resp["next_step"] = (
            "Cancel accepted but not yet confirmed upstream — poll "
            f"'snaplii transfer status --order-no {order_no} --wait' for the final state."
        )
    print_json(resp)


@transfer_group.command("finish")
@click.option("--order-no", required=True, help="Order number from 'transfer create'")
@click.pass_context
def finish_cmd(ctx, order_no):
    """Send the transfer NOW (only when the user explicitly asks).

    This shortens the undo window and cannot be undone once settled.
    """
    client: GatewayClient = ctx.obj["client"]
    resp = decorate_transfer(client.transfer_finish(order_no))
    if isinstance(resp, dict):
        resp["next_step"] = (
            "Settlement runs in the background (normally within ~15s). Poll "
            f"'snaplii transfer status --order-no {order_no} --wait' for the outcome."
        )
    print_json(resp)


@transfer_group.command("status")
@click.option("--order-no", required=True, help="Order number from 'transfer create'")
@click.option("--wait", is_flag=True,
              help="Poll every 3s until FINISHED / CANCELLED / FAILED (or timeout)")
@click.option("--timeout", default=120, show_default=True,
              help="Max seconds to poll with --wait")
@click.pass_context
def status_cmd(ctx, order_no, wait, timeout):
    """Get one transfer; --wait polls until it reaches a terminal state."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.transfer_get(order_no)
    if wait:
        deadline = time.monotonic() + timeout
        while (isinstance(resp, dict) and resp.get("status") not in _TERMINAL_STATUSES
               and time.monotonic() < deadline):
            time.sleep(3)
            resp = client.transfer_get(order_no)
        if isinstance(resp, dict) and resp.get("status") not in _TERMINAL_STATUSES:
            resp["wait_timed_out"] = True
            resp["next_step"] = "Still not terminal — run this command again to keep polling."
    print_json(decorate_transfer(resp))


@transfer_group.command("list")
@click.option("--status", default=None,
              help="Comma-separated status filter, e.g. PENDING,FINISHED")
@click.option("--page", default=1, show_default=True)
@click.option("--page-size", default=20, show_default=True)
@click.pass_context
def list_cmd(ctx, status, page, page_size):
    """List your transfers, newest first."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.transfer_list(status=status, page=page, page_size=page_size)
    if isinstance(resp, dict):
        for row in resp.get("data") or []:
            decorate_transfer(row)
    print_json(resp)
