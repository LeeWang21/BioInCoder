from typing import Literal 
from pydantic import BaseModel, Field 

from AgentConfig import AgentConfig, AgentRegistry
from Middleware import check_plan, StorePlanOutputMiddleware
from Ask_user_tool import AskUserTool
from Skill_tool import SkillTool, generate_skill_tool_prompt
from Todo_tools import WritePlan, UpdateChecklist, AdvanceChecklist
from LLM import llm
from Prompts import PLANNER_PROMPT, BIOINCODER_PROMPT

from langchain_community.tools import ShellTool
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.structured_output import ToolStrategy



# =========================
# Response_format Setup
# =========================
class PlanChecklistStep(BaseModel):
    step: str = Field(
        ...,
        description=(
            "A short, concrete, one-sentence checklist step. "
            "It should describe a meaningful unit of work, not a vague activity. "
            "Prefer logically ordered, verifiable steps that can be marked done. "
            "Keep it concise, ideally no more than 5-10 words."
        ),
    )

    status: Literal["pending", "in_progress", "completed"] = Field(
        ...,
        description=(
            "Current execution status of this step. "
            "'pending' means the step has not started; "
            "'in_progress' means this is the active step being worked on now; "
            "'completed' means the step has been finished and verified enough to move on. "
            "When plan_required is true and work is not finished, exactly one step should usually be 'in_progress'. "
            "When all work is finished, all steps should be 'completed'."
        ),
    )


class PlanOutputFormat(BaseModel):
    plan_required: bool = Field(
        ...,
        description=(
            "Whether the user request benefits from an explicit multi-step plan. "
            "Use true for non-trivial, ambiguous, multi-phase, tool-using, file/code/data, or long-running tasks; "
            "for tasks with dependencies where sequencing matters; "
            "for tasks requiring intermediate checkpoints; "
            "or when the user explicitly asks for a plan/TODO/checklist. "
            "Use false for simple, single-step, conversational, or immediately answerable requests. "
            "Do not create a plan merely to pad simple work."
        ),
    )

    overview: str = Field(
        ...,
        description=(
            "A human- and agent-readable Markdown planning brief. "
            "When plan_required is true, this should be a complete proposed plan, not just a short summary. "
            "It should explain the goal, discovered context, assumptions, constraints, execution strategy, "
            "validation criteria, and expected deliverable when relevant. "
            "Use clear Markdown headings and bullets so the plan can be reviewed by a user and handed off to an executor. "
            "When plan_required is false, briefly explain in plain text why no explicit plan is needed. "
            "Do not include hidden chain-of-thought. "
            "Do not merely repeat the checklist."
        ),
    )

    checklist: list[PlanChecklistStep] = Field(
        default_factory=list,
        description=(
            "An ordered checklist of meaningful steps needed to complete the task. "
            "Use only when plan_required is true. "
            "Each step should be concrete, logically sequenced, and easy to verify. "
            "Avoid low-quality filler steps such as 'understand task', 'do work', or 'summarize result'. "
            "Do not include steps the agent cannot actually perform. "
            "Use an empty list when plan_required is false."
        ),
    )


# =========================
# Agent_registry Setup
# =========================
agent_registry = AgentRegistry()
ckpt = InMemorySaver()

#register_tool
agent_registry.register_tool(name="Bash_tool", tool=ShellTool(name = "Bash"))
agent_registry.register_tool(name="Ask_user_tool", tool=AskUserTool())
agent_registry.register_tool(name="Skill_tool", tool=SkillTool())
agent_registry.register_tool(name="Write_plan", tool=WritePlan())
agent_registry.register_tool(name="Update_checklist", tool=UpdateChecklist())
agent_registry.register_tool(name="Advance_checklist", tool=AdvanceChecklist())

#register_middleware
agent_registry.register_middleware(name="check_plan", middleware=check_plan)
agent_registry.register_middleware(name="store_plan", middleware=StorePlanOutputMiddleware())

#Plan_AgentConfig
tools_for_plan = ["Ask_user_tool", "Skill_tool", "Bash_tool"]
middleware_for_plan = ["check_plan", "store_plan"]

SKILL_PROMPT_FOR_PLAN = generate_skill_tool_prompt() if "Skill_tool" in tools_for_plan else ""

Plan_AgentConfig = AgentConfig(
    agent_name = "planner",
    description = "The planner responsible for plan module in BioInCoder system",
    channel = "Plan_Channel",
    model = llm,
    system_prompt = PLANNER_PROMPT + SKILL_PROMPT_FOR_PLAN,
    tool_names = tools_for_plan,
    middleware_names = middleware_for_plan,
    response_format = ToolStrategy(schema = PlanOutputFormat),
    checkpointer = ckpt
)

#BioInCoder_AgentConfig
tools_for_Coder = [
    "Ask_user_tool",
    "Skill_tool",
    "Bash_tool",
    "Write_plan",
    "Update_checklist",
    "Advance_checklist",
]

SKILL_PROMPT_FOR_CODER = generate_skill_tool_prompt() if "Skill_tool" in tools_for_Coder else ""

BioInCoder_AgentConfig = AgentConfig(
    agent_name = "BioInCoder",
    description = "The main agent in BioInCoder system",
    channel = "BioInCoder_Channel",
    model = llm,
    system_prompt = BIOINCODER_PROMPT + SKILL_PROMPT_FOR_CODER,
    tool_names = tools_for_Coder,
    checkpointer = ckpt
)

#register agent
for config in [BioInCoder_AgentConfig, Plan_AgentConfig]:
    agent_registry.register_agent(config)
