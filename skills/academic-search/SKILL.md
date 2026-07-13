---
name: bioincoder-academic-search
description: Construct flexible JSON requests for BioInCoder academic_search using academic_rest_request across PubMed/NCBI Entrez, Europe PMC, bioRxiv/medRxiv, arXiv, OpenAlex, and Semantic Scholar. Use when searching papers, preprints, scholarly metadata, citations, or biomedical database records.
metadata:
  tool_type: search
  primary_tools:
    - academic_rest_request
    - search_raw_read
  intended_agent: [search]
---

# BioInCoder Academic Search

Use this skill when SearchAgent needs to construct JSON for `academic_rest_request`.

The tool is intentionally flexible. Choose the database first, then write one compact JSON object.

This skill owns academic API request patterns, source-specific query syntax,
record paths, and search-result response shaping. It does not own browser
navigation, local artifact reading, candidate tracking tables, or paper-by-paper
evidence-mining orchestration.

Allowed academic API hosts:

- `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`
- `https://www.ebi.ac.uk/europepmc/webservices/rest`
- `https://api.biorxiv.org`
- `https://export.arxiv.org/api`
- `https://api.openalex.org`
- `https://api.semanticscholar.org`

Accepted source aliases include:

- `pubmed`, `ncbi_entrez`, `ncbi`, `entrez`
- `biorxiv`, `bioarxiv`, `bio_rxiv`
- `medrxiv`, `med_rxiv`
- `arxiv`
- `europepmc`, `europe_pmc`
- `openalex`
- `semantic_scholar`, `semanticscholar`

General rules:

- Use the narrowest search that satisfies the task's coverage goal.
- For targeted identifier lookup, DOI/title verification, or quick checks, start
  narrow and avoid noisy broad retrieval.
- For broad screening, recent literature, method comparison, or review-style
  retrieval, search broadly enough, but expand through focused rounds rather
  than one noisy query.
- Escalate to additional sources, synonyms, date windows, or evidence-bearing
  terms only when the current round is insufficient for the requested coverage.
- When the objective involves recency or a relative time expression, use the runtime current date and convert it to exact date ranges.
- Use database-supported filters instead of broad free-text dumps.
- Use `record_path` for JSON APIs when the useful results are nested.
- Use `response_format: "text"` or `"xml"` for XML APIs such as arXiv Atom.
- Use `save_raw: true` for every `academic_rest_request` so the complete API
  response remains available for audit and follow-up inspection.
- Treat `records`, `summary`, and `text_head` from `academic_rest_request` as
  compact previews. If the preview is truncated or insufficient for the task
  goal, use `search_raw_read` on `raw_output_path` with `record_path` before
  finalizing results.
- Use `search_raw_read(index=...)` to inspect a specific truncated record,
  `search_raw_read(where={"doi": "..."})` or `where={"pmid": "..."}` to confirm
  identifiers, and `search_raw_read(offset=..., limit=...)` to build broad
  candidate tables in bounded batches.
- For XML/text raw files such as arXiv Atom responses, use
  `search_raw_read(offset_chars=..., limit_chars=...)` to inspect the saved raw
  response in bounded text chunks.
- Label bioRxiv/medRxiv results as preprints.
- If an initial request returns only IDs, run a second metadata request when needed.

## Input

`academic_rest_request` takes one argument, `request_json`. Keep examples and
tool calls in this shape:

```json
{
  "request_json": {
    "source": "pubmed",
    "endpoint": "esearch",
    "params": {
      "db": "pubmed",
      "term": "KRAS[Title/Abstract] AND colorectal cancer[Title/Abstract]",
      "retmode": "json"
    },
    "record_path": "esearchresult.idlist",
    "max_items": 25,
    "save_raw": true
  }
}
```

Required inside `request_json`:

- `source`: one accepted source alias, or `custom` with both `base_url` and
  `path`.

Common optional fields:

- `endpoint`: NCBI Entrez endpoint; used with `source="pubmed"` or
  `source="ncbi_entrez"` to build `<endpoint>.fcgi`.
- `base_url`: explicit HTTPS API root; only allowed hosts are accepted.
- `path`: endpoint path under `base_url`.
- `method`: `GET` or `POST`; most academic searches should use `GET`.
- `params`: REST query parameters.
- `json_body` or `form_body`: request body for POST APIs if needed; use only
  one.
- `record_path`: dot path to useful JSON records, such as
  `esearchresult.idlist`, `resultList.result`, `collection`, `results`, or
  `data`.
- `response_format`: `auto`, `json`, `text`, or `xml`.
- `max_items`: compact preview count for list/dict output. Use 20-50 for normal
  screening, smaller values for smoke tests, and `search_raw_read` for larger
  batches from saved raw.
- `max_depth`, `max_string`, `text_head_chars`: compact-preview controls.
- `timeout_seconds` or `timeout_sec`.
- `save_raw`: keep `true` unless the user explicitly wants a lightweight quick
  check.
- `raw_output_path`: optional relative path under `artifacts/search`.

## Source Selection

- Use PubMed/NCBI Entrez for biomedical article discovery, PMID metadata,
  MeSH-aware searches, and PubMed follow-up from known PMIDs.
- Use Europe PMC for broad life-science literature, PMCID/open-access metadata,
  DOI lookup, and topic-level preprint discovery.
- Use bioRxiv/medRxiv API for date-window or DOI follow-up of preprints. It is
  not a general topic search API.
- Use arXiv for computational biology, quantitative methods, statistics, and
  machine-learning papers.
- Use OpenAlex for broad scholarly discovery, DOI/title disambiguation, venue
  metadata, and cross-disciplinary coverage.
- Use Semantic Scholar for citation counts, influential citations, abstracts,
  and compact citation-context metadata.

## PubMed / NCBI Entrez

Use for biomedical literature metadata and PubMed IDs.

Common `endpoint` values:

- `esearch`: find PubMed IDs.
- `esummary`: retrieve metadata for PMID lists.
- `efetch`: retrieve richer XML or text records when summaries are insufficient.
- `elink`: find linked PMC, GEO, or related Entrez records.
- `einfo`: inspect database fields and capabilities.

Common `params`:

- `db`: usually `pubmed` for literature; use other Entrez databases only when
  the task explicitly requires them.
- `term`: Entrez query string.
- `id`: comma-separated IDs for `esummary`, `efetch`, or `elink`.
- `retmode`: use `json` for `esearch`, `esummary`, and `elink`; use `xml` for
  richer `efetch` records.
- `retmax`: number of IDs returned by `esearch`.
- `retstart`: pagination offset.
- `sort`: `relevance` for topical discovery, `pub date` for newest-first
  PubMed literature searches.
- `datetype`, `mindate`, `maxdate`: explicit date filtering. For publication
  date searches, `datetype=pdat` is common.

Useful PubMed query tags:

- title/abstract: `single-cell[Title/Abstract]`
- author: `Smith J[Author]`
- journal: `Nature[Jour]`
- publication date range: `2020:2026[pdat]`
- MeSH terms: `Neoplasms[MeSH Terms]`
- publication type: `Review[Publication Type]`, `Clinical Trial[Publication Type]`
- exact DOI: `10.1038/s41586-020-2649-2[DOI]`
- organism concepts: `Humans[MeSH Terms]`, `Mice[MeSH Terms]`

Topical PMID discovery:

```json
{
  "request_json": {
    "source": "pubmed",
    "endpoint": "esearch",
    "params": {
      "db": "pubmed",
      "term": "(KRAS[Title/Abstract]) AND (colorectal cancer[Title/Abstract])",
      "retmode": "json",
      "retmax": 25,
      "sort": "relevance"
    },
    "record_path": "esearchresult.idlist",
    "max_items": 25,
    "save_raw": true
  }
}
```

Recent PubMed search:

```json
{
  "request_json": {
    "source": "pubmed",
    "endpoint": "esearch",
    "params": {
      "db": "pubmed",
      "term": "spatial transcriptomics[Title/Abstract] AND tumor microenvironment[Title/Abstract]",
      "retmode": "json",
      "retmax": 30,
      "sort": "pub date",
      "datetype": "pdat",
      "mindate": "2023/01/01",
      "maxdate": "2026/07/13"
    },
    "record_path": "esearchresult.idlist",
    "max_items": 30,
    "save_raw": true
  }
}
```

Follow up IDs with `esummary`:

```json
{
  "request_json": {
    "source": "pubmed",
    "endpoint": "esummary",
    "params": {
      "db": "pubmed",
      "id": "12345678,23456789",
      "retmode": "json"
    },
    "record_path": "result",
    "max_depth": 5,
    "save_raw": true
  }
}
```

Retrieve XML for detailed inspection:

```json
{
  "request_json": {
    "source": "pubmed",
    "endpoint": "efetch",
    "params": {
      "db": "pubmed",
      "id": "12345678,23456789",
      "retmode": "xml"
    },
    "response_format": "xml",
    "text_head_chars": 12000,
    "save_raw": true
  }
}
```

## Europe PMC

Use for life-science literature across PubMed, PMC, preprints, DOI, and open-access metadata.

Common `path` values:

- `search`: literature search and identifier lookup.

Common `params` for `search`:

- `query`: Europe PMC query syntax.
- `format`: use `json`.
- `pageSize`: record count per page; use 20-50 for screening.
- `page`: page number for simple pagination.
- `cursorMark`: use for deep pagination when needed.
- `sort`: omit for default relevance, or use explicit supported values.
- `resultType`: `lite` for compact discovery; `core` for more metadata.

```json
{
  "request_json": {
    "source": "europepmc",
    "path": "search",
    "params": {
      "query": "single-cell RNA-seq pancreatic cancer",
      "format": "json",
      "pageSize": 25,
      "resultType": "core"
    },
    "record_path": "resultList.result",
    "max_items": 25,
    "save_raw": true
  }
}
```

Europe PMC defaults to relevance ranking when `sort` is omitted. Do not use
`sort: "RELEVANCE"`; it does not return a normal `resultList` response.

Date-limited example:

```json
{
  "request_json": {
    "source": "europepmc",
    "path": "search",
    "params": {
      "query": "(spatial transcriptomics) AND FIRST_PDATE:[2023-01-01 TO 2026-07-13]",
      "format": "json",
      "pageSize": 30,
      "sort": "P_PDATE_D desc"
    },
    "record_path": "resultList.result",
    "max_items": 30,
    "save_raw": true
  }
}
```

Known DOI lookup:

```json
{
  "request_json": {
    "source": "europepmc",
    "path": "search",
    "params": {
      "query": "DOI:\"10.1038/s41586-020-2649-2\"",
      "format": "json",
      "pageSize": 5,
      "resultType": "core"
    },
    "record_path": "resultList.result",
    "max_items": 5,
    "save_raw": true
  }
}
```

Useful Europe PMC query terms:

- publication date: `FIRST_PDATE:[2023-01-01 TO 2026-07-13]`
- source: `SRC:MED`, `SRC:PMC`, `SRC:PPR`
- open access: `OPEN_ACCESS:Y`
- full text availability: `HAS_FT:Y`
- PubMed ID: `EXT_ID:12345678 AND SRC:MED`
- DOI: `DOI:"10.1038/s41586-020-2649-2"`

Useful explicit sort values:

- `P_PDATE_D desc` for newest publication date first.
- `CITED desc` for citation count first.

## bioRxiv / medRxiv

Use for recent preprint metadata. The API is date-window or DOI oriented, not general full-text search.

Common `path` patterns:

- `details/biorxiv/YYYY-MM-DD/YYYY-MM-DD/<cursor>/json`
- `details/medrxiv/YYYY-MM-DD/YYYY-MM-DD/<cursor>/json`
- `details/biorxiv/<doi>/na/json`
- `details/medrxiv/<doi>/na/json`

Recent bioRxiv details:

```json
{
  "request_json": {
    "source": "biorxiv",
    "path": "details/biorxiv/2026-01-01/2026-01-31/0/json",
    "record_path": "collection",
    "max_items": 50,
    "save_raw": true
  }
}
```

DOI lookup:

```json
{
  "request_json": {
    "source": "biorxiv",
    "path": "details/biorxiv/10.1101/2024.01.01.123456/na/json",
    "record_path": "collection",
    "save_raw": true
  }
}
```

medRxiv uses the same host with `medrxiv` in the path:

```json
{
  "request_json": {
    "source": "medrxiv",
    "path": "details/medrxiv/2026-01-01/2026-01-31/0/json",
    "record_path": "collection",
    "max_items": 50,
    "save_raw": true
  }
}
```

For topic search in preprints, prefer Europe PMC first, then use bioRxiv/medRxiv API for DOI/date follow-up.

## arXiv

Use for computational methods, statistics, machine learning, and quantitative biology papers.

arXiv returns Atom XML. Use `response_format: "xml"` and summarize from `text_head`, or set `save_raw: true` for later parsing.

```json
{
  "request_json": {
    "source": "arxiv",
    "path": "query",
    "params": {
      "search_query": "all:\"single cell\" AND all:\"RNA seq\" AND cat:q-bio.GN",
      "start": 0,
      "max_results": 25,
      "sortBy": "relevance",
      "sortOrder": "descending"
    },
    "response_format": "xml",
    "text_head_chars": 12000,
    "save_raw": true
  }
}
```

Known arXiv ID lookup:

```json
{
  "request_json": {
    "source": "arxiv",
    "path": "query",
    "params": {
      "id_list": "2301.00001"
    },
    "response_format": "xml",
    "text_head_chars": 12000,
    "save_raw": true
  }
}
```

Common arXiv `params`:

- `search_query`: `all:`, `ti:`, `au:`, `abs:`, and `cat:` fielded query.
- `id_list`: comma-separated arXiv IDs for known-paper lookup.
- `start`: zero-based offset.
- `max_results`: result count.
- `sortBy`: `relevance`, `lastUpdatedDate`, or `submittedDate`.
- `sortOrder`: `ascending` or `descending`.

Common arXiv categories:

- `q-bio.GN`: genomics
- `q-bio.QM`: quantitative methods
- `cs.LG`: machine learning
- `stat.ML`: machine learning/statistics

## OpenAlex

Use for broad scholarly lookup, DOI/title search, and cross-disciplinary metadata.

Common `path` values:

- `works`: paper/work search.
- `works/doi:<doi>`: DOI lookup; URL-encode `/` in DOI values as `%2F`.
- `works/<openalex_id>`: known OpenAlex work lookup.

Common `params` for `works`:

- `search`: broad text search over works.
- `filter`: comma-separated filters such as publication dates, open access,
  type, DOI, author, institution, or concept filters.
- `sort`: supported work sort field, such as `publication_date:desc` or
  `cited_by_count:desc`.
- `per-page`: records per page; use 20-50.
- `cursor`: use `*` for cursor pagination when broad coverage is needed.
- `select`: comma-separated fields when compact output is preferred.

```json
{
  "request_json": {
    "source": "openalex",
    "path": "works",
    "params": {
      "search": "spatial transcriptomics tumor microenvironment",
      "filter": "from_publication_date:2023-01-01,to_publication_date:2026-07-13",
      "sort": "publication_date:desc",
      "per-page": 25
    },
    "record_path": "results",
    "max_items": 25,
    "save_raw": true
  }
}
```

OpenAlex DOI lookup:

```json
{
  "request_json": {
    "source": "openalex",
    "path": "works/doi:10.1038%2Fs41586-020-2649-2",
    "record_path": "$",
    "max_depth": 5,
    "save_raw": true
  }
}
```

## Semantic Scholar

Use for broad paper lookup and citation context. Keep requests small.

Common `path` values:

- `graph/v1/paper/search`: text search.
- `graph/v1/paper/DOI:<doi>`: DOI lookup; URL-encode `/` in DOI values as
  `%2F`.
- `graph/v1/paper/PMID:<pmid>`: PMID lookup.
- `graph/v1/paper/arXiv:<id>`: arXiv ID lookup.

Common `params`:

- `query`: text search query.
- `limit`: result count; keep small unless broad citation screening is needed.
- `offset`: pagination offset.
- `fields`: comma-separated fields to return. Ask only for fields needed for the
  task.

```json
{
  "request_json": {
    "source": "semantic_scholar",
    "path": "graph/v1/paper/search",
    "params": {
      "query": "single cell RNA-seq pancreatic cancer",
      "limit": 20,
      "fields": "title,authors,year,venue,url,abstract,externalIds,citationCount,influentialCitationCount"
    },
    "record_path": "data",
    "max_items": 20,
    "save_raw": true
  }
}
```

Semantic Scholar identifier lookup:

```json
{
  "request_json": {
    "source": "semantic_scholar",
    "path": "graph/v1/paper/DOI:10.1038%2Fs41586-020-2649-2",
    "params": {
      "fields": "title,authors,year,venue,url,abstract,externalIds,citationCount,references,citations"
    },
    "record_path": "$",
    "max_depth": 5,
    "save_raw": true
  }
}
```

## Search Patterns

For a biomedical topic:

1. Start with Europe PMC or PubMed.
2. If only IDs are returned, follow up with summary metadata.
3. Add bioRxiv/medRxiv only for recent preprints.
4. Add arXiv only for computational or quantitative methods.
5. Add OpenAlex or Semantic Scholar for broader discovery or citation context.

For a known identifier:

- PMID: PubMed `esummary`.
- DOI: Europe PMC `query: "DOI:<doi>"` or Semantic Scholar paper endpoint.
- arXiv ID: arXiv query by `id_list`.
- bioRxiv DOI: bioRxiv `details/<server>/<doi>/na/json`.

## Multi-Round Search Strategy

Use multiple focused rounds when the task asks for broad discovery, screening,
method comparison, recent coverage, or as many relevant records as possible.
Start with the most likely source/query family, then expand only when the
coverage goal is not met or source behavior suggests missing records. Do not
rely on one broad query when terminology, source coverage, or evidence words may
change the candidate set.

Useful round types:

1. Broad discovery:
   - combine the main biological, disease, method, organism, or tool concepts;
   - use PubMed or Europe PMC first for biomedical topics;
   - use OpenAlex or Semantic Scholar when broad scholarly coverage matters.
2. Evidence-bearing search:
   - add terms such as antibody, clone, catalog, accession, GEO, SRA, code,
     GitHub, supplement, Table S, method, protocol, primer, reagent,
     availability, benchmark, or dataset.
3. Synonym and alias backfill:
   - search gene/protein aliases, old names, assay abbreviations, disease
     synonyms, species names, tissue terms, vendor/resource names, and spelling
     variants supplied by the task brief.
4. Source-specific follow-up:
   - use exact PMID, PMCID, DOI, arXiv ID, title, or author fields to recover
     missing identifiers or metadata.
5. Recent/preprint follow-up:
   - use Europe PMC for topic-level preprint discovery;
   - use bioRxiv/medRxiv API for date-window or DOI follow-up;
   - label preprints clearly.

For each round, keep the returned summary traceable:

```text
round_id
source
query_or_request_summary
filters
records_returned
useful_records
coverage_notes
```

When returning a candidate table, include enough identifiers and URLs for
BioInCoder to deduplicate and route follow-up work. If coverage is incomplete,
state whether the limit came from query breadth, source behavior, API failure,
rate limits, date filters, or missing terminology.

## Response Guidance

Summarize records, do not dump raw JSON.

Include:

- source;
- title;
- year/date;
- authors if available;
- DOI/PMID/PMCID/arXiv ID if available;
- URL;
- one short relevance note.

Browser handoff requirements:

- Return a usable URL whenever possible.
- For DOI records, include `https://doi.org/<doi>`.
- For PubMed records, include PMID and PubMed URL when possible.
- For PMC records, include PMCID and PMC URL when possible.
- For arXiv records, include abstract URL and PDF URL when possible.
- For bioRxiv/medRxiv records, include DOI and page URL when possible.
- If no URL can be recovered, say which identifier is available and what follow-up request is needed.

Mention when:

- results are preprints;
- source metadata is incomplete;
- a query returned only IDs;
- a follow-up request failed;
- more precise terms are needed.
