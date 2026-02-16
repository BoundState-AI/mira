# MUA Stratified Sample v2 -- 50 Records for Manual Audit

Generated: 2026-02-15 11:09

**Dataset**: Clean merged (ghosts removed, v5 material backfill applied)

## Sampling Strategy

- 10 from **most frequent real materials**: TEFLON, PTFE, 316 SS, SILICONE, Epoxy...
- 10 from each of **top 3 concern clusters**: FLAMM, CORR, TOX
- 10 from records matching **no keyword cluster** (the weird ones)
- Remainder from **long tail** materials (count <= 3)
- Quality filter: all records have >50 chars of rationale or application
- Total: 50 records

## Audit Instructions

For each record, manually tag:

1. **WHAT** -- Can you identify a specific material? (Y/N, and what is it?)
2. **WHY** -- Can you identify a concern domain? (FLAMM/SCC/CORR/TOX/FC/TVS/OTHER)
3. **HOW** -- Is there a mitigation pattern? (test data, engineering rationale, usage limits, etc.)
4. **QUALITY** -- Is the text coherent? (Good / Partial / Garbage)

---

### Record 1 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 62 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `1001-0089.pdf` |
| **MUA Number** | 1001-0089 |
| **Material (best)** | 6AL-4V TITANIUM, 3AL-2.5V TITANIUM |
| **Material v6** | 6AL-4V TITANIUM, 3AL-2.5V TITANIUM |
| **Material v5** | 286 CRES |
| **Material Family** | titanium |
| **Category** | I |
| **Issue** | TI FASTENER USAGE, CORR, SCC |
| **Issues (cleaned)** | scc |
| **Environment** | 30% OXY. |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, SCC |

**Application (WHAT)**:
> TITANIUM FASTENERS AND NUTS ARE PROPOSED FOR ASSEMBLY OF COMPOSITE RACK COMPONENTS. THE FASTENERS PROPOSED FOR USE ARE AS FOLLOWS: (1) BACB30LN1 BOLT, 130 DEGREE HEAD 6AL-4V TITANIUM MATCO 10365. (2) EL90203NN, EDDIE BOLT, 6AL-4V TITANIUM MATCO 10365. (3) EN1183ND, EDDIE NUT, 3AL-2.5V TITANIUM MATCO 53637. THE 6AL-4V FASTENERS ARE RATED 'A' FOR CORROSION RESISTANCE AND STRESS CORROSION CRACKING. THE 3AL-2.5V TI NUTS HAVE NO CORR OR STRESS CORR DATA IN MAPTIS. THIS MUA IS INTENDED TO OUTLINE THE 

**Rationale (WHY/HOW)**:
> DUE TO THE NATURE OF LAMINATED COMPOSITES, THE STRUCTURAL DESIGN OF THE RACK CONFIGURES LOADS IN COMPOSITE MEMBERS TO PROHIBIT THROUGH-THICKNESS STRESSES. LOADS ARE CARRIED THROUGHOUT THE STRUCTURE USING SHEAR CONNECTIONS WITH THE HOLE SPACING DESIGNED TO PREVENT INTER-FASTENER BUCKLING AND INDUCED TENSION LOADS IN THE FASTENER HEADS. EACH OF THE FASTENER SYSTEMS HAS A 130 DEGREE FLUSH SHEAR HEAD TO FACILITATE USE IN THIS FASHION. A-286 CRES WILL BE USED AT THE MAJOR JOINTS IN THE RACK STRUCTURE

**Issue (concern domain)**:
> TI FASTENER USAGE, CORR, SCC

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 2 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 301 |
| **Sample Bucket** | FLAMM |
| **Source File** | `1014-0005.pdf` |
| **MUA Number** | 1014-0005 |
| **Material (best)** | Loctite 242 |
| **Material v6** | Loctite 242 |
| **Material v5** | TEFLON |
| **Material Family** | unknown |
| **Category** | I |
| **Issue** | Flammability |
| **Issues (cleaned)** | fluid_compat, flammability, toxicity |
| **Environment** | 28.5% Oxygen 71.5% Nitrogen |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, FLAMM |

**Application (WHAT)**:
> Loctite 242 used to provide secondary locking mechanism for screws of various sizes on a number of flight systems. The compound is necessary to prevent nuts and bolts from floating around the cabin if a nut/ bolt combination loses torque. Compound 242 is applied at assembly; excess compound is removed before hardening with a solvent such as acetone or methyl ethyl ketone. Fastener systems which use Loctite 242 are not orbital replacement units and therefore will not be removed in orbit.

**Rationale (WHY/HOW)**:
> A thin coating (minimal amount less than 0.0005" thick) of Loctite 242 is placed on screw threads for secondary locking; the locking compound is totally encapsulated between the threads of the mating nuts and bolts. These act as heatsinks for flammability concerns. There is no flame source or line of sight to a flame source. Loctite is not toxic, an unmeasurable amount will be used on small screws. Numerous MUAs have been approved for using Loctite (see attached MAPTIS printout). Technical Data 

**Issue (concern domain)**:
> Flammability

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 3 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 317 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `1015-0119.pdf` |
| **MUA Number** | 1016-0119 |
| **Material (best)** | BLACK OXIDE COATING |
| **Material v6** | BLACK OXIDE COATING |
| **Material v5** | CRES 300 |
| **Material Family** | coating |
| **Category** | II |
| **Issue** | FLAMMABILITY TOXICITY |
| **Issues (cleaned)** | corrosion, workmanship, flammability, toxicity |
| **Environment** | 24.1 % OXY |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, FLAMM, TOX |

**Application (WHAT)**:
> THE BLACK OXIDE COATING IS USED AS CORROSION PROTECTION ON THE AN 960XC10LL FLAT WASHER. IT IS BELIEVED THAT THE BLACK OXIDE COATING ALSO SERVES TO DISTINGUISH BETWEEN THE 0.011" AND THE -1' THICKNESSES WITH THE AN 960XC10LL FLAT WASHER HAVING A THICKNESS OF 0.016" AND A BLACK COLOR. OTHER THICKNESSES ARE SHINY METALLIC. THE AN 960XC10LL FLAT WASHER IS MADE OF CRES 300 SERIES STEEL AND IS COATED THE INORGANIC BLACK OXIDE COATING. THE WASHER IS USED AS A SPACER IN THE BLOWER SUPPORT ASSEMBLY AS S

**Rationale (WHY/HOW)**:
> THE BLACK OXIDE COATING IS NOT A FLAMMABILITY OR TOXICITY HAZARD TO THE CREW, EXPERIMENT OR MISSION SINCE IT IS HAS MINOR USAGE. FURTHERMORE, THE METALLIC STRUCTURE OF THE BLOWER SUPPORT ASSEMBLY WILL ACT AS A FIRE BARRIER AND AS A HEAT SINK. AS USED IN THIS APPLICATION, THE BLACK OXIDE COATING DOES NOT REPRESENT A FLAMMABILITY HAZARD TO THE CREW, EXPERIMENT OR MISSION.

**Issue (concern domain)**:
> FLAMMABILITY TOXICITY

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 4 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 413 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `2-13-01.pdf` |
| **MUA Number** | (unknown) |
| **Material (best)** | TEFLON |
| **Material v6** |  |
| **Material v5** | TEFLON |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | (none) |
| **Determination** | (none) |
| **Confidence** | 0.20 |
| **Cluster Matches** | FLAMM |

**Application (WHAT)**:
> (none)

**Rationale (WHY/HOW)**:
> The MUAs behind the materials list all deal with flammability. See if you can give Morgan any recommendations based upon the information supplied.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 5 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 537 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `50000-8010.pdf` |
| **MUA Number** | 50000-8010 |
| **Material (best)** | CRES 316L |
| **Material v6** | CRES 316L |
| **Material v5** | 15-5PH |
| **Material Family** | stainless_steel |
| **Category** | II |
| **Issue** | Corrosion |
| **Issues (cleaned)** | corrosion |
| **Environment** | payload waste gas |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR |

**Application (WHAT)**:
> SSP41002 Section 3.3.7.2 contains conflicting requirements for materials to come in contact with payload waste gases. The US Laboratory is limited to CRES 321 and 450. The European APM is limited to Fe Cr 18 Ni 10 Mo Ti (1.4571 / AISI 316 Ti) (Tubes); Fe Cr 18 Ni 9 (1.4306 / AISI 304 L) (Tubing system); (AISI 316 L) (QD). The Japanese Experiment Module is limited to Stainless Steel (CRES 300 series, 400 series, CRES 15-5PH, 17-4PH, 17-7PH, Custom 450). The payload waste gas vent hardware in the 

**Rationale (WHY/HOW)**:
> The intent of the material limitations in SSP41002 is to ensure that the materials which are exposed to payload waste gases have good resistance to corrosion. The lists of materials for the APM and JEM include the CRES 316L used for the Express Rack waste gas vent system, but the US Laboratory does not list CRES 316L as acceptable. Since CRES 316L provides acceptable corrosion resistance for the APM and JEM, it should also be considered acceptable for use in the US Laboratory. All entries for CR

**Issue (concern domain)**:
> Corrosion

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 6 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 538 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `50000-8011.pdf` |
| **MUA Number** | 50000-8011 |
| **Material (best)** | D. Williams |
| **Material v6** |  |
| **Material v5** | D. Williams |
| **Category** | II |
| **Issue** | Structural soldering |
| **Environment** | Cabin air |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> SSP30233 Section 4.3.6 says "Soldering shall not be used for structural applications." The BRP EMU is a vendor assembly whose fabrication will include a soldered lid on the box.

**Rationale (WHY/HOW)**:
> The attached test reports and vendor catalog pages indicate that the soldered joint will withstand the expected loads.

**Issue (concern domain)**:
> Structural soldering

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 7 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 725 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `aadsf-001.pdf` |
| **MUA Number** | AADSF-001 |
| **Material (best)** | TEFLON |
| **Material v6** |  |
| **Material v5** | TEFLON |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | Argon, 50 C Max. |
| **Determination** | (none) |
| **Confidence** | 0.60 |
| **Cluster Matches** | CORR, SCC, TVS |

**Application (WHAT)**:
> The motor assembly, drawing No. 96M60230, is used in the transition mechanism of the Advanced Automated Directional Solidification Furnace (AADSF) to convey a molten crystal sample from a hot zone to a cooler zone where solidus and crystal growth occurs. The AADSF experiment is being developed to study the growth of single crystal materials under a low-g environment. The AADSF will fly on the MSL carrier. The motor assembly will be housed in an Experiment Assembly Container (EAC) which is pressu

**Rationale (WHY/HOW)**:
> The torque output of the motor is 1.5 ft-lbs. This low power will result in extremely low stress levels in the 440 balls and should make it immune to stress corrosion. The materials comprising the major surface areas on the motor and tachometer are identified on pages 2 and 3. Thermal analysis predicts the steady state temperature of the motor assembly will be under 50 C which is significantly below cadmium's critical outgassing temperature of 100°C. Because the AADSF is defined as a class "C" e

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 8 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 802 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `acis-022.pdf` |
| **MUA Number** | ACIS-022 |
| **Material (best)** | Expando HR |
| **Material v6** | Expando HR |
| **Material v5** | EC-1443 |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | TVS: A, Flammability: X |
| **Issues (cleaned)** | offgassing, flammability, tvs |
| **Environment** | SPACE |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | FLAMM |

**Application (WHAT)**:
> The Expando HR sleeving provides protection over the cable wire harness in the following applications: 849AC831000: (1/2" Nominal Diameter) F2299050, 849AC832000: (1-1/4" Nominal Diameter) F2299125

**Rationale (WHY/HOW)**:
> 1. Flammability is not a concern as there are no ignition sources in the vicinity of this material. 2. The Expando HR sleeving literature shows an oxygen index of 48 and UL recognized as a VW-1/FR-1 component. It will not melt and drip on direct exposure to flame. 3. The Assemblies will be vented away from contamination sensitive surfaces and will be vacuum baked per MSFC-SPEC-1238 during qualification acceptance. As a result of the vacuum bake and venting of the system, contamination will not b

**Issue (concern domain)**:
> TVS: A, Flammability: X

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 9 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 947 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `apcg-002.pdf` |
| **MUA Number** | APCG-002 |
| **Material (best)** | AL 2021-T3/T4, Silicone Rubber |
| **Material v6** | AL 2021-T3/T4, Silicone Rubber |
| **Material v5** | SILICONE |
| **Material Family** | aluminum |
| **Category** | (none) |
| **Issue** | Stress Corrosion Flammability |
| **Issues (cleaned)** | corrosion, flammability, scc |
| **Environment** | 30% O2, 20% O2 |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | CORR, FLAMM, SCC |

**Application (WHAT)**:
> Two MS27511F10C TES dust caps are used in a non-structural application to cover and protect the experiment connector and the RS422 port on the TES front panel. The covers also provide a means of safety control to isolate the flight crew from inadvertent accessibility to a voltage source. Neither of these connections are used by the APCG experiment and are not powered at any time.

**Rationale (WHY/HOW)**:
> The dust cap is used in a non-structural application in a controlled non-corrosive environment. The caps employ a retention mechanism (small chain) and any failure of this cap would not create a safety hazard. Also, the silicone gasket is sandwiched between the aluminum cap and the metal connector body. The connections are not powered and there are no ignition sources. Therefore, the application of this part is safe and acceptable in the application above.

**Issue (concern domain)**:
> Stress Corrosion Flammability

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 10 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1067 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `apu-128.pdf` |
| **MUA Number** | APU-128 |
| **Material (best)** | Silicone Rubber |
| **Material v6** | Silicone Rubber |
| **Material v5** | DC 140 |
| **Material Family** | elastomer |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | other |
| **Environment** | Air, Fog Water |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> Used as an end sealer following application on Dow Corning Sylgard 186.

**Rationale (WHY/HOW)**:
> Sylgard 186 adhesion is inadequate to the metal ends. The DC 140 is needed to accomplish proper sealing at the ends.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 11 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1294 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `att-001.pdf` |
| **MUA Number** | A77-001 |
| **Material (best)** | 17-4 PH Stainless Steel |
| **Material v6** | 17-4 PH Stainless Steel |
| **Material v5** | TEFLON |
| **Material Family** | stainless_steel |
| **Category** | (none) |
| **Issue** | Use of 17-4 PH SS |
| **Issues (cleaned)** | other |
| **Environment** | GN2 |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> The hand valve is used in the panel as a gauge isolation valve when the pressure gauges require recalibration. There are 11 hand valves in the panel

**Rationale (WHY/HOW)**:
> The hand valve has a maximum operating pressure of 10,000 psig with a burst pressure of 40,000 psig. This hand valve is used by KSC (Specification 29K80049) when building systems. Per phone conversations with KSC design personnel, they have had no problem with this valve in this configuration in any of their systems. KSC is looking at GFE 11 values plus 3 spares to MSFC

**Issue (concern domain)**:
> Use of 17-4 PH SS

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 12 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1477 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `basd-120.pdf` |
| **MUA Number** | BASD-120 |
| **Material (best)** | PTFE |
| **Material v6** | PTFE |
| **Material v5** | TEFLON |
| **Material Family** | polymer |
| **Category** | I |
| **Issue** | MUL, Rev. A, 6/1/84 |
| **Issues (cleaned)** | offgassing, toxicity, tvs |
| **Environment** | vacuum |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | TOX, TVS |

**Application (WHAT)**:
> Tubing for electrical insulation on component leads, solder connections, etc. Reference MUL, Appendix D.

**Rationale (WHY/HOW)**:
> Material code 60114, assigned to Teflon tubing, shows a usage evaluation rating of "U" for toxicity and thermal vacuum stability. The CRRES spacecraft will be located in a nonhabitable area. JSC 08962, Rev. U, contains several outgassing test results on Teflon tubing and electrical insulation, all of which meet the requirements of SP-R-0022A. Some of the results are in Part I on pages 2B, 5B, and 7B. Also, Addendum 9 shows a test in Part I on page 2B.

**Issue (concern domain)**:
> MUL, Rev. A, 6/1/84

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 13 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1613 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `basd-265.pdf` |
| **MUA Number** | BASD-265 |
| **Material (best)** | Epoxy/Polyamide |
| **Material v6** | Epoxy/Polyamide |
| **Material v5** | 6061-T651 |
| **Material Family** | adhesive |
| **Category** | I |
| **Issue** | Toxicity & Fluid Systems Compatibility |
| **Issues (cleaned)** | corrosion, offgassing, toxicity, fluid_compat |
| **Environment** | Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, TOX, TVS |

**Application (WHAT)**:
> This material is used as a primer coat on the optical fence (159478) before applying a black conductive topcoat. It is also used as corrosion protection of dissimilar metals during wet installation of inserts (type 304 CRES) into aluminum alloy plate (6061-T651) on the doubler (150835) of the sun antenna assembly (150825). For the Digital Telemetry & Command Decoder Units (Appendix B), the material is used as primer before applying Chemglaze 2306 black polyurethane. CURE: Room temperature (for t

**Rationale (WHY/HOW)**:
> Material code 05135, assigned to epoxy/polyamide primers, shows a usage evaluation rating of "X" for toxicity and for fluid systems compatibility. The primer is used in negligible quantities, it will be in a nonhabitable location (CRRES will be launched by an unmanned launch vehicle), and it will not be exposed to reactive or corrosive fluids. Outgassing properties of epoxy/polyamide primers' per MIL-P-23377 are indicated by the test results tabulated below. NOTE: Revision B of this MUA provides

**Issue (concern domain)**:
> Toxicity & Fluid Systems Compatibility

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 14 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1662 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `BASD-SL-036A.pdf` |
| **MUA Number** | BASD-SL-036 |
| **Material (best)** | Epoxy |
| **Material v6** | Epoxy |
| **Material v5** |  |
| **Material Family** | adhesive |
| **Category** | I |
| **Issue** | Toxicity and Thermal Vac. Stability |
| **Issues (cleaned)** | toxicity, tvs |
| **Environment** | 75% RH @ 49°C & 0-24.5% O₂ |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | TOX, TVS |

**Application (WHAT)**:
> Epoxy is a high peel strength adhesive, approximately 35 pli.

510960 Stop Assembly, Limit (0.010 inch/<1 gm/<0.5 cm²) Nonstructural bond. Bonds Vespel SP-1 (MUA 035) to titanium bracket. Loading is primarily compressive.

511770 Stop Assembly, Sensor (0.010 inch/ 1 gm/ 0.2 cm²) Nonstructural bond. Bonds Vespel SP-1 to A286 supports.

510970 Mirror Drive Assembly
o Structural bonding of stiffeners and plates to flexures. Shear test samples to be prepared along with flight hardware to verify bond

**Rationale (WHY/HOW)**:
> Epoxy is given a "B" rating for toxicity, and a "C" rating for thermal vacuum stability per MSFC-HDBK-527, material code 05192.

Toxicity
o Required cure to meet toxicity (72 hours at room temperature) will be met for all bonds.
o This is the "no asbestos" (i.e. NA) version of EA9309.

**Issue (concern domain)**:
> Toxicity and Thermal Vac. Stability

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 15 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1733 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `bcrs-032.pdf` |
| **MUA Number** | BCRS-32 |
| **Material (best)** | Fluorinated Silicone |
| **Material v6** | Fluorinated Silicone |
| **Material v5** | SILICONE |
| **Material Family** | elastomer |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | other |
| **Environment** | Air |
| **Determination** | (none) |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> The electrical connectors will have O-rings to seal the cables.

**Rationale (WHY/HOW)**:
> This Fluorinated Silicone was approved in MUA-VCDS-39.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 16 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 1789 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `bd-da-001.pdf` |
| **MUA Number** | BD-DA-001A |
| **Material (best)** | Epoxy Adhesive |
| **Material v6** | Epoxy Adhesive |
| **Material v5** | TEFLON |
| **Material Family** | adhesive |
| **Category** | II |
| **Issue** | FLAM/TOX |
| **Issues (cleaned)** | offgassing, flammability, toxicity |
| **Environment** | MEDIA 245%O2 |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, FLAMM, TOX |

**Application (WHAT)**:
> Bonding of parts on printed circuit boards inside power supply housing (not sealed). Processing data: Mix 1/1 Cure: Room temperature 24 hours Used in: MAS-DL-04.2602-01.10/01.20/-01.11, MBB-DL-14.2609-01.00, MBB-DL-01.2905-01.10, MBB-DL-01.2606-01.00/-01.11, MBB-ST-05.2607-04.40, MBB-ST-01.2606-04.10. RATIONALE: No volings in MSFC-HDBK 527 are given Code 60428. Flammability: Per pre-MHB 8060-1B, listed in ESA-RS1-01-301 for 23.8% O2 approved for 24.5% O2 in EWP 1232 B, Item 9. Toxicity: Past per

**Rationale (WHY/HOW)**:
> No volings in MSFC-HDBK 527 are given Code 60428. Flammability: Per pre-MHB 8060-1B, listed in ESA-RS1-01-301 for 23.8% O2 approved for 24.5% O2 in EWP 1232 B, Item 9. Toxicity: Past per ESA-key vapors 151/193 Calculated. PSM-level offgas test to be done. Used in similar applications on Spacelab DE (unmanned) racks CHAUTHLORM CU and MMSJ. PCBs including adhesive are coated with Parylene C non-flammable coating. No flame propagation is possible.

**Issue (concern domain)**:
> FLAM/TOX

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 17 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2079 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `c-2030.pdf` |
| **MUA Number** | C-2030 |
| **Material (best)** | Silver Plating |
| **Material v6** | Silver Plating |
| **Material v5** | 440CSS |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | LOX Compatibility per NHB8060.1C (Test 13)(1) |
| **Issues (cleaned)** | o2_compat |
| **Environment** | LOX/GOX |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, FLAMM |

**Application (WHAT)**:
> This revision updates the LOX test type (1) and adds flight effectivity (2) for all silver plated parts used in LOX/GOX on the ATD HPOTP. See Table 1 below from previous revision for reference to exposures.

**Rationale (WHY/HOW)**:
> Materials, processing and environments are unchanged from previous revision.

**Issue (concern domain)**:
> LOX Compatibility per NHB8060.1C (Test 13)(1)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 18 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2085 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `c-3aam14.pdf` |
| **MUA Number** | 3AAM14 |
| **Material (best)** | TEFLON |
| **Material v6** |  |
| **Material v5** | TEFLON |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | AIR / VACUUM |
| **Determination** | APPROVED |
| **Confidence** | 0.70 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> THIS MUA PROVIDES CERTIFICATION OF THE FOLLOWING HARDWARE PER THE PROVISIONS AND RESTRICTIONS OF: NHB 1700.7A JSC-SER-0006B MSFC STD 5066 OTHER

**Rationale (WHY/HOW)**:
> THE CERTIFICATION BASED ON EVALUATION OF FINAL MATERIALS LIST DRAWINGS SL-3/ATMOS NON-METALLIC MATERIALS LIST 05/83, HONEYWELL/JPL METALLIC MATERIALS LIST SUBMITTED BY: JPL / LARRY SIMMONS / ATMOS PROJECT MANAGER, PER 3/22/84 AND 5/9/84 JPL MEMO

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 19 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2092 |
| **Sample Bucket** | FLAMM |
| **Source File** | `c-astro-2.pdf` |
| **MUA Number** | C-ASTRO-2 |
| **Material (best)** | AL2024 |
| **Material v6** |  |
| **Material v5** | AL2024 |
| **Category** | (none) |
| **Issue** | FLAMMABILITY, OFFGASSING, THERMAL VACUUM STABILITY (TVS) STRESS CORROSION AND CORROSION |
| **Environment** | AIR TO VACUUM |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | CORR, FLAMM, SCC, TOX, TVS |

**Application (WHAT)**:
> This MUA provides certification of the following hardware for the ASTRO-2 Mission per the provisions and restrictions of MSFC-STD-506B.

**Rationale (WHY/HOW)**:
> Certification based on evaluation of Final Materials List

**Issue (concern domain)**:
> FLAMMABILITY, OFFGASSING, THERMAL VACUUM STABILITY (TVS) STRESS CORROSION AND CORROSION

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 20 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2110 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `c-lms.pdf` |
| **MUA Number** | C-LMS |
| **Material (best)** | 17-4PH |
| **Material v6** |  |
| **Material v5** | 17-4PH |
| **Category** | (none) |
| **Issue** | Flammability, Offgassing, Thermal Vacuum Stability, Stress Corrosion, Corrosion |
| **Environment** | Module & Tunnel-24.5% O2 75.5% N2 AFD-30% O2 70% N2 AIR TO VACUUM |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | CORR, FLAMM, SCC, TOX, TVS |

**Application (WHAT)**:
> This MUA provides certification of the following hardware per the LMS mission per the provisions and restrictions of MSFC-STD-506.

**Rationale (WHY/HOW)**:
> Certification based on evaluation of Final Materials List Drawings

**Issue (concern domain)**:
> Flammability, Offgassing, Thermal Vacuum Stability, Stress Corrosion, Corrosion

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 21 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2120 |
| **Sample Bucket** | FLAMM |
| **Source File** | `c-pfa-001.pdf` |
| **MUA Number** | C-PFA-001 |
| **Material (best)** | PFA |
| **Material v6** |  |
| **Material v5** | PFA |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | 16.1 to 30.3% O2 @ 25-75% RH (40-60 Dpt) |
| **Determination** | APPROVED |
| **Confidence** | 0.70 |
| **Cluster Matches** | CORR, FLAMM, SCC, TOX, TVS |

**Application (WHAT)**:
> THIS MUA PROVIDES CERTIFICATION OF THE FOLLOWING HARDWARE PER THE PROVISIONS AND RESTRICTIONS OF: __X_NHB 1700.7 JSC-SER-0006B __T__MSFC-STD-506 __X_ OTHER (SSP 30233)

**Rationale (WHY/HOW)**:
> THE CERTIFICATION IS BASED ON EVALUATION OF: PLUS NEW USE CRITERIA __X__ FINAL MAT'LS LIST __X__ DESIGN DRAWINGS SUBMITTED BY: ATTACHMENT 1 BRIEF DESCRIPTION OF ITEM AND GENERAL CORRESPONDENCE ATTACHMENT 2 MATERIAL USAGE AGREEMENTS AND VERIFICATION SUMMARY ATTACHMENT 3 TOXIC OFFGASSING DATA AND VERIFICATION SUMMARY ATTACHMENT 4 FINAL MATERIALS LIS AND/OR FLAMMABILITY VERIFICATION SUMMARY ATTACHMENT 5 STRESS CORROSION CRACKING VERIFICATION SUMMARY ATTACHMENT 6 THERMAL VACUUM STABILITY VERIFICATIO

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 22 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2205 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `cctv-026.pdf` |
| **MUA Number** | CCTV 026 |
| **Material (best)** | Polyimide/Fluorocarbon Polyimide Tape |
| **Material v6** | Polyimide/Fluorocarbon Polyimide Tape |
| **Material v5** | 0259-O |
| **Material Family** | polymer |
| **Category** | (none) |
| **Issue** | Flammability Toxicity |
| **Issues (cleaned)** | workmanship, flammability, toxicity |
| **Environment** | 25.9%O 74.1%N |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> Polyimide/Fluorocarbon Tape is used for the jacket material in North American special purpose electrical cable MP572-0279-002 fabricated per MB0150-051. See Attachments 1 and 2 respectively. The MB0150-051 cable is used in the CCTV cable and wire list and the CCTV cable wire list monitor extension cable.

**Rationale (WHY/HOW)**:
> Polyimide/Fluorocarbon tape is used over the cable shield as described in paragraph 3.3.3 of North American Specification F4BQ150-051. See Attachment 1. Assembly of the cable is illustrated on page 240 of OPPL MF 0004-400. See Attachment 2. The cable jacket is constructed of Multi-layers of Contra-helically-wrapped Tape. The first layer is wrapped with polyimide facing the cable core. All successive layers contain fluorocarbon on both sides of the polyimide and are crosswrapped over the precedin

**Issue (concern domain)**:
> Flammability Toxicity

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 23 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2221 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `cert-erack.pdf` |
| **MUA Number** | CCRT-ERACK |
| **Material (best)** | SILICONE |
| **Material v6** |  |
| **Material v5** | SILICONE |
| **Category** | I |
| **Issue** | (none) |
| **Environment** | 24.5% O2 |
| **Determination** | APPROVED |
| **Confidence** | 0.70 |
| **Cluster Matches** | CORR |

**Application (WHAT)**:
> THIS MUA PROVIDES CERTIFICATION OF THE FOLLOWING HARDWARE PER THE PROVISIONS AND RESTRICTIONS OF: NHB 1700.7A, JSC-SER-0008B, MSFC STD 506B, OTHER

**Rationale (WHY/HOW)**:
> THE CERTIFICATION BASED ON EVALUATION OF FINAL MATERIALS LIST. Proof test per work with T value of 0.3011. No SCC or Corrosion concerns from MIUL Component MUA FMPT-ERACK approved (Rev A) for Flam & TOX.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 24 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2235 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `cgf-sac-008.pdf` |
| **MUA Number** | CGF-SAC-008 |
| **Material (best)** | Quartz Wool |
| **Material v6** | Quartz Wool |
| **Material v5** | UANWACTURER |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | No material code, No test data |
| **Issues (cleaned)** | offgassing, flammability, tvs |
| **Environment** | Argon |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | FLAMM |

**Application (WHAT)**:
> Padding material for quartz ampoule.

**Rationale (WHY/HOW)**:
> No material code exists for the material. Also, there is no test data. A data sheet is attached providing a description of the material. There should be no problems from either flammability or TVS based on the nature of the material. The material may cause respiratory tract irritations in dust form, but due to the small quantity and nature of usage this will not be a problem. This material is fully contained within the sealed cartridge. The cartridge is filled with Argon.

**Issue (concern domain)**:
> No material code, No test data

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 25 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2349 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `cry-025-kt.pdf` |
| **MUA Number** | CAY-MUA-025-LT |
| **Material (best)** | SILICONE |
| **Material v6** |  |
| **Material v5** | SILICONE |
| **Category** | I |
| **Issue** | HEAT CONDUCTIVE PASTE |
| **Environment** | (none) |
| **Determination** | APPROVED |
| **Confidence** | 0.75 |
| **Cluster Matches** | CORR |

**Application (WHAT)**:
> USED AS A THIN FILM COATING BETWEEN HEAT TRANSFER DEVICES AND COLDPLATE ELEMENTS IN THE CRYOSTAT FUSELAGE AND STORAGE UNITS. Heat sinked, sandwiched between metallics, thin layer, edge exposure only enclosed in cryostat box per 1/6/30 telecon with Grumman & JSC office

**Rationale (WHY/HOW)**:
> GOOD PERFORMANCE (SEE PAGES 2 AND 3) AND GOOD EXPERIENCE FROM APPLICATION IN D-1 HARDWARE.

**Issue (concern domain)**:
> HEAT CONDUCTIVE PASTE

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 26 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2350 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `cry-026-kt.pdf` |
| **MUA Number** | CRV-MUA-026-LT |
| **Material (best)** | EPOXY ADHESIVE AND HARDENER |
| **Material v6** | EPOXY ADHESIVE AND HARDENER |
| **Material v5** | ADHESIVE |
| **Material Family** | adhesive |
| **Category** | I |
| **Issue** | FLAMM |
| **Issues (cleaned)** | flammability |
| **Environment** | 20 VACUUM |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | FLAMM |

**Application (WHAT)**:
> 1. USED AS FILLER FOR THERMAL INSULATION AND SURFACE SEALING IN CRYOSTAT STOWAGE CONTAINER

2. USED IN FREEZER AND STABILIZER CHAMBERS FOR ADHERING FOAM PIECES TOGETHER (FEW POINTS ON CONNECTING SURFACES)

**Rationale (WHY/HOW)**:
> THERE IS NO IGNITION SOURCE OR PROPAGATION PATH IN THE VICINITY WHERE THE MATERIAL IS USED

AS PER ASD MSS-01-90-1  SNT N° A-8

**Issue (concern domain)**:
> FLAMM

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 27 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2466 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `dmls-007.pdf` |
| **MUA Number** | DMLS-7 |
| **Material (best)** | Toggle Switch, Circuit Breaker |
| **Material v6** | Toggle Switch, Circuit Breaker |
| **Material v5** | 6000 O |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | All |
| **Issues (cleaned)** | offgassing, flammability |
| **Environment** | Cabin Air |
| **Determination** | (none) |
| **Confidence** | 0.90 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> The toggle switch is used to switch power from one lamp to the other in case of failure in the primary lamp. The circuit breaker is used as a main power on/off switch for the DMLS. Neither the switch nor the circuit breaker appear in MSFC-HDBK-527F.

**Rationale (WHY/HOW)**:
> The switch is built to military specifications, and is the best available for the application. Airpax circuit breakers have been flight approved for use on rack hardware. The switches do not see significant loading therefore no significant stresses will occur. The DMLS will be used twice, each time for approx. 30 minutes. The rest of the time the DMLS will be a stowed item, removed from any ignition source. The DMLS has been offgassed at WSTF, ref. Report #90-24546, JSC #9L01, attached.

**Issue (concern domain)**:
> All

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 28 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 2631 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `dpm-0166.pdf` |
| **MUA Number** | DPM 166 |
| **Material (best)** | POLYDIMETHYLSILOXANE 2,5 CS |
| **Material v6** | POLYDIMETHYLSILOXANE 2,5 CS |
| **Material v5** | SILICONE |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | TOXICITY |
| **Issues (cleaned)** | flammability, toxicity |
| **Environment** | 25.9% O2, 18-27° C, 14.5 psi |
| **Determination** | (none) |
| **Confidence** | 0.90 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> (*APPROX. QUANTITY OF VARIOUS VISCOSITIES: 2cs=45 ml, 5cs = 45 ml.) USED AS A WORKING FLUID IN MATERIAL PHYSICS INVESTIGATIONS. IT IS DISPENSED AS 4.6 cm DIAMETER (8 ml) DROPS IN A CLOSED EXPERIMENT APPARATUS. THE DROPS ARE ACOUSTICALLY SUSPENDED, EXAMINED FOR FLUID DYNAMIC OR SURFACE TENSION EFFECTS, AND RETRIEVED, ONE DROP AT A TIME. SEVERAL 4.4 cm DIAMETER DROPS ARE ALSO PLANNED. NO CHEMICAL MIXING OR REACTION IS ANTICIPATED. THIS MATERIAL IS NOT LISTED IN MSFC-HDBK-527.

**Rationale (WHY/HOW)**:
> NOT FLAMMABLE. NO KNOWN CHRONIC ADVERSE HEALTH EFFECTS TO EXPOSURE IN SMALL QUANTITIES (SEE ATTACHED MATERIAL SAFETY DATA SHEETS). ADDITIONAL RATIONALE IS ATTACHED.

**Issue (concern domain)**:
> TOXICITY

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 29 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3010 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `exp-004.pdf` |
| **MUA Number** | EXP-04 |
| **Material (best)** | DP-190 Adhesive |
| **Material v6** | DP-190 Adhesive |
| **Material v5** | NITRILE |
| **Material Family** | adhesive |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | flammability, toxicity |
| **Environment** | (none) |
| **Determination** | APPROVED |
| **Confidence** | 0.60 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> (none)

**Rationale (WHY/HOW)**:
> Flammability - Rated "A" at 25.9%. Toxicity - Rated "A" for toxicity. MUA not required

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 30 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3364 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `gse-1004.pdf` |
| **MUA Number** | GSE1004 |
| **Material (best)** | Aluminum alloys 2017-T4, 2024-T4, 7075-T6 |
| **Material v6** | Aluminum alloys 2017-T4, 2024-T4, 7075-T6 |
| **Material v5** | 2024-T4 |
| **Material Family** | aluminum |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | other |
| **Environment** | Ambient Air |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> Aluminum alloys 2017-T4, 2024-T4 or 7075-T6, are used to fabricate the heads for Quick Release Pins NAS1335A3S14, NAS1337A3S08 and NAS1343A3S34.

**Rationale (WHY/HOW)**:
> Aluminum alloys 2017-T4, 2024-T4 and 7075-T6 are used for fabricating the heads for NAS1333 through 1346 quick release pins. The aluminum head configuration is Type 3 which is depicted on sheet 1 of the NAS Standard Part document (see attachment). The head of the quick release pin provides a mechanism for hand grasping or holding the pin for actuation of the releasing element and in this capacity is subjected to very minimal stress. The major loads experienced are double shear stresses applied t

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 31 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3415 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `hrc-94-016_b.pdf` |
| **MUA Number** | HRC-94-016 |
| **Material (best)** | Pure Molybdenum (99.95% Mo) |
| **Material v6** | Pure Molybdenum (99.95% Mo) |
| **Material v5** | MOS2 |
| **Material Family** | unknown |
| **Category** | I |
| **Issue** | SCC |
| **Issues (cleaned)** | scc |
| **Environment** | Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> The material application is for the fiducial light ring on the HRC AXAF-I assembly. This is a low load application. The primary requirement of the ring component is to serve as a stable base for the fiducial light assembly. The ring material must be non-distorting within operating temperature limits of -15°C to +40°C, at a probable use temperature of approximately 20°C.

**Rationale (WHY/HOW)**:
> Pure Mo possesses a CTE of 2.7/in/in/°F at 20°C - 100°C and a thermal conductivity of 142 W/m.K. These properties meet the requirements of the application. Although MSFC-HDBK-527 Material Selection List for Space Hardware Systems allows the refractory metal molybdenum (Mo), the MSFC-STD-506C Standard-Materials and Process Control requires approval by the NASA procuring activity for refractory metals. This MUA is submitted in light of that requirement.

**Issue (concern domain)**:
> SCC

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 32 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3436 |
| **Sample Bucket** | FLAMM |
| **Source File** | `ibm-sl-006.pdf` |
| **MUA Number** | IBM-SL-006 |
| **Material (best)** | Polyester |
| **Material v6** | Polyester |
| **Material v5** | primer |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | Toxicity Flammability |
| **Issues (cleaned)** | flammability, toxicity |
| **Environment** | 24.5% O2, 75.5% N2, Air to Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> Loctite Grade C thread sealant and Grade T primer are used on screws that do not use self-clinching nuts. Total usage in a subsystem is 146 screws. All but 16 of these screws are subjected to a TE Freon vapor degreasing process after the Loctite is cured.

**Rationale (WHY/HOW)**:
> The material ratings per MSFC-HDBK-527 are as follows: Loctite C - Not Listed U U - -, Loctite T - 61577 U U - -

**Issue (concern domain)**:
> Toxicity Flammability

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 33 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3447 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `ibm-sl-017.pdf` |
| **MUA Number** | IBM-SL-017 |
| **Material (best)** | Epoxy |
| **Material v6** | Epoxy |
| **Material v5** |  |
| **Material Family** | adhesive |
| **Category** | (none) |
| **Issue** | Flammability Toxicity |
| **Issues (cleaned)** | flammability, toxicity |
| **Environment** | HABITABLE: +10°C to +50°C, 24.5% O2, 75.5% N2, 750 TORR, 760 TORR; NONHABITABLE: |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | FLAMM, TOX |

**Application (WHAT)**:
> EA934 is used to bond the aluminum frame to the epoxy/glass printed wiring board on the 130A815-1 subassembly. The aluminum frame has a 0.004 inch think layer of Hysol EA956 for electrical insulation. (See IBM-SL-016)

**Rationale (WHY/HOW)**:
> The material ratings per MSFC-HDBK-527 are as follows: Material Part Material Code Specification ETSC LXCO .00007 X B*- - *The cure used in the toxicity test was 2 hours at 200°F.

**Issue (concern domain)**:
> Flammability Toxicity

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 34 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3506 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `iea-027.pdf` |
| **MUA Number** | IEA-27 |
| **Material (best)** | Adhesive Tape |
| **Material v6** | Adhesive Tape |
| **Material v5** |  |
| **Material Family** | adhesive |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | other |
| **Environment** | Air, Sea Water |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> Application of Press Sensitive Adhesive Tape 3M #467 to Nameplate. Secure name and caution plates to Housing.

**Rationale (WHY/HOW)**:
> Method has been used in previous space applications and has been tested for salt water immersion. No MSFC rating given.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 35 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3610 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `iml-1%20biostack%20cert.pdf` |
| **MUA Number** | 131 |
| **Material (best)** | PTFE |
| **Material v6** |  |
| **Material v5** | PTFE |
| **Category** | I |
| **Issue** | (none) |
| **Environment** | 24.5 % O2 |
| **Determination** | APPROVED |
| **Confidence** | 0.70 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> THIS MUA PROVIDES CERTIFICATION OF THE FOLLOWING HARDWARE PER THE PROVISIONS AND RESTRICTIONS OF NHB 1700.7A

**Rationale (WHY/HOW)**:
> THE CERTIFICATION BASED ON EVALUATION OF FINAL MATERIALS LIST August 2, 1987 DFVLR

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 36 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 3912 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `ius-258.pdf` |
| **MUA Number** | IUS-258 |
| **Material (best)** | PH 13-8 Mo |
| **Material v6** | PH 13-8 Mo |
| **Material v5** | MS 5629 |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | PH 13-8 Mo is on Table II of MSFC-SPEC-522A |
| **Issues (cleaned)** | corrosion, scc |
| **Environment** | LH2 - Ethanol and Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | CORR, SCC |

**Application (WHAT)**:
> Male half of RTG Disconnect Coupling. An MUA is required because PH 13-8 Mo is on Table II of MSFC-SPEC-522A. Use of PH 13-8 Mo is requested so that existing qualified hardware originally developed for Centaur can be used.

**Rationale (WHY/HOW)**:
> Material is heat treated to H 1100 per Mil-H-6875 (150 ksi). The strength and sustained stresses are low enough to preclude the possibility of hydrogen embrittlement or stress corrosion cracking.

**Issue (concern domain)**:
> PH 13-8 Mo is on Table II of MSFC-SPEC-522A

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 37 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4081 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `lif-019.pdf` |
| **MUA Number** | LIF-019 |
| **Material (best)** | TEFLON |
| **Material v6** |  |
| **Material v5** | TEFLON |
| **Category** | I |
| **Issue** | (none) |
| **Environment** | 24.5% O2 |
| **Determination** | APPROVED |
| **Confidence** | 0.70 |
| **Cluster Matches** | TOX |

**Application (WHAT)**:
> Stowage item is used for normal operation and in-flight maintenance.

**Rationale (WHY/HOW)**:
> Note.e1:. Offgassing test data is shown in Verification 4.1.4.1 data

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 38 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4120 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `LMSC-m-022.pdf` |
| **MUA Number** | LMSC/M-022 |
| **Material (best)** | Tin/Brass or Phosphor Bronze |
| **Material v6** | Tin/Brass or Phosphor Bronze |
| **Material v5** | MS35335 |
| **Material Family** | copper_alloy |
| **Category** | I |
| **Issue** | Corrosion |
| **Issues (cleaned)** | corrosion, dissimilar_metals |
| **Environment** | 24.5% Oxy |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR |

**Application (WHAT)**:
> This small metallic lockwasher is used on drawing 5815503. The lockwasher is used to lock a tin/plated brass nut in place. The material in the lockwasher was chosen to avoid a dissimilar metal corrosion situation with the tin plated brass nut.

**Rationale (WHY/HOW)**:
> CORR - No problem - Material specifically chosen to avoid dissimilar metal corrosion problem.

**Issue (concern domain)**:
> Corrosion

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 39 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4163 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `lmsc-m-075.pdf` |
| **MUA Number** | LMSC/M-075 |
| **Material (best)** | Cres 17-4, PH |
| **Material v6** | Cres 17-4, PH |
| **Material v5** |  |
| **Material Family** | stainless_steel |
| **Category** | (none) |
| **Issue** | SCC |
| **Issues (cleaned)** | scc |
| **Environment** | 21% Oxy |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> The CRES 17-4 PH material used for disk, half disk & quarter disk will be in compression load and not immersed in any aqueous solution.

**Rationale (WHY/HOW)**:
> SCC: Since the parts will be under compression loading, no SCC can occur.

**Issue (concern domain)**:
> SCC

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 40 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4215 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `lmsc-n-078.pdf` |
| **MUA Number** | LMSC/N-078 |
| **Material (best)** | Marking ink with Uralane Coating |
| **Material v6** | Marking ink with Uralane Coating |
| **Material v5** | Uralane 5750 |
| **Material Family** | coating |
| **Category** | I |
| **Issue** | FLAM, TOX, TVS |
| **Issues (cleaned)** | tvs, offgassing, flammability, toxicity |
| **Environment** | up to 24.5% Oxy |
| **Determination** | APPROVED |
| **Confidence** | 1.00 |
| **Cluster Matches** | CORR, FLAMM, TOX, TVS |

**Application (WHAT)**:
> The Table I inks are used to make part numbers on assemblies throughout the Starlab payload. The inks are coated with uralane 5050 A/B. MSFC-HDBK-527 lists CAT-L-INK 50-770 as untested (material code no. 61007) and CAT-L-INK 50-100 with a "B" rating for toxicity when cured for 7D-RT/24H-150F Material code 05231. This ink is untested for flammability and outgassing. CAT-L-INK 50-771 is not listed in MSFC-HDBK-527.

**Rationale (WHY/HOW)**:
> Toxicity and TVS: The above inks will be applied with catalyst 9 and cured for 24H at 150°F. Then, they will be coated with Uralane 5750 A/B as per LAC 40-4647 (cured for 9h at 150°F) to prevent outgasing and offgassing. Uralane coating 5750 A/B is listed in MSFC-HDBK-527 with a material code No. 20209. It is rated "B" for TVS and toxicity when cured for 9H at 149°F. Therefore, the ink-coating combination meets the requirements for toxicity and outgassing.

Flammability: The ink-coating combinat

**Issue (concern domain)**:
> FLAM, TOX, TVS

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 41 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4439 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `ls-tk-003.pdf` |
| **MUA Number** | LS-TK-003 |
| **Material (best)** | NF-2000 polycarbonate |
| **Material v6** | NF-2000 polycarbonate |
| **Material v5** | TEFLON |
| **Material Family** | polymer |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | other |
| **Environment** | buffer solution (95% water) |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> This MUA is for the NASDA Life Sciences experiments to be flown on the IML-2 Mission. This MUA is for an Interface Connector (fluid) which is part of the Transfer Kit. The Interface Connector is stowed in the Transfer Kit (AI 5056) which is stowed in the Rack Stowage Container. The Interface Connector housing is made of NF-2000 polycarbonate. The adapter, plug, needle, and screws are made of Cres 304. The septums and o-rings are made of viton and the packing is made of silicone rubber. The fluid

**Rationale (WHY/HOW)**:
> This MUA is for the NASDA Life Sciences experiments to be flown on the IML-2 Mission. This MUA is for an Interface Connector (fluid) which is part of the Transfer Kit. The Interface Connector is stowed in the Transfer Kit (AI 5056) which is stowed in the Rack Stowage Container. The Interface Connector housing is made of NF-2000 polycarbonate. The adapter, plug, needle, and screws are made of Cres 304. The septums and o-rings are made of viton and the packing is made of silicone rubber. The fluid

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 42 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4506 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `MAS-055.pdf` |
| **MUA Number** | MAS-055 |
| **Material (best)** | Epoxy Adhesive |
| **Material v6** | Epoxy Adhesive |
| **Material v5** |  |
| **Material Family** | adhesive |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | offgassing, flammability |
| **Environment** | (none) |
| **Determination** | (none) |
| **Confidence** | 0.70 |
| **Cluster Matches** | FLAMM, TVS |

**Application (WHAT)**:
> Bonding of THREE THERMISTORS of the ANTENNA, COVERED WITH VCM : 0.06%

**Rationale (WHY/HOW)**:
> 1) Amount used = 1.5g approx
;1) No ignition sources for FLAMMABILITY
AMOUNT of outgassing WILL OCCUR
SMALL AMOUNT of MATERIAL EDGE

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 43 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4612 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `mdssc0191.pdf` |
| **MUA Number** | 1007-0079 |
| **Material (best)** | SUPERIOR 48 |
| **Material v6** | SUPERIOR 48 |
| **Material v5** |  |
| **Material Family** | unknown |
| **Category** | II |
| **Issue** | (none) |
| **Issues (cleaned)** | corrosion, workmanship |
| **Environment** | Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 0.90 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> In accordance with NHB 5300.4 (3A-1), section 3A900, usage of an organic flux shall be approved by the NASA procuring installation. This MUA addresses the usage of Superior 48, an organic acid flux used to enhance the solderability of the High Rate Frame Multiplexer motherboard to the bus bars. Due to the age of the hardware and the number of times it has been processed, intermetallics have become exposed and oxidized rendering the material unsolderablе with conventional fluxes. Small amounts of

**Rationale (WHY/HOW)**:
> Due to the age of the hardware and the number of times it has been processed, intermetallics have become exposed and oxidized rendering the material unsolderablе with conventional fluxes. Small amounts of Superior 48 organic acid flux is applied to the topside of the affected solder connection.

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 44 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4734 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `mgm-015.pdf` |
| **MUA Number** | MGM-015 |
| **Material (best)** | TEFLON |
| **Material v6** | Several |
| **Material v5** | TEFLON |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | Toxicity / Flammability |
| **Issues (cleaned)** | workmanship, offgassing, flammability, toxicity |
| **Environment** | PRESSURE 14.7 psia, TEMPERATURE 65-80 deg F, MEDIA 25.9% O2 |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | CORR, FLAMM, TOX |

**Application (WHAT)**:
> During final assembly of the MGM flight hardware, small amounts of adhesives and epoxies are used to attach small aluminum brackets and cable tiedown blocks. Small amounts of adhesives, epoxies, and conformal coating are used to stake screws. In addition, thread sealant is used on fluid system threaded fittings. Also, thread-locking fluid is used on threaded fasteners which do not have corresponding locking inserts.

**Rationale (WHY/HOW)**:
> Toxicity: The entire flight hardware assembly has been offgas tested at the MGM system level.

Flammability: All of the items specified above are used in small and widely-separated amounts during final assembly of the flight hardware, and are heat-sinked by the surfaces to which they are applied. There are no sources of ignition or flame propagation paths to those items.

**Issue (concern domain)**:
> Toxicity / Flammability

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 45 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4844 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `mmd-010.pdf` |
| **MUA Number** | MMD-010-DSS |
| **Material (best)** | 4340 steel (body), 440 C CRES (ball), 17-4PH CRES (race), TFE teflon (liner) |
| **Material v6** | 4340 steel (body), 440 C CRES (ball), 17-4PH CRES (race), TFE teflon (liner) |
| **Material v5** | 17-4PH |
| **Material Family** | stainless_steel |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | workmanship |
| **Environment** | Air |
| **Determination** | APPROVED |
| **Confidence** | 0.80 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> This MS21242S07-L rod end bearing is used in the main parachute support strut assembly to take care of any misalignment between the aft isogrid lug and the frustum mounting bracket. It is requested that this rod end bearing be approved for use and added to the 80000 Material Code (standard parts) of the SE019-094-2H Materials Selection List.

**Rationale (WHY/HOW)**:
> This part will not be refurbished but will be replaced after each flight. The part is finished with an epoxy primer/topcoat system in accordance with STP30143 and is to be sealed with PR 1422 polysulfide sealant during final assembly. This bearing is composed of four parts, 1) the body, 2) the ball, 3) the race and 4) the liner. The body is 4340 steel in accordance with MIL-S-5000 heat treated to RC 39-42 and cadmium plated per QQ-P-416; Type I, Class 2. It is embrittlement relieved after platin

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 46 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 4970 |
| **Sample Bucket** | FLAMM |
| **Source File** | `mpe-017.pdf` |
| **MUA Number** | MPE-017 |
| **Material (best)** | (no material) |
| **Material v6** |  |
| **Material v5** |  |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | Water |
| **Determination** | APPROVED |
| **Confidence** | 0.65 |
| **Cluster Matches** | CORR, FLAMM, SCC, TVS |

**Application (WHAT)**:
> This is primarily metallic tubing and fittings which will be mounted inside the Spacelab module. It will be attached under the floor and provide cooling water to the "MSDR" Expr. in Rack 8. This hardware is MPE.

**Rationale (WHY/HOW)**:
> The materials used to construct this hardware as defined on the drawings meet the requirements of JSC-SE-R-006A, JSC-SP-R-0022 and MSFC-SPEC-522A for flammability, stress corrosion and thermal vacuum stability. These materials also meet the safety requirements of NHP, 1700.7A, section 7.10.8 of the SPAH and para.'s 4.1.4.2, 4.1.4.3, 4.1.4.8 and 4.1.4.4 of JA-061. NOTE: Above hardware is in-house designed and all drawings are signed Material and Processes Laboratory, Materials Selection & Control

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 47 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 5429 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `omv-029.pdf` |
| **MUA Number** | OMV.MUA-029 |
| **Material (best)** | C15-015 |
| **Material v6** | C15-015 |
| **Material v5** | TEFLON |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | (none) |
| **Issues (cleaned)** | offgassing, flammability |
| **Environment** | Space Vacuum |
| **Determination** | APPROVED |
| **Confidence** | 0.85 |
| **Cluster Matches** | CORR, FLAMM, TVS |

**Application (WHAT)**:
> Epoxy resin system used for inhouse fabrication of inductors and transformers in accordance with details of part specifications. The impregnant is applied and cured per PR4-16.

**Rationale (WHY/HOW)**:
> The material is rated B and A for outgassing and flammability, respectively, per MSFC-HDBK-527. However, outgassing test performed by TRW shows that it meets the project outgassing requirement: TWL = 0.54%, CVCM = 0.09% (Ref. TRW Test #925, R211-87-0360). The magnetics are utilized within electronic boxes and are coated with Solithane 113 conformal coating which is rated A for outgassing per MSFC-HDBK-527 (05164).

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 48 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 5531 |
| **Sample Bucket** | LONG_TAIL |
| **Source File** | `opm-054.pdf` |
| **MUA Number** | OPM-054 |
| **Material (best)** | Nomex/Volara Foam |
| **Material v6** | Nomex/Volara Foam |
| **Material v5** | SS302 |
| **Material Family** | unknown |
| **Category** | I |
| **Issue** | FLAM, TOX, TVS |
| **Issues (cleaned)** | tvs, offgassing, flammability, toxicity |
| **Environment** | (none) |
| **Determination** | APPROVED |
| **Confidence** | 0.95 |
| **Cluster Matches** | FLAMM, TOX, TVS |

**Application (WHAT)**:
> This material is used to cover OPM and to protect OPM from damage in transit and movement within the spacecraft. It will be removed before OPM is placed in airlock to be EVAed. See attached data sheets.

**Rationale (WHY/HOW)**:
> This material has been tested at NASA/MSFC for flammability and is rated 'A' @ 40% oxygen, 5.6 psi and @ 30.3% oxygen, 9.3 psi. The Volara foam is rated 'II' for toxicity; maximum usage = 99.99 lb.; actual usage = 2.21 lbs. The Nomex thread is rated 'V' for toxicity; maximum usage = 9.99 lb.; actual usage = less than 1 lb. OPM will be toxicity tested prior to acceptance. This test consists of a three-day bakeout at 120°F and will alleviate the toxicity issue. OPM will be thermal vacuum baked pri

**Issue (concern domain)**:
> FLAM, TOX, TVS

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 49 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 5600 |
| **Sample Bucket** | NO_CLUSTER |
| **Source File** | `ota-004.pdf` |
| **MUA Number** | 4, 5, 6, 7, 8, and 9 |
| **Material (best)** | (no material) |
| **Material v6** |  |
| **Material v5** |  |
| **Category** | (none) |
| **Issue** | (none) |
| **Environment** | below 50% R.H. or in high vacuum |
| **Determination** | APPROVED |
| **Confidence** | 0.45 |
| **Cluster Matches** | NONE |

**Application (WHAT)**:
> (none)

**Rationale (WHY/HOW)**:
> Perkin-Elmer's policy is to maintain all its assembly and storage areas below 50% humidity for the OTA as well as other high reliability programs (Reference 2, 3). For all operations after OTA delivery, which include shipment from P-E, integration into the SSM, and ST preparation for launch, P-E is establishing requirements to maintain a less than 50% R.H. environment for the OTA. Since P-E has met the intent of MSFC's request, and since MSFC has not placed the requirement for written certificat

**Issue (concern domain)**:
> (none)

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

### Record 50 of 50

| Field | Value |
|-------|-------|
| **Record Index** | 6205 |
| **Sample Bucket** | TOP_MATERIAL |
| **Source File** | `pmic-ir36-206.pdf` |
| **MUA Number** | PMIC-IR36-0206 |
| **Material (best)** | AL6061 |
| **Material v6** | See Attached |
| **Material v5** | AL6061 |
| **Material Family** | unknown |
| **Category** | (none) |
| **Issue** | Flammability, Toxicity Stress Corrosion |
| **Issues (cleaned)** | corrosion, flammability, scc, toxicity |
| **Environment** | 24.5%O2 |
| **Determination** | (none) |
| **Confidence** | 0.85 |
| **Cluster Matches** | CORR, FLAMM, SCC, TOX |

**Application (WHAT)**:
> This is a component MUA for SL-J Mission Peculiar Equipment. The applications of materials covered under this MUA are given in the attached pages.

**Rationale (WHY/HOW)**:
> Flammability and Stress Corrosion use rationale for materials covered under this component MUA is given on the attached pages.

**Issue (concern domain)**:
> Flammability, Toxicity Stress Corrosion

**Manual Audit Tags**:
- WHAT: ___
- WHY: ___
- HOW: ___
- QUALITY: ___

---

