import click
from importlib.metadata import version

from snaplii import auth
from snaplii.config_store import ConfigStore
from snaplii.auth import DEFAULT_ORIGIN, normalize_base_url
from snaplii.exceptions import ConfigError
from snaplii.output import print_json


@click.group("config")
@click.pass_context
def config_group(ctx):
    """Manage CLI configuration (base URL, credentials)."""
    pass


@config_group.command("set")
@click.option("--base-url", required=True, help="Gateway base URL (e.g. https://aipay.stage.snaplii.com)")
@click.pass_context
def config_set(ctx, base_url):
    """Set the gateway base URL."""
    store: ConfigStore = ctx.obj["config_store"]
    store.set("base_url", normalize_base_url(base_url))
    print_json({"status": "ok", "updated": ["base_url"]})


@config_group.command("show")
@click.pass_context
def config_show(ctx):
    """Display current configuration."""
    store: ConfigStore = ctx.obj["config_store"]
    origin = ctx.obj["base_url"] or store.get("base_url", DEFAULT_ORIGIN)
    status = store.auth_status(origin=origin)
    # The skill defers to this text, so it is the only copy of the instruction.
    if status.get("host") == "muse" and auth.muse_app_outdated():
        status["muse_app_update"] = (
            "Tell the user once per conversation that their Muse app is outdated and suggest "
            "updating it from the App Store or Google Play, without mentioning version numbers. "
            "This does not change any other step.")
    print_json(status)


@config_group.command("doctor")
@click.pass_context
def config_doctor(ctx):
    """Show safe runtime/storage diagnostics without logging in or reading a key."""
    store: ConfigStore = ctx.obj["config_store"]
    muse = auth.muse_environment_status()
    instinct = auth.instinct_environment_status()
    try:
        origin = ctx.obj["base_url"] or store.get("base_url", DEFAULT_ORIGIN)
        status = store.auth_status(origin=origin)
    except ConfigError:
        status = {"has_valid_token": False, "auth_state": "session_cache_failed",
                  "reason_code": "configuration_unreadable_or_invalid",
                  "host": "muse" if muse["detected"] else "instinct" if instinct["detected"] else "unknown",
                  # Do not reread broken configuration or guess its session storage.
                  "credential_storage": "unknown", "auth_method": None, "base_url": None,
                  "next_action": {"type": "stop", "reason": "session_cache_failed"}}
    print_json({"version": version("snaplii-cli"), "muse": muse, "instinct": instinct,
                "authentication": status})


@config_group.command("clear")
@click.pass_context
def config_clear(ctx):
    """Delete configuration file."""
    store: ConfigStore = ctx.obj["config_store"]
    store.clear()
    print_json({"status": "ok", "message": "Configuration cleared"})
