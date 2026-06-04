from typing import Type, Literal
from pydantic import BaseModel, Field, ConfigDict
from langchain.tools import BaseTool, ToolRuntime 
from langchain.messages import HumanMessage, ToolMessage

from langgraph.types import Command, interrupt


class PlanChecklistStep(BaseModel):
    step: str = Field(
        ...,
        description=(
            "A short, concrete, verifiable checklist step. "
            "It should describe one meaningful unit of work. "
            "For steps without minor revision, Keep the original step wording."
        ),
    )

    status: Literal["pending", "in_progress", "completed"] = Field(
        ...,
        description=(
            "The current status of this checklist step. "
            "'pending' means not started; "
            "'in_progress' means this is the active step; "
            "'completed' means the step has been finished and verified enough to move on."
        ),
    )


def _coerce_checklist(checklist: list) -> list[dict]:
    return [
        step.model_dump() if hasattr(step, "model_dump") else dict(step)
        for step in checklist
    ]


def _format_checklist(checklist: list[dict]) -> str:
    if not checklist:
        return "(empty)"

    return "\n".join(
        f"[] {step['step']}\t Status: {step['status']}"
        for step in checklist
    )


def _count_in_progress(checklist: list[dict]) -> int:
    return sum(step.get("status") == "in_progress" for step in checklist)


def _coerce_plan(plan_state: dict) -> dict:
    plan = plan_state.get("plan")
    if plan:
        return dict(plan)

    structured_response = plan_state.get("structured_response")
    if structured_response is None:
        return {}

    if hasattr(structured_response, "model_dump"):
        return structured_response.model_dump()

    return dict(structured_response)


def _format_plan(plan: dict) -> str:
    checklist = _format_checklist(plan.get("checklist", []))
    return (
        f"# Plan overview\n{plan.get('overview', '')}\n\n"
        f"# Plan checklist\n{checklist}"
    )


class WritePlanInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True) #allow arbitrary types so Pydantic accepts ToolRuntime 
    objective: str = Field(
        ...,
        description=(
            "The concrete user goal that needs a plan. "
            "Restate the actual task to be planned, including important constraints, files, data, or expected outputs if known. "
            "Do not pass vague text like 'make a plan' unless that is the full user request."
        )
    )
    runtime: ToolRuntime
    #Ref https://forum.langchain.com/t/how-to-access-tool-call-id-using-runtime/2166



class WritePlan(BaseTool):
    name: str = "write_plan"
    description: str = (
        "Create or reset a plan composed of structured plan overview and plan checklist for the current user objective. "
        "Use this tool when the task is complex, multi-step, ambiguous, requires tools/files/code/data, "
        "or when progress tracking would help. "
        "or both previous plan overview and plan checklist require major revision"
        "The tool calls a planner subagent using the current conversation/runtime state and the provided objective. "
        "It returns a human- and agent-readable planning brief plus an ordered checklist with statuses. "
        "Do not use this tool for simple one-step questions, direct factual answers, trivial rewrites, checklist minor revision or checklist status change. "
        "This tool only plans; it does not execute the task, modify files, run analysis, or produce the final deliverable."
    )
    args_schema: Type[BaseModel] = WritePlanInput

    def _run(self, objective: str, runtime: ToolRuntime):
        from AgentConfigSetup import multi_agent_runtime

        coder_msgs = runtime.state.get("messages", [])

        coder_msgs_sanitization = coder_msgs
        if coder_msgs_sanitization and getattr(coder_msgs_sanitization[-1], "tool_calls", None):
            coder_msgs_sanitization = coder_msgs_sanitization[:-1]


        planner_instruction = HumanMessage(
            content=(
                "Create or update the execution plan for the following objective.\n\n"
                f"# Objective\n{objective}\n\n"
                "Use the current conversation and runtime state as context. "
                "If a plan already exists in context, reset it for major revision instead of starting from scratch. "
                "Return only the required PlanOutputFormat structured output."
            )
        )

        request_id = runtime.tool_call_id
        planner_config = multi_agent_runtime.make_child_config(
            parent_config=getattr(runtime, "config", None),
            agent_name="planner",
            request_id=request_id,
        )
        plan_state, message_ref = multi_agent_runtime.invoke_agent(
            agent_name="planner",
            graph_input={
                "messages": coder_msgs_sanitization + [planner_instruction],
            },
            request_id=request_id,
            config=planner_config,
        )

        plan = _coerce_plan(plan_state)
        plan_required = bool(plan.get("plan_required", False))
        plan_context = (
            _format_plan(plan)
            if plan_required
            else (
                "No executable plan was produced. Either the user quit plan generation "
                "or the planner returned plan_required=False."
            )
        )
        if message_ref is not None:
            plan_context = (
                f"{plan_context}\n\n"
                "# Saved subagent messages\n"
                f"{message_ref.to_tool_hint()}"
            )

        update = {
            "messages": [ToolMessage(content=plan_context, tool_call_id=runtime.tool_call_id)]
        }

        if plan:
            update["plan"] = plan

        return Command(update=update)
    


class UpdateChecklistInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    updated_checklist: list[PlanChecklistStep] = Field(
        ...,
        description=(
            "The minor revised checklist that should replace the current plan checklist. "
            "Pass the full checklist, not only the changed step. "
            "Each item must preserve the original task meaning unless a minor revision is needed. "
            "Use this making a small checklist refinement during execution. "
            "Do not use this to advance progress status."
            "Do not use this for create or reset the plan."
            "Use only these statuses: 'pending', 'in_progress', and 'completed'. "
            "Normally there should be exactly one 'in_progress' step while work remains. "
            "Do not mark a step as 'completed' unless it has actually been completed or verified. "
            "Do not add unrelated new steps, remove important remaining steps, or rewrite the plan strategy. "
        ),
    )

    runtime: ToolRuntime


class UpdateChecklist(BaseTool):
    name: str = "update_checklist"
    description: str = (
        "make a minor revision for the current plan checklist. "
        "Use this tool for applying a minor checklist refinement during execution. "
        "The input must be the complete minor revised checklist, not only the changed item. "
        "This tool compares the original checklist with the proposed updated checklist and asks for user confirmation "
        "before writing the update to state. "
        "Use this tool only for small checklist edits. "
        "Do not use it to create the initial plan, rewrite the planning brief, change the overall strategy, "
        "or perform the task itself. "
        "Do not use it to advance the checklist."
        "Normally keep exactly one checklist item as 'in_progress' while work remains"
    )
    args_schema: type[BaseModel] = UpdateChecklistInput

    def _run(self, updated_checklist: list, runtime: ToolRuntime):
        plan = runtime.state.get("plan", {})
        original_checklist = plan.get("checklist", [])

        if not original_checklist:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="No plan checklist exists. Create a plan first before updating the checklist.",
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

        original_checklist_list = []
        for step in original_checklist:
            original_checklist_list.append(
                f"[] {step['step']}\t Status: {step['status']}"
            )

        original_todos_string = "\n".join(original_checklist_list)

        updated_checklist = _coerce_checklist(updated_checklist)

        updated_in_progress = _count_in_progress(updated_checklist)
        updated_checklist_string = _format_checklist(updated_checklist)

        if updated_in_progress > 1:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Do not set more than one checklist item to 'in_progress'. "
                                "Re-create the updated checklist with at most one active step:\n\n"
                                f"{updated_checklist_string}"
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

        checklist_context = (
            f"\n# Original checklist\n{original_todos_string}\n\n"
            f"# Proposed updated checklist\n{updated_checklist_string}\n"
        )

        comment = interrupt(
            f'{checklist_context}\nReply "yes" to approve the checklist update.\n'
            "Reply with comments if the checklist update needs refinement.\n"
        )

        if comment.strip().lower() in {
            "yes",
            "yeah",
            "yep",
            "ok",
            "correct",
            "good",
            "perfect",
            "no comment",
        }:
            return Command(
                update={
                    "plan": {
                        **plan,
                        "checklist": updated_checklist,
                    },
                    "messages": [
                        ToolMessage(
                            content=f"Checklist was updated:\n\n{updated_checklist_string}",
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "The proposed updated checklist needs further refinement:\n\n"
                            f"{updated_checklist_string}\n\n"
                            f"User comment: {comment}"
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )


class AdvanceChecklistInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    runtime: ToolRuntime


class AdvanceChecklist(BaseTool):
    name: str = "advance_checklist"
    description: str = (
        "Advance the current plan checklist by marking one step completed and moving the next pending step "
        "to 'in_progress'. Use this only after the single current 'in_progress' step has actually been completed. "
        "This tool is for routine progress advancement only; use update_checklist for manual checklist minor edits."
    )
    args_schema: type[BaseModel] = AdvanceChecklistInput

    def _run(self, runtime: ToolRuntime):
        plan = runtime.state.get("plan", {})
        original_checklist = plan.get("checklist", [])

        if not original_checklist:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="No plan checklist exists. Create a plan before advancing it.",
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

        checklist = _coerce_checklist(original_checklist)

        active_indices = [
            idx for idx, step in enumerate(checklist)
            if step.get("status") == "in_progress"
        ]

        if len(active_indices) > 1:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Checklist has more than one 'in_progress' step. "
                                "Use update_checklist to fix statuses before advancing:\n\n"
                                f"{_format_checklist(checklist)}"
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

        if not active_indices:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Checklist has no 'in_progress' step to advance. "
                                "Use update_checklist to mark the active step before advancing."
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

        completed_step_index = active_indices[0]

        next_pending_index = next(
            (
                idx for idx, step in enumerate(checklist[completed_step_index + 1:], start=completed_step_index + 1)
                if step.get("status") == "pending"
            ),
            None,
        )

        checklist[completed_step_index]["status"] = "completed"
        if next_pending_index is not None:
            checklist[next_pending_index]["status"] = "in_progress"


        verb = "completed" if next_pending_index is None else "advanced"

        return Command(
            update={
                "plan": {
                    **plan,
                    "checklist": checklist,
                },
                "messages": [
                    ToolMessage(
                        content=f"Checklist {verb}:\n\n{_format_checklist(checklist)}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )
