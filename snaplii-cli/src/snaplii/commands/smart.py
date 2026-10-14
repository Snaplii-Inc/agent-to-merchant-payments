import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.group("smart")
@click.pass_context
def smart_group(ctx):
    """Smart features: cashback calculator, dashboard."""
    pass


@smart_group.command("cashback")
@click.option("--brand-id", required=True, help="Card brand ID")
@click.option("--amount", required=True, type=float, help="Purchase amount in dollars")
@click.pass_context
def cashback_cmd(ctx, brand_id, amount):
    """Calculate cashback savings for a specific brand and amount."""
    client: GatewayClient = ctx.obj["client"]
    detail = client.get_card_brand_by_id(brand_id)
    # Gateway returns detail directly; prod wraps in "data"
    brand_data = detail.get("data", detail) if isinstance(detail.get("data"), dict) else detail
    cards = brand_data.get("cards", [])

    best_match = None
    for c in cards:
        fv = c.get("faceValueRules", {})
        if fv.get("type") == "FIXED" and float(fv.get("priceStart", 0)) == amount:
            best_match = c
            break
        elif fv.get("type") == "VARIABLE":
            start = float(fv.get("priceStart", 0))
            end = float(fv.get("priceEnd", 0))
            if start <= amount <= end:
                best_match = c

    if best_match:
        discount_pct = float(best_match.get("discount", 0) or 0)
        savings = amount * discount_pct / 100
        print_json({
            "brand_id": brand_id,
            "amount": amount,
            "cashback_percent": f"{discount_pct}%",
            "you_save": f"${savings:.2f}",
            "effective_cost": f"${amount - savings:.2f}",
            "item_id": f"{brand_id}-{best_match.get('cardTemplateId', '')}",
        })
    else:
        print_json({"error": f"No matching denomination for ${amount}"})


@smart_group.command("dashboard")
@click.pass_context
def dashboard_cmd(ctx):
    """Show a summary dashboard of all your gift cards."""
    client: GatewayClient = ctx.obj["client"]
    cards = client.list_all_user_cards()

    total_value = 0
    brands = {}
    for card in cards:
        face_value = float(card.get("faceValue", 0))
        total_value += face_value
        brand_id = card.get("cardBrandId", "unknown")
        brand_name = card.get("cardTemplate", {}).get("desc", {}).get("name", brand_id)
        if brands.get(brand_id):
            brands[brand_id]["count"] += 1
            brands[brand_id]["total"] += face_value
        else:
            brands[brand_id] = {"name": brand_name, "count": 1, "total": face_value}

    print_json({
        "total_cards": len(cards),
        "total_face_value": f"${total_value:.2f}",
        "brands": [
            {"brand": info["name"], "cards": info["count"], "total_value": f"${info['total']:.2f}"}
            for info in sorted(brands.values(), key=lambda x: x["total"], reverse=True)
        ],
    })
