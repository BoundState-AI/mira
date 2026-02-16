# MUA Extraction Profile Report (Clean Merged Data)

Generated: 2026-02-15 11:09

**Source**: `mua_v6_parsed_results.jsonl` filtered + merged with v5 material backfill

## Data Pipeline

```
v6_parsed raw:       13,786 records
Ghost records:       -6,440 (success=True but all fields empty)
Clean records:       7,346
v5 material backfill: +657 material names recovered
v6_cleaned backfill:  +1 material names recovered
v6_cleaned families:  +6,377 material_family tags added
```

## Summary

| Metric | Value |
|--------|-------|
| Total clean records | 7,346 |
| Ghosts removed | 6,440 |
| Distinct materials | 4,962 |
| Material coverage | 7,206 / 7,346 (98.1%) |
| Still missing material | 140 (1.9%) |
| Distinct source PDFs | 7,338 |
| Avg confidence | 0.86 |

## Material Frequency (best available name)

Uses v6 designation when available, v5 name as fallback.

### Top 40 Materials

| Rank | Material | Count | % |
|------|----------|-------|---|
| 1 | TEFLON | 166 | 2.3% |
| 2 | (no material) | 140 | 1.9% |
| 3 | PTFE | 66 | 0.9% |
| 4 | 316 SS | 66 | 0.9% |
| 5 | SILICONE | 56 | 0.8% |
| 6 | Epoxy | 42 | 0.6% |
| 7 | 17-4PH | 36 | 0.5% |
| 8 | Silicone Rubber | 32 | 0.4% |
| 9 | Epoxy Adhesive | 29 | 0.4% |
| 10 | Nitronic 60 | 28 | 0.4% |
| 11 | AL6061 | 27 | 0.4% |
| 12 | Nylon | 26 | 0.4% |
| 13 | Polyurethane | 24 | 0.3% |
| 14 | KYNAR fluoroplastic | 22 | 0.3% |
| 15 | Brass | 21 | 0.3% |
| 16 | Polyolefin | 19 | 0.3% |
| 17 | 17-4 PH CRES | 19 | 0.3% |
| 18 | EPOXY | 19 | 0.3% |
| 19 | CRES 416 | 19 | 0.3% |
| 20 | CRES 410 OR 416 | 19 | 0.3% |
| 21 | ETFE | 18 | 0.2% |
| 22 | Adhesive | 18 | 0.2% |
| 23 | Solid Film Lubricant | 18 | 0.2% |
| 24 | CRES 440C | 16 | 0.2% |
| 25 | SILICONE RUBBER | 16 | 0.2% |
| 26 | NITRONIC 60 | 16 | 0.2% |
| 27 | CRES 410 | 15 | 0.2% |
| 28 | AL2024 | 14 | 0.2% |
| 29 | Neoprene | 14 | 0.2% |
| 30 | 440C | 14 | 0.2% |
| 31 | Polyethylene | 13 | 0.2% |
| 32 | BRASS | 13 | 0.2% |
| 33 | NYLON | 13 | 0.2% |
| 34 | Kapton | 12 | 0.2% |
| 35 | Delrin | 12 | 0.2% |
| 36 | Inconel 718 | 12 | 0.2% |
| 37 | Silicone | 12 | 0.2% |
| 38 | ADHESIVE | 12 | 0.2% |
| 39 | EPOXY ADHESIVE | 12 | 0.2% |
| 40 | 17-4 PH | 12 | 0.2% |

### Material Frequency Distribution

| Frequency | # Materials | % of distinct |
|-----------|------------|---------------|
| Appears once | 4323 | 87.1% |
| 2-3 times | 468 | 9.4% |
| 4-10 times | 120 | 2.4% |
| >10 times | 51 | 1.0% |

## Material Family Distribution

From v6_cleaned enrichment (not all records have this).

| Family | Count | % |
|--------|-------|---|
| unknown | 2,697 | 36.7% |
| (none) | 969 | 13.2% |
| stainless_steel | 749 | 10.2% |
| adhesive | 547 | 7.4% |
| polymer | 536 | 7.3% |
| elastomer | 483 | 6.6% |
| aluminum | 462 | 6.3% |
| coating | 230 | 3.1% |
| copper_alloy | 227 | 3.1% |
| lubricant | 121 | 1.6% |
| nickel_alloy | 99 | 1.3% |
| ceramic | 84 | 1.1% |
| carbon_steel | 71 | 1.0% |
| sealant | 43 | 0.6% |
| titanium | 18 | 0.2% |
| composite | 10 | 0.1% |

## Concern Domain Keyword Clusters

| Cluster | Keywords (sample) | Records | % |
|---------|-------------------|---------|---|
| FLAMM | flammability, flammable, ignition, combustion | 2,712 | 36.9% |
| SCC | stress corrosion, cracking, msfc-std-3029, sustained load | 896 | 12.2% |
| CORR | corrosion, galvanic, plating, coating | 1,708 | 23.3% |
| TOX | toxicity, offgassing, offgas, test 7 | 1,278 | 17.4% |
| FC | fracture, fatigue, crack growth, safe life | 54 | 0.7% |
| TVS | thermal vacuum, outgassing, tml, cvcm | 952 | 13.0% |
| NONE | (no cluster match) | 2,703 | 36.8% |

### Multi-Cluster Records

| # Clusters | Records | % |
|-----------|---------|---|
| 0 | 2,703 | 36.8% |
| 1 | 2,326 | 31.7% |
| 2 | 1,848 | 25.2% |
| 3 | 327 | 4.5% |
| 4 | 113 | 1.5% |
| 5 | 29 | 0.4% |

## Source File Distribution

- **Distinct source PDFs**: 7,338
- **Extractions per source**: avg=1.0, max=2
- **Sources with >1 extraction**: 8

### Top 20 Source Files

| Source PDF | Extractions |
|-----------|------------|
| feu-036.pdf | 2 |
| feu-037.pdf | 2 |
| feu-038.pdf | 2 |
| feu-039.pdf | 2 |
| feu-040.pdf | 2 |
| feu-041.pdf | 2 |
| 1001-2346.pdf | 2 |
| 1011-0016.pdf | 2 |
| 1000-0003.pdf | 1 |
| 1000-0005.pdf | 1 |
| 1000-0006.pdf | 1 |
| 1000-0009.pdf | 1 |
| 1000-0011.pdf | 1 |
| 1000-0012.pdf | 1 |
| 1000-0013.pdf | 1 |
| 1000-0014.pdf | 1 |
| 1001-0002.pdf | 1 |
| 1001-0003.pdf | 1 |
| 1001-0004.pdf | 1 |
| 1001-0005.pdf | 1 |

## Text Field Lengths

| Field | N | Avg | Median | P10 | P90 | Min | Max |
|-------|---|-----|--------|-----|-----|-----|-----|
| rationale | 7,026 | 280 | 262 | 78 | 500 | 1 | 500 |
| application | 7,098 | 217 | 173 | 46 | 500 | 1 | 500 |
| issue | 4,825 | 31 | 17 | 4 | 74 | 1 | 200 |

Rationale texts are **full paragraphs** (avg > 200 chars).
Application texts are **full paragraphs**.

## Category Distribution

| Category | Count | % |
|----------|-------|---|
| (none) | 5,200 | 70.8% |
| I | 1,650 | 22.5% |
| II | 415 | 5.6% |
| III | 81 | 1.1% |

## Determination Distribution

| Determination | Count | % |
|---------------|-------|---|
| APPROVED | 5,784 | 78.7% |
| (none) | 1,224 | 16.7% |
| DEFERRED | 144 | 2.0% |
| APPROVED_WITH_LIMITS | 140 | 1.9% |
| REJECTED | 47 | 0.6% |
| CANCELLED | 3 | 0.0% |
| ACCEPTED | 2 | 0.0% |
| DEFER | 1 | 0.0% |
| Acceptable | 1 | 0.0% |

## Environment Distribution

| Environment | Count | % |
|-------------|-------|---|
| (none) | 1,130 | 15.4% |
| Vacuum | 385 | 5.2% |
| Air | 311 | 4.2% |
| vacuum | 180 | 2.5% |
| 24.5% O2 | 173 | 2.4% |
| 21% O2 | 137 | 1.9% |
| AIR | 120 | 1.6% |
| Space | 109 | 1.5% |
| VACUUM | 94 | 1.3% |
| Air to Vacuum | 91 | 1.2% |
| 30% O2 | 71 | 1.0% |
| air | 70 | 1.0% |
| Vac/Air | 67 | 0.9% |
| O2 | 59 | 0.8% |
| SPACE | 52 | 0.7% |

## Extraction Mode

| Mode | Count | % |
|------|-------|---|
| vision | 7,346 | 100.0% |

## Confidence Distribution

| Range | Count | % |
|-------|-------|---|
| 0.0-0.2 | 24 | 0.3% |
| 0.2-0.4 | 241 | 3.3% |
| 0.4-0.6 | 234 | 3.2% |
| 0.6-0.8 | 925 | 12.6% |
| 0.8-1.0 | 5,922 | 80.6% |

