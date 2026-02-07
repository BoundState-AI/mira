# MIUL (Materials Identification and Usage List) Generation Instructions

## Overview

A MIUL is a hierarchical materials tracking document used by NASA for secondary payloads. It tracks all materials in an assembly, their MAPTIS material codes, and their environmental ratings. The MIUL is structured as an Excel spreadsheet that can be imported directly into the MAPTIS database.

**Authoritative Reference:** `SecPayMIULHelp.pdf` - MIUL Development Secondary Payloads Example
**Implementation Reference:** `mira/miul/builder.py` (MIULBuilderV3)

---

## Core Principles (from SecPayMIULHelp.pdf)

1. **ANY Materials** that are not rated, or don't have a passing rating for the Use Environment should have an MUA. If there is an appropriate Rationale Code, this can be recorded in the MIUL instead of submitting a formal MUA.

2. **Metals** at a minimum should have ratings for Corrosion (CORR) and Stress Corrosion Cracking (SCC).

3. **Non-metals** at a minimum should have Flammability (FLAMM) ratings.

4. **Optical devices** (cameras, telescopes, etc.) require Thermal Vacuum Stability (TVS) ratings.

5. **Non-habitable environments**: Toxicity ratings are not needed but can be included if desired.

6. **Electronic circuit boards**:
   - EEE parts are NOT rated or tracked
   - Indicate the board material (FR-4, etc.)
   - Include conformal coating
   - Include any connectors

7. **Fluid Systems**: If any liquids involved, FS ratings should be included.

---

## Excel Schema (Per SecPayMIULHelp.pdf)

The columns from the authoritative example:

| Column | Name | Description |
|--------|------|-------------|
| A | **Index** | Sequential integer starting at 1. **Must end with -1** after last data row |
| B | **Parent** | Index number of parent row (used to build tree hierarchy) |
| C | **Part Number** | Drawing/part identifier (e.g., "MCP-CH-001") |
| D | **Part Description** | Human-readable description |
| E | **Nomenclature** | Standard name/designation |
| F | **NHA** | Next Higher Assembly acronym - **determines tree visibility** |
| G | **Material Code** | 5-digit MAPTIS material code (e.g., 10018) |
| H | **Designation** | Material name from MAPTIS (e.g., "AL 6061-T4 Sheet") |
| I | **Mfg.** | Manufacturer |
| J | **Material Spec.** | Material specification (e.g., "ASTM B209") |
| K | **Find No.** | Find number for drawing reference |
| L | **Qty** | Quantity (integer or "AR" for As Required) |
| M | **Thick** | Thickness |
| N | **Weight (lb)** | Weight in pounds |
| O | **Surface Area (in2)** | Surface area in square inches |
| P | **Criticality** | Criticality designation |
| Q | **Dwg Number** | Drawing number |
| R | **Dwg Rev** | Drawing revision |
| S | **Dwg Description** | Drawing description |
| T | **Dwg Source** | Source of drawing (e.g., "Acme", "BUSEK") |
| U | **System** | System designation |
| V | **Subsystem** | Subsystem designation |
| W | **O2 %** | Oxygen percentage (20.9 for secondary payloads) |
| X | **Max Pressure (psia)** | Maximum pressure (14.7 for secondary payloads) |
| Y | **Min Pressure (psia)** | Minimum pressure (0 for vacuum exposure) |
| Z | **Max Temp (°F)** | Maximum temperature (120 for secondary payloads) |
| AA | **Min Temp (°F)** | Minimum temperature (0 for secondary payloads) |
| AB | **Media** | Environment media ("Air, VAC" for secondary payloads) |
| AC | **Process Spec.** | Process specification |
| AD | **CORR Rating** | Corrosion rating (A, B, C, N, U) - **REQUIRED for metals** |
| AE | **SCC Rating** | Stress Corrosion Cracking rating - **REQUIRED for metals** |
| AF | **TVS Rating** | Thermal Vacuum Stability - **REQUIRED for optical devices** |
| AG | **FLAMM Rating** | Flammability rating - **REQUIRED for non-metals** |
| AH | **FS Rating** | Fluid Systems rating - **REQUIRED if liquids involved** |
| AI | **TOX Rating** | Toxicity rating - Optional for non-habitable |
| AJ | **Cure No.** | Cure number for adhesives/sealants |
| AK | **Rationale Code** | MAPTIS rationale code (409, 505, etc.) |
| AL | **MUA** | Material Usage Agreement reference (e.g., "EX-MUA-001") |
| AM | **Remarks** | Additional notes |

---

## Secondary Payload Default Environment

**Use these values for all secondary payload MIULs:**

| Parameter | Value |
|-----------|-------|
| Min Pressure | 0 |
| Max Pressure | 14.7 |
| Min Temperature | 0 |
| Max Temperature | 120 |
| Media | Air, VAC |
| O2% | 20.9 |

---

## Hierarchical Structure (The Critical Part)

### The First 3 Rows "Kick Off" the Import Process

```
Row 1: Index=1, Parent=0, Part Number=[Project Name]     → Project identifier
Row 2: Index=2, Parent=0, Part Number=[MIUL Acronym]     → MIUL root, NHA=[Acronym]  
Row 3: Index=3, Parent=2, Part Number=[First Assembly]   → First assembly, NHA=[Acronym]
```

**Example from SecPayMIULHelp.pdf:**

| Index | Parent | Part Number | Part Description | Nomenclature | NHA |
|-------|--------|-------------|------------------|--------------|-----|
| 1 | 0 | My Cube Project | My Cube Project | My Cube Project | |
| 2 | 0 | MCP | My Cube Project | My Cube Project | MCP |
| 3 | 2 | MCP-CH-001 | Chassis | Chassis | MCP |
| 4 | 3 | MCP-CH-001-1 | Base Plate | Base Plate | |

### Parent and NHA Columns Build the Tree

**Parent column:** Determines the relationship between parts (points to Index of parent row)

**NHA column:** Determines which rows appear in the MAPTIS tree
- **NHA populated** = Part appears as a node in the tree
- **NHA blank** = Part is a subpart (attached to parent, not separate tree node)

### Tree Parts vs Sub Parts

```
Tree parts         → Have NHA populated (e.g., "MCP")
(attached at       → Parent points to row 2 (MIUL root) or another assembly
the top level)     

Sub parts          → NHA is BLANK
(attached to       → Parent points to the assembly they belong to
tree parts)        
```

**Visual from SecPayMIULHelp.pdf:**

```
Index | Parent | Part Number    | NHA | Tree Position
------|--------|----------------|-----|---------------------------
1     | 0      | My Cube Project|     | (Project root - not in tree)
2     | 0      | MCP            | MCP | ← MIUL root (appears in tree)
3     | 2      | MCP-CH-001     | MCP | ├── Chassis (appears in tree)
4     | 3      | MCP-CH-001-1   |     | │   └── Base Plate (subpart)
5     | 3      | MCP-CH-001-2   |     | │   └── Backing Plate (subpart)
6     | 3      | MS16995-001    |     | │   └── Screw, Cap (subpart)
9     | 2      | MCP-PM-001     | MCP | ├── Photomultiplier (appears in tree)
10    | 9      | MCP-PM-001-1   |     | │   └── Lense (subpart)
```

### Key Rules

1. **Index must start at 1** and increment by 1 for each row
2. **Index = -1** must be in the last row (EOF marker)
3. **Parts in the tree** have the MIUL acronym in the NHA column
4. **Subparts** have the parent Index in Parent column but **NO data in NHA column**
5. Material codes are obtained from the Selection List in MAPTIS

---

## Material Data Placement

Material data can appear on any row, but is usually placed on the subpart rows.

**Example: Materials for MCP-CH-001 (Chassis):**

| Index | Parent | Part Number | Part Description | Material Code | Designation |
|-------|--------|-------------|------------------|---------------|-------------|
| 3 | 2 | MCP-CH-001 | Chassis | | |
| 4 | 3 | MCP-CH-001-1 | Base Plate | 10018 | AL 6061-T4 Sheet |
| 5 | 3 | MCP-CH-001-2 | Backing Plate | 10017 | AL 6061-T4 Sheet |
| 6 | 3 | MS16995-001 | Screw, Cap | 20132 | BLACK OXIDE COATING |
| 7 | 3 | MS16995-001 | Screw, Cap | 10268 | CRES 300 SERIES |
| 8 | 3 | MS16995-001 | Thread locker | 00007 | Loctite EA934EA |

**Note:** The same part number (MS16995-001) can appear multiple times with different materials (coating + base metal).

---

## Ratings Requirements

Ratings are specific to Material Codes and are obtained from MAPTIS.

### Rating Scale
- **A** = Best/Acceptable
- **B** = Acceptable with limitations  
- **C** = Marginal
- **N** = Not rated
- **U** = Unsuitable
- **K** = Special (for some FLAMM ratings)

### Required Ratings by Material Type

| Material Type | Required Ratings |
|---------------|------------------|
| **Metals** | CORR, SCC |
| **Non-metals** (plastics, adhesives, polymers) | FLAMM |
| **Optical devices** (cameras, telescopes, lenses) | TVS |
| **Fluid system components** | FS |
| **Habitable environment only** | TOX (not needed for secondary payloads) |

### Example Ratings Table (from SecPayMIULHelp.pdf)

| Material Code | Designation | CORR | SCC | TVS | FLAMM | FS | TOX |
|---------------|-------------|------|-----|-----|-------|----|----|
| 10018 | AL 6061-T4 Sheet | B | A | | | | |
| 10017 | AL 6061-T4 Sheet | B | A | | | | |
| 20132 | BLACK OXIDE COATING | A | A | | | | |
| 10268 | CRES 300 SERIES | A | A | | | | |
| 00007 | Loctite EA934EA | | | A | A | | |
| 01339 | FR-4 | | | A | A | | |
| 03420 | XYDAR G-930 | | | | A | | K |
| 01517 | PTFE Insulated Wire | | | C | | | |

---

## MUA and Rationale Codes

If a material doesn't have a passing rating for the Use Environment:

1. **Submit a formal MUA** (Material Usage Agreement), OR
2. **Record an appropriate Rationale Code** in the MIUL instead

**Common Rationale Codes:**
- **409** - Limited exposure/enclosed until deployed
- **505** - De minimis quantity

**Example:** Row 19 in SecPayMIUL has PTFE Insulated Wire with TVS Rating = C and Rationale Code = 409, Remarks = "Cabling"

---

## Termination Row (CRITICAL)

**A negative one (-1) must be in the Index column after the last row with data.**

```
Index | Parent | Part Number | ... (all other columns blank)
------|--------|-------------|----
  -1  |        |             |
```

This signals EOF to the MAPTIS import process.

---

## Complete Example Structure

From SecPayMIULHelp.pdf - "My Cube Project" with acronym "MCP":

```
Index | Parent | Part Number     | Description          | NHA | Material Code | Designation
------|--------|-----------------|----------------------|-----|---------------|------------------
1     | 0      | My Cube Project | My Cube Project      |     |               |
2     | 0      | MCP             | My Cube Project      | MCP |               |
3     | 2      | MCP-CH-001      | Chassis              | MCP |               |
4     | 3      | MCP-CH-001-1    | Base Plate           |     | 10018         | AL 6061-T4 Sheet
5     | 3      | MCP-CH-001-2    | Backing Plate        |     | 10017         | AL 6061-T4 Sheet
6     | 3      | MS16995-001     | Screw, Cap           |     | 20132         | BLACK OXIDE COATING
7     | 3      | MS16995-001     | Screw, Cap           |     | 10268         | CRES 300 SERIES
8     | 3      | MS16995-001     | Thread locker        |     | 00007         | Loctite EA934EA
9     | 2      | MCP-PM-001      | Photomultiplier      | MCP |               |
10    | 9      | MCP-PM-001-1    | Lense                |     |               | Borosilicate Glass
11    | 9      | MCP-PM-002      | Lense Tube           |     | 10005         | AL 2024-T81 TUBE...
12    | 9      | MCP-PM-003      | Electronics Board    |     | 01339         | FR-4
13    | 9      | MCP-PM-004      | Connector            |     | 10022         | AL 6061-T6 Sheet
...   | ...    | ...             | ...                  | ... | ...           | ...
-1    |        |                 |                      |     |               |
```

---

## Part Number Conventions

```
[Project Acronym]-[Assembly Code]-[Part Sequence]

MCP-CH-001        → Chassis assembly (CH = Chassis)
MCP-CH-001-1      → First subpart of Chassis
MCP-PM-001        → Photomultiplier assembly (PM = Photomultiplier)
MCP-PM-001-1      → First subpart of Photomultiplier
MS16995-001       → Standard hardware (MS = Military Standard)
```

---

## MAPTIS Import Result

When properly formatted, the MIUL imports into MAPTIS showing:

**Tree Structure (left panel):**
```
□ My Cube Project
  ├── MCP-CH-001
  ├── MCP-PM-001
  ├── PS-001
  ├── SWC-001
  └── TA-001
```

**Material Codes Table (showing MCP-CH-001 selected):**
| Find No | Part No | Nomen | Mtr Code | Mfg Desig | Mfg | Spec | ... |
|---------|---------|-------|----------|-----------|-----|------|-----|
| | MCP-CH-001 | Chassis | | | | | |
| | MCP-CH-001-1 | Base Plate | 10018 | AL 6061-T4 Sheet | | ASTM B209 | |
| | MCP-CH-001-2 | Backing Plate | 10017 | AL 6061-T4 Sheet | | ASTM B209 | |

**Ratings Data Table:**
| Find No | Mtrl Code | FLM | SCC | COR | TVS | TOX | FS | Rat | MUA | Remarks |
|---------|-----------|-----|-----|-----|-----|-----|----|----|-----|---------|
| | 10018 | | A | B | | | | | | |
| | 10017 | | A | B | | | | | | |

---

## Validation Checklist

Before submitting a MIUL for import:

- [ ] Index starts at 1 and increments by 1
- [ ] **Last row has Index = -1** (EOF marker)
- [ ] First 3 rows follow kick-off pattern
- [ ] All Parent values reference valid Index values
- [ ] Tree parts have NHA = MIUL acronym
- [ ] Subparts have NHA blank
- [ ] Environment values set (O2%, Pressure, Temp, Media)
- [ ] **Metals have CORR and SCC ratings**
- [ ] **Non-metals have FLAMM ratings**
- [ ] **Optical devices have TVS ratings**
- [ ] Materials without passing ratings have MUA or Rationale Code
- [ ] Material Codes are valid MAPTIS codes (from Selection List)

---

## Builder Implementation Notes

The `mira/miul/builder.py` (MIULBuilderV3) automates MIUL generation using a 2-phase pipeline:

1. **Phase 1:** Extract Drawing Tree (DT) JSON → hierarchy/parent-child
2. **Phase 2:** Extract Parts JSON → materials, specs, descriptions  
3. **Phase 3:** Merge DT + Parts → MIUL DataFrame

**Key differences from manual SecPayMIUL format:**
- Builder uses full parent drawing numbers in NHA (e.g., "MER07543-001") rather than just acronym
- Builder calculates Parent index from NHA in post-processing
- For MAPTIS import compatibility, may need to normalize NHA to acronym format

**NHA Priority in Builder:**
1. Manual overrides from JSON file (highest authority)
2. Drawing Tree (DT) extraction
3. EPL-based inference (only for standard hardware MS/NAS/AN)

---

## Compliance

- **JSC 27301F** Section 4.2.1 - MIUL specification
- **NASA-STD-8739.8B** - Materials identification requirements
- **SecPayMIULHelp.pdf** - Authoritative secondary payload MIUL format

---

*BoundState AI 2025*
