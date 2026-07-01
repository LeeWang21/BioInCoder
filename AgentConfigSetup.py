import os
from typing import Literal 
from pydantic import BaseModel, Field 

from AgentConfig import AgentConfig, AgentRegistry
from Middleware import check_plan, shell_approval, StorePlanOutputMiddleware
from Ask_user_tool import AskUserTool
from Message_tools import ReadAgentMessages, ListSavedMessageRefs
from Skill_tool import SkillTool, generate_skill_tool_prompt
from Todo_tools import SetPlan, UpdateChecklist, AdvanceChecklist
from LLM import llm, llm_flash
from Prompts import PLANNER_PROMPT, SEARCH_PROMPT, BROWSER_PROMPT, READ_PROMPT, CODE_REVIEWER_PROMPT, BIOINCODER_PROMPT
from Runtime import MultiAgentRuntime, BioInCoderState
from jupytercode_tool import JupyterCodeToolkit, JUPYTER_REGISTRY
from Search_tools import AcademicRestRequest, AcademicSearch
from CodeReview_tools import CodeReview, CodeReviewWorkspace
from Persistence import make_checkpointer, session_subagent_transcripts_dir
from Browser_tools import (
    AgentBrowserCommand,
    AgentBrowserHelp,
    BrowserAuthConfig,
    BrowserCleanup,
    BrowserBrowse,
    BrowserDownloadArtifact,
    BrowserLoginWithEnv,
    BrowserState,
    CloakBrowserConfig,
)
from Read_tools import MarkItDownCommand, ReadArtifact

from langchain_community.tools import ShellTool
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
ckpt = make_checkpointer()

#register_tool
agent_registry.register_tool(name="Bash_tool", tool=ShellTool(name = "Bash"))
agent_registry.register_tool(name="Ask_user_tool", tool=AskUserTool())
agent_registry.register_tool(name="Skill_tool_BioInCoder", tool=SkillTool(agent_name="BioInCoder"))
agent_registry.register_tool(name="Skill_tool_Planner", tool=SkillTool(agent_name="planner"))
agent_registry.register_tool(name="Skill_tool_Search", tool=SkillTool(agent_name="search"))
agent_registry.register_tool(name="Skill_tool_Browser", tool=SkillTool(agent_name="browser"))
agent_registry.register_tool(name="Skill_tool_Read", tool=SkillTool(agent_name="reader"))
agent_registry.register_tool(name="Skill_tool_CodeReviewer", tool=SkillTool(agent_name="CodeReviewer"))
agent_registry.register_tool(name="Set_plan", tool=SetPlan())
agent_registry.register_tool(name="Update_checklist", tool=UpdateChecklist())
agent_registry.register_tool(name="Advance_checklist", tool=AdvanceChecklist())
agent_registry.register_tool(name="Read_agent_messages", tool=ReadAgentMessages())
agent_registry.register_tool(name="List_saved_message_refs", tool=ListSavedMessageRefs())
agent_registry.register_tool(name="Academic_rest_request", tool=AcademicRestRequest())
agent_registry.register_tool(name="Academic_search", tool=AcademicSearch())
agent_registry.register_tool(name="Code_review", tool=CodeReview())
agent_registry.register_tool(name="Code_review_workspace", tool=CodeReviewWorkspace())
agent_registry.register_tool(name="Agent_browser_command", tool=AgentBrowserCommand())
agent_registry.register_tool(name="Agent_browser_help", tool=AgentBrowserHelp())
agent_registry.register_tool(name="Cloakbrowser_config", tool=CloakBrowserConfig())
agent_registry.register_tool(name="Browser_cleanup", tool=BrowserCleanup())
agent_registry.register_tool(name="Browser_auth_config", tool=BrowserAuthConfig())
agent_registry.register_tool(name="Browser_download_artifact", tool=BrowserDownloadArtifact())
agent_registry.register_tool(name="Browser_state", tool=BrowserState())
agent_registry.register_tool(name="Browser_login_with_env", tool=BrowserLoginWithEnv())
agent_registry.register_tool(name="Browser_browse", tool=BrowserBrowse())
agent_registry.register_tool(name="Markitdown_command", tool=MarkItDownCommand())
agent_registry.register_tool(name="Read_artifact", tool=ReadArtifact())

for tool in JupyterCodeToolkit().get_tools():
    agent_registry.register_tool(name=tool.name, tool=tool)

#register_middleware
agent_registry.register_middleware(name="check_plan", middleware=check_plan)
agent_registry.register_middleware(name="shell_approval", middleware=shell_approval)
agent_registry.register_middleware(name="store_plan", middleware=StorePlanOutputMiddleware())

#Plan_AgentConfig
tools_for_plan = ["Ask_user_tool", "Skill_tool_Planner", "Bash_tool"]
middleware_for_plan = ["check_plan", "store_plan", "shell_approval"]

SKILL_PROMPT_FOR_PLAN = generate_skill_tool_prompt(agent_name="planner") if "Skill_tool_Planner" in tools_for_plan else ""

Plan_AgentConfig = AgentConfig(
    agent_name = "planner",
    description = "The planner responsible for plan module in BioInCoder system",
    channel = "Plan_Channel",
    model = llm,
    system_prompt = PLANNER_PROMPT + SKILL_PROMPT_FOR_PLAN,
    tool_names = tools_for_plan,
    middleware_names = middleware_for_plan,
    response_format = ToolStrategy(schema = PlanOutputFormat),
)

#Search_AgentConfig
tools_for_search = [
    "Skill_tool_Search",
    "Read_agent_messages",
    "List_saved_message_refs",
    "Academic_rest_request",
]

SKILL_PROMPT_FOR_SEARCH = generate_skill_tool_prompt(agent_name="search") if "Skill_tool_Search" in tools_for_search else ""

Search_AgentConfig = AgentConfig(
    agent_name = "search",
    description = "The search subagent responsible for academic literature and scholarly metadata retrieval in BioInCoder system",
    channel = "Search_Channel",
    model = llm_flash,
    system_prompt = SEARCH_PROMPT + SKILL_PROMPT_FOR_SEARCH,
    tool_names = tools_for_search,
)

#Browser_AgentConfig
tools_for_browser = [
    "Ask_user_tool",
    "Skill_tool_Browser",
    "Read_agent_messages",
    "List_saved_message_refs",
    "Agent_browser_help",
    "Cloakbrowser_config",
    "Agent_browser_command",
    "Browser_cleanup",
    "Browser_auth_config",
    "Browser_download_artifact",
    "Browser_state",
    "Browser_login_with_env",
]

SKILL_PROMPT_FOR_BROWSER = generate_skill_tool_prompt(agent_name="browser") if "Skill_tool_Browser" in tools_for_browser else ""

Browser_AgentConfig = AgentConfig(
    agent_name = "browser",
    description = "The browser subagent responsible for web browsing with agent-browser CLI and cloakbrowser in BioInCoder system",
    channel = "Browser_Channel",
    model = llm,
    system_prompt = BROWSER_PROMPT + SKILL_PROMPT_FOR_BROWSER,
    tool_names = tools_for_browser,
)

#Read_AgentConfig
tools_for_read = [
    "Skill_tool_Read",
    "Read_agent_messages",
    "List_saved_message_refs",
    "Markitdown_command",
]

SKILL_PROMPT_FOR_READ = generate_skill_tool_prompt(agent_name="reader") if "Skill_tool_Read" in tools_for_read else ""

Read_AgentConfig = AgentConfig(
    agent_name="reader",
    description="The read subagent responsible for local document reading with MarkItDown in BioInCoder system",
    channel="Read_Channel",
    model=llm_flash,
    system_prompt=READ_PROMPT + SKILL_PROMPT_FOR_READ,
    tool_names=tools_for_read,
)

#CodeReviewer_AgentConfig
tools_for_code_reviewer = [
    "Skill_tool_CodeReviewer",
    "Read_agent_messages",
    "List_saved_message_refs",
    "Code_review_workspace",
]

SKILL_PROMPT_FOR_CODE_REVIEWER = generate_skill_tool_prompt(agent_name="CodeReviewer") if "Skill_tool_CodeReviewer" in tools_for_code_reviewer else ""

CodeReviewer_AgentConfig = AgentConfig(
    agent_name="CodeReviewer",
    description=(
        "The code review subagent responsible for independent review of notebooks, scripts, "
        "workflow files, reproducibility, and user-intent alignment in BioInCoder system"
    ),
    channel="CodeReview_Channel",
    model=llm,
    system_prompt=CODE_REVIEWER_PROMPT + SKILL_PROMPT_FOR_CODE_REVIEWER,
    tool_names=tools_for_code_reviewer,
)

#BioInCoder_AgentConfig
tools_for_Coder = [
    "Ask_user_tool",
    "Skill_tool_BioInCoder",
    "Bash_tool",
    "Read_agent_messages",
    "List_saved_message_refs",
    "Academic_search",
    "Browser_browse",
    "Read_artifact",
    "Code_review",
    "Set_plan",
    "Update_checklist",
    "Advance_checklist",
    "jupytercode_kernel_selection",
    "jupytercode_notebooks_info",
    "jupytercode_use_notebook",
    "jupytercode_read_notebook",
    "jupytercode_read_cell",
    "jupytercode_insert_cell",
    "jupytercode_insert_execute_code_cell",
    "jupytercode_delete_cell",
    "jupytercode_overwrite_cell_source",
    "jupytercode_session_control",
]

SKILL_PROMPT_FOR_CODER = generate_skill_tool_prompt(agent_name="BioInCoder") if "Skill_tool_BioInCoder" in tools_for_Coder else ""

BioInCoder_AgentConfig = AgentConfig(
    agent_name = "BioInCoder",
    description = "The main agent in BioInCoder system",
    channel = "BioInCoder_Channel",
    model = llm,
    system_prompt = BIOINCODER_PROMPT + SKILL_PROMPT_FOR_CODER,
    tool_names = tools_for_Coder,
    middleware_names = ["shell_approval"],
    state_schema = BioInCoderState,
    checkpointer = ckpt
)

#register agent
for config in [BioInCoder_AgentConfig, Plan_AgentConfig, Search_AgentConfig, Browser_AgentConfig, Read_AgentConfig, CodeReviewer_AgentConfig]:
    agent_registry.register_agent(config)


# =========================
# MultiAgentRuntime Setup
# =========================
BIOINCODER_USER_ID = os.environ.get("BIOINCODER_USER_ID", "default_user")
BIOINCODER_SESSION_ID = os.environ.get("BIOINCODER_SESSION_ID", "default_session")
JUPYTER_REGISTRY.configure(
    user_id=BIOINCODER_USER_ID,
    session_id=BIOINCODER_SESSION_ID,
)

multi_agent_runtime = MultiAgentRuntime(
    agent_registry=agent_registry,
    jupyter_registry=JUPYTER_REGISTRY,
    user_id=BIOINCODER_USER_ID,
    session_id=BIOINCODER_SESSION_ID,
    message_storage_dir=session_subagent_transcripts_dir(BIOINCODER_USER_ID, BIOINCODER_SESSION_ID),
)
