from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool, ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from Tool_utils import tool_error_command, tool_error_response


ALLOWED_ACADEMIC_HOSTS = {
    "eutils.ncbi.nlm.nih.gov",
    "api.biorxiv.org",
    "export.arxiv.org",
    "www.ebi.ac.uk",
    "api.openalex.org",
    "api.semanticscholar.org",
}

NCBI_ENTREZ_ENDPOINTS = {"esearch", "esummary", "efetch", "elink", "einfo"}
SOURCE_BASE_URLS = {
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "ncbi_entrez": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "biorxiv": "https://api.biorxiv.org",
    "medrxiv": "https://api.biorxiv.org",
    "arxiv": "https://export.arxiv.org/api",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest",
    "openalex": "https://api.openalex.org",
    "semantic_scholar": "https://api.semanticscholar.org",
}
SOURCE_ALIASES = {
    "bioarxiv": "biorxiv",
    "bio_rxiv": "biorxiv",
    "med_rxiv": "medrxiv",
    "ncbi": "ncbi_entrez",
    "entrez": "ncbi_entrez",
    "europe_pmc": "europepmc",
    "europe-pmc": "europepmc",
    "semantic-scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
}


def _require_dict(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"`{name}` must be a JSON object.")
    return value


def _require_str(name: str, value: Any, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"`{name}` is required.")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{name}` must be a non-empty string.")
    return value.strip()


def _positive_int(name: str, value: Any, default: int, maximum: int | None = None) -> int:
    if value is None:
        out = default
    elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"`{name}` must be a positive integer.")
    else:
        out = value
    if maximum is not None:
        return min(out, maximum)
    return out


def _build_url(base_url: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _service_name(base_url: str) -> str:
    host = urlparse(base_url).netloc
    return host.replace(".", "-") or "academic-source"


def _validate_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only https URLs are allowed for academic_rest_request.")
    host = parsed.netloc.lower()
    if host not in ALLOWED_ACADEMIC_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_ACADEMIC_HOSTS))
        raise ValueError(f"Host '{host}' is not allowed. Allowed hosts: {allowed}.")


def _get_by_path(value: Any, path: str) -> Any:
    current = value
    if path == "$":
        return current
    for part in path.split("."):
        if isinstance(current, list):
            if not part.isdigit():
                raise ValueError(f"`record_path` segment {part!r} must be a list index.")
            index = int(part)
            if index >= len(current):
                raise ValueError(f"`record_path` index {index} is out of range.")
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                raise ValueError(f"`record_path` key {part!r} was not present.")
            current = current[part]
        else:
            raise ValueError(f"`record_path` segment {part!r} could not be applied.")
    return current


def _infer_target(data: Any) -> tuple[str | None, Any]:
    if isinstance(data, list):
        return "$", data
    if isinstance(data, dict):
        for key in (
            "collection",
            "resultList.result",
            "results",
            "works",
            "data",
            "items",
            "records",
        ):
            try:
                target = _get_by_path(data, key)
            except ValueError:
                continue
            if isinstance(target, list):
                return key, target
        embedded = data.get("_embedded")
        if isinstance(embedded, dict):
            for key, value in embedded.items():
                if isinstance(value, list):
                    return f"_embedded.{key}", value
    return None, data


def _compact(value: Any, max_items: int, max_depth: int, max_string: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "..."
    if max_depth <= 0:
        if isinstance(value, (dict, list)):
            return "..."
        return value
    if isinstance(value, list):
        out = [_compact(item, max_items, max_depth - 1, max_string) for item in value[:max_items]]
        if len(value) > max_items:
            out.append(f"... (+{len(value) - max_items} more)")
        return out
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:max_items]:
            out[str(key)] = _compact(item, max_items, max_depth - 1, max_string)
        if len(items) > max_items:
            out["_truncated_keys"] = len(items) - max_items
        return out
    return value


def _request_summary(config: dict[str, Any], final_url: str, raw_output_path: str | None) -> dict[str, Any]:
    return {
        "url": final_url,
        "url_without_query": config["url"],
        "params": _compact(config["params"], max_items=50, max_depth=3, max_string=1000),
        "param_keys": list(config["params"].keys()),
        "json_body": _compact(config["json_body"], max_items=30, max_depth=3, max_string=1000)
        if config["json_body"] is not None
        else None,
        "form_body": _compact(config["form_body"], max_items=30, max_depth=3, max_string=1000)
        if config["form_body"] is not None
        else None,
        "saved_raw": bool(raw_output_path),
    }


def _safe_raw_output_path(raw_output_path: str | None, base_url: str, suffix: str) -> Path:
    root = Path.cwd() / "artifacts" / "search"
    root.mkdir(parents=True, exist_ok=True)

    if raw_output_path:
        path = Path(raw_output_path)
        if path.is_absolute():
            raise ValueError("`raw_output_path` must be relative to artifacts/search.")
        candidate = (root / path).resolve()
    else:
        filename = f"{_service_name(base_url)}-{int(time.time())}.{suffix}"
        candidate = (root / filename).resolve()

    if root.resolve() not in candidate.parents and candidate != root.resolve():
        raise ValueError("`raw_output_path` must stay inside artifacts/search.")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _normalize_request(payload: dict[str, Any]) -> dict[str, Any]:
    source = _require_str("source", payload.get("source")) or "custom"
    source_key = source.lower().replace("-", "_")
    source_key = SOURCE_ALIASES.get(source_key, source_key)
    base_url = _require_str("base_url", payload.get("base_url"))
    path = _require_str("path", payload.get("path"))

    if source_key in {"pubmed", "ncbi_entrez"} and payload.get("endpoint"):
        endpoint = _require_str("endpoint", payload.get("endpoint"), required=True)
        if endpoint not in NCBI_ENTREZ_ENDPOINTS:
            raise ValueError(f"`endpoint` must be one of {sorted(NCBI_ENTREZ_ENDPOINTS)}.")
        base_url = base_url or SOURCE_BASE_URLS[source_key]
        path = path or f"{endpoint}.fcgi"
    elif base_url is None and source_key in SOURCE_BASE_URLS:
        base_url = SOURCE_BASE_URLS[source_key]

    if base_url is None or path is None:
        raise ValueError("Provide either source-specific fields or both `base_url` and `path`.")

    method = (_require_str("method", payload.get("method")) or "GET").upper()
    if method not in {"GET", "POST"}:
        raise ValueError("`method` must be GET or POST.")

    json_body = payload.get("json_body")
    form_body = payload.get("form_body")
    if json_body is not None and form_body is not None:
        raise ValueError("Provide only one of `json_body` or `form_body`.")

    response_format = (_require_str("response_format", payload.get("response_format")) or "auto").lower()
    if response_format not in {"auto", "json", "text", "xml"}:
        raise ValueError("`response_format` must be auto, json, text, or xml.")

    url = _build_url(base_url, path)
    _validate_host(url)

    headers = _require_dict("headers", payload.get("headers"))
    blocked_headers = {"authorization", "cookie", "x-api-key"}
    for header in headers:
        if header.lower() in blocked_headers:
            raise ValueError(f"Header `{header}` is not allowed in academic_rest_request.")

    headers.setdefault("User-Agent", "BioInCoder academic_search/0.1")
    headers.setdefault("Accept", "application/json, text/xml, application/xml, text/plain;q=0.8, */*;q=0.5")

    return {
        "source": source_key,
        "base_url": base_url,
        "url": url,
        "path": path,
        "method": method,
        "params": _require_dict("params", payload.get("params")),
        "headers": headers,
        "json_body": json_body,
        "form_body": _require_dict("form_body", form_body) if form_body is not None else None,
        "record_path": _require_str("record_path", payload.get("record_path")),
        "response_format": response_format,
        "max_items": _positive_int("max_items", payload.get("max_items"), 20, maximum=100),
        "max_depth": _positive_int("max_depth", payload.get("max_depth"), 4, maximum=8),
        "max_string": _positive_int("max_string", payload.get("max_string"), 500, maximum=3000),
        "text_head_chars": _positive_int("text_head_chars", payload.get("text_head_chars"), 2500, maximum=12000),
        "timeout_seconds": _positive_int("timeout_seconds", payload.get("timeout_seconds"), 30, maximum=120),
        "save_raw": bool(payload.get("save_raw", False)),
        "raw_output_path": _require_str("raw_output_path", payload.get("raw_output_path")),
    }


class AcademicRestRequestInput(BaseModel):
    request_json: dict[str, Any] = Field(
        ...,
        description=(
            "One JSON object describing an academic API request. "
            "Use source-specific skills to construct this JSON. Supported sources include "
            "pubmed/ncbi_entrez, biorxiv, medrxiv, arxiv, europepmc, openalex, and semantic_scholar."
        ),
    )


class AcademicRestRequest(BaseTool):
    name: str = "academic_rest_request"
    description: str = (
        "Execute one controlled academic REST request from a JSON object. "
        "The input is flexible JSON, not a fixed search schema. "
        "Supports GET/POST, params, json_body, form_body, record_path, compact previews, and optional raw saving. "
        "Use this inside SearchAgent after loading the appropriate database skill."
    )
    args_schema: type[BaseModel] = AcademicRestRequestInput

    def _run(self, request_json: dict[str, Any]) -> dict[str, Any]:
        try:
            config = _normalize_request(request_json)
            url = config["url"]
            params = config["params"]
            if params:
                query = urlencode(params, doseq=True)
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}{query}"

            body = None
            headers = dict(config["headers"])
            if config["json_body"] is not None:
                body = json.dumps(config["json_body"]).encode("utf-8")
                headers["Content-Type"] = "application/json"
            elif config["form_body"] is not None:
                body = urlencode(config["form_body"], doseq=True).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"

            req = Request(url=url, data=body, headers=headers, method=config["method"])
            with urlopen(req, timeout=config["timeout_seconds"]) as response:
                raw_bytes = response.read()
                status_code = response.status
                content_type = (response.headers.get("content-type") or "").lower()

            raw_text = raw_bytes.decode("utf-8", errors="replace")
            wants_text = config["response_format"] in {"text", "xml"}
            wants_json = config["response_format"] == "json"
            auto_json = (
                config["response_format"] == "auto"
                and ("json" in content_type or raw_text.lstrip().startswith(("{", "[")))
            )

            raw_output_path = None
            if wants_json or auto_json:
                data = json.loads(raw_text)
                if config["save_raw"]:
                    raw_path = _safe_raw_output_path(config["raw_output_path"], config["base_url"], "json")
                    raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    raw_output_path = str(raw_path)

                record_path = config["record_path"]
                path_used, target = (
                    _infer_target(data)
                    if record_path is None
                    else (record_path, _get_by_path(data, record_path))
                )

                out: dict[str, Any] = {
                    "ok": True,
                    "source": config["source"],
                    "base_url": config["base_url"],
                    "path": config["path"],
                    "method": config["method"],
                    "status_code": status_code,
                    "content_type": content_type,
                    "record_path": path_used,
                    "raw_output_path": raw_output_path,
                    "request_summary": _request_summary(config, url, raw_output_path),
                    "warnings": [],
                }

                if isinstance(target, list):
                    records = target[: config["max_items"]]
                    out.update(
                        {
                            "record_count_returned": len(records),
                            "record_count_available": len(target),
                            "truncated": len(records) < len(target),
                            "records": _compact(
                                records,
                                config["max_items"],
                                config["max_depth"],
                                config["max_string"],
                            ),
                        }
                    )
                else:
                    out["summary"] = _compact(
                        target,
                        config["max_items"],
                        config["max_depth"],
                        config["max_string"],
                    )
                    if isinstance(target, dict):
                        out["top_keys"] = list(target)[: config["max_items"]]
                return out

            if config["save_raw"]:
                suffix = "xml" if "xml" in content_type or wants_text else "txt"
                raw_path = _safe_raw_output_path(config["raw_output_path"], config["base_url"], suffix)
                raw_path.write_text(raw_text, encoding="utf-8")
                raw_output_path = str(raw_path)

            text_head = raw_text[: config["text_head_chars"]]
            return {
                "ok": True,
                "source": config["source"],
                "base_url": config["base_url"],
                "path": config["path"],
                "method": config["method"],
                "status_code": status_code,
                "content_type": content_type,
                "raw_output_path": raw_output_path,
                "text_head": None if raw_output_path else text_head,
                "text_head_truncated": len(raw_text) > len(text_head),
                "request_summary": _request_summary(config, url, raw_output_path),
                "warnings": [],
            }
        except HTTPError as exc:
            return tool_error_response(
                f"HTTP {exc.code}: {exc.reason}",
                error_type="HTTPError",
                hint="Check the database JSON, endpoint path, parameters, and rate limits.",
            )
        except URLError as exc:
            return tool_error_response(
                exc,
                hint="Network access failed or the academic API host is unavailable.",
            )
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check that request_json is one valid academic REST request JSON object.",
            )


class AcademicSearchInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    objective: str = Field(
        ...,
        description=(
            "The academic search objective. Include the scientific question, target entities, "
            "source preferences, date constraints, expected output, or other search constraints if known."
        ),
    )
    runtime: ToolRuntime


class AcademicSearch(BaseTool):
    name: str = "academic_search"
    description: str = (
        "Call the SearchAgent to perform academic literature/database search. "
        "Use for PubMed/Entrez, bioRxiv/medRxiv, arXiv, Europe PMC, OpenAlex, Semantic Scholar, "
        "or other scholarly metadata searches. The SearchAgent can construct flexible JSON requests "
        "with academic_rest_request and saves its full transcript to Search_Channel."
    )
    args_schema: type[BaseModel] = AcademicSearchInput

    def _run(
        self,
        objective: str,
        runtime: ToolRuntime,
    ):
        try:
            from AgentConfigSetup import multi_agent_runtime

            coder_msgs = runtime.state.get("messages", [])
            coder_msgs_sanitization = coder_msgs
            if coder_msgs_sanitization and getattr(coder_msgs_sanitization[-1], "tool_calls", None):
                coder_msgs_sanitization = coder_msgs_sanitization[:-1]

            search_instruction = HumanMessage(
                content=(
                    "Perform an academic search for the following objective.\n\n"
                    f"# Current date\n{date.today().isoformat()}\n\n"
                    f"# Objective\n{objective}\n\n"
                    "Use available search skills to construct database-specific JSON requests. "
                    "Choose appropriate sources and result depth from the objective and current context. "
                    "When the search involves recency or a date window, calculate exact date ranges from the current date above. "
                    "For literature retrieval, return a reasonably broad result set instead of stopping at only a few papers. "
                    "Use academic_rest_request for retrieval. "
                    "Return a concise evidence-oriented answer with source names, IDs/URLs/DOIs when available, "
                    "and note unresolved uncertainty. Do not fabricate papers or identifiers."
                )
            )

            request_id = runtime.tool_call_id
            search_config = multi_agent_runtime.make_child_config(
                parent_config=getattr(runtime, "config", None),
                agent_name="search",
                request_id=request_id,
            )
            search_state, message_ref = multi_agent_runtime.invoke_agent(
                agent_name="search",
                graph_input={"messages": coder_msgs_sanitization + [search_instruction]},
                request_id=request_id,
                config=search_config,
            )

            messages = multi_agent_runtime.extract_messages(search_state)
            final_content = ""
            if messages:
                final_content = str(getattr(messages[-1], "content", messages[-1]))

            if message_ref is not None:
                final_content = (
                    f"{final_content}\n\n"
                    "# Saved subagent messages\n"
                    f"{message_ref.to_tool_hint()}"
                )

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=final_content,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )
        except Exception as exc:
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="SearchAgent failed. Retry academic_search with a narrower objective or inspect saved messages.",
            )
