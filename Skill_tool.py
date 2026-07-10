#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Skill Tool - executes skills within the conversation.

This tool allows agent to invoke skills that provide specialized knowledge
and workflows for specific tasks.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr
from Tool_utils import tool_error_response


TEXT_RESOURCE_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".r",
    ".R",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
}

RUNNABLE_SCRIPT_SUFFIXES = {".py", ".R", ".r", ".sh"}
RUNNABLE_SCRIPT_DIRS = {"scripts", "examples"}


def _resource_type(relative_path: Path) -> str:
    first = relative_path.parts[0] if relative_path.parts else ""
    if first in {"references", "reference"} or relative_path.name == "usage-guide.md":
        return "reference"
    if first == "scripts":
        return "script"
    if first == "examples":
        return "example"
    if first == "assets":
        return "asset"
    return "resource"


def _skill_resources(skill_path: Path) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for path in sorted(skill_path.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_path)
        if path.name == "SKILL.md":
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        resources.append(
            {
                "relative_path": relative.as_posix(),
                "type": _resource_type(relative),
                "size_bytes": path.stat().st_size,
                "suffix": path.suffix,
            }
        )
    return resources


def _resolve_skill_resource_path(skill_path: Path, relative_path: str) -> Path:
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("`relative_path` must be a non-empty string.")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("`relative_path` must stay inside the skill directory.")

    root = skill_path.resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("`relative_path` must stay inside the skill directory.")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"Resource does not exist: {relative_path}")
    return candidate


class SkillToolInput(BaseModel):
    """Input schema for SkillTool."""
    skill: str = Field(description="The skill name to load. It must be one of the available skills listed in the system prompt.")


class SkillTool(BaseTool):
    """
    Tool for executing skills within the main conversation.

    Skills are modular packages that extend agent's capabilities by providing
    specialized knowledge, workflows, and tools. When a skill is invoked,
    its instructions are loaded into the conversation context.
    """

    name: str = "Skill"
    description: str = """Execute a skill within the main conversation.

Skills are folders of instructions, scripts, and resources that agent loads
dynamically to improve performance on specialized tasks.

Usage:
- Invoke skills using this tool with the skill name only (no arguments)
- When you invoke a skill, its prompt will expand and provide detailed instructions
- Only use skills listed in <available_skills> in the system prompt

Important:
- Only use skills that are listed as available
- Do not invoke a skill that is already running
"""
    args_schema: type[BaseModel] = SkillToolInput
    # Private internal cache. This is not exposed as a tool field or argument.
    _registry: Any = PrivateAttr(default=None)
    _agent_name: Optional[str] = PrivateAttr(default=None)


    def __init__(self, agent_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._registry = None
        self._agent_name = agent_name

    @property
    def registry(self):
        """Get the skill registry, loading skills if needed."""
        if self._registry is None:
            from Skill_registry import SkillRegistry
            from Skill_loader import load_skills
            self._registry = load_skills()
        return self._registry

    def _run(self, skill: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a skill by loading its instructions into the conversation.
        This is the synchronous entry point required by BaseTool.

        Args:
            skill: Name of the skill to execute

        Returns:
            Dict containing the skill prompt and metadata
        """
        try:
            return self.execute_skill(skill)
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check that the skill registry can load SKILL.md files and that the requested skill name is valid.",
            )
    
    async def _arun(self, skill: str) -> Dict[str, Any]:
        try:
            return self.execute_skill(skill)
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check that the skill registry can load SKILL.md files and that the requested skill name is valid.",
            )

    def execute_skill(self, skill: str) -> Dict[str, Any]:
        """
        Execute a skill by loading its instructions into the conversation.

        Args:
            skill: Name of the skill to execute

        Returns:
            Dict containing the skill prompt and metadata
        """
        # Check if skill exists
        skill_obj = self.registry.get(skill)

        if skill_obj is None:
            available = [s.name for s in self.registry.list_all(agent_name=self._agent_name)]
            return {
                "success": False,
                "error": f"Unknown skill: {skill}",
                "available_skills": available[:10],  # Show first 10
                "hint": "Use one of the available skills listed above"
            }

        if not skill_obj.is_available_to(self._agent_name):
            available = [s.name for s in self.registry.list_all(agent_name=self._agent_name)]
            return {
                "success": False,
                "error": f"Skill is not available to this agent: {skill}",
                "available_skills": available[:10],
                "hint": "Use a skill listed in this agent's <available_skills> block.",
            }

        # Get the skill prompt
        prompt = skill_obj.get_prompt()

        # Build response with skill content
        return {
            "success": True,
            "skill_name": skill_obj.name,
            "skill_description": skill_obj.description,
            "skill_location": skill_obj.location,
            "skill_path": str(skill_obj.path),  # Absolute path for resolving relative resources
            "resources": _skill_resources(skill_obj.path),
            "prompt": prompt,
            "message": f'The "{skill_obj.name}" skill is loading',
            "allowed_tools": skill_obj.allowed_tools,
        }

    def validate_skill(self, skill: str) -> tuple[bool, Optional[str]]:
        """
        Validate that a skill exists and can be executed.

        Args:
            skill: Name of the skill to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not skill:
            return False, "Skill name is required"

        if not self.registry.exists(skill):
            available = [s.name for s in self.registry.list_all(agent_name=self._agent_name)]
            return False, f"Unknown skill: {skill}. Available: {', '.join(available[:5])}"

        if not self.registry.get(skill).is_available_to(self._agent_name):
            available = [s.name for s in self.registry.list_all(agent_name=self._agent_name)]
            return False, f"Skill not available to this agent: {skill}. Available: {', '.join(available[:5])}"

        return True, None

    def get_available_skills_prompt(self, char_budget: int = 10000) -> str:
        """
        Generate a prompt listing available skills for the system message.

        Args:
            char_budget: Maximum characters for skills list

        Returns:
            Formatted skills prompt
        """
        return self.registry.generate_skills_prompt(char_budget, agent_name=self._agent_name)


def generate_skill_tool_prompt(agent_name: Optional[str] = None) -> str:
    """
    Generate the complete skill tool prompt including available skills.

    This is used to generate the skill tool description in the system prompt.

    Returns:
        Complete skill tool prompt
    """
    from Skill_loader import load_skills

    registry = load_skills()
    skills = registry.list_all(agent_name=agent_name)

    if not skills:
        return """Execute a skill within the main conversation.

No skills are currently available. Skills can be added to:
- skills/ (project-level)
- ~/skills/ (user-level)
"""

    skills_xml = "\n".join(skill.to_xml() for skill in skills)

    return f"""Execute a skill within the main conversation.

<skills_instructions>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke skills using this tool with the skill name only (no arguments)
- When you invoke a skill, you will see <command-message>The "{{name}}" skill is loading</command-message>
- The skill's prompt will expand and provide detailed instructions on how to complete the task
- The output includes a `resources` index listing bundled files such as references/, scripts/, examples/, and assets/
- Use `read_skill_resource` to read listed resources when the SKILL.md points to them or more detail is needed
- Use `run_skill_script` only for listed scripts/examples that must be executed for the task

Important:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already running
</skills_instructions>

<available_skills>
{skills_xml}
</available_skills>
"""


class ReadSkillResourceInput(BaseModel):
    skill: str = Field(description="The skill name whose bundled resource should be read.")
    relative_path: str = Field(description="Relative path inside the skill directory, as listed in SkillTool resources.")


class ReadSkillResource(BaseTool):
    name: str = "read_skill_resource"
    description: str = (
        "Read the full text of a bundled skill resource such as usage-guide.md, "
        "references/*.md, scripts/*.py, or examples/*.R. Only reads files inside "
        "the requested skill directory."
    )
    args_schema: type[BaseModel] = ReadSkillResourceInput
    _registry: Any = PrivateAttr(default=None)
    _agent_name: Optional[str] = PrivateAttr(default=None)

    def __init__(self, agent_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._registry = None
        self._agent_name = agent_name

    @property
    def registry(self):
        if self._registry is None:
            from Skill_loader import load_skills
            self._registry = load_skills()
        return self._registry

    def _run(self, skill: str, relative_path: str) -> Dict[str, Any]:
        try:
            skill_obj = self.registry.get(skill)
            if skill_obj is None:
                return tool_error_response(f"Unknown skill: {skill}")
            if not skill_obj.is_available_to(self._agent_name):
                return tool_error_response(f"Skill is not available to this agent: {skill}")

            path = _resolve_skill_resource_path(skill_obj.path, relative_path)
            if path.suffix not in TEXT_RESOURCE_SUFFIXES:
                raise ValueError(f"Unsupported resource file type: {path.suffix}")

            text = path.read_text(encoding="utf-8", errors="replace")
            return {
                "ok": True,
                "skill": skill_obj.name,
                "relative_path": Path(relative_path).as_posix(),
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "chars": len(text),
                "text": text,
            }
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check that the skill is available and relative_path is a listed text resource inside the skill directory.",
            )


class RunSkillScriptInput(BaseModel):
    skill: str = Field(description="The skill name whose bundled script should be run.")
    relative_path: str = Field(description="Relative path inside scripts/ or examples/ under the skill directory.")
    args: list[str] = Field(default_factory=list, description="Command arguments passed to the script. Do not include the interpreter.")
    timeout_seconds: int = Field(default=120, description="Execution timeout in seconds. Capped at 600.")


class RunSkillScript(BaseTool):
    name: str = "run_skill_script"
    description: str = (
        "Run a bundled skill script from scripts/ or examples/ with a constrained argument list. "
        "Supports .py, .R, and .sh files. This is not a general shell: pass args as a JSON list."
    )
    args_schema: type[BaseModel] = RunSkillScriptInput
    _registry: Any = PrivateAttr(default=None)
    _agent_name: Optional[str] = PrivateAttr(default=None)

    def __init__(self, agent_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._registry = None
        self._agent_name = agent_name

    @property
    def registry(self):
        if self._registry is None:
            from Skill_loader import load_skills
            self._registry = load_skills()
        return self._registry

    def _run(
        self,
        skill: str,
        relative_path: str,
        args: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> Dict[str, Any]:
        try:
            skill_obj = self.registry.get(skill)
            if skill_obj is None:
                return tool_error_response(f"Unknown skill: {skill}")
            if not skill_obj.is_available_to(self._agent_name):
                return tool_error_response(f"Skill is not available to this agent: {skill}")

            path = _resolve_skill_resource_path(skill_obj.path, relative_path)
            relative = path.relative_to(skill_obj.path)
            if not relative.parts or relative.parts[0] not in RUNNABLE_SCRIPT_DIRS:
                raise ValueError("Only scripts under scripts/ or examples/ may be run.")
            if path.suffix not in RUNNABLE_SCRIPT_SUFFIXES:
                raise ValueError(f"Unsupported script file type: {path.suffix}")

            if args is None:
                args = []
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError("`args` must be a list of strings.")
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
                raise ValueError("`timeout_seconds` must be a positive integer.")
            timeout_seconds = min(timeout_seconds, 600)

            if path.suffix == ".py":
                command = [sys.executable, str(path), *args]
            elif path.suffix in {".R", ".r"}:
                command = ["Rscript", str(path), *args]
            else:
                command = ["bash", str(path), *args]

            completed = subprocess.run(
                command,
                cwd=str(skill_obj.path),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            return {
                "ok": completed.returncode == 0,
                "skill": skill_obj.name,
                "relative_path": relative.as_posix(),
                "command": command,
                "cwd": str(skill_obj.path),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except subprocess.TimeoutExpired as exc:
            return tool_error_response(
                f"Timed out after {timeout_seconds} seconds",
                error_type="TimeoutExpired",
                hint=f"stdout: {exc.stdout or ''}\nstderr: {exc.stderr or ''}",
            )
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check skill, relative_path, args, script interpreter availability, and timeout_seconds.",
            )
