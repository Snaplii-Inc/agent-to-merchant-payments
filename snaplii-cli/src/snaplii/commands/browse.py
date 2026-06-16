import click

from snaplii.client import GatewayClient, summarize_denominations
from snaplii.output import print_json


@click.group("browse")
@click.pass_context
def browse_group(ctx):
    """Browse available gift card brands and categories."""
    pass


@browse_group.command("tags")
@click.option("--channel", default="HOME_PAGE", help="Channel: HOME_PAGE or SEND_GIFT")
@click.option("--prov", default=None,
              help="Province/state code (e.g. ON, QC, BC, NY). Card availability can "
                   "vary by province. Optional — omit to list all cards available for "
                   "your account's country (the country is fixed by your account).")
@click.pass_context
def browse_tags(ctx, channel, prov):
    """List all card categories (tags) with brand summaries."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.get_all_card_tags(channel=channel, location_prov=prov)
    print_json(resp)


@browse_group.command("brand")
@click.option("--id", "brand_id", required=True, help="Card brand ID (e.g. CB0000000000135)")
@click.pass_context
def browse_brand(ctx, brand_id):
    """Get card brand details including available denominations."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.get_card_brand_by_id(brand_id)
    denoms = summarize_denominations(resp)
    if denoms and isinstance(resp, dict):
        resp = {**resp, "denominations": denoms}
    print_json(resp)
