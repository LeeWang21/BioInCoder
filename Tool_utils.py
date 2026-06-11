from typing import Any

from langchain.messages import ToolMessage
from langgraph.types import Command


def is_graph_interrupt(error: BaseException) -> bool:
    return type(error).__name__ == "GraphInterrupt"


def tool_error_response(
    error: Exception | str,
    error_type: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    if isinstance(error, Exception):
        error_type = error_type or type(error).__name__
        error_text = str(error)
    else:
        error_type = error_type or "Error"
        error_text = error

    out: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "error": error_text,
    }
    if hint:
        out["hint"] = hint
    return out


def tool_error_command(
    error: Exception | str,
    tool_call_id: str,
    error_type: str | None = None,
    hint: str | None = None,
) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=str(tool_error_response(error, error_type=error_type, hint=hint)),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
