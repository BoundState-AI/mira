# MIUL V4 Tree Refactor Rollback Plan

## Scope
This rollout introduces:
- Per-drawing extraction packages (`drawing_packages`) persisted in `extraction.json`
- Deterministic DT-skeleton-first MIUL tree assembly
- Hard tree validation gate (`MIUL -> DT`) before export

## Runtime Controls (No Code Revert Needed)
All controls are environment-variable based.

### 1) Immediate Safety Bypass
- `MIUL_V4_ENFORCE_TREE_VALIDATION=0`
- Effect: `/v4/build` no longer blocks export on tree mismatch.
- Use only as a temporary emergency bypass.

### 2) Structural Builder Rollback
- `MIUL_V4_STRUCTURAL_TREE_MODE=legacy`
- Effect: switches from DT-skeleton deterministic builder to legacy pair-row structural mode.

### 3) Package Input Rollback
- `MIUL_V4_USE_DRAWING_PACKAGES=0`
- Effect: ignores `drawing_packages` and uses legacy flat `materials[]` as pair-row source.

## Recommended Rollback Sequence
1. Set `MIUL_V4_ENFORCE_TREE_VALIDATION=0` (restore service continuity first).
2. Set `MIUL_V4_STRUCTURAL_TREE_MODE=legacy` (revert tree assembly strategy).
3. Set `MIUL_V4_USE_DRAWING_PACKAGES=0` (revert extraction-to-build source model).
4. Restart API process.

## Forward-Restore Sequence
1. Set `MIUL_V4_USE_DRAWING_PACKAGES=1`
2. Set `MIUL_V4_STRUCTURAL_TREE_MODE=deterministic`
3. Set `MIUL_V4_ENFORCE_TREE_VALIDATION=1`
4. Restart API process

## Operational Verification
After `/v4/build`, inspect response headers:
- `X-V4-Tree-Mode`
- `X-V4-Package-Mode`
- `X-V4-Tree-Validation-Enforced`
- `X-V4-Tree-Validation-Pass`

If validation is enforced and fails, API returns `422` with structured mismatch details.

## Data Compatibility
- New sessions store `drawing_packages` in `extraction.json`.
- Old sessions without `drawing_packages` auto-derive packages from `materials[]` at load time.

## Known Emergency Fallback
If all else fails, deploy with:
- `MIUL_V4_ENFORCE_TREE_VALIDATION=0`
- `MIUL_V4_STRUCTURAL_TREE_MODE=legacy`
- `MIUL_V4_USE_DRAWING_PACKAGES=0`

This fully disables the new strict path while preserving endpoint compatibility.
