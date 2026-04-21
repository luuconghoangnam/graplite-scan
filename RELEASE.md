# RELEASE.md

## Local release rule for this repo

If a change should affect what users get from:

```bash
npx graplite-scan
```

then **GitHub push alone is not enough**.

You must also:

1. bump npm package version
2. publish the new version to npm

## Why

`npx graplite-scan` resolves from the npm package, not directly from the GitHub repo.

So:
- code changed in GitHub only -> npm users still get the old package
- code changed + npm publish -> `npx graplite-scan` gets the new behavior

## Standard release flow

```bash
cd graplite-scan
git add .
git commit -m "feat/fix: ..."
git push

npm version patch
npm publish --access public
```

## Versioning guide

- `npm version patch` -> small fixes / tweaks / non-breaking improvements
- `npm version minor` -> new features without breaking old usage
- `npm version major` -> breaking changes

## Practical reminder

If you only use local source / `npm link`, publish is optional.

If you want users or other machines running `npx graplite-scan` to receive the update, publish is required.

## Current quality levers to remember

When improving output quality for real repos, prefer these before adding heavier analysis:

1. improve summaries (`MAP.md` / `IMPACT.md`)
2. reduce repo-specific noise
3. add narrow, explainable heuristics

Repo-local noise control now lives in `.graplite.json` via:
- `ignoreDirs`
- `ignorePaths`

## Output budget rule

Prefer shipping value inside:
- `MAP.md`
- `IMPACT.md`

Allow a third file only when it clearly earns its place:
- `ARCHITECTURE.mmd`

Do not casually add new generated output files beyond this budget.
Improve quality inside the existing 2-3 file surface first.
