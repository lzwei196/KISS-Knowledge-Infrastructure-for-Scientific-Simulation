"""A concurrent HTTP close during Stop is cancellation, not a provider failure."""
import threading

import pytest

from kiss_cli import api


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_stop_while_response_is_iterating_normalizes_closed_stream_error(monkeypatch, wire):
    entered, closed = threading.Event(), threading.Event()
    handle = api.TurnHandle()

    class Response:
        fp = object()

        def __iter__(self):
            entered.set()
            assert closed.wait(5), "fixture close did not arrive"
            # HTTPResponse can have its backing stream cleared by close while
            # the consumer is inside iteration.
            self.fp.peek()
            yield b"unreachable"

        def close(self):
            self.fp = None
            closed.set()

    monkeypatch.setattr(api, "_open", lambda *args, **kwargs: Response())
    result = {}

    def consume():
        try:
            result["reply"] = api._post("https://fixture.invalid", {}, {},
                                        provider="fixture", wire=wire, handle=handle)
        except Exception as error:
            result["error"] = error

    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    assert entered.wait(5)
    handle.stop()
    worker.join(5)
    assert not worker.is_alive()
    assert isinstance(result.get("error"), api.ToolError)
    assert str(result["error"]) == "stopped by the user"
    assert "reply" not in result and handle._response is None


def test_unrelated_attribute_error_is_not_hidden_as_cancellation(monkeypatch):
    class Response:
        def __iter__(self):
            raise AttributeError("unrelated parser bug")

        def close(self):
            pass

    monkeypatch.setattr(api, "_open", lambda *args, **kwargs: Response())
    with pytest.raises(AttributeError, match="unrelated parser bug"):
        api._post("https://fixture.invalid", {}, {}, provider="fixture", wire="openai",
                  handle=api.TurnHandle())
