# Reference Notes — `tirth8205/code-review-graph`

Purpose: selective learning notes for `graplite-scan`.

Goal is **not** to copy the product whole. Goal is to extract the highest-value technical ideas that improve:
- `MAP.md`
- `IMPACT.md`
- diff-aware impact precision
- future lightweight visualization

## Overall assessment

`code-review-graph` is strong as a **local code intelligence / impact graph** reference.

Most valuable parts are the ones that help answer:
- what changed?
- what is likely affected?
- how do I trace this visually or structurally?

Less valuable for `graplite-scan` right now are the broad product/platform layers.

## Worth learning deeply

### 1. Line-range -> symbol -> impact mapping
This is the most immediately valuable idea.

Why it matters:
- diff-based precision gets much better than file-only heuristics
- impact output becomes explainable
- route/file boosts can be tied to exact changed regions

How to adapt for `graplite-scan`:
- continue building changed-line-range plumbing
- connect diff hunks to SCIP occurrence/definition lines when available
- render a short "why this file was boosted" explanation

Priority: very high

### 2. Minimal normalized graph schema
Not a full graph product. Just enough structure to support better reasoning.

Useful minimal entities:
- node: file | symbol | route | feature-entry
- edge: imports | calls | owns | serves-route | uses-provider | impacts
- metadata: confidence, source (`heuristic` | `scip`), path, line

Why it matters:
- keeps future visualization/query work clean
- prevents heuristic sprawl
- makes later export possible without rewrite

Priority: high

### 3. Local persistent index/cache
The reference repo treats persistence as a feature, not an afterthought.

For `graplite-scan`, adapt in a smaller form:
- cache normalized scan artifacts in `.graplite/`
- reuse parsed SCIP summaries when inputs unchanged
- make later `scan` / `summary` / `visualize` commands cheaper

Priority: medium-high

### 4. Lightweight visualization mindset
The reference repo is a reminder that some relationships are easier to understand visually than in markdown.

For `graplite-scan`, do not jump to a full app yet.
Preferred thin-slice direction:
- export `graph.json`
- or generate Mermaid/HTML for a few focused views:
  - architecture overview
  - top hubs / chokepoints
  - changed-file blast radius
  - transfer/runtime flow

Priority: medium-high

## Only borrow carefully

### 5. Community / clustering ideas
Potentially useful later for architecture summaries.

But this should come *after* the graph schema is stable and useful.
Do not add clustering just because it looks advanced.

Priority: later

### 6. Queryable local storage
Interesting long-term if `graplite-scan` grows into a deeper repo intelligence tool.

But avoid premature productization.

Priority: later

## Not worth copying now

### A. Broad MCP / platform-install surface
This expands scope too early and shifts focus away from scan quality.

### B. Large product footprint
`graplite-scan` should stay thin, practical, and easy to reason about.

### C. Fancy graph features before core precision
Visualization is only as good as the underlying edges.
First improve correctness and explainability.

## Recommended adaptation plan for `graplite-scan`

### Phase 1 — strengthen precision (current focus)
- improve changed-line-range -> SCIP symbol mapping
- continue noise filtering
- improve boost explanations in `IMPACT.md`

### Phase 2 — define graph substrate
- add a minimal internal graph representation
- keep edges typed and source-tagged
- use it first for markdown generation, not UI

### Phase 3 — thin-slice visualization
- add one focused output such as:
  - `ARCHITECTURE.mmd`
  - `BLAST_RADIUS.mmd`
  - `graph.json`
- prefer static/portable outputs first

### Phase 4 — cache and incremental scan
- persist reusable scan artifacts in `.graplite/`
- avoid recomputing stable structures

## Practical rule

If an idea from `code-review-graph` helps us produce:
- cleaner output
- more correct impact analysis
- better explainability
- or a thin, portable visual summary

then it is worth adapting.

If it mainly adds product surface, maintenance burden, or hidden complexity,
then skip it for now.
