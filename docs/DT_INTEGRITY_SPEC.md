# DT Source of Truth + Soft-Delete Architecture

## The Problem

The Design Tree (DT) is the source of truth for BOM structure. The MIUL is a *materialized view* of the DT enriched with material data. Users need to be able to "remove" rows from their MIUL (garbled data, non-parts, mistakes), but that action **must never destroy DT data**.

Hard-deleting a MIUL row creates three catastrophic failure modes:
1. **BOM gap** — Real part vanishes from the compliance document. NASA auditor asks "where's MER07576-001?" and it's gone.
2. **Orphan on re-extract** — Next pipeline run finds the part again, creates it fresh with no history, no HITL resolutions, no enrichment.
3. **Silent data loss** — No audit trail of what was removed, when, why, or by whom. Unacceptable for safety-critical systems.

## The Architecture: Three-Layer Model

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: DT (Design Tree)                          │
│  ─────────────────────────                          │
│  IMMUTABLE source of truth.                         │
│  Extracted from drawings. Never deleted by users.   │
│  Only modified by re-extraction or admin override.  │
│                                                     │
│  Part exists in DT = part exists in the world.      │
└───────────────────────┬─────────────────────────────┘
                        │ JOIN
┌───────────────────────▼─────────────────────────────┐
│  Layer 2: MIUL Rows (miul_rows table)               │
│  ────────────────────────────────                   │
│  Materialized from DT + drawing extraction.         │
│  Enriched by std_parts_lookup + HITL resolutions.   │
│  SOFT-DELETE only. Never hard-deleted.              │
│                                                     │
│  row_status: active | suppressed | excluded | error │
└───────────────────────┬─────────────────────────────┘
                        │ FILTER (WHERE status='active')
┌───────────────────────▼─────────────────────────────┐
│  Layer 3: MIUL View (what user sees / XLSX export)  │
│  ──────────────────────────────────────────         │
│  Filtered view of Layer 2.                          │
│  Only shows active rows by default.                 │
│  Toggle to show suppressed/excluded for review.     │
│  Export to XLSX only includes active rows.           │
└─────────────────────────────────────────────────────┘
```

## Row Status Model

Every MIUL row has a `row_status` field. This is the ONLY mechanism for "deleting" rows.

| Status | Meaning | Visible in MIUL? | In XLSX export? | Recoverable? |
|--------|---------|-------------------|-----------------|--------------|
| `active` | Normal row, part of MIUL | Yes | Yes | N/A |
| `suppressed` | User hid it (garbled, duplicate, etc.) | No (toggle to show) | No | Yes — one click |
| `excluded` | Intentionally excluded with rationale | No (toggle to show) | No* | Yes — one click |
| `error` | System flagged as extraction error | Shown in error panel | No | Yes — re-extract |

*`excluded` rows MAY appear in a separate "Excluded Items" appendix in the XLSX for audit completeness.

### Status Transitions

```
                    ┌──────────────┐
        extract ──▶ │   active     │ ◀── restore
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │suppressed│ │ excluded │ │  error   │
        └──────────┘ └──────────┘ └──────────┘
              │            │            │
              └────────────┼────────────┘
                           │
                     restore (all go back to active)
```

**There is no transition to "deleted." The row always exists.**

## Postgres Schema

### Core table: `miul_rows`

```sql
CREATE TABLE miul_rows (
    id              SERIAL PRIMARY KEY,
    miul_id         TEXT NOT NULL,              -- "MER07540"
    row_index       INTEGER NOT NULL,           -- Position in MIUL
    
    -- DT linkage (IMMUTABLE after creation)
    dt_node_id      INTEGER REFERENCES dt_nodes(id),  -- FK to DT
    part_number     TEXT NOT NULL,
    
    -- Extracted / enriched data (MUTABLE via HITL + enrichment)
    part_description TEXT,
    nomenclature    TEXT,
    nha             TEXT,
    designation     TEXT,
    material_spec   TEXT,
    process_spec    TEXT,
    -- ... all other MIUL columns ...
    
    -- Row lifecycle
    row_status      TEXT NOT NULL DEFAULT 'active'
                    CHECK (row_status IN ('active', 'suppressed', 'excluded', 'error')),
    status_reason   TEXT,                      -- Why it was suppressed/excluded
    status_changed_by TEXT,                    -- Who changed it
    status_changed_at TIMESTAMPTZ,
    
    -- Source tracking
    source_type     TEXT NOT NULL DEFAULT 'extraction',  -- extraction | manual | enrichment
    extraction_run_id TEXT,                    -- Which pipeline run created this
    
    -- Versioning
    version         INTEGER NOT NULL DEFAULT 1,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(miul_id, row_index)
);

CREATE INDEX idx_miul_rows_status ON miul_rows(miul_id, row_status);
CREATE INDEX idx_miul_rows_dt ON miul_rows(dt_node_id);
CREATE INDEX idx_miul_rows_pn ON miul_rows(miul_id, part_number);
```

### Audit table: `miul_row_history`

Every change to every row. Complete provenance.

```sql
CREATE TABLE miul_row_history (
    id              SERIAL PRIMARY KEY,
    miul_row_id     INTEGER NOT NULL REFERENCES miul_rows(id),
    miul_id         TEXT NOT NULL,
    row_index       INTEGER NOT NULL,
    part_number     TEXT NOT NULL,
    
    -- What changed
    action          TEXT NOT NULL,              -- "status_change", "field_edit", "enrichment", "hitl_resolve"
    field_name      TEXT,                       -- Which field changed (NULL for status changes)
    value_before    TEXT,
    value_after     TEXT,
    
    -- Who / why
    changed_by      TEXT NOT NULL DEFAULT 'system',
    change_reason   TEXT,                      -- Free text: "Garbled extraction, suppressed pending re-extract"
    change_source   TEXT,                      -- "user", "hitl_engine", "enrichment", "re_extraction"
    
    -- Version tracking
    version_before  INTEGER,
    version_after   INTEGER,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_history_row ON miul_row_history(miul_row_id);
CREATE INDEX idx_history_miul ON miul_row_history(miul_id);
```

### DT nodes table (reference — may already exist)

```sql
CREATE TABLE dt_nodes (
    id              SERIAL PRIMARY KEY,
    miul_id         TEXT NOT NULL,              -- Which DT this belongs to
    part_number     TEXT NOT NULL,
    parent_part_number TEXT,                    -- Parent in BOM tree
    indent_level    INTEGER NOT NULL DEFAULT 0,
    
    -- DT source data (from DT JSON extraction)
    description     TEXT,
    nha             TEXT,
    find_number     TEXT,
    quantity        TEXT,
    
    -- Immutability flag
    is_locked       BOOLEAN NOT NULL DEFAULT TRUE,  -- Users cannot modify DT nodes
    lock_reason     TEXT DEFAULT 'Extracted from design tree. Modify via re-extraction only.',
    
    -- Source
    source_document TEXT,                      -- "MER07540 DT.json"
    extraction_run_id TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(miul_id, part_number)
);

CREATE INDEX idx_dt_nodes_miul ON dt_nodes(miul_id);
CREATE INDEX idx_dt_nodes_parent ON dt_nodes(parent_part_number);
```

## API Endpoints

### Suppress a row (user "deletes" it)

```python
@router.post("/miul/{miul_id}/rows/{row_id}/suppress")
async def suppress_row(
    miul_id: str, 
    row_id: int,
    reason: str,              # REQUIRED — must say why
    user: str = "system"
):
    """
    Soft-delete a MIUL row. Row still exists, just hidden from default view.
    
    The DT node is NEVER touched. Only the MIUL row status changes.
    """
    cur = db_conn.cursor()
    
    # Get current state for history
    cur.execute("SELECT * FROM miul_rows WHERE id = %s AND miul_id = %s", (row_id, miul_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Row not found")
    
    old_status = row['row_status']
    
    # Update status
    cur.execute("""
        UPDATE miul_rows 
        SET row_status = 'suppressed',
            status_reason = %s,
            status_changed_by = %s,
            status_changed_at = NOW(),
            version = version + 1,
            updated_at = NOW()
        WHERE id = %s
        RETURNING version
    """, (reason, user, row_id))
    
    new_version = cur.fetchone()['version']
    
    # Write history
    cur.execute("""
        INSERT INTO miul_row_history 
        (miul_row_id, miul_id, row_index, part_number, action,
         field_name, value_before, value_after,
         changed_by, change_reason, change_source,
         version_before, version_after)
        VALUES (%s, %s, %s, %s, 'status_change',
                'row_status', %s, 'suppressed',
                %s, %s, 'user',
                %s, %s)
    """, (row_id, miul_id, row['row_index'], row['part_number'],
          old_status, user, reason,
          new_version - 1, new_version))
    
    db_conn.commit()
    
    return {
        "status": "suppressed",
        "row_id": row_id,
        "part_number": row['part_number'],
        "message": f"Row suppressed. DT entry preserved. Restore anytime.",
        "dt_node_id": row['dt_node_id'],  # Show them the DT link still exists
    }
```

### Restore a suppressed row

```python
@router.post("/miul/{miul_id}/rows/{row_id}/restore")
async def restore_row(
    miul_id: str,
    row_id: int,
    user: str = "system"
):
    """Restore a suppressed/excluded row back to active."""
    cur = db_conn.cursor()
    
    cur.execute("SELECT * FROM miul_rows WHERE id = %s AND miul_id = %s", (row_id, miul_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Row not found")
    if row['row_status'] == 'active':
        return {"status": "already_active", "row_id": row_id}
    
    old_status = row['row_status']
    
    cur.execute("""
        UPDATE miul_rows 
        SET row_status = 'active',
            status_reason = NULL,
            status_changed_by = %s,
            status_changed_at = NOW(),
            version = version + 1,
            updated_at = NOW()
        WHERE id = %s
    """, (user, row_id))
    
    # Write history
    cur.execute("""
        INSERT INTO miul_row_history 
        (miul_row_id, miul_id, row_index, part_number, action,
         field_name, value_before, value_after,
         changed_by, change_source, version_before, version_after)
        VALUES (%s, %s, %s, %s, 'status_change',
                'row_status', %s, 'active',
                %s, 'user', %s, %s)
    """, (row_id, miul_id, row['row_index'], row['part_number'],
          old_status, user, row['version'], row['version'] + 1))
    
    db_conn.commit()
    
    return {"status": "restored", "row_id": row_id, "part_number": row['part_number']}
```

### Exclude a row (with rationale — for non-parts like lubricant notes)

```python
@router.post("/miul/{miul_id}/rows/{row_id}/exclude")
async def exclude_row(
    miul_id: str,
    row_id: int,
    reason: str,              # REQUIRED
    user: str = "system"
):
    """
    Exclude a row from the MIUL with documented rationale.
    
    Use for items that are intentionally NOT in the MIUL:
    - Drawing note references (5., 6., 9.) that aren't real parts
    - Standard parts tracked elsewhere
    - Items outside the material evaluation scope
    
    Excluded rows appear in an audit appendix but not the main MIUL.
    """
    # Same pattern as suppress, but status = 'excluded'
    # ... (identical logic, different status value)
```

### Get MIUL with status filtering

```python
@router.get("/miul/{miul_id}/rows")
async def get_miul_rows(
    miul_id: str,
    include_suppressed: bool = False,
    include_excluded: bool = False,
    include_errors: bool = False,
):
    """
    Get MIUL rows with optional visibility of non-active rows.
    Default: only active rows (what goes in the XLSX).
    """
    statuses = ['active']
    if include_suppressed:
        statuses.append('suppressed')
    if include_excluded:
        statuses.append('excluded')
    if include_errors:
        statuses.append('error')
    
    placeholders = ','.join(['%s'] * len(statuses))
    cur = db_conn.cursor()
    cur.execute(f"""
        SELECT mr.*, dn.parent_part_number, dn.indent_level
        FROM miul_rows mr
        LEFT JOIN dt_nodes dn ON mr.dt_node_id = dn.id
        WHERE mr.miul_id = %s AND mr.row_status IN ({placeholders})
        ORDER BY mr.row_index
    """, [miul_id] + statuses)
    
    return cur.fetchall()
```

### DT integrity check (run periodically or on-demand)

```python
@router.get("/miul/{miul_id}/integrity")
async def check_dt_integrity(miul_id: str):
    """
    Verify every DT node has a corresponding MIUL row.
    Flags gaps where DT parts are missing from the MIUL.
    """
    cur = db_conn.cursor()
    
    # Find DT nodes with no MIUL row at all
    cur.execute("""
        SELECT dn.part_number, dn.description
        FROM dt_nodes dn
        LEFT JOIN miul_rows mr ON dn.id = mr.dt_node_id AND mr.miul_id = %s
        WHERE dn.miul_id = %s AND mr.id IS NULL
    """, (miul_id, miul_id))
    missing = cur.fetchall()
    
    # Find DT nodes where MIUL row is suppressed/excluded
    cur.execute("""
        SELECT dn.part_number, dn.description, mr.row_status, mr.status_reason
        FROM dt_nodes dn
        JOIN miul_rows mr ON dn.id = mr.dt_node_id AND mr.miul_id = %s
        WHERE dn.miul_id = %s AND mr.row_status != 'active'
    """, (miul_id, miul_id))
    non_active = cur.fetchall()
    
    return {
        "miul_id": miul_id,
        "dt_node_count": _count_dt_nodes(cur, miul_id),
        "active_miul_rows": _count_active_rows(cur, miul_id),
        "missing_from_miul": [{"part_number": r[0], "description": r[1]} for r in missing],
        "suppressed_or_excluded": [
            {"part_number": r[0], "description": r[1], "status": r[2], "reason": r[3]} 
            for r in non_active
        ],
        "integrity_ok": len(missing) == 0,
        "message": (
            "All DT nodes accounted for." if len(missing) == 0 
            else f"WARNING: {len(missing)} DT nodes have no MIUL row."
        )
    }
```

## Re-extraction Behavior

When the pipeline re-extracts (new drawings uploaded, parser fixed, etc.):

```python
def re_extract_miul(miul_id: str, new_rows: list, db_conn):
    """
    Re-extraction MERGES with existing data, never replaces.
    
    Rules:
    1. New parts (in DT, not in miul_rows) → INSERT as 'active'
    2. Existing active rows → UPDATE extracted fields, preserve HITL edits
    3. Suppressed/excluded rows → DO NOT auto-restore (respect human decision)
    4. Error rows → Re-extract and set to 'active' if data now clean
    5. Enrichment data → Preserve (never overwrite std_parts enrichment with raw extraction)
    """
    cur = db_conn.cursor()
    
    for new_row in new_rows:
        pn = new_row['Part Number']
        
        # Check if row already exists
        cur.execute("""
            SELECT id, row_status, designation, material_spec, version
            FROM miul_rows 
            WHERE miul_id = %s AND part_number = %s
        """, (miul_id, pn))
        existing = cur.fetchone()
        
        if existing is None:
            # New part — insert
            _insert_miul_row(cur, miul_id, new_row, source='re_extraction')
            continue
        
        row_id = existing['id']
        status = existing['row_status']
        
        if status in ('suppressed', 'excluded'):
            # DO NOT auto-restore. Log that re-extraction found it.
            cur.execute("""
                INSERT INTO miul_row_history 
                (miul_row_id, miul_id, row_index, part_number, action,
                 change_reason, change_source)
                VALUES (%s, %s, %s, %s, 'reextract_skipped',
                        'Row is %s. Re-extraction found data but did not restore.',
                        're_extraction')
            """, (row_id, miul_id, new_row.get('Index', 0), pn, status))
            continue
        
        if status == 'error':
            # Error rows get re-extracted — this is the fix path
            _update_miul_row(cur, row_id, new_row, set_active=True)
            continue
        
        # Active row — merge carefully
        # Rule: NEVER overwrite enriched data with raw extraction
        if existing['designation'] and not new_row.get('Designation'):
            # Existing has material (from enrichment/HITL), new extraction doesn't
            # Keep the enriched value
            new_row['Designation'] = existing['designation']
        
        if existing['material_spec'] and not new_row.get('Material Specification'):
            new_row['Material Specification'] = existing['material_spec']
        
        _update_miul_row(cur, row_id, new_row, set_active=False)
    
    db_conn.commit()
```

## UI Implications

### Default MIUL view
- Shows only `active` rows
- Row count badge: "87 active / 94 total"
- Toggle: "Show suppressed (5)" / "Show excluded (2)"

### Suppress action
- User right-clicks row → "Suppress this row"
- **Required**: Reason dropdown + optional free text
  - "Garbled extraction"
  - "Not a real part (drawing note)"
  - "Duplicate entry"
  - "Out of scope"
  - "Other: ___"
- Row fades out with strikethrough, then disappears
- Toast: "MER07576-001 suppressed. DT entry preserved. [Undo]"

### Integrity indicator
- Green check: "All DT parts accounted for"
- Yellow warning: "3 parts suppressed/excluded"
- Red alert: "2 DT parts missing from MIUL" (should never happen)

### History panel
- Click any row → see full history
- "Version 1: Extracted (Jan 15)"
- "Version 2: Enriched designation A286 → A286 (180 KSI) CRES (auto, std_parts_lookup)"
- "Version 3: Suppressed by jdoe: 'Garbled extraction' (Jan 16)"
- "Version 4: Restored by admin (Jan 17)"
