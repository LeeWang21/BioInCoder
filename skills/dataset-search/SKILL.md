---
name: bioincoder-dataset-search
description: Submit compact dataset REST requests for GEO and ArrayExpress metadata using BioInCoder dataset_search.
metadata:
  tool_type: search
  primary_tools:
    - dataset_search
    - search_raw_read
  intended_agent: [search]
---

# BioInCoder Dataset Search

Use this skill when SearchAgent is asked to query public transcriptomics,
functional genomics, or closely related omics dataset metadata from GEO or
ArrayExpress.

`dataset_search` is the dataset counterpart of `academic_rest_request`: pass one
JSON object, let the tool fill source-specific REST defaults, and read compact
records or summaries from the returned dict.

This tool performs one controlled REST request per call. It does not merge,
deduplicate, rank, or normalize records across databases. SearchAgent is
responsible for running follow-up requests and building the final candidate
table.

## Covered Sources

`dataset_search` currently supports:

- GEO through NCBI Entrez `db=gds`
- ArrayExpress through the EBI BioStudies API path `ArrayExpress/search`

Important scope rule:

- ArrayExpress is accessed through the EBI BioStudies service, but this tool
  intentionally exposes only the ArrayExpress search scope, not general
  BioStudies search.
- General BioStudies search is intentionally omitted to reduce noise for
  transcriptomics dataset discovery.
- `source="arrayexpress"` means the ArrayExpress-specific search scope under
  BioStudies.

Accepted source names:

- `geo`
- `arrayexpress`

## Query Strategy

- Build concise biological queries from disease, tissue, organism, assay, and
  technology terms.
- Use `max_items=30` for normal dataset discovery. Use `max_items=50` for broad
  screening or when the user asks for many candidates. Use 5-10 only for known
  accession checks, smoke tests, or very narrow follow-ups.
- Keep `save_raw=true` unless the user explicitly wants a lightweight quick
  check. Raw responses are saved under `artifacts/search` and can be inspected
  with `search_raw_read`.
- Do not treat GEO `esearch` IDs as dataset accessions. GEO `esearch` returns
  Entrez GDS UIDs; call GEO `esummary` before reporting titles, accessions,
  sample counts, FTP links, publication dates, or BioProject IDs.
- For known accessions, search the likely source first:
  - `GSE`, `GSM`, `GPL`: GEO
  - `E-MTAB`, `E-GEOD`, `E-MEXP`: ArrayExpress

## GEO Parameters

Use `source="geo"` for NCBI Entrez E-Utilities against `db=gds`.

Common `endpoint` values:

- `esearch`: find Entrez GDS UIDs.
- `esummary`: retrieve metadata for one or more UIDs.
- `elink`: retrieve linked PubMed or related Entrez records.
- `einfo`: inspect database fields if query syntax is uncertain.

Common `params`:

- `db`: usually `gds`.
- `term`: Entrez query string for `esearch`.
- `id`: comma-separated Entrez GDS UIDs for `esummary` or `elink`.
- `retmode`: use `json` for `esearch`, `esummary`, and `elink`.
- `retmax`: result count for `esearch`; this is filled from `max_items` if not
  provided.
- `retstart`: pagination offset for larger screens.
- `sort`: `relevance` is accepted for topical searches. For recent datasets,
  prefer an explicit `[pdat]` date range; `pub date` is not a reliable GDS sort
  schema.
- `usehistory`: set to `y` on broad `esearch` requests when you may need to
  page through many results or reuse the result set in follow-up Entrez calls.
- `WebEnv` and `query_key`: history-server tokens returned by `esearch` when
  `usehistory=y`; pass them to compatible follow-up Entrez requests instead of
  resending long ID lists.

Useful GEO query tags:

- `GSE[ETYP]`: restrict to GEO Series records.
- `GSM[ETYP]`: sample-level records; use only when sample discovery is needed.
- `GPL[ETYP]`: platform records; rarely useful for dataset discovery.
- `Homo sapiens[Organism]` or `Mus musculus[Organism]`: organism filter.
- `2023:2026[pdat]`: publication/date range.
- assay terms such as `single-cell RNA-seq`, `scRNA-seq`, `single nucleus
  RNA-seq`, `bulk RNA-seq`, `spatial transcriptomics`, or `ATAC-seq`.

Default `record_path` values:

- GEO `esearch`: `esearchresult.idlist`
- GEO `esummary`: `result`

GEO Entrez history workflow:

- Use this when a broad GEO query may return more IDs than fit comfortably in
  one preview, or when SearchAgent needs reproducible pagination over the same
  result set.
- First call `esearch` with `usehistory=y`. The response includes
  `esearchresult.webenv`, `esearchresult.querykey`, `esearchresult.count`, and
  the first `idlist` page.
- For later pages, call `esearch` again with the same `term`, `retstart`, and
  `retmax`, or use `WebEnv` and `query_key` with compatible Entrez endpoints
  when retrieving summaries or linked records.
- Keep `save_raw=true`; if `WebEnv` or `query_key` is not visible in the compact
  preview, inspect the saved response with `search_raw_read`.

## ArrayExpress Parameters

Use `source="arrayexpress"` for the ArrayExpress scope inside the EBI BioStudies
API. General BioStudies search is intentionally not exposed.

Common `path` values:

- `ArrayExpress/search`: free-text search across ArrayExpress records.
- `studies/<accession>`: full study record for an accession.
- `studies/<accession>/info`: file/link/download metadata for an accession.

Common `params` for `ArrayExpress/search`:

- `query`: free-text query. Include organism, disease/tissue, assay, and
  technology terms.
- `page`: 1-based page number; default is 1.
- `pageSize`: records per page; this is filled from `max_items` if not provided.

Default `record_path` values:

- `ArrayExpress/search`: `hits`
- `studies/<accession>` and `studies/<accession>/info`: use `record_path="$"`
  when you want the full compact summary object.

## Input

`dataset_search` takes one argument, `request_json`, following the same style as
`academic_rest_request`.

Required:

- `source`: `geo` or `arrayexpress`

Optional common fields:

- `query`: convenience query string. For GEO `esearch`, it fills `params.term`.
  For ArrayExpress search, it fills `params.query`.
- `endpoint`: GEO Entrez endpoint, such as `esearch`, `esummary`, `efetch`,
  `elink`, or `einfo`; default is `esearch`.
- `path`: explicit path. Defaults to `<endpoint>.fcgi` for GEO and
  `ArrayExpress/search` for ArrayExpress.
- `params`: REST query parameters.
- `record_path`: dot path to the useful JSON records. Defaults to
  `esearchresult.idlist` for GEO `esearch`, `result` for GEO `esummary`, and
  `hits` for ArrayExpress search.
- `response_format`: `auto`, `json`, `text`, or `xml`.
- `max_items`: defaults to 30 in the tool when omitted; use 50 for broad
  screening
- `max_depth`, `max_string`, `text_head_chars`
- `timeout_sec` or `timeout_seconds`
- `save_raw`
- `raw_output_path`

## GEO Examples

Human liver cancer single-cell GEO Series:

```json
{
  "request_json": {
    "source": "geo",
    "endpoint": "esearch",
    "query": "GSE[ETYP] AND human[organism] AND hepatocellular carcinoma AND single-cell RNA-seq",
    "max_items": 30,
    "save_raw": true
  }
}
```

Recent human single-cell GEO Series:

```json
{
  "request_json": {
    "source": "geo",
    "endpoint": "esearch",
    "params": {
      "db": "gds",
      "term": "GSE[ETYP] AND Homo sapiens[Organism] AND single-cell RNA-seq AND 2023:2026[pdat]",
      "retmode": "json",
      "retmax": 30
    },
    "record_path": "esearchresult.idlist",
    "max_items": 30,
    "save_raw": true
  }
}
```

Broad GEO search with Entrez history tokens:

```json
{
  "request_json": {
    "source": "geo",
    "endpoint": "esearch",
    "params": {
      "db": "gds",
      "term": "GSE[ETYP] AND Homo sapiens[Organism] AND RNA-seq",
      "retmode": "json",
      "retmax": 50,
      "retstart": 0,
      "usehistory": "y"
    },
    "record_path": "esearchresult.idlist",
    "max_items": 50,
    "save_raw": true
  }
}
```

GEO metadata follow-up for candidate UIDs:

```json
{
  "request_json": {
    "source": "geo",
    "endpoint": "esummary",
    "params": {
      "db": "gds",
      "id": "200326201,200292071,200278074",
      "retmode": "json"
    },
    "record_path": "result",
    "max_depth": 5,
    "max_items": 10,
    "save_raw": true
  }
}
```

GEO linked PubMed records:

```json
{
  "request_json": {
    "source": "geo",
    "endpoint": "elink",
    "params": {
      "dbfrom": "gds",
      "db": "pubmed",
      "id": "200326201",
      "retmode": "json"
    },
    "max_depth": 5,
    "save_raw": true
  }
}
```

## ArrayExpress Examples

Single-cell RNA-seq ArrayExpress search:

```json
{
  "request_json": {
    "source": "arrayexpress",
    "query": "single cell RNA-seq",
    "max_items": 30,
    "save_raw": true
  }
}
```

Broad human tumor single-cell ArrayExpress screening:

```json
{
  "request_json": {
    "source": "arrayexpress",
    "params": {
      "query": "Homo sapiens tumor single cell RNA-seq",
      "page": 1,
      "pageSize": 50
    },
    "record_path": "hits",
    "max_items": 50,
    "save_raw": true
  }
}
```

ArrayExpress accession lookup:

```json
{
  "request_json": {
    "source": "arrayexpress",
    "path": "studies/E-MTAB-6701",
    "record_path": "$",
    "max_depth": 6,
    "save_raw": true
  }
}
```

ArrayExpress file/link metadata:

```json
{
  "request_json": {
    "source": "arrayexpress",
    "path": "studies/E-MTAB-6701/info",
    "record_path": "$",
    "max_depth": 4,
    "save_raw": true
  }
}
```

## Output Interpretation

Success returns top-level fields similar to `academic_rest_request`:

- `ok`
- `source`
- `base_url`
- `path`
- `method`
- `status_code`
- `content_type`
- `record_path`
- `raw_output_path`
- `request_summary`
- `record_count_returned`
- `record_count_available`
- `truncated`
- `records`
- `warnings`

The `records` or `summary` payload is compacted directly from the source API
response. It is not normalized across databases. If a preview is truncated or
you need fields not shown, use `search_raw_read` on `raw_output_path`.

For GEO `esearch`, `records` are Entrez IDs. Do not present those IDs as dataset
accessions until an `esummary` follow-up confirms the accession and metadata.
For ArrayExpress search, `records` are BioStudies hit objects from the
ArrayExpress search scope.

## Handoff Guidance

When returning dataset candidates to BioInCoder, include:

- accession and source
- repository/source
- title
- organism and assay if available
- disease/tissue relevance
- URL
- download URL or file/link counts if available
- raw response path when follow-up inspection may be needed
- limitations, especially when sample counts or downloadable files were not
  confirmed

Do not claim a dataset is analysis-ready unless raw files, metadata, and sample
labels have been verified from the source record or follow-up inspection.

If the next step requires opening repository landing pages or downloading files,
return URLs and candidate accessions for BioInCoder to hand off to BrowserAgent
or ReadAgent. SearchAgent should not perform browser navigation or local file
inspection.
