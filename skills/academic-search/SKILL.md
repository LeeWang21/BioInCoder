---
name: bioincoder-academic-search
description: Construct flexible JSON requests for BioInCoder academic_search using academic_rest_request across PubMed/NCBI Entrez, Europe PMC, bioRxiv/medRxiv, arXiv, OpenAlex, and Semantic Scholar. Use when searching papers, preprints, scholarly metadata, citations, or biomedical database records.
metadata:
  tool_type: search
  primary_tool: academic_rest_request
---

# BioInCoder Academic Search

Use this skill when SearchAgent needs to construct JSON for `academic_rest_request`.

The tool is intentionally flexible. Choose the database first, then write one compact JSON object.

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

- For literature retrieval, prefer result windows around 50 records by default.
- Use larger windows or multiple requests when the objective needs broad coverage, recent literature, method comparison, or review-style retrieval.
- Use small windows only for targeted identifier lookup, DOI lookup, or quick verification.
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
    "retmax": 50,
    "sort": "relevance"
  },
  "record_path": "esearchresult.idlist",
  "max_items": 50
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
  "record_path": "result",
  "max_items": 50
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
    "pageSize": 50,
    "sort": "RELEVANCE"
  },
  "record_path": "resultList.result",
  "max_items": 50
}
```

Date-limited example:

```json
{
  "source": "europepmc",
  "path": "search",
  "params": {
    "query": "(spatial transcriptomics) AND FIRST_PDATE:[2023-01-01 TO 2026-12-31]",
    "format": "json",
    "pageSize": 50
  },
  "record_path": "resultList.result",
  "max_items": 50
}
```

## bioRxiv / medRxiv

Use for recent preprint metadata. The API is date-window or DOI oriented, not general full-text search.

Recent bioRxiv details:

```json
{
  "source": "biorxiv",
  "path": "details/biorxiv/2026-01-01/2026-01-31/0/json",
  "record_path": "collection",
  "max_items": 50
}
```

DOI lookup:

```json
{
  "source": "biorxiv",
  "path": "details/biorxiv/10.1101/2024.01.01.123456/na/json",
  "record_path": "collection",
  "max_items": 5
}
```

medRxiv uses the same host with `medrxiv` in the path:

```json
{
  "source": "medrxiv",
  "path": "details/medrxiv/2026-01-01/2026-01-31/0/json",
  "record_path": "collection",
  "max_items": 50
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
    "max_results": 50,
    "sortBy": "relevance",
    "sortOrder": "descending"
  },
  "response_format": "xml",
  "text_head_chars": 12000,
  "max_items": 50
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
    "search": "spatial transcriptomics tumor microenvironment",
    "per-page": 50
  },
  "record_path": "results",
  "max_items": 50
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
    "limit": 50,
    "fields": "title,authors,year,venue,url,abstract,externalIds,citationCount"
  },
  "record_path": "data",
  "max_items": 50
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
