# BS-SPEC-MUA-003: MUA Generation Pipeline — Flag-First Stepwise Specification

**BoundState Technologies — MIRA Platform**
**Document:** BS-SPEC-MUA-003 Rev A
**Date:** 2026-02-28
**Supersedes:** BS-SPEC-MUA-002 (architecture was inverted — material-first instead of flag-first)
**Governing Standards:** NASA-STD-6016C w/Change 2 (July 2025), JSC-27301 Rev J (July 2025)

---

## 1. Core Insight

An MUA has nothing to do with the material. That's non-intuitive, but it's correct.

An MUA is a response to a **flag**. MAPTIS raised a flag. The MUA answers one question: **is that flag valid in this application?**

- 1st order: Flag → Rationale (why did it flag, does the flag matter here?)
- 2nd order: Material → Sanity check (should this flag even exist on this material class?)

The material is the noun. The flag is the verb. The MUA is the answer to the verb.

This spec defines a stepwise pipeline where each step asks one question, gets one answer, and proceeds to the next step. Every step is a function. Every function is automatable. The output is a Form 551 MUA document identical to the 11 generated manually in the 2026-02-26/28 sessions.

---

## 2. Pipeline Overview

```
MIUL Row In
    │
    Step 1: WHAT FLAG?        → Read the column and the letter
    │
    Step 2: WHAT DOES IT MEAN? → Decode the letter per that column's dictionary
    │
    Step 3: SHOULD THIS FLAG EXIST? → Material-class smell test
    │
    Step 4: DOES THE HAZARD APPLY?  → Environment check against service conditions
    │
    Step 5: WHAT TYPE OF MUA?       → Classify from Steps 2+4
    │
    Step 6: WHAT CATEGORY?          → Cat I or Cat II from type
    │
    Step 7: WRITE RATIONALE         → Template fill from type + decoded flag meaning
    │
    Step 8: FILL FORM 551           → Copy MIUL fields into document
    │
    Step 9: HUMAN REVIEWS           → Engineer reads, adjusts, signs
    │
MUA Out
```

---

## 3. Step Definitions

### Step 1: WHAT FLAG?

**Input:** One MIUL row (or grouped rows sharing same MAPTIS code)
**Question:** Which screening column has a non-passing rating?
**Action:** Read each rating column. Identify all non-A ratings.

```
For each column in [FLAM, SCC, CORR, TVS, TOX, FS]:
    rating = row[column]
    if rating is None/blank → flag as MISSING_DATA
    if rating == 'A'        → pass, no MUA needed for this column
    if rating != 'A'        → this is a FLAG. Proceed to Step 2 with (column, rating)
```

**Output:** List of (column, rating) pairs that need MUAs.
**One MUA per flag.** MAPTIS 10727 with FLAM=C and FS=U = two separate MUAs.

**Grouping rule:** Before entering the pipeline, group all MIUL rows by MAPTIS code. All parts sharing the same MAPTIS code share the same ratings, so they share the same flags, so they share the same MUAs. One MUA per MAPTIS code per flag.

---

### Step 2: WHAT DOES IT MEAN?

**Input:** (column, rating) from Step 1
**Question:** What does this specific letter mean in this specific column?
**Action:** Look up the rating in the column-specific dictionary.

This is the critical step. **The same letter means different things in different columns.** The tool must use the correct dictionary for the column it's reading.

#### FLAM Dictionary (Promoted Ignition — per NHB 8060.1C/NASA-STD-6001)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | ≥5 standard samples tested, burn length ≤6.0 inches. **Pass.** | NO_FLAG |
| C | Burn length >6.0 inches. **Material failed promoted combustion test.** | REAL_FAIL |
| I | <5 standard samples tested, but all tested samples had burn length ≤6.0 inches. **Passed on limited data. Administrative shortfall, not technical failure.** | ADMIN_GAP |
| S | Special test conducted on this material. **Need to review actual test report.** | NEEDS_REVIEW |
| U | Unacceptable data or material not tested. **No usable test data exists.** | NO_DATA |
| N | Not applicable or not tested. **Context-dependent.** | NEEDS_REVIEW |
| blank | No entry in MAPTIS. **Unknown status.** | MISSING_DATA |

#### FS Dictionary (Fluid System Compatibility — NASA-STD-6001B Test 15)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | Passes 48-hour immersion screening in test fluid (hydrazine/MMH/N2O4 class). **Pass.** | NO_FLAG |
| U | No Test 15 data exists. **Material was never tested against hydrazine/N2O4.** | NO_DATA |
| blank | No entry in MAPTIS. | MISSING_DATA |

**Critical domain fact for FS:** Test 15 specifically evaluates compatibility with hydrazine (N2H4), monomethylhydrazine (MMH), and nitrogen tetroxide (N2O4). It does NOT evaluate hydrogen compatibility. Per JSC-27301 §5.1.3 and NASA-STD-6016C §4.2.1.3. This fact is used in Step 4.

#### TOX Dictionary (Offgassing — NASA-STD-6001B Test 7)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | TML ≤1.0% and CVCM ≤0.1%. **Pass.** | NO_FLAG |
| U | Not tested. | NO_DATA |
| K | **Undocumented rating. Not in any standard. MIUL builder artifact.** | BAD_DATA |
| blank | No entry. | MISSING_DATA |

#### TVS Dictionary (Thermal Vacuum Stability — ASTM E595)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | Passes outgassing in vacuum. **Pass.** | NO_FLAG |
| C | Conditional — fails under some conditions. | REAL_FAIL |
| U | Not tested. | NO_DATA |
| blank | No entry. | MISSING_DATA |

#### SCC Dictionary (Stress Corrosion Cracking)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | Resistant to SCC. **Pass.** | NO_FLAG |
| B | Conditional — batch/lot dependent. | BATCH_REQUIRED |
| C | Susceptible under certain conditions. | REAL_FAIL |
| N | Not applicable. | NO_FLAG |
| U | Not tested. | NO_DATA |
| blank | No entry. | MISSING_DATA |

#### CORR Dictionary (Corrosion)

| Rating | Decoded Meaning | Flag Type |
|--------|----------------|-----------|
| A | Resistant. **Pass.** | NO_FLAG |
| B | Conditional — batch dependent. | BATCH_REQUIRED |
| U | Not tested. | NO_DATA |
| blank | No entry. | MISSING_DATA |

**Output:** (column, rating, decoded_meaning, flag_type)

**If flag_type = BAD_DATA or MISSING_DATA or NEEDS_REVIEW → STOP. Route to human. Tool cannot proceed.**

**If flag_type = BATCH_REQUIRED → Check batch/lot traceability. If verified → no MUA. If not → route to human.**

**If flag_type = NO_FLAG → No MUA needed for this column. Done.**

**If flag_type = REAL_FAIL, ADMIN_GAP, or NO_DATA → Proceed to Step 3.**

---

### Step 3: SHOULD THIS FLAG EXIST?

**Input:** (column, rating, decoded_meaning, flag_type) + material_class from MIUL
**Question:** Does this screening category apply to this material class and environment?
**Action:** Smell test. Catch garbage flags.

```
COLUMN_APPLIES_TO = {
    'FLAM': 'all',              # Promoted ignition — tested on all materials
    'FS':   'all',              # Fluid compatibility — all materials in hazardous fluids
    'TOX':  'nonmetallic_habitable',  # MPR 45: nonmetallics in habitable compartments ONLY
    'TVS':  'nonmetallic',      # §4.2.3.6: ASTM E595 outgassing — nonmetallics ONLY
    'SCC':  'metal',            # Stress corrosion — metals only
    'CORR': 'metal',            # Corrosion — metals only
}

def material_class_from_miul(designation):
    """Determine if material is metal or nonmetallic from MIUL designation."""
    metals = ['steel', 'sst', 'cres', 'inconel', 'aluminum', 'al', 'titanium',
              'bronze', 'copper', 'nickel', 'a286', 'waspaloy', 'monel',
              'hastelloy', 'cobalt', 'tungsten', 'beryllium', 'magnesium']
    nonmetallics = ['vespel', 'teflon', 'ptfe', 'kapton', 'nylon', 'rubber',
                    'silicone', 'epoxy', 'polyimide', 'adhesive', 'sealant',
                    'elastomer', 'composite', 'foam', 'film']
    d = designation.lower()
    for m in metals:
        if m in d: return 'metal'
    for n in nonmetallics:
        if n in d: return 'nonmetallic'
    return 'unknown'  # Route to human

def should_flag_exist(column, material_class, environment):
    applies_to = COLUMN_APPLIES_TO[column]
    if applies_to == 'all':
        return True
    if applies_to == 'nonmetallic_habitable':
        return material_class == 'nonmetallic' and environment == 'habitable'
    if applies_to == 'nonmetallic':
        return material_class == 'nonmetallic'
    if applies_to == 'metal':
        return material_class == 'metal'
    return True  # Default: assume it applies
```

**Output:** True or False.

**If False → FLAG IS INVALID.** This screening doesn't apply to this material class. No MUA needed. Log the anomaly (MAPTIS has a flag that shouldn't be there) and move on. Examples:
- TOX on a metal → metals don't outgas. Skip.
- TVS on a metal → metals don't have thermal vacuum stability issues. Skip.
- SCC on a nonmetallic → nonmetallics don't stress-corrosion crack. Skip.

**If True → Proceed to Step 4.**

---

### Step 4: DOES THE HAZARD APPLY?

**Input:** (column, rating, decoded_meaning, flag_type) + service environment from MIUL
**Question:** Is the hazard that this screening tests for actually present in this application?
**Action:** One domain fact + one string match per flag type.

This is the step that writes the MUA. It answers: "MAPTIS says there's a problem. Is there actually a problem here?"

#### FLAM flags (C, I, U):

**Domain fact:** Promoted ignition testing evaluates combustion behavior in oxygen-enriched environments per NHB 8060.1C. The hazard is fire/combustion in the presence of elevated O2.

**Question:** Is there an oxygen-enriched atmosphere in the service environment?

```python
def flam_hazard_applies(media, environment):
    """Does promoted ignition hazard apply?"""
    o2_indicators = ['ox', 'gox', 'lox', 'o2', 'oxygen', 'air']
    media_lower = media.lower()
    for indicator in o2_indicators:
        if indicator in media_lower:
            return True  # O2 present — hazard applies
    return False  # No O2 — hazard does not apply
```

**If False:** FLAM flag exists but the hazard (O2-driven combustion) is not present. The rationale writes itself.

#### FS flags (U):

**Domain fact:** Test 15 evaluates compatibility with hydrazine (N2H4), MMH, and N2O4 per JSC-27301 §5.1.3 and NASA-STD-6016C §4.2.1.3. The hazard is chemical degradation in these specific propellants.

**Question:** Is the material in contact with hydrazine, MMH, or N2O4?

```python
def fs_hazard_applies(media):
    """Does Test 15 fluid compatibility hazard apply?"""
    test15_fluids = ['hydrazine', 'n2h4', 'mmh', 'monomethylhydrazine',
                     'n2o4', 'nitrogen tetroxide', 'nto', 'udmh']
    media_lower = media.lower()
    for fluid in test15_fluids:
        if fluid in media_lower:
            return True  # Material IS in Test 15 fluids — hazard applies
    return False  # Material not in Test 15 fluids — screening doesn't apply
```

**If False:** FS=U means "never tested against hydrazine." If material isn't in hydrazine, that's expected.

#### TOX flags (U, K):

**Domain fact:** Test 7 evaluates offgassing in habitable compartments per MPR 45. Only applies to nonmetallics in habitable environments.

**Question:** (Already answered in Step 3 — if it got here, the flag applies.)
**Secondary question:** Is the material in a sealed/vented application where offgassing could reach crew?

#### SCC flags (C, U):

**Domain fact:** SCC requires three simultaneous conditions: susceptible material + tensile stress + corrosive environment (moisture, chlorides, etc.).

**Question:** Is the corrosive environment present?

```python
def scc_hazard_applies(media, temperature):
    """Does SCC hazard apply?"""
    # Cryogenic H2 suppresses aqueous SCC mechanisms
    # No moisture, no chlorides in clean H2 systems
    scc_suppressors = ['gh2', 'lh2', 'h2', 'hydrogen']
    media_lower = media.lower()
    for s in scc_suppressors:
        if s in media_lower:
            return False  # Cryogenic H2 suppresses SCC. No aqueous environment.
    return True  # Other media — SCC may apply
```

**Output of Step 4:** hazard_applies = True or False

**Combine with flag_type from Step 2 to get MUA classification in Step 5.**

---

### Step 5: WHAT TYPE OF MUA?

**Input:** flag_type (from Step 2) + hazard_applies (from Step 4)
**Action:** Deterministic classification.

```
flag_type = REAL_FAIL  + hazard_applies = False  →  ANTI_RULE
flag_type = REAL_FAIL  + hazard_applies = True   →  REAL_PROBLEM (route to human)
flag_type = ADMIN_GAP  + hazard_applies = False  →  INCOMPLETE_PASS
flag_type = ADMIN_GAP  + hazard_applies = True   →  INCOMPLETE_PASS (still favorable data)
flag_type = NO_DATA    + hazard_applies = False  →  THIN_SCREENING
flag_type = NO_DATA    + hazard_applies = True   →  REAL_GAP (route to human)
```

| flag_type | hazard_applies | MUA Type | Automatable? |
|-----------|---------------|----------|-------------|
| REAL_FAIL | No | ANTI_RULE | Yes |
| REAL_FAIL | Yes | REAL_PROBLEM | No — needs engineer |
| ADMIN_GAP | No | INCOMPLETE_PASS | Yes |
| ADMIN_GAP | Yes | INCOMPLETE_PASS | Yes (data is favorable) |
| NO_DATA | No | THIN_SCREENING | Yes |
| NO_DATA | Yes | REAL_GAP | No — needs engineer |

**Three automatable types. Two human-required types.**

The tool handles the paperwork (ANTI_RULE, INCOMPLETE_PASS, THIN_SCREENING). The engineer handles the engineering (REAL_PROBLEM, REAL_GAP).

---

### Step 6: WHAT CATEGORY?

**Input:** MUA type from Step 5
**Action:** Direct mapping.

Per NASA-STD-6016C §4.1.6.1:

| MUA Type | Category | Why |
|----------|----------|-----|
| THIN_SCREENING | II | "Fails screening, not considered hazard in its use application" |
| ANTI_RULE | II | "Fails screening, not considered hazard in its use application" |
| INCOMPLETE_PASS | II | "Fails screening, not considered hazard in its use application" |
| REAL_PROBLEM | I | "Could affect safety but has to be used for functional reasons" |
| REAL_GAP | I or II | Engineer determines — depends on whether gap is a real hazard |

**All automatable MUAs are Category II.** This is inherent — if the tool can determine the hazard doesn't apply, it's by definition "not considered a hazard in its use application."

Category I requires engineering judgment about accepted risk. That's human territory.

**Approval signatures:**
- Cat II: Prepared by (Materials Engineer) + Approved by (M&P Branch Chief)
- Cat I: Prepared by + Approved by (M&P) + Approved by (Program/Project Office)

---

### Step 7: WRITE RATIONALE

**Input:** MUA type + decoded flag meaning (Step 2) + environment data (Step 4)
**Action:** Select template, substitute values.

Each MUA type has a fixed rationale structure. The template takes the decoded flag meaning from Step 2 and the environment facts from Step 4 and combines them into 2-5 sentences.

#### THIN_SCREENING Template

```
Sentence 1: {material} (MAPTIS {code}) has a {column_name} rating of {rating},
            indicating {decoded_meaning}.

Sentence 2: {test_scope_fact}. {material} is not in {test_fluids} service in this
            application; the service medium is {actual_media}.

Sentence 3: {actual_hazard} compatibility is addressed under a separate MUA per
            NASA-STD-6016C {section_ref} [{mpr_ref}].
```

**Example filled:**
> Inconel 625 (MAPTIS 10727) has a fluid system compatibility rating of U, indicating no test data exists in MAPTIS for the NASA-STD-6001B Test 15 screening. Test 15 is a 48-hour screening test designed to evaluate material compatibility with hydrazine (N2H4), monomethylhydrazine (MMH), and nitrogen tetroxide (N2O4) class propellants. This material is not used in hydrazine, MMH, N2O4, or any other propellant for which Test 15 screening was designed. The operating medium is hydrogen (GH2/LH2) for in-space refueling. Hydrogen compatibility is addressed under a separate MUA per NASA-STD-6016C section 4.2.6.4 [MPR 192/193] and section 4.2.1.3 [MPR 47].

#### ANTI_RULE Template

```
Sentence 1: {material} (MAPTIS {code}) carries a {column_name} rating of {rating},
            indicating {decoded_meaning}.

Sentence 2: This rating is not applicable to the actual service environment.
            {environment_description}. {why_hazard_absent}.

Sentence 3: The failure mode underlying the {rating} rating — {failure_mode} — is
            not credible in {actual_media} service. {standard_ref}.

Sentence 4: {actual_hazard} compatibility is addressed under a separate MUA per
            NASA-STD-6016C {section_ref} [{mpr_ref}].
```

**Example filled:**
> Inconel 625 (MAPTIS 10727) carries a promoted ignition rating of C per NHB 8060.1C/NASA-STD-6001, indicating test specimens exhibited a burn length greater than 6.0 inches under standard promoted combustion conditions in oxygen-enriched environments. This rating is not applicable to the actual service environment. The 10-inch valve operates exclusively in hydrogen media (GH2/LH2) as part of the DMLLV in-space refueling system. The non-habitable in-space location contains no oxygen-enriched atmosphere. The failure mode underlying the C rating — promoted ignition and sustained combustion propagation in enriched oxygen — is not credible in a hydrogen-only fluid system. The flammability screening requirement per NASA-STD-6016C section 4.2.1.1 [MPR 44] is satisfied because the hazard condition does not exist at the point of use. Hydrogen compatibility is addressed under a separate MUA per NASA-STD-6016C section 4.2.6.4 [MPR 192/193].

#### INCOMPLETE_PASS Template

```
Sentence 1: {material} (MAPTIS {code}) carries a {column_name} rating of {rating}.
            {decoded_meaning}. The {rating} designation reflects incomplete sample
            count, not a test failure.

Sentence 2: The existing test data is favorable. All tested specimens met acceptance
            criteria. The rating deficiency is administrative rather than technical.

Sentence 3: [If hazard doesn't apply]: Furthermore, {failure_mode} is not applicable
            to the actual service environment. {why_hazard_absent}.

Sentence 4: {actual_hazard} compatibility is addressed under a separate MUA per
            NASA-STD-6016C {section_ref} [{mpr_ref}].
```

---

### Step 8: FILL FORM 551

**Input:** All data from Steps 1-7 + MIUL row data
**Action:** Map MIUL fields directly into Form 551 fields. No transformation.

| Form 551 Field | Source |
|----------------|--------|
| MUA No. | Generated: MUA-{COLUMN}-{MATERIAL_SHORT}-{MAPTIS} |
| Category | Step 6 output |
| Date | Current date |
| Standard | "NASA-STD-6016C" (always) |
| Project | MIUL column: Project |
| System | MIUL column: Document Title + context |
| Material | MIUL column: Designation |
| MAPTIS Code | MIUL column: Material Code |
| Specification | MIUL column: Material Specification |
| Material Class | Step 3: material_class |
| Issue | Column name from Step 1 + decoded meaning header |
| Rating | MIUL column: {COLUMN} + decoded meaning from Step 2 |
| Part Number(s) | MIUL columns: Part Number, Part Description (grouped) |
| Part Count | Count of grouped rows |
| Media | MIUL column: Fluid Type + Environment |
| Pressure | MIUL columns: Max Pressure, Min Pressure |
| Temperature | MIUL columns: Max Temperature, Min Temperature |
| Location | MIUL column: Environment (habitable/non-habitable) |
| Application | Generated from part descriptions + environment |
| Rationale | Step 7 output |
| Disposition | Generated from MUA type (see below) |

#### Disposition Templates

**THIN_SCREENING:**
> Accepted. {COLUMN}={RATING} reflects absence of {test_name} screening data for {test_fluids}. Material is not in contact with those fluids. {Actual_hazard} compatibility is addressed under companion MUA per {mpr_refs}. No {test_name} testing required.

**ANTI_RULE:**
> Accepted. {decoded_failure} does not constitute a hazard in this application. Material operates in {actual_media} with no {hazard_condition}. No additional testing or controls required for this specific screening deficiency.

**INCOMPLETE_PASS:**
> Accepted. {COLUMN}={RATING} reflects incomplete sample count, not a test failure; all tested specimens passed with results within acceptance criteria. {Additional_environment_note}. No additional {test_name} testing required.

---

### Step 9: HUMAN REVIEWS

**Input:** Completed Form 551 document
**Action:** Materials engineer reads, validates, adjusts, signs.

The tool produces a draft. The human owns the final document. The tool's job is to get the draft 90% right so the human spends 5 minutes reviewing instead of 2 hours writing from scratch.

**Human must verify:**
- MAPTIS code matches actual material (MIUL builder may have hallucinated)
- Rating is current (MAPTIS data may have been updated since MIUL was built)
- Environment data is correct (media, pressure, temperature)
- Rationale logic is sound for this specific application
- No additional concerns exist that the tool can't know about

---

## 4. Flags the Tool CANNOT Handle

These route to human immediately with a clear explanation of why:

| Situation | Why Tool Stops |
|-----------|---------------|
| REAL_FAIL + hazard applies | Material actually fails a relevant screening. Needs engineering judgment. |
| NO_DATA + hazard applies | No test data and the test is actually relevant. Needs test plan. |
| Rating = K, S, or unknown letter | Tool doesn't know what the rating means. |
| Rating = blank / MISSING_DATA | No data to work with. |
| Material class = unknown | Can't determine if screening applies. |
| No MAPTIS code | Can't identify material in database. |
| MAPTIS code doesn't match designation | Possible MIUL builder error. Needs verification. |

**The tool should be honest about what it can't do.** A clear "I can't automate this because [specific reason], here's what a human needs to decide" is more valuable than a bad MUA.

---

## 5. What About H2 Compatibility? (The Real MUA)

Everything above handles **screening MUAs** — paperwork that clears MAPTIS flags. These are Cat II, automatable, and frankly not where the engineering value lives.

The real work is the **H2COMPAT companion MUA** that every screening MUA cross-references. Per NASA-STD-6016C:

- **MPR 47 (§4.2.1.3):** MUA required for materials exposed to hazardous fluids. Hydrogen is a hazardous fluid (fuel causing physical degradation per footnote 1).
- **MPR 192 (§4.2.6.4):** Hydrogen embrittlement SHALL be addressed in M&P Plan.
- **MPR 193 (§4.2.6.4):** MUA SHALL be written rationalizing metallic material selection for H2 systems to preclude cracking.

**This MUA is Category I** — it genuinely "could affect safety" and the materials "have to be used for functional reasons." This is the accepted-risk-with-eyes-open scenario.

**This MUA is NOT automatable from MAPTIS data.** It requires:
- Hydrogen embrittlement test data (HEE, IHE, HRE)
- Fracture toughness values in hydrogen environment
- Cryogenic mechanical property data
- Weld zone characterization (where applicable)
- Reference to NASA/TM-2016-218602

**The screening MUAs buy time for this work.** Automating the 11 Cat II MUAs means the engineer isn't spending days on paperwork and can focus on the H2COMPAT MUA that actually keeps people alive.

---

## 6. Domain Facts Registry

The tool needs a small, curated set of domain facts. Not a database. Not an LLM knowledge base. A lookup table.

Each entry answers one question that Step 4 needs.

```python
DOMAIN_FACTS = {
    'FS_TEST_SCOPE': {
        'fact': 'Test 15 evaluates compatibility with hydrazine (N2H4), '
                'monomethylhydrazine (MMH), and nitrogen tetroxide (N2O4).',
        'source': 'JSC-27301 §5.1.3, NASA-STD-6016C §4.2.1.3',
        'used_in': 'Step 4 — determining if FS screening applies to service media'
    },
    'FLAM_TEST_SCOPE': {
        'fact': 'Promoted ignition testing per NHB 8060.1C evaluates combustion '
                'behavior in oxygen-enriched environments.',
        'source': 'NHB 8060.1C, NASA-STD-6001B Test 17',
        'used_in': 'Step 4 — determining if FLAM screening applies to service media'
    },
    'TOX_APPLICABILITY': {
        'fact': 'Offgassing requirements per Test 7 apply to nonmetallic materials '
                'in habitable flight compartments only.',
        'source': 'NASA-STD-6016C §4.2.1.2 [MPR 45]',
        'used_in': 'Step 3 — material class gate for TOX flags'
    },
    'TVS_APPLICABILITY': {
        'fact': 'Thermal vacuum stability per ASTM E595 applies to nonmetallic '
                'materials only. Measures outgassing (TML, CVCM, WVR).',
        'source': 'NASA-STD-6016C §4.2.3.6',
        'used_in': 'Step 3 — material class gate for TVS flags'
    },
    'H2_IS_HAZARDOUS_FLUID': {
        'fact': 'Hydrogen qualifies as hazardous fluid per footnote 1: fuels that '
                'are critical or catastrophic hazards due to physical degradation.',
        'source': 'NASA-STD-6016C §4.2.1.3 footnote 1',
        'used_in': 'Triggering H2COMPAT companion MUA requirement'
    },
    'H2_EMBRITTLEMENT_MUA_REQUIRED': {
        'fact': 'MUA SHALL be written rationalizing metallic material selection for '
                'H2 systems to preclude cracking.',
        'source': 'NASA-STD-6016C §4.2.6.4 [MPR 193]',
        'used_in': 'Cross-reference in all screening MUAs for metals in H2 service'
    },
    'CAT_I_DEFINITION': {
        'fact': 'Category I: M&P usage that could affect safety of mission/crew/'
                'vehicle or mission success BUT HAVE TO BE USED for functional '
                'reasons. Two conditions, both required.',
        'source': 'NASA-STD-6016C §4.1.6.1.1',
        'used_in': 'Step 6 — category never applies to screening artifacts'
    },
    'CAT_II_DEFINITION': {
        'fact': 'Category II: M&P usage that fails a screening and is NOT considered '
                'a hazard in its use application.',
        'source': 'NASA-STD-6016C §4.1.6.1.2',
        'used_in': 'Step 6 — all automatable MUAs are Cat II by definition'
    },
    'FLAM_I_DEFINITION': {
        'fact': 'Rating I = Less than 5 standard samples with burn length of '
                '6.0 inches or less. Incomplete pass, not failure.',
        'source': 'NHB 8060.1C rating criteria (MAPTIS tooltip)',
        'used_in': 'Step 2 — distinguishing I from C'
    },
    'FLAM_C_DEFINITION': {
        'fact': 'Rating C = Materials that have a burn length greater than '
                '6.0 inches. Actual test failure.',
        'source': 'NHB 8060.1C rating criteria (MAPTIS tooltip)',
        'used_in': 'Step 2 — distinguishing C from I'
    },
    'B_RATING_MEANING': {
        'fact': 'B = batch/lot testing required. Per retired codes 303/406, '
                'material CAN pass if specific batch is verified. Not automatic pass.',
        'source': 'NASA-STD-6016C Appendix C (retired codes 303, 406)',
        'used_in': 'Step 2 — B-rating handling'
    },
    'CAT_III_RETIRED': {
        'fact': 'Category III MUA codes retired as of 6016C Rev A and '
                'JSC-27301 Rev G. Not used for new hardware.',
        'source': 'NASA-STD-6016C §4.1.6.1.3',
        'used_in': 'Historical context for B-rating disposition'
    }
}
```

This is the entire knowledge base. 12 facts. Each traces to a specific standard section. No LLM interpolation required.

---

## 7. MUAs Generated To Date (Validation Set)

These 11 MUAs were generated using this pipeline (executed manually) and serve as the validation set for the automated tool.

| # | MAPTIS | Flag | Rating | Type | Cat | Rationale Core |
|---|--------|------|--------|------|-----|---------------|
| 1 | 10392 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 2 | 10520 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 3 | 50769 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 4 | 50768 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 5 | 50784 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 6 | 50181 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 7 | 54223 | FLAM | C | ANTI_RULE | II | Promoted combustion in O2. No O2 in H2 service. |
| 8 | 10727 | FLAM | C | ANTI_RULE | II | Promoted combustion in O2. No O2 in H2 service. |
| 9 | 10727 | FS | U | THIN_SCREENING | II | Test 15 is for hydrazine. Not in hydrazine. |
| 10 | 50678 | FLAM | C | ANTI_RULE | II | Promoted combustion in O2. No O2 in H2 service. |
| 11 | 55962 | FLAM | I | INCOMPLETE_PASS | II | <5 samples but all passed. Plus no O2 anyway. |

**Pattern:** Look at the "Rationale Core" column. Every single one is the same structure: "Test checks for X. X is not present here." That's the entire MUA in one sentence. The Form 551 document is the formal packaging of that one sentence.

---

## 8. From MUA Tool to MIUL Tool

If this pipeline works for MUA generation, it works backwards for MIUL validation:

**MIUL Validation = Run Steps 1-4 on every row, don't generate MUAs, just report:**
- "Row 38: FLAM=C, but no O2 in service → will need ANTI_RULE MUA"
- "Row 73: TOX=K, unknown rating → MIUL builder error, investigate"
- "Row 105: No MAPTIS code → can't evaluate, needs material identification"
- "Row 31: SCC=N, CORR=A, all clean → no MUAs needed"

The MIUL tool is Steps 1-5 without Steps 6-8. It triages the entire parts list and tells the engineer: here's what needs MUAs, here's what's clean, here's what's broken.

**That's the product.** Not "generate 130 MUAs." It's "here are the 11 that matter, here are the 5 that are broken, here are the 114 that are clean, go."

---

## 9. Implementation Notes

### Trust the MIUL
The MAPTIS code on the MIUL was assigned by a human. Do NOT re-resolve from material designation. Use the code directly. The prior system re-resolved and got the wrong code (10011 instead of 10392). This is the #1 bug to not repeat.

### Column-Specific Dictionaries Are Not Optional
The same letter means different things in different columns. "C" in FLAM = burn > 6 inches (real failure). "C" in TVS = conditional outgassing (real failure). "I" in FLAM = incomplete pass (favorable data). The tool MUST decode per-column. A generic "C = bad" approach produces wrong MUAs.

### 12 Domain Facts, Not 12,000
The tool needs 12 curated facts (Section 6), not a vector database of 5,650 precedents. Each fact answers one question in one step. The precedent database is useful for REAL_PROBLEM and REAL_GAP types where the engineer needs prior art — but for the automatable types, precedents add noise without value.

### No Self-Referential Evidence
The tool must never cite its own output as precedent. Every claim in the rationale traces to a standard section (MPR number) or a domain fact with a specific source citation. "Precedent support: [system-generated text]" is not evidence.

### Output Format
Form 551 per Appendix B of NASA-STD-6016C. The .docx format generated in the 2026-02-26/28 sessions is the reference implementation. Not a seven-section report. Not a narrative document. A form with fields.

---

*This document is a working specification derived from hands-on MUA generation against real MIUL data for the DMLLV 10-inch H2 valve (in-space refueling). It will be updated as additional flag types are encountered and as the H2COMPAT companion MUA process is defined.*

*Built by BoundState. Flag first. Material second. Standards always.*
