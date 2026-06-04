
from AgentConfigSetup import agent_registry
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command


if __name__ == "__main__":

    #build agent
    BioInCoder = agent_registry.build_agent(agent_name = "BioInCoder")

    thread_id = str("001")
    config = {"configurable": {"thread_id": thread_id}}

    try:

        while True:
            user_input = input("you> ").strip()

            if user_input.lower() in {"exit", "quit"}:
                print("Exiting.")
                break

            graph_input = {
                "messages": [HumanMessage(content=user_input)]
                }

            while True:
                interrupted = False

                for chunk in BioInCoder.stream(graph_input, config = config, stream_mode=["updates"], version="v2", subgraphs=True):
                    if "__interrupt__" in chunk["data"]:
                        interrupt_info = chunk["data"]["__interrupt__"][0].value
                        print(interrupt_info)
                        user_answer = input("\nYour answer> ").strip()
                        graph_input = Command(resume=user_answer)
                        interrupted = True
                        break
                    else:
                        for update in chunk["data"].values():
                            if update is None:
                                pass
                            else:
                                if "messages" in update:
                                    if isinstance(update["messages"], list):
                                        for msg in update["messages"]:
                                            if isinstance(msg, AIMessage) and msg.content:
                                                print(f"\n----------\nAI Message\n----------\n{msg.content}\n\n")
                                            elif isinstance(msg, ToolMessage) and msg.content:
                                                print(f"\n----------\nTool Message\n----------\n{msg.content}\n\n")
                                            else:
                                                pass                 
                if not interrupted:
                    break
    finally:
        print("Shutting down all kernel sessions...")

