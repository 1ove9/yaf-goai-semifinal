"""Agent-loop test against a faked DeepSeek endpoint.

An in-process ASGI app plays DeepSeek: round 1 answers with a streamed
tool call, round 2 (after the tool result is fed back) answers with
text. Verifies the SSE frame protocol end-to-end without network or
API key.
"""

import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import yaf_api.routers.chat as chat_module

TOOL_ARGS = {"length_mm": 500, "f_min_ghz": 0.1, "f_max_ghz": 0.5}


def _sse_lines(*payloads: object) -> str:
    return "".join(f"data: {json.dumps(p)}\n\n" for p in payloads) + "data: [DONE]\n\n"


def _fake_deepseek() -> FastAPI:
    app = FastAPI()

    @app.post("/chat/completions")
    async def completions(request: Request) -> StreamingResponse:
        body = await request.json()
        assert body["stream"] is True
        has_tool_result = any(m.get("role") == "tool" for m in body["messages"])
        if not has_tool_result:
            # round 1: request a tool call, arguments split across frames
            args = json.dumps(TOOL_ARGS)
            frames = _sse_lines(
                {"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "id": "call_1",
                    "function": {"name": "simulate_dipole",
                                 "arguments": args[:10]},
                }]}, "finish_reason": None}]},
                {"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": args[10:]},
                }]}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            )
        else:
            # round 2: the tool result came back — answer in text
            tool_msg = next(m for m in body["messages"] if m["role"] == "tool")
            got = json.loads(tool_msg["content"])
            frames = _sse_lines(
                {"choices": [{"delta": {
                    "content": f"Resonance {got['resonance_ghz']} GHz."
                }, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            )
        return StreamingResponse(frames, media_type="text/event-stream")

    return app


@pytest.fixture
def client(monkeypatch):
    fake = _fake_deepseek()

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, **kw):  # noqa: ANN003
            kw["transport"] = httpx.ASGITransport(app=fake)
            super().__init__(**kw)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(chat_module, "DEEPSEEK_BASE_URL", "http://fake-deepseek")
    monkeypatch.setattr(chat_module.httpx, "AsyncClient", _PatchedClient)

    async def fake_execute(name, args):
        assert name == "simulate_dipole"
        assert args == TOOL_ARGS
        return {"solver_mode": "subprocess", "resonance_ghz": 0.28}

    async def fake_availability():
        return {"openems": True, "nec2": False}

    monkeypatch.setattr(chat_module, "execute_tool", fake_execute)
    monkeypatch.setattr(chat_module, "solver_availability", fake_availability)

    app = FastAPI()
    app.include_router(chat_module.router)
    return TestClient(app)


def _frames(text: str) -> list[dict]:
    out = []
    for line in text.split("\n\n"):
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[5:]))
    return out


class TestAgentLoop:
    def test_tool_round_trip(self, client):
        resp = client.post("/api/v1/chat", json={
            "messages": [{"role": "user", "content": "simulate a 0.5 m dipole"}],
        })
        assert resp.status_code == 200
        frames = _frames(resp.text)

        tool_frames = [f["tool"] for f in frames if "tool" in f]
        assert tool_frames == [
            {"name": "simulate_dipole", "status": "running"},
            {"name": "simulate_dipole", "status": "ok"},
        ]
        text = "".join(f["delta"] for f in frames if "delta" in f)
        assert "Resonance 0.28 GHz" in text
        assert frames[-1] == {"done": True}
        assert not any("error" in f for f in frames)

    def test_missing_key_is_503(self, client, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY")
        resp = client.post("/api/v1/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 503
