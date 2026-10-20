from fastapi.testclient import TestClient

from insightly.api.main import app


def test_api_endpoints():
    with TestClient(app) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        r = c.post("/v1/ask", json={"question": "Number of products in each department"})
        assert r.status_code == 200 and r.json()["status"] == "ok"
        fb = c.post(
            "/v1/feedback",
            json={
                "thread_id": r.json()["thread_id"],
                "rating": "up",
                "question": "Number of products in each department",
                "sql": r.json()["sql"],
            },
        )
        assert fb.json() == {"stored": True}
        assert c.post("/v1/ask", json={}).status_code == 400
        with c.stream("POST", "/v1/ask/stream", json={"question": "Orders by status"}) as s:
            events = [line for line in s.iter_lines() if line.startswith("event")]
        assert events[-1] == "event: result" and "event: progress" in events
