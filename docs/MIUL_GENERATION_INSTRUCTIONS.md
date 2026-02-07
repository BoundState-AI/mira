# MIUL (Materials Identification and Usage List) Generation Instructions

## Overview

A MIUL is a hierarchical materials tracking document used by NASA for secondary payloads. It tracks all materials in an assembly, their MAPTIS material codes, and their environmental ratings. The MIUL is structured as an Excel spreadsheet that can be imported directly into the MAPTIS database.

---

## Excel Schema (40 Columns)

| Column | Name | Description |
|--------|------|-------------|
| A (0) | **Index** | Sequential integer starting at 1. Terminates with -1 after last data row |
| B (1) | **Parent** | Index number of parent row (0 = top-level) |
| C (2) | **Part Number** | Unique identifier for the part/assembly |
| D (3) | **Part Description** | Human-readable description |
| E (4) | **Nomenclature** | Standard name/designation |
| F (5) | **Title** | Display title |
| G (6) | **NHA** | Next Higher Assembly - MIUL acronym if part appears in tree, blank for subparts |
| H (7) | **Material Code** | 5-digit MAPTIS material code (e.g., 10018) |
| I (8) | **Designation** | Material name from MAPTIS (e.g., "AL 6061-T4 Sheet") |
| J (9) | **Mfg.** | Manufacturer |
| K (10) | **Material Spec.** | Material specification (e.g., "ASTM B209") |
| L (11) | **Find No.** | Find number for drawing reference |
| M (12) | **Qty** | Quantity (integer or "AR" for As Required) |
| N (13) | **Thick** | Thickness |
| O (14) | **Weight (lb)** | Weight in pounds |
| P (15) | **Surface Area (in2)** | Surface area in square inches |
| Q (16) | **Criticality** | Criticality designation |
| R (17) | **Dwg Number** | Drawing number |
| S (18) | **Dwg Rev** | Drawing revision |
| T (19) | **Dwg Description** | Drawing description |
| U (20) | **Dwg Source** | Source of drawing (e.g., "Acme") |
| V (21) | **System** | System designation |
| W (22) | **Subsystem** | Subsystem designation |
| X (23) | **O2 %** | Oxygen percentage (typically 20.9 for secondary payloads) |
| Y (24) | **Max Pressure (psia)** | Maximum pressure (typically 14.7 for secondary payloads) |
| Z (25) | **Min Pressure (psia)** | Minimum pressure (typically 0 for vacuum exposure) |
| AA (26) | **Max Temp (°F)** | Maximum temperature (typically 120 for secondary payloads) |
| AB (27) | **Min Temp (°F)** | Minimum temperature (typically 0 for secondary payloads) |
| AC (28) | **Media** | Environment media (typically "Air, VAC" for secondary payloads) |
| AD (29) | **Process Spec.** | Process specification |
| AE (30) | **CORR Rating** | Corrosion rating (A, B, C, N, U) - REQUIRED for metals |
| AF (31) | **SCC Rating** | Stress Corrosion Cracking rating - REQUIRED for metals |
| AG (32) | **TVS Rating** | Thermal Vacuum Stability rating - REQUIRED for optical devices |
| AH (33) | **FLAMM Rating** | Flammability rating - REQUIRED for non-metals |
| AI (34) | **FS Rating** | Fluid Systems rating - REQUIRED if liquids involved |
| AJ (35) | **TOX Rating** | Toxicity rating - Optional for non-habitable environments |
| AK (36) | **Cure No.** | Cure number for adhesives/sealants |
| AL (37) | **Rationale Code** | MAPTIS rationale code for MUA-exempt materials |
| AM (38) | **MUA** | Material Usage Agreement reference (e.g., "EX-MUA-001") |
| AN (39) | **Remarks** | Additional notes |

---

## Hierarchical Structure Rules

### The First Three Rows (Kick-off Rows)

```
Row 1: Index=1, Parent=0, Part Number=[Project Name]     → Project root (no NHA)
Row 2: Index=2, Parent=0, Part Number=[MIUL Acronym]     → MIUL root (NHA = acronym)
Row 3: Index=3, Parent=2, Part Number=[First Assembly]   → First assembly (NHA = acronym)
```

### Parent-Child Relationships

- **Parent column** = Index value of the parent row
- **Parent=0** = Top-level item
- **NHA column** determines tree visibility:
  - **NHA populated** = Part appears in MAPTIS tree
  - **NHA blank** = Part is a subpart (attached to parent but not separate tree node)

### Example Tree Structure

```
Index | Parent | Part Number    | NHA | Role
------|--------|----------------|-----|---------------------------
1     | 0      | My Cube Project|     | Project root
2     | 0      | MCP            | MCP | MIUL root (appears in tree)
3     | 2      | MCP-CH-001     | MCP | Assembly (appears in tree)
4     | 3      | MCP-CH-001-1   |     | Subpart of MCP-CH-001
5     | 3      | MCP-CH-001-2   |     | Subpart of MCP-CH-001
9     | 2      | MCP-PM-001     | MCP | Another assembly (appears in tree)
10    | 9      | MCP-PM-001-1   |     | Subpart of MCP-PM-001
```

---

## Rating Requirements by Material Type

### Metals
- **CORR** (Corrosion) - REQUIRED
- **SCC** (Stress Corrosion Cracking) - REQUIRED
- Ratings: A (best), B, C, N (not rated), U (unsuitable)

### Non-Metals (Plastics, Adhesives, etc.)
- **FLAMM** (Flammability) - REQUIRED
- Ratings: A (best), B, C

### Optical Devices (Cameras, Telescopes, Lenses)
- **TVS** (Thermal Vacuum Stability) - REQUIRED

### Fluid Systems
- **FS** (Fluid Systems) - REQUIRED if liquids involved

### MUA Requirements
- Materials without passing ratings for the Use Environment need an MUA
- If an appropriate Rationale Code exists, record in MIUL instead of formal MUA
- Common Rationale Codes: 409, 505

---

## Secondary Payload Default Environment

For secondary payloads (non-habitable), use these defaults:

```
O2 %:           20.9
Max Pressure:   14.7 psia
Min Pressure:   0 psia
Max Temp:       120°F
Min Temp:       0°F
Media:          Air, VAC
```

**Note:** Toxicity ratings NOT required for non-habitable environments.

---

## Special Handling

### Electronic Circuit Boards
- EEE parts are NOT rated/tracked
- Include: Board material (FR-4, etc.), conformal coating, connectors
- Typically have FLAMM ratings

### COTS (Commercial Off-The-Shelf) Items
- Mark designation as "COTS Power Supply" or similar
- May have "Various" for unknown internals

### Coatings/Platings
- List as separate material rows with same parent
- Example: BLACK OXIDE COATING on a screw

### Material-Only Rows
- Rows 14-19 in example show materials attached to an assembly
- Have Parent index but blank Part Number
- Used for components where multiple materials exist in same subpart

---

## Termination Row

**CRITICAL:** The last row must have Index = -1 with all other columns blank.

```
-1 | [blank] | [blank] | ... all columns blank ...
```

---

## Generation Algorithm

```python
def generate_miul(project_name: str, acronym: str, assemblies: list) -> DataFrame:
    """
    assemblies = [
        {
            "part_number": "MCP-CH-001",
            "description": "Chassis",
            "subparts": [
                {
                    "part_number": "MCP-CH-001-1",
                    "description": "Base Plate",
                    "material_code": "10018",
                    "designation": "AL 6061-T4 Sheet",
                    "spec": "ASTM B209",
                    "corr_rating": "B",
                    "scc_rating": "A"
                },
                ...
            ]
        },
        ...
    ]
    """
    rows = []
    index = 1
    
    # Row 1: Project root
    rows.append(make_row(index=1, parent=0, part_number=project_name, 
                         description=project_name, nha=None))
    
    # Row 2: MIUL root
    rows.append(make_row(index=2, parent=0, part_number=acronym,
                         description=project_name, nha=acronym))
    
    index = 3
    for assembly in assemblies:
        # Assembly row (appears in tree)
        assembly_index = index
        rows.append(make_row(index=index, parent=2, 
                            part_number=assembly["part_number"],
                            description=assembly["description"],
                            nha=acronym))
        index += 1
        
        # Subparts (no NHA - attached to assembly)
        for subpart in assembly["subparts"]:
            rows.append(make_row(index=index, parent=assembly_index,
                                part_number=subpart["part_number"],
                                description=subpart["description"],
                                material_code=subpart.get("material_code"),
                                designation=subpart.get("designation"),
                                nha=None,  # Subparts don't appear in tree
                                **subpart.get("ratings", {})))
            index += 1
    
    # Termination row
    rows.append(make_termination_row())
    
    return DataFrame(rows)
```

---

## Validation Checklist

Before submitting a MIUL:

- [ ] Index starts at 1 and increments by 1
- [ ] Last row has Index = -1
- [ ] All Parent values reference valid Index values
- [ ] NHA populated only for tree-visible parts
- [ ] Environment values set (O2%, Pressure, Temp, Media)
- [ ] Metals have CORR and SCC ratings
- [ ] Non-metals have FLAMM ratings
- [ ] Optical devices have TVS ratings
- [ ] Unrated materials have MUA or Rationale Code
- [ ] Material Codes are valid MAPTIS codes

---

## Example Part Number Convention

```
[ACRONYM]-[ASSEMBLY]-[PART]
MCP-CH-001        → Chassis assembly
MCP-CH-001-1      → First subpart of Chassis
MCP-PM-001        → Photomultiplier assembly
MS16995-001       → Standard hardware (MS = Military Standard)
```

---

## MAPTIS Integration

The Excel file imports directly into MAPTIS when formatted correctly. The system uses:
- Index/Parent/NHA to build the tree structure
- Material Codes to link to MAPTIS material database
- Ratings to validate against Use Environment requirements

Material codes and ratings are obtained from the MAPTIS Selection List.
