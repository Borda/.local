<!-- file: eda.md — selected by composition.md -->

# EDA section contract

Generate the EDA section after the foundation. Use only grounded paths and schema fields.

## Section 3: EDA

Open with a `# %% [markdown]` EDA header.

### Just-in-time configuration

Define only EDA constants, including the grounded target column and sample count:

```python
# %%
SAMPLE_N = 9
TARGET_COL = "<grounded-target-column>"
```

### Dataset overview

- Load the grounded training table or file index.
- Display shape, head, dtypes, missing values, and appropriate descriptive statistics.
- Confirm referenced files exist on a representative sample.
- Assert non-empty data, required columns, sample availability, and readable representative files immediately before using them. Do not wrap overview, sample, or chart cells in `try`/`except` or conditional skips.

### Target distribution

Plot the target distribution. For regression, include robust quantiles/outlier context; for segmentation/detection, summarize annotation prevalence and empty-target frequency.

### Hypothesis validation

Create a markdown hypothesis cell followed by an executable check for each decision-driving question. At minimum consider:

- class/target balance → loss, sampling, or stratification;
- spatial/sequence dimensions → resize, crop, padding, or batching;
- duplicates, leakage, or grouped entities → split strategy;
- missing/corrupt files → dataset guards;
- label noise or empty annotations → augmentation and evaluation behavior.

Every check ends with a printed finding and explicit design implication. Do not infer a conclusion from a plot without recording the observed statistic.

### Modality display

Read `modality-dispatch.md`, select only the grounded branch, and define its visualization helper immediately before first use. Adapt every placeholder column and path from the fact table. Show representative samples and, where applicable, width/height, volume-shape, sequence-length, or point-count distributions.

### EDA lens

Display representative records/samples and print the grounded schema, target properties, missingness, duplicate/leakage checks, and the decisions carried into later stages. In EDA-only mode, retain these implications even though no later sections are generated.
