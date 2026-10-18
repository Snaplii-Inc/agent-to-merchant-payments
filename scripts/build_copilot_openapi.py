#!/usr/bin/env python3
"""Build openapidefinition.json, the Copilot Studio connector definition, from openapi.yaml.

Copilot Studio connectors need OpenAPI 2.0 (Swagger). The connector exposes only the read-only
and quote operations; the token exchange is not an operation, script.csx calls it with the key
stored in the connection.

--check fails when openapidefinition.json is out of date with openapi.yaml.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "openapi.yaml"
TARGET = ROOT / "openapidefinition.json"

PATHS = ("/v2/card-brands", "/v2/card-brands/{card_brand_id}", "/v2/balance", "/v2/quote")

# Copilot Studio summaries: letters, digits and parentheses only, at most 80 characters.
SUMMARY = {
    "listCardBrands": "List gift card categories and brands",
    "getCardBrand": "Get gift card brand details and denominations",
    "getBalance": "Get Snaplii Cash balance",
    "quoteOrder": "Quote a gift card purchase",
}

PARAMETER_TITLES = {
    "channel": "Catalog channel",
    "card_brand_id": "Card brand ID",
    "showDetail": "Show card details",
    "body": "Quote request",
}


class Converter:
    """OpenAPI 3.1 schemas to Swagger 2.0 definitions, emitting only the schemas referenced."""

    def __init__(self, schemas: dict):
        self.schemas = schemas
        self.definitions: dict = {}

    def ref(self, name: str) -> dict:
        if name not in self.definitions:
            self.definitions[name] = self.schema(self.schemas[name])
        return {"$ref": "#/definitions/" + name}

    def schema(self, s):
        if not isinstance(s, dict):
            return s
        s = copy.deepcopy(s)
        if "$ref" in s:
            return self.ref(s["$ref"].rsplit("/", 1)[1])
        t = s.get("type")
        if isinstance(t, list):
            types = [x for x in t if x != "null"]
            if "null" in t:
                s["x-nullable"] = True
            # Amounts that may be a string or a number are typed as strings.
            s["type"] = "string" if "string" in types else types[0]
        if "examples" in s:
            examples = s.pop("examples")
            s["example"] = examples[0] if isinstance(examples, list) else examples
        if "anyOf" in s:
            # Swagger 2.0 has no anyOf: merge the object alternatives into one open object.
            properties = {}
            for alternative in (self.schema(a) for a in s.pop("anyOf")):
                if alternative.get("type") == "array":
                    continue
                if "$ref" in alternative:
                    alternative = self.definitions[alternative["$ref"].rsplit("/", 1)[1]]
                properties.update(alternative.get("properties", {}))
            s["type"] = "object"
            s["properties"] = properties
            s["additionalProperties"] = True
        if "properties" in s:
            s["properties"] = {k: self.schema(v) for k, v in s["properties"].items()}
        if "items" in s:
            s["items"] = self.schema(s["items"])
        return s


def parameter(p: dict) -> dict:
    q = {"name": p["name"], "in": p["in"], "type": p["schema"]["type"]}
    if p.get("required"):
        q["required"] = True
    if "description" in p:
        q["description"] = p["description"]
    if "default" in p["schema"]:
        q["default"] = p["schema"]["default"]
    return q


def build(spec: dict) -> dict:
    convert = Converter(spec["components"]["schemas"])
    error = spec["components"]["responses"]["GatewayError"]
    paths = {}
    for path in PATHS:
        paths[path] = {}
        for method, o in spec["paths"][path].items():
            op = {
                "operationId": o["operationId"],
                "summary": SUMMARY[o["operationId"]],
                "description": o["description"],
                "tags": o.get("tags", []),
                "produces": ["application/json", "text/plain"],
            }
            params = [parameter(p) for p in o.get("parameters", [])]
            if "requestBody" in o:
                op["consumes"] = ["application/json"]
                params.append({"name": "body", "in": "body", "required": True,
                               "schema": convert.schema(o["requestBody"]["content"]["application/json"]["schema"])})
            if params:
                op["parameters"] = params
            op["responses"] = {
                "200": {"description": "Gateway response. Check rspMsgCd even when the HTTP status is 200.",
                        "schema": convert.schema(o["responses"]["200"]["content"]["application/json"]["schema"])},
                "default": {"description": error["description"],
                            "schema": convert.schema(error["content"]["application/json"]["schema"])},
            }
            paths[path][method] = op
    defs = convert.definitions

    # The connector quotes gift cards only; fixed fields carry defaults and stay hidden.
    order_info = defs["OrderInfo"]["properties"]
    order_info["orderType"] = {"type": "string", "enum": ["GIFT_CARD"], "default": "GIFT_CARD",
                               "x-ms-visibility": "internal"}
    order_info["businessChannel"]["default"] = "APP"
    order_info["businessChannel"]["x-ms-visibility"] = "internal"
    gift_order = defs["OrderContext"]["properties"]["giftOrder"]
    gift_order["default"] = "false"
    gift_order["x-ms-visibility"] = "internal"
    item = defs["OrderItem"]["properties"]
    item["itemId"]["description"] = (
        "The gift card ID, exactly {cardBrandId}-{cardTemplateId}: the brand's cardBrandId, one hyphen, "
        "and the chosen card's cardTemplateId, both copied verbatim from the brand details. "
        "Never send one ID alone, a card from another brand, or a guessed ID.")
    item["price"]["description"] = (
        "Decimal amount as a string. A FIXED card accepts exactly its priceStart; "
        "a VARIABLE card accepts priceStart to priceEnd.")
    payment = defs["PaymentContext"]["properties"]
    payment["specifiedPrimaryPaymentMethod"]["x-ms-visibility"] = "internal"
    paths["/v2/quote"]["post"]["description"] = (
        "Quote a gift card purchase. Before quoting, read the brand details and confirm the card ID and "
        "amount match one of its denominations. A positive primaryPayAmount means Snaplii Cash does not "
        "fully cover the order. Nothing is charged by a quote.")
    paths["/v2/card-brands/{card_brand_id}"]["get"]["description"] = (
        "Returns the brand's cards and their denominations. FIXED requires the exact priceStart; "
        "VARIABLE requires an amount between priceStart and priceEnd.")

    # Visibility and display names.
    for operations in paths.values():
        for op in operations.values():
            op["x-ms-visibility"] = "important"
            for p in op.get("parameters", []):
                p.setdefault("x-ms-visibility", "important")
                p["x-ms-summary"] = PARAMETER_TITLES[p["name"]]
    detail = {p["name"]: p for p in paths["/v2/card-brands/{card_brand_id}"]["get"]["parameters"]}
    detail["showDetail"]["x-ms-visibility"] = "internal"
    channel = paths["/v2/card-brands"]["get"]["parameters"][0]
    channel["description"] = "Catalog channel. Always HOME_PAGE: the brands shown on the Snaplii app home page."
    channel["enum"] = ["HOME_PAGE"]
    channel["default"] = "HOME_PAGE"
    channel["x-ms-visibility"] = "internal"
    paths["/v2/quote"]["post"]["parameters"][0]["description"] = "The gift card order to quote."
    for name in ("voucherOption", "cashbackOption", "specifiedVoucher"):
        payment[name]["x-ms-visibility"] = "advanced"

    # The gateway returns the category list as an array.
    defs["CatalogResponse"] = {"description": "Categories with their brands, as an array.",
                               "type": "array", "items": {"$ref": "#/definitions/GatewayObject"}}

    return {
        "swagger": "2.0",
        "info": {
            "title": "Snaplii",
            "description": ("Browse Snaplii gift card brands, check your Snaplii Cash balance, and get a "
                            "price quote before buying. Spending comes only from your prepaid Snaplii Cash."),
            "version": spec["info"]["version"],
        },
        "host": spec["servers"][0]["url"].replace("https://", ""),
        "basePath": "/",
        "schemes": ["https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": paths,
        "definitions": defs,
        "securityDefinitions": {
            "api_key": {"type": "apiKey", "in": "header", "name": "X-Snaplii-Api-Key"}
        },
        "security": [{"api_key": []}],
    }


def render(spec: dict) -> str:
    return json.dumps(build(spec), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only drift check")
    args = parser.parse_args(argv)
    content = render(yaml.safe_load(SOURCE.read_text(encoding="utf-8")))
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else None
    if args.check:
        if current != content:
            print(f"{TARGET.name} is out of date; run scripts/{Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"{TARGET.name} is up to date.")
        return 0
    TARGET.write_text(content, encoding="utf-8")
    print(f"Wrote {TARGET.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
