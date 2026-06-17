import re
from typing import Optional


SHELL_APPROVAL_RULES: list[tuple[str, str, str]] = [
    (
        "rm_recursive_force",
        r"(^|[;&|]\s*)rm\s+.*((-[^\s]*r[^\s]*f[^\s]*)|(-[^\s]*f[^\s]*r[^\s]*)|(-r\s+-f)|(-f\s+-r))",
        "Can recursively and forcefully delete files.",
    ),
    (
        "rm_root_or_home",
        r"(^|[;&|]\s*)rm\b.*(?:^|\s)(/|~|\$HOME)(?:/|\s|$)",
        "May delete root/home or broad paths.",
    ),
    (
        "git_clean_force",
        r"\bgit\s+clean\b.*(?:^|\s)-[^\s]*f[^\s]*(?:\s|$)",
        "Can delete untracked files.",
    ),
    (
        "git_reset_hard",
        r"\bgit\s+reset\b.*--hard\b",
        "Can discard working tree and index changes.",
    ),
    (
        "git_checkout_path",
        r"\bgit\s+checkout\b.*--\s+",
        "Can overwrite working tree files.",
    ),
    (
        "git_restore_path",
        r"\bgit\s+restore\b",
        "Can overwrite working tree files.",
    ),
    (
        "sudo",
        r"(^|[;&|]\s*)sudo\b",
        "Runs commands with elevated privileges.",
    ),
    (
        "chmod",
        r"(^|[;&|]\s*)chmod\b",
        "Changes file permissions.",
    ),
    (
        "chown",
        r"(^|[;&|]\s*)chown\b",
        "Changes file ownership.",
    ),
    (
        "chgrp",
        r"(^|[;&|]\s*)chgrp\b",
        "Changes file group ownership.",
    ),
    (
        "system_package_manager",
        r"\b(apt|apt-get|yum|dnf|brew)\s+(install|remove|upgrade|update|uninstall)\b",
        "Changes system packages.",
    ),
    (
        "pip_install",
        r"\bpip(3)?\s+install\b",
        "Installs Python packages and changes the environment.",
    ),
    (
        "pip_uninstall",
        r"\bpip(3)?\s+uninstall\b",
        "Removes Python packages and changes the environment.",
    ),
    (
        "pip_sync",
        r"\bpip-sync\b",
        "Synchronizes Python packages and changes the environment.",
    ),
    (
        "conda_mutation",
        r"\bconda\s+(install|remove|uninstall|update|upgrade|env\s+create|env\s+remove)\b",
        "Changes conda packages or environments.",
    ),
    (
        "mamba_mutation",
        r"\bmamba\s+(install|remove|uninstall|update|upgrade|env\s+create|env\s+remove)\b",
        "Changes conda packages or environments.",
    ),
    (
        "uv_mutation",
        r"\buv\s+(pip\s+install|pip\s+uninstall|sync|add|remove)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "poetry_mutation",
        r"\bpoetry\s+(add|remove|install|update)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "pipenv_mutation",
        r"\bpipenv\s+(install|uninstall|sync|update)\b",
        "Changes Python packages or project dependencies.",
    ),
    (
        "npm_mutation",
        r"\bnpm\s+(install|uninstall|update|audit\s+fix)\b",
        "Changes Node dependencies.",
    ),
    (
        "pnpm_mutation",
        r"\bpnpm\s+(install|remove|update|add)\b",
        "Changes Node dependencies.",
    ),
    (
        "yarn_mutation",
        r"\byarn\s+(add|remove|install|upgrade)\b",
        "Changes Node dependencies.",
    ),
    (
        "ruby_bundle_mutation",
        r"\bbundle\s+(install|update|add|remove)\b",
        "Changes Ruby dependencies.",
    ),
    (
        "cargo_install",
        r"\bcargo\s+install\b",
        "Installs Rust binaries or packages.",
    ),
    (
        "curl_pipe_shell",
        r"\bcurl\b.*\|\s*(sh|bash|zsh|python|python3)\b",
        "Downloads and executes remote code.",
    ),
    (
        "wget_pipe_shell",
        r"\bwget\b.*\|\s*(sh|bash|zsh|python|python3)\b",
        "Downloads and executes remote code.",
    ),
    (
        "remote_shell",
        r"\bssh\b",
        "Opens a remote shell/session.",
    ),
    (
        "remote_copy",
        r"\b(scp|sftp)\b",
        "Transfers files to or from a remote host.",
    ),
    (
        "kill_all",
        r"\b(killall|pkill)\b",
        "Can terminate many processes.",
    ),
    (
        "service_control",
        r"\b(systemctl|launchctl|service)\b",
        "Controls system services.",
    ),
]


def normalize_shell_command(command: str) -> str:
    return " ".join(command.strip().split())


def shell_approval_reason(command: str) -> Optional[tuple[str, str]]:
    command = normalize_shell_command(command)
    for name, pattern, description in SHELL_APPROVAL_RULES:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return name, description
    return None
