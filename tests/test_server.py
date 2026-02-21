import json
from pathlib import Path
import asyncio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / 'project'))

import server as server_module  # noqa: E402
from server import app, BASE_DIR  # noqa: E402

# Configure client to not auto-follow redirects so we can assert redirect responses
client = TestClient(app, follow_redirects=False)


def test_root_serves_login_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<title>" in resp.text or "html" in resp.text.lower()


def test_login_invalid_credentials():
    resp = client.post("/login", data={"username": "nobody", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["message"].lower().startswith("invalid")


def test_login_success_redirects_to_index_and_sets_session(tmp_path, monkeypatch):
    with client:
        resp = client.post("/login", data={"username": "vamsi", "password": "1234"})
        assert resp.status_code in (302, 303)
        assert resp.headers.get("location") == "/index"
        follow = client.get("/index")
        assert follow.status_code == 200
        assert "vamsi" in follow.text


def test_index_requires_authentication():
    unauth_client = TestClient(app, follow_redirects=False)
    with unauth_client:
        resp = unauth_client.get("/index")
        assert resp.status_code in (302, 303, 307)
        assert resp.headers.get("location") == "/"


def test_chat_requires_authentication():
    unauth_client = TestClient(app, follow_redirects=False)
    with unauth_client:
        resp = unauth_client.get("/chat")
        assert resp.status_code in (302, 303, 307)
        assert resp.headers.get("location") == "/"


def test_messages_endpoint_returns_json_list():
    resp = client.get("/messages")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_chat_page_excludes_current_user(monkeypatch):
    with client:
        login = client.post("/login", data={"username": "krishna", "password": "abcd"})
        assert login.status_code in (302, 303)
        resp = client.get("/chat")
        assert resp.status_code == 200
        # Current user should not be in the selectable chatusers list; list renders as <span>{{ person }}</span>
        assert "<span>krishna</span>" not in resp.text


def test_logout_clears_session_and_redirects():
    with client:
        client.post("/login", data={"username": "vamsi", "password": "1234"})
        assert client.get("/index").status_code == 200
        out = client.get("/logout")
        assert out.status_code in (302, 303)
        assert out.headers.get("location") == "/"
        redirected = client.get("/index")
        assert redirected.status_code in (302, 303, 307)


@pytest.fixture()
def temp_messages_file(tmp_path, monkeypatch):
    # Prepare a temp messages.json and chdir so relative path resolves
    tmp = tmp_path / 'messages.json'
    tmp.write_text("[]", encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    return tmp


@pytest.fixture()
def async_persist_save(monkeypatch, temp_messages_file):
    async def async_save(data):
        path = Path("messages.json")
        try:
            arr = json.loads(path.read_text(encoding='utf-8') or "[]")
        except Exception:
            arr = []
        arr.append(data)
        path.write_text(json.dumps(arr), encoding='utf-8')
    # Patch server.save_message with async version so `await save_message(...)` works
    monkeypatch.setattr(server_module, "save_message", async_save)
    return temp_messages_file


def test_websocket_broadcasts_messages_and_persists(async_persist_save):
    # Use two authenticated websocket connections to verify broadcast to group
    with client:
        login = client.post("/login", data={"username": "vamsi", "password": "1234"})
        assert login.status_code in (302, 303)
        with client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
            payload = {"username": "vamsi", "message": "hello", "to": "FamilyChat"}
            ws1.send_json(payload)
            # Both should receive the message
            r1 = ws1.receive_json()
            r2 = ws2.receive_json()
            assert r1 == payload
            assert r2 == payload

    data = json.loads(Path("messages.json").read_text(encoding='utf-8'))
    assert any(item.get("message") == "hello" and item.get("to") == "FamilyChat" for item in data)


def test_websocket_handles_missing_username_and_still_broadcasts(async_persist_save):
    with client:
        login = client.post("/login", data={"username": "vamsi", "password": "1234"})
        assert login.status_code in (302, 303)
        with client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
            payload = {"message": "no user", "to": "FamilyChat"}
            ws1.send_json(payload)
            r1 = ws1.receive_json()
            r2 = ws2.receive_json()
            # Even without 'username' field, broadcast should echo the payload
            assert r1 == payload
            assert r2 == payload

    data = json.loads(Path("messages.json").read_text(encoding='utf-8'))
    assert any(item.get("message") == "no user" and item.get("to") == "FamilyChat" for item in data)


#

#
