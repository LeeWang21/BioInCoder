from typing import Type, Literal
from pydantic import BaseModel, Field, ConfigDict
from langchain.tools import BaseTool, ToolRuntime 
from langchain.messages import HumanMessage, ToolMessage

from langgraph.types import Command, interrupt


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

    def _run(self, objective: str, runtime: ToolRuntime) -> str:
        from AgentConfigSetup import agent_registry

        planner_agent = agent_registry.build_agent(agent_name="planner")

        coder_msgs = runtime.state.get("messages", [])

        coder_msgs_sanitization = coder_msgs
        if coder_msgs_sanitization and getattr(coder_msgs_sanitization[-1], "tool_calls", None):
            coder_msgs_sanitization = coder_msgs_sanitization[:-1]


        planner_instruction = HumanMessage(
            content=(
                "Create or update the execution plan for the following objective.\n\n"
                f"# Objective\n{objective}\n\n"
                "Use the current conversation and runtime state as context. "
                "If a plan already exists in context, update it instead of starting from scratch. "
                "Return only the required PlanOutputFormat structured output."
            )
        )

        plan_state = planner_agent.invoke(
            {
                "messages": coder_msgs_sanitization + [planner_instruction],
            }
        )

        plan_context = plan_state["messages"][-1].content

        return Command(
            update = {
                "plan_required": plan_state["plan_required"],
                "plan": plan_state["plan"],
                "messages": [ToolMessage(content=plan_context, tool_call_id=runtime.tool_call_id)]
            }
        )
    


class PlanChecklistStep(BaseModel):
    step: str = Field(
        ...,
        description=(
            "A short, concrete, verifiable checklist step. "
            "It should describe one meaningful unit of work. "
            "Keep the original step wording when only updating status."
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


class UpdateChecklistInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    updated_checklist: list[PlanChecklistStep] = Field(
        ...,
        description=(
            "The complete revised checklist that should replace the current plan checklist. "
            "Pass the full checklist, not only the changed step. "
            "Each item must preserve the original task meaning unless a minor revision is needed. "
            "Use this to update progress status after completing a step, starting the next step, "
            "or making a small checklist refinement during execution. "
            "Use only these statuses: 'pending', 'in_progress', and 'completed'. "
            "Normally there should be exactly one 'in_progress' step while work remains. "
            "If the whole task is finished, all steps should be 'completed'. "
            "Do not mark a step as 'completed' unless it has actually been completed or verified. "
            "Do not add unrelated new steps, remove important remaining steps, or rewrite the plan strategy. "
            "For major plan changes, create or reset the plan instead of using this checklist update tool."
        ),
    )

    runtime: ToolRuntime


class UpdateChecklist(BaseTool):
    name: str = "update_checklist"
    description: str = (
        "Update the current plan checklist in graph state. "
        "Use this tool after meaningful progress has been made, such as marking a completed step as 'completed', "
        "moving the next step to 'in_progress', or applying a minor checklist refinement during execution. "
        "The input must be the complete revised checklist, not only the changed item. "
        "This tool compares the original checklist with the proposed updated checklist and asks for user confirmation "
        "before writing the update to state. "
        "Use this tool only for checklist progress/status updates or small checklist edits. "
        "Do not use it to create the initial plan, rewrite the planning brief, change the overall strategy, "
        "or perform the task itself. "
        "Normally keep exactly one checklist item as 'in_progress' while work remains; "
        "when the task is fully complete, mark all checklist items as 'completed'."
    )
    args_schema: type[BaseModel] = UpdateChecklistInput

    def _run(self, updated_checklist: list, runtime: ToolRuntime):
        original_checklist = runtime.state["plan"]["checklist"]

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

        updated_checklist = [
            step.model_dump() if hasattr(step, "model_dump") else step
            for step in updated_checklist
        ]

        updated_checklist_list = []
        updated_in_progress = 0

        for step in updated_checklist:
            updated_in_progress += step["status"] == "in_progress"
            updated_checklist_list.append(
                f"[] {step['step']}\t Status: {step['status']}"
            )

        updated_checklist_string = "\n".join(updated_checklist_list)

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
                        "overview": runtime.state["plan"]["overview"],
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
            
        

