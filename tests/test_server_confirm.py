import asyncio

import server

from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    UrlElicitationCapability,
)


class FakeElicitResult:
    def __init__(self, action, content=None):
        self.action = action
        self.content = content or {}


class FakeSession:
    def __init__(self, result):
        self._result = result
        self.last_message = None
        self.last_schema = None

    async def elicit_form(self, message, requestedSchema):
        self.last_message = message
        self.last_schema = requestedSchema
        return self._result


def test_confirm_accept_returns_true():
    session = FakeSession(FakeElicitResult("accept", {"confirm": True}))
    canonical = {"brand": "DoorDash", "you_pay": "46.00", "order_amount": "50.00"}
    approved = asyncio.run(server._confirm_via_elicitation(session, canonical))
    assert approved is True
    assert "46.00" in session.last_message  # server-built, from canonical fields


def test_confirm_decline_returns_false():
    session = FakeSession(FakeElicitResult("decline"))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False


def test_confirm_accept_but_unchecked_returns_false():
    session = FakeSession(FakeElicitResult("accept", {"confirm": False}))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False


def test_caps_support_form_true_when_form_present():
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(form=FormElicitationCapability())
    )
    assert server._caps_support_form(caps) is True


def test_caps_support_form_false_for_url_only():
    # url-only elicitation: elicit_form would fail, so this must NOT count.
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(url=UrlElicitationCapability())
    )
    assert caps.elicitation.form is None
    assert server._caps_support_form(caps) is False


def test_caps_support_form_false_when_elicitation_absent():
    assert server._caps_support_form(ClientCapabilities()) is False
    assert server._caps_support_form(None) is False
