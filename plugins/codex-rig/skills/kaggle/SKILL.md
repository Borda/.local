---
name: kaggle
description: "Build/extend grounded Kaggle Jupytext notebooks for training, EDA, inference, or resume workflows, grounding schema and submission format through the authenticated kaggle CLI."
---

# Kaggle

Build a public-readable Kaggle notebook with an evidence-backed problem profile, visual EDA, stage-level sanity checks, reproducible training, inference, and submission validation. Write notebook scripts only; use `develop` for packages or production modules and `research` for literature surveys.

## Input Schema

```json
{
  "competition": "required output slug",
  "context": "competition URL, pasted description, local dataset metadata, or existing notebook path",
  "problem_type": "optional classification|regression|segmentation|detection|tabular|time-series|point-cloud|mixed",
  "mode": "full|eda-only|inference-only",
  "offline_setup": "optional boolean",
  "resume": "optional existing Jupytext .py path",
  "keep": "optional user-specified content that must survive regeneration",
  "done_when": "the grounded notebook is written, structurally verified, and recorded in a validated result artifact"
}
```

Default `mode` to `full`. Resolve mode behavior and output paths only through `references/composition.md`.

## Workflow

### 01: Create the run and normalize input

Create `.reports/codex/kaggle/<timestamp>/` and keep the active plan current. Record normalized inputs in `profile.md`.

- Require a filesystem-safe lowercase slug containing only letters, digits, and hyphens.
- Reject conflicting or unsupported mode inputs.
- Require `resume` to exist, be readable, and use Jupytext cell markers.
- Treat unknown options as blocking until the user confirms whether to ignore them.
- Create `.experiments/kaggle/` only after inputs pass validation.

### 02: Gather evidence before choosing an approach

Prefer the authenticated `kaggle` CLI over the competition page for anything the CLI can read. Competition pages are login-walled and often return partial content; the CLI reads real file names, sizes, and the actual sample submission.

Apply the networked CLI approval contract in `../../shared/native-skill-contract.md` to every `kaggle` invocation, including probes, help, listings, and downloads: execute the complete owning command with external network approval from its first attempt. In a Codex exec call, set `sandbox_permissions="require_escalated"` with a narrow Kaggle-read/download justification; never enable persistent workspace network access or approve only a nested executable. The user's Kaggle task authorizes requesting the runtime permission, not bypassing its prompt. Kaggle CLI installation and authentication are user-owned prerequisites; never run an installer or authentication setup from this workflow.

**CLI probe.** `command -v kaggle`, then `kaggle competitions list -p 1` — succeeds only with valid credentials, and needs no rules acceptance, so it separates an auth failure from a rules failure. Record the resulting state in `profile.md` as `ready`, `unauthorized`, or `absent`. Absence is never fatal: fall back to the page and user-supplied facts, and record the degraded grounding as a residual limit.

- `absent` — do not install it. Ask the user to install and authenticate the Kaggle CLI, then rerun the workflow; use page or user-supplied evidence only when the requested mode can tolerate degraded grounding.
- `unauthorized` — instruct the user to create a token at `https://www.kaggle.com/settings` (API → Create New Token), place it at `~/.kaggle/kaggle.json` with `chmod 600`, or export `KAGGLE_USERNAME`/`KAGGLE_KEY`. Never fabricate or request a pasted token.

**Credential secrecy — hard constraint.** The token value never enters this run's context, any artifact, or any delegated agent's prompt. Forbidden regardless of who asks: reading `~/.kaggle/kaggle.json` by any tool, `cat`/`head`/`grep`/`jq` on it, `kaggle config view`, `env | grep KAGGLE`, echoing `$KAGGLE_KEY`/`$KAGGLE_API_TOKEN`, quoting a pasted token back, or writing any of it into a notebook cell, `profile.md`, gate log, or result artifact. The `kaggle` binary reads credentials from the environment on its own — the workflow needs the CLI to work, never the secret's value. Verify auth by exit code alone (`kaggle competitions list -p 1 >/dev/null 2>&1`), never by inspecting the file. A token pasted into chat is compromised: do not repeat it, and tell the user to rotate it.

**CLI queries.** Competition slug is positional; `-v` means CSV output, not verbose. Read `kaggle competitions --help` or `kaggle datasets --help` for anything beyond these — the flag surface shifts between CLI releases, so never invent one.

- `kaggle competitions files <slug> -v --page-size 200` — file names and sizes.
- `kaggle competitions leaderboard <slug> -s -v` — achievable score range for the metric.
- `kaggle competitions download <slug> -f sample_submission.csv -p .experiments/kaggle/data/<slug>/ -q` — the real submission header. Single-file downloads may arrive zipped; unzip before reading.
- `kaggle datasets list -s "<term>" -v` / `kaggle datasets files <owner>/<name> -v` / `kaggle datasets download <owner>/<name> --unzip` — only when the competition permits external data.

File listing works without joining the competition; rules acceptance gates downloads. On a `403` or any "accept the rules" error, direct the user to `https://www.kaggle.com/competitions/<slug>/rules` — the CLI cannot accept them — and treat the affected facts as ungrounded until confirmed. A `404` instead means a malformed slug: `kaggle competitions list -v` returns full URLs in `ref`, so pass only the last path segment, and verify with `kaggle competitions list -s "<term>" -v`.

Never download the full competition archive unprompted — list files with sizes first and ask. Local downloads do not change notebook path constants; `PATH_DATASET` stays the Kaggle-runtime path unless the user states the notebook runs locally.

Inspect in parallel where available:

- `.temp/kaggle-style-distill.md` for local notebook style.
- The requested competition page for problem narrative and metric definition — the parts the CLI does not expose. Browse the exact page when a URL is supplied; quote only short supporting text and record access failures.
- The resume file and `.experiments/kaggle/*.py` for established local structure.
- `resources/competitors/**/*.{ipynb,py}` for comparable preprocessing, model, augmentation, and submission patterns.
- Local data dictionaries, sample submission files, schemas, and directory listings supplied by the user.

Write a source-backed table in `profile.md`:

| Fact | Value | Source |
| --- | --- | --- |
| problem type | — | user, fetched URL, local file, or explicit inference from another row |
| input modality | — | — |
| target/output format | — | — |
| evaluation metric and direction | — | — |
| data schema and paths | — | — |
| submission schema | — | — |

Cite `kaggle competitions files`, `kaggle competitions download`, or `kaggle datasets files` by name as the source when the CLI supplied a row. CLI evidence outranks the fetched page for file names, data schema, and submission format; the page stays authoritative for problem narrative and metric definition.

Never invent competition-specific columns, paths, labels, metrics, or submission formats. Ask for missing input modality, metric, and submission format before generation. If the user elects to continue without them, use conspicuous placeholders and list every placeholder as an unresolved limit.

### 03: Select the problem profile

Choose the simplest justified model family:

| Profile | Preferred starting point |
| --- | --- |
| image classification/regression | `timm` backbone; PyTorch Lightning for neural training |
| 2D segmentation | `segmentation_models_pytorch`; MONAI for 3D |
| detection | `torchvision.models.detection` or a verified installed detector API |
| tabular | scikit-learn pipeline or XGBoost; Lightning only for neural models |
| time series | feature baseline plus XGBoost, or a Lightning sequence model |
| point cloud | verified MONAI/PyTorch3D-compatible path with Lightning |

Use PyTorch Lightning whenever a neural training loop is needed. Pure scikit-learn or XGBoost pipelines do not need Lightning. Record the selected model, alternatives rejected, metric direction, and package/API evidence in `profile.md`. Verify current third-party APIs from installed package metadata or current primary documentation; do not rely on reference snippets when versions differ.

### 04: Resolve the composition

Read `references/composition.md` completely and execute the selected row.

Keep ownership strict: composition owns mode routing; section contracts own notebook behavior; style rules own presentation.

### 05: Generate or resume the notebook

Write the notebook directly; do not delegate generation to an external runner or assume a Foundry agent exists.

- Preserve all requested `keep` content and unrelated resume-file content.
- Use `# %%` and `# %% [markdown]` cell boundaries.

Do not distill helpers into a package during the notebook run. Offer package extraction only as a separate `develop` task after the baseline notebook passes.

### 06: Verify the generated artifact

Record verification in `profile.md` and gate logs.

1. Confirm the output exists, is non-empty, starts with `# %% [markdown]`, and contains only recognized cell markers.
2. Confirm all sections required by the selected mode are present and prohibited sections are absent.
3. Scan for unresolved angle-bracket placeholders, `TODO`, guessed schema, stale external-runner vocabulary, bare shell lines, deprecated `torch.cuda.amp`, and duplicate global helper blocks.
4. Confirm every grounded field used in code matches `profile.md` and the sample submission/schema evidence.
5. If `jupytext` is installed, convert to a temporary notebook and fail on conversion errors. Otherwise record the missing optional conversion check as a residual limit.
6. Run executable smoke checks that do not require unavailable Kaggle data. Never claim model training, inference, or submission execution unless it actually ran.
7. Review the focused diff and run `git diff --check` without modifying unrelated changes.

### 07: Run gates and publish the result artifact

Follow `../../shared/helper-cli-contract.md` and inspect helper `--help` before invocation.

- `tests`: structural/content checks plus Jupytext conversion when available.
- `review`: request conformance, evidence/profile consistency, focused diff, and `git diff --check`.
- `lint`, `format`, and `types`: use applicable project/notebook commands; otherwise provide precise not-applicable reasons because Jupytext magics are not ordinary Python syntax.
- Set `KAGGLE_METADATA` with mode, output path, grounded sources, unresolved placeholders, confidence recovery, and confidence gap closures.
- Write a candidate from `result-template.json`, validate it with the shared validator as `kaggle`, and promote only a validated candidate to `result.json`.

## Fail-Fast Rules

1. Missing or unsafe competition slug => fail before writing.
2. Conflicting modes or missing resume path => fail before writing.
3. Unknown input modality, metric, or submission format without explicit placeholder approval => stop and ask.
4. Competition-specific claim without a cited user, local, fetched, or `kaggle` CLI source => fail the grounding gate.
5. Referenced composition, section contract, or style file missing or unreadable => fail before generation.
6. Generated output missing required sections, containing forbidden sections, or failing cell-marker checks => fail.
7. Claimed runtime success without executed evidence => fail review.
8. Missing `profile.md`, gate evidence, or validated result artifact => fail.
9. Full competition or dataset archive downloaded without listing file sizes and asking first => fail.
10. A required main-path notebook action (data load, sample display, chart, lens, training, inference, or submission validation) guarded by `try`/`except`, `if`/`else`, or a silent skip => fail. Assert its preconditions immediately before the action and let unexpected errors stop the notebook.

## Quality Gates

Required:

- `tests`: composition integrity, notebook structure, mode sections, placeholder disclosure, and optional Jupytext conversion.
- `review`: grounding table, output/schema consistency, request constraints, focused diff, and clean `git diff --check`.
- `artifact`: `profile.md`, gate logs, and result JSON pass the shared `kaggle` validator.

Conditional:

- `lint`, `format`, and `types`: run when compatible notebook-aware commands exist; otherwise record explicit not-applicable reasons.
- Runtime data/model checks: required only when the requested data and dependencies are locally available.

Pass only when all applicable gates pass, no grounded fields are silently guessed, and confidence is at least `0.85` with objective evidence and residual limits recorded.

## Calibration Hooks

Review calibration when this workflow changes grounding, mode routing, model selection, network approval, or notebook acceptance. Relevant cases cover invented competition schema, missing submission validation, full-mode sections leaking into EDA-only mode, inference notebooks retraining, unsupported runtime-success claims, and networked CLI owning-command approval. If calibration files are intentionally unchanged, explain why in the manage/review artifact.

## Output Contract

Write the notebook under `.experiments/kaggle/` and the canonical run result under `.reports/codex/kaggle/<timestamp>/result.json`. Use the common fields and confidence metadata from `../../shared/quality-gates.md`; `result-template.json` is the minimum payload shape. Report the notebook path, mode, verified checks, unresolved placeholders or runtime limits, and final confidence in chat.
