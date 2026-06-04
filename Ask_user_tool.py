# ask_user_tool.py

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langgraph.types import interrupt


class AskUserInput(BaseModel):
    question: str = Field(
        description=(
            "The exact question to ask the user. "
            "Ask one clear, specific question that helps the agent continue correctly."
        )
    )


class AskUserTool(BaseTool):
    name: str = "ask_user"
    description: str = (
        "Ask the user a question before continuing. "
        "Use this tool when the next step is unclear, when important information is missing, "
        "when there are multiple reasonable choices, or when continuing without confirmation "
        "may lead the agent away from the user's original goal. "
        "Use it before making assumptions about paths, data scope, parameters, outputs, or user intent. "
        "Also use it before inspecting information outside the current task scope or before taking actions "
        "that may change files, overwrite results, or commit to a direction the user has not confirmed. "
        "Do not use this tool if the answer can be reliably obtained from the conversation, current state, "
        "available tools, or already inspected files. "
        "Ask one clear, specific question that helps the agent continue correctly."
    )
    args_schema: type[BaseModel] = AskUserInput

    def _run(self, question: str) -> str:
        answer = interrupt(question)
        return f"User comment: {str(answer)}"

    async def _arun(self, question: str) -> str:
        answer = interrupt(question)
        return f"Question:\n{str(question)}\nUser answer:\n{str(answer)}"