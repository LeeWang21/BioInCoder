---
name: literature-evidence-mining
description: Coordinate Agent for large-scale literature screening, paper-by-paper evidence extraction, supplementary file/resource retrieval, and structured evidence table construction. Use when users need to find many papers, screen literature, or extract specific information/resources from papers, full text, methods, PDFs, supplementary tables, datasets, protocols, catalog numbers, accession IDs, software versions, or other paper-linked evidence.
metadata:
  tool_type: orchestration
  intended_agent: [BioInCoder, planner]
---

# BioInCoder Literature Evidence Mining

Use this skill when BioInCoder must coordinate multiple agents to find papers and extract specific evidence or resources from them.

This is an orchestration skill for BioInCoder. It is not a SearchAgent-only, BrowserAgent-only, or ReadAgent-only skill.

## Core Principle

Use tracked, progressive evidence mining:

1. Search broadly enough to build a complete candidate table.
2. Prioritize candidates, but do not drop lower-priority records from tracking.
3. Process papers one by one in priority order.
4. Use the cheapest sufficient evidence source first.
5. Escalate only when needed: metadata -> page evidence -> downloaded artifacts -> ReadAgent.
6. Update candidate and evidence tables after every paper or small milestone.

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

## Phase 0: Define Evidence Target

Before delegating, BioInCoder should identify:

- target evidence fields, such as antibody catalog number, reagent vendor, dataset accession, software version, primer sequence, cell line, animal model, protocol, supplement table, code URL, or resource file;
- target paper scope: disease, species, tissue, method, intervention, date range, paper type;
- inclusion and exclusion criteria;
- whether the user wants exhaustive screening, best-effort screening, or top-N screening;
- whether page evidence is enough or exact file/table snippets are required;
- desired final table format.

Ask the user only when a missing criterion would materially change screening.

## Phase 1: Candidate Search

Use SearchAgent to retrieve a broad candidate set.

For large-scale literature tasks, do not accept an incomplete summary as the candidate set. Ask SearchAgent to retrieve records according to the requested coverage goal and to explain whether coverage was constrained by query specificity, source coverage, deduplication, relevance filtering, or source behavior.

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

## Phase 2: Prioritize Without Dropping Records

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

## Phase 3: Process One Paper at a Time

Default mode is one-paper-at-a-time evidence closure.

For each candidate in priority order:

1. Check whether metadata already answers the target.
2. If not, call BrowserAgent for that paper.
3. If BrowserAgent finds sufficient page-level evidence, integrate it and continue to the next paper.
4. If BrowserAgent downloads relevant artifacts or page evidence is insufficient, call ReadAgent for those artifacts.
5. Integrate ReadAgent evidence.
6. Update candidate status and evidence table.
7. Continue to the next candidate unless the user requested a stopping condition that is now satisfied.

This one-paper loop improves traceability and lets BioInCoder adjust strategy after each result.

## Progressive Evidence Escalation

Use the cheapest sufficient evidence source.

### 1. Metadata Evidence

Use metadata when it is enough for screening, such as title/abstract clearly excluding a paper.

Do not use metadata alone for exact fields such as catalog numbers, accession IDs, reagent clones, or supplement table values unless the metadata explicitly contains the field.

### 2. Page-Level Evidence

Use BrowserAgent when a web page must be opened.

BrowserAgent may directly extract page evidence from:

- PubMed/PMC pages;
- publisher method sections;
- key resources tables;
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
Retrieve a broad candidate set for screening.

# Relevant Context
[disease/species/method/target/resource constraints]

# Inputs
Search concepts:
Inclusion criteria:
Exclusion criteria:
Date range:
Preferred sources:

# Scope Boundary
Do not open webpages, download files, or read local artifacts.

# Required Output
Return a complete candidate table with candidate_id, title, year, journal/source, PMID, PMCID, DOI, URL, source_database, relevance_reason, provisional_priority, and screening_notes.

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
Open this specific paper/page and look for page-level evidence, full text, PDF, supplementary files, resource links, or dataset links.

# Relevant Context
Candidate_id:
Title:
PMID/PMCID/DOI:
Target evidence fields:
Known prior findings:

# Inputs
URL(s):

# Scope Boundary
Do not start a broad literature search. Do not deeply read downloaded PDF/Excel/Word/PPT files. Download artifacts and return paths if file inspection is needed.

# Required Output
Return access_status, page_evidence_found, evidence snippet/location if found, downloaded_artifacts with file_path/metadata_path, read_agent_needed yes/no, blockers, and recommended next step.

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
Known BrowserAgent findings:

# Inputs
file_path(s):
source URL(s):
keywords/aliases:

# Scope Boundary
Do not browse the web or search literature. Do not inspect unrelated files.

# Required Output
Return extracted_value, evidence_snippet, file_path, section/table/sheet if available, confidence, and limitations.

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
