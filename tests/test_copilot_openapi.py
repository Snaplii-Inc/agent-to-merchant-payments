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

CONNECTOR = ROOT / "copilot-connector"
PROPERTIES = json.loads((CONNECTOR / "apiProperties.json").read_text())["properties"]


def _operations():
    return [o for p in DEFINITION["paths"].values() for o in p.values()]


def test_the_certification_package_carries_the_same_definition():
    assert (CONNECTOR / "apiDefinition.swagger.json").read_text() == (ROOT / "openapidefinition.json").read_text()


def test_definition_follows_the_certification_rules():
    assert DEFINITION["swagger"] == "2.0" and DEFINITION["schemes"] == ["https"]
    info = DEFINITION["info"]
    assert len(info["title"]) <= 30
    assert not {"api", "connector"} & set(info["title"].lower().split())
    assert 30 <= len(info["description"]) <= 500
    assert "@" in info["contact"]["email"] and info["contact"]["url"].startswith("https://")
    metadata = {m["propertyName"]: m["propertyValue"] for m in DEFINITION["x-ms-connector-metadata"]}
    assert set(metadata) == {"Website", "Privacy policy", "Categories"}
    assert metadata["Website"].startswith("https://") and metadata["Privacy policy"].startswith("https://")
    assert set(metadata["Categories"].split(";")) <= {"Finance", "Commerce"}
    for op in _operations():
        assert op["summary"] and len(op["summary"]) <= 80, op["operationId"]
        assert all(c.isalnum() or c in " ()" for c in op["summary"]), op["operationId"]
        assert op["description"].endswith("."), op["operationId"]
        assert op["x-ms-visibility"], op["operationId"]
        # DefaultResponseHasSchema: only expected responses carry a schema.
        assert "schema" not in op["responses"]["default"], op["operationId"]
        assert "schema" in op["responses"]["200"], op["operationId"]
        for p in op.get("parameters", []):
            assert p.get("x-ms-summary") and p.get("description"), (op["operationId"], p["name"])
            if p.get("x-ms-visibility") == "internal" and "default" in p:
                # An internal parameter with a default is sent only when it is required.
                assert p.get("required") is True, (op["operationId"], p["name"])
            if p["in"] == "path":
                assert p.get("x-ms-url-encoding") == "single", (op["operationId"], p["name"])


def test_api_key_connection_parameter_matches_the_security_definition_and_script():
    [(name, scheme)] = DEFINITION["securityDefinitions"].items()
    assert scheme["type"] == "apiKey" and scheme["in"] == "header"
    assert set(PROPERTIES["connectionParameters"]) == {name}
    parameter = PROPERTIES["connectionParameters"][name]
    assert parameter["type"] == "securestring"
    assert parameter["uiDefinition"]["constraints"]["required"] == "true"
    script = (CONNECTOR / "script.csx").read_text()
    assert 'ApiKeyHeader = "%s"' % scheme["name"] in script
    # Every operation runs through the script, which exchanges the key for a token.
    assert PROPERTIES["scriptOperations"] == []


def test_connector_properties_and_documents():
    assert PROPERTIES["iconBrandColor"].lower() not in ("#ffffff", "#007ee5")
    assert PROPERTIES["publisher"] == PROPERTIES["stackOwner"] == "Snaplii Inc."
    readme = (CONNECTOR / "readme.md").read_text()
    for section in ("## Publisher:", "## Prerequisites", "## Supported Operations", "## Obtaining Credentials",
                    "## Known Issues and Limitations", "## Deployment Instructions"):
        assert section in readme, section
    for op in _operations():
        assert "### " + op["summary"] in readme, op["summary"]
    assert "Known issues and limitations" in (CONNECTOR / "intro.md").read_text()


def test_script_uses_only_the_namespaces_power_platform_allows():
    allowed = {
        "System", "System.Collections", "System.Collections.Generic", "System.Diagnostics", "System.IO",
        "System.IO.Compression", "System.Linq", "System.Net", "System.Net.Http", "System.Net.Http.Headers",
        "System.Net.Security", "System.Security.Authentication", "System.Security.Cryptography", "System.Text",
        "System.Text.RegularExpressions", "System.Threading", "System.Threading.Tasks", "System.Web", "System.Xml",
        "System.Xml.Linq", "System.Drawing", "System.Drawing.Drawing2D", "System.Drawing.Imaging",
        "Microsoft.Extensions.Logging", "Newtonsoft.Json", "Newtonsoft.Json.Linq",
    }
    script = (CONNECTOR / "script.csx").read_text()
    usings = {line[len("using "):].rstrip(";") for line in script.splitlines() if line.startswith("using ")}
    assert usings <= allowed
    assert "class Script : ScriptBase" in script and "new HttpClient" not in script
