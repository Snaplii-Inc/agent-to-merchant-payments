"""Synthetic external helper for subprocess tests; never packaged or deployed."""


class DynamicCredentialError(Exception):
    pass


def add_surrogate_to_request(request, provider, *, allowed_hosts):
    assert provider == "custom.snaplii"
    assert allowed_hosts == ("aipayment.snaplii.com",)
    request.add_header("Authorization", "Bearer hsurr:synthetic-test-only")
