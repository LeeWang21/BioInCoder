#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill data class representing a loaded skill.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only without PyYAML
    yaml = None


@dataclass
class Skill:
    """Represents a loaded skill with its metadata and content."""

    name: str
    description: str
    content: str  # The markdown body (instructions)
    path: Path  # Path to the skill directory

    # Optional metadata from frontmatter
    license: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Source location type
    location: str = "project"  # project, user, managed

    @classmethod
    def from_skill_md(cls, skill_md_path: Path, location: str = "project") -> Optional["Skill"]:
        """
        Parse a SKILL.md file and create a Skill instance.

        Args:
            skill_md_path: Path to the SKILL.md file
            location: Where the skill was found (project, user, managed)

        Returns:
            Skill instance or None if parsing fails
        """
        if not skill_md_path.exists():
            return None

        content = skill_md_path.read_text(encoding='utf-8')
        frontmatter, body = cls._parse_frontmatter(content)

        if not frontmatter:
            return None

        name = frontmatter.get('name')
        description = frontmatter.get('description')

        if not name or not description:
            return None

        return cls(
            name=name,
            description=description,
            content=body.strip(),
            path=skill_md_path.parent,
            license=frontmatter.get('license'),
            allowed_tools=frontmatter.get('allowed-tools', []) or [],
            metadata=frontmatter.get('metadata', {}) or {},
            location=location,
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
        """
        Parse YAML frontmatter from markdown content.

        Args:
            content: Raw markdown content with potential YAML frontmatter

        Returns:
            Tuple of (frontmatter dict, body content)
        """
        # Match YAML frontmatter pattern: starts with ---, ends with ---
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            return {}, content

        yaml_content = match.group(1)
        body = match.group(2)

        if yaml is not None:
            try:
                frontmatter = yaml.safe_load(yaml_content) or {}
            except yaml.YAMLError:
                return {}, content
        else:
            frontmatter = Skill._parse_simple_yaml_frontmatter(yaml_content)

        return frontmatter, body

    @staticmethod
    def _parse_simple_yaml_frontmatter(yaml_content: str) -> Dict[str, Any]:
        """
        Minimal fallback parser for the simple SKILL.md frontmatter used here.

        Supports top-level scalar keys and one-level nested mapping blocks such
        as metadata. PyYAML is still preferred when installed.
        """
        parsed: Dict[str, Any] = {}
        current_map: Optional[str] = None

        for raw_line in yaml_content.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()

            if indent == 0:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if value == "":
                    parsed[key] = {}
                    current_map = key
                else:
                    parsed[key] = Skill._parse_simple_yaml_value(value)
                    current_map = None
                continue

            if current_map and indent >= 2 and ":" in line:
                key, value = line.split(":", 1)
                parsed.setdefault(current_map, {})[key.strip()] = Skill._parse_simple_yaml_value(value.strip())

        return parsed

    @staticmethod
    def _parse_simple_yaml_value(value: str) -> Any:
        value = value.strip()
        if not value:
            return ""
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [item.strip().strip('"').strip("'") for item in inner.split(",")]
        return value.strip('"').strip("'")

    def get_prompt(self) -> str:
        """
        Get the full prompt content for this skill.
        Includes the skill location header for resolving relative paths
        to bundled resources (references/, scripts/, assets/).

        Returns:
            Full prompt string with base directory header
        """
        header = f"""Loading: {self.name}
Base directory: {self.path}

"""
        return header + self.content

    @staticmethod
    def _normalize_agent_name(agent_name: str) -> str:
        return agent_name.lower().replace("_", "").replace("-", "").replace(" ", "")

    def is_available_to(self, agent_name: Optional[str]) -> bool:
        """
        Return whether this skill should be advertised to an agent.

        Skills without metadata.intended_agent are treated as top-level domain
        skills and are visible to BioInCoder and Planner by default. Subagent
        operation skills should set metadata.intended_agent explicitly.
        metadata.intended_agent can be a string or a list of strings.
        """
        intended = self.metadata.get("intended_agent")
        if not agent_name:
            return True

        normalized_agent = self._normalize_agent_name(agent_name)

        if not intended:
            return normalized_agent in {"bioincoder", "main", "coder", "planner", "plan", "planneragent"}

        if isinstance(intended, str):
            intended_agents = [intended]
        elif isinstance(intended, list):
            intended_agents = [str(item) for item in intended]
        else:
            return True

        aliases = {
            "bioincoder": {"bioincoder", "main", "coder"},
            "planner": {"planner", "plan", "planneragent"},
            "search": {"search", "searchagent"},
            "browser": {"browser", "browseragent"},
            "reader": {"reader", "read", "readagent"},
        }

        agent_keys = {normalized_agent}
        for canonical, names in aliases.items():
            if normalized_agent in names:
                agent_keys.add(canonical)
                agent_keys.update(names)

        normalized_intended = {self._normalize_agent_name(item) for item in intended_agents}
        if "all" in normalized_intended or "any" in normalized_intended:
            return True

        return bool(agent_keys & normalized_intended)

    def to_xml(self) -> str:
        """
        Format skill as XML for inclusion in prompts.

        Returns:
            XML formatted skill entry
        """
        return f"""<skill>
<name>{self.name}</name>
<description>{self.description}</description>
<location>{self.location}</location>
</skill>"""

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, location={self.location!r})"
