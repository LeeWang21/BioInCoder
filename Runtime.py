from dataclasses import dataclass, field
from typing import TypedDict, Annotated
from Messages import MessageContainer, MessageContainerConfig
from project.BioMultiAgent.AgentConfig import AgentRegistry

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph.message import AnyMessage, add_messages

# =========================
# MultiAgentSate
# =========================
class MultiAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    goal: str
    plan: dict = field(default_factory=dict)
    task: str
    agent_from: str
    agent_to: str



class MultiAgentRuntime:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        message_container: MessageContainer | None = None,
        context_usage: float = 0
    ):
        self.agent_registry = agent_registry
        self.message_container = message_container or MessageContainer(MessageContainerConfig())
        self.context_usage = context_usage

        
    def ContextConcat(
        self,
        main_channel: str,
        secondary_channel: str,
        goal: str | None,
        agent_from: str,
        agent_to: str,
        task: str | None,
        agent_instruction: str | None,
        extra_instruction: str | None,
        plan: str | None = None
    ):
        
        prompt_temp = ChatPromptTemplate.from_messages(
            [
                MessagesPlaceholder(variable_name = "channel"),
                ("human", "{request_goal}"),
                ("human", "{plan}"),
                ("human", "{current_task}"),
                ("human", "{agent_instruction}"),
                ("human", "{extra_instruction}")
            ]
        )

        

        prompt_context = prompt_temp.invoke(
            {
                "channel": main_channel if agent_from != agent_to else secondary_channel,
                "request_goal": f"The goal of user request is: {goal}",
                "plan": "" if plan is None else plan,
                "current_task": f"You are finishing the task: {task}",
                "agent_instruction": f"Fllowing the instraction: {agent_instruction}",
                "extra_instruction": f"extra the instraction: {extra_instruction}"
            }
        )

        return prompt_context
    

    def get_agent(self, agent_name: str):
        return self.agent_registry.build_agent(agent_name)

    def save_messages(
        self,
        channel_name: str,
        request_id: str,
        messages,
    ) -> dict:

        self.message_container.add_requestMsgs(
            channel_name=channel_name,
            request_id=request_id,
            messages=messages,
        )

        return {
            "saved_message_refs": [
                {
                    "channel_name": channel_name,
                    "request_id": request_id,
                }
            ]
        }

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