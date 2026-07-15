---
name: literature-evidence-mining
description: Coordinate BioInCoder, SearchAgent, BrowserAgent, and ReadAgent for literature or evidence-bearing record discovery, screening, and evidence extraction. Use when users need to plan a search, retrieve candidate records from literature or dataset databases, screen records using metadata and follow-up evidence, and report traceable screening results from papers, repository records, full text, methods, PDFs, supplementary files, datasets, protocols, catalog numbers, accession IDs, software versions, or other evidence-linked records.
metadata:
  tool_type: orchestration
  primary_tools:
    - academic_search
    - browser_browse
    - read_artifact
  intended_agent: [BioInCoder]
---

# BioInCoder Literature Evidence Mining

Use this skill when BioInCoder must coordinate multiple agents to find papers
or evidence-bearing repository records and extract specific evidence or
resources from them.

This is an orchestration skill for BioInCoder. It is not a SearchAgent-only, BrowserAgent-only, or ReadAgent-only skill.

This skill owns cross-agent evidence-mining strategy: scope definition, search
direction, candidate-record set construction, screening traceability,
processing order, stage reports, and task-brief templates.

## Core Principle

Use planned, tracked, progressive evidence mining:

1. Define the evidence target, scope, search strategy, and stopping rule before mining.
2. Discuss materially ambiguous retrieval details with the user before large searches.
3. Search broadly enough to build a candidate-record set that matches the
   requested coverage mode.
4. For large searches, use multiple rounds, keyword families, and sources.
5. Use retrieved metadata such as title, abstract, identifiers, accessions, and
   repository links to choose a suitable screening record set.
6. Process paper or dataset candidates one by one in a transparent order.
7. Use the cheapest sufficient evidence source first.
8. Within each paper or dataset, search the most likely evidence location before reading broadly.
9. Escalate only when needed: metadata -> page evidence -> targeted section/page -> downloaded artifacts -> ReadAgent.
10. Record screening decisions, evidence, blockers, and limitations after every
    record or small milestone so the workflow is auditable.

## Workflow Shape

Keep the workflow simple and traceable:

1. BioInCoder discusses scope with the user and defines the search plan.
2. BioInCoder delegates a self-contained search task to SearchAgent.
3. SearchAgent searches literature and, when relevant, dataset databases, then
   returns a potential screening record set with retained metadata.
4. BioInCoder uses that record set and its retained metadata to decide which
   records need metadata-only screening, BrowserAgent inspection, or ReadAgent
   artifact reading.
5. BioInCoder records the screening process and final decisions in a form
   appropriate for the task.

For long or high-value mining tasks, preserve the potential screening record set and screening log as
local artifacts such as CSV, TSV, Markdown, or JSON, and report the file paths.

## Agent Roles

BioInCoder owns the workflow:

- define the evidence target and inclusion/exclusion criteria;
- write self-contained `task_brief` handoffs;
- maintain the potential screening record set and screening log;
- decide screening order;
- integrate evidence;
- decide whether to continue, refine search, ask the user, or stop.

SearchAgent:

- retrieve candidate literature records, scholarly metadata, and supported
  public dataset repository metadata;
- use academic databases, dataset databases, and search tools;
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
- target paper, dataset, or repository-record scope;
- search sources and query families;
- inclusion and exclusion criteria;
- expected evidence locations inside papers;
- screening scale, batch size, and stopping condition;
- reporting preference and evidence standard.

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
- target record scope: disease, species, tissue, method, intervention, date range, paper type, dataset type, or repository type;
- inclusion and exclusion criteria;
- whether the user wants exhaustive screening, best-effort screening, or top-N screening;
- whether page evidence is enough or exact file/table snippets are required;
- desired final reporting style;
- likely evidence locations inside each paper.

Ask the user only when a missing criterion would materially change screening.

## Phase 2: Candidate Search

Use SearchAgent to retrieve a potential screening record set.

Before delegation, BioInCoder should translate the user's request into a
coverage mode:

- `exhaustive`: maximize recall; keep broad records for later screening before
  applying narrow evidence-level filters.
- `best-effort`: balance recall and precision within the available time, source,
  and interaction limits.
- `top-N`: intentionally return only the requested number of strongest records
  and state the ranking basis.

Ask SearchAgent to retrieve records from appropriate entry points, including
literature databases and supported dataset databases such as GEO or ArrayExpress
when relevant. SearchAgent should use returned metadata such as title, abstract,
publication type, identifiers, dataset accession, repository fields
to produce a record set suitable for downstream screening.

Evidence fields that are often hidden in full text, supplementary files, sample
metadata, or repository records should usually be treated as downstream
screening targets, not hard first-pass search filters.

For broad or complete candidate retrieval, ask SearchAgent to save raw academic
or dataset API responses and use `search_raw_read` when compact previews are
truncated or insufficient for constructing the record set.

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
  bioRxiv/medRxiv, GEO, and ArrayExpress when appropriate.

Use multiple rounds when coverage matters:

1. Broad discovery queries to identify the candidate universe.
2. Focused evidence queries that add evidence-bearing terms.
3. Source-specific follow-up queries for missing identifiers, repository
   accessions, linked literature, or open full text.
4. Backfill queries for key synonyms, spelling variants, older names, or
   user-provided terms.
5. Optional citation/bibliography expansion when the first rounds reveal a
   small set of central papers.

Each round should leave enough trace for BioInCoder to understand what was
searched, why that source/query was chosen, how much it added, and why the
search moved on or stopped.

Stop broad searching only when the planned coverage target is met, the
remaining sources are unlikely to add relevant records, or a blocker requires
user input.

SearchAgent should return enough retained metadata for BioInCoder to understand
why each record may be worth screening, deduplicate records across sources, and
continue follow-up work. It should also explain the search rounds, coverage
limits, and stop reason well enough for BioInCoder to judge whether the
retrieval matched the requested coverage mode.

When raw academic or dataset API responses are saved, SearchAgent should report
the raw response paths and record paths so truncated or ambiguous metadata can
be audited later.

SearchAgent should not make final inclusion/exclusion decisions except for
records that are obviously unrelated.

If records come from multiple sources, BioInCoder must merge and deduplicate by
DOI, PMID, PMCID, title, and URL. Do not lose candidate records when
summarizing.

## Phase 3: Organize Records for Screening

BioInCoder takes SearchAgent's potential screening record set and retained raw
search metadata, then organizes records for downstream screening. This step
should be lightweight: merge obvious duplicates, preserve useful metadata, and
choose a screening order that matches the coverage mode.

Priority factors may include:

- direct mention of the target entity or method in title, metadata, abstract
  snippet
- likely use of methods/reagents/resources;
- recency, paper type, and source quality;
- user-specified importance.

Priority controls processing order, not whether a plausible record is kept. Use
simple status or priority labels only when they clarify the next action.

For exhaustive searches, lower-priority plausible records may be delayed but
should not be silently discarded. For top-N searches, the record set is allowed
to be intentionally small.

BioInCoder may store the organized record set as a table, list, Markdown note,
JSON artifact, or another task-appropriate structure.

Do not over-engineer the schema. Preserve the metadata needed to explain why
each record was screened, deferred, excluded, or passed to BrowserAgent or
ReadAgent.

## Phase 4: Screen Records One at a Time

Default mode is one-record-at-a-time evidence closure using the organized
screening order.

For each candidate in priority order:

1. State the evidence focus for this candidate.
2. Choose the likely evidence locations to inspect first.
3. Record or update the candidate's screening status.
4. Check whether retained metadata already answers the target.
5. If not, call BrowserAgent for that record with the target locations.
6. If BrowserAgent finds sufficient page-level evidence, add rows to the
   screening log, update candidate status, and continue to the next record.
7. If BrowserAgent downloads relevant artifacts or page evidence is insufficient, call ReadAgent for those artifacts with targeted keywords and location hints.
8. Integrate ReadAgent evidence into the screening log.
9. Update candidate status after every record or small milestone.
10. Continue to the next candidate unless the user requested a stopping condition that is now satisfied.

This one-record loop improves traceability and lets BioInCoder adjust strategy
after each result.

## Evidence Location Strategy

Shared evidence-mining principle: use the cheapest likely evidence source
first; inspect targeted likely locations before broad reading; escalate only
when the current layer is insufficient for the task's evidence standard.

Before opening or reading a paper, identify what kind of evidence is needed and
inspect the most likely locations first. Do not read a whole article or dump a
whole PDF when a targeted section, table, or supplement is likely to answer the
question.

Common evidence targets have predictable first-pass locations. Reagents are
often in methods, key resources, or supplementary methods. Dataset accessions
are often in data availability sections, methods, repository links, and
supplements. Code and software evidence is often in code availability, methods,
GitHub links, and supplementary methods. Cohort and sample evidence is often in
abstracts, methods, study design descriptions, table 1, and supplementary
tables. Protocol details are often in methods, supplementary methods, protocol
repositories, or supplementary tables.

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

Use the cheapest likely evidence source first. If it satisfies the task's
evidence standard, stop escalation for that candidate. If it is insufficient,
move to the next evidence layer with the narrowest useful request.

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

### Browser Access and Reliability

BrowserAgent owns the browser mechanics. For literature mining, BioInCoder's
job is to give BrowserAgent a focused target page/candidate, likely evidence
locations, any known access notes, and the required return fields.

If the page still cannot be used, BrowserAgent must mark the candidate with a
specific blocker such as `blocked_antibot`, `blocked_firewall`,
`blocked_login_required`, `blocked_paywall`, or `blocked_unstable_page`. The
stage report should tell the user which URL failed, what was tried at a useful
summary level, and what user action or alternate route might help.

### Authentication and User Coordination

When legitimate login or institutional access is needed to complete the task,
BrowserAgent should follow the browser skill. BioInCoder should only preserve
non-secret access context that helps later calls: institution selected, login
provider, auth state path, browser session name, manual step required, and
whether user input is still needed.

BioInCoder should preserve successful login notes in the screening log so later
BrowserAgent calls can reuse the same access route instead of rediscovering it.

BrowserAgent should report what was checked, what evidence was found or not
found, what blocked access if anything, what artifacts were downloaded, and
whether local artifact reading is needed. The goal is to let BioInCoder continue
screening without rediscovering the same page state.

### 3. Artifact Retrieval

BrowserAgent downloads artifacts only when needed:

- PDF/full text;
- supplementary PDF;
- XLSX/CSV/TSV tables;
- DOCX/PPTX files;
- ZIP archives;
- dataset files or metadata files.

When a file must be downloaded, BrowserAgent should first locate the direct file
URL and use `browser_download_artifact`. Do not rely on ad hoc shell download
commands or manual browser cache paths for normal paper PDFs, supplementary
files, tables, archives, or dataset metadata.

BrowserAgent must report `file_path` and `metadata_path` for each downloaded
artifact, plus any warning that affects whether ReadAgent can trust the file.

### 4. Local Artifact Reading

Call ReadAgent only when:

- a downloaded/local artifact likely contains the target evidence;
- page evidence is incomplete;
- exact snippets, tables, sheets, or sections are needed;
- the user provided local files.

Do not call ReadAgent when BrowserAgent already found sufficient page evidence.

ReadAgent should return the extracted evidence, where it was found, what was
searched, and any limitations. The goal is to make each extracted claim
auditable and let BioInCoder decide whether more browsing, reading, or screening
is needed.

## Screening Log and Reports

Maintain a screening log while processing records. The log can be a table, list,
Markdown section, JSON artifact, or another task-appropriate structure. It
should make the screening process auditable without forcing unnecessary schema
work.

For each screened record, preserve enough information to reconstruct why it was
included, excluded, deferred, blocked, or selected for deeper inspection:

- why the record was retained or prioritized for screening;
- what metadata, pages, sections, repository records, or artifacts were checked;
- what evidence was found or not found;
- what blocked progress, if anything;
- what should happen next for that record.

Every extracted claim should have a URL, identifier, file path, table/section, or snippet.
If no target evidence is found for a processed candidate, record a negative
evidence row or clear tracking note with the locations checked and limitations.

For long tasks, report progress periodically without losing the potential
screening record set, retained search metadata, or screening log.

Report interim results when useful evidence has accumulated, when a batch boundary is reached, or when progress may take a long time. Good reporting points include:

- after SearchAgent returns the potential screening record set;
- after a useful batch of records has been processed;
- after any strong evidence is found;
- after repeated blockers suggest a strategy change;
- before asking the user for access, credentials, institution choice, or a scope decision.

For evidence-mining tasks, an interim report should usually include:

- a short progress summary;
- newly found high-value evidence with enough source context to audit it;
- new blockers or limitations;
- the next planned candidate or action;
- the location or current state of the potential screening record set and
  screening log.

Stage reports are not a substitute for the retained record set and screening
log. After a stage report, continue the tracked workflow unless the user changes
the objective or explicitly stops.

## Failure and Blocking Rules

Do not retry one paper forever.

If a paper is blocked:

- record the exact blocker;
- preserve URL, DOI/PMID, and attempted path;
- record access attempts, waits/retries, alternate URLs, and login/auth state
  attempts when relevant;
- mark the candidate's current screening status;
- continue to the next candidate when possible.

Use `needs_user_input` for:

- institution selection;
- visible CAPTCHA or two-factor authentication;
- required credentials;
- ambiguous user preference;
- license/access permission decisions.

## Subagent Handoff Principles
This skill is intended for BioInCoder. Subagents do not need to load the full
orchestration skill. BioInCoder should translate the relevant parts of this
skill into each subagent's task_brief.

BioInCoder must write self-contained `task_brief` messages because subagents do
not receive the full BioInCoder conversation. The brief should explain the goal,
the current subtask, the relevant constraints, the scope boundary, and why the
requested work matters for the next screening step.

For SearchAgent, BioInCoder should explain the coverage mode, search direction,
important concepts and aliases, inclusion/exclusion intent, preferred sources,
and whether literature databases, dataset databases, or both should be used.
The brief should ask SearchAgent to return a potential screening record set with
enough retained metadata and search trace for BioInCoder to judge coverage,
deduplicate, and continue follow-up screening. SearchAgent should not be asked
to browse pages or make final screening decisions.

For BrowserAgent, BioInCoder should provide the specific record or page to
inspect, the target evidence, likely evidence locations, known identifiers or
URLs, and any access context that is safe to share. The brief should ask
BrowserAgent to report what it checked, what it found, what blocked access, what
was downloaded, and whether ReadAgent is needed. BrowserAgent should not start a
broad search or deeply read local artifacts.

For ReadAgent, BioInCoder should provide the local artifacts, target evidence,
keywords or aliases, and any page-level findings from BrowserAgent. The brief
should ask ReadAgent to report extracted evidence, where it was found, what was
searched, and what limitations remain. ReadAgent should not browse the web or
inspect unrelated files.


## Stop Conditions

Continue through the potential screening record set unless:

- the user explicitly requested only top-N or quick best-effort results;
- the user asks to stop;
- all candidates are processed;
- remaining candidates are out of scope or duplicates;
- progress is blocked by user-required access decisions.

If enough evidence has been found but candidates remain, report the preliminary result and ask whether to continue only when the user did not request exhaustive screening.
