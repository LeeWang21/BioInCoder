---
name: literature-evidence-mining
description: Coordinate Agent for large-scale literature screening, paper-by-paper evidence extraction, supplementary file/resource retrieval, and structured evidence table construction. Use when users need to find many papers, screen literature, or extract specific information/resources from papers, full text, methods, PDFs, supplementary tables, datasets, protocols, catalog numbers, accession IDs, software versions, or other paper-linked evidence.
metadata:
  tool_type: orchestration
  primary_tools:
    - academic_search
    - browser_browse
    - read_artifact
  intended_agent: [BioInCoder, planner]
---

# BioInCoder Literature Evidence Mining

Use this skill when BioInCoder must coordinate multiple agents to find papers and extract specific evidence or resources from them.

This is an orchestration skill for BioInCoder. It is not a SearchAgent-only, BrowserAgent-only, or ReadAgent-only skill.

## Core Principle

Use planned, tracked, progressive evidence mining:

1. Define the evidence target, scope, search strategy, and stopping rule before mining.
2. Discuss materially ambiguous retrieval details with the user before large searches.
3. Search broadly enough to build a complete candidate table.
4. For large searches, use multiple rounds, keyword families, and sources.
5. Prioritize candidates, but do not drop lower-priority records from tracking.
6. Process papers one by one or in small batches in priority order.
7. Use the cheapest sufficient evidence source first.
8. Within each paper, search the most likely evidence location before reading broadly.
9. Escalate only when needed: metadata -> page evidence -> targeted section/page -> downloaded artifacts -> ReadAgent.
10. Update candidate and evidence tables after every paper or small milestone.

Do not stop just because high-priority papers produced an answer unless the user explicitly asked for only top results or a quick sample.

## Agent Roles

BioInCoder owns the workflow:

- define the evidence target and inclusion/exclusion criteria;
- write self-contained `task_brief` handoffs;
- maintain the complete candidate tracking table;
- decide priority order;
- integrate evidence;
- decide whether to continue, refine search, ask the user, or stop.

SearchAgent:

- retrieve candidate literature records and scholarly metadata;
- use academic databases and search tools;
- return identifiers and actionable URLs;
- do not open webpages, download files, or read local artifacts.

BrowserAgent:

- open specific URLs/DOIs/PMCID pages;
- inspect page-level evidence;
- find full text, PDF, supplementary files, resource links, and dataset links;
- download artifacts when page-level evidence is insufficient;
- do not deeply read downloaded PDF/Excel/Word/PowerPoint files.

ReadAgent:

- inspect local files downloaded by BrowserAgent or provided by the user;
- use targeted conversion/search to extract evidence snippets and values;
- do not browse the web or start new literature searches.

## Phase 0: Plan Evidence Mining

Before mining or delegating, BioInCoder should create or reset a plan with
`write_plan` for non-trivial evidence-mining tasks. The plan should cover:

- the evidence fields to extract;
- target paper scope;
- search sources and query families;
- inclusion and exclusion criteria;
- expected evidence locations inside papers;
- screening scale, batch size, and stopping condition;
- output table schema and evidence standard.

If the search will be broad, expensive, or sensitive to wording, discuss the
search details with the user before starting large-scale retrieval. Ask only
for decisions that materially change the search:

- exhaustive vs best-effort vs top-N;
- required date range;
- preferred literature sources;
- whether preprints should be included;
- required evidence strictness, such as exact snippet/table vs summary-level evidence;
- key synonyms, gene/protein aliases, model systems, tissue names, disease names,
  assay names, reagent names, software names, or dataset types.

After the user answers, update the plan or checklist before continuing.

## Phase 1: Define Evidence Target

Before delegating, BioInCoder should identify:

- target evidence fields, such as antibody catalog number, reagent vendor, dataset accession, software version, primer sequence, cell line, animal model, protocol, supplement table, code URL, or resource file;
- target paper scope: disease, species, tissue, method, intervention, date range, paper type;
- inclusion and exclusion criteria;
- whether the user wants exhaustive screening, best-effort screening, or top-N screening;
- whether page evidence is enough or exact file/table snippets are required;
- desired final table format;
- likely evidence locations inside each paper.

Ask the user only when a missing criterion would materially change screening.

## Phase 2: Candidate Search

Use SearchAgent to retrieve a broad candidate set.

For large-scale literature tasks, do not accept an incomplete summary as the
candidate set. Ask SearchAgent to retrieve records according to the requested
coverage goal and to explain whether coverage was constrained by query
specificity, source coverage, deduplication, relevance filtering, or source
behavior.

### Multi-Round Search Strategy

For broad mining, SearchAgent should use a search matrix instead of one query.
Combine:

- concept families: target biology, disease/phenotype, method/assay, model
  system, perturbation, resource type, software/tool, dataset type;
- synonyms and aliases: gene symbols, protein names, old names, MeSH terms,
  assay abbreviations, species terms, tissue aliases, vendor/resource names;
- evidence-bearing words: antibody, clone, catalog, accession, GEO, SRA,
  code, GitHub, supplement, Table S, method, protocol, primer, reagent,
  availability;
- source families: PubMed, Europe PMC, OpenAlex, Semantic Scholar, arXiv,
  bioRxiv/medRxiv when appropriate.

Use multiple rounds when coverage matters:

1. Broad discovery queries to identify the candidate universe.
2. Focused evidence queries that add evidence-bearing terms.
3. Source-specific follow-up queries for missing identifiers or open full text.
4. Backfill queries for key synonyms, spelling variants, older names, or
   user-provided terms.
5. Optional citation/bibliography expansion when the first rounds reveal a
   small set of central papers.

Each round should record:

```text
round_id
source
query
filters
records_returned
new_unique_records
reason_for_query
coverage_notes
```

Stop broad searching only when the planned coverage target is met, the
remaining sources are unlikely to add relevant records, or a blocker requires
user input.

SearchAgent output must include a candidate table with:

```text
candidate_id
priority_rank or provisional_priority
title
year
journal_or_source
PMID
PMCID
DOI
URL
source_database
relevance_reason
include_exclude_status
screening_notes
```

If records come from multiple sources, BioInCoder must merge and deduplicate by DOI, PMID, PMCID, title, and URL.

Do not lose candidate records when summarizing. Stage reports may be short, but the master candidate table must remain complete.

## Phase 3: Prioritize Without Dropping Records

BioInCoder should rank candidates by likelihood of containing the target evidence.

Priority factors may include:

- direct mention of the target entity or method in title/abstract;
- full text or PMCID availability;
- likely use of methods/reagents/resources;
- recency, paper type, and source quality;
- user-specified importance.

Keep all candidates in the master table. Use priority labels such as:

```text
high
medium
low
out_of_scope
duplicate
```

Lower-priority candidates may be delayed, but not silently discarded.

## Phase 4: Process One Paper at a Time

Default mode is one-paper-at-a-time evidence closure.

For each candidate in priority order:

1. State the evidence focus for this candidate.
2. Choose the likely evidence locations to inspect first.
3. Check whether metadata already answers the target.
4. If not, call BrowserAgent for that paper with the target locations.
5. If BrowserAgent finds sufficient page-level evidence, integrate it and continue to the next paper.
6. If BrowserAgent downloads relevant artifacts or page evidence is insufficient, call ReadAgent for those artifacts with targeted keywords and location hints.
7. Integrate ReadAgent evidence.
8. Update candidate status and evidence table.
9. Continue to the next candidate unless the user requested a stopping condition that is now satisfied.

This one-paper loop improves traceability and lets BioInCoder adjust strategy after each result.

## Evidence Location Strategy

Before opening or reading a paper, identify what kind of evidence is needed and
inspect the most likely locations first. Do not read a whole article or dump a
whole PDF when a targeted section, table, or supplement is likely to answer the
question.

Common evidence targets and likely locations:

```text
antibody/reagent catalog, clone, vendor:
  methods, key resources table, resource availability, STAR Methods,
  supplementary methods, supplement tables

dataset accession:
  data availability, methods, abstract/metadata, GEO/SRA/ArrayExpress links,
  supplementary information, article landing page

code/software URL or version:
  code availability, data/code availability, methods, GitHub links,
  software section, supplementary methods

sample size, cohort, species, tissue, cell line, animal model:
  abstract, methods, results overview, table 1, study design, supplement tables

algorithm, benchmark metric, model architecture:
  methods, results figures, benchmark tables, supplementary methods,
  supplementary tables, code repository

mechanistic claim or biological conclusion:
  abstract, specific result section, figure legend, discussion, cited evidence

protocol detail, primer sequence, guide RNA, perturbation design:
  methods, supplementary methods, supplementary tables, protocol repository

resource/file availability:
  data availability, supplementary files, article landing page, publisher
  attachments, repository records
```

Use progressive disclosure inside each paper:

1. Metadata and abstract for inclusion/exclusion and quick hints.
2. Page-level article sections and article landing page links.
3. Targeted article sections: methods, data/code availability, key resources,
   results subsection, figure legend, discussion.
4. Supplement list and supplement descriptions.
5. Downloaded artifacts only when the likely evidence is not visible on page.
6. ReadAgent targeted search inside downloaded artifacts.

When evidence is not found, record which locations were checked. This is part
of the evidence standard.

## Progressive Evidence Escalation

Use the cheapest sufficient evidence source.

### 1. Metadata Evidence

Use metadata when it is enough for screening, such as title/abstract clearly excluding a paper.

Do not use metadata alone for exact fields such as catalog numbers, accession IDs, reagent clones, or supplement table values unless the metadata explicitly contains the field.

### 2. Page-Level Evidence

Use BrowserAgent when a web page must be opened.

BrowserAgent may directly extract page evidence from:

- PubMed/PMC pages;
- abstract and metadata pages;
- publisher method sections;
- data/code availability sections;
- key resources tables;
- figure legends or result subsections;
- article landing pages;
- supplement description sections;
- dataset/resource pages.

If page-level evidence is sufficient, do not call ReadAgent.

BrowserAgent should return:

```text
candidate_id
visited_url
access_status
page_evidence_found: yes/no
page_evidence_summary
evidence_snippet_or_location
locations_checked
downloaded_artifacts
read_agent_needed: yes/no
reason
blocked_reason
recommended_next_step
```

### 3. Artifact Retrieval

BrowserAgent downloads artifacts only when needed:

- PDF/full text;
- supplementary PDF;
- XLSX/CSV/TSV tables;
- DOCX/PPTX files;
- ZIP archives;
- dataset files or metadata files.

BrowserAgent must report `file_path` and `metadata_path` for each downloaded artifact.

### 4. Local Artifact Reading

Call ReadAgent only when:

- a downloaded/local artifact likely contains the target evidence;
- page evidence is incomplete;
- exact snippets, tables, sheets, or sections are needed;
- the user provided local files.

Do not call ReadAgent when BrowserAgent already found sufficient page evidence.

ReadAgent should return:

```text
candidate_id
file_path
matched_terms
section_table_or_sheet
locations_checked
evidence_snippet
extracted_value
confidence
limitations
read_agent_needed_next: yes/no
```

## Tracking Tables

Maintain two tables.

### Candidate Tracking Table

This table prevents missed literature:

```text
candidate_id
priority
title
year
journal_or_source
PMID
PMCID
DOI
URL
source_database
relevance_reason
planned_evidence_locations
status
notes
```

Recommended status values:

```text
queued
in_progress
metadata_screened
page_evidence_found
artifact_downloaded
read_evidence_found
evidence_found
evidence_not_found
excluded
duplicate
blocked_paywall
blocked_antibot
needs_user_input
deferred_low_priority
```

### Evidence Extraction Table

This table captures extracted evidence:

```text
candidate_id
title
PMID
DOI
target_field
extracted_value
evidence_source
evidence_snippet
source_url
file_path
section_table_or_sheet
locations_checked
confidence
limitations
next_action
```

Every extracted claim should have a URL, identifier, file path, table/section, or snippet.

## Stage Reports

For long tasks, report progress periodically without losing the master tables.

Report interim results when useful evidence has accumulated, when a batch boundary is reached, or when progress may take a long time. Good reporting points include:

- after the initial candidate table is built and prioritized;
- after every 5-10 processed candidates;
- after any strong evidence is found;
- after repeated blockers suggest a strategy change;
- before switching from search to browsing, or from browsing to reading;
- before asking the user for access, credentials, institution choice, or a scope decision.

A stage report may include:

```text
processed: 5/63
evidence_found: 2
not_found: 1
blocked: 1
needs_user_input: 1
remaining: 58
next_candidate: candidate_006
```

For evidence-mining tasks, an interim report should usually include:

- a short progress summary;
- newly found high-value evidence with candidate_id and source;
- new blockers or limitations;
- the next planned candidate or action;
- the location or current state of the complete candidate/evidence tables.

Stage reports are not a substitute for the full candidate table. After a stage report, continue the tracked workflow unless the user changes the objective or explicitly stops.

## Failure and Blocking Rules

Do not retry one paper forever.

If a paper is blocked:

- record the exact blocker;
- preserve URL, DOI/PMID, and attempted path;
- mark the candidate status;
- continue to the next candidate when possible.

Use `needs_user_input` for:

- institution selection;
- visible CAPTCHA or two-factor authentication;
- required credentials;
- ambiguous user preference;
- license/access permission decisions.

## Task Brief Templates

BioInCoder must write self-contained `task_brief` messages. Subagents do not receive the full BioInCoder conversation.

### SearchAgent

```text
# Overall Goal
Find papers that may contain [target evidence].

# Current Subtask
Retrieve a broad candidate set for screening using multiple query families and
sources when coverage matters.

# Relevant Context
[disease/species/method/target/resource constraints]

# Inputs
Search concepts:
Keyword families and aliases:
Evidence-bearing terms:
Inclusion criteria:
Exclusion criteria:
Date range:
Preferred sources:
Coverage target:

# Scope Boundary
Do not open webpages, download files, or read local artifacts.

# Required Output
Return search_rounds plus a complete candidate table with candidate_id, title,
year, journal/source, PMID, PMCID, DOI, URL, source_database, relevance_reason,
provisional_priority, and screening_notes.

# Stop Condition
Stop after the requested coverage goal is reached, selected databases are exhausted, or clear source limitations prevent further retrieval.

# Handoff
BioInCoder will prioritize candidates and send individual papers to BrowserAgent.
```

### BrowserAgent

```text
# Overall Goal
Extract or locate evidence for [target field] from the candidate paper.

# Current Subtask
Open this specific paper/page and look for page-level evidence, full text, PDF,
supplementary files, resource links, or dataset links.

# Relevant Context
Candidate_id:
Title:
PMID/PMCID/DOI:
Target evidence fields:
Evidence focus:
Likely evidence locations to check first:
Known prior findings:

# Inputs
URL(s):

# Scope Boundary
Do not start a broad literature search. Do not deeply read downloaded PDF/Excel/Word/PPT files. Download artifacts and return paths if file inspection is needed.

# Required Output
Return access_status, locations_checked, page_evidence_found, evidence
snippet/location if found, downloaded_artifacts with file_path/metadata_path,
read_agent_needed yes/no, blockers, and recommended next step.

# Stop Condition
Stop after checking the specified page and directly linked full text/supplement/resource artifacts, or after a clear access/blocking condition.

# Handoff
BioInCoder will integrate page evidence or pass downloaded artifacts to ReadAgent.
```

### ReadAgent

```text
# Overall Goal
Extract [target evidence] for candidate [candidate_id].

# Current Subtask
Inspect the listed local artifact(s) for exact evidence values and snippets.

# Relevant Context
Candidate_id:
Title:
Target evidence fields:
Evidence focus:
Likely evidence locations:
Known BrowserAgent findings:

# Inputs
file_path(s):
source URL(s):
keywords/aliases:
section/table/sheet hints:

# Scope Boundary
Do not browse the web or search literature. Do not inspect unrelated files.

# Required Output
Return extracted_value, evidence_snippet, file_path, locations_checked,
section/table/sheet if available, confidence, and limitations.

# Stop Condition
Stop after the requested artifacts are searched or the evidence is found with sufficient support.

# Handoff
BioInCoder will update the evidence table and continue to the next candidate.
```

## Stop Conditions

Continue through the candidate table unless:

- the user explicitly requested only top-N or quick best-effort results;
- the user asks to stop;
- all candidates are processed;
- remaining candidates are out of scope or duplicates;
- progress is blocked by user-required access decisions.

If enough evidence has been found but candidates remain, report the preliminary result and ask whether to continue only when the user did not request exhaustive screening.
