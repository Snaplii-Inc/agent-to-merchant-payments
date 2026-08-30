import subprocess
import sys
from importlib.metadata import version as pkg_version

import click

from snaplii.client import GatewayClient
from snaplii.commands.balance import balance_cmd
from snaplii.commands.billpay import billpay_group
from snaplii.commands.browse import browse_group
from snaplii.commands.config import config_group
from snaplii.commands.giftcard import giftcard_group
from snaplii.commands.init import init_cmd
from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.quote import quote_cmd
from snaplii.commands.smart import smart_group
from snaplii.commands.transfer import transfer_group
from snaplii.config_store import ConfigStore
from snaplii.exceptions import SnapliiCliError
from snaplii.output import print_error, print_json
from snaplii.version_check import check_for_update

_VERSION = pkg_version("snaplii-cli")
_DEFAULT_BASE_URL = "https://aipayment.snaplii.com"


@click.group()
@click.version_option(_VERSION, prog_name="snaplii")
@click.option(
    "--base-url",
    envvar="SNAPLII_BASE_URL",
    default=None,
    help="Gateway base URL (overrides config)",
)
@click.pass_context
def main(ctx, base_url):
    """Snaplii Agent Gateway CLI.

    Browse gift card brands, purchase cards, pay bills, and preview
    savings — all from your Snaplii Cash balance.
    """
    ctx.ensure_object(dict)
    store = ConfigStore()
    resolved_url = base_url or store.get("base_url", _DEFAULT_BASE_URL)
    ctx.obj["config_store"] = store
    ctx.obj["client"] = GatewayClient(resolved_url, store)

    # Daily, fail-silent check for a newer release. Notice goes to stderr so it
    # never pollutes the JSON on stdout that agents parse.
    if ctx.invoked_subcommand != "update":
        update = check_for_update(store)
        if update:
            from snaplii.version_check import is_editable_install
            how = ("git pull in your checkout" if is_editable_install("snaplii-cli")
                   else "snaplii update")
            click.echo(
                f"[snaplii] Update available: {update['current']} -> {update['latest']}. Run '{how}'.",
                err=True,
            )


main.add_command(init_cmd)
main.add_command(balance_cmd)
main.add_command(browse_group)
main.add_command(giftcard_group)
main.add_command(purchase_cmd)
main.add_command(quote_cmd)
main.add_command(smart_group)
main.add_command(billpay_group)
main.add_command(transfer_group)
main.add_command(config_group)


@main.command("update")
@click.pass_context
def update_cmd(ctx):
    """Check for and install the latest snaplii-cli from PyPI."""
    store = ctx.obj["config_store"]
    # Force a fresh check by clearing the daily cache.
    store.set("_version_check_snaplii_cli", {})
    update = check_for_update(store)
    if not update:
        print_json({"status": "up-to-date", "version": _VERSION})
        return
    from snaplii.version_check import is_editable_install
    if is_editable_install("snaplii-cli"):
        # Editable / git-clone install: pip -U would clobber the checkout. Tell the
        # user to git pull instead.
        print_json({
            "status": "manual-update-required",
            "from": update["current"], "to": update["latest"],
            "action": "This is an editable/clone install — run 'git pull' in your snaplii repo, then 'pip install -e .' if dependencies changed.",
        })
        return
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "snaplii-cli"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print_json({"status": "updated", "from": update["current"], "to": update["latest"]})
    else:
        print_error({
            "error": "Update failed. Try manually: pip install -U snaplii-cli (or pipx upgrade snaplii-cli)",
            "detail": (result.stderr or "").strip()[-300:],
        })
        sys.exit(1)


@main.command("help")
@click.pass_context
def help_cmd(ctx):
    """Show full CLI documentation."""
    click.echo(ctx.parent.get_help())


def _cli():
    try:
        main(standalone_mode=False)
    except click.exceptions.Exit:
        pass
    except click.UsageError as e:
        print_error({"error": "Usage error", "message": str(e)})
        sys.exit(1)
    except SnapliiCliError as e:
        print_error(e.to_dict())
        sys.exit(1)
