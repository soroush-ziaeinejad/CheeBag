"""RoomCraft AI service. Step 1: chat with Claude, no tools yet."""
import os
from typing import Literal

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are the RoomCraft AI Assistant, the support assistant of RoomCraft, an online store \
for kitchen and home products. Be friendly, short and clear.
You cannot look up orders, shipments or products yet. If someone asks about a specific order or product, \
say that this ability is coming soon. Never invent order details, prices or policies."""

app = FastAPI(title="RoomCraft AI Service")
API_KEY_SET = bool(os.environ.get("ANTHROPIC_API_KEY"))
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)  # the whole conversation so far, oldest first


class ChatResponse(BaseModel):
    reply: str
    model: str
    input_tokens: int
    output_tokens: int


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "api_key_set": API_KEY_SET}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not API_KEY_SET:
        print("ANTHROPIC_API_KEY is not set: add it to RoomCraft/.env and restart the agent")
        raise HTTPException(503, "The AI service is not configured yet.")
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[m.model_dump() for m in request.messages],
        )
    except anthropic.AnthropicError as e:
        # log the real error for us, show a generic one to the caller
        print(f"Claude API error: {e!r}")
        raise HTTPException(502, "The AI service is unavailable right now.")

    reply = "".join(block.text for block in response.content if block.type == "text")
    return ChatResponse(
        reply=reply,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
