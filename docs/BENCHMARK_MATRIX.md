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
- one additional MVVM-heavy WPF sample repo (to be chosen next)
  - Why: we still need a smaller app-shaped repo with explicit `ViewModel` / `Command` / `Service` conventions.

### Flutter / hybrid
- `flutter/samples`
  - Why: broad official sample corpus for testing app structure and avoiding regressions beyond `drops`.
- `imaNNeo/fl_chart`
  - Why: useful shared-surface/package-style Flutter benchmark to ensure scanner does not hallucinate app-flow where a library is the dominant shape.
- `drops`
  - Why: current anchor repo and regression guard for the product's strongest practical lane.

## Immediate next benchmark authoring tasks

1. For each chosen repo, write 5–10 expected observations
2. Add a lightweight benchmark run checklist
3. Start fixing issues based on benchmark misses, not intuition alone
4. Fill the remaining gap: one additional MVVM-heavy WPF sample repo
