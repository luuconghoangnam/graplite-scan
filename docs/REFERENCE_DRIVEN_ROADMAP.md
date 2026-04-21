# Reference-Driven Roadmap for `graplite-scan`

## Why this roadmap exists

`graplite-scan` is already useful, but it is now in the hardest transition zone:
- beyond toy/demo quality
- already practical on real repos
- not yet generalized enough to feel "finished"

Instead of reinventing everything from scratch, this roadmap uses proven reference repos to selectively borrow the right ideas while preserving `graplite-scan`'s strengths:
- concise outputs
- practical impact reasoning
- offline/local-first scanning
- fast iteration

## Product standard to aim for

`graplite-scan` should become:
- **stable** — low regression rate, predictable outputs
- **clean** — low noise, readable summaries, minimal dumpiness
- **trustworthy** — users can believe the main impact stories most of the time
- **complete enough** — covers the key structural layers for each supported project class
- **detailed when needed** — can surface meaningful links and blast radius without overwhelming the user
- **fast to update** — new repo patterns can be added in thin slices, not heroic rewrites
- **benchmarkable** — quality can be evaluated against known real-world repos

## Non-goals

Do **not** turn `graplite-scan` into:
- a full security scanner like Semgrep
- a giant hosted code search product like Bloop
- an MCP/platform ecosystem before the core scanner is mature
- a full parser/index platform for every language all at once

## Current strengths to preserve

1. **Readable output quality**
   - `MAP.md` and `IMPACT.md` are compact and useful
   - output is onboarding-friendly, not a raw data dump

2. **Change-impact orientation**
   - the scanner tries to answer "what will likely break if I change this?"
   - this is more valuable than generic tree/index dumps

3. **Practical hybrid architecture**
   - heuristic-first where possible
   - structured help (like SCIP) where it materially improves quality
   - no requirement for a heavy setup path by default

4. **Fast local iteration**
   - able to improve quickly from real repo feedback

## Reference repo lessons

### 1) `references/code-review-graph`
Best lessons:
- diff-aware intelligence is high leverage
- normalized internal graph ideas matter
- incremental thinking matters
- practical context pruning matters

What to borrow:
- stronger internal graph normalization
- fixture/benchmark mindset
- change-focused prioritization

What to avoid:
- broad MCP/platform sprawl
- product complexity unrelated to core scanner quality

### 2) `references/scip`
Best lessons:
- semantic data needs a durable interchange model
- symbols/occurrences/definitions/references should not stay ad-hoc forever

What to borrow:
- structured symbol model thinking
- long-term substrate for semantic augmentation

What to avoid:
- overcommitting to deep semantic infra before heuristics and benchmarks are mature

### 3) `references/scip-typescript`
Best lessons:
- TS/JS indexing quality can be materially improved without inventing a parser
- project-shape conventions matter for quality

What to borrow:
- TS/JS semantic assist as a practical multiplier
- better expectations around project roots / inferred configs / structured symbols

What to avoid:
- making TS-only semantics the entire product strategy

### 4) `references/tree-sitter`
Best lessons:
- parser-based multi-language support is possible in layers
- syntax trees are a realistic next step after heuristic ceilings are reached

What to borrow:
- future parser architecture direction
- language grammar awareness

What to avoid:
- jumping prematurely into a huge parsing rewrite across all languages

### 5) `references/semgrep`
Best lessons:
- mature tools win through fixtures, discipline, and clear support boundaries
- quality comes from coverage + tests + low-noise output, not just engine cleverness

What to borrow:
- regression fixture culture
- support-matrix discipline
- confidence-aware quality bar

What to avoid:
- becoming a rule-engine or security scanner first

### 6) `references/bloop`
Best lessons:
- durable internal indexes and symbol navigation are powerful
- productized code intelligence benefits from clean internal abstractions

What to borrow:
- long-term index/search architecture ideas
- durable internal representation concepts

What to avoid:
- heavyweight product/platform complexity too early

### 7) `references/static-analysis`
Best lessons:
- the market is broad; coverage claims need benchmarking discipline

What to borrow:
- language/framework landscape awareness

What to avoid:
- confusing a tool directory with an implementation roadmap

## Quality model by project class

### A. Modern TS/JS web apps
Target quality: **excellent**

Must understand:
- app entrypoints
- pages/routes/app-router segments
- layouts/providers/shell
- hooks/stores/state/context/reducers
- shared UI surfaces
- route/page/app-shell blast radius

Roadmap slices:
1. Route-segment companion file awareness ✅ started
2. Parent/child segment chain awareness
3. Route-group and segment weighting
4. Provider/context propagation hints
5. Better app-shell influence scoring
6. Real benchmark repos + expected-output review

Success criteria:
- outputs feel natural on Next/React/Vite-ish repos
- page/layout/provider/state surfaces rank sensibly
- route/app-shell blast radius becomes believable

### B. TS/JS Node backends
Target quality: **excellent**

Must understand:
- backend entrypoints
- route registration
- controller/service/provider/gateway chains
- shared infrastructure layers
- diff-aware route impact

Roadmap slices:
1. keep improving route flow precision
2. expand support beyond current route patterns
3. improve controller/service matching confidence
4. tighten generic symbol noise filtering
5. benchmark on multiple backend styles

Success criteria:
- changing backend files produces believable impacted-route stories
- service/provider chain summaries stay concise and useful

### C. Flutter / hybrid app repos
Target quality: **very usable**

Must understand:
- main app entry
- feature pages/tabs/screens
- core/shared widgets/theme/platform/services
- app-side flow and shared-surface impact

Roadmap slices:
1. preserve quality while broadening other frameworks
2. benchmark against multiple non-DROPS Flutter repos
3. improve hybrid app/backend cross-surface summaries

Success criteria:
- no major regressions while generalized support improves

### D. C# desktop apps
Target quality: **good practical baseline → very usable**

Must understand:
- `Program.cs`, `App.xaml`, `MainWindow.xaml`
- `Views`, `ViewModels`, `Controls`, `Commands`, `Services`
- XAML bindings and viewmodel hints
- command wiring and service injection signals

Roadmap slices:
1. Baseline `.cs` + `.xaml` support ✅
2. DataContext / vm: / relay/delegate command heuristics ✅
3. `InitializeComponent` / `ICommand` signals ✅
4. stronger XAML command ↔ ViewModel command correlation
5. ViewModelLocator / StaticResource / ResourceDictionary hints
6. constructor/service injection confidence weighting
7. benchmark against real WPF/desktop repos

Success criteria:
- desktop impact section no longer says "nothing found" on common practical repos
- View ↔ ViewModel ↔ Command/Service inference becomes useful enough for onboarding/change review

### E. Python web/framework repos
Target quality: **basic structural support first**

Why not now:
- current highest ROI remains web TS/JS + C# desktop

When to start:
- after web + desktop tracks feel stable and benchmarkable

## Cross-cutting engineering roadmap

### 1. Reference-backed benchmark suite
Need:
- 3–5 web repos
- 2–3 backend repos
- 2–3 C# desktop repos
- 2–3 Flutter repos

For each benchmark repo, define:
- what the scanner should notice
- what should appear in `MAP.md`
- what should appear in `IMPACT.md`
- what should not appear (noise)

This is the single biggest missing ingredient for feeling "done".

### 2. Normalized internal graph shape
Need a clearer internal representation for:
- file roles
- route/page/screen shells
- shared surfaces
- semantic symbols (when available)
- impact edges

This should stay internal first, not a user-facing graph platform.

### 3. Confidence-aware heuristics
Every major inferred relation should trend toward:
- high-confidence
- medium-confidence
- fallback heuristic

This reduces false certainty and improves trustworthiness.

### 4. Fixture-driven regression discipline
Before claiming support for a new class, add:
- at least one real benchmark repo
- repeatable expected observations
- smoke checks on `graplite-scan`
- smoke checks on `drops`

### 5. Commit discipline
Every thin slice should:
- change one meaningful thing
- be smoke-tested
- be committed immediately

## Execution order

## Stage 1 — lock in web + desktop improvements
1. Web route-segment chain awareness
2. Desktop command-binding correlation improvement
3. Web provider/context blast radius refinement
4. Desktop ViewModelLocator/resource hints

## Stage 2 — benchmark and harden
5. Add benchmark matrix doc
6. Pull benchmark repos and define expected output criteria
7. Fix ranking/noise issues revealed by those repos
8. Add lightweight regression runner/checklist

## Stage 3 — strengthen the substrate
9. Internal normalized graph abstraction for impact reasoning
10. Confidence-aware ranking
11. Selective semantic expansion where heuristics plateau

## Stage 4 — widen support carefully
12. More backend route patterns
13. More desktop patterns
14. Basic Python web lane

## Definition of “near-perfect” for this product

`graplite-scan` can be considered near-perfect for its intended scope when:
- it is excellent on modern TS/JS web apps and Node backends
- it is very usable on Flutter hybrid repos
- it is genuinely useful on common C# desktop repos
- its output stays concise, readable, and low-noise
- changes are benchmarked against multiple real repos, not one familiar codebase
- new support is added by thin slices instead of destabilizing rewrites
- users trust its top impact stories most of the time

## Optimization backlog (detailed)

### A. Desktop ranking hardening
1. **Page-local command owner ranking**
   - Prefer ViewModels whose stem matches the current page/view stem.
   - Prefer command-property matches that appear in both XAML and the candidate ViewModel.
   - Down-rank generic command-heavy ViewModels that only match by broad shared command names.
   - Acceptance: `RelayCommandPage` / `AsyncRelayCommandPage` should rank their page-local ViewModel above unrelated command-heavy samples.

2. **Service ownership confidence weighting**
   - Prefer service links discovered from matched ViewModel dependencies over loose textual service-name mentions.
   - Down-rank service pages masquerading as service dependencies when they are only linked by naming coincidence.
   - Acceptance: desktop service buckets should favor `I*Service.cs` / concrete service implementations over unrelated `*ServicePage.xaml.cs` files.

3. **Resource-driven MVVM hints**
   - Add lightweight support for `ViewModelLocator`, `StaticResource`, and `ResourceDictionary`-style ViewModel discovery.
   - Acceptance: desktop repos using resource-based binding should stop looking shell-only.

### B. Sample-corpus presentation quality
4. **Representative-root ranking v2**
   - Score sample roots by app-ness, shell-ness, and feature representativeness.
   - Reduce incidental/demo root domination in `MAP.md` summaries.
   - Acceptance: top sample roots should look like the real center of gravity of the sample corpus.

5. **Module-group summary confidence**
   - Distinguish between inferred module groups and fallback representative groups.
   - Acceptance: summaries stay concise without implying false precision.

### C. Web/backend hardening
6. **Framework-aware wording layer**
   - Separate frontend app-shell wording from backend controller/provider wording more explicitly.
   - Acceptance: backend repos stop inheriting frontend phrasing from generic folder names.

7. **Regression fixtures/checklist**
   - Add a lightweight repeatable benchmark runner/checklist for `web-next`, `backend-nest`, `desktop-mvvm`, `flutter-samples`, and `drops`.
   - Acceptance: each thin slice can be checked quickly for regressions before commit.

### D. Substrate / trustworthiness
8. **Confidence-aware inferred links**
   - Tag major inferred links as strong / medium / fallback internally, even if not fully exposed in user-facing output yet.
   - Acceptance: ranking can prefer stronger evidence paths before looser textual hints.

9. **Normalized internal flow objects**
   - Move desktop/web/backend impact rows toward a clearer internal representation for page/view, owner, linked services, commands, and confidence.
   - Acceptance: future ranking/presentation changes become easier without repeated ad-hoc logic.

## Immediate next slice recommendation

Do this next:
1. tighten desktop page-local command owner ranking
2. commit
3. tighten desktop service ownership ranking
4. commit
5. improve representative-root ranking for sample corpora
6. commit
7. add lightweight regression checklist/runner notes
8. commit

That path gives the highest ratio of:
- practical value
- confidence gain
- future leverage
