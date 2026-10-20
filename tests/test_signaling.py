from fastapi.testclient import TestClient

from app.main import app


def test_websocket_join_and_chat():
    with TestClient(app) as client:
        # create room
        r = client.post("/api/rooms", json={"host_name": "Alice"})
        code = r.json()["code"]
        with client.websocket_connect(f"/ws/{code}?name=Alice") as ws1:
            ws1.receive_json()  # joined
            with client.websocket_connect(f"/ws/{code}?name=Bob") as ws2:
                ws2.receive_json()  # joined
                # host receives join
                msg = ws1.receive_json()
                assert msg["type"] == "join" and msg["name"] == "Bob"
                # chat roundtrip
                ws1.send_json({"type": "chat", "body": "hello"})
                chat = ws2.receive_json()
                assert chat["type"] == "chat" and chat["body"] == "hello" and chat["sender"] == "Alice"