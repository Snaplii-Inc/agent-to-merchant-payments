"""A stdio JSON-RPC server that misbehaves on request; driven by FAKE_MCP_MODE."""
import json
import os
import sys
import time

MODE = os.environ.get("FAKE_MCP_MODE", "normal")
TOOLS = int(os.environ.get("FAKE_MCP_TOOLS", "26"))
PROTOCOL = os.environ.get("FAKE_MCP_PROTOCOL", "2025-06-18")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def tool_names():
    return ["snaplii_config_show"] + ["snaplii_tool_%d" % i for i in range(1, TOOLS)]


def main():
    if MODE == "hang":
        time.sleep(60)
    if MODE == "flood":
        while True:
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"n": 1}})
    if MODE == "eof":
        return
    if MODE == "oversize":
        sys.stdout.write("{" + "a" * (1100 * 1024) + "}\n")
        sys.stdout.flush()
    if MODE == "creates_config":
        open(os.environ["SNAPLII_CONFIG_PATH"], "w").write("{}")
    sys.stderr.write("fake server stderr https://u:SENTINEL9@h\n")
    sys.stderr.flush()
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, rid = msg.get("method"), msg.get("id")
        if method == "initialize":
            if MODE == "close_stdin":
                os.close(sys.stdin.fileno())
                send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}}})
                time.sleep(2)
                return
            if MODE == "bad_json":
                sys.stdout.write("this is not json\n")
            if MODE == "wrong_id":
                send({"jsonrpc": "2.0", "id": 99, "result": {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}}})
            if MODE == "error":
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "nope"}})
                continue
            caps = {} if MODE == "no_tools_cap" else {"tools": {}}
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": PROTOCOL, "capabilities": caps,
                                                            "serverInfo": {"name": "fake", "version": "0"}}})
        elif method == "tools/list":
            names = tool_names()
            params = msg.get("params") or {}
            cursor = params.get("cursor")
            if MODE == "paginate":
                page = int(cursor or 0)
                chunk = names[page * 10:(page + 1) * 10]
                result = {"tools": [{"name": n} for n in chunk]}
                if (page + 1) * 10 < len(names):
                    result["nextCursor"] = str(page + 1)
                send({"jsonrpc": "2.0", "id": rid, "result": result})
            elif MODE == "paginate_forever":
                send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": "snaplii_tool_x"}], "nextCursor": "again"}})
            elif MODE == "empty_cursor":
                send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": n} for n in names], "nextCursor": ""}})
            else:
                send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": n} for n in names]}})
        elif method == "notifications/initialized":
            continue


if __name__ == "__main__":
    main()
