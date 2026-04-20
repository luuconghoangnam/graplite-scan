# graplite-scan — next steps

## A) Offline upgrades (no new deps)
- [ ] Add env var map extraction (process.env / dotenv keys; Flutter consts?)
- [ ] Add HTTP route map extraction (Fastify: app.get/post/put/delete + route registration)
- [ ] Add websocket/gateway map extraction (Fastify websocket patterns + message/event constants)
- [ ] Add module responsibilities section (heuristic + README/docs summary)
- [ ] Add stable anchors: `path:line` for key symbols and key files.

## B) Graph-based upgrades (needs tooling)
- [ ] Add TS SCIP generation (scip-typescript) + parse scip index → symbol refs/defs.
- [ ] Add callers/callees and impacted symbols from SCIP.
- [ ] Add `--diff <range>`: changed symbols/files → impacted graph.

## References cloned
- scip spec: `references/scip`
- scip-typescript: `references/scip-typescript`
- tree-sitter: `references/tree-sitter`
