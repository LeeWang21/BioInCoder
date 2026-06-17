#!/usr/bin/env python3
"""Validate BioInCoder skill frontmatter conventions."""

from pathlib import Path
import sys

from Skill import Skill


ALLOWED_TOP_LEVEL = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
}

FORBIDDEN_METADATA = {
    "primary_tool",
}


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    frontmatter, _ = Skill._parse_frontmatter(content)

    if not frontmatter:
        return ["missing or invalid YAML frontmatter"]

    extra_top_level = sorted(set(frontmatter) - ALLOWED_TOP_LEVEL)
    if extra_top_level:
        errors.append(f"unexpected top-level keys: {', '.join(extra_top_level)}")

    skill = Skill.from_skill_md(path)
    if skill is None:
        errors.append("Skill.from_skill_md could not parse name/description")
        return errors

    metadata = skill.metadata
    if not isinstance(metadata, dict):
        errors.append("metadata must be a mapping")
        return errors

    for key in sorted(FORBIDDEN_METADATA & set(metadata)):
        errors.append(f"metadata.{key} is forbidden; use metadata.primary_tools")

    if "tool_type" not in metadata:
        errors.append("metadata.tool_type is required")

    primary_tools = metadata.get("primary_tools")
    if not isinstance(primary_tools, list) or not primary_tools:
        errors.append("metadata.primary_tools must be a non-empty list")

    intended_agent = metadata.get("intended_agent")
    if intended_agent is not None and not isinstance(intended_agent, list):
        errors.append("metadata.intended_agent must be a list when present")

    return errors


def main() -> int:
    skill_paths = sorted(Path("skills").glob("**/SKILL.md"))
    all_errors: list[tuple[Path, list[str]]] = []

    for path in skill_paths:
        errors = validate_skill(path)
        if errors:
            all_errors.append((path, errors))

    if all_errors:
        for path, errors in all_errors:
            print(f"{path}:")
            for error in errors:
                print(f"  - {error}")
        return 1

    print(f"Validated {len(skill_paths)} skills.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
