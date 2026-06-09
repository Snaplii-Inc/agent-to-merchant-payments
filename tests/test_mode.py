from snaplii.security import mode


class FakeStore:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


def test_resolve_mode_elicitation_wins():
    assert mode.resolve_mode(True, False) == mode.ELICITATION
    assert mode.resolve_mode(True, True) == mode.ELICITATION


def test_resolve_mode_degraded_when_opt_in():
    assert mode.resolve_mode(False, True) == mode.DEGRADED


def test_resolve_mode_blocked_by_default():
    assert mode.resolve_mode(False, False) == mode.BLOCKED


def test_opt_in_via_env():
    assert mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "1"})
    assert mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "true"})
    assert not mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "0"})


def test_opt_in_via_config_flag():
    assert mode.insecure_opt_in_enabled(FakeStore({"allow_insecure_mode": True}), env={})
    assert not mode.insecure_opt_in_enabled(FakeStore({}), env={})
