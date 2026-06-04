from typing import TypedDict, Optional, Literal

from langchain.agents.middleware import (
    before_agent,
    before_model,
    after_model,
    after_agent,
    wrap_model_call,
    wrap_tool_call,
    AgentMiddleware,
    AgentState
)

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt
from langgraph.runtime import Runtime


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

        if structured_out is None:
            return None
        
        if hasattr(structured_out, "model_dump"):
            out_dict = structured_out.model_dump()
        elif isinstance(structured_out, dict):
            out_dict = structured_out
        else:
            out_dict = dict(structured_out)
        
        return {
            "structured_response": out_dict,
            "plan": {
                "plan_required": structured_out.plan_required,
                "overview": structured_out.overview,
                "checklist": [step.model_dump() for step in structured_out.checklist]
            }
        }
    

@after_agent(can_jump_to=["model"])
def check_plan(state: AgentState, runtime: Runtime):
    plan = state.get("plan", {})

    if not plan["plan_required"]:
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
                "messages": [HumanMessage(content=f"current proposed checklist:\n{checklist_string}.\n Do not set more than one 'in_progress' for checklist status.")]
            }
            
            
        plan_context = f"\n#The proposed **plan overview** is: \n{plan_overview}\n\n#The proposed **plan checklist** is: \n{checklist_string}\n"

        comment = interrupt(f'''{plan_context}\nreply "yes" for plan execution.\nreply "exit" for no plan.\nreply comments for plan refinement.\n''')

        if comment.strip().lower() in {"yes", "yeah", "yep", "ok", "correct", "good", "perfect", "no comment"}:
            return {
                "messages": [HumanMessage(content=f"Final plan overview and plan TODO/checklist: {plan_context}")]
            }
            
        elif comment.strip().lower() in {"exit", "exiting", "quit"}:
            return {
                "messages": [HumanMessage(content=f"No plan needed for execution.")],
                "plan_required": False,
                "plan": {},
            }
        else:
            return {
                "messages": [HumanMessage(content=f"Refine the plan: {plan_context}. The comment is: {comment}")],
                "jump_to": "model"
            }
    

    