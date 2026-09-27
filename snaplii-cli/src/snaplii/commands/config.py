import click

from snaplii.config_store import ConfigStore
from snaplii.auth import DEFAULT_ORIGIN, normalize_base_url
from snaplii.output import print_json


@click.group("config")
@click.pass_context
def config_group(ctx):
    """Manage CLI configuration (base URL, credentials)."""
    pass


@config_group.command("set")
@click.option("--base-url", required=True, help="Gateway base URL (e.g. http://localhost:8080)")
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
    print_json(store.auth_status(origin=origin))


@config_group.command("clear")
@click.pass_context
def config_clear(ctx):
    """Delete configuration file."""
    store: ConfigStore = ctx.obj["config_store"]
    store.clear()
    print_json({"status": "ok", "message": "Configuration cleared"})
