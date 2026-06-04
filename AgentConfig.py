from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.stores import BaseStore
from langchain_core.caches import BaseCache


ToolLike = BaseTool | Callable[..., Any] | dict[str, Any]
ModelLike = str | BaseChatModel


@dataclass
class AgentConfig:
    # -------------------------
    # Your registry metadata
    # -------------------------
    agent_name: str
    description: str | None = None
    channel: str | None = None
    enabled: bool = True

    # -------------------------
    # create_agent args
    # -------------------------
    model: ModelLike | None = None
    system_prompt: str | SystemMessage | None = None

    # Registry-based extension
    tool_names: list[str] = field(default_factory=list)
    middleware_names: list[str] = field(default_factory=list)

    # Native create_agent-like args
    tools: Sequence[ToolLike] | None = None
    middleware: Sequence[Any] | None = None

    response_format: Any | None = None
    context_schema: type[Any] | None = None
    checkpointer: Any | None = None
    store: BaseStore | None = None
    interrupt_before: list[str] | None = None
    interrupt_after: list[str] | None = None
    debug: bool = False
    name: str | None = None
    cache: BaseCache | None = None

    def resolve_tools(
        self,
        tool_registry: dict[str, ToolLike] | None = None,
    ) -> list[ToolLike] | None:
        resolved_tools: list[ToolLike] = []

        if self.tools is not None:
            resolved_tools.extend(self.tools)

        if self.tool_names:
            if tool_registry is None:
                raise ValueError(
                    f"Agent '{self.agent_name}' has tool_names but no tool_registry was provided."
                )

            for tool_name in self.tool_names:
                if tool_name not in tool_registry:
                    raise KeyError(f"Tool '{tool_name}' is not registered.")
                resolved_tools.append(tool_registry[tool_name])

        return resolved_tools or None

    def resolve_middleware(
        self,
        middleware_registry: dict[str, Any] | None = None,
    ) -> Sequence[Any]:
        resolved_middleware: list[Any] = []

        if self.middleware is not None:
            resolved_middleware.extend(self.middleware)

        if self.middleware_names:
            if middleware_registry is None:
                raise ValueError(
                    f"Agent '{self.agent_name}' has middleware_names but no middleware_registry was provided."
                )

            for middleware_name in self.middleware_names:
                if middleware_name not in middleware_registry:
                    raise KeyError(f"Middleware '{middleware_name}' is not registered.")
                resolved_middleware.append(middleware_registry[middleware_name])

        return tuple(resolved_middleware)

    def to_create_agent_kwargs(
        self,
        tool_registry: dict[str, ToolLike] | None = None,
        middleware_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "tools": self.resolve_tools(tool_registry),
            "system_prompt": self.system_prompt,
            "middleware": self.resolve_middleware(middleware_registry),
            "response_format": self.response_format,
            "context_schema": self.context_schema,
            "checkpointer": self.checkpointer,
            "store": self.store,
            "interrupt_before": self.interrupt_before,
            "interrupt_after": self.interrupt_after,
            "debug": self.debug,
            "name": self.name or self.agent_name,
            "cache": self.cache,
        }

        return {k: v for k, v in kwargs.items() if v is not None}

    def build_agent(
        self,
        tool_registry: dict[str, ToolLike] | None = None,
        middleware_registry: dict[str, Any] | None = None,
    ):
        if not self.enabled:
            raise RuntimeError(f"Agent '{self.agent_name}' is disabled.")

        from langchain.agents import create_agent

        return create_agent(
            **self.to_create_agent_kwargs(
                tool_registry=tool_registry,
                middleware_registry=middleware_registry,
            )
        )
    
    def __repr__(self):
        return f'''Agent Name: {self.agent_name}\nAgent description: {self.description}\nAgent Enabled: {self.enabled}\nAgent Channel: {self.channel}\nAgent Tools: {self.tool_names}(Defined via `tool_names`)'''
    


class AgentRegistry:
    def __init__(self) -> None:
        self.agent_configs: dict[str, AgentConfig] = {}
        self.tool_registry: dict[str, ToolLike] = {}
        self.middleware_registry: dict[str, Any] = {}

    def register_tool(self, name: str, tool: ToolLike, overwrite: bool = False) -> None:
        if name in self.tool_registry and not overwrite:
            raise ValueError(f"Tool '{name}' is already registered.")
        self.tool_registry[name] = tool

    def register_middleware(
        self,
        name: str,
        middleware: Any,
        overwrite: bool = False,
    ) -> None:
        if name in self.middleware_registry and not overwrite:
            raise ValueError(f"Middleware '{name}' is already registered.")
        self.middleware_registry[name] = middleware

    def register_agent(self, config: AgentConfig, overwrite: bool = False) -> None:
        if config.agent_name in self.agent_configs and not overwrite:
            raise ValueError(f"Agent '{config.agent_name}' is already registered.")
        self.agent_configs[config.agent_name] = config

    def get_config(self, agent_name: str) -> AgentConfig:
        if agent_name not in self.agent_configs:
            raise KeyError(f"Agent '{agent_name}' is not registered.")
        return self.agent_configs[agent_name]

    def build_agent(self, agent_name: str):
        config = self.get_config(agent_name)
        return config.build_agent(
            tool_registry=self.tool_registry,
            middleware_registry=self.middleware_registry,
        )

    def list_agents(self, only_enabled: bool = False) -> list[str]:
        if not only_enabled:
            return list(self.agent_configs.keys())

        return [
            name
            for name, config in self.agent_configs.items()
            if config.enabled
        ]

    def enable_agent(self, agent_name: str) -> None:
        self.get_config(agent_name).enabled = True

    def disable_agent(self, agent_name: str) -> None:
        self.get_config(agent_name).enabled = False