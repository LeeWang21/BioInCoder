import argparse
import os

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BioInCoder CLI.")
    parser.add_argument("--user-id", default=os.environ.get("BIOINCODER_USER_ID", "default_user"))
    parser.add_argument("--session-id", default=os.environ.get("BIOINCODER_SESSION_ID", "default_session"))
    parser.add_argument("--thread-id", default=os.environ.get("BIOINCODER_THREAD_ID", "001"))
    return parser.parse_args()


def print_message_update(update: dict) -> None:
    if "messages" not in update or not isinstance(update["messages"], list):
        return

    for msg in update["messages"]:
        if isinstance(msg, AIMessage) and msg.content:
            print(f"\n----------\nAI Message\n----------\n{msg.content}\n\n")
        elif isinstance(msg, ToolMessage) and msg.content:
            print(f"\n----------\nTool Message\n----------\n{msg.content}\n\n")


def main() -> None:
    args = parse_args()
    os.environ["BIOINCODER_USER_ID"] = args.user_id
    os.environ["BIOINCODER_SESSION_ID"] = args.session_id

    from AgentConfigSetup import multi_agent_runtime

    bioincoder = multi_agent_runtime.agent_registry.build_agent(agent_name="BioInCoder")
    config = {"configurable": {"thread_id": args.thread_id}}

    print(
        "BioInCoder started "
        f"(user_id={args.user_id}, session_id={args.session_id}, thread_id={args.thread_id})."
    )

    try:
        while True:
            user_input = input("you> ").strip()

            if user_input.lower() in {"exit", "quit"}:
                print("Exiting.")
                break

            graph_input = {"messages": [HumanMessage(content=user_input)]}

            while True:
                interrupted = False

                for chunk in bioincoder.stream(
                    graph_input,
                    config=config,
                    stream_mode=["updates"],
                    version="v2",
                    subgraphs=True,
                ):
                    if "__interrupt__" in chunk["data"]:
                        interrupt_info = chunk["data"]["__interrupt__"][0].value
                        print(interrupt_info)
                        user_answer = input("\nYour answer> ").strip()
                        graph_input = Command(resume=user_answer)
                        interrupted = True
                        break

                    for update in chunk["data"].values():
                        if update is not None:
                            print_message_update(update)

                if not interrupted:
                    break
    finally:
        multi_agent_runtime.jupyter_registry.shutdown_all()
        print("Shut down all Jupyter kernel sessions.")


if __name__ == "__main__":
    main()
