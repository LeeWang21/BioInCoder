import re
from typing import TypedDict, Optional, Literal

from langchain.agents.middleware import (
    before_agent,
    before_model,
    after_model,
    after_agent,
    wrap_model_call,
    wrap_tool_call,
    AgentMiddleware,
    AgentState,
    HumanInTheLoopMiddleware,
)
from langchain.tools.tool_node import ToolCallRequest

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt
from langgraph.runtime import Runtime

# =========================
# Middleware for shell approval
# =========================
SHELL_APPROVAL_RULES: list[tuple[str, str, str]] = [
    (
        "rm_recursive_force",
        r"\brm\s+.*(-rf|-fr)\b",
        "Can recursively and forcefully delete files.",
    ),
    (
        "rm_root_or_home",
        r"\brm\s+.*(?:\s|^)(/|~|\$HOME)(?:\s|$)",
        "May delete root/home or broad paths.",
    ),
    (
        "git_clean_force",
        r"\bgit\s+clean\b.*(?:^|\s)(-f|-df|-fd|-xdf|-xfd)(?:\s|$)",
        "Can delete untracked files.",
    ),
    (
        "git_reset_hard",
        r"\bgit\s+reset\b.*--hard\b",
        "Can discard working tree and index changes.",
    ),
    (
        "git_checkout_path",
        r"\bgit\s+checkout\b.*--\s+",
        "Can overwrite working tree files.",
    ),
    (
        "git_restore_path",
        r"\bgit\s+restore\b",
        "Can overwrite working tree files.",
    ),
    (
        "sudo",
        r"(^|[;&|]\s*)sudo\b",
        "Runs commands with elevated privileges.",
    ),
    (
        "chmod_recursive",
        r"\bchmod\b.*(?:^|\s)-R(?:\s|$)",
        "Recursively changes permissions.",
    ),
    (
        "chown_recursive",
        r"\bchown\b.*(?:^|\s)-R(?:\s|$)",
        "Recursively changes ownership.",
    ),
    (
        "system_package_manager",
        r"\b(apt|apt-get|yum|dnf|brew)\s+(install|remove|upgrade|update|uninstall)\b",
        "Changes system packages.",
    ),
    (
        "pip_install",
        r"\bpip(3)?\s+install\b",
        "Installs Python packages and changes the environment.",
    ),
    (
        "pip_uninstall",
        r"\bpip(3)?\s+uninstall\b",
        "Removes Python packages and changes the environment.",
    ),
    (
        "pip_sync",
        r"\bpip-sync\b",
        "Synchronizes Python packages and changes the environment.",
    ),
    (
        "conda_mutation",
        r"\bconda\s+(install|remove|uninstall|update|upgrade|env\s+create|env\s+remove)\b",
        "Changes conda packages or environments.",
    ),
    (
        "mamba_mutation",
        r"\bmamba\s+(install|remove|uninstall|update|upgrade|env\s+create|env\s+remove)\b",
        "Changes conda packages or environments.",
    ),
    (
        "uv_mutation",
        r"\buv\s+(pip\s+install|pip\s+uninstall|sync|add|remove)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "poetry_mutation",
        r"\bpoetry\s+(add|remove|install|update)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "pipenv_mutation",
        r"\bpipenv\s+(install|uninstall|sync|update)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "npm_mutation",
        r"\bnpm\s+(install|uninstall|update|audit\s+fix)\b",
        "Changes Node dependencies.",
    ),
    (
        "pnpm_mutation",
        r"\bpnpm\s+(install|remove|update|add)\b",
        "Changes Node dependencies.",
    ),
    (
        "yarn_mutation",
        r"\byarn\s+(add|remove|install|upgrade)\b",
        "Changes Node dependencies.",
    ),
    (
        "ruby_bundle_mutation",
        r"\bbundle\s+(install|update|add|remove)\b",
        "Changes Ruby dependencies.",
    ),
    (
        "cargo_install",
        r"\bcargo\s+install\b",
        "Installs Rust binaries or packages.",
    ),
    (
        "curl_pipe_shell",
        r"\bcurl\b.*\|\s*(sh|bash|zsh|python|python3)\b",
        "Downloads and executes remote code.",
    ),
    (
        "wget_pipe_shell",
        r"\bwget\b.*\|\s*(sh|bash|zsh|python|python3)\b",
        "Downloads and executes remote code.",
    ),
    (
        "remote_shell",
        r"\bssh\b",
        "Opens a remote shell/session.",
    ),
    (
        "remote_copy",
        r"\b(scp|sftp)\b",
        "Transfers files to or from a remote host.",
    ),
    (
        "kill_all",
        r"\b(killall|pkill)\b",
        "Can terminate many processes.",
    ),
    (
        "service_control",
        r"\b(systemctl|launchctl|service)\b",
        "Controls system services.",
    ),
]


def _normalize_shell_command(command: str) -> str:
    return " ".join(command.strip().split())


def _extract_shell_command(request: ToolCallRequest) -> str:
    args = request.tool_call.get("args", {})
    if isinstance(args, dict):
        command = (
            args.get("commands")
            or args.get("command")
            or args.get("query")
            or args
        )
        return str(command)
    return str(args)


def shell_approval_reason(command: str) -> tuple[str, str] | None:
    command = _normalize_shell_command(command)
    for name, pattern, description in SHELL_APPROVAL_RULES:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return name, description
    return None


def shell_needs_approval(request: ToolCallRequest) -> bool:
    return shell_approval_reason(_extract_shell_command(request)) is not None


def shell_approval_description(request: ToolCallRequest) -> str:
    command = _normalize_shell_command(_extract_shell_command(request))
    reason = shell_approval_reason(command)
    if reason is None:
        return f"Shell command requires approval.\n\nCommand:\n{command}"

    name, description = reason
    return (
        "Shell command requires approval.\n\n"
        f"Reason: {name} - {description}\n\n"
        f"Command:\n{command}"
    )


shell_approval = HumanInTheLoopMiddleware(
    interrupt_on={
        "Bash": {
            "allowed_decisions": ["approve", "reject"],
            "when": shell_needs_approval,
        }
    },
    description_prefix="Shell command pending approval",
)

# =========================
# Middleware for plan
# =========================
class PlanChecklistStep(TypedDict, total=False):
    step: str
    status: Literal["pending", "in_progress", "completed"]

class PlanOutput(TypedDict, total = False):
    plan_required: bool
    overview: str
    checklist: list[PlanChecklistStep]

class PlanState(TypedDict, total = False):
    plan: PlanOutput

class StorePlanOutputMiddleware(AgentMiddleware):
    state_schema = PlanState

    def after_agent(self, state: AgentState, runtime: Runtime):
        structured_out = state.get("structured_response")

        #skip if no structured_out
        if structured_out is None:
            return None
        
        #deserialize
        if hasattr(structured_out, "model_dump"):
            out_dict = structured_out.model_dump()
        elif isinstance(structured_out, dict):
            out_dict = structured_out
        else:
            out_dict = dict(structured_out)

        out_dict["checklist"] = [
            step.model_dump() if hasattr(step, "model_dump") else dict(step)
            for step in out_dict["checklist"]
        ]
        
        return {
            "structured_response": out_dict,
            "plan": {
                "plan_required": out_dict["plan_required"],
                "overview": out_dict["overview"],
                "checklist": out_dict["checklist"]
            }
        }
    

@after_agent(can_jump_to=["model"])
def check_plan(state: AgentState, runtime: Runtime):
    plan = state.get("plan", {})

    if not plan.get("plan_required", False):
        return None
    else:
            
        plan_overview = plan["overview"]
        plan_checklist = plan["checklist"]
        if not plan_overview or not plan_checklist:
            return {
                "messages": [HumanMessage(content = "Either plan overview or plan checklist is empty, need to replan")],
                "jump_to": "model"
            }

        checklist_list = []
        checklist_in_progress = 0
        for step in plan_checklist:
            checklist_in_progress += step['status'] == "in_progress"
            checklist_list.append(f"[] {step['step']}\t Status: {step['status']}")
            
        checklist_string = "\n".join(checklist_list)

        if checklist_in_progress > 1:
            return {
                "messages": [HumanMessage(content=f"Do not set more than one 'in_progress' status for checklist:\n{checklist_string}\n")]
            }
            
            
        plan_context = f"\n#The proposed **plan overview** is: \n{plan_overview}\n\n#The proposed **plan checklist** is: \n{checklist_string}\n"

        comment = interrupt(f'''{plan_context}\nreply "yes" for plan execution.\nreply "exit" for no plan.\nreply comments for plan refinement.\n''')

        if comment.strip().lower() in {"yes", "yeah", "yep", "ok", "correct", "good", "perfect", "no comment"}:
            return {
                "messages": [HumanMessage(content=f"Final plan overview and plan checklist: {plan_context}")]
            }
            
        elif comment.strip().lower() in {"exit", "exiting", "quit"}:
            return {
                "messages": [HumanMessage(content=f"The user quit the plan generation. No plan needed for execution. Continue the execution without plan")],
                "plan": {
                    **plan,
                    "plan_required": False
                },
            }
        else:
            return {
                "messages": [HumanMessage(content=f"Refine the plan based on the comment: {plan_context}. The comment is: {comment}")],
                "jump_to": "model"
            }
    

    
