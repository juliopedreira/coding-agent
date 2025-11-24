import pytest

from lincona.openai_client.transport import HttpResponsesTransport


def test_transport_requires_api_key() -> None:
    with pytest.raises(ValueError):
        HttpResponsesTransport(api_key=" ")
