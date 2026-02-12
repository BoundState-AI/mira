MIUL v4 Fix Output
==================

Generated file:
- MIUL_V4_fixed.xlsx

What was fixed:
- v4 build now merges reviewed extraction data onto DT JSON skeleton.
- Output now includes full MIUL structure (Index, Parent, NHA, Part Description, etc.) instead of flat raw extraction rows.
- Duplicate explosion from raw sightings is removed by deduping part numbers before DT merge.

Quick result (DMLLV sample):
- Previous v4: 206 rows, 61 duplicate part numbers, NHA mostly empty.
- Fixed v4: 92 rows, 1 expected duplicate (MER07540 header rows), full tree columns.

Regenerate from API code:
- Use endpoint: POST /miul/v4/build
- Required: approved extraction_id
- Optional: project

Regenerate from current workspace (same sample extraction id):
- py -3 -c "import asyncio; from pathlib import Path; from mira.api.routers.miul import build_miul_v4; r=asyncio.run(build_miul_v4(extraction_id='b2e930a5-6cf1-4a8a-a059-f96edbb9c998', project='DMLLV')); Path('miul_codex/MIUL_V4_fixed.xlsx').write_bytes(r.body)"
