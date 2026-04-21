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
Status: RUNNING
Owner: Coonie

Target outcome:
- Make `graplite-scan` excellent on modern TS/JS web apps (Next app router, React/Vite-ish, route/page/layout/provider/state patterns).

Planned thin slices:
- [x] Better frontend entry detection
- [x] Better app-router companion file awareness (`layout` / `template` / `loading` / `error` / `not-found` / `providers`)
- [x] Route-segment chain understanding (same-segment grouping + parent shell influence)
- [x] Better shared state/provider/context blast radius
- [ ] Framework-aware wording + regression fixtures
- [ ] Benchmark against 3–5 real web repos

### Phase D1 — C# desktop reliability track
Status: RUNNING
Owner: Coonie

Target outcome:
- Make `graplite-scan` clearly useful on practical C# Windows app repos without requiring a full Roslyn pipeline.

Planned thin slices:
- [x] Baseline `.cs` / `.xaml` support
- [x] View ↔ ViewModel ↔ Command heuristic pass
- [x] `DataContext`, `vm:`, relay/delegate command patterns
- [x] `InitializeComponent` / `ICommand` property hints
- [x] Better `ICommand` binding resolution across XAML ↔ code-behind ↔ ViewModel
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
- Completed reference-roadmap execution slices:
  - `765ce79` — `feat: deepen desktop and web app heuristics`
  - `cd83027` — `feat: improve app-router and desktop command heuristics`
  - `579058c` — `docs: add reference-driven roadmap`
  - `b9b5987` — `feat: add route segment companion awareness`
  - `363d3d8` — `feat: improve desktop command binding correlation`
  - `47b7140` — `feat: refine provider and context blast radius`
- Benchmarking substrate now added in `docs/BENCHMARK_MATRIX.md`
- Concrete benchmark shortlist now chosen for web / backend / desktop / Flutter
- Expected observations are now drafted for web, backend, C# desktop, and Flutter benchmark candidates in `docs/BENCHMARK_MATRIX.md`
- Added a concrete MVVM-heavy WPF benchmark candidate: `CommunityToolkit/MVVM-Samples`
- Added a lightweight benchmark run checklist in `docs/BENCHMARK_MATRIX.md`
- First benchmark runs completed on `web-next`, `backend-nest`, `desktop-mvvm`, and `flutter-samples`
- Fixed benchmark miss #1: top-level `app/` / `ui/` roots were not being scanned as frontend candidate roots, causing weak app-router flow detection on `web-next`
- Fixed benchmark miss #2: sample/multi-app repos with sparse import graphs (`desktop-mvvm`, `flutter-samples`) now get structural fallback impact instead of empty impact sections
- Fixed benchmark miss #3: backend-dominant package repos like `backend-nest` no longer leak frontend/shared-state wording from generic `/context/` or `/providers/` paths
- Fixed benchmark miss #4: sample-corpus repos (`desktop-mvvm`, `flutter-samples`) now emit repo-level architecture summaries instead of falling back to “No high-confidence architecture summary detected yet.”
- Fixed benchmark miss #5: sample-corpus summaries now rank more representative roots first instead of leading with incidental samples
- Fixed benchmark miss #6: multi-root desktop sample repos now correlate page views to concrete `ViewModel` files instead of staying shell-only
- Fixed benchmark miss #7: fallback desktop output now separates `ViewModel` vs service vs command buckets more cleanly instead of duplicating the same file across all three
- Fixed benchmark miss #8: sample-corpus repos now emit restrained fallback module-group summaries instead of leaving `Module / feature groups` blank
- Fixed benchmark miss #9: desktop fallback now rebuilds service buckets from matched `ViewModel` code instead of leaving them mostly empty
- Fixed benchmark miss #10: desktop fallback command links now use explicit command-property evidence instead of broad framework-kind/path-only matching
- Fixed benchmark miss #11: desktop fallback buckets are now re-ranked so page-local ViewModels and real services outrank broader shared matches and `*ServicePage.xaml.cs` naming collisions
- Follow-up note for miss #11: ranking is materially better, but generic command-heavy ViewModels can still rank too high when broad command names are reused across many samples
- Next recommended slice:
  - Tighten command ranking again using stronger page-local vs shared-command penalties for generic ViewModels
  - Improve ranking within fallback module groups so strongest representative roots appear first more consistently
  - Add a lightweight benchmark regression checklist for the current benchmark set

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

1. Pick concrete benchmark candidates across web / backend / desktop / Flutter
2. Write expected observations and anti-noise checks for each candidate
3. Framework-aware wording + regression fixtures
4. Internal normalized graph shape for cross-feature reuse
5. Selective semantic deepening where heuristics plateau
