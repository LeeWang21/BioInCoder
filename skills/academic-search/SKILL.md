---
name: bioincoder-academic-search
description: Construct flexible JSON requests for BioInCoder academic_search using academic_rest_request across PubMed/NCBI Entrez, Europe PMC, bioRxiv/medRxiv, arXiv, OpenAlex, and Semantic Scholar. Use when searching papers, preprints, scholarly metadata, citations, or biomedical database records.
metadata:
  tool_type: search
  primary_tools:
    - academic_rest_request
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
- Use `save_raw: true` only when raw records are needed for audit or later processing.
- Label bioRxiv/medRxiv results as preprints.
- If an initial request returns only IDs, run a second metadata request when needed.

## PubMed / NCBI Entrez

Use for biomedical literature metadata and PubMed IDs.

Base shortcut:

```json
{
  "source": "pubmed",
  "endpoint": "esearch",
  "params": {
    "db": "pubmed",
    "term": "KRAS AND colorectal cancer",
    "retmode": "json",
    "sort": "relevance"
  },
  "record_path": "esearchresult.idlist"
}
```

Follow up IDs with `esummary`:

```json
{
  "source": "pubmed",
  "endpoint": "esummary",
  "params": {
    "db": "pubmed",
    "id": "12345678,23456789",
    "retmode": "json"
  },
  "record_path": "result"
}
```

Useful PubMed query tags:

- title/abstract: `single-cell[Title/Abstract]`
- author: `Smith J[Author]`
- journal: `Nature[Jour]`
- publication date: `2020:2026[pdat]`; for recent searches, use exact years calculated from the runtime current date
- organism: `human[MeSH Terms]` or `mouse[MeSH Terms]`

## Europe PMC

Use for life-science literature across PubMed, PMC, preprints, DOI, and open-access metadata.

```json
{
  "source": "europepmc",
  "path": "search",
  "params": {
    "query": "single-cell RNA-seq pancreatic cancer",
    "format": "json",
    "pageSize": 25
  },
  "record_path": "resultList.result"
}
```

Europe PMC defaults to relevance ranking when `sort` is omitted. Do not use
`sort: "RELEVANCE"`; it does not return a normal `resultList` response.

Date-limited example:

```json
{
  "source": "europepmc",
  "path": "search",
  "params": {
    "query": "(spatial transcriptomics) AND FIRST_PDATE:[2023-01-01 TO 2026-12-31]",
    "format": "json"
  },
  "record_path": "resultList.result"
}
```

Useful explicit sort values:

- `P_PDATE_D desc` for newest publication date first.
- `CITED desc` for citation count first.

## bioRxiv / medRxiv

Use for recent preprint metadata. The API is date-window or DOI oriented, not general full-text search.

Recent bioRxiv details:

```json
{
  "source": "biorxiv",
  "path": "details/biorxiv/2026-01-01/2026-01-31/0/json",
  "record_path": "collection"
}
```

DOI lookup:

```json
{
  "source": "biorxiv",
  "path": "details/biorxiv/10.1101/2024.01.01.123456/na/json",
  "record_path": "collection"
}
```

medRxiv uses the same host with `medrxiv` in the path:

```json
{
  "source": "medrxiv",
  "path": "details/medrxiv/2026-01-01/2026-01-31/0/json",
  "record_path": "collection"
}
```

For topic search in preprints, prefer Europe PMC first, then use bioRxiv/medRxiv API for DOI/date follow-up.

## arXiv

Use for computational methods, statistics, machine learning, and quantitative biology papers.

arXiv returns Atom XML. Use `response_format: "xml"` and summarize from `text_head`, or set `save_raw: true` for later parsing.

```json
{
  "source": "arxiv",
  "path": "query",
  "params": {
    "search_query": "all:single cell RNA seq AND cat:q-bio.GN",
    "start": 0,
    "sortBy": "relevance",
    "sortOrder": "descending"
  },
  "response_format": "xml",
  "text_head_chars": 12000
}
```

Common arXiv categories:

- `q-bio.GN`: genomics
- `q-bio.QM`: quantitative methods
- `cs.LG`: machine learning
- `stat.ML`: machine learning/statistics

## OpenAlex

Use for broad scholarly lookup, DOI/title search, and cross-disciplinary metadata.

```json
{
  "source": "openalex",
  "path": "works",
  "params": {
    "search": "spatial transcriptomics tumor microenvironment"
  },
  "record_path": "results"
}
```

## Semantic Scholar

Use for broad paper lookup and citation context. Keep requests small.

```json
{
  "source": "semantic_scholar",
  "path": "graph/v1/paper/search",
  "params": {
    "query": "single cell RNA-seq pancreatic cancer",
    "fields": "title,authors,year,venue,url,abstract,externalIds,citationCount"
  },
  "record_path": "data"
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
