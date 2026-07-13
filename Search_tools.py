from __future__ import annotations

import json
import os
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

from Tool_utils import is_graph_interrupt, tool_error_command, tool_error_response


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
DATASET_SOURCE_ALIASES = {
    "geo": "geo",
    "gds": "geo",
    "ncbi_geo": "geo",
    "arrayexpress": "arrayexpress",
    "array_express": "arrayexpress",
    "ae": "arrayexpress",
}
DATASET_BASE_URLS = {
    "geo": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "arrayexpress": "https://www.ebi.ac.uk/biostudies/api/v1",
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


def _optional_positive_int(name: str, value: Any, maximum: int | None = None) -> int | None:
    if value is None:
        return None
    return _positive_int(name, value, 1, maximum=maximum)


def _non_negative_int(name: str, value: Any, default: int, maximum: int | None = None) -> int:
    if value is None:
        out = default
    elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"`{name}` must be a non-negative integer.")
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


def _compact(value: Any, max_items: int | None, max_depth: int, max_string: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "..."
    if max_depth <= 0:
        if isinstance(value, (dict, list)):
            return "..."
        return value
    if isinstance(value, list):
        items = value if max_items is None else value[:max_items]
        out = [_compact(item, max_items, max_depth - 1, max_string) for item in items]
        if max_items is not None and len(value) > max_items:
            out.append(f"... (+{len(value) - max_items} more)")
        return out
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        items = list(value.items())
        selected_items = items if max_items is None else items[:max_items]
        for key, item in selected_items:
            out[str(key)] = _compact(item, max_items, max_depth - 1, max_string)
        if max_items is not None and len(items) > max_items:
            out["_truncated_keys"] = len(items) - max_items
        return out
    return value


def _request_summary(config: dict[str, Any], final_url: str, raw_output_path: str | None) -> dict[str, Any]:
    params = {
        key: "[redacted]" if str(key).lower() in {"api_key", "apikey", "key", "token"} else value
        for key, value in config["params"].items()
    }
    has_sensitive_params = params != config["params"]
    return {
        "url": f"{config['url']}?[query redacted due to sensitive params]" if has_sensitive_params else final_url,
        "url_without_query": config["url"],
        "params": _compact(params, max_items=50, max_depth=3, max_string=1000),
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
        filename = f"{_service_name(base_url)}-{time.time_ns()}.{suffix}"
        candidate = (root / filename).resolve()

    if root.resolve() not in candidate.parents and candidate != root.resolve():
        raise ValueError("`raw_output_path` must stay inside artifacts/search.")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _resolve_search_raw_path(raw_output_path: str) -> Path:
    root = (Path.cwd() / "artifacts" / "search").resolve()
    path = Path(_require_str("raw_output_path", raw_output_path, required=True))

    if path.is_absolute():
        candidate = path.resolve()
    elif len(path.parts) >= 2 and path.parts[0] == "artifacts" and path.parts[1] == "search":
        candidate = (Path.cwd() / path).resolve()
    else:
        candidate = (root / path).resolve()

    if root not in candidate.parents and candidate != root:
        raise ValueError("`raw_output_path` must stay inside artifacts/search.")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"`raw_output_path` does not exist: {raw_output_path}")
    return candidate


def _optional_get_by_path(value: Any, path: str) -> Any:
    try:
        return _get_by_path(value, path)
    except ValueError:
        return None


def _record_matches(record: Any, where: dict[str, str]) -> bool:
    for key, expected in where.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("`where` keys must be non-empty strings.")
        if not isinstance(expected, str):
            raise ValueError("`where` values must be strings.")

        field = key
        contains = False
        if key.endswith("__contains"):
            field = key[: -len("__contains")]
            contains = True
        if not field:
            raise ValueError("`where` field path must be non-empty.")

        actual = _optional_get_by_path(record, field)
        if actual is None:
            return False
        actual_text = str(actual)
        if contains:
            if expected.lower() not in actual_text.lower():
                return False
        elif actual_text != expected:
            return False
    return True


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
        "max_items": _optional_positive_int("max_items", payload.get("max_items")),
        "max_depth": _positive_int("max_depth", payload.get("max_depth"), 4, maximum=8),
        "max_string": _positive_int("max_string", payload.get("max_string"), 500, maximum=3000),
        "text_head_chars": _positive_int("text_head_chars", payload.get("text_head_chars"), 2500, maximum=12000),
        "timeout_seconds": _positive_int("timeout_seconds", payload.get("timeout_seconds"), 30, maximum=120),
        "save_raw": bool(payload.get("save_raw", True)),
        "raw_output_path": _require_str("raw_output_path", payload.get("raw_output_path")),
    }


class AcademicRestRequestInput(BaseModel):
    request_json: dict[str, Any] = Field(
        ...,
        description=(
            "One controlled REST request JSON for scholarly/literature metadata APIs. "
            "Use source-specific skills to choose fields such as source, endpoint/path, params, "
            "record_path, response_format, max_items, save_raw, and raw_output_path. "
            "Supported source shortcuts include pubmed/ncbi_entrez, biorxiv, medrxiv, "
            "arxiv, europepmc, openalex, and semantic_scholar."
        ),
    )


class AcademicRestRequest(BaseTool):
    name: str = "academic_rest_request"
    description: str = (
        "Execute one controlled scholarly REST request from request_json and return a compact dict. "
        "Use for literature and scholarly metadata APIs after loading the relevant SearchAgent skill. "
        "Supports source shortcuts, GET/POST, params, json_body/form_body, record_path extraction, "
        "compact JSON/text previews, and raw response saving under artifacts/search."
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
                    records = target if config["max_items"] is None else target[: config["max_items"]]
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
                        out["top_keys"] = (
                            list(target)
                            if config["max_items"] is None
                            else list(target)[: config["max_items"]]
                        )
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
                "text_head": text_head,
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


class SearchRawReadInput(BaseModel):
    raw_output_path: str = Field(
        ...,
        description=(
            "Raw response path returned by academic_rest_request or dataset_search when save_raw=true. "
            "Only files under artifacts/search are readable."
        ),
    )
    record_path: str | None = Field(
        default=None,
        description=(
            "Dot path to the record list inside a JSON raw response, such as "
            "resultList.result, esearchresult.idlist, hits, results, collection, or $. "
            "If omitted, the tool tries to infer a useful record list or summary."
        ),
    )
    offset: int = Field(
        default=0,
        description="Zero-based record offset for JSON batch/where reads. Ignored when index is provided.",
    )
    limit: int = Field(
        default=50,
        description="Maximum JSON records to return in batch/where mode. Capped at 200.",
    )
    index: int | None = Field(
        default=None,
        description="Return exactly one JSON record by zero-based index. Takes precedence over offset/limit.",
    )
    where: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional filters for JSON record lists. Keys are dot paths; suffix a key with "
            "__contains for case-insensitive substring matching."
        ),
    )
    max_depth: int = Field(
        default=8,
        description="Maximum nested depth returned for JSON records or summaries. Capped at 8.",
    )
    max_string: int = Field(
        default=10000,
        description="Maximum characters per returned JSON string value. Capped at 10000.",
    )
    offset_chars: int = Field(
        default=0,
        description="Zero-based character offset for XML/text raw files.",
    )
    limit_chars: int = Field(
        default=12000,
        description="Maximum characters to return from XML/text raw files. Capped at 50000.",
    )


class SearchRawRead(BaseTool):
    name: str = "search_raw_read"
    description: str = (
        "Read saved raw search responses from artifacts/search in bounded slices. "
        "Use after academic_rest_request or dataset_search when compact previews are truncated, "
        "insufficient, or need field-level confirmation. Supports record_path, offset/limit, "
        "index, and where filters for JSON files, plus offset_chars/limit_chars for XML/text files."
    )
    args_schema: type[BaseModel] = SearchRawReadInput

    def _run(
        self,
        raw_output_path: str,
        record_path: str | None = None,
        offset: int = 0,
        limit: int = 50,
        index: int | None = None,
        where: dict[str, str] | None = None,
        max_depth: int = 8,
        max_string: int = 10000,
        offset_chars: int = 0,
        limit_chars: int = 12000,
    ) -> dict[str, Any]:
        try:
            resolved_path = _resolve_search_raw_path(raw_output_path)
            offset = _non_negative_int("offset", offset, 0)
            limit = _positive_int("limit", limit, 50, maximum=200)
            if index is not None:
                index = _non_negative_int("index", index, 0)
            if where is not None:
                where = _require_dict("where", where)
            max_depth = _positive_int("max_depth", max_depth, 8, maximum=8)
            max_string = _positive_int("max_string", max_string, 10000, maximum=10000)
            offset_chars = _non_negative_int("offset_chars", offset_chars, 0)
            limit_chars = _positive_int("limit_chars", limit_chars, 12000, maximum=50000)

            suffix = resolved_path.suffix.lower()
            if suffix != ".json":
                raw_text = resolved_path.read_text(encoding="utf-8", errors="replace")
                text = raw_text[offset_chars : offset_chars + limit_chars]
                next_offset_chars = offset_chars + len(text)
                return {
                    "ok": True,
                    "raw_output_path": str(resolved_path),
                    "mode": "text",
                    "content_type": "xml" if suffix == ".xml" else "text",
                    "offset_chars": offset_chars,
                    "limit_chars": limit_chars,
                    "chars_returned": len(text),
                    "chars_available": len(raw_text),
                    "next_offset_chars": next_offset_chars if next_offset_chars < len(raw_text) else None,
                    "has_more": next_offset_chars < len(raw_text),
                    "text": text,
                    "warnings": [],
                }

            data = json.loads(resolved_path.read_text(encoding="utf-8"))
            path_used, target = (
                _infer_target(data)
                if record_path is None
                else (_require_str("record_path", record_path), _get_by_path(data, record_path))
            )

            out: dict[str, Any] = {
                "ok": True,
                "raw_output_path": str(resolved_path),
                "record_path": path_used,
                "mode": "summary",
                "warnings": [],
            }

            if not isinstance(target, list):
                out["summary"] = _compact(target, None, max_depth, max_string)
                if isinstance(target, dict):
                    out["top_keys"] = list(target)
                return out

            record_count_available = len(target)
            if index is not None:
                if index >= record_count_available:
                    raise ValueError(f"`index` {index} is out of range for {record_count_available} records.")
                selected = [target[index]]
                out.update(
                    {
                        "mode": "index",
                        "index": index,
                        "record_count_available": record_count_available,
                        "record_count_returned": 1,
                        "has_more": False,
                    }
                )
            elif where:
                matches = [record for record in target if _record_matches(record, where)]
                selected = matches[offset : offset + limit]
                next_offset = offset + len(selected)
                out.update(
                    {
                        "mode": "where",
                        "where": where,
                        "offset": offset,
                        "limit": limit,
                        "record_count_available": record_count_available,
                        "match_count_available": len(matches),
                        "record_count_returned": len(selected),
                        "next_offset": next_offset if next_offset < len(matches) else None,
                        "truncated": next_offset < len(matches),
                        "has_more": next_offset < len(matches),
                    }
                )
            else:
                selected = target[offset : offset + limit]
                next_offset = offset + len(selected)
                out.update(
                    {
                        "mode": "batch",
                        "record_count_available": record_count_available,
                        "offset": offset,
                        "limit": limit,
                        "record_count_returned": len(selected),
                        "next_offset": next_offset if next_offset < record_count_available else None,
                        "has_more": next_offset < record_count_available,
                    }
                )

            out["records"] = _compact(selected, None, max_depth, max_string)
            return out
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "Check raw_output_path, record_path, offset/limit, index, where filters, "
                    "or offset_chars/limit_chars. Only files saved under artifacts/search are supported."
                ),
            )



def _dataset_source_key(source: str | None) -> str:
    source_key = (source or "").strip().lower().replace("-", "_").replace(" ", "_")
    source_key = DATASET_SOURCE_ALIASES.get(source_key, source_key)
    if source_key not in DATASET_BASE_URLS:
        raise ValueError("`source` must be one of: geo, arrayexpress.")
    return source_key


def _dataset_default_path(source: str, payload: dict[str, Any]) -> str:
    if source == "geo":
        endpoint = _require_str("endpoint", payload.get("endpoint")) or "esearch"
        if endpoint not in NCBI_ENTREZ_ENDPOINTS:
            raise ValueError(f"For source=geo, `endpoint` must be one of {sorted(NCBI_ENTREZ_ENDPOINTS)}.")
        return f"{endpoint}.fcgi"
    if source == "arrayexpress":
        return "ArrayExpress/search"
    raise ValueError(f"Unsupported dataset source: {source}")


def _dataset_default_record_path(source: str, path: str, payload: dict[str, Any]) -> str | None:
    explicit = _require_str("record_path", payload.get("record_path"))
    if explicit is not None:
        return explicit
    if source == "geo":
        endpoint = path.rsplit("/", 1)[-1].removesuffix(".fcgi")
        if endpoint == "esearch":
            return "esearchresult.idlist"
        if endpoint == "esummary":
            return "result"
        return None
    if source == "arrayexpress" and path.rstrip("/") in {"ArrayExpress/search", "search"}:
        return "hits"
    return None


def _ncbi_common_params(params: dict[str, Any]) -> dict[str, Any]:
    merged = dict(params)
    api_key = os.environ.get("NCBI_API_KEY") or os.environ.get("NCBI_EUTILS_API_KEY")
    tool = os.environ.get("NCBI_TOOL")
    email = os.environ.get("NCBI_EMAIL")
    if api_key and "api_key" not in merged:
        merged["api_key"] = api_key
    if tool and "tool" not in merged:
        merged["tool"] = tool
    if email and "email" not in merged:
        merged["email"] = email
    return merged


def _dataset_params(source: str, path: str, payload: dict[str, Any], max_items: int | None) -> dict[str, Any]:
    params = _require_dict("params", payload.get("params"))
    query = _require_str("query", payload.get("query"))
    merged = dict(params)

    if source == "geo":
        endpoint = path.rsplit("/", 1)[-1].removesuffix(".fcgi")
        merged.setdefault("db", "gds")
        if query is not None and endpoint == "esearch":
            merged.setdefault("term", query)
        if endpoint in {"esearch", "esummary"}:
            merged.setdefault("retmode", "json")
        if max_items is not None and endpoint == "esearch":
            merged.setdefault("retmax", max_items)
        return _ncbi_common_params(merged)

    if source == "arrayexpress":
        if query is not None:
            merged.setdefault("query", query)
        if path.rstrip("/") == "ArrayExpress/search":
            merged.setdefault("page", 1)
            if max_items is not None:
                merged.setdefault("pageSize", max_items)
        return merged

    return merged


def _normalize_dataset_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("`request_json` must be one JSON object.")

    source = _dataset_source_key(_require_str("source", payload.get("source"), required=True))
    base_url = _require_str("base_url", payload.get("base_url")) or DATASET_BASE_URLS[source]
    path = _require_str("path", payload.get("path")) or _dataset_default_path(source, payload)

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

    max_items = _optional_positive_int("max_items", payload.get("max_items"), maximum=200)
    url = _build_url(base_url, path)
    _validate_host(url)

    headers = _require_dict("headers", payload.get("headers"))
    blocked_headers = {"authorization", "cookie", "x-api-key"}
    for header in headers:
        if header.lower() in blocked_headers:
            raise ValueError(f"Header `{header}` is not allowed in dataset_search.")
    headers.setdefault("User-Agent", "BioInCoder dataset_search/0.1")
    headers.setdefault("Accept", "application/json, text/xml, application/xml, text/plain;q=0.8, */*;q=0.5")

    return {
        "source": source,
        "base_url": base_url,
        "url": url,
        "path": path,
        "method": method,
        "params": _dataset_params(source, path, payload, max_items),
        "headers": headers,
        "json_body": json_body,
        "form_body": _require_dict("form_body", form_body) if form_body is not None else None,
        "record_path": _dataset_default_record_path(source, path, payload),
        "response_format": response_format,
        "max_items": max_items or 30,
        "max_depth": _positive_int("max_depth", payload.get("max_depth"), 4, maximum=8),
        "max_string": _positive_int("max_string", payload.get("max_string"), 500, maximum=3000),
        "text_head_chars": _positive_int("text_head_chars", payload.get("text_head_chars"), 2500, maximum=12000),
        "timeout_seconds": _positive_int(
            "timeout_seconds",
            payload.get("timeout_seconds") if payload.get("timeout_seconds") is not None else payload.get("timeout_sec"),
            30,
            maximum=120,
        ),
        "save_raw": bool(payload.get("save_raw", True)),
        "raw_output_path": _require_str("raw_output_path", payload.get("raw_output_path")),
    }


class DatasetSearchInput(BaseModel):
    request_json: dict[str, Any] = Field(
        ...,
        description=(
            "One controlled REST request JSON for dataset metadata APIs. "
            "Supported source shortcuts are geo and arrayexpress. Common fields include source, "
            "endpoint or path, query, params, record_path, response_format, max_items, "
            "max_depth, max_string, timeout_sec/timeout_seconds, save_raw, and raw_output_path. "
            "If omitted, max_items defaults to 30 for dataset searches."
        ),
    )


class DatasetSearch(BaseTool):
    name: str = "dataset_search"
    description: str = (
        "Execute one controlled dataset REST request from request_json and return a compact dict. "
        "Use for public dataset metadata after loading the dataset-search skill. "
        "Supports GEO via NCBI Entrez gds and ArrayExpress via the EBI BioStudies ArrayExpress/search endpoint, "
        "with params, record_path extraction, compact JSON/text previews, and raw response saving under artifacts/search."
    )
    args_schema: type[BaseModel] = DatasetSearchInput

    def _run(self, request_json: dict[str, Any]) -> dict[str, Any]:
        try:
            config = _normalize_dataset_request(request_json)
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
                    records = target if config["max_items"] is None else target[: config["max_items"]]
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
                        out["top_keys"] = (
                            list(target)
                            if config["max_items"] is None
                            else list(target)[: config["max_items"]]
                        )
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
                "text_head": text_head,
                "text_head_truncated": len(raw_text) > len(text_head),
                "request_summary": _request_summary(config, url, raw_output_path),
                "warnings": [],
            }
        except HTTPError as exc:
            return tool_error_response(
                f"HTTP {exc.code}: {exc.reason}",
                error_type="HTTPError",
                hint="Check the dataset request JSON, endpoint/path, parameters, and rate limits.",
            )
        except URLError as exc:
            return tool_error_response(
                exc,
                hint="Network access failed or the dataset API host is unavailable.",
            )
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Check that request_json is one valid dataset REST request JSON object.",
            )


class AcademicSearchInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_brief: str = Field(
        ...,
        description=(
            "Self-contained task brief for SearchAgent. Include the overall goal, current search subtask, "
            "relevant scientific context, concrete inputs such as queries/accessions/DOIs/PMIDs/URLs, "
            "source preferences, inclusion/exclusion criteria, date or recency constraints, desired breadth, "
            "required output fields/table shape, stop condition, and any BrowserAgent handoff needs. "
            "For broad screening, explicitly request the candidate-table breadth instead of asking for a few examples."
        ),
    )
    runtime: ToolRuntime


class AcademicSearch(BaseTool):
    name: str = "academic_search"
    description: str = (
        "Delegate a literature, scholarly metadata, or public dataset search to SearchAgent. "
        "Use when the main agent needs PubMed/Entrez, bioRxiv/medRxiv, arXiv, Europe PMC, "
        "OpenAlex, Semantic Scholar, GEO, ArrayExpress, or related metadata retrieval. "
        "SearchAgent chooses and calls academic_rest_request or dataset_search as appropriate and saves its transcript."
    )
    args_schema: type[BaseModel] = AcademicSearchInput

    def _run(
        self,
        runtime: ToolRuntime,
        task_brief: str,
    ):
        try:
            from AgentConfigSetup import multi_agent_runtime

            search_instruction = HumanMessage(
                content=(
                    "SearchAgent delegated task.\n\n"
                    f"# Current date\n{date.today().isoformat()}\n\n"
                    f"# Task brief\n{task_brief}\n\n"
                    "# Message instruction\n"
                    "Use the task brief as the binding scope for this search. "
                    "Use the current date only to resolve relative recency/date windows. "
                    "Return the requested records, candidate table, identifiers, URLs, source notes, "
                    "and limitations needed for BioInCoder handoff."
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
                graph_input={"messages": [search_instruction]},
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
            if is_graph_interrupt(exc):
                raise
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="SearchAgent failed. Retry academic_search with a clearer, narrower task_brief or inspect saved messages.",
            )
