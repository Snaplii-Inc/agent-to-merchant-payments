import click

from snaplii.config_store import ConfigStore
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
    store.set("base_url", base_url)
    print_json({"status": "ok", "updated": ["base_url"]})


@config_group.command("show")
@click.pass_context
def config_show(ctx):
    """Display current configuration."""
    store: ConfigStore = ctx.obj["config_store"]
    data = store.load()
    # Hide internal bookkeeping fields (e.g. _version_check cache)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    if "api_key" in data and data["api_key"]:
        key = data["api_key"]
        data["api_key"] = key[:8] + "..." if len(key) > 8 else "***"
    if "access_token" in data and data["access_token"]:
        data["access_token"] = data["access_token"][:20] + "..."
    data["credential_storage"] = "system keychain" if store._use_keyring else "config file"
    print_json(data)


@config_group.command("clear")
@click.pass_context
def config_clear(ctx):
    """Delete configuration file."""
    store: ConfigStore = ctx.obj["config_store"]
    store.clear()
    print_json({"status": "ok", "message": "Configuration cleared"})
