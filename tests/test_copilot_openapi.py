"""openapidefinition.json, the Copilot Studio connector definition, is generated from openapi.yaml."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = json.loads((ROOT / "openapidefinition.json").read_text())


def test_definition_exposes_only_read_and_quote_operations():
    operations = {o["operationId"] for p in DEFINITION["paths"].values() for o in p.values()}
    assert operations == {"listCardBrands", "getCardBrand", "getBalance", "quoteOrder"}
    assert "/v2/auth/token" not in DEFINITION["paths"]
    assert DEFINITION["host"] == "aipayment.snaplii.com"
