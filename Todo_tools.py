from typing import Type, Literal
from pydantic import BaseModel, Field, ConfigDict
from langchain.tools import BaseTool, ToolRuntime 
from langchain.messages import HumanMessage, ToolMessage

from langgraph.types import Command, interrupt
from Tool_utils import is_graph_interrupt, tool_error_command


class PlanChecklistStep(BaseModel):
    step: str = Field(
        ...,
        description=(
            "A short, concrete, verifiable checklist step. "
            "Describe one meaningful unit of work with a clear action and expected checkpoint. "
            "Prefer task-specific wording tied to the user's files, data, code, question, or deliverable. "
            "Avoid vague filler such as 'analyze data', 'do research', 'finalize', or optional future work. "
            "For steps without minor revision, keep the original step wording."
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


def _format_plan(plan: dict) -> str:
    checklist = _format_checklist(plan.get("checklist", []))
    return (
        f"# Plan overview\n{plan.get('overview', '')}\n\n"
        f"# Plan checklist\n{checklist}"
    )


class SetPlanInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True) #allow arbitrary types so Pydantic accepts ToolRuntime 

    overview: str = Field(
        ...,
        description=(
            "Markdown execution brief for the current task, based on the current conversation context. "
            "Make it sufficient for later execution without reconstructing the planning discussion. "
            "Include the user's goal, relevant context already known, important constraints, assumptions/defaults, "
            "proposed approach and order of work, validation or done criteria, and expected deliverable. "
            "Keep it concise and omit sections that do not matter for the task."
        ),
    )
    checklist: list[PlanChecklistStep] = Field(
        ...,
        description=(
            "Complete ordered execution checklist for the current task. "
            "Each item should be concrete, task-specific, sequential, and independently verifiable. "
            "Prefer 3-8 steps for most tasks. Split genuinely separate phases, but avoid over-fragmented micro-steps. "
            "Include validation or handoff as a checklist item when it is part of completion. "
            "Use exactly one 'in_progress' item while work remains, normally the first actionable step. "
            "Use only 'pending', 'in_progress', and 'completed'."
        ),
    )
    plan_required: bool = Field(
        True,
        description="Whether this task needs an explicit plan.",
    )
    runtime: ToolRuntime
    #Ref https://forum.langchain.com/t/how-to-access-tool-call-id-using-runtime/2166



class SetPlan(BaseTool):
    name: str = "set_plan"
    description: str = (
        "Create the initial plan or reset the current plan from the current conversation context. "
        "Use this tool when there is no plan yet and the task benefits from planning, "
        "or when a major replan is needed because the goal, strategy, overview, scope, or checklist structure has changed substantially. "
        "Provide a decision-complete overview and a complete ordered checklist directly in the tool arguments. "
        "The tool validates the plan, asks the user to approve/refine/skip it, and saves approved plans to state. "
        "Do not use this tool for simple one-step questions, direct factual answers, minor checklist edits, or routine progress advancement. "
        "For small checklist item revisions, use update_checklist. "
        "For only completing the current step and starting the next one, use advance_checklist. "
        "This tool only plans; it does not execute the task, modify files, run analysis, or produce the final deliverable."
    )
    args_schema: Type[BaseModel] = SetPlanInput

    def _run(
        self,
        runtime: ToolRuntime,
        overview: str,
        checklist: list[PlanChecklistStep],
        plan_required: bool = True,
    ):
        try:
            checklist = _coerce_checklist(checklist)
            overview = overview.strip()

            if plan_required and not overview:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="Plan overview is empty. Revise the plan overview and call set_plan again.",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ]
                    }
                )

            if plan_required and not checklist:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="Plan checklist is empty. Revise the checklist and call set_plan again.",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ]
                    }
                )

            checklist_in_progress = _count_in_progress(checklist)
            checklist_string = _format_checklist(checklist)

            if checklist_in_progress > 1:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=(
                                    "Do not set more than one checklist item to 'in_progress'. "
                                    "Revise the plan checklist and call set_plan again:\n\n"
                                    f"{checklist_string}"
                                ),
                                tool_call_id=runtime.tool_call_id,
                            )
                        ]
                    }
                )

            has_pending = any(step.get("status") == "pending" for step in checklist)
            if plan_required and has_pending and checklist_in_progress == 0:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=(
                                    "The checklist has pending work but no 'in_progress' item. "
                                    "Set exactly one active step and call set_plan again:\n\n"
                                    f"{checklist_string}"
                                ),
                                tool_call_id=runtime.tool_call_id,
                            )
                        ]
                    }
                )

            plan = {
                "plan_required": plan_required,
                "overview": overview,
                "checklist": checklist,
            }
            plan_context = _format_plan(plan)

            if not plan_required:
                return Command(
                    update={
                        "plan": plan,
                        "messages": [
                            ToolMessage(
                                content="Plan was marked as not required for this task.",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )

            comment = interrupt(
                f"{plan_context}\n\n"
                'Reply "yes" to approve the plan.\n'
                'Reply "exit" to continue without an explicit plan.\n'
                "Reply with comments if the plan needs refinement.\n"
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
                        "plan": plan,
                        "messages": [
                            ToolMessage(
                                content=f"Plan approved and saved:\n\n{plan_context}",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )

            if comment.strip().lower() in {"exit", "exiting", "quit"}:
                return Command(
                    update={
                        "plan": {
                            **plan,
                            "plan_required": False,
                        },
                        "messages": [
                            ToolMessage(
                                content="User chose to continue without an explicit plan.",
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
                                "The proposed plan needs refinement. "
                                "Revise the plan from the current conversation context and call set_plan again.\n\n"
                                f"# Proposed plan\n{plan_context}\n\n"
                                f"# User comment\n{comment}"
                            ),
                            tool_call_id=runtime.tool_call_id,
                        ),
                        HumanMessage(
                            content=(
                                "PLAN_REVISION_REQUIRED\n"
                                "The previous proposed plan was not approved by the user. "
                                "You must revise the plan according to the user's comment and call `set_plan` again as your next action. "                                f"User plan comment: {comment}"
                            )
                        )
                    ]
                }
            )
        except Exception as exc:
            if is_graph_interrupt(exc):
                raise
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="set_plan failed. Revise the overview/checklist and retry.",
            )
    


class UpdateChecklistInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    updated_checklist: list[PlanChecklistStep] = Field(
        ...,
        description=(
            "The complete minor-revised checklist that should replace the current plan checklist. "
            "Pass the full checklist, not only changed items. "
            "Use this only when checklist items need a small content or structure revision, such as adding, removing, splitting, merging, rewording, or reordering items. "
            "Statuses may be adjusted only as needed to keep the revised checklist coherent after those item changes. "
            "Do not use this when the only intended change is routine progress advancement. "
            "If the current in_progress step was completed and the next pending step should start, use advance_checklist instead. "
            "Do not use this to create or reset the plan."
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
        "Apply a minor revision to the current plan checklist. "
        "Use this tool when checklist item content or structure needs a small change during execution: "
        "add, remove, split, merge, reword, or reorder checklist items. "
        "The input must be the complete revised checklist, not only the changed items. "
        "Statuses may change only to keep the revised checklist coherent after item changes. "
        "This tool compares the original checklist with the proposed updated checklist and asks for user confirmation "
        "before writing the update to state. "
        "Do not use it to create the initial plan, reset the plan, rewrite the planning brief, change the overall strategy, "
        "or perform the task itself. "
        "Do not use it when the only change is marking the current step completed and moving to the next step; use advance_checklist for that. "
        "Normally keep exactly one checklist item as 'in_progress' while work remains."
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
        "Advance routine checklist progress without changing checklist content or structure. "
        "Use this only after the single current 'in_progress' step has actually been completed. "
        "It marks that step as 'completed' and moves the next pending step to 'in_progress'. "
        "Do not use this to add, remove, split, merge, reword, or reorder checklist items. "
        "For minor checklist item revisions, use update_checklist. "
        "For major replanning, use set_plan."
    )
    args_schema: type[BaseModel] = AdvanceChecklistInput

    def _run(self, runtime: ToolRuntime):
        try:
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
        except Exception as exc:
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="Failed to advance checklist. Inspect the current plan/checklist state.",
            )
