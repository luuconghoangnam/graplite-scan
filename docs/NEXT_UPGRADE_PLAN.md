# Next Upgrade Plan for `graplite-scan`

## Selected direction

Borrow selectively from `code-review-graph`, with this priority order:

1. diff precision
2. explainable impact reasons
3. minimal internal graph schema
4. lightweight visualization
5. cache/incremental reuse

## Why this order

This keeps `graplite-scan` aligned with its current strengths:
- practical
- local-first
- AI-friendly markdown outputs
- minimal commands

It avoids premature expansion into a large platform product.

## Immediate next thin slice

### Target
Add a **portable visual summary output** without rewriting the scanner.

### Recommended first artifact
Generate one of these from existing scan data:
- `ARCHITECTURE.mmd` (Mermaid)
- `BLAST_RADIUS.mmd` (Mermaid)
- `graph.json`

Recommended first pick: `ARCHITECTURE.mmd`

Why:
- easy to inspect in GitHub/Markdown tooling
- portable
- low maintenance
- good bridge between text-only and full graph UI

## Constraints

- no big rewrite
- no external service dependency
- no premature MCP/platform sprawl
- outputs must stay understandable by both humans and AI
- keep generated output budget tight: prefer 2 files, max 3 files

## Done means

For the first visualization slice, success should look like:
- generated from current scan data
- highlights entrypoints, major groups, and key links
- works on repos like `drops`
- remains concise enough to be useful
