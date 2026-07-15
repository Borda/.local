---
name: kaggle
description: Generate or extend grounded Kaggle competition notebooks as Jupytext `# %%` Python scripts. Use for full training notebooks, EDA-only notebooks, checkpoint-based inference notebooks, or resuming an existing Kaggle script across classification, regression, segmentation, detection, tabular, time-series, point-cloud, and mixed-modality tasks.
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

Inspect in parallel where available:

- `.temp/kaggle-style-distill.md` for local notebook style.
- The requested competition page. Browse the exact page when a URL is supplied; quote only short supporting text and record access failures.
- The resume file and `.experiments/kaggle/*.py` for established local structure.
- `resources/competitors/**/*.{ipynb,py}` for comparable preprocessing, model, augmentation, and submission patterns.
- Local data dictionaries, sample submission files, schemas, and directory listings supplied by the user.

Write a source-backed table in `profile.md`:

| Fact                            | Value | Source                                                                |
| ------------------------------- | ----- | --------------------------------------------------------------------- |
| problem type                    |       | user, fetched URL, local file, or explicit inference from another row |
| input modality                  |       |                                                                       |
| target/output format            |       |                                                                       |
| evaluation metric and direction |       |                                                                       |
| data schema and paths           |       |                                                                       |
| submission schema               |       |                                                                       |

Never invent competition-specific columns, paths, labels, metrics, or submission formats. Ask for missing input modality, metric, and submission format before generation. If the user elects to continue without them, use conspicuous placeholders and list every placeholder as an unresolved limit.

### 03: Select the problem profile

Choose the simplest justified model family:

| Profile                         | Preferred starting point                                            |
| ------------------------------- | ------------------------------------------------------------------- |
| image classification/regression | `timm` backbone; PyTorch Lightning for neural training              |
| 2D segmentation                 | `segmentation_models_pytorch`; MONAI for 3D                         |
| detection                       | `torchvision.models.detection` or a verified installed detector API |
| tabular                         | scikit-learn pipeline or XGBoost; Lightning only for neural models  |
| time series                     | feature baseline plus XGBoost, or a Lightning sequence model        |
| point cloud                     | verified MONAI/PyTorch3D-compatible path with Lightning             |

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

Follow `../_shared/helper-cli-contract.md` and inspect helper `--help` before invocation.

- `tests`: structural/content checks plus Jupytext conversion when available.
- `review`: request conformance, evidence/profile consistency, focused diff, and `git diff --check`.
- `lint`, `format`, and `types`: use applicable project/notebook commands; otherwise provide precise not-applicable reasons because Jupytext magics are not ordinary Python syntax.
- Set `KAGGLE_METADATA` with mode, output path, grounded sources, unresolved placeholders, confidence recovery, and confidence gap closures.
- Write a candidate from `result-template.json`, validate it with the shared validator as `kaggle`, and promote only a validated candidate to `result.json`.

## Fail-Fast Rules

1. Missing or unsafe competition slug => fail before writing.
2. Conflicting modes or missing resume path => fail before writing.
3. Unknown input modality, metric, or submission format without explicit placeholder approval => stop and ask.
4. Competition-specific claim without a cited user, local, or fetched source => fail the grounding gate.
5. Referenced composition, section contract, or style file missing or unreadable => fail before generation.
6. Generated output missing required sections, containing forbidden sections, or failing cell-marker checks => fail.
7. Claimed runtime success without executed evidence => fail review.
8. Missing `profile.md`, gate evidence, or validated result artifact => fail.
9. A required main-path notebook action (data load, sample display, chart, lens, training, inference, or submission validation) guarded by `try`/`except`, `if`/`else`, or a silent skip => fail. Assert its preconditions immediately before the action and let unexpected errors stop the notebook.

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

Review calibration when this workflow changes grounding, mode routing, model selection, or notebook acceptance. Relevant cases cover invented competition schema, missing submission validation, full-mode sections leaking into EDA-only mode, inference notebooks retraining, and unsupported runtime-success claims. If calibration files are intentionally unchanged, explain why in the manage/review artifact.

## Output Contract

Write the notebook under `.experiments/kaggle/` and the canonical run result under `.reports/codex/kaggle/<timestamp>/result.json`. Use the common fields and confidence metadata from `../_shared/quality-gates.md`; `result-template.json` is the minimum payload shape. Report the notebook path, mode, verified checks, unresolved placeholders or runtime limits, and final confidence in chat.
