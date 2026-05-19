<!-- Loaded by foundry:doc-scribe (sonnet + medium) -->
# Specialized Docstring Patterns (foundry:doc-scribe specialized guidance)

Read this file only when documenting computer-vision / ML tensor functions or writing deprecation migration guides. Skip for routine docstring or README work.

## Computer Vision (CV) / Tensor Docstring Checklist

**CV/ML projects only**: When documenting image/tensor functions — identified by params like `image`, `frame`, `volume`, `tensor`,
`mask`, `feature_map`, or explicit shape annotations like `(B, C, H, W)` — always specify:

- **Shape**: exact dims with named axes (B, C, D, H, W) — e.g., `Shape: (B, C, H, W)`
- **Value range**: [0, 1], [0, 255], or [-1, 1]
- **Channel convention**: channel-first (PyTorch) vs channel-last (NumPy/TensorFlow (TF))
- **Spatial convention**: orientation (RAS/LPS), pixel vs world coordinates
- **dtype**: expected dtype (float32, uint8, int64)
- **Batch handling**: document if function accepts batched/unbatched inputs

## Migration Guide Template (for API deprecation cycles)

When public API deprecated with pyDeprecate, write migration guide
(deprecation lifecycle and pyDeprecate usage policy → `oss:shepherd` agent (requires `oss` plugin)):

- `## Migrating from \`old_function()\` to \`new_function()\`` — title with both names
- **Deprecated in**: version; **Removed in**: version
- `### Before (deprecated)` — minimal before-code example
- `### After` — equivalent after-code example
- `### Argument Mapping` — table: Old | New | Notes (renamed, removed, semantic change)
- Add to both docs and CHANGELOG
