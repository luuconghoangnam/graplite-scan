# REPORTS.md — graplite-scan

## Current Direction

Goal: evolve `graplite-scan` from a strong practical repo scanner into a stable, trustworthy, reference-informed analysis tool for multiple real-world project types.

Constraints:
- Keep outputs concise and useful: `MAP.md` + `IMPACT.md`, with `ARCHITECTURE.mmd` only when it adds real value.
- Prefer practical wins over heavy platform/product sprawl.
- Preserve compatibility with `drops` while broadening support.
- Work in thin slices; every small completed task should end in a commit.

## Phase Tracking

### Phase R1 — Reference-driven reset and roadmap
Status: RUNNING
Owner: Coonie

Definition of Done:
- [x] Pull additional real-world reference repos into `references/`
- [x] Reassess which repos are worth learning from vs avoiding wholesale
- [x] Write a detailed roadmap covering quality, stability, trustworthiness, breadth, and update speed
- [ ] Start executing roadmap slices with one commit per completed sub-task

### Phase W1 — Web app excellence track
Status: RECEIVED
Owner: Coonie

Target outcome:
- Make `graplite-scan` excellent on modern TS/JS web apps (Next app router, React/Vite-ish, route/page/layout/provider/state patterns).

Planned thin slices:
- [x] Better frontend entry detection
- [x] Better app-router companion file awareness (`layout` / `template` / `loading` / `error` / `not-found` / `providers`)
- [ ] Route-segment chain understanding (same-segment grouping + parent shell influence)
- [ ] Better shared state/provider/context blast radius
- [ ] Framework-aware wording + regression fixtures
- [ ] Benchmark against 3–5 real web repos

### Phase D1 — C# desktop reliability track
Status: RECEIVED
Owner: Coonie

Target outcome:
- Make `graplite-scan` clearly useful on practical C# Windows app repos without requiring a full Roslyn pipeline.

Planned thin slices:
- [x] Baseline `.cs` / `.xaml` support
- [x] View ↔ ViewModel ↔ Command heuristic pass
- [x] `DataContext`, `vm:`, relay/delegate command patterns
- [x] `InitializeComponent` / `ICommand` property hints
- [ ] Better `ICommand` binding resolution across XAML ↔ code-behind ↔ ViewModel
- [ ] ViewModelLocator / resource-dictionary / static resource hints
- [ ] Constructor/service injection confidence improvements
- [ ] Benchmark against 2–3 real desktop repos

## Current Active Tasks

### [R1-T1] Pull real reference repos and reassess learning sources
Status: DONE
Notes:
- Added references: `honk`, `static-analysis`, `semgrep`, `lsif-node`, `bloop`
- Existing references kept: `code-review-graph`, `scip`, `scip-typescript`, `tree-sitter`
- Initial judgment:
  - Learn deeply from: `code-review-graph`, `scip`, `scip-typescript`, `tree-sitter`
  - Learn selectively from: `semgrep`, `bloop`
  - Learn mainly for landscape/benchmark context: `static-analysis`
  - Deprioritize implementation borrowing from: `lsif-node` (deprecated), `honk` (not directly relevant)

### [R1-T2] Convert reference study into an execution roadmap
Status: DONE
Notes:
- Roadmap stored in `docs/REFERENCE_DRIVEN_ROADMAP.md`

### [R1-T3] Begin roadmap execution with one-commit-per-slice discipline
Status: RUNNING
Notes:
- Latest completed implementation slices before roadmap formalization:
  - `765ce79` — `feat: deepen desktop and web app heuristics`
  - `cd83027` — `feat: improve app-router and desktop command heuristics`
- Next recommended slice:
  - Web: route-segment chain awareness
  - Desktop: stronger `ICommand` binding correlation

## Reference Repo Assessment

### High-value references
- `references/code-review-graph`
  - Why: incremental graph thinking, practical repo-context orientation, diff-aware workflows
  - Borrow: normalized internal graph ideas, selective context extraction, upgrade sequencing
  - Avoid copying: full MCP/product surface and broad platform complexity

- `references/scip`
  - Why: durable interchange model for semantic indexing
  - Borrow: structured symbol/occurrence model, long-term graph substrate ideas
  - Avoid copying: overcommitting too early to full semantic infra before heuristics are mature

- `references/scip-typescript`
  - Why: realistic path to improve TS/JS semantic quality without building parsers from scratch
  - Borrow: indexing assumptions, project-shape expectations, docs-driven usage patterns
  - Avoid copying: tight dependency on TS-only workflows as the sole engine

- `references/tree-sitter`
  - Why: future path for language-aware parsing when regex/heuristics hit a ceiling
  - Borrow: grammar-driven parsing direction, multi-language parser architecture ideas
  - Avoid copying: jumping too early into full parser integration across all languages

### Medium-value selective references
- `references/semgrep`
  - Why: mature rule/engine discipline, quality/reliability mindset, test culture
  - Borrow: fixture mentality, rule-style confidence patterns, language support discipline
  - Avoid copying: turning graplite into a rule-engine/security scanner product

- `references/bloop`
  - Why: code intelligence product architecture, symbol navigation/search thinking
  - Borrow: indexing/search architecture ideas, durable internal models, UX layering
  - Avoid copying: app/platform sprawl, conversational product complexity, heavy infra footprint

### Low-priority / context references
- `references/static-analysis`
  - Why: market map for benchmarking and future coverage planning
  - Borrow: landscape awareness and category discovery only

- `references/lsif-node`
  - Why: historical context only; deprecated

- `references/honk`
  - Why: not materially relevant to graplite core roadmap

## Quality Bar for "done"

A slice is only DONE when:
- code is implemented surgically
- scanner runs successfully on `graplite-scan`
- scanner smoke-test still works on `drops`
- output gets more useful or more correct, not just more verbose
- commit is created

## Next Suggested Implementation Order

1. Web route-segment chain awareness
2. Desktop `ICommand`/binding correlation improvement
3. Real benchmark fixtures + expected-output checks
4. Internal normalized graph shape for cross-feature reuse
5. Selective semantic deepening where heuristics plateau
