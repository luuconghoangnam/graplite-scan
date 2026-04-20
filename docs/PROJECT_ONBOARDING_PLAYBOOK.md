# Project Onboarding Playbook (Coonie)

Mục tiêu: mỗi khi Gone yêu cầu làm việc trên **một repo/codebase**, Coonie sẽ chạy một “preflight scan” chuẩn để hiểu nhanh dự án + giảm đoán mò.

> Output ưu tiên (nếu repo cho phép ghi file):
> - `PROJECT_FAST_MAP.md`
> - `PROJECT_BLAST_RADIUS.md`
>
> Nếu không muốn commit vào repo: đặt dưới `.coonie/` hoặc `docs/_coonie/` trong repo và add vào `.gitignore`.

---

## 0) Inputs cần từ Gone (1 lần / mỗi repo)
- Đường dẫn repo local (ưu tiên) **hoặc** URL clone.
- Repo private/public? cần auth không?
- Có cho phép tạo/ghi 2 file map vào repo không?

---

## 1) Preflight (luôn chạy)
1. Xác định repo root
   - `git rev-parse --show-toplevel`
   - `git status -sb`
   - `git remote -v`
2. Snapshot cấu trúc
   - `ls -la`
   - `find . -maxdepth 2 -type d` (hoặc `tree -L 3` nếu có)
3. Detect stack/build
   - check: `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `composer.json`, `pubspec.yaml`, …
4. Detect entrypoints
   - heuristic search (ripgrep): `main`, `app`, `server`, `index`, `router`, `bootstrap`, `createServer`, `listen(`, `run(`, …
5. Detect tests & run commands
   - locate `tests/`, `__tests__/`, `*_test.go`, CI configs.

---

## 2) (Nice-to-have) Indexing for better blast radius
### SCIP-first (nếu indexer sẵn có)
- Nếu dự án có thể generate SCIP index locally, ưu tiên vì impact graph chuẩn hơn.
- Nếu indexer chưa cài: Coonie chỉ **gợi ý** cách cài, không tự curl pipe.

### Fallback (không có SCIP)
- Dùng:
  - `ripgrep` (symbol usage)
  - dependency manifests (module graph)
  - import graph heuristics theo ngôn ngữ

---

## 3) Emit 2 files (format ổn định, “AI-friendly”)
### A) PROJECT_FAST_MAP.md
- TL;DR 10 dòng
- Repo layout (top-level folders + responsibility)
- Entrypoints (ranked)
- Runbook: dev/build/test
- Key modules (top N)
- Key files (top N)
- Conventions (errors/logging/config)

### B) PROJECT_BLAST_RADIUS.md
- Module dependency summary
- Top risk nodes (central modules/files)
- “If you change X, check Y” recipes
- (Optional) Diff impact section (khi có git diff range)

---

## 4) Runtime rule (khi Gone nhắn “làm task trong repo X”)
Coonie sẽ:
1) chạy **Preflight**
2) refresh 2 file map (nếu được phép)
3) rồi mới bắt đầu implement/bugfix/PR

---

## 5) Recommended local layout trên server (để tự dùng)
- Clone repos vào: `~/repos/<name>` (ngoài workspace) **hoặc** `/home/gone/projects/<name>`
- Coonie chỉ cần path repo để scan + làm việc.
