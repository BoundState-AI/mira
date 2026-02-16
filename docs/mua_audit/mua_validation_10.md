# MUA Validation Sample -- 10 Records for Eyeball Check

Generated: 2026-02-15 15:59

Verify that the normalizer and pattern matcher got it right.

---

### Validation Record 1 of 10

| Field | Value |
|-------|-------|
| **Source** | `sci-015.pdf` |
| **MUA Number** | TSS-SCI-015 |
| **Material** | Polyester Mylar Film |
| **Material Family** | unknown |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | Space |
| **MUA Type** | component |
| **Confidence** | 1.0 |

**Raw Issue**: `FLAM`

**Normalized Domains**: FLAMM

**Rationale** (first 500 chars):
> 1. TSS contract specifies Flammability ratings at 20.9% O2 level. No specific data at that oxygen level is available. The closest data point is at .003" thickness and 23.8% O2. Extrapolating from that point, Flammability ratings typically improve both as the thickness increases and the oxygen content decreases. 2. The position of the washer in the DACA, held between the circuit board and the retaining screws provides a very limited amount of surface area to potentially support combustion. 3. The

**Matched Patterns**:

- `small_amount` -- "...aining screws provides a very limited amount of surface area to potentiall..."

**Application** (first 300 chars):
> These Mylar washers are used in the circuit card assembly as insulating washers for the fasteners used to hold down the boards. The MAPTIS system rates this Mylar Film as 'A' - TVS and 'X' - FLAM (23.8% 02, .003" thick; 30.0% oz, .010"tk).

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 2 of 10

| Field | Value |
|-------|-------|
| **Source** | `arclsp-014.pdf` |
| **MUA Number** | ARC-LSP-014 |
| **Material** | White nylon |
| **Material Family** | polymer |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | 21.7% O₂, 77.6% N₂ |
| **MUA Type** | component |
| **Confidence** | 0.8000000000000002 |

**Raw Issue**: `(none)`

**Normalized Domains**: FLAMM, TOX

**Rationale** (first 500 chars):
> Nylon is rated "B" for flammability and toxicity in MSFC-HDBK-527, Materials Selection Guide for MSFC Spacelab Payloads. The antenna is a passive element with no internal power source. The received signal voltage will be on the order of 1mV maximum. No fire ignition sources or propagation paths exist in the antenna assembly. The antenna is fully contained within the RAHF cage. The detailed antenna design was carried as a late open item from the BTS CDR. The vendor has only recently identified th

**Matched Patterns**:

- `metallic_enclosure` -- "...enna assembly. The antenna is fully contained within the RAHF cage. The det..."
- `material_nature` -- "...g torroid to the antenna PCB (glass epoxy). A non-metallic screw..."

**Evidence Citations**:

- [standard] MSFC-HDBK-527

**Application** (first 300 chars):
> The one nylon screw in the BTS rodent antenna assembly is used to secure the tuning torroid to the antenna PCB (glass epoxy). A non-metallic screw is required to preserve the magnetic performance of the torroid. The antenna assembly is mounted to the inside right side wall of the RAHF rodent cage. O

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 3 of 10

| Field | Value |
|-------|-------|
| **Source** | `1011-0008.pdf` |
| **MUA Number** | 1011-0004 |
| **Material** | WORNOWINK M-O-N/CATA |
| **Material Family** | unknown |
| **Category** | I |
| **Determination** | APPROVED |
| **Environment** | Cabin Air O2 |
| **MUA Type** | component |
| **Confidence** | 1.0 |

**Raw Issue**: `TOX`

**Normalized Domains**: TOX

**Rationale** (first 500 chars):
> The M-O-N/CAT A Epoxy Ink is A-rated for flammability and shall be applied to metallic hardware which acts as heat sinks. There are no credible ignition sources. The 168 hr 75°F cure specified in MAPTIS with a A-rating should not present any hazard to the crew based on the extremely small amount used. The total amount used shall be much less than the 11.778 lbs. Allowable.

**Matched Patterns**:

- `small_amount` -- "...e crew based on the extremely small amount used. The total amount used s..."
- `heat_sink` -- "...ed to metallic hardware which acts as heat sinks. There are no credible ignit..."

**Application** (first 300 chars):
> The M-O-N/CAT A Epoxy Marking Ink (MC 00030) is used to rubber stamp idendification numbers on metallic hardware. The ink is A-rated at 30.0% oxy. and A-rated for toxicity with a cure of 168 hours and 75°F, followed by 24 hours at 150 F.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 4 of 10

| Field | Value |
|-------|-------|
| **Source** | `emdm-s009.pdf` |
| **MUA Number** | EMDM-S09 |
| **Material** | Al 6061-T6 |
| **Material Family** | aluminum |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | NITROGEN |
| **MUA Type** | component |
| **Confidence** | 1.0 |

**Raw Issue**: `CORROSION`

**Normalized Domains**: CORR

**Rationale** (first 500 chars):
> THE PART IS CHEMFILMED PER MIL-C-5541. Used as spacer, compressive loads only, part has been chemical filmed to prevent corrosion and is used in a non-corrosive atmosphere.

**Matched Patterns**:

- `compression_only` -- "...R MIL-C-5541. Used as spacer, compressive loads only, part has been chemical filme..."

**Application** (first 300 chars):
> USED AS A MECHANICAL STANDOFF SPACER BETWEEN TWO MATING ASSEMBLIES.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 5 of 10

| Field | Value |
|-------|-------|
| **Source** | `dpm-0004.pdf` |
| **MUA Number** | DPM 0004 |
| **Material** | KYNAR |
| **Material Family** | unknown |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | Cabin Air |
| **MUA Type** | component |
| **Confidence** | 1.0 |

**Raw Issue**: `FLAM/TOX`

**Normalized Domains**: FLAMM, TOX

**Rationale** (first 500 chars):
> NO IGNITION SOURCE - REF. MATERIAL CODE 00367 & MUA NO. DPM 0003 (SYRINGES). - SEE ATTACHED DRAWING 10130563, WHICH ILLUSTRATES THE SPECIFIC KYNAR APPLICATION. - THE MASS OF THE SYRINGE WILL SERVE AS A HEATSINK AND REDUCE THE FIRE HAZARD.

**Matched Patterns**:

- `no_ignition_source` -- "...NO IGNITION SOURCE - REF. MATERIAL CODE 00367 &..."
- `heat_sink` -- "...F THE SYRINGE WILL SERVE AS A HEATSINK AND REDUCE THE FIRE HAZARD. T..."
- `material_nature` -- "...ROTECTIVE SLEEVING TO CONTAIN GLASS FRAGMENTS IN THE EVENT OF A B..."

**Application** (first 300 chars):
> TRANSLUCENT KYNAR SHRINK SLEEVE WILL SERVE AS A PROTECTIVE SLEEVING TO CONTAIN GLASS FRAGMENTS IN THE EVENT OF A BROKEN SYRINGE.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 6 of 10

| Field | Value |
|-------|-------|
| **Source** | `cry-034-kt.pdf` |
| **MUA Number** | C4Y-MUA-034-47 |
| **Material** | DACRON NON-TREATED |
| **Material Family** | unknown |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | (none) |
| **MUA Type** | component |
| **Confidence** | 0.9000000000000001 |

**Raw Issue**: `FLAMM`

**Normalized Domains**: FLAMM

**Rationale** (first 500 chars):
> IT IS USED AS REQUIRED, BUT NOT IN CONTINUOUS LENGTHS

**Matched Patterns**:

- `metallic_enclosure` -- "...LSO WITHIN THE UNIT CRYOSTAT. Enclosed in electronics module used on te..."

**Application** (first 300 chars):
> USED FOR TYING WIRES ON PRINTED CIRCUIT BOARDS TO GATHER ALSO WITHIN THE UNIT CRYOSTAT. Enclosed in electronics module used on teflon wires. Small mounts

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 7 of 10

| Field | Value |
|-------|-------|
| **Source** | `basd-027.pdf` |
| **MUA Number** | BASD-027 |
| **Material** | Silicone Sealant |
| **Material Family** | elastomer |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | Vacuum, <10⁻⁵ torr |
| **MUA Type** | component |
| **Confidence** | 0.9 |

**Raw Issue**: `(none)`

**Normalized Domains**: CORR, FC

**Rationale** (first 500 chars):
> Material code 05227 (assigned to this silicone) shows a usage/evaluation rating of "X" for fluid system compatibility. However, the material will contact neither nitrogen tetroxide nor hydrazine.

**Matched Patterns**:

- `conformal_coating` -- "...ogen tetroxide nor hydrazine. Conformal coating for ground-wire terminal...."

**Application** (first 300 chars):
> Conformal coating for ground-wire terminal.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 8 of 10

| Field | Value |
|-------|-------|
| **Source** | `apu-107.pdf` |
| **MUA Number** | APU-107 |
| **Material** | Solid Film Lubricant |
| **Material Family** | lubricant |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | Seawater/Air |
| **MUA Type** | component |
| **Confidence** | 0.9500000000000002 |

**Raw Issue**: `Flammability`

**Normalized Domains**: FLAMM

**Rationale** (first 500 chars):
> Revise to reflect current drawing numbers. This material was previously approved for this application by MUA APU-107. See attachment 1.

**Matched Patterns**:

- `heritage_usage` -- "...ng numbers. This material was previously approved for this application by MUA A..."

**Evidence Citations**:

- [attachment] attachment 1

**Application** (first 300 chars):
> Update to incorporate drawings for Model APU02; Outline 740416; Assembly 740414. Material usage remains the same. Revision A: add using assembly 00-11545-01000. Revision B: add environment press. and temp.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 9 of 10

| Field | Value |
|-------|-------|
| **Source** | `sli-237.pdf` |
| **MUA Number** | SLI-237 |
| **Material** | NOMEX |
| **Material Family** | (none) |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | 30% O2 on aluminum substrate |
| **MUA Type** | component |
| **Confidence** | 0.7000000000000001 |

**Raw Issue**: `ER-131 yellow ink and ER-159 permanent blue ink have not been flammability nor toxicity tested`

**Normalized Domains**: FLAMM, TOX

**Unmapped fragments**: ER-131 yellow ink

**Rationale** (first 500 chars):
> The characters associated with the CTRL function keys are silk screened in yellow using Part Number ER-131. Approximately 0.04 lbs total was used for the templates. This ink has not been flammability nor toxicity tested, but it is considered to be similar to the ER-111 black ink. The ink is silk screened onto an aluminum template which acts as a heat sink and the 0.04 lbs used is within the 0.8364 lbs. weight limit. Therefore, the yellow ink is acceptable for this application. The characters on 

**Matched Patterns**:

- `heat_sink` -- "...to an aluminum template which acts as a heat sink and the 0.04 lbs used is with..."

**Application** (first 300 chars):
> Three templates for PGSC keyboard with silk screened characters. CTRL function key characters silk screened in yellow (ER-131), ALT function key characters silk screened with mixture of ER-112 (white) and ER-159 (permanent blue). Templates attached to PGSC keyboard via two 1" x 1" patches of fastene

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

### Validation Record 10 of 10

| Field | Value |
|-------|-------|
| **Source** | `pcf-001.pdf` |
| **MUA Number** | PCF-001 |
| **Material** | Aluminum/Adhesive |
| **Material Family** | aluminum |
| **Category** | None |
| **Determination** | APPROVED |
| **Environment** | Air |
| **MUA Type** | component |
| **Confidence** | 0.9500000000000002 |

**Raw Issue**: `Toxicity, Flammibility`

**Normalized Domains**: TOX

**Unmapped fragments**: Flammibility

**Rationale** (first 500 chars):
> Flammability should not be an issue due to the fact that there are no ignition sources. Toxicity should not be a concern due to the fact that there only a small amount of exposed material. Shims will be cleaned with Alcohol prior to Assembly.

**Matched Patterns**:

- `small_amount` -- "...to the fact that there only a small amount of exposed material. Shims wi..."
- `no_ignition_source` -- "...ue to the fact that there are no ignition sources. Toxicity should not be a co..."

**Application** (first 300 chars):
> The laminated shims are used to adjust the width of the PCF assembly. The shims are located under the rails that guide the PCF assembly into the R/IM.

**Eyeball Check**:
- Domains correct? ___
- Patterns correct? ___
- MUA type correct? ___
- Missing anything? ___

---

