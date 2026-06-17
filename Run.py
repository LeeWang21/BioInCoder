import argparse
import json
import os
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
except ImportError:  # pragma: no cover - runtime fallback for minimal environments
    PromptSession = None
    AutoSuggestFromHistory = None
    FileHistory = None


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


def clean_repl_input(text: str) -> tuple[str, bool]:
    cleaned_chars: list[str] = []
    changed = False
    for char in text:
        if char == "\x00":
            changed = True
            continue
        if ord(char) < 32 and char not in {"\t", "\n", "\r"}:
            changed = True
            continue
        cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars).strip()
    return cleaned, changed or cleaned != text.strip()


def make_prompt_session():
    if PromptSession is None or FileHistory is None or AutoSuggestFromHistory is None:
        return None
    history_path = Path.cwd() / ".bioincoder_history"
    return PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
    )


def read_repl_input(session, prompt: str) -> str | None:
    while True:
        try:
            if session is None:
                raw_input = input(prompt)
            else:
                raw_input = session.prompt(prompt)
        except KeyboardInterrupt:
            print("\nInput cleared. Use /exit to quit BioInCoder.")
            continue
        except EOFError:
            return None

        user_input, cleaned = clean_repl_input(raw_input)
        if cleaned:
            print("[input cleaned: removed terminal control characters]")
        if not user_input:
            continue
        return user_input


def is_hitl_interrupt(interrupt_info: Any) -> bool:
    return (
        isinstance(interrupt_info, dict)
        and isinstance(interrupt_info.get("action_requests"), list)
        and isinstance(interrupt_info.get("review_configs"), list)
    )


def format_hitl_interrupt(interrupt_info: dict) -> str:
    lines = ["\nShell/tool action requires approval."]
    action_requests = interrupt_info.get("action_requests", [])
    review_configs = interrupt_info.get("review_configs", [])

    for index, request in enumerate(action_requests, start=1):
        lines.append(f"\n[{index}] {request.get('name', 'tool')}")
        description = request.get("description")
        if description:
            lines.append(str(description))
        args = request.get("args", {})
        if args:
            lines.append("Args:")
            lines.append(json.dumps(args, ensure_ascii=False, indent=2, default=str))

    if review_configs:
        allowed = review_configs[0].get("allowed_decisions", [])
        if allowed:
            lines.append(f"\nAllowed decisions: {', '.join(allowed)}")

    lines.append('Reply "approve" to run, or "reject <reason>" to cancel.')
    return "\n".join(lines)


def make_hitl_resume(interrupt_info: dict, user_answer: str) -> Command:
    answer = user_answer.strip()
    answer_lower = answer.lower()
    action_count = len(interrupt_info.get("action_requests", [])) or 1

    if answer_lower in {"approve", "approved", "yes", "y", "ok", "run", "continue"}:
        decisions = [{"type": "approve"} for _ in range(action_count)]
        return Command(resume={"decisions": decisions})

    if answer_lower.startswith("reject"):
        message = answer[6:].strip() or "Rejected by user."
    elif answer_lower in {"no", "n", "cancel", "deny", "denied"}:
        message = "Rejected by user."
    else:
        message = answer or "Rejected by user."

    decisions = [{"type": "reject", "message": message} for _ in range(action_count)]
    return Command(resume={"decisions": decisions})


def make_resume_command(interrupt_info: Any, user_answer: str) -> Command:
    if is_hitl_interrupt(interrupt_info):
        return make_hitl_resume(interrupt_info, user_answer)
    return Command(resume=user_answer)


def main() -> None:
    args = parse_args()
    os.environ["BIOINCODER_USER_ID"] = args.user_id
    os.environ["BIOINCODER_SESSION_ID"] = args.session_id

    from AgentConfigSetup import multi_agent_runtime

    bioincoder = multi_agent_runtime.agent_registry.build_agent(agent_name="BioInCoder")
    config = {"configurable": {"thread_id": args.thread_id}}
    repl_session = make_prompt_session()

    print(
        "BioInCoder started "
        f"(user_id={args.user_id}, session_id={args.session_id}, thread_id={args.thread_id})."
    )
    if repl_session is None:
        print("prompt_toolkit is not available; falling back to basic input().")
    print("Use /exit or Ctrl-D to quit. Ctrl-C clears the current input line.")

    try:
        while True:
            user_input = read_repl_input(repl_session, "BioInCoder> ")
            if user_input is None:
                print("\nExiting.")
                break

            if user_input.lower() in {"exit", "quit", "/exit", "/quit"}:
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
                        if is_hitl_interrupt(interrupt_info):
                            print(format_hitl_interrupt(interrupt_info))
                            prompt = "BioInCoder approval> "
                        else:
                            print(interrupt_info)
                            prompt = "BioInCoder needs input> "

                        user_answer = read_repl_input(repl_session, prompt)
                        if user_answer is None:
                            print("\nExiting.")
                            return
                        if user_answer.lower() in {"/exit", "/quit"}:
                            print("Exiting.")
                            return
                        graph_input = make_resume_command(interrupt_info, user_answer)
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
