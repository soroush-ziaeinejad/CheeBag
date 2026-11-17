"""The tool-calling loop: ask Claude, run the tools it asks for, send results back, repeat."""
import os
from datetime import date
import time
import anthropic
from .tools import TOOLS, run_tool
import json


MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 1024
MAX_ROUNDS = 5


SYSTEM_PROMPT = """You are CHEE, the home-loving shopping and support assistant of Chideman AI, an online store \
for kitchen and home products. Be friendly, short and clear, with the warm personality of a witty interior designer. Use gentle, occasional humour; never mock a customer or let jokes get in the way of help. Do not claim to generate room designs or previews. Today is {today}. Prices are in Canadian dollars (CAD). The store ships to Canada and the United States.
You are talking to a signed-in customer. Use your tools to look up their orders and the product catalog.
- Answer only from tool results. Never invent orders, tracking numbers, dates, prices or products.
- If a tool returns an error, explain it simply (for example, that you couldn't find that order) and don't guess.
- You can only see this customer's own orders.
- To cancel an order, use propose_cancel_order. It only shows the customer a confirmation card: the order is \
cancelled only if they click Confirm, so never say an order is cancelled. After proposing, ask them to check \
the card. If the store says it can't be cancelled, explain the reason kindly.
- You can't change addresses yet, and you don't have the store policies (returns, refunds, shipping times) \
yet. Say these are coming soon."""

client = anthropic.Anthropic(timeout=30, max_retries=2)


def run_agent(messages, customer_id):
    conversation = list(messages)
    tool_calls = []
    ui = []
    input_tokens = output_tokens = 0

    for i in range(MAX_ROUNDS):
        response = client.messages.create(
            model = MODEL,
            max_tokens = MAX_TOKENS,
            system = SYSTEM_PROMPT.format(today=date.today().isoformat()),
            tools = TOOLS,
            messages = conversation
        )
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        if response.stop_reason != "tool_use":
            reply = "".join(block.text for block in response.content if block.type == "text") \
                    or "Sorry, I couldn't put together an answer. Could you rephrase that?"
            return {"reply": reply, "tool_calls": tool_calls, "ui": ui,
                    "input_tokens": input_tokens, "output_tokens": output_tokens}
        conversation.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            start = time.perf_counter()
            result, is_error = run_tool(block.name, customer_id, block.input)
            if isinstance(result, dict) and "_ui" in result:  # NEW (3)
                ui.append(result.pop("_ui"))  # take the card (and its token) out BEFORE Claude sees the result

            tool_calls.append({"tool": block.name, "input": block.input, "is_error": is_error,
                                "ms": round((time.perf_counter() - start) * 1000)})
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(result), "is_error": is_error})
        conversation.append({"role": "user", "content": results})
    return {"reply": "Sorry, I couldn't finish that. Could you ask in a simpler way?",
            "tool_calls": tool_calls, "ui": ui, "input_tokens": input_tokens, "output_tokens": output_tokens}