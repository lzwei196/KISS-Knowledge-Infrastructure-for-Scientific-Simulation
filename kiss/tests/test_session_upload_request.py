"""Exercise the real upload handler without a server or provider."""
import io
import json

import pytest

from kiss_cli import gui, sessions, setup


@pytest.mark.parametrize("kind", ["permission", "choice", "download"])
def test_upload_does_not_answer_or_resume_a_pending_request(tmp_path, kind):
    session = sessions.create(tmp_path)
    project = sessions.project_path(tmp_path, session)
    request = setup.request_user(project, {
        "kind": kind, "title": "An unrelated request", "message": "Wait for explicit input",
    })
    for filename in ("plan.json", "data-inventory.json", "approval.json"):
        (project / "runs" / filename).write_text(json.dumps({"untouched": filename}))
    tracked = [project / setup.REQUEST_FILE, *(project / "runs").glob("*.json")]
    before = {p: p.read_bytes() for p in tracked}
    responses = []
    handler = object.__new__(gui.Handler)
    handler.workroot = tmp_path
    handler.path = f"/api/session/{session['id']}/upload?name=weather%20data.csv&item=forcing"
    handler.headers = {"Content-Length": "4"}
    handler.rfile = io.BytesIO(b"rain")
    handler._browser_write_allowed = lambda: (True, "")
    handler._json = lambda payload, status=200: responses.append((payload, status))
    handler.do_POST()
    payload, status = responses[0]
    assert status == 200 and payload["ok"]
    assert payload["relative_path"] == "inputs/user/forcing/weather_data.csv"
    assert (project / payload["relative_path"]).read_bytes() == b"rain"
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert setup.request(project)["status"] == "waiting"
    assert setup.request(project)["id"] == request["id"]
