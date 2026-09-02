# ============================================================
# REFERENCE
#   仿造来源：OpenAI-compatible chat completions 代理 + tool-calling
#             智能体循环（DeepSeek 兼容 OpenAI function calling 协议）
#   理由：前端不应持有 API key；由后端代理 DeepSeek 并以 SSE 流式转发。
#   关键设计点：
#     - POST /api/v1/chat 接收 {messages[], model?, temperature?}
#     - 服务端从 DEEPSEEK_API_KEY 环境变量读取密钥（绝不下发前端）
#     - 智能体循环：流式转发文本 delta；累积 tool_calls 增量，
#       finish_reason=="tool_calls" 时本地执行真实仿真工具
#       （chat_tools.py），结果以 role=tool 回喂，最多 5 轮
#     - SSE 帧协议：{"delta"} 文本、{"tool":{name,status,error?}}
#       工具活动、{"done"}、{"error"}
#     - 流开始后出错时以 data: {"error": ...} 帧上报（HTTP 头已发出，
#       无法再改状态码）
# ============================================================

"""
Chat router — DeepSeek-backed assistant agent with real-solver tools.

POST /api/v1/chat    Stream an agentic chat completion (SSE)
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from yaf_api.routers.chat_tools import (
    TOOLS_SCHEMA,
    execute_tool,
    solver_availability,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

#: per-message budget: each round costs one growing-context LLM call
#: plus up to minutes of real FDTD — the cap is the runaway fuse, and a
#: follow-up message always gets a fresh budget
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = (
    "You are the YAF (YuanXu Antenna Forge) assistant, an expert in antenna "
    "engineering and RF design: dipoles, patches, arrays, S-parameters, "
    "impedance matching, radiation patterns, NEC2/MoM and openEMS/FDTD "
    "solvers, and inverse design. Answer in the language the user writes in. "
    "Be precise with formulas and units; say so plainly when unsure.\n\n"
    "You can RUN REAL electromagnetic simulations through your tools "
    "(simulate_patch, simulate_dipole, run_inverse_design). Use them when "
    "the user asks to design, simulate, verify or tune an antenna — a real "
    "FDTD/MoM result always beats a formula estimate. Simulations take "
    "30 s – 3 min; tell the user before starting one.\n\n"
    "HONESTY RULES (non-negotiable):\n"
    "- Only cite numeric results that a tool actually returned.\n"
    "- Always check solver_mode/oracle_mode in tool results: "
    "'subprocess'/'native' means real physics; 'fallback_analytical' means "
    "an analytical estimate — you MUST tell the user which one they got.\n"
    "- If a tool returns an error, explain it honestly and suggest what to "
    "try instead. Never fabricate a simulation result."
)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.7, ge=0, le=2)


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def merge_tool_call_delta(
    pending: dict[int, dict[str, str]], deltas: list[dict[str, Any]]
) -> None:
    """Fold streamed tool_calls deltas into complete calls (by index).

    The OpenAI stream protocol sends id/name once and the JSON arguments
    in fragments; each fragment carries the call's list index.
    """
    for tc in deltas:
        entry = pending.setdefault(
            int(tc.get("index", 0)), {"id": "", "name": "", "arguments": ""}
        )
        if tc.get("id"):
            entry["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            entry["name"] = fn["name"]
        entry["arguments"] += fn.get("arguments") or ""


@router.post("")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Stream an agentic chat completion from DeepSeek as SSE.

    Text arrives as ``data: {"delta": "..."}``; tool activity as
    ``data: {"tool": {"name", "status"}}``; the stream ends with
    ``data: {"done": true}``. Errors surface as ``data: {"error": "..."}``.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "DEEPSEEK_API_KEY is not set on the server. "
                "Set it in the environment before starting `yaf serve`."
            ),
        )

    solvers = await solver_availability()
    system = SYSTEM_PROMPT + (
        f"\n\nReal solvers available on this host right now: "
        f"openEMS={'yes' if solvers['openems'] else 'NO'}, "
        f"NEC2={'yes' if solvers['nec2'] else 'NO'}. "
        "If none is available, tool results will be analytical fallbacks."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system}
    ] + [m.model_dump() for m in req.messages]
    headers = {"Authorization": f"Bearer {api_key}"}

    async def stream() -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(180, connect=15)
            ) as client:
                for _round in range(MAX_TOOL_ROUNDS + 1):
                    payload = {
                        "model": req.model,
                        "messages": messages,
                        "temperature": req.temperature,
                        "stream": True,
                        # last round: no tools → force a final text answer
                        **(
                            {"tools": TOOLS_SCHEMA}
                            if _round < MAX_TOOL_ROUNDS
                            else {}
                        ),
                    }
                    content_parts: list[str] = []
                    pending: dict[int, dict[str, str]] = {}
                    finish_reason: str | None = None

                    async with client.stream(
                        "POST",
                        f"{DEEPSEEK_BASE_URL}/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode(
                                "utf-8", errors="replace"
                            )
                            yield _sse({
                                "error": (
                                    f"DeepSeek API HTTP {resp.status_code}: "
                                    f"{body[:500]}"
                                )
                            })
                            return
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            chunk = line[5:].strip()
                            if chunk == "[DONE]":
                                break
                            try:
                                choice = json.loads(chunk)["choices"][0]
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
                            finish_reason = (
                                choice.get("finish_reason") or finish_reason
                            )
                            delta = choice.get("delta") or {}
                            if delta.get("content"):
                                content_parts.append(delta["content"])
                                yield _sse({"delta": delta["content"]})
                            if delta.get("tool_calls"):
                                merge_tool_call_delta(
                                    pending, delta["tool_calls"]
                                )

                    if finish_reason != "tool_calls" or not pending:
                        break

                    # execute the requested tools, feed results back
                    calls = [pending[i] for i in sorted(pending)]
                    messages.append({
                        "role": "assistant",
                        "content": "".join(content_parts) or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": c["arguments"],
                                },
                            }
                            for c in calls
                        ],
                    })
                    for c in calls:
                        yield _sse({
                            "tool": {"name": c["name"], "status": "running"}
                        })
                        try:
                            args = json.loads(c["arguments"] or "{}")
                        except json.JSONDecodeError as e:
                            result: dict[str, Any] = {
                                "error": f"malformed tool arguments: {e}"
                            }
                        else:
                            result = await execute_tool(c["name"], args)
                        status = "error" if "error" in result else "ok"
                        tool_info: dict[str, object] = {
                            "name": c["name"], "status": status,
                        }
                        if status == "error":
                            tool_info["error"] = str(result["error"])[:300]
                        yield _sse({"tool": tool_info})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        })
            yield _sse({"done": True})
        except httpx.HTTPError as e:
            yield _sse({"error": f"Cannot reach DeepSeek API: {e}"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
