def test_snaplii_imports():
    import snaplii  # noqa: F401


def test_server_imports():
    import server  # noqa: F401
    assert hasattr(server, "call_tool")
