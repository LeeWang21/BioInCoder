from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder



def ContextConcat(
    main_channel: str,
    secondary_channel: str,
    goal: str,
    agent_from: str,
    agent_to: str,
    task: str,
    agent_instruction: str,
    extra_instruction: str,
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


class ContextCompactor:
    pass