from dataclasses import dataclass, field
from typing import Any, TypedDict, Annotated
from uuid import uuid4

from Messages import MessageContainer, MessageContainerConfig
from AgentConfig import AgentRegistry

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph.message import AnyMessage, add_messages

# =========================
# MultiAgentSate
# =========================
class MultiAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: dict



@dataclass
class JupyterRegistry:
    """Placeholder registry for future notebook/kernel sessions."""

    sessions: dict[str, Any] = field(default_factory=dict)

    def register(self, name: str, session: Any, overwrite: bool = False) -> None:
        if name in self.sessions and not overwrite:
            raise ValueError(f"Jupyter session '{name}' is already registered.")
        self.sessions[name] = session

    def get(self, name: str) -> Any:
        if name not in self.sessions:
            raise KeyError(f"Jupyter session '{name}' is not registered.")
        return self.sessions[name]

    def list_sessions(self) -> list[str]:
        return list(self.sessions.keys())


@dataclass
class MessageRef:
    channel_name: str
    request_id: str
    agent_name: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    read_tool_name: str = "read_agent_messages"

    def to_tool_hint(self) -> str:
        return (
            "The subagent transcript was saved in message_container.\n"
            f"- agent_name: {self.agent_name}\n"
            f"- channel_name: {self.channel_name}\n"
            f"- request_id: {self.request_id}\n"
            f"- user_id: {self.user_id}\n"
            f"- session_id: {self.session_id}\n"
            f"Use `{self.read_tool_name}` with `channel_name='{self.channel_name}'` "
            f"and `request_id='{self.request_id}'` to read it."
        )


class MultiAgentRuntime:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        message_container: MessageContainer | None = None,
        jupyter_registry: JupyterRegistry | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        context_usage: float = 0
    ):
        self.agent_registry = agent_registry
        self.user_id = user_id
        self.session_id = session_id
        self.message_container = message_container or MessageContainer(
            MessageContainerConfig(
                user_id=user_id,
                session_id=session_id,
            )
        )
        self.jupyter_registry = jupyter_registry or JupyterRegistry()
        self.context_usage = context_usage
        self.ensure_agent_channels()

    def ensure_agent_channels(self) -> None:
        for config in self.agent_registry.agent_configs.values():
            if config.channel:
                self.message_container.add_channel(config.channel)

    def get_agent_channel(self, agent_name: str) -> str:
        config = self.agent_registry.get_config(agent_name)
        return config.channel or f"{agent_name}_Channel"

    def make_request_id(self, agent_name: str, prefix: str | None = None) -> str:
        prefix = prefix or agent_name
        return f"{prefix}-{uuid4().hex[:12]}"

    def make_child_config(
        self,
        parent_config: dict | None,
        agent_name: str,
        request_id: str | None = None,
    ) -> dict:
        request_id = request_id or self.make_request_id(agent_name)
        parent_config = dict(parent_config or {})
        configurable = dict(parent_config.get("configurable", {}))
        parent_thread_id = configurable.get("thread_id", "root")

        configurable["thread_id"] = f"{parent_thread_id}:{agent_name}:{request_id}"
        parent_config["configurable"] = configurable
        return parent_config

    
    def get_agent(self, agent_name: str):
        return self.agent_registry.build_agent(agent_name)

    def extract_messages(self, agent_state: Any) -> list[AnyMessage]:
        if isinstance(agent_state, dict):
            messages = agent_state.get("messages", [])
            return list(messages or [])

        messages = getattr(agent_state, "messages", None)
        return list(messages or [])

    def save_messages(
        self,
        channel_name: str,
        request_id: str,
        messages,
        agent_name: str | None = None,
    ) -> MessageRef:

        self.message_container.add_requestMsgs(
            channel_name=channel_name,
            request_id=request_id,
            messages=messages,
        )

        return MessageRef(
            channel_name=channel_name,
            request_id=request_id,
            agent_name=agent_name,
            user_id=self.message_container.config.user_id,
            session_id=self.message_container.config.session_id,
        )

    def save_agent_state_messages(
        self,
        agent_name: str,
        agent_state: Any,
        request_id: str | None = None,
        input_message_count: int = 0,
    ) -> MessageRef:
        channel_name = self.get_agent_channel(agent_name)
        request_id = request_id or self.make_request_id(agent_name)
        messages = self.extract_messages(agent_state)
        if input_message_count > 0 and len(messages) >= input_message_count:
            messages = messages[input_message_count - 1:]

        return self.save_messages(
            channel_name=channel_name,
            request_id=request_id,
            messages=messages,
            agent_name=agent_name,
        )

    def invoke_agent(
        self,
        agent_name: str,
        graph_input: dict,
        config: dict | None = None,
        request_id: str | None = None,
        save_messages: bool = True,
        save_input_messages: bool = False,
    ) -> tuple[Any, MessageRef | None]:
        agent = self.get_agent(agent_name)
        input_message_count = 0
        if not save_input_messages and isinstance(graph_input, dict):
            input_message_count = len(graph_input.get("messages") or [])

        if config is None:
            agent_state = agent.invoke(graph_input)
        else:
            agent_state = agent.invoke(graph_input, config=config)

        message_ref = None
        if save_messages:
            message_ref = self.save_agent_state_messages(
                agent_name=agent_name,
                agent_state=agent_state,
                request_id=request_id,
                input_message_count=input_message_count,
            )

        return agent_state, message_ref

    def read_messages_as_context(
        self,
        channel_name: str,
        request_id: str,
        format: str = "prefix",
    ) -> str:

        return self.message_container.string_requestMsgs(
            channel_name=channel_name,
            request_id=request_id,
            format=format,
        )
