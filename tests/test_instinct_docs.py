from pathlib import Path

from snaplii import auth

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def test_skill_block_routes_instinct_to_mcp():
    block = auth.render_auth_skill_block()
    section = block.split("### Instinct", 1)[1].split("### Other agents", 1)[0]
    section = " ".join(section.split())
    for phrase in ("host=instinct", "snaplii_connect", "README", "Never ask for the API key in the chat"):
        assert phrase in section


def test_readme_instinct_section_skips_cli_login_and_states_the_risk():
    section = README.split("<summary><strong>Instinct</strong></summary>", 1)[1].split("</details>", 1)[0]
    for phrase in ("mcp-server/server.py", "Skip `snaplii init`", "snaplii_connect",
                   auth.INSTINCT_VAULT_ENTRY, "INSTINCT_", "one-time `eid`", "2 minutes"):
        assert phrase in section


def test_readme_cli_login_step_points_instinct_elsewhere():
    step = README.split("#### Step 3: Connect", 1)[1].split("\n####", 1)[0]
    assert "In Instinct, skip this step" in step


def test_instinct_instruction_uses_the_readme_app_route():
    route = "More → Payment Methods → AI Payment Management → + New API Key"
    assert route in " ".join(auth.INSTINCT_AUTH_INSTRUCTION.split())
    quick_start = README.split("### 1. Get Your API Key via Snaplii App", 1)[1].split("### 2.", 1)[0]
    positions = [quick_start.index(label) for label in route.split(" → ")]
    assert positions == sorted(positions)
