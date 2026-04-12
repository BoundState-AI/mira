#!/usr/bin/env python3
"""
Module: MUA v7 Material Database
Purpose: Curated lookup tables for aerospace material designation resolution.

BoundState AI 2026
Version: 7.0.0
Classification: BoundState Proprietary

Co-Authored-By: Atlas (OpenAI GPT-5) <noreply@openai.com>
Co-Authored-By: Claude "Atlas" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032
Safety Critical: True

Contains the curated MATERIAL_DATABASE (canonical designation -> MAPTIS code)
and _ALIASES (common variant names -> canonical keys). Extracted from
material_resolver.py to separate data from resolution logic.

The database corrects the v6 regex-based approach which treated
2024-T4 and 2014 as equivalent. Each entry is keyed on the
UPPER-CASED canonical designation for exact match after normalization.

WHY curated lookup vs DB query:
- MAPTIS has ~35K materials but many are duplicates/variants
- The MUA wizard needs fast, offline-capable resolution
- Curated entries guarantee correct material_code linkage
- Live MAPTIS fallback handles anything not in the lookup table
"""

from .models import MaterialClass

MATERIAL_DATABASE: dict[str, dict] = {
    # ------------------------------------------------------------------
    # Aluminum alloys
    # ------------------------------------------------------------------
    "1100": {
        "canonical_name": "Aluminum 1100",
        "material_code": "MAT-A00101",
        "material_class": MaterialClass.METAL,
        "family": "Al-1xxx",
        "is_process_sensitive": False,
    },
    "2014-T6": {
        "canonical_name": "Aluminum 2014-T6",
        "material_code": "MAT-A00201",
        "material_class": MaterialClass.METAL,
        "family": "Al-2014",
        "is_process_sensitive": False,
    },
    "2024-T3": {
        "canonical_name": "Aluminum 2024-T3",
        "material_code": "MAT-A00210",
        "material_class": MaterialClass.METAL,
        "family": "Al-2024",
        "is_process_sensitive": False,
    },
    "2024-T4": {
        "canonical_name": "Aluminum 2024-T4",
        "material_code": "MAT-A00211",
        "material_class": MaterialClass.METAL,
        "family": "Al-2024",
        "is_process_sensitive": False,
    },
    "2024-T351": {
        "canonical_name": "Aluminum 2024-T351",
        "material_code": "MAT-A00212",
        "material_class": MaterialClass.METAL,
        "family": "Al-2024",
        "is_process_sensitive": False,
    },
    "2219-T87": {
        "canonical_name": "Aluminum 2219-T87",
        "material_code": "MAT-A00220",
        "material_class": MaterialClass.METAL,
        "family": "Al-2219",
        "is_process_sensitive": False,
    },
    "5052-H34": {
        "canonical_name": "Aluminum 5052-H34",
        "material_code": "MAT-A00501",
        "material_class": MaterialClass.METAL,
        "family": "Al-5052",
        "is_process_sensitive": False,
    },
    "6061-T6": {
        "canonical_name": "Aluminum 6061-T6",
        "material_code": "MAT-A00601",
        "material_class": MaterialClass.METAL,
        "family": "Al-6061",
        "is_process_sensitive": False,
    },
    "6061-T651": {
        "canonical_name": "Aluminum 6061-T651",
        "material_code": "MAT-A00602",
        "material_class": MaterialClass.METAL,
        "family": "Al-6061",
        "is_process_sensitive": False,
    },
    "7050-T7451": {
        "canonical_name": "Aluminum 7050-T7451",
        "material_code": "MAT-A00701",
        "material_class": MaterialClass.METAL,
        "family": "Al-7050",
        "is_process_sensitive": False,
    },
    "7075-T6": {
        "canonical_name": "Aluminum 7075-T6",
        "material_code": "MAT-A00710",
        "material_class": MaterialClass.METAL,
        "family": "Al-7075",
        "is_process_sensitive": False,
    },
    "7075-T73": {
        "canonical_name": "Aluminum 7075-T73",
        "material_code": "MAT-A00711",
        "material_class": MaterialClass.METAL,
        "family": "Al-7075",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Stainless steels
    # ------------------------------------------------------------------
    "17-4 PH": {
        "canonical_name": "Stainless Steel 17-4 PH",
        "material_code": "MAT-S01740",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-17-4PH",
        "is_process_sensitive": False,
    },
    "17-7 PH": {
        "canonical_name": "Stainless Steel 17-7 PH",
        "material_code": "MAT-S01770",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-17-7PH",
        "is_process_sensitive": False,
    },
    "21-6-9": {
        "canonical_name": "Stainless Steel 21-6-9",
        "material_code": "MAT-S02169",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-21-6-9",
        "is_process_sensitive": False,
    },
    "301": {
        "canonical_name": "Stainless Steel 301",
        "material_code": "MAT-S00301",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-301",
        "is_process_sensitive": False,
    },
    "302": {
        "canonical_name": "Stainless Steel 302",
        "material_code": "MAT-S00302",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-302",
        "is_process_sensitive": False,
    },
    "303": {
        "canonical_name": "Stainless Steel 303",
        "material_code": "MAT-S00303",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-303",
        "is_process_sensitive": False,
    },
    "304": {
        "canonical_name": "Stainless Steel 304",
        "material_code": "MAT-S00304",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-304",
        "is_process_sensitive": False,
    },
    "304L": {
        "canonical_name": "Stainless Steel 304L",
        "material_code": "MAT-S00305",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-304",
        "is_process_sensitive": False,
    },
    "316": {
        "canonical_name": "Stainless Steel 316",
        "material_code": "MAT-S00316",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-316",
        "is_process_sensitive": False,
    },
    "316L": {
        "canonical_name": "Stainless Steel 316L",
        "material_code": "MAT-S00317",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-316",
        "is_process_sensitive": False,
    },
    "321": {
        "canonical_name": "Stainless Steel 321",
        "material_code": "MAT-S00321",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-321",
        "is_process_sensitive": False,
    },
    "347": {
        "canonical_name": "Stainless Steel 347",
        "material_code": "MAT-S00347",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-347",
        "is_process_sensitive": False,
    },
    "410": {
        "canonical_name": "Stainless Steel 410",
        "material_code": "MAT-S00410",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-410",
        "is_process_sensitive": False,
    },
    "416": {
        "canonical_name": "Stainless Steel 416",
        "material_code": "MAT-S00416",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-416",
        "is_process_sensitive": False,
    },
    "430": {
        "canonical_name": "Stainless Steel 430",
        "material_code": "MAT-S00430",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-430",
        "is_process_sensitive": False,
    },
    "440C": {
        "canonical_name": "Stainless Steel 440C",
        "material_code": "MAT-S00440",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-440C",
        "is_process_sensitive": False,
    },
    "455 CUSTOM": {
        "canonical_name": "Custom 455 Stainless Steel",
        "material_code": "MAT-S00455",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-Custom455",
        "is_process_sensitive": False,
    },
    "A-286": {
        "canonical_name": "A-286 Iron-Based Superalloy",
        "material_code": "MAT-S00286",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-A286",
        "is_process_sensitive": False,
    },
    "AM350": {
        "canonical_name": "AM350 Stainless Steel",
        "material_code": "MAT-S00350",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-AM350",
        "is_process_sensitive": False,
    },
    "PH 13-8MO": {
        "canonical_name": "PH 13-8Mo Stainless Steel",
        "material_code": "MAT-S01380",
        "material_class": MaterialClass.ALLOY,
        "family": "SS-PH13-8Mo",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Nickel alloys
    # ------------------------------------------------------------------
    "INCONEL 600": {
        "canonical_name": "Inconel 600",
        "material_code": "MAT-N00600",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Inconel600",
        "is_process_sensitive": False,
    },
    "INCONEL 617": {
        "canonical_name": "Inconel 617",
        "material_code": "MAT-N00617",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Inconel617",
        "is_process_sensitive": False,
    },
    "INCONEL 625": {
        "canonical_name": "Inconel 625",
        "material_code": "MAT-N00625",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Inconel625",
        "is_process_sensitive": False,
    },
    "INCONEL 706": {
        "canonical_name": "Inconel 706",
        "material_code": "MAT-N00706",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Inconel706",
        "is_process_sensitive": False,
    },
    "INCONEL 718": {
        "canonical_name": "Inconel 718",
        "material_code": "MAT-N00718",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Inconel718",
        "is_process_sensitive": False,
    },
    "INCONEL X-750": {
        "canonical_name": "Inconel X-750",
        "material_code": "MAT-N00750",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-InconelX750",
        "is_process_sensitive": False,
    },
    "HASTELLOY C-276": {
        "canonical_name": "Hastelloy C-276",
        "material_code": "MAT-N01276",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-HastelloyC276",
        "is_process_sensitive": False,
    },
    "HASTELLOY X": {
        "canonical_name": "Hastelloy X",
        "material_code": "MAT-N01300",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-HastelloyX",
        "is_process_sensitive": False,
    },
    "MONEL 400": {
        "canonical_name": "Monel 400",
        "material_code": "MAT-N02400",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Monel400",
        "is_process_sensitive": False,
    },
    "MONEL K-500": {
        "canonical_name": "Monel K-500",
        "material_code": "MAT-N02500",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-MonelK500",
        "is_process_sensitive": False,
    },
    "WASPALOY": {
        "canonical_name": "Waspaloy",
        "material_code": "MAT-N03001",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Waspaloy",
        "is_process_sensitive": False,
    },
    "RENE 41": {
        "canonical_name": "Rene 41",
        "material_code": "MAT-N03041",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Rene41",
        "is_process_sensitive": False,
    },
    "HAYNES 230": {
        "canonical_name": "Haynes 230",
        "material_code": "MAT-N03230",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Haynes230",
        "is_process_sensitive": False,
    },
    "HAYNES 188": {
        "canonical_name": "Haynes 188",
        "material_code": "MAT-N03188",
        "material_class": MaterialClass.ALLOY,
        "family": "Ni-Haynes188",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Titanium alloys
    # ------------------------------------------------------------------
    "CP TI GRADE 2": {
        "canonical_name": "Commercially Pure Titanium Grade 2",
        "material_code": "MAT-T00002",
        "material_class": MaterialClass.METAL,
        "family": "Ti-CP",
        "is_process_sensitive": False,
    },
    "CP TI GRADE 4": {
        "canonical_name": "Commercially Pure Titanium Grade 4",
        "material_code": "MAT-T00004",
        "material_class": MaterialClass.METAL,
        "family": "Ti-CP",
        "is_process_sensitive": False,
    },
    "TI-6AL-4V": {
        "canonical_name": "Ti-6Al-4V",
        "material_code": "MAT-T00640",
        "material_class": MaterialClass.METAL,
        "family": "Ti-6Al-4V",
        "is_process_sensitive": False,
    },
    "TI-6AL-4V ELI": {
        "canonical_name": "Ti-6Al-4V ELI",
        "material_code": "MAT-T00641",
        "material_class": MaterialClass.METAL,
        "family": "Ti-6Al-4V",
        "is_process_sensitive": False,
    },
    "TI-3AL-2.5V": {
        "canonical_name": "Ti-3Al-2.5V",
        "material_code": "MAT-T00325",
        "material_class": MaterialClass.METAL,
        "family": "Ti-3Al-2.5V",
        "is_process_sensitive": False,
    },
    "TI-5AL-2.5SN": {
        "canonical_name": "Ti-5Al-2.5Sn",
        "material_code": "MAT-T00525",
        "material_class": MaterialClass.METAL,
        "family": "Ti-5Al-2.5Sn",
        "is_process_sensitive": False,
    },
    "TI-6AL-2SN-4ZR-2MO": {
        "canonical_name": "Ti-6Al-2Sn-4Zr-2Mo",
        "material_code": "MAT-T00642",
        "material_class": MaterialClass.METAL,
        "family": "Ti-6Al-2Sn-4Zr-2Mo",
        "is_process_sensitive": False,
    },
    "TI-15V-3CR-3AL-3SN": {
        "canonical_name": "Ti-15V-3Cr-3Al-3Sn",
        "material_code": "MAT-T01533",
        "material_class": MaterialClass.METAL,
        "family": "Ti-15V-3Cr-3Al-3Sn",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Copper alloys
    # ------------------------------------------------------------------
    "OFHC COPPER": {
        "canonical_name": "OFHC Copper (C10200)",
        "material_code": "MAT-C00102",
        "material_class": MaterialClass.METAL,
        "family": "Cu-OFHC",
        "is_process_sensitive": False,
    },
    "C17200": {
        "canonical_name": "C17200 Beryllium Copper",
        "material_code": "MAT-C00172",
        "material_class": MaterialClass.METAL,
        "family": "Cu-BeCu",
        "is_process_sensitive": False,
    },
    "BECU": {
        "canonical_name": "C17200 Beryllium Copper",
        "material_code": "MAT-C00172",
        "material_class": MaterialClass.METAL,
        "family": "Cu-BeCu",
        "is_process_sensitive": False,
    },
    "C17500": {
        "canonical_name": "C17500 Beryllium Copper",
        "material_code": "MAT-C00175",
        "material_class": MaterialClass.METAL,
        "family": "Cu-BeCu",
        "is_process_sensitive": False,
    },
    "GRCOP-42": {
        "canonical_name": "GRCop-42",
        "material_code": "MAT-C01042",
        "material_class": MaterialClass.METAL,
        "family": "Cu-GRCop",
        "is_process_sensitive": False,
    },
    "GRCOP-84": {
        "canonical_name": "GRCop-84",
        "material_code": "MAT-C01084",
        "material_class": MaterialClass.METAL,
        "family": "Cu-GRCop",
        "is_process_sensitive": False,
    },
    "NARLOY-Z": {
        "canonical_name": "NARloy-Z",
        "material_code": "MAT-C02001",
        "material_class": MaterialClass.METAL,
        "family": "Cu-NARloy",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Cobalt alloys
    # ------------------------------------------------------------------
    "L-605": {
        "canonical_name": "L-605 (Haynes 25)",
        "material_code": "MAT-K00605",
        "material_class": MaterialClass.ALLOY,
        "family": "Co-L605",
        "is_process_sensitive": False,
    },
    "HAYNES 25": {
        "canonical_name": "L-605 (Haynes 25)",
        "material_code": "MAT-K00605",
        "material_class": MaterialClass.ALLOY,
        "family": "Co-L605",
        "is_process_sensitive": False,
    },
    "STELLITE 6B": {
        "canonical_name": "Stellite 6B",
        "material_code": "MAT-K00606",
        "material_class": MaterialClass.ALLOY,
        "family": "Co-Stellite6B",
        "is_process_sensitive": False,
    },
    "MP35N": {
        "canonical_name": "MP35N",
        "material_code": "MAT-K00350",
        "material_class": MaterialClass.ALLOY,
        "family": "Co-MP35N",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Refractory metals
    # ------------------------------------------------------------------
    "MOLYBDENUM TZM": {
        "canonical_name": "Molybdenum TZM",
        "material_code": "MAT-R00421",
        "material_class": MaterialClass.METAL,
        "family": "Ref-MoTZM",
        "is_process_sensitive": False,
    },
    "TZM": {
        "canonical_name": "Molybdenum TZM",
        "material_code": "MAT-R00421",
        "material_class": MaterialClass.METAL,
        "family": "Ref-MoTZM",
        "is_process_sensitive": False,
    },
    "TUNGSTEN": {
        "canonical_name": "Tungsten (Unalloyed)",
        "material_code": "MAT-R00500",
        "material_class": MaterialClass.METAL,
        "family": "Ref-W",
        "is_process_sensitive": False,
    },
    "NIOBIUM C-103": {
        "canonical_name": "Niobium C-103",
        "material_code": "MAT-R00103",
        "material_class": MaterialClass.METAL,
        "family": "Ref-NbC103",
        "is_process_sensitive": False,
    },
    "C-103": {
        "canonical_name": "Niobium C-103",
        "material_code": "MAT-R00103",
        "material_class": MaterialClass.METAL,
        "family": "Ref-NbC103",
        "is_process_sensitive": False,
    },
    "TANTALUM": {
        "canonical_name": "Tantalum (Unalloyed)",
        "material_code": "MAT-R00600",
        "material_class": MaterialClass.METAL,
        "family": "Ref-Ta",
        "is_process_sensitive": False,
    },

    # ------------------------------------------------------------------
    # Adhesives, sealants, composites (process-sensitive)
    # ------------------------------------------------------------------
    "EA 9394": {
        "canonical_name": "Hysol EA 9394 Adhesive",
        "material_code": "MAT-P09394",
        "material_class": MaterialClass.ADHESIVE,
        "family": "Adhesive-EA9394",
        "is_process_sensitive": True,
    },
    "EA 9396": {
        "canonical_name": "Hysol EA 9396 Adhesive",
        "material_code": "MAT-P09396",
        "material_class": MaterialClass.ADHESIVE,
        "family": "Adhesive-EA9396",
        "is_process_sensitive": True,
    },
    "EPIBOND 1590": {
        "canonical_name": "Epibond 1590 Adhesive",
        "material_code": "MAT-P01590",
        "material_class": MaterialClass.ADHESIVE,
        "family": "Adhesive-Epibond1590",
        "is_process_sensitive": True,
    },
    "HYSOL EA 934": {
        "canonical_name": "Hysol EA 934 Adhesive",
        "material_code": "MAT-P00934",
        "material_class": MaterialClass.ADHESIVE,
        "family": "Adhesive-EA934",
        "is_process_sensitive": True,
    },
    "RTV 560": {
        "canonical_name": "RTV 560 Silicone Sealant",
        "material_code": "MAT-P00560",
        "material_class": MaterialClass.SEALANT,
        "family": "Sealant-RTV560",
        "is_process_sensitive": True,
    },
    "RTV 566": {
        "canonical_name": "RTV 566 Silicone Sealant",
        "material_code": "MAT-P00566",
        "material_class": MaterialClass.SEALANT,
        "family": "Sealant-RTV566",
        "is_process_sensitive": True,
    },
    "PR-1422": {
        "canonical_name": "PR-1422 Polysulfide Sealant",
        "material_code": "MAT-P01422",
        "material_class": MaterialClass.SEALANT,
        "family": "Sealant-PR1422",
        "is_process_sensitive": True,
    },
    "ARALDITE": {
        "canonical_name": "Araldite Epoxy Adhesive",
        "material_code": "MAT-P00010",
        "material_class": MaterialClass.ADHESIVE,
        "family": "Adhesive-Araldite",
        "is_process_sensitive": True,
    },
    "IM7/8552": {
        "canonical_name": "IM7/8552 Carbon Fiber Composite",
        "material_code": "MAT-P08552",
        "material_class": MaterialClass.COMPOSITE,
        "family": "Composite-IM7-8552",
        "is_process_sensitive": True,
    },
    "T300/5208": {
        "canonical_name": "T300/5208 Carbon Fiber Composite",
        "material_code": "MAT-P05208",
        "material_class": MaterialClass.COMPOSITE,
        "family": "Composite-T300-5208",
        "is_process_sensitive": True,
    },
    "AS4/3501-6": {
        "canonical_name": "AS4/3501-6 Carbon Fiber Composite",
        "material_code": "MAT-P03501",
        "material_class": MaterialClass.COMPOSITE,
        "family": "Composite-AS4-3501",
        "is_process_sensitive": True,
    },
    "KEVLAR 49": {
        "canonical_name": "Kevlar 49 Aramid Fiber",
        "material_code": "MAT-P04900",
        "material_class": MaterialClass.COMPOSITE,
        "family": "Composite-Kevlar49",
        "is_process_sensitive": True,
    },

    # ------------------------------------------------------------------
    # Polymers and elastomers
    # ------------------------------------------------------------------
    "PTFE": {
        "canonical_name": "PTFE (Teflon)",
        "material_code": "MAT-Y00001",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-PTFE",
        "is_process_sensitive": False,
    },
    "TEFLON": {
        "canonical_name": "PTFE (Teflon)",
        "material_code": "MAT-Y00001",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-PTFE",
        "is_process_sensitive": False,
    },
    "PEEK": {
        "canonical_name": "PEEK (Polyether Ether Ketone)",
        "material_code": "MAT-Y00002",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-PEEK",
        "is_process_sensitive": False,
    },
    "VESPEL SP-1": {
        "canonical_name": "Vespel SP-1 Polyimide",
        "material_code": "MAT-Y00003",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-Vespel",
        "is_process_sensitive": False,
    },
    "KAPTON": {
        "canonical_name": "Kapton Polyimide Film",
        "material_code": "MAT-Y00004",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-Kapton",
        "is_process_sensitive": False,
    },
    "NOMEX": {
        "canonical_name": "Nomex Aramid Paper/Felt",
        "material_code": "MAT-Y00005",
        "material_class": MaterialClass.POLYMER,
        "family": "Polymer-Nomex",
        "is_process_sensitive": False,
    },
    "VITON A": {
        "canonical_name": "Viton A Fluoroelastomer",
        "material_code": "MAT-Y00010",
        "material_class": MaterialClass.ELASTOMER,
        "family": "Elastomer-Viton",
        "is_process_sensitive": False,
    },
    "BUNA-N": {
        "canonical_name": "Buna-N (Nitrile Rubber)",
        "material_code": "MAT-Y00011",
        "material_class": MaterialClass.ELASTOMER,
        "family": "Elastomer-BunaN",
        "is_process_sensitive": False,
    },
    "SILICONE": {
        "canonical_name": "Silicone Rubber (General)",
        "material_code": "MAT-Y00012",
        "material_class": MaterialClass.ELASTOMER,
        "family": "Elastomer-Silicone",
        "is_process_sensitive": False,
    },
}

# ---------------------------------------------------------------------------
# Aliases: alternate spellings and designations that map to the same DB key
# Keys are upper-cased alternate forms; values are the canonical DB key.
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    # Aluminum shorthand variants
    "AL 1100": "1100",
    "ALUMINUM 1100": "1100",
    "AL 2014-T6": "2014-T6",
    "AL 2024-T3": "2024-T3",
    "AL 2024-T4": "2024-T4",
    "AL 2024-T351": "2024-T351",
    "AL 2219-T87": "2219-T87",
    "AL 5052-H34": "5052-H34",
    "AL 6061-T6": "6061-T6",
    "AL 6061-T651": "6061-T651",
    "AL 7050-T7451": "7050-T7451",
    "AL 7075-T6": "7075-T6",
    "AL 7075-T73": "7075-T73",
    "ALUMINUM 2024-T3": "2024-T3",
    "ALUMINUM 2024-T4": "2024-T4",
    "ALUMINUM 6061-T6": "6061-T6",
    "ALUMINUM 7075-T6": "7075-T6",

    # Stainless steel variants
    "SS 304": "304",
    "SS 304L": "304L",
    "SS 316": "316",
    "SS 316L": "316L",
    "SS 321": "321",
    "SS 347": "347",
    "SS 410": "410",
    "SS 430": "430",
    "STAINLESS 304": "304",
    "STAINLESS 316": "316",
    "STAINLESS 316L": "316L",
    "CRES 304": "304",
    "CRES 316": "316",
    "CRES 321": "321",
    "CRES 347": "347",
    "CRES A286": "A-286",
    "CRES A-286": "A-286",
    "A286 CRES": "A-286",
    "A-286 CRES": "A-286",
    "A286": "A-286",
    "17-4PH": "17-4 PH",
    "17-7PH": "17-7 PH",
    "174PH": "17-4 PH",
    "177PH": "17-7 PH",
    "CUSTOM 455": "455 CUSTOM",
    "PH13-8MO": "PH 13-8MO",
    "PH 13-8": "PH 13-8MO",
    "13-8MO": "PH 13-8MO",
    "13-8 MO": "PH 13-8MO",

    # Nickel alloy variants
    "INC 600": "INCONEL 600",
    "INC 617": "INCONEL 617",
    "INC 625": "INCONEL 625",
    "INC 706": "INCONEL 706",
    "INC 718": "INCONEL 718",
    "IN 718": "INCONEL 718",
    "ALLOY 718": "INCONEL 718",
    "ALLOY 625": "INCONEL 625",
    "ALLOY X-750": "INCONEL X-750",
    "INCONEL X750": "INCONEL X-750",
    "HAST C-276": "HASTELLOY C-276",
    "HAST C276": "HASTELLOY C-276",
    "HAST X": "HASTELLOY X",
    "MONEL K500": "MONEL K-500",
    "RENE41": "RENE 41",
    "HAYNES230": "HAYNES 230",
    "HAYNES188": "HAYNES 188",

    # Titanium variants
    "TI 6AL-4V": "TI-6AL-4V",
    "TI 6-4": "TI-6AL-4V",
    "TI6AL4V": "TI-6AL-4V",
    "TI64": "TI-6AL-4V",
    "TI-6-4": "TI-6AL-4V",
    "TI-6AL-4V-ELI": "TI-6AL-4V ELI",
    "TI 6AL-4V ELI": "TI-6AL-4V ELI",
    "TI-3AL-2.5V": "TI-3AL-2.5V",
    "TI 3-2.5": "TI-3AL-2.5V",
    "CP TITANIUM GRADE 2": "CP TI GRADE 2",
    "CP TITANIUM GRADE 4": "CP TI GRADE 4",

    # Copper variants
    "OFHC CU": "OFHC COPPER",
    "C10200": "OFHC COPPER",
    "BERYLLIUM COPPER": "C17200",
    "BECU C17200": "C17200",
    "BE-CU": "C17200",
    "GRCOP42": "GRCOP-42",
    "GRCOP84": "GRCOP-84",
    "NARLOY Z": "NARLOY-Z",
    "NARLOYZ": "NARLOY-Z",

    # Cobalt variants
    "HAYNES 25": "HAYNES 25",
    "L605": "L-605",

    # Refractory variants
    "MO TZM": "MOLYBDENUM TZM",
    "MOLY TZM": "MOLYBDENUM TZM",
    "NB C-103": "NIOBIUM C-103",
    "NB C103": "NIOBIUM C-103",
    "NIOBIUM C103": "NIOBIUM C-103",

    # Composite variants
    "HYSOL EA 9394": "EA 9394",
    "HYSOL EA 9396": "EA 9396",
    "HYSOL 9394": "EA 9394",
    "HYSOL 9396": "EA 9396",
    "EA9394": "EA 9394",
    "EA9396": "EA 9396",
    "EA934": "HYSOL EA 934",
    "HYSOL 934": "HYSOL EA 934",
    "RTV560": "RTV 560",
    "RTV566": "RTV 566",
    "PR1422": "PR-1422",
    "KEVLAR49": "KEVLAR 49",

    # Polymer/elastomer variants
    "VESPEL": "VESPEL SP-1",
    "VESPEL SP1": "VESPEL SP-1",
    "VITON": "VITON A",
    "NITRILE": "BUNA-N",
    "NBR": "BUNA-N",
    "NITRILE RUBBER": "BUNA-N",
    "SILICONE RUBBER": "SILICONE",
}

# ---------------------------------------------------------------------------
# AMS / AISI / UNS specification -> canonical DB key mapping
# These translate standard specification numbers to our lookup keys.
# ---------------------------------------------------------------------------

_SPEC_MAP: dict[str, str] = {
    # AMS specifications (Aerospace Material Specifications)
    "AMS 4911": "TI-6AL-4V",
    "AMS 4928": "TI-6AL-4V",
    "AMS 4930": "TI-6AL-4V",
    "AMS 4931": "TI-6AL-4V ELI",
    "AMS 4935": "TI-6AL-4V ELI",
    "AMS 4944": "TI-6AL-2SN-4ZR-2MO",
    "AMS 4918": "TI-3AL-2.5V",
    "AMS 5596": "INCONEL 718",
    "AMS 5597": "INCONEL 718",
    "AMS 5599": "INCONEL 625",
    "AMS 5536": "HASTELLOY X",
    "AMS 5524": "HASTELLOY C-276",
    "AMS 5604": "17-4 PH",
    "AMS 5622": "17-7 PH",
    "AMS 5643": "17-4 PH",
    "AMS 5659": "PH 13-8MO",
    "AMS 5629": "AM350",
    "AMS 5737": "A-286",
    "AMS 5525": "21-6-9",
    "AMS 5528": "21-6-9",
    "AMS 5640": "455 CUSTOM",
    "AMS 4027": "2024-T3",
    "AMS 4037": "2024-T351",
    "AMS 4035": "2024-T4",
    "AMS 4050": "7075-T6",
    "AMS 4078": "7050-T7451",
    "AMS 4117": "6061-T6",
    "AMS 4025": "2014-T6",
    "AMS 4031": "2219-T87",
    "AMS 5501": "301",
    "AMS 5516": "304",
    "AMS 5513": "304L",
    "AMS 5524": "316",
    "AMS 5507": "316L",
    "AMS 5510": "321",
    "AMS 5512": "347",
    "AMS 5776": "WASPALOY",
    "AMS 5545": "RENE 41",
    "AMS 5878": "HAYNES 230",
    "AMS 5608": "440C",
    "AMS 5772": "L-605",
    "AMS 5758": "MP35N",
    "AMS 5844": "STELLITE 6B",
    "AMS 7801": "MOLYBDENUM TZM",

    # UNS designations (Unified Numbering System)
    "UNS N06600": "INCONEL 600",
    "UNS N06617": "INCONEL 617",
    "UNS N06625": "INCONEL 625",
    "UNS N09706": "INCONEL 706",
    "UNS N07718": "INCONEL 718",
    "UNS N07750": "INCONEL X-750",
    "UNS N10276": "HASTELLOY C-276",
    "UNS N06002": "HASTELLOY X",
    "UNS N04400": "MONEL 400",
    "UNS N05500": "MONEL K-500",
    "UNS N07001": "WASPALOY",
    "UNS N07041": "RENE 41",
    "UNS N06230": "HAYNES 230",
    "UNS R30188": "HAYNES 188",
    "UNS R30605": "L-605",
    "UNS R30035": "MP35N",
    "UNS S17400": "17-4 PH",
    "UNS S17700": "17-7 PH",
    "UNS S21900": "21-6-9",
    "UNS S30100": "301",
    "UNS S30200": "302",
    "UNS S30300": "303",
    "UNS S30400": "304",
    "UNS S30403": "304L",
    "UNS S31600": "316",
    "UNS S31603": "316L",
    "UNS S32100": "321",
    "UNS S34700": "347",
    "UNS S41000": "410",
    "UNS S41600": "416",
    "UNS S43000": "430",
    "UNS S44004": "440C",
    "UNS S45500": "455 CUSTOM",
    "UNS S66286": "A-286",
    "UNS S35000": "AM350",
    "UNS S13800": "PH 13-8MO",
    "UNS R56400": "TI-6AL-4V",
    "UNS R56401": "TI-6AL-4V ELI",
    "UNS R56320": "TI-3AL-2.5V",
    "UNS R54520": "TI-5AL-2.5SN",
    "UNS R56260": "TI-6AL-2SN-4ZR-2MO",
    "UNS A92024": "2024-T3",
    "UNS A97075": "7075-T6",
    "UNS A96061": "6061-T6",
    "UNS C17200": "C17200",
    "UNS C17500": "C17500",

    # AISI designations (American Iron and Steel Institute)
    "AISI 301": "301",
    "AISI 302": "302",
    "AISI 303": "303",
    "AISI 304": "304",
    "AISI 304L": "304L",
    "AISI 316": "316",
    "AISI 316L": "316L",
    "AISI 321": "321",
    "AISI 347": "347",
    "AISI 410": "410",
    "AISI 416": "416",
    "AISI 430": "430",
    "AISI 440C": "440C",
}
