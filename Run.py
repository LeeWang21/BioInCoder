import argparse
import json
import os
from pathlib import Path
from typing import Any

from EnvConfig import load_env_file
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from Persistence import generate_session_id, graph_thread_id
from Transcript import (
    DEFAULT_HISTORY_LIMIT,
    TranscriptStore,
    format_entries,
    format_subagent_transcript_refs,
)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
except ImportError:  # pragma: no cover - runtime fallback for minimal environments
    PromptSession = None
    AutoSuggestFromHistory = None
    FileHistory = None

load_env_file()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BioInCoder CLI.")
    parser.add_argument("--user-id", default=os.environ.get("BIOINCODER_USER_ID"))
    parser.add_argument("--session-id", default=os.environ.get("BIOINCODER_SESSION_ID"))
    return parser.parse_args(argv)


def print_message_update(update: dict, transcript: TranscriptStore | None = None) -> None:
    if "messages" not in update or not isinstance(update["messages"], list):
        return

    for msg in update["messages"]:
        if isinstance(msg, AIMessage) and msg.content:
            print(f"\n----------\nAI Message\n----------\n{msg.content}\n\n")
            if transcript is not None:
                transcript.append(
                    "assistant",
                    str(msg.content),
                    metadata={"message_type": type(msg).__name__},
                )
        elif isinstance(msg, ToolMessage) and msg.content:
            print(f"\n----------\nTool Message\n----------\n{msg.content}\n\n")
            if transcript is not None:
                transcript.append(
                    "tool",
                    str(msg.content),
                    metadata={
                        "message_type": type(msg).__name__,
                        "tool_call_id": getattr(msg, "tool_call_id", None),
                    },
                )


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
        if request.get("name") == "Bash" and isinstance(args, dict):
            command = args.get("commands") or args.get("command") or args.get("query")
            if command:
                try:
                    from Shell_approval_rules import shell_approval_reason

                    reason = shell_approval_reason(str(command))
                    if reason:
                        reason_name, reason_description = reason
                        lines.append(f"Risk reason: {reason_name} - {reason_description}")
                    else:
                        lines.append(
                            "Risk reason: no local shell approval rule matched. "
                            "If this approval was unexpected, check the installed LangChain version."
                        )
                except Exception as exc:
                    lines.append(f"Risk reason unavailable: {type(exc).__name__}: {exc}")
        if args:
            lines.append("Args:")
            lines.append(json.dumps(args, ensure_ascii=False, indent=2, default=str))

    if review_configs:
        allowed = review_configs[0].get("allowed_decisions", [])
        if allowed:
            lines.append(f"\nAllowed decisions: {', '.join(allowed)}")

    lines.append('Reply "approve" to run, or "reject <reason>" to cancel with feedback.')
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


def parse_transcript_limit(parts: list[str]) -> int:
    if not parts:
        return DEFAULT_HISTORY_LIMIT
    if len(parts) == 1 and parts[0].isdigit():
        value = parts[0]
    if len(parts) == 2 and parts[0] == "show":
        value = parts[1]
    elif len(parts) == 1 and parts[0] == "show":
        return DEFAULT_HISTORY_LIMIT
    elif not (len(parts) == 1 and parts[0].isdigit()):
        raise ValueError("Usage: /transcript [show [n] | path | subagents | subagent <channel> <request_id> [prefix|xml]]")
    try:
        limit = int(value)
    except ValueError as exc:
        raise ValueError("Transcript limit must be a positive integer.") from exc
    if limit <= 0:
        raise ValueError("Transcript limit must be a positive integer.")
    return limit


def repl_subagent_transcript_refs(runtime: Any) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for channel_name, requests in runtime.message_container.channels.items():
        if requests:
            refs[channel_name] = list(requests.keys())
    return refs


def handle_repl_command(command: str, transcript: TranscriptStore, runtime: Any | None = None) -> bool:
    command = command.strip()
    command_lower = command.lower()
    if not (command_lower == "/transcript" or command_lower.startswith("/transcript ")):
        return False

    parts = command.split()[1:]
    parts_lower = [part.lower() for part in parts]

    if not parts or parts_lower[0] == "show" or (len(parts) == 1 and parts[0].isdigit()):
        try:
            limit = parse_transcript_limit(parts_lower)
        except ValueError as exc:
            print(str(exc))
            return True
        print(format_entries(transcript.read_recent(limit)))
        return True

    if parts_lower == ["path"]:
        print(f"Transcript: {transcript.path}")
        return True

    if parts_lower == ["subagents"]:
        if runtime is None:
            print("(subagent transcripts are unavailable before runtime initialization)")
        else:
            print(format_subagent_transcript_refs(repl_subagent_transcript_refs(runtime)))
        return True

    if len(parts) in {3, 4} and parts_lower[0] == "subagent":
        if runtime is None:
            print("(subagent transcripts are unavailable before runtime initialization)")
            return True
        output_format = parts[3].lower() if len(parts) == 4 else "prefix"
        if output_format not in {"prefix", "xml"}:
            print("Subagent transcript format must be 'prefix' or 'xml'.")
            return True
        try:
            print(runtime.read_messages_as_context(parts[1], parts[2], format=output_format))
        except Exception as exc:
            print(f"Could not read subagent transcript: {exc}")
        return True

    print("Usage: /transcript [show [n] | path | subagents | subagent <channel> <request_id> [prefix|xml]]")
    return True


def unpack_stream_chunk(chunk: Any) -> tuple[Any, dict]:
    if isinstance(chunk, tuple) and len(chunk) == 2:
        namespace, data = chunk
        return namespace, data or {}
    if isinstance(chunk, dict):
        namespace = chunk.get("namespace") or chunk.get("path") or ()
        data = chunk.get("data", chunk)
        return namespace, data or {}
    return (), {}


def is_top_level_namespace(namespace: Any) -> bool:
    return namespace in (None, "", (), [])


def run_repl(user_id: str, session_id: str, thread_id: str | None = None) -> None:
    os.environ["BIOINCODER_USER_ID"] = user_id
    os.environ["BIOINCODER_SESSION_ID"] = session_id

    from AgentConfigSetup import multi_agent_runtime

    bioincoder = multi_agent_runtime.agent_registry.build_agent(agent_name="BioInCoder")
    internal_thread_id = graph_thread_id(user_id, session_id, thread_id)
    config = {"configurable": {"thread_id": internal_thread_id}}
    repl_session = make_prompt_session()
    transcript = TranscriptStore(user_id=user_id, session_id=session_id)

    print(
        "BioInCoder started "
        f"(user_id={user_id}, session_id={session_id}, "
        f"checkpoint_thread_id={internal_thread_id})."
    )
    print(
        "To resume this session later:\n"
        f"  python3 bioincoder_cli.py run --user-id {user_id} --session-id {session_id}"
    )
    print(f"Transcript: {transcript.path}")
    print(f"Previous transcript entries: {transcript.count()}")
    if repl_session is None:
        print("prompt_toolkit is not available; falling back to basic input().")
    print("Use /transcript, /transcript path, /exit, or Ctrl-D. Ctrl-C clears the current input line.")

    try:
        while True:
            user_input = read_repl_input(repl_session, "BioInCoder> ")
            if user_input is None:
                print("\nExiting.")
                break

            if user_input.lower() in {"exit", "quit", "/exit", "/quit"}:
                print("Exiting.")
                break

            if handle_repl_command(user_input, transcript, runtime=multi_agent_runtime):
                continue

            transcript.append("user", user_input)
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
                    namespace, chunk_data = unpack_stream_chunk(chunk)
                    should_record_transcript = is_top_level_namespace(namespace)

                    if "__interrupt__" in chunk_data:
                        interrupt_info = chunk_data["__interrupt__"][0].value
                        if is_hitl_interrupt(interrupt_info):
                            print(format_hitl_interrupt(interrupt_info))
                            prompt = "BioInCoder approval> "
                        else:
                            print(interrupt_info)
                            prompt = "BioInCoder needs input> "

                        while True:
                            user_answer = read_repl_input(repl_session, prompt)
                            if user_answer is None:
                                print("\nExiting.")
                                return
                            if user_answer.lower() in {"/exit", "/quit"}:
                                print("Exiting.")
                                return
                            if not handle_repl_command(user_answer, transcript, runtime=multi_agent_runtime):
                                break
                        transcript.append(
                            "user",
                            user_answer,
                            metadata={"kind": "interrupt_resume"},
                        )
                        graph_input = make_resume_command(interrupt_info, user_answer)
                        interrupted = True
                        break

                    for update in chunk_data.values():
                        if update is not None:
                            print_message_update(
                                update,
                                transcript=transcript if should_record_transcript else None,
                            )

                if not interrupted:
                    break
    finally:
        multi_agent_runtime.jupyter_registry.shutdown_all()
        print("Shut down all Jupyter kernel sessions.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.user_id:
        raise SystemExit(
            "BIOINCODER_USER_ID is not set.\n"
            "Run with --user-id <name>, or export BIOINCODER_USER_ID=<name>."
        )
    session_id = args.session_id or generate_session_id()
    run_repl(
        user_id=args.user_id,
        session_id=session_id,
    )


if __name__ == "__main__":
    main()
