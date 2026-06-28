from __future__ import annotations

import argparse
import sys
from pathlib import Path

from Persistence import artifacts_root


def _add_session_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user-id", default=None, help="BioInCoder user id.")
    parser.add_argument("--session-id", default=None, help="BioInCoder session id.")
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Advanced: optional sub-thread id under the same session.",
    )


def _cmd_run(args: argparse.Namespace) -> int:
    import os

    if sys.version_info < (3, 10):
        print(
            "BioInCoder requires Python >= 3.10 for the current LangChain/LangGraph stack. "
            f"Current Python is {sys.version.split()[0]}. "
            "Set BIOINCODER_PYTHON=/path/to/python3.10+ and rerun."
        )
        return 1

    user_id = args.user_id or os.environ.get("BIOINCODER_USER_ID", "default_user")
    session_id = args.session_id or os.environ.get("BIOINCODER_SESSION_ID", "default_session")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set.")
        print("Run: export DEEPSEEK_API_KEY='<your-key>'")
        return 1

    from Run import run_repl

    run_repl(user_id=user_id, session_id=session_id, thread_id=args.thread_id)
    return 0


def _cmd_validate_skills(args: argparse.Namespace) -> int:
    import validate_skills

    return validate_skills.main()


def _session_rows() -> list[tuple[str, str, Path, int]]:
    sessions_root = artifacts_root() / "sessions"
    if not sessions_root.exists():
        return []

    rows: list[tuple[str, str, Path, int]] = []
    for user_dir in sorted(path for path in sessions_root.iterdir() if path.is_dir()):
        for session_dir in sorted(path for path in user_dir.iterdir() if path.is_dir()):
            messages_dir = session_dir / "messages"
            message_count = len(list(messages_dir.glob("*.json"))) if messages_dir.exists() else 0
            rows.append((user_dir.name, session_dir.name, session_dir, message_count))
    return rows


def _cmd_list_sessions(args: argparse.Namespace) -> int:
    rows = _session_rows()
    if not rows:
        print(f"No sessions found under {artifacts_root() / 'sessions'}")
        return 0

    print(f"Sessions under {artifacts_root() / 'sessions'}:")
    for user_id, session_id, session_dir, message_count in rows:
        print(
            f"- user_id={user_id} session_id={session_id} "
            f"saved_message_refs={message_count} path={session_dir}"
        )
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
