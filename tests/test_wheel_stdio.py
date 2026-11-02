"""The snaplii-mcp wheel, as built, serves over stdio the same surface as the source server.py."""
import asyncio
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import server

ROOT = Path(__file__).resolve().parents[1]


async def _serve(wheel_dir: Path, home: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("INSTINCT_")}
    env.update({"HOME": str(home), "PYTHONPATH": os.pathsep.join([str(wheel_dir), str(ROOT / "snaplii-cli" / "src")])})
    params = StdioServerParameters(command=sys.executable, env=env, args=[
        "-c", "import server, sys; assert server.__file__.startswith(sys.argv[1]), server.__file__; server.main_sync()",
        str(wheel_dir)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            prompts = await session.list_prompts()
            resources = await session.list_resources()
    return init, tools.tools, prompts.prompts, resources.resources


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")
def test_built_wheel_serves_the_source_tools_over_stdio(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist"), str(ROOT / "mcp-server")],
                   check=True, capture_output=True)
    [wheel] = (tmp_path / "dist").glob("snaplii_mcp-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert [n for n in archive.namelist() if not n.split("/")[0].endswith(".dist-info")] == ["server.py"]
        archive.extractall(tmp_path / "wheel")
    assert (tmp_path / "wheel" / "server.py").read_bytes() == (ROOT / "mcp-server" / "server.py").read_bytes()
    (tmp_path / "home").mkdir()

    init, tools, prompts, resources = asyncio.run(_serve(tmp_path / "wheel", tmp_path / "home"))

    assert init.instructions == server._SERVER_INSTRUCTIONS
    source = asyncio.run(server.list_tools())
    assert [t.model_dump(by_alias=True, exclude_none=True) for t in tools] == \
        [t.model_dump(by_alias=True, exclude_none=True) for t in source]
    assert [p.name for p in prompts] == [p.name for p in asyncio.run(server.list_prompts())]
    assert [str(r.uri) for r in resources] == [str(r.uri) for r in asyncio.run(server.list_resources())]
    billpay = next(t for t in tools if t.name == "snaplii_billpay_pay")
    assert "bill payments are not subject to it" in billpay.description
