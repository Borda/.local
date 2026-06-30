<!-- file: style-rules.md — consumers: full.md, eda-only.md, inference-only.md -->

Apply ALL of these in the generated script:

1. **Every section `# %% [markdown]` header: explain what, why, and how it advances the goal**: after `## Section Name` write 2–4 sentences covering (a) what this stage does, (b) why this approach was chosen over alternatives, (c) how it contributes to the competition objective (metric, leaderboard, submission quality). Notebook is a public educational resource — write for a reader seeing the competition for the first time. Bare `## Title` headings with no explanation are forbidden.
2. **Shell commands — `# ! cmd` (Python comment)**: write every shell command as `# ! cmd`; valid Python syntax, visible as comment in Jupyter. `%matplotlib inline` verbatim — never `get_ipython().run_line_magic(...)`; if a linter rejects `%` magic, fix the linter config
3. `# ==============================` between logical blocks within a cell (not every line — only at major breaks)
4. `_=` to suppress matplotlib/pandas return values: `_= df["col"].plot(...)`
5. **Every plot: axis labels + grid + legend when multiple series**: always call `plt.xlabel("...")`, `plt.ylabel("...")`, `plt.grid(True)` after any plot; when chart has multiple lines/bars/hues add `plt.legend()` or pass `legend=True`; for seaborn facets use `g.set_axis_labels("x label", "y label")`
6. ALL_CAPS for paths and config constants
7. Version print block right after imports
8. No `if __name__ == '__main__':` guards
9. No argparse, no dataclasses for config
10. **Markdown blank lines — empty lines only**
11. **`display()` over `print()` for pandas objects**: use `display(df.head())`, `display(df.dtypes)`, `display(metrics.dropna(axis=1, how="all").head())`; `print()` for scalars and status strings only: in `# %% [markdown]` cells, blank lines between paragraphs or sections must be actual empty lines (no characters). Never `#` alone (renders as H1 in Kaggle) and never `# ` with trailing space. Pattern: `# Last sentence.` → empty line → `# Next paragraph.`
