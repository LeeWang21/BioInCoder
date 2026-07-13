from __future__ import annotations

import argparse
import sys
from pathlib import Path

from EnvConfig import load_env_file
from Persistence import artifacts_root, generate_session_id
from Transcript import (
    DEFAULT_HISTORY_LIMIT,
    TranscriptStore,
    format_entries,
    format_subagent_transcript_payload,
    format_subagent_transcript_refs,
    list_subagent_transcript_refs,
    read_subagent_transcript_payload,
)

load_env_file()


def _add_session_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    parser.add_argument("--session-id", default=None, help="BioInCoder session id.")


def _cmd_run(args: argparse.Namespace) -> int:
    import os

    user_id = args.user_id or os.environ.get("BIOINCODER_USER_ID")
    if not user_id:
        print("BIOINCODER_USER_ID is not set.")
        print("Run with --user-id <name>, or export BIOINCODER_USER_ID=<name>.")
        return 1

    session_id = args.session_id or os.environ.get("BIOINCODER_SESSION_ID") or generate_session_id()

    if sys.version_info < (3, 10):
        print(
            "BioInCoder requires Python >= 3.10 for the current LangChain/LangGraph stack. "
            f"Current Python is {sys.version.split()[0]}. "
            "Set BIOINCODER_PYTHON=/path/to/python3.10+ and rerun."
        )
        return 1

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set.")
        print("Run: export DEEPSEEK_API_KEY='<your-key>'")
        return 1

    from Run import run_repl

    run_repl(user_id=user_id, session_id=session_id)
    return 0


def _cmd_validate_skills(args: argparse.Namespace) -> int:
    import validate_skills

    return validate_skills.main()


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _session_rows() -> list[tuple[str, str, Path, int, int]]:
    sessions_root = artifacts_root() / "sessions"
    if not sessions_root.exists():
        return []

    rows: list[tuple[str, str, Path, int, int]] = []
    for user_dir in sorted(path for path in sessions_root.iterdir() if path.is_dir()):
        for session_dir in sorted(path for path in user_dir.iterdir() if path.is_dir()):
            subagent_dir = session_dir / "subagent_transcripts"
            message_count = len(list(subagent_dir.glob("*.json"))) if subagent_dir.exists() else 0
            transcript_count = TranscriptStore(user_dir.name, session_dir.name).count()
            rows.append((user_dir.name, session_dir.name, session_dir, message_count, transcript_count))
    return rows


def _cmd_list_sessions(args: argparse.Namespace) -> int:
    rows = _session_rows()
    if not rows:
        print(f"No sessions found under {artifacts_root() / 'sessions'}")
        return 0

    print(f"Sessions under {artifacts_root() / 'sessions'}:")
    for user_id, session_id, session_dir, message_count, transcript_count in rows:
        print(
            f"- user_id={user_id} session_id={session_id} "
            f"transcript_entries={transcript_count} "
            f"subagent_transcripts={message_count} path={session_dir}"
        )
    return 0


def _session_ids_from_args(args: argparse.Namespace) -> tuple[str, str]:
    import os

    user_id = args.user_id or os.environ.get("BIOINCODER_USER_ID")
    if not user_id:
        raise ValueError("Provide --user-id or set BIOINCODER_USER_ID.")
    session_id = args.session_id or os.environ.get("BIOINCODER_SESSION_ID")
    if not session_id:
        raise ValueError("Provide --session-id or set BIOINCODER_SESSION_ID.")
    return user_id, session_id


def _cmd_transcript_show(args: argparse.Namespace) -> int:
    try:
        user_id, session_id = _session_ids_from_args(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    transcript = TranscriptStore(user_id=user_id, session_id=session_id)
    print(format_entries(transcript.read_recent(args.limit)))
    return 0


def _cmd_transcript_path(args: argparse.Namespace) -> int:
    try:
        user_id, session_id = _session_ids_from_args(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    transcript = TranscriptStore(user_id=user_id, session_id=session_id)
    print(transcript.path)
    return 0


def _cmd_transcript_subagents(args: argparse.Namespace) -> int:
    try:
        user_id, session_id = _session_ids_from_args(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(format_subagent_transcript_refs(list_subagent_transcript_refs(user_id, session_id)))
    return 0


def _cmd_transcript_subagent(args: argparse.Namespace) -> int:
    try:
        user_id, session_id = _session_ids_from_args(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    try:
        payload = read_subagent_transcript_payload(
            user_id=user_id,
            session_id=session_id,
            channel_name=args.channel,
            request_id=args.request_id,
        )
        print(format_subagent_transcript_payload(payload, output_format=args.format))
    except Exception as exc:
        print(f"Could not read subagent transcript: {exc}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bioincoder",
        description="BioInCoder command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the interactive BioInCoder REPL.")
    _add_session_args(run_parser)
    run_parser.set_defaults(func=_cmd_run)

    skills_parser = subparsers.add_parser("skills", help="Skill registry commands.")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    validate_parser = skills_subparsers.add_parser("validate", help="Validate SKILL.md metadata.")
    validate_parser.set_defaults(func=_cmd_validate_skills)

    sessions_parser = subparsers.add_parser("sessions", help="Session artifact commands.")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command")
    list_parser = sessions_subparsers.add_parser("list", help="List saved session artifact directories.")
    list_parser.set_defaults(func=_cmd_list_sessions)

    transcript_parser = subparsers.add_parser("transcript", help="Main and subagent transcript commands.")
    transcript_subparsers = transcript_parser.add_subparsers(dest="transcript_command")

    transcript_show_parser = transcript_subparsers.add_parser("show", help="Show recent main conversation transcript entries.")
    transcript_show_parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    transcript_show_parser.add_argument("--session-id", default=None, help="BioInCoder session id.")
    transcript_show_parser.add_argument(
        "--limit",
        type=_positive_int,
        default=DEFAULT_HISTORY_LIMIT,
        help=f"Number of recent transcript entries to show. Default: {DEFAULT_HISTORY_LIMIT}.",
    )
    transcript_show_parser.set_defaults(func=_cmd_transcript_show)

    transcript_path_parser = transcript_subparsers.add_parser("path", help="Print the main transcript file path.")
    transcript_path_parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    transcript_path_parser.add_argument("--session-id", default=None, help="BioInCoder session id.")
    transcript_path_parser.set_defaults(func=_cmd_transcript_path)

    transcript_subagents_parser = transcript_subparsers.add_parser("subagents", help="List saved subagent transcripts.")
    transcript_subagents_parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    transcript_subagents_parser.add_argument("--session-id", default=None, help="BioInCoder session id.")
    transcript_subagents_parser.set_defaults(func=_cmd_transcript_subagents)

    transcript_subagent_parser = transcript_subparsers.add_parser("subagent", help="Read one saved subagent transcript.")
    transcript_subagent_parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    transcript_subagent_parser.add_argument("--session-id", default=None, help="BioInCoder session id.")
    transcript_subagent_parser.add_argument("--channel", required=True, help="Subagent transcript channel name.")
    transcript_subagent_parser.add_argument("--request-id", required=True, help="Subagent transcript request id.")
    transcript_subagent_parser.add_argument("--format", choices=["prefix", "json"], default="prefix")
    transcript_subagent_parser.set_defaults(func=_cmd_transcript_subagent)

    return parser


def _normalize_legacy_args(argv: list[str]) -> list[str]:
    if argv and argv[0] not in {"-h", "--help"} and argv[0].startswith("-"):
        return ["run", *argv]
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_legacy_args(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 2

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
