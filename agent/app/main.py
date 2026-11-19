import os
from typing import Literal

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .agent import MODEL, run_agent


app = FastAPI(title="CheeBag · CHEE Service")
API_KEY_SET = bool(os.environ.get("ANTHROPIC_API_KEY"))


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)  # the whole conversation so far, oldest first
    customer_id: int = Field(gt=0)  # the signed-in customer, set by the website (point 2)

class ToolCall(BaseModel):
    tool: str
    input: dict
    is_error: bool
    ms: int

class UIComponent(BaseModel):
    type: Literal["confirmation_card", "product_cards"]   # only card types the website knows how to draw
    version: int = 1                     # lets the card's shape change later without breaking old pages
    data: dict

class ChatResponse(BaseModel):
    reply: str
    model: str
    input_tokens: int
    tool_calls: list[ToolCall]
    output_tokens: int
    ui: list[UIComponent] = []           # NEW: cards for the browser (empty for normal answers)

                       # the card content built by the Store API (order, total, token, ...)
@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "api_key_set": API_KEY_SET}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not API_KEY_SET:
        print("ANTHROPIC_API_KEY is not set: add it to the project .env and restart the agent")
        raise HTTPException(503, "The AI service is not configured yet.")
    try:
        result = run_agent([m.model_dump() for m in request.messages], request.customer_id)

    except anthropic.AnthropicError as e:
        # log the real error for us, show a generic one to the caller
        print(f"Claude API error: {e!r}")
        raise HTTPException(502, "The AI service is unavailable right now.")

    return ChatResponse(model=MODEL, **result)

