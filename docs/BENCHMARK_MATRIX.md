# Benchmark Matrix for `graplite-scan`

## Purpose

This document exists to stop `graplite-scan` from improving by gut feel alone.

Every meaningful support claim should eventually be grounded in real repos and explicit expectations:
- what the scanner should notice
- what should show up in `MAP.md`
- what should show up in `IMPACT.md`
- what should stay out because it is noise

## Quality rule

A repo is only a valid benchmark when we can answer all four:
1. What project class is it?
2. What are the important structural surfaces?
3. What output do we expect from `MAP.md`?
4. What output do we expect from `IMPACT.md` when key files change?

---

## Tier 1 — active benchmark priorities

These are the most important benchmark categories right now.

### A. Web apps (highest current priority)
Target count: **3–5 repos**

What we need to validate:
- entry detection
- app-router segment understanding
- parent/child layout influence
- provider/context/state propagation
- shared UI surface ranking
- believable route/page blast radius

Expected `MAP.md` quality:
- should identify route/app shell surfaces cleanly
- should mention providers/layouts/hooks/stores when they materially shape runtime
- should avoid dumping generic component noise as if it were architecture

Expected `IMPACT.md` quality:
- changing `page/layout/providers/context/store` files should produce believable page/app-shell impact
- shared state files should fan out to meaningful route or shell consumers
- route-segment support files (`loading`, `error`, `not-found`) should not be treated as invisible side files

Suggested candidates:
- a Next.js app-router repo
- a React + Vite repo with routes + context/store
- a repo with provider-heavy app shell patterns
- a repo with nested route/layout hierarchy

### B. Node/TS backends
Target count: **2–3 repos**

What we need to validate:
- route registration discovery
- controller/service/provider/gateway chains
- backend entry detection
- diff-aware route impact

Expected `MAP.md` quality:
- should identify route surfaces and important service/provider layers
- should avoid drowning useful backend flow in utility noise

Expected `IMPACT.md` quality:
- changing controller/service/provider files should surface believable impacted routes
- top risk files should look business-relevant, not framework-generic

Suggested candidates:
- Express/Fastify/Nest-ish route-driven repo
- a service-oriented backend with controllers + services + providers
- a realtime or gateway-including backend if available

### C. C# desktop apps
Target count: **2–3 repos**

What we need to validate:
- WPF-ish structure detection
- `Views` / `ViewModels` / `Commands` / `Services`
- XAML binding hints
- `ICommand` / relay-command correlation
- viewmodel/service influence on impact output

Expected `MAP.md` quality:
- should identify desktop runtime shell and major UI layers
- should mention viewmodel/service/command structure in practical terms
- should not collapse into “nothing interesting found” on normal MVVM repos

Expected `IMPACT.md` quality:
- changing a view, viewmodel, or command should expose a useful interaction path
- command/service inference should feel directionally right often enough to trust during onboarding/review

Suggested candidates:
- one classic WPF MVVM repo
- one repo with commands/services/data binding patterns
- one repo with resource dictionaries or locator patterns later

### D. Flutter / hybrid repos
Target count: **2–3 repos**

What we need to validate:
- current `drops` quality remains intact
- app entry + feature screens + core widgets remain legible
- hybrid/shared-surface reasoning still works after web/desktop generalization

Expected `MAP.md` quality:
- should preserve practical app structure summaries
- should still identify feature pages/screens and important shared layers

Expected `IMPACT.md` quality:
- feature and shared-widget changes should still propagate sensibly
- no regression into web-biased nonsense on Flutter repos

Suggested candidates:
- `drops`
- one additional medium-sized Flutter app
- one hybrid repo with app + backend folders if available

---

## Benchmark review checklist

For each benchmark run, review these questions:

### Structural correctness
- Did the scanner find the right entrypoints?
- Did it identify the right project shape?
- Did it miss major runtime shells?

### Ranking quality
- Are the top highlighted files/components actually important?
- Did generic framework files outrank business-relevant files?
- Did shared surfaces show believable fan-out?

### Impact quality
- If I changed this file in real life, would these impact hints help me?
- Are provider/context/layout effects visible when they should be?
- Are command/service relationships visible when they should be?

### Noise control
- Is the output concise enough to scan quickly?
- Is anything present only because the heuristic is path-happy?
- Is anything obviously important still missing?

---

## Failure patterns to watch for

### Web
- treating route support files as unrelated leaf files
- missing provider/context propagation through ancestor layouts/providers
- over-ranking generic components and under-ranking app-shell files

### Backend
- route handlers found but service/provider chain too shallow
- generic framework symbols outranking business logic
- entrypoint present but route influence not visible in impact output

### Desktop
- finding views but not linking them to practical viewmodel/command/service paths
- detecting `ICommand` superficially without showing interaction shape
- over-reporting controls while under-reporting command/service influence

### Flutter
- regressions caused by over-generalizing for web
- shared widget noise crowding out actual feature surfaces
- hybrid repo summaries losing the real app flow

---

## Current benchmark status

### Web
- Status: **not benchmarked formally yet**
- Confidence: improving, but still based mostly on heuristic reasoning + smoke tests
- Immediate need: pick 3–5 real repos and define expected observations before claiming “excellent”

### Backend
- Status: **partially validated via DROPS backend**
- Confidence: good on known route/service/provider chains; not broad enough yet

### Desktop
- Status: **practical baseline exists, formal benchmarks missing**
- Confidence: useful directionally; needs real WPF/MVVM repos to test trustworthiness

### Flutter
- Status: **validated on DROPS, not enough external variety yet**
- Confidence: strong on current anchor repo, broader validation still needed

---

## Concrete benchmark shortlist

### Web
- `vercel/next-app-router-playground`
  - Why: direct pressure-test for nested app-router segments, layouts, loading/error boundaries, and provider-like app shell behavior.
- `calcom/cal.com`
  - Why: large real-world Next/web app with substantial app shell, routes, shared UI, and stateful frontend surfaces.
- `payloadcms/payload`
  - Why: rich modern web app/admin surface with shared providers, internal routing, and non-trivial frontend layering.

### Backend
- `fastify/fastify`
  - Why: route/backend ecosystem anchor; useful for verifying scanner behavior on framework-heavy Node backend structure and avoiding generic-symbol overranking.
- `nestjs/nest`
  - Why: tests controller/module/provider-style backend organization and whether graplite can summarize layered server shapes cleanly.
- `payloadcms/payload`
  - Why: doubles as a mixed full-stack benchmark where backend and frontend boundaries both matter.

### C# desktop
- `dotnet/wpf`
  - Why: important ecosystem reference for WPF structure and desktop surface expectations, even if not a small app-shaped benchmark.
- `lepoco/wpfui`
  - Why: practical WPF/UI-oriented repo that should pressure-test views, controls, resources, and desktop app structure summaries.
- `CommunityToolkit/MVVM-Samples`
  - Why: explicit MVVM-heavy WPF sample repo with practical `ViewModel` / command / binding patterns, making it a strong benchmark for command/service/viewmodel inference.

### Flutter / hybrid
- `flutter/samples`
  - Why: broad official sample corpus for testing app structure and avoiding regressions beyond `drops`.
- `imaNNeo/fl_chart`
  - Why: useful shared-surface/package-style Flutter benchmark to ensure scanner does not hallucinate app-flow where a library is the dominant shape.
- `drops`
  - Why: current anchor repo and regression guard for the product's strongest practical lane.

## Expected observations — web

### `vercel/next-app-router-playground`
Expected observations:
1. `MAP.md` should clearly recognize an app-router-shaped frontend rather than a generic React tree.
2. Route-segment files such as `page`, `layout`, `loading`, `error`, and `not-found` should be treated as meaningful runtime surfaces, not side noise.
3. Parent layout influence should show up in summaries when nested route segments exist.
4. Shared app-shell/provider-like surfaces should rank above random leaf UI components.
5. `IMPACT.md` should make a `layout` change feel broader than a `page`-only change.
6. `loading` / `error` / `not-found` files should surface as route-visible behavior, not invisible helpers.
7. Output should stay concise even if many route segments exist.

Anti-noise checks:
- generic UI leaf components should not dominate the top architecture story
- utility helpers should not outrank route/layout/app-shell files

### `calcom/cal.com`
Expected observations:
1. `MAP.md` should surface a large web app shape with meaningful route/app-shell/shared-surface groupings.
2. Shared providers, layouts, or shell-like files should appear when they materially influence many pages.
3. Important stateful frontend layers should rank above isolated component files.
4. `IMPACT.md` should show believable fan-out for app-shell or provider-like changes.
5. Changes in route/page surfaces should point to shared shell/state effects when appropriate.
6. Output should remain readable despite repo size.
7. Noise from generic frontend plumbing should be contained.

Anti-noise checks:
- generated/build/config clutter should not take over the summary
- low-level utility files should not outrank app shell and route surfaces without strong evidence

### `payloadcms/payload` (web/admin angle)
Expected observations:
1. `MAP.md` should recognize that this is not a tiny toy frontend, but a layered web/admin surface.
2. Shared admin/provider/context/state surfaces should appear as meaningful building blocks.
3. Route/admin shell summaries should avoid collapsing into an unhelpful generic component inventory.
4. `IMPACT.md` should show believable blast radius for shared provider/context/admin-shell changes.
5. The scanner should separate broadly shared surfaces from one-off leaf views.
6. Mixed full-stack shape should not confuse frontend summaries into becoming backend-only.

Anti-noise checks:
- backend-heavy files should not drown the frontend app-shell view when scanning the full repo
- component spam should not outrank genuinely shared admin/runtime surfaces

## Expected observations — backend

### `fastify/fastify`
Expected observations:
1. `MAP.md` should clearly present a backend/server-oriented shape rather than forcing frontend-style labels.
2. Route/handler/service-like structure should be summarized in a way that still feels useful on a framework-heavy backend repo.
3. Generic framework symbols should not dominate the most important impact stories.
4. `IMPACT.md` should prefer business-relevant or flow-relevant backend files over generic helper noise.
5. Entry/backend runtime surfaces should be visible if the repo exposes them cleanly.
6. Output should remain concise even when the repo contains lots of framework internals.

Anti-noise checks:
- framework internals should not swamp business-meaningful files
- generic types/symbols should stay below route/service/provider relevance

### `nestjs/nest`
Expected observations:
1. `MAP.md` should recognize layered backend structure such as controllers/modules/providers/services when present.
2. Scanner wording should feel natural for a controller/module/provider backend, not only for Express-style route files.
3. `IMPACT.md` should show believable impact from controller/service/provider changes.
4. Shared backend infrastructure should appear when it truly influences many modules.
5. Output should avoid overclaiming semantic precision where only heuristic evidence exists.
6. Important backend files should rank above framework boilerplate.

Anti-noise checks:
- decorator/framework noise should not outrank controllers/services/providers
- docs/examples/test scaffolding should not dominate the main story

### `payloadcms/payload` (backend/full-stack angle)
Expected observations:
1. `MAP.md` should capture that the repo has both frontend and backend value, rather than collapsing into one side only.
2. Backend-relevant surfaces should still be visible alongside admin/web layers.
3. `IMPACT.md` should feel plausible when shared backend logic changes, even in a mixed repo.
4. The scanner should avoid confusing shared full-stack files with purely frontend or purely backend files when evidence is mixed.
5. Important cross-surface/shared logic should rank above random implementation details.

Anti-noise checks:
- mixed repo complexity should not cause unreadable summary sprawl
- scanner should not double-count the same surface in redundant wording

## Expected observations — C# desktop

### `dotnet/wpf`
Expected observations:
1. `MAP.md` should recognize a desktop/WPF-oriented shape, not try to narrate it like a web app.
2. Views, controls, application shell, and binding-related surfaces should appear as meaningful desktop layers.
3. `ARCHITECTURE.mmd` (when generated) should prefer desktop runtime/spine wording over generic backend/frontend wording.
4. Shared desktop infrastructure should appear when it genuinely influences many UI surfaces.
5. Output should stay conservative when the repo is framework/ecosystem-heavy and not a single tidy app.

Anti-noise checks:
- framework/source internals should not be over-sold as if they were app-specific business flows
- desktop-infrastructure detail should not drown the high-level shape

### `lepoco/wpfui`
Expected observations:
1. `MAP.md` should surface a practical WPF/UI app or UI-library shape with strong desktop terminology.
2. Views, controls, resources, and shared desktop shell surfaces should rank sensibly.
3. `IMPACT.md` should treat shared controls/resources/shell files as broader-impact surfaces than leaf demo views.
4. Desktop summaries should feel useful even if the repo has library-ish characteristics.
5. Output should not regress into “nothing interesting found” just because the repo is not a classic full app.

Anti-noise checks:
- isolated control implementation details should not outrank broadly shared desktop shell surfaces
- package/demo scaffolding should not dominate the top story

### `CommunityToolkit/MVVM-Samples`
Expected observations:
1. `MAP.md` should detect a strong MVVM desktop shape: `Views`, `ViewModels`, commands/bindings, and app shell surfaces.
2. XAML command bindings should correlate directionally with likely ViewModel command properties.
3. `IMPACT.md` should show believable interaction paths when a ViewModel or command-related file changes.
4. Shared ViewModel or command patterns should outrank one-off UI leaf files when they influence many samples or screens.
5. Desktop command/service inference should feel notably better here than on a generic WPF repo.
6. Output should stay concise despite sample diversity.

Anti-noise checks:
- sample/demo duplication should not cause repetitive summary spam
- command names should not be treated as meaningful if no supporting viewmodel/binding evidence exists

## Expected observations — Flutter / hybrid

### `flutter/samples`
Expected observations:
1. `MAP.md` should recognize app-oriented Flutter structure where present instead of flattening everything into generic Dart files.
2. Important app entrypoints, screens, features, and shared widgets should appear when scanning app-shaped samples.
3. Shared widget/theme/core surfaces should rank above incidental helper files when they truly fan out.
4. `IMPACT.md` should remain practical and not regress because web/desktop support became richer.
5. Different sample styles should not confuse the scanner into inventing backend/web labels where they do not belong.

Anti-noise checks:
- package/example clutter should not dominate app-shape summaries
- low-level Dart utility files should not outrank real app surfaces without evidence

### `imaNNeo/fl_chart`
Expected observations:
1. `MAP.md` should recognize library/package shape rather than hallucinating a full application architecture.
2. Shared chart/widget surfaces should appear as reusable library surfaces.
3. `IMPACT.md` should treat broadly reused library entry surfaces as meaningful while staying conservative about end-user app impact.
4. Output wording should make sense for a Flutter package, not just a Flutter app.

Anti-noise checks:
- scanner should not pretend there are route/page/app-shell concepts if the repo is mainly a package
- example/demo code should not overshadow the main reusable library surfaces

### `drops`
Expected observations:
1. `MAP.md` should continue to surface the repo as a hybrid app/backend codebase with practical feature-level summaries.
2. Feature pages/tabs, shared widgets, platform/discovery/cloud adapter surfaces, and backend transfer flow should remain visible.
3. `IMPACT.md` should still feel strongest on `drops`; this remains the regression anchor.
4. Web/desktop generalization work must not degrade Flutter-specific clarity here.
5. Shared frontend and backend surfaces should remain concise and believable, not more verbose just because more heuristics exist.

Anti-noise checks:
- no regression into web-biased terminology for Flutter app surfaces
- scanner should not over-expand support files or generated artifacts into the main architecture story

## First benchmark findings

### `web-next`
- First miss observed: app-router repo was detected as frontend, but app-side feature flow and shared surface output were too weak because top-level `app/` and `ui/` roots were not part of scanner candidate roots.
- Fix applied: scanner now includes top-level `app/` and `ui/` in scan/candidate logic, which materially improves module grouping and frontend feature-flow visibility on `web-next`.
- Result after fix: `MAP.md` now exposes `app/*` module groups properly, and `IMPACT.md` now emits app-side feature flow entries instead of staying mostly empty.

### `backend-nest`
- First miss observed: backend structure is detected, but some wording and shared-surface heuristics still leak frontend/state language into a multi-package backend repo.
- Fix applied: restrict frontend shared-surface detection to files rooted in frontend/app-oriented paths, so backend package folders like `packages/*/context/` no longer get mislabeled as frontend state surfaces.
- Result after fix: `backend-nest/IMPACT.md` keeps backend-central risk ranking while frontend/shared-state sections stay empty instead of hallucinating app-side impact.
- Likely next fix area: improve backend-centric wording for package-level architecture summaries and change recipes.

### `desktop-mvvm`
- First miss observed: large sample repo is recognized structurally in the tree, but architecture summary stays too conservative and does not yet elevate desktop/MVVM shape strongly enough.
- Fix applied: add structural desktop fallback impact for repos where import-graph evidence is sparse but `.xaml` / `Views` / `Controls` / shell surfaces are clearly present.
- Result after fix: `IMPACT.md` now emits useful desktop flow entries (for controls, app shells, and key pages) instead of staying empty.
- Second fix applied: architecture summary now recognizes nested desktop sample roots under `samples/` when they expose MVVM or shell markers.
- Result after second fix: `MAP.md` now summarizes the repo as a desktop sample corpus instead of defaulting to “No high-confidence architecture summary detected yet.”
- Likely next fix area: improve nested `Views` → `ViewModels` correlation when sample repos place MVVM layers under multiple app roots.

### `flutter-samples`
- First miss observed: scanner inventories the repo correctly, but architecture summary is too timid for a sample corpus and does not distinguish app-shaped Flutter subprojects from repo-level sample collection shape.
- Fix applied: add structural app-sample fallback impact for Flutter sample corpora, so app-shaped subprojects with `lib/` + platform folders surface in `IMPACT.md` even without a strong repo-wide import graph.
- Result after fix: `IMPACT.md` now highlights sample-level app surfaces such as `form_app/`, `navigation_and_routing/`, `material_3_demo/`, and `testing_app/`.
- Second fix applied: architecture summary now counts and names app-shaped Flutter sample roots at repo level.
- Result after second fix: `MAP.md` now summarizes `flutter-samples` as a Flutter sample corpus with multiple app-shaped roots instead of leaving architecture summary blank.
- Third fix applied: sample-root ranking now prefers representative, app-like, multi-platform roots over incidental or infra-oriented samples.
- Result after third fix: repo summary now highlights stronger anchors such as `material_3_demo`, `testing_app`, `form_app`, and `navigation_and_routing` before weaker incidental samples.
- Likely next fix area: add nested module-group summaries for large sample corpora without flooding the output.

## Lightweight benchmark run checklist

For each benchmark repo run:
1. Run the scanner and save `MAP.md` + `IMPACT.md` into the target repo.
2. Review output against the repo's expected observations in this document.
3. Mark misses under one of four buckets:
   - structure miss
   - ranking miss
   - impact miss
   - noise miss
4. Fix only the highest-leverage miss first.
5. Re-run on `graplite-scan` and `drops` before committing.
6. Commit one thin slice only after the benchmark miss is actually improved.

## Immediate next benchmark authoring tasks

1. Start running the chosen benchmark repos and record first misses
2. Fix issues based on benchmark misses, not intuition alone
3. Expand expected observations if a repo reveals a missing category
