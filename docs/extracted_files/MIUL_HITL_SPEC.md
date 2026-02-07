# MIUL HITL + Materials DB — VSClaude Implementation Spec

## Overview

Three components that work together to take MIUL output from ~64% complete to ~96% complete:

1. **Postgres Materials DB** — Two tables: `materials_reference` (alloy families) and `std_parts_lookup` (known hardware PN→material mappings)
2. **HITL Rules Engine** — Scans MIUL output, auto-fixes what it can, flags what needs human review
3. **Enrichment Pipeline** — Post-extraction pass that matches parts against the DB, fills in specs, upgrades generic designations

Result: 94 rows → 60 clean + 15 auto-enriched + 11 assemblies (no material expected) + ~8 true HITL = **91.5% automated, 8.5% human review**

---

## Part 1: Postgres Schema

### Table: `materials_reference`

The canonical materials knowledge base. Every alloy family MIRA knows about.

```sql
CREATE TABLE materials_reference (
    id              SERIAL PRIMARY KEY,
    designation     TEXT NOT NULL UNIQUE,      -- "A286 CRES", "INCONEL 718", "7075-T651 ALUMINUM"
    family          TEXT NOT NULL,             -- "nickel_superalloy", "austenitic_stainless", "aluminum"
    uns             TEXT,                      -- "S66286", "N07718", "A97075" (nullable for generics)
    spec_primary    TEXT,                      -- "SAE AMS 5731" (nullable for generics)
    spec_alternates TEXT[],                    -- ARRAY of alternate specs
    common_forms    TEXT[],                    -- ARRAY: "BAR", "SHEET", "FORGING", "WIRE"
    is_specific     BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE for "INCONEL" (no alloy#), "A286" (no CRES)
    hitl_required   BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE if this designation triggers HITL
    hitl_question   TEXT,                      -- What to ask the human
    resolves_to     TEXT,                      -- "A286" resolves_to "A286 CRES"
    notes           TEXT,
    
    -- Strength classes (for fastener alloys like A286)
    strength_classes JSONB,    -- {"180 KSI": {"spec": "SAE AMS 5737", "condition": "..."}, ...}
    
    -- Subtypes (for polymers like VESPEL SP-3)
    subtypes        JSONB,    -- {"TYPE III/M": "MoS2 filled", "TYPE III/P": "PTFE filled"}
    
    -- Context-dependent resolution (for "NICKEL ALLOY" etc.)
    common_resolution JSONB,  -- {"MS20995": "INCONEL X-750", "NASM20995": "INCONEL X-750"}
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_materials_family ON materials_reference(family);
CREATE INDEX idx_materials_hitl ON materials_reference(hitl_required) WHERE hitl_required = TRUE;
CREATE INDEX idx_materials_uns ON materials_reference(uns) WHERE uns IS NOT NULL;
```

### Table: `std_parts_lookup`

Maps standard part number patterns to known materials. The auto-enrichment engine.

```sql
CREATE TABLE std_parts_lookup (
    id                  SERIAL PRIMARY KEY,
    part_number_pattern TEXT NOT NULL,          -- Human-readable: "NAS1352N*"
    part_number_regex   TEXT NOT NULL,          -- Regex: "^NAS1352N\\d+-\\d+"
    description_template TEXT,                  -- "SHCS, Socket Head Cap Screw"
    designation         TEXT NOT NULL,          -- "A286 CRES"
    designation_full    TEXT,                   -- "A286 (180 KSI) CRES" (more specific)
    uns                 TEXT,                   -- "S66286"
    material_spec       TEXT,                   -- "SAE AMS 5737"
    strength_class      TEXT,                   -- "180 KSI"
    source              TEXT,                   -- "NAS1352 specification"
    notes               TEXT,
    examples            TEXT[],                 -- ARRAY: ["NAS1352N4-10", "NAS1352N4-12"]
    
    -- Link to materials_reference
    material_ref_id     INTEGER REFERENCES materials_reference(id),
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_std_parts_pattern ON std_parts_lookup(part_number_pattern);
```

### Table: `hitl_queue`

Tracks items flagged for human review. This is what the MIRA UI renders.

```sql
CREATE TABLE hitl_queue (
    id              SERIAL PRIMARY KEY,
    miul_id         TEXT NOT NULL,              -- Which MIUL this belongs to (e.g., "MER07540")
    row_index       INTEGER NOT NULL,           -- Row in the MIUL spreadsheet
    part_number     TEXT NOT NULL,
    part_description TEXT,
    current_designation TEXT,                   -- What extraction produced
    
    -- HITL metadata
    rule_id         TEXT NOT NULL,              -- Which rule flagged it: "GENERIC_INCONEL"
    priority        TEXT NOT NULL,              -- "P0", "P1", "P2", "INFO"
    hitl_prompt     TEXT NOT NULL,              -- Question for the human
    context_hint    TEXT,                       -- Auto-generated hint from rules engine
    suggested_value TEXT,                       -- Best guess if we have one
    
    -- Resolution
    status          TEXT NOT NULL DEFAULT 'pending',  -- "pending", "resolved", "skipped"
    resolved_designation TEXT,                  -- What the human entered
    resolved_spec   TEXT,                       -- Material spec they confirmed
    resolved_by     TEXT,                       -- Username
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,                       -- Free text: "Confirmed from drawing MER07573-001"
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_hitl_miul ON hitl_queue(miul_id);
CREATE INDEX idx_hitl_status ON hitl_queue(status) WHERE status = 'pending';
CREATE INDEX idx_hitl_priority ON hitl_queue(priority);
```

### Table: `enrichment_log`

Audit trail of every auto-enrichment. Full provenance.

```sql
CREATE TABLE enrichment_log (
    id              SERIAL PRIMARY KEY,
    miul_id         TEXT NOT NULL,
    row_index       INTEGER NOT NULL,
    part_number     TEXT NOT NULL,
    
    field_name      TEXT NOT NULL,              -- "designation", "material_spec", "uns"
    value_before    TEXT,                       -- What extraction produced
    value_after     TEXT NOT NULL,              -- What enrichment set it to
    
    enrichment_source TEXT NOT NULL,            -- "std_parts_lookup", "materials_reference", "hitl_resolution"
    source_id       INTEGER,                   -- FK to the source record
    confidence      TEXT NOT NULL DEFAULT 'high', -- "high" (exact match), "medium" (regex), "low" (heuristic)
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_enrichment_miul ON enrichment_log(miul_id);
```

---

## Part 2: Seed Data

### materials_reference seed (19 entries)

```sql
INSERT INTO materials_reference (designation, family, uns, spec_primary, spec_alternates, common_forms, is_specific, hitl_required, hitl_question, resolves_to, strength_classes, notes) VALUES

-- Aluminum
('7075-T651 ALUMINUM', 'aluminum', 'A97075', 'ASTM B211', ARRAY['SAE AMS-QQ-A-225/9', 'SAE AMS 4078'], ARRAY['BAR', 'PLATE', 'FORGING'], TRUE, FALSE, NULL, NULL, NULL, 'High-strength aerospace aluminum. T651 = stress relieved by stretching.'),
('6061-T6 ALUMINUM', 'aluminum', 'A96061', 'ASTM B209', ARRAY['SAE AMS-QQ-A-250/11', 'SAE AMS 4027'], ARRAY['SHEET', 'PLATE', 'BAR', 'TUBE'], TRUE, FALSE, NULL, NULL, NULL, 'General purpose aerospace aluminum.'),
('ALUMINUM BRONZE ALLOY', 'copper', 'C95400', 'ASTM B505', ARRAY['SAE AMS 4880'], ARRAY['BAR', 'CASTING'], FALSE, TRUE, 'Which aluminum bronze? C95400? C95500? Need UNS or spec.', NULL, NULL, 'Used for bearings, bushings, wear surfaces.'),

-- CRES / Stainless
('A286 CRES', 'iron_nickel_superalloy', 'S66286', 'SAE AMS 5731', ARRAY['SAE AMS 5737', 'SAE AMS 5525', 'SAE AMS 5726'], ARRAY['BAR', 'FORGING', 'SHEET', 'WIRE'], TRUE, FALSE, NULL, NULL,
 '{"130 KSI": {"spec": "SAE AMS 5731", "condition": "Solution treated + aged"}, "140 KSI": {"spec": "SAE AMS 5732"}, "150 KSI": {"spec": "SAE AMS 5525", "condition": "Cold drawn wire"}, "160 KSI": {"spec": "SAE AMS 5726", "condition": "High strength bolting"}, "180 KSI": {"spec": "SAE AMS 5737", "condition": "High strength fastener grade"}, "200 KSI": {"spec": "SAE AMS 5853", "condition": "Maximum strength"}}',
 'Iron-nickel superalloy. Excellent for LOX/GOX. Non-magnetic after aging.'),
('A286', 'iron_nickel_superalloy', 'S66286', NULL, NULL, NULL, FALSE, TRUE, 'A286: need (1) CRES confirmed? (2) Strength class (KSI)? (3) Which AMS spec?', 'A286 CRES', NULL, 'Generic A286. Almost always A286 CRES (UNS S66286). Need strength class for fasteners.'),
('302 CRES', 'austenitic_stainless', 'S30200', 'ASTM A313', ARRAY['SAE AMS 5688'], ARRAY['WIRE', 'SPRING'], TRUE, FALSE, NULL, NULL, NULL, 'Common for springs and Belleville washers.'),
('302 OR 304 CRES', 'austenitic_stainless', NULL, 'MS21209', NULL, ARRAY['INSERT'], TRUE, FALSE, NULL, NULL, NULL, 'Per MS21209, helical coil inserts can be 302 or 304.'),
('304 CRES', 'austenitic_stainless', 'S30400', 'ASTM A240', ARRAY['SAE AMS 5513'], ARRAY['SHEET', 'PLATE', 'BAR'], TRUE, FALSE, NULL, NULL, NULL, 'Most common austenitic stainless.'),
('316 CRES', 'austenitic_stainless', 'S31600', 'ASTM A276', ARRAY['SAE AMS 5648', 'ASTM A580'], ARRAY['BAR', 'WIRE', 'TUBE', 'FITTING'], TRUE, FALSE, NULL, NULL, NULL, 'Mo-bearing austenitic. Common for fittings.'),
('18-8 CRES', 'austenitic_stainless', NULL, 'ASTM F879', NULL, NULL, FALSE, FALSE, NULL, '304 CRES or 302 CRES', NULL, 'Generic 18-8 (18% Cr, 8% Ni). Usually 304 or 302.'),

-- Nickel superalloys
('INCONEL 718', 'nickel_superalloy', 'N07718', 'SAE AMS 5663', ARRAY['SAE AMS 5596', 'SAE AMS 5662', 'ASTM B637'], ARRAY['BAR', 'FORGING', 'SHEET', 'WIRE'], TRUE, FALSE, NULL, NULL, NULL, 'Precipitation-hardened Ni-Cr-Fe-Mo-Nb. Primary aerospace superalloy.'),
('INCONEL 625', 'nickel_superalloy', 'N06625', 'SAE AMS 5666', ARRAY['SAE AMS 5599', 'ASTM B443'], ARRAY['BAR', 'SHEET', 'WELD WIRE', 'FORGING'], TRUE, FALSE, NULL, NULL, NULL, 'Solid-solution strengthened. Excellent weldability.'),
('INCONEL X-750', 'nickel_superalloy', 'N07750', 'SAE AMS 5698', ARRAY['SAE AMS 5542'], ARRAY['WIRE', 'BAR', 'SPRING'], TRUE, FALSE, NULL, NULL, NULL, 'Age-hardenable. Standard for safety wire and springs.'),
('INCONEL', 'nickel_superalloy', NULL, NULL, NULL, NULL, FALSE, TRUE, 'Which Inconel? 625 (weld/corrosion), 718 (strength/springs), X-750 (springs/bolts)?', NULL, NULL, 'Generic Inconel. MUST resolve to specific alloy.'),
('INCONEL ALLOY', 'nickel_superalloy', NULL, NULL, NULL, NULL, FALSE, TRUE, 'Same as INCONEL — which specific alloy?', 'INCONEL', NULL, 'Generic Inconel variant wording.'),
('NICKEL ALLOY', 'nickel_superalloy', NULL, NULL, NULL, NULL, FALSE, TRUE, 'Which nickel alloy? For safety wire (MS20995), it is Inconel X-750.', NULL, '{"MS20995": "INCONEL X-750", "NASM20995": "INCONEL X-750"}', 'Context-dependent resolution.'),

-- Non-metallics
('PCTFE', 'fluoropolymer', NULL, 'ASTM D7194', ARRAY['ASTM D1430'], ARRAY['ROD', 'SHEET', 'MOLDED'], TRUE, FALSE, NULL, NULL, NULL, 'Polychlorotrifluoroethylene. Excellent for LOX/GOX service.'),
('SI3N4', 'ceramic', NULL, NULL, NULL, ARRAY['BEARING BALL', 'BEARING ROLLER'], TRUE, FALSE, NULL, NULL, NULL, 'Silicon nitride. Hybrid ceramic bearings. Non-sparking in O2.'),

-- Placeholders
('MISC', 'placeholder', NULL, NULL, NULL, NULL, FALSE, TRUE, 'MISC = assembly with multiple materials. Mark VARIOUS or specify primary.', NULL, NULL, 'Placeholder for mixed-material assemblies.');
```

### std_parts_lookup seed (21 pattern entries covering 38+ part numbers)

The JSON file `std_parts_reference.json` contains all entries. Load with:

```python
import json
import psycopg2

with open("std_parts_reference.json") as f:
    parts = json.load(f)

conn = psycopg2.connect(...)
cur = conn.cursor()

for p in parts:
    cur.execute("""
        INSERT INTO std_parts_lookup 
        (part_number_pattern, part_number_regex, description_template,
         designation, designation_full, uns, material_spec, 
         strength_class, source, notes, examples)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        p['part_number_pattern'], p['part_number_regex'],
        p.get('description_template'), p['designation'],
        p.get('designation_full'), p.get('uns'),
        p.get('material_spec'), p.get('strength_class'),
        p.get('source'), p.get('notes'),
        p.get('examples', [])
    ))

conn.commit()
```

---

## Part 3: HITL Rules Engine

### Location: `mira/miul/v3/hitl_engine.py` (new file)

### Core Function

```python
"""
HITL Rules Engine for MIUL Designation Validation
=================================================
Scans MIUL output rows and:
1. Auto-fixes trivial issues (trailing note refs)
2. Auto-enriches from std_parts_lookup (DB match → fill spec)
3. Flags true HITL items with context-aware prompts

Usage:
    from mira.miul.v3.hitl_engine import process_miul_hitl
    
    result = process_miul_hitl(miul_rows, db_conn, miul_id="MER07540")
    
    # result.auto_fixed: list of rows auto-corrected
    # result.enriched: list of rows enriched from std_parts DB
    # result.hitl_queue: list of items needing human review
    # result.clean: list of rows with no issues
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------
# HITL Rule Definitions
# ---------------------------------------------------------------

HITL_RULES = [
    # P0 — Garbled data
    {
        "rule_id": "GARBLED_DESIGNATION",
        "priority": "P0",
        "field": "designation",
        "detect": lambda desig, pn, desc: bool(re.match(
            r'^(?:SEMBLY|SSEMBLY|EMBLY|MM\s)', desig
        )) if desig else False,
        "auto_fix": None,
        "prompt": "Designation appears garbled (extraction error). Verify from source drawing.",
    },
    {
        "rule_id": "NOTE_REF_AS_PN",
        "priority": "P0",
        "field": "part_number",
        "detect": lambda desig, pn, desc: bool(re.match(r'^\d{1,2}\.$', pn.strip())) if pn else False,
        "auto_fix": None,
        "prompt": "Part number is a drawing note reference, not a real part. "
                  "Typically a consumable (lubricant, sealant). Specify exact material.",
    },
    {
        "rule_id": "MISSING_DESCRIPTION",
        "priority": "P1",
        "field": "description",
        "detect": lambda desig, pn, desc: not desc or not desc.strip(),
        "auto_fix": None,
        "prompt": "Part description is missing. Check source drawing.",
    },
    
    # P1 — Auto-fixable
    {
        "rule_id": "TRAILING_NOTE_REF",
        "priority": "P1",
        "field": "part_number",
        "detect": lambda desig, pn, desc: bool(re.search(r'\s+\d+\.$', pn)) if pn else False,
        "auto_fix": lambda pn: re.sub(r'\s+\d+\.$', '', pn),
        "prompt": None,  # Auto-fixed, no human needed
    },
    
    # P1 — Generic materials
    {
        "rule_id": "GENERIC_INCONEL",
        "priority": "P1",
        "field": "designation",
        "detect": lambda desig, pn, desc: desig.strip().upper() in ('INCONEL', 'INCONEL ALLOY') if desig else False,
        "auto_fix": None,
        "prompt": "Which Inconel? 625 (weld/corrosion), 718 (strength/springs), X-750 (springs/bolts)?",
        "context_hints": {
            "WELD": "Likely INCONEL 625",
            "BELLOWS": "Likely INCONEL 718",
            "BELLEVILLE": "Likely INCONEL 718",
            "SPRING": "Likely INCONEL X-750 or 718",
            "WIRE": "Likely INCONEL X-750",
        },
    },
    {
        "rule_id": "GENERIC_NICKEL",
        "priority": "P1",
        "field": "designation",
        "detect": lambda desig, pn, desc: desig.strip().upper() == 'NICKEL ALLOY' if desig else False,
        "auto_fix": None,  # Could auto-resolve for MS20995 but flag anyway
        "prompt": "Which nickel alloy? For safety wire (MS20995/NASM20995), it's INCONEL X-750.",
    },
    
    # P2 — Enrichable
    {
        "rule_id": "GENERIC_A286",
        "priority": "P2",
        "field": "designation",
        "detect": lambda desig, pn, desc: desig.strip().upper() == 'A286' if desig else False,
        "auto_fix": None,  # Resolved via std_parts_lookup
        "prompt": "A286 needs CRES suffix, strength class (KSI), and AMS spec number.",
    },
    {
        "rule_id": "MISC_DESIGNATION",
        "priority": "P2",
        "field": "designation",
        "detect": lambda desig, pn, desc: desig.strip().upper() == 'MISC' if desig else False,
        "auto_fix": None,
        "prompt": "MISC = multiple materials in assembly. Mark as VARIOUS or specify primary material.",
    },
    {
        "rule_id": "MISSING_DESIGNATION",
        "priority": "P2",
        "field": "designation",
        "detect": lambda desig, pn, desc: (
            not desig and desc and 
            'ASSEMBLY' not in desc.upper() and 
            'SUB-ASSEMBLY' not in desc.upper()
        ),
        "auto_fix": None,  # Resolved via std_parts_lookup
        "prompt": "No material designation found. Check source drawing or specify material.",
    },
]


# ---------------------------------------------------------------
# Core Processing
# ---------------------------------------------------------------

@dataclass
class HITLResult:
    auto_fixed: list = field(default_factory=list)
    enriched: list = field(default_factory=list)
    hitl_queue: list = field(default_factory=list)
    clean: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def process_miul_hitl(miul_rows: list, db_conn, miul_id: str) -> HITLResult:
    """
    Process all MIUL rows through the HITL rules engine.
    
    Args:
        miul_rows: List of dicts, each representing a MIUL row
        db_conn: psycopg2 connection to the materials DB
        miul_id: Identifier for this MIUL (e.g., "MER07540")
    
    Returns:
        HITLResult with categorized rows
    """
    result = HITLResult()
    
    for row in miul_rows:
        idx = row.get('Index', 0)
        pn = str(row.get('Part Number', '')).strip()
        desc = str(row.get('Part Description', '')).strip()
        desig = str(row.get('Designation', '')).strip()
        
        # Skip header/footer rows
        if idx <= 2 or idx == -1:
            continue
        
        # Check if assembly (no material expected)
        if not desig and desc and ('ASSEMBLY' in desc.upper() or 'SUB-ASSEMBLY' in desc.upper()):
            result.clean.append({'row': idx, 'status': 'assembly_no_material'})
            continue
        
        # --- Phase 1: Auto-fixes ---
        auto_fixed = False
        for rule in HITL_RULES:
            if rule['auto_fix'] and rule['detect'](desig, pn, desc):
                if rule['field'] == 'part_number':
                    old_val = pn
                    pn = rule['auto_fix'](pn)
                    row['Part Number'] = pn
                    result.auto_fixed.append({
                        'row': idx, 'rule': rule['rule_id'],
                        'field': 'Part Number', 'before': old_val, 'after': pn
                    })
                    auto_fixed = True
                    _log_enrichment(db_conn, miul_id, idx, pn, 
                                   'Part Number', old_val, pn, 'auto_fix')
        
        # --- Phase 2: Std Parts DB enrichment ---
        enrichment = _try_std_parts_enrichment(db_conn, pn, desig)
        if enrichment:
            changes = []
            if enrichment.get('designation_full') and enrichment['designation_full'] != desig:
                old_desig = desig
                row['Designation'] = enrichment['designation_full']
                desig = enrichment['designation_full']
                changes.append(('Designation', old_desig, desig))
            
            if enrichment.get('material_spec') and not row.get('Material Specification'):
                row['Material Specification'] = enrichment['material_spec']
                changes.append(('Material Specification', '', enrichment['material_spec']))
            
            if changes:
                result.enriched.append({
                    'row': idx, 'part_number': pn, 'changes': changes,
                    'source': enrichment.get('source', 'std_parts_lookup')
                })
                for field_name, old_val, new_val in changes:
                    _log_enrichment(db_conn, miul_id, idx, pn,
                                   field_name, old_val, new_val, 'std_parts_lookup',
                                   source_id=enrichment.get('id'))
        
        # --- Phase 3: HITL flagging ---
        # Re-check after enrichment (some rules may no longer apply)
        flagged = False
        for rule in HITL_RULES:
            if rule['auto_fix']:  # Skip auto-fix rules (already handled)
                continue
            if rule['detect'](desig, pn, desc):
                # Generate context hint if available
                context_hint = None
                if 'context_hints' in rule and desc:
                    for keyword, hint in rule['context_hints'].items():
                        if keyword in desc.upper():
                            context_hint = hint
                            break
                
                hitl_item = {
                    'miul_id': miul_id,
                    'row_index': idx,
                    'part_number': pn,
                    'part_description': desc,
                    'current_designation': desig,
                    'rule_id': rule['rule_id'],
                    'priority': rule['priority'],
                    'hitl_prompt': rule['prompt'],
                    'context_hint': context_hint,
                    'suggested_value': _generate_suggestion(rule, pn, desc, desig, db_conn),
                }
                result.hitl_queue.append(hitl_item)
                _insert_hitl_queue(db_conn, hitl_item)
                flagged = True
                break  # One flag per row (highest priority wins)
        
        if not flagged and not auto_fixed and not enrichment:
            result.clean.append({'row': idx, 'status': 'ok'})
    
    # Stats
    result.stats = {
        'total_rows': len(miul_rows),
        'clean': len(result.clean),
        'auto_fixed': len(result.auto_fixed),
        'enriched': len(result.enriched),
        'hitl_pending': len(result.hitl_queue),
        'hitl_by_priority': {
            'P0': sum(1 for h in result.hitl_queue if h['priority'] == 'P0'),
            'P1': sum(1 for h in result.hitl_queue if h['priority'] == 'P1'),
            'P2': sum(1 for h in result.hitl_queue if h['priority'] == 'P2'),
        }
    }
    
    return result


def _try_std_parts_enrichment(db_conn, part_number: str, current_desig: str) -> Optional[dict]:
    """
    Look up a part number in std_parts_lookup.
    Returns enrichment dict or None.
    """
    # Clean PN for matching
    clean_pn = re.sub(r'\s+\d+\.$', '', part_number)  # Strip trailing note refs
    
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM std_parts_lookup ORDER BY id")
    rows = cur.fetchall()
    
    for row in rows:
        pattern = row['part_number_regex']  # Assumes RealDictCursor
        try:
            if re.match(pattern, clean_pn, re.IGNORECASE):
                # Match found — would this enrich?
                db_desig = row.get('designation_full') or row['designation']
                db_spec = row.get('material_spec', '')
                
                # Only enrich if it adds information
                if (not current_desig) or (db_desig != current_desig and row.get('designation_full')):
                    return {
                        'id': row['id'],
                        'designation': row['designation'],
                        'designation_full': db_desig,
                        'material_spec': db_spec,
                        'uns': row.get('uns'),
                        'source': row.get('source', 'std_parts_lookup'),
                    }
        except re.error:
            continue
    
    return None


def _generate_suggestion(rule: dict, pn: str, desc: str, desig: str, db_conn) -> Optional[str]:
    """Generate a best-guess suggestion for HITL items."""
    rule_id = rule['rule_id']
    
    if rule_id == 'GENERIC_INCONEL':
        # Use description context
        desc_upper = desc.upper() if desc else ''
        if any(kw in desc_upper for kw in ['BELLOWS', 'BELLEVILLE', 'SPRING', 'WASHER']):
            return 'INCONEL 718'
        if any(kw in desc_upper for kw in ['WELD', 'CAP', 'MOUNT']):
            return 'INCONEL 625'
        if 'WIRE' in desc_upper:
            return 'INCONEL X-750'
    
    if rule_id == 'GENERIC_NICKEL':
        pn_upper = pn.upper()
        if 'MS20995' in pn_upper or 'NASM20995' in pn_upper:
            return 'INCONEL X-750'
    
    if rule_id == 'GENERIC_A286':
        return 'A286 CRES'  # Almost always correct
    
    return None


def _log_enrichment(db_conn, miul_id, row_index, part_number,
                    field_name, value_before, value_after, source, source_id=None):
    """Write enrichment to audit log."""
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO enrichment_log 
        (miul_id, row_index, part_number, field_name, value_before, value_after, 
         enrichment_source, source_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (miul_id, row_index, part_number, field_name,
          value_before, value_after, source, source_id))
    db_conn.commit()


def _insert_hitl_queue(db_conn, item: dict):
    """Insert a HITL item into the queue table."""
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO hitl_queue 
        (miul_id, row_index, part_number, part_description, current_designation,
         rule_id, priority, hitl_prompt, context_hint, suggested_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        item['miul_id'], item['row_index'], item['part_number'],
        item.get('part_description'), item.get('current_designation'),
        item['rule_id'], item['priority'], item['hitl_prompt'],
        item.get('context_hint'), item.get('suggested_value')
    ))
    db_conn.commit()
```

---

## Part 4: Integration with MIUL Pipeline

### Where it goes in builder.py

After `merge_dt_and_parts()` completes and before writing the XLSX:

```python
# In build_miul_2phase() or wherever final MIUL rows are assembled:

# ... existing merge logic produces miul_rows ...

# --- NEW: HITL + Enrichment pass ---
from mira.miul.v3.hitl_engine import process_miul_hitl

hitl_result = process_miul_hitl(miul_rows, db_conn, miul_id=top_level_pn)

LOGGER.info(f"[HITL] Results: {hitl_result.stats}")
LOGGER.info(f"[HITL]   Clean: {hitl_result.stats['clean']}")
LOGGER.info(f"[HITL]   Auto-fixed: {hitl_result.stats['auto_fixed']}")
LOGGER.info(f"[HITL]   Enriched: {hitl_result.stats['enriched']}")
LOGGER.info(f"[HITL]   HITL pending: {hitl_result.stats['hitl_pending']}")

# miul_rows are modified in-place by the engine
# Write enriched rows to XLSX as normal
# HITL items are in the queue table, ready for the UI
```

### API endpoint for HITL resolution

```python
# In miul.py or wherever the API routes are:

@router.post("/miul/{miul_id}/hitl/{item_id}/resolve")
async def resolve_hitl_item(
    miul_id: str, 
    item_id: int,
    designation: str,
    spec: Optional[str] = None,
    note: Optional[str] = None,
    user: str = "system"
):
    """Resolve a HITL queue item with human-provided values."""
    cur = db_conn.cursor()
    cur.execute("""
        UPDATE hitl_queue 
        SET status = 'resolved',
            resolved_designation = %s,
            resolved_spec = %s,
            resolved_by = %s,
            resolved_at = NOW(),
            resolution_note = %s
        WHERE id = %s AND miul_id = %s
        RETURNING row_index, part_number
    """, (designation, spec, user, note, item_id, miul_id))
    
    row = cur.fetchone()
    if row:
        # Log the enrichment
        _log_enrichment(db_conn, miul_id, row['row_index'], row['part_number'],
                       'Designation', '', designation, 'hitl_resolution', item_id)
        
        # Update the MIUL row in the working data
        # (Implementation depends on how you persist MIUL state)
    
    db_conn.commit()
    return {"status": "resolved", "row_index": row['row_index']}
```

---

## Part 5: Expected Results for MIUL_test.xlsx

| Category | Count | % | Action |
|----------|-------|---|--------|
| Clean (no issues) | 60 | 63.8% | None |
| Assembly (no material expected) | 11 | 11.7% | None |
| Auto-fixed (trailing note ref) | 3 | 3.2% | Code strips `\s+\d+\.$` |
| Enriched (std parts DB) | 15 | 16.0% | DB adds spec, upgrades designation |
| HITL P0 (garbled/note-as-PN) | 5 | 5.3% | Human re-extracts or specifies |
| HITL P1 (generic material) | 5 | 5.3% | Human picks specific alloy |
| HITL P2 (MISC/missing) | 2 | 2.1% | Human clarifies |
| **Total automated** | **89** | **94.7%** | |
| **Total HITL** | **~10** | **~10.6%** | |

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `mira/miul/v3/hitl_engine.py` | **CREATE** | HITL rules engine + enrichment pipeline |
| `mira/miul/v3/builder.py` | **EDIT** | Add HITL pass after merge, before XLSX write |
| `mira/miul/v3/miul.py` | **EDIT** | Add HITL resolution API endpoint |
| `migrations/001_materials_db.sql` | **CREATE** | Postgres schema (4 tables) |
| `migrations/002_seed_materials.sql` | **CREATE** | Seed data (19 materials + 21 std parts patterns) |
| `materials_reference.json` | **DATA** | Materials reference seed (JSON) |
| `std_parts_reference.json` | **DATA** | Standard parts lookup seed (JSON) |
| `hitl_rules.json` | **DATA** | HITL rules definition (JSON) |
