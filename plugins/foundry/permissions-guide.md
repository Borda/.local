# Permissions Reference

Annotated companion to `.claude-plugin/permissions-allow.json` (allow list) and `.claude-plugin/permissions-deny.json` (deny list) — canonical sources merged into `~/.claude/settings.json` by `/foundry:setup`. Working copy lives at `.claude/permissions-guide.md`, kept in sync by `/audit` (Check 4 drift check) and `/manage add perm` / `/manage remove perm`.

**Destructive git commands explicitly denied** — see Deny List below. Deny rules evaluated before allow rules; matching deny always blocks regardless of any allow entry. Remote-mutating ops (`git push`, `git remote`) not denied — prompt user for approval.

## Deny List — always blocked

| Permission | Description | Why denied |
| --- | --- | --- |
| `Bash(chmod 777:*)` | World-writable permissions | Security risk; overly broad file permissions |
| `Bash(rm -rf:*)` | Recursive force delete | Irreversible; destroys entire directory trees |
| `Bash(ssh:*)` | SSH connections | Prevents agent from opening remote sessions |
| `Bash(sudo:*)` | Privilege escalation | Agents must not gain root access |
| `Bash(git branch -D:*)` | Force-delete local branch | Irreversible; require explicit confirmation |
| `Bash(git branch -d:*)` | Delete local branch | Requires explicit user confirmation |
| `Bash(git tag -d:*)` | Delete local tag | Requires explicit user confirmation |
| `Bash(curl -X DELETE:*)` | HTTP DELETE requests | Destructive external state mutation |
| `Bash(curl --request DELETE:*)` | HTTP DELETE requests (alternate form) | Destructive external state mutation |

## Built-in tool permissions

Pre-authorize `Read`, `Glob`, `Grep`, `Write` on dirs skills and teammates access frequently as part of their own config or runtime state. Without these, agents prompted to confirm accessing own config files or writing output to skill run dirs.

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Read(.claude/*.md)` | Read top-level `.claude/` markdown files | Agents read CLAUDE.md, permissions-guide.md, TEAM_PROTOCOL.md at spawn |
| `Read(.claude/**/*.md)` | Read any nested `.claude/` markdown file | Agents and skills read own agent/skill/rule files; curator reads config files for audit |
| `Read(.claude/logs/**)` | Read log files under `.claude/logs/` | `/calibrate` reads calibrations.jsonl for historical context; `/audit` reads audit-errors.jsonl |
| `Edit(.claude/logs/**)` | Edit log files under `.claude/logs/` | Skills append to calibrations.jsonl and audit-errors.jsonl without Bash redirection |
| `Read(./**)` | Read any file in project root | Teammates read `TEAM_PROTOCOL.md` and agent files at spawn; skills read own SKILL.md files |
| `Glob(./**)` | Glob-match any file in project | `/audit` and `/manage` enumerate agents, skills, hooks, source files without shell `find` |
| `Grep(./**)` | Search content in any project file | `/audit` checks cross-references; `/calibrate` locates skill keyword patterns |
| `Read(/tmp/**)` | Read temporary files under `/tmp/` | `/calibrate` reads checkpoint files for background agent health monitoring; skill temp output files |
| `Write(.plans/**)` | Write plan and blueprint files to `.plans/` | `/brainstorm` writes spec and tree files to `.plans/blueprint/`; `/develop:plan` writes plans to `.plans/active/` |
| `Write(.notes/**)` | Write notes and lessons to `.notes/` | Skills write lessons, diary entries, guides to `.notes/` |
| `Write(.reports/**)` | Write files into `.reports/` skill run dirs | Skills and Codex write timestamped run artifacts (result.jsonl, analysis files) to `.reports/<skill>/` |
| `Write(.temp/**)` | Write prose output files to `.temp/` | Quality-gates long output; research, review, resolve, session, other skills write findings to `.temp/output-<slug>-<date>.md` |
| `Glob(~/.claude/**)` | Glob-match files in home `.claude/` directory | `/foundry:setup link` checks for existing symlinks/files before linking; `/investigate` probes verify agent/skill/config files exist in `~/.claude/`; scoped to `.claude/` only to avoid broad home-dir timeout |
| `Read(~/.claude/**)` | Read files in home `.claude/` directory | `/foundry:setup` reads `~/.claude/settings.json` for merging; `/investigate` probes read `~/.claude/settings.json` during environment checks |

## Web

| Permission | Description | Typical use case |
| --- | --- | --- |
| `WebSearch` | Search web for current information | Fetch current docs, CVE advisories, package release notes, ecosystem news |

## Shell utilities

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(curl:*)` | HTTP requests and file downloads | Hit REST API, download file, fetch raw URLs for link verification |
| `Bash(echo:*)` | Print strings to stdout | Pipe content into another command, emit simple diagnostics |
| `Bash(find:*)` | Locate files by name, type, or modification time | Discover files matching pattern across directory tree |
| `Bash(find .cache*)` | Locate files inside `.cache/` (GitHub API cache) | `/analyse` GitHub API response cache inspection and TTL cleanup |
| `Bash(find .experiments*)` | Locate files inside `.experiments/` skill run dirs | `/optimize` run iteration inspection and TTL cleanup |
| `Bash(find .developments*)` | Locate files inside `.developments/` skill run dirs | `/develop` review-cycle artifact inspection and TTL cleanup |
| `Bash(find .notes*)` | Locate files inside `.notes/` | Notes inspection and TTL cleanup |
| `Bash(find .plans*)` | Locate files inside `.plans/` | Blueprint spec TTL cleanup; plan file inspection |
| `Bash(find .reports*)` | Locate files inside `.reports/` (skill runs) | `/analyse`, `/calibrate`, `/audit`, `/resolve` artifact inspection and TTL cleanup |
| `Bash(find .temp*)` | Locate files inside `.temp/` (prose output) | Quality-gates long output inspection and TTL cleanup |
| `Bash(grep:*)` | Search file content by regex pattern | Filter command output, find usages across codebase |
| `Bash(head:*)` | Read first N lines of file | Inspect file headers, preview log beginnings |
| `Bash(tail:*)` | Read last N lines of file | Follow live logs with `-f`, inspect recent entries |
| `Bash(ls:*)` | List directory contents | Check file existence, inspect directory structure |
| `Bash(wc:*)` | Count lines, words, or bytes | Measure file count, line budget checks |
| `Bash(diff:*)` | Compare two files line-by-line | Confirm patch outcome, spot drift between config files |
| `Bash(cp:*)` | Copy files | `/foundry:setup` uses this to copy rules and settings to `~/.claude/` |
| `Bash(ln:*)` | Create symlinks | `/foundry:setup link` symlinks agents, skills, rules into `~/.claude/` |
| `Bash(mkdir:*)` | Create directories | Ensure target paths exist before writing |
| `Bash(mkdir -p .cache/*)` | Create subdirs inside `.cache/` | `/analyse` creates `.cache/gh/` for GitHub API response caching |
| `Bash(mkdir -p .notes/)` | Create `.notes/` directory | Skills write lessons, diary entries, guides to `.notes/` |
| `Bash(mkdir -p .plans/active/)` | Create `.plans/active/` plan directory | `/develop:plan` creates active plans directory before writing plan files |
| `Bash(mkdir -p .plans/blueprint/)` | Create `.plans/blueprint/` directory | `/brainstorm` creates blueprint directory before writing spec and tree files |
| `Bash(mkdir -p .plans/closed/)` | Create `.plans/closed/` directory | Plans moved here when completed |
| `Bash(mkdir -p .reports/calibrate/*)` | Create `.reports/calibrate/` skill run subdirs | `/calibrate` creates timestamped run dir before spawning pipeline agents |
| `Bash(mkdir -p .reports/resolve/*)` | Create `.reports/resolve/` skill run subdirs | `/resolve` creates run dir for lint+QA gate artifacts |
| `Bash(mkdir -p .reports/audit/*)` | Create `.reports/audit/` skill run subdirs | `/audit` creates timestamped run dir before spawning curator agents |
| `Bash(mkdir -p .reports/review/*)` | Create `.reports/review/` final report subdirs | `/oss:review`, `/develop:review` create per-run dir for consolidated final report |
| `Bash(mkdir -p .temp/review/*)` | Create `.temp/review/` intermediate handover subdirs | `/oss:review`, `/develop:review` create per-run dir for subagent handover files |
| `Bash(mkdir -p .reports/analyse/*)` | Create `.reports/analyse/` skill run subdirs | `/analyse` creates subdirs for thread, ecosystem, health modes |
| `Bash(mkdir -p .experiments/*)` | Create `.experiments/` skill run subdirs | `/optimize` creates run dir for run mode artifacts |
| `Bash(mkdir -p .developments/*)` | Create `.developments/` skill run subdirs | `/develop` creates run dir for review-cycle artifacts |
| `Bash(mkdir -p .temp/)` | Create `.temp/` prose output directory | Skills write quality-gates prose output (research, review, resolve, session) to `.temp/` |
| `Bash(time:*)` | Measure wall-clock execution time | Establish baseline before optimisation pass |
| `Bash(rsync:*)` | Efficient file sync between directories | File mirroring and drift detection; `--dry-run` for preview, no `--delete` ever |
| `Bash(sed:*)` | Stream editor for text transformation | Rewrite paths, strip comments, process file content in pipelines |
| `Bash(awk:*)` | Column-oriented text processing | Extract fields, compute sums, reformat tabular output |
| `Bash(cat:*)` | Concatenate and print file contents | Pipe multi-file content into command; display small files |
| `Bash(sort:*)` | Sort lines of text | Deduplicate sorted output, produce ordered lists for diffing |
| `Bash(uniq:*)` | Filter adjacent duplicate lines | Count occurrences, collapse repeated log lines |
| `Bash(cut:*)` | Extract fixed columns or delimited fields | Pull specific CSV/TSV columns, trim output fields |
| `Bash(tr:*)` | Translate or delete characters | Normalise line endings, uppercase/lowercase transforms |
| `Bash(xargs:*)` | Build and execute commands from stdin | Batch-apply command to list of files or arguments |
| `Bash(eval:*)` | Evaluate a shell string | Sanctioned only for `eval "$(python "${CLAUDE_PLUGIN_ROOT}/bin/state.py" load <ns>)"` cross-block state reload and `eval "$(python health_sentinel.py ...)"` health-sentinel setup — both emit single-quote-escaped assignments, so `eval` is injection-safe (see `bin-authoring-guide.md`) |
| `Bash(tee:*)` | Write stdin to stdout and file simultaneously | Capture command output while still piping downstream |
| `Bash(jq:*)` | Query and transform JSON | Parse API responses, inspect settings.json, filter JSONL logs |
| `Bash(date:*)` | Print or format current date/time | Timestamp log entries, generate dated filenames |
| `Bash(which:*)` | Locate executable on PATH | Verify tool installed before invoking |
| `Bash(comm:*)` | Compare two sorted files line by line | `/audit` Check 1: diff on-disk agent/skill names against MEMORY.md roster |
| `Bash(mktemp:*)` | Create temporary file with unique name | Create temp files for safe content comparison before overwriting |
| `Bash(touch:*)` | Create file or update modification time | `/audit` health monitoring: create per-agent checkpoint files for stall detection |
| `Bash(printf:*)` | Formatted output (supports escape sequences) | Color-coded terminal output in audit and hook scripts |
| `Bash(basename:*)` | Strip directory and suffix from file path | Extract agent/skill names from full file paths in audit and manage scripts |
| `Bash(dirname:*)` | Extract directory component from file path | Compute parent directory of file path in shell pipelines |
| `Bash(node --check:*)` | Validate Node.js script syntax without running | `/audit upgrade` correctness check for hook JS files after applying config changes |
| `Bash(cd:*)` | Directory navigation | Change working directory before running commands in subdirectory (split from compound cd&&cmd patterns) |

## GitHub CLI — primarily read-only

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(gh auth status:*)` | Check GitHub CLI authentication state | Pre-flight check in `/resolve` and any skill requiring `gh` auth |
| `Bash(gh pr view:*)` | Inspect PR metadata, body, review status | Used by `/oss:review` and `/develop:fix` to understand PR under review |
| `Bash(gh pr checkout:*)` | Check out PR branch locally | `/resolve` uses this to enter PR branch state before applying changes |
| `Bash(gh pr diff:*)` | Fetch full diff of PR | `/oss:review` fetches diff for static analysis |
| `Bash(gh pr list:*)` | List open or merged PRs | `/analyse health` and duplicate-detection modes |
| `Bash(gh pr checks:*)` | Read CI check status on PR | Verify CI passed before marking fix complete |
| `Bash(gh repo view:*)` | Fetch repository metadata (name, owner) | `/resolve` detects owner/repo slug for constructing API call paths |
| `Bash(gh run list:*)` | List recent workflow runs | `/cicd-steward` diagnosis: find failing run |
| `Bash(gh run view:*)` | View logs and status of specific CI run | Read error output from failed job |
| `Bash(gh issue view:*)` | Read issue body, labels, comments | `/analyse` and `/develop:fix` read issue before starting work |
| `Bash(gh issue list:*)` | List issues | `/analyse dupes` and health overview |
| `Bash(gh release view:*)` | Inspect existing release's notes and assets | `/release` reads previous release as baseline |
| `Bash(gh release list:*)` | List releases | Find most recent tag to set changelog range |
| `Bash(gh api graphql:*)` | Execute GitHub GraphQL API queries | `/analyse discussion` mode fetches Discussion threads via GraphQL API |
| `Bash(gh api repos/*:*)` | GitHub REST API calls for repo resources | `/analyse`, `/oss:review`, `/resolve` fetch PR reviews, issue data via REST |
| `Bash(gh api search/*)` | GitHub REST API search endpoint | `/resolve` searches for downstream usage of changed APIs |

## Git — read-only

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(git fetch:*)` | Fetch from remote without merging | `/resolve` fetches remote refs to detect fork divergence before merging |
| `Bash(git log:*)` | Browse commit history | `/release` reads commits since last tag; general history inspection |
| `Bash(git shortlog:*)` | Summarise history grouped by author | Contributor stats for release notes |
| `Bash(git describe:*)` | Derive version string from nearest tag | Determine current version in release automation |
| `Bash(git diff:*)` | Show unstaged / staged / commit-to-commit changes | Pre-commit review, diffing patch before applying |
| `Bash(git show:*)` | Inspect specific commit, tag, or blob | Read content of tagged release or specific file at ref |
| `Bash(git rev-list:*)` | Enumerate commits in range | Count distance between refs, find commits to include in release notes |
| `Bash(git rev-parse:*)` | Resolve refs to hashes; get project root | Many skills use `--show-toplevel` to locate project root; MEMORY.md path derivation |
| `Bash(git ls-files:*)` | List tracked files in index | `/audit` and `/manage` enumerate tracked config files |
| `Bash(git branch:*)` | List or inspect local branches | Check active branch; list branches without touching remote |
| `Bash(git tag:*)` | List or inspect local tags | Find latest release tag without pushing |
| `Bash(git status:*)` | Show working-tree state: staged, unstaged, untracked | Pre-commit check, verifying clean state before release |

## Git — local write

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(git merge:*)` | Merge branch into current branch (with or without committing) | `/resolve` merges PR head branch to detect and stage conflict resolution; `--no-commit --no-ff` for inspection, `--ff-only` for clean pointer advance |
| `Bash(git merge-base:*)` | Find common ancestor commit of two branches | `/resolve` uses this to find diverge point between source and target for diff analysis |
| `Bash(git worktree:*)` | Add, list, or remove linked working trees | `/resolve` creates temporary isolated worktree in `/tmp` to run merge without touching user's main working directory |
| `Bash(git commit:*)` | Commit staged changes to local history | `/optimize run` commits each experiment atomically before verifying metric |
| `Bash(git revert:*)` | Revert commit by creating inverse commit | `/optimize run` reverts failed experiments with `git revert HEAD --no-edit` — preserves history, avoids `reset --hard` |
| `Bash(git add:*)` | Stage files for next commit | Stage changes after edit before prompting user to commit |
| `Bash(git checkout:*)` | Switch branches or restore individual files from ref | Switch to feature branch; restore file to HEAD state |
| `Bash(git stash:*)` | Shelve uncommitted changes temporarily | Save work in progress before pulling or switching context |
| `Bash(git apply:*)` | Apply patch file to working tree | Apply generated diff or contributor's patch |

## Python toolchain

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(pytest:*)` | Run test suite via `pytest` entry point | Quick test run during TDD loop in `/develop:feature` and `/develop:fix` |
| `Bash(pre-commit run:*)` | Run pre-commit hooks on staged or all files | Verify formatting and linting before marking task done |
| `Bash(python -m pytest:*)` | Run tests via module interface | Environment-safe alternative when `pytest` binary not on PATH |
| `Bash(python -m doctest:*)` | Execute doctests embedded in module | Validate inline usage examples in docstrings |
| `Bash(python -m pre_commit run:*)` | Run pre-commit via module interface | Alternative invocation inside virtual environments |
| `Bash(python -m cProfile:*)` | Profile script and output timing data | `/optimize` Step 1 baseline measurement |
| `Bash(ruff:*)` | Lint and auto-fix Python source | Run after edits; `check` for diagnostics, `format` for style |
| `Bash(mypy:*)` | Static type-checking | Validate type annotations on module or package |
| `Bash(pip show:*)` | Display metadata for installed package | Check installed version, confirm dependency present |
| `Bash(pip list:*)` | List all installed packages and versions | Dependency audit, environment snapshot |
| `Bash(pip index:*)` | Query PyPI for available versions of package | Check whether newer release available |
| `Bash(pip-audit:*)` | Scan installed packages for known CVEs | Pre-release dependency CVE scan |
| `Bash(uv run pytest:*)` | Run tests via uv-managed pytest | Same as `pytest:*` but uses project's uv-managed environment |
| `Bash(uv run python -m pytest:*)` | Run tests via uv python module interface | Environment-safe pytest invocation through uv |
| `Bash(uv run python -m doctest:*)` | Execute doctests via uv python | Validate inline usage examples via uv-managed interpreter |
| `Bash(uv run python -m cProfile:*)` | Profile script via uv python | `/optimize` baseline measurement through uv-managed interpreter |
| `Bash(uv run ruff:*)` | Lint and auto-fix Python source via uv | Run ruff through uv to ensure project venv rules apply |
| `Bash(uv run mypy:*)` | Static type-checking via uv | Run mypy through uv to use project-pinned version |
| `Bash(uv run pre-commit run:*)` | Run pre-commit hooks via uv | Verify formatting/linting via uv-managed pre-commit |
| `Bash(uv run pip-audit:*)` | Scan packages for CVEs via uv | Pre-release CVE scan through uv-managed environment |
| `Bash(uv pip show:*)` | Display metadata for installed package | Check installed version in uv-managed environment |
| `Bash(uv pip list:*)` | List all packages installed via uv | Dependency audit of uv-managed environment |
| `Bash(uv pip check:*)` | Verify package compatibility in uv environment | Detect dependency conflicts without installing anything |
| `Bash(uv tree:*)` | Show dependency tree for project | Visualize transitive deps; identify why package installed |

## macOS / ecosystem

| Permission | Description | Typical use case |
| --- | --- | --- |
| `Bash(claude:*)` | Invoke Claude Code CLI | SessionStart hook runs `claude auth status` to cache plan info |
| `Bash(node:*)` | Run Node.js scripts | Hooks (`task-log.js`, `statusline.js`) are Node scripts executed by Claude Code |

## WebFetch — allowed domains

| Permission | Description | Typical use case |
| --- | --- | --- |
| `WebFetch(domain:github.com)` | GitHub web pages and repo content | Fetch README, release pages, action marketplace entries |
| `WebFetch(domain:docs.github.com)` | GitHub documentation | GitHub Actions syntax, REST API reference |
| `WebFetch(domain:raw.githubusercontent.com)` | Raw file content from GitHub repos | Read source files, configs, or changelogs directly |
| `WebFetch(domain:pypi.org)` | PyPI package metadata | Release history, classifiers, dependency info |
| `WebFetch(domain:pre-commit.ci)` | pre-commit.ci run status and badge URLs | Verify CI badges before adding to README |
| `WebFetch(domain:claude.ai)` | Claude product pages |
| `WebFetch(domain:claude.com)` | Claude Code landing and docs |
| `WebFetch(domain:anthropic.com)` | Anthropic blog, model cards, policy docs | Research model capabilities, fetch release announcements |
| `WebFetch(domain:docs.anthropic.com)` | Claude Code documentation | Fetch Claude Code docs; redirects to code.claude.com — both domains needed for full coverage |
| `WebFetch(domain:code.claude.com)` | Claude Code documentation | `/audit` fetches hook, agent, skill schemas for validation |
| `WebFetch(domain:arxiv.org)` | ML preprints | `/research:topic` and `research:scientist` fetch papers |
| `WebFetch(domain:developers.openai.com)` | OpenAI developer documentation | Codex CLI docs, API reference |
| `WebFetch(domain:platform.openai.com)` | OpenAI platform and API reference | Model capabilities, pricing, endpoint docs |
| `WebFetch(domain:openai.com)` | OpenAI blog and model release notes | Track new model releases |
| `WebFetch(domain:www.anthropic.com)` | Anthropic main site | Research blog posts, model announcements, policy pages |
| `WebFetch(domain:support.claude.com)` | Anthropic support and help centre | Lookup Claude feature behaviour, plan limits, billing FAQs |
| `WebFetch(domain:hr.linkedin.com)` | LinkedIn profile pages | Release contributor lookup: confirm contributor's real name via profile (see `oss/release/guidelines/writing-rules.md`) |
| `WebFetch(domain:scholar.google.com)` | Google Scholar academic search | `research:scientist` and `/research:topic` find papers and citation counts |

## Skills — pre-approved invocations

Only skills invoked **programmatically** (by another skill, hook, or automated workflow) need `Skill()` entry. Skills invoked directly by user (`/audit`, `/oss:review`, `/develop:feature`, etc.) never need pre-authorization — user's own invocation is approval. Adding all 14 skills to allow list = noise.

| Permission | Description | Why programmatic (not user-invoked) |
| --- | --- | --- |
| `Skill(calibrate)` | Invoke `/calibrate` skill without confirmation | Post-fix quality gate in `/develop` and CLAUDE.md self-improvement loop; runs without user at prompt |

## Top-level `settings.json` keys

Non-permission top-level keys in `settings.json` controlling Claude Code behaviour. Not part of `permissions` block but documented here as canonical `settings.json` reference.

| Key | Value in this project | Description |
| --- | --- | --- |
| `autoCompactThreshold` | `0.7` | Fraction of context capacity triggering automatic compaction. `0.7` = compact at 70% full. Lower = compact earlier (safer for long sessions); higher = use more context before compacting. |
| `ordering` | `"auto"` | Controls tool-call ordering. `"auto"` lets Claude Code choose optimal execution order. Undocumented in public docs as of 2026-04-07 — re-check quarterly; keep as `"auto"` unless release notes document other values. |
| `teammateMode` | `"in-process"` | Controls how agent teammates spawn. `"in-process"` runs teammates in same process (low overhead, shared memory); alternative `"subprocess"` for full isolation. Required alongside `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `env`. |
| `model` | `"opusplan"` | Default model for session. `"opusplan"` = plan-gated Opus alias — activates plan mode for non-trivial tasks. See MEMORY.md for model alias reference. |
| `effortLevel` | `"high"` | Default effort level for all tasks. Equivalent to always running with extended thinking enabled. |
| `autoUpdatesChannel` | `"stable"` | Release channel for auto-updates. `"stable"` = released versions only; `"beta"` includes pre-release builds. |
| `fastModePerSessionOptIn` | `false` | Whether fast mode enabled per-session (opt-in). `false` = normal mode by default; user must explicitly toggle `/fast` to enable. |
