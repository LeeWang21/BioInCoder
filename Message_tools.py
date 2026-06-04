from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ReadAgentMessagesInput(BaseModel):
    channel_name: str = Field(
        ...,
        description="The message_container channel name, such as Plan_Channel.",
    )
    request_id: str = Field(
        ...,
        description="The saved request id inside the channel.",
    )
    format: Literal["prefix", "xml"] = Field(
        default="prefix",
        description="Output format for the stored transcript.",
    )


class ReadAgentMessages(BaseTool):
    name: str = "read_agent_messages"
    description: str = (
        "Read a saved agent or subagent transcript from MultiAgentRuntime.message_container. "
        "Use this when a previous tool response says that detailed subagent messages were saved "
        "in a channel/request_id."
    )
    args_schema: type[BaseModel] = ReadAgentMessagesInput

    def _run(self, channel_name: str, request_id: str, format: str = "prefix") -> str:
        from AgentConfigSetup import multi_agent_runtime

        return multi_agent_runtime.read_messages_as_context(
            channel_name=channel_name,
            request_id=request_id,
            format=format,
        )


class ListSavedMessageRefsInput(BaseModel):
    include_empty_channels: bool = Field(
        default=False,
        description="Whether to include channels that currently have no saved requests.",
    )


class ListSavedMessageRefs(BaseTool):
    name: str = "list_saved_message_refs"
    description: str = (
        "List saved message_container channels and request ids. "
        "Use this before read_agent_messages when you need to find available saved transcripts."
    )
    args_schema: type[BaseModel] = ListSavedMessageRefsInput

    def _run(self, include_empty_channels: bool = False) -> dict:
        from AgentConfigSetup import multi_agent_runtime

        channels = {}
        for channel_name, requests in multi_agent_runtime.message_container.channels.items():
            if requests or include_empty_channels:
                channels[channel_name] = list(requests.keys())

        return {
            "user_id": multi_agent_runtime.message_container.config.user_id,
            "session_id": multi_agent_runtime.message_container.config.session_id,
            "channels": channels,
        }
