"""Material resolution module for MUA v7.

Replaces the v6 regex-based alloy family matching (which treated 2024-T4 and 2014
as equivalent, and lumped 316L with 430 stainless) with a proper lookup table.

Resolution states:
- RESOLVED: Exact match to MAPTIS material code (green checkmark)
- FUZZY: Close match, engineer picks from suggestions (yellow)
- UNRESOLVED: No match found, needs manual input (red)

The v6 approach used first-digit regex grouping, meaning:
  - 2024-T3 and 2219-T87 were "same family" (both start with 2)
  - 316L and 347 were "same family" (both 3xx stainless)
  - No distinction between temper states

This module corrects all of that by resolving against a curated lookup table
keyed on canonical aerospace designations, with MAPTIS material codes as values.

Co-Authored-By: Atlas (OpenAI GPT-5) <noreply@openai.com>
"""

import re
import logging
from typing import Optional, Any
from difflib import SequenceMatcher

from .models import MaterialResolution, MaterialClass, ResolutionStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lookup table: canonical aerospace designation -> material record
#
# Keys are UPPER-CASED canonical names used for exact matching after
# normalisation.  Each value carries:
#   canonical_name        – human-readable designation
#   material_code         – MAPTIS-format code (MAT-Axxxxx)
#   material_class        – MaterialClass enum value
#   family                – alloy family grouping (used by is_same_family)
#   is_process_sensitive  – True for adhesives, sealants, composites, potting
# ---------------------------------------------------------------------------

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

# Precomputed normalised lookup for fast matching.  Built once at import time.
_NORMALISED_DB: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Non-material detection patterns
# ---------------------------------------------------------------------------

_NON_MATERIAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bper\s+drawing\b", re.IGNORECASE),
    re.compile(r"\bper\s+dwg\b", re.IGNORECASE),
    re.compile(r"\bsee\s+note\b", re.IGNORECASE),
    re.compile(r"\bsee\s+drawing\b", re.IGNORECASE),
    re.compile(r"\bnote\s+\d+\b", re.IGNORECASE),
    re.compile(r"\btbd\b", re.IGNORECASE),
    re.compile(r"\bt\.?b\.?d\.?\b", re.IGNORECASE),
    re.compile(r"\bn/?a\b", re.IGNORECASE),
    re.compile(r"\bnot\s+applicable\b", re.IGNORECASE),
    re.compile(r"\bnone\b", re.IGNORECASE),
    re.compile(r"\bvarious\b", re.IGNORECASE),
    re.compile(r"\bmaterial\s+per\b", re.IGNORECASE),
    re.compile(r"\bper\s+spec\b", re.IGNORECASE),
    re.compile(r"\bper\s+specification\b", re.IGNORECASE),
    re.compile(r"\bcallout\b", re.IGNORECASE),
    re.compile(r"\bto\s+be\s+determined\b", re.IGNORECASE),
    re.compile(r"\bunknown\b", re.IGNORECASE),
]

# Minimum length for a plausible material designation.  Anything shorter
# that doesn't exact-match is almost certainly garbage.
_MIN_PLAUSIBLE_LENGTH = 2

# Characters that a real material designation should contain.  If the input
# has none of these it is likely gibberish (e.g., "asdf").
_MATERIAL_CHARS_RE = re.compile(r"[0-9]|inconel|hastelloy|monel|haynes|rene|waspaloy"
                                r"|titanium|ti-|cp\s*ti|aluminum|steel|stainless"
                                r"|copper|ofhc|grcop|narloy|stellite|mp35n"
                                r"|kevlar|kapton|nomex|vespel|peek|ptfe|teflon"
                                r"|viton|buna|silicone|rtv|araldite|epibond|hysol"
                                r"|ea\s*9|pr-|im7|t300|as4|l-605|a-286|am350"
                                r"|tungsten|molybdenum|niobium|tantalum|tzm|c-103"
                                r"|ams\s|aisi\s|uns\s",
                                re.IGNORECASE)


# ---------------------------------------------------------------------------
# Initialisation: build normalised lookup
# ---------------------------------------------------------------------------

def _normalize_designation(text: str) -> str:
    """Normalize a material designation string for matching.

    Transformations applied:
    - Strip leading/trailing whitespace
    - Upper-case
    - Collapse multiple spaces into one
    - Normalise common temper/condition separators (e.g. "T 6" -> "T6")
    - Remove extraneous punctuation but preserve meaningful hyphens

    Returns:
        Normalised upper-case string suitable for lookup.
    """
    result = text.strip().upper()

    # Collapse multiple whitespace characters into a single space.
    result = re.sub(r"\s+", " ", result)

    # Normalise temper designation spacing: "- T 351" -> "-T351", " T6" -> "-T6"
    # But only for aluminum-style temper codes (T or H followed by digits).
    result = re.sub(r"\s*-?\s*([TH])[\s-]*(\d+)", r"-\1\2", result)

    # Some people write "AL2024" without a space — add one for the alias lookup.
    # (But don't break things like "AM350" or "PH13".)

    return result


def _build_normalised_db() -> None:
    """Build the normalised lookup table from MATERIAL_DATABASE + _ALIASES + _SPEC_MAP.

    Called once at module import time.  Maps normalised forms of every known
    designation (canonical keys, aliases, and spec numbers) to the canonical
    DB key so that ``resolve_material`` can do O(1) lookups.
    """
    # Canonical DB keys
    for key in MATERIAL_DATABASE:
        norm = _normalize_designation(key)
        _NORMALISED_DB[norm] = key

    # Aliases
    for alias, canonical_key in _ALIASES.items():
        norm = _normalize_designation(alias)
        # Only set if not already present (canonical keys take priority).
        _NORMALISED_DB.setdefault(norm, canonical_key)

    # Specification numbers (AMS/AISI/UNS)
    for spec, canonical_key in _SPEC_MAP.items():
        norm = _normalize_designation(spec)
        _NORMALISED_DB.setdefault(norm, canonical_key)


_build_normalised_db()


# ---------------------------------------------------------------------------
# Non-material detection
# ---------------------------------------------------------------------------

def _is_non_material(text: str) -> bool:
    """Determine whether *text* is clearly not a material designation.

    Catches drawing callouts ("material per drawing note 7"), placeholder
    tokens ("TBD", "N/A"), and gibberish strings ("asdf").

    Args:
        text: Raw user input (already stripped of leading/trailing whitespace).

    Returns:
        True if the input should be rejected as a non-material.
    """
    if not text:
        return True

    # Very short inputs that are not exact DB hits are almost certainly junk.
    upper = text.upper()
    if len(text) < _MIN_PLAUSIBLE_LENGTH and upper not in MATERIAL_DATABASE:
        return True

    # Check against known non-material phrases.
    for pattern in _NON_MATERIAL_PATTERNS:
        if pattern.search(text):
            return True

    # If the string contains no digits and no recognisable material keyword,
    # it is likely gibberish.  (We allow short all-alpha strings that *are* in
    # the DB, like "PEEK" or "TZM".)
    if upper in MATERIAL_DATABASE or upper in _ALIASES:
        return False
    norm = _normalize_designation(text)
    if norm in _NORMALISED_DB:
        return False

    if not _MATERIAL_CHARS_RE.search(text):
        # No digits, no known material keywords — probably not a material.
        return True

    return False


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def _find_fuzzy_matches(text: str, threshold: float = 0.65) -> list[dict]:
    """Find materials in the database that are close to *text*.

    Uses ``difflib.SequenceMatcher`` on the normalised input against every
    canonical key.  Results are sorted by descending similarity.

    Args:
        text: The user input (will be normalised internally).
        threshold: Minimum similarity ratio (0.0 .. 1.0) to include a result.
            Defaults to 0.65 to catch plausible typos without flooding the
            engineer with irrelevant suggestions.

    Returns:
        A list of dicts, each containing:
            - ``canonical_name``: human-readable name
            - ``material_code``: MAPTIS code
            - ``similarity``: float ratio
            - ``db_key``: the canonical DB key that matched
        Sorted by descending similarity.  At most 5 results returned.
    """
    norm_input = _normalize_designation(text)
    matches: list[dict] = []

    seen_codes: set[str] = set()

    for db_key, record in MATERIAL_DATABASE.items():
        norm_key = _normalize_designation(db_key)
        ratio = SequenceMatcher(None, norm_input, norm_key).ratio()
        if ratio >= threshold and record["material_code"] not in seen_codes:
            matches.append({
                "canonical_name": record["canonical_name"],
                "material_code": record["material_code"],
                "similarity": round(ratio, 4),
                "db_key": db_key,
            })
            seen_codes.add(record["material_code"])

    # Also check aliases — the user might have typed something close to a
    # common alias rather than the canonical key.
    for alias, canonical_key in _ALIASES.items():
        norm_alias = _normalize_designation(alias)
        ratio = SequenceMatcher(None, norm_input, norm_alias).ratio()
        record = MATERIAL_DATABASE.get(canonical_key)
        if record and ratio >= threshold and record["material_code"] not in seen_codes:
            matches.append({
                "canonical_name": record["canonical_name"],
                "material_code": record["material_code"],
                "similarity": round(ratio, 4),
                "db_key": canonical_key,
            })
            seen_codes.add(record["material_code"])

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches[:5]


# ---------------------------------------------------------------------------
# AMS / AISI / UNS pattern extraction
# ---------------------------------------------------------------------------

_SPEC_PATTERN = re.compile(
    r"(AMS\s*\d{4}[A-Z]?|AISI\s*\d{3}[A-Z]?|UNS\s*[A-Z]\d{5})",
    re.IGNORECASE,
)


def _try_spec_resolution(text: str) -> Optional[str]:
    """Attempt to extract and resolve an AMS/AISI/UNS specification number.

    Args:
        text: Raw user input.

    Returns:
        The canonical DB key if a spec number is found and mapped, else None.
    """
    match = _SPEC_PATTERN.search(text)
    if not match:
        return None

    spec_raw = match.group(1).strip().upper()
    # Normalise spacing: "AMS5596" -> "AMS 5596"
    spec_normalised = re.sub(r"(AMS|AISI|UNS)\s*", r"\1 ", spec_raw).strip()

    norm = _normalize_designation(spec_normalised)
    db_key = _NORMALISED_DB.get(norm)
    if db_key:
        logger.debug("Spec pattern '%s' resolved to DB key '%s'", spec_normalised, db_key)
    return db_key


# ---------------------------------------------------------------------------
# Live MAPTIS-backed resolution path (global, form-aware candidate set)
# ---------------------------------------------------------------------------

_PROCESS_SENSITIVE_KEYWORDS = (
    "ADHESIVE",
    "EPOXY",
    "SEALANT",
    "POTTING",
    "RTV",
    "COMPOSITE",
    "PREPREG",
)


_MATERIAL_KEYWORD_PATTERN = re.compile(
    r"\b("
    r"STEEL|STAINLESS|CRES|SST|SS|"
    r"AL|ALUMINUM|ALUMINIUM|TITANIUM|TI|"
    r"NICKEL|INCONEL|HASTELLOY|MONEL|"
    r"COPPER|BRONZE"
    r")\b",
    re.IGNORECASE,
)

_UNS_DIRECT_PATTERN = re.compile(
    r"\b[ACGKMNRSTW]\d{5}\b",
    re.IGNORECASE,
)

_ALLOY_TOKEN_PATTERN = re.compile(
    r"\b(A-?286|[1-9]\d{2,4}[A-Z]?)\b",
    re.IGNORECASE,
)


def _split_material_segments(text: str) -> list[str]:
    """Split likely multi-material callouts while preserving spec fractions (e.g. 250/11)."""
    raw = (text or "").strip()
    if not raw:
        return []

    # Split on slash except when used as numeric fraction.
    chunks: list[str] = []
    current: list[str] = []
    for i, ch in enumerate(raw):
        if ch == "/":
            prev_ch = raw[i - 1] if i > 0 else ""
            next_ch = raw[i + 1] if i + 1 < len(raw) else ""
            if prev_ch.isdigit() and next_ch.isdigit():
                current.append(ch)
            else:
                chunk = "".join(current).strip()
                if chunk:
                    chunks.append(chunk)
                current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        chunks.append(tail)

    segments: list[str] = []
    for chunk in chunks:
        for seg in re.split(r"\s*(?:;|,|\+|\bAND\b|\bOR\b)\s*", chunk, flags=re.IGNORECASE):
            cleaned = seg.strip()
            if cleaned:
                segments.append(cleaned)
    return segments


def _segment_has_material_signal(segment: str) -> bool:
    cleaned = (segment or "").strip()
    if len(cleaned) < 2:
        return False

    has_keyword = bool(_MATERIAL_KEYWORD_PATTERN.search(cleaned))
    is_spec_fragment = bool(
        re.search(r"\b(AMS|ASTM|SAE|MIL|QQ|ASME|SPEC|REV|TYPE|CLASS)\b", cleaned, re.IGNORECASE)
    )

    # Avoid treating standalone standards callouts as material identities.
    if is_spec_fragment and not has_keyword:
        return False

    if _UNS_DIRECT_PATTERN.search(cleaned):
        return True

    try:
        from mira.miul.alloy_normalizer import normalize_alloy

        normalized = normalize_alloy(cleaned)
        if getattr(normalized, "is_resolved", False) and getattr(normalized, "uns", None):
            return True
    except Exception:
        # Fall through to lexical signal checks.
        pass

    has_alloy_token = bool(_ALLOY_TOKEN_PATTERN.search(cleaned))
    return has_keyword and has_alloy_token


def _detect_multi_material_input(text: str) -> tuple[bool, list[str]]:
    """Detect mixed-material callouts that require explicit human disambiguation."""
    segments = _split_material_segments(text)
    if len(segments) < 2:
        return False, segments

    signal_segments = [s for s in segments if _segment_has_material_signal(s)]
    return len(signal_segments) >= 2, signal_segments


def _detect_family_from_text(text: str) -> Optional[str]:
    """Infer a broad material family from designation text."""
    upper = (text or "").upper()

    if re.search(r"\b(STAINLESS|CRES|SST|SS)\b", upper):
        return "stainless"
    if re.search(r"\b(INCONEL|HASTELLOY|MONEL|NICKEL|WASPALOY|RENE)\b", upper):
        return "nickel"
    if re.search(r"\b(ALUMINUM|ALUMINIUM|AL)\b", upper):
        return "aluminum"
    if re.search(r"\b(TITANIUM|TI)\b", upper):
        return "titanium"
    if re.search(r"\b(ADHESIVE|EPOXY|SEALANT|RTV|POTTING)\b", upper):
        return "adhesive"
    if re.search(r"\b(PTFE|TEFLON|PEEK|POLYIMIDE|VITON|NITRILE|ELASTOMER)\b", upper):
        return "polymer"
    if re.search(r"\b(COPPER|BRONZE|BERYLLIUM COPPER)\b", upper):
        return "copper"
    return None


def _class_from_family(family: Optional[str]) -> MaterialClass:
    """Map broad family labels to MaterialClass for UI/step gating."""
    if family in {"stainless", "nickel", "titanium"}:
        return MaterialClass.ALLOY
    if family in {"aluminum", "copper"}:
        return MaterialClass.METAL
    if family == "adhesive":
        return MaterialClass.ADHESIVE
    if family == "polymer":
        return MaterialClass.POLYMER
    return MaterialClass.OTHER


def _is_process_sensitive_designation(text: str) -> bool:
    upper = (text or "").upper()
    return any(keyword in upper for keyword in _PROCESS_SENSITIVE_KEYWORDS)


def _derive_anchor_token(text: str) -> Optional[str]:
    """Pick a high-signal token for boundary-safe material candidate search."""
    upper = _normalize_designation(text or "")
    if not upper:
        return None

    tokens = re.findall(r"[A-Z0-9]+(?:-[A-Z0-9]+)?", upper)
    digit_tokens = [t for t in tokens if any(ch.isdigit() for ch in t) and len(t) >= 3]
    if digit_tokens:
        return max(digit_tokens, key=len)

    alpha_tokens = [t for t in tokens if len(t) >= 4]
    if alpha_tokens:
        return max(alpha_tokens, key=len)

    return None


def _score_candidate_row(
    *,
    query_text: str,
    row: dict[str, Any],
    preferred_code: Optional[str],
    preferred_name: Optional[str],
    anchor: Optional[str],
) -> float:
    """Score a candidate row for ranking in HITL suggestions."""
    designation = str(row.get("designation") or "")
    material_code = str(row.get("material_code") or "")
    query_norm = _normalize_designation(query_text)
    designation_norm = _normalize_designation(designation)

    score = SequenceMatcher(None, query_norm, designation_norm).ratio()

    if preferred_code and material_code == str(preferred_code):
        score += 0.35
    if preferred_name and _normalize_designation(preferred_name) == designation_norm:
        score += 0.25
    if anchor and re.search(rf"\b{re.escape(anchor)}\b", designation_norm):
        score += 0.20
    if designation_norm.startswith(query_norm):
        score += 0.10

    return round(min(score, 1.0), 4)


def _load_material_candidates(
    query_text: str,
    *,
    preferred_code: Optional[str] = None,
    preferred_name: Optional[str] = None,
    max_rows: int = 12,
) -> list[dict[str, Any]]:
    """Query MAPTIS materials table for candidate designations.

    Uses a boundary-safe anchor token first, then a broader fallback search.
    """
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
        from mira.core.db_config import get_db_connection_params
    except Exception:
        logger.exception("MAPTIS candidate query imports failed")
        return []

    rows_by_code: dict[str, dict[str, Any]] = {}
    anchor = _derive_anchor_token(query_text)

    try:
        conn = psycopg2.connect(**get_db_connection_params())
        cursor = conn.cursor(cursor_factory=DictCursor)
    except Exception:
        logger.exception("MAPTIS candidate query DB connection failed")
        return []

    try:
        if preferred_code:
            cursor.execute(
                """
                SELECT material_key, material_code, designation
                FROM materials
                WHERE material_code = %s
                  AND material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                LIMIT 1
                """,
                (str(preferred_code),),
            )
            for row in cursor.fetchall():
                d = dict(row)
                rows_by_code[str(d.get("material_code"))] = d

        if anchor:
            cursor.execute(
                """
                SELECT material_key, material_code, designation
                FROM materials
                WHERE material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                  AND designation ~* %s
                ORDER BY designation
                LIMIT 80
                """,
                (rf"\y{re.escape(anchor)}\y",),
            )
            for row in cursor.fetchall():
                d = dict(row)
                rows_by_code.setdefault(str(d.get("material_code")), d)

        if preferred_name:
            cursor.execute(
                """
                SELECT material_key, material_code, designation
                FROM materials
                WHERE material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                  AND LOWER(designation) LIKE %s
                ORDER BY designation
                LIMIT 40
                """,
                (f"%{preferred_name.lower()}%",),
            )
            for row in cursor.fetchall():
                d = dict(row)
                rows_by_code.setdefault(str(d.get("material_code")), d)

        if not rows_by_code:
            cursor.execute(
                """
                SELECT material_key, material_code, designation
                FROM materials
                WHERE material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                  AND LOWER(designation) LIKE %s
                ORDER BY designation
                LIMIT 40
                """,
                (f"%{query_text.lower()}%",),
            )
            for row in cursor.fetchall():
                d = dict(row)
                rows_by_code.setdefault(str(d.get("material_code")), d)

    except Exception:
        logger.exception("MAPTIS candidate query failed for '%s'", query_text)
        return []
    finally:
        cursor.close()
        conn.close()

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows_by_code.values():
        score = _score_candidate_row(
            query_text=query_text,
            row=row,
            preferred_code=preferred_code,
            preferred_name=preferred_name,
            anchor=anchor,
        )
        scored.append((score, row))

    scored.sort(
        key=lambda item: (
            item[0],
            -len(str(item[1].get("designation") or "")),
        ),
        reverse=True,
    )
    return [row for _, row in scored[:max_rows]]


def _candidate_to_suggestion(row: dict[str, Any], score: float) -> dict[str, Any]:
    """Normalize a candidate row into UI-friendly suggestion payload."""
    return {
        "name": str(row.get("designation") or ""),
        "spec": str(row.get("material_code") or ""),
        "score": score,
        "material_code": str(row.get("material_code") or ""),
        "material_key": int(row["material_key"]) if row.get("material_key") is not None else None,
    }


def _resolve_with_live_maptis_lookup(
    input_text: str,
    *,
    preferred_code: Optional[str] = None,
    preferred_name: Optional[str] = None,
    preferred_key: Optional[int] = None,
) -> Optional[MaterialResolution]:
    """Resolve material using the MAPTIS-backed lookup service.

    Returns ``None`` only when the live path cannot be executed; caller
    should then use the legacy in-module fallback.
    """
    is_multi_material, segments = _detect_multi_material_input(input_text)
    explicit_override = bool((preferred_code or "").strip()) or preferred_key is not None

    # Mixed callouts (e.g., "STEEL 9310/STAINLESS 316") should never auto-resolve.
    # Force explicit human pick unless caller provided an explicit override.
    if is_multi_material and not explicit_override:
        query_list = [input_text] + segments[:4]
        rows_by_code: dict[str, dict[str, Any]] = {}
        for query in query_list:
            for row in _load_material_candidates(query, max_rows=10):
                code = str(row.get("material_code") or "").strip()
                if not code:
                    continue
                rows_by_code.setdefault(code, row)

        candidates = list(rows_by_code.values())
        query_anchor = _derive_anchor_token(input_text)
        suggestions: list[dict[str, Any]] = []
        for row in candidates:
            score = _score_candidate_row(
                query_text=input_text,
                row=row,
                preferred_code=None,
                preferred_name=preferred_name,
                anchor=query_anchor,
            )
            suggestions.append(_candidate_to_suggestion(row, score))
        suggestions.sort(key=lambda s: s.get("score", 0.0), reverse=True)

        family = _detect_family_from_text(input_text)
        material_class = _class_from_family(family)
        process_sensitive = _is_process_sensitive_designation(input_text)

        return MaterialResolution(
            status=ResolutionStatus.FUZZY,
            input_text=input_text.strip(),
            resolved_name=input_text.strip(),
            material_code=None,
            material_key=None,
            material_class=material_class,
            family=family,
            suggestions=suggestions[:8],
            is_process_sensitive=process_sensitive,
            selection_method="multi_material_detected",
            selection_confidence=None,
        )

    try:
        from mira.miul.material_code_lookup import get_lookup_service
    except Exception:
        logger.exception("Could not import material_code_lookup service")
        return None

    try:
        lookup = get_lookup_service()
        match = lookup.lookup_material_code(input_text)
    except Exception:
        logger.exception("material_code_lookup failed for '%s'", input_text)
        return None

    selected_code = str(preferred_code).strip() if preferred_code else (
        str(match.material_code).strip() if match.material_code else None
    )

    candidates = _load_material_candidates(
        input_text,
        preferred_code=selected_code,
        preferred_name=preferred_name,
        max_rows=12,
    )

    # Fold in explicit ambiguous candidates from the lookup service.
    for cand in (match.candidates or []):
        if not cand.material_code:
            continue
        code = str(cand.material_code).strip()
        if any(str(row.get("material_code")) == code for row in candidates):
            continue
        candidates.append(
            {
                "material_key": None,
                "material_code": code,
                "designation": cand.designation,
            }
        )

    if selected_code:
        selected_row = next(
            (row for row in candidates if str(row.get("material_code")) == selected_code),
            None,
        )
    elif preferred_key is not None:
        selected_row = next(
            (
                row
                for row in candidates
                if row.get("material_key") is not None
                and int(row["material_key"]) == int(preferred_key)
            ),
            None,
        )
    else:
        selected_row = next(
            (row for row in candidates if str(row.get("material_code") or "").strip()),
            candidates[0] if candidates else None,
        )

    # If lookup did not select a code but we have a selected candidate row,
    # carry its code so downstream MAPTIS evidence retrieval can execute.
    if not selected_code and selected_row:
        row_code = str(selected_row.get("material_code") or "").strip()
        if row_code:
            selected_code = row_code

    selected_designation = (
        (preferred_name or "").strip()
        or (str(selected_row.get("designation")) if selected_row else "")
        or (match.designation or "")
    )
    selected_key = preferred_key if preferred_key is not None else (
        int(selected_row["material_key"]) if selected_row and selected_row.get("material_key") is not None else None
    )

    family = _detect_family_from_text(selected_designation or input_text)
    material_class = _class_from_family(family)
    process_sensitive = _is_process_sensitive_designation(selected_designation or input_text)

    query_anchor = _derive_anchor_token(input_text)
    suggestions: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in candidates:
        code = str(row.get("material_code") or "")
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        score = _score_candidate_row(
            query_text=input_text,
            row=row,
            preferred_code=selected_code,
            preferred_name=selected_designation or None,
            anchor=query_anchor,
        )
        suggestions.append(_candidate_to_suggestion(row, score))
    suggestions.sort(key=lambda s: s.get("score", 0.0), reverse=True)

    method = str(getattr(match, "method", "") or "")
    confidence = float(getattr(match, "score", 0.0) or 0.0)
    match_code = str(getattr(match, "material_code", "") or "").strip()
    manual_override = (
        preferred_key is not None
        or (
            bool((preferred_code or "").strip())
            and str(preferred_code).strip() != match_code
        )
    )

    if manual_override:
        status = ResolutionStatus.RESOLVED if selected_code else ResolutionStatus.FUZZY
        method = "manual_override"
    elif method.startswith("ambiguous"):
        status = ResolutionStatus.FUZZY
    elif selected_code:
        unresolved_with_choices = method in {"unresolved", "fallback", "candidate_ranked_fallback"} and len(suggestions) > 1
        # Generic alloy-only inputs (e.g., "316", "6061") should keep HITL.
        generic_alloy = bool(re.fullmatch(r"[A-Z]{0,4}\s*\d{3,4}[A-Z]?", _normalize_designation(input_text)))
        if unresolved_with_choices or (generic_alloy and len(suggestions) > 1):
            status = ResolutionStatus.FUZZY
        else:
            status = ResolutionStatus.RESOLVED
    elif suggestions:
        status = ResolutionStatus.FUZZY
    else:
        status = ResolutionStatus.UNRESOLVED

    return MaterialResolution(
        status=status,
        input_text=input_text.strip(),
        resolved_name=selected_designation or None,
        material_code=selected_code,
        material_key=selected_key,
        material_class=material_class,
        family=family,
        suggestions=suggestions[:8],
        is_process_sensitive=process_sensitive,
        selection_method=method or None,
        selection_confidence=confidence if confidence > 0 else None,
    )


# ---------------------------------------------------------------------------
# Main resolution function
# ---------------------------------------------------------------------------

def resolve_material(
    input_text: str,
    *,
    preferred_code: Optional[str] = None,
    preferred_name: Optional[str] = None,
    preferred_key: Optional[int] = None,
) -> MaterialResolution:
    """Resolve a free-text material input against the MAPTIS lookup table.

    Resolution strategy (tried in order):
    1. Detect non-material inputs and reject immediately.
    2. Exact match against canonical DB keys (case-insensitive).
    3. Normalised match (handles whitespace, temper separator variants).
    4. Alias match (common alternate designations).
    5. AMS/AISI/UNS specification pattern extraction.
    6. Fuzzy match via SequenceMatcher (threshold 0.75 for auto-suggest).
    7. Fall through to UNRESOLVED.

    Args:
        input_text: Raw engineer input, e.g. "2024-T3", "AMS 5596",
            "material per drawing note 7", "Inocel 718" (typo).

    Returns:
        A ``MaterialResolution`` instance carrying the resolution status,
        matched material data (if any), and fuzzy suggestions (if applicable).
    """
    raw = input_text.strip() if input_text else ""
    if not raw:
        logger.info("Empty input received - marking UNRESOLVED.")
        return MaterialResolution(
            status=ResolutionStatus.UNRESOLVED,
            input_text=raw,
        )

    # Step 1: non-material detection
    if _is_non_material(raw):
        logger.info("Non-material input detected: '%s'", raw)
        return MaterialResolution(
            status=ResolutionStatus.UNRESOLVED,
            input_text=raw,
        )

    # Preferred global path: live MAPTIS-backed lookup service (v4-compatible).
    live = _resolve_with_live_maptis_lookup(
        raw,
        preferred_code=preferred_code,
        preferred_name=preferred_name,
        preferred_key=preferred_key,
    )
    if live is not None:
        logger.info(
            "Live MAPTIS resolution for '%s': status=%s code=%s method=%s",
            raw,
            live.status.value,
            live.material_code,
            live.selection_method,
        )
        return live

    upper = raw.upper()

    # ----- Step 2: exact match (case-insensitive on canonical keys) -----
    if upper in MATERIAL_DATABASE:
        record = MATERIAL_DATABASE[upper]
        logger.info("Exact match for '%s' -> %s", raw, record["material_code"])
        return MaterialResolution(
            status=ResolutionStatus.RESOLVED,
            input_text=raw,
            resolved_name=record["canonical_name"],
            material_code=record["material_code"],
            material_class=record["material_class"],
            family=record["family"],
            is_process_sensitive=record["is_process_sensitive"],
        )

    # ----- Step 3: normalised match -----
    norm = _normalize_designation(raw)
    db_key = _NORMALISED_DB.get(norm)
    if db_key and db_key in MATERIAL_DATABASE:
        record = MATERIAL_DATABASE[db_key]
        logger.info("Normalised match for '%s' (norm='%s') -> %s",
                     raw, norm, record["material_code"])
        return MaterialResolution(
            status=ResolutionStatus.RESOLVED,
            input_text=raw,
            resolved_name=record["canonical_name"],
            material_code=record["material_code"],
            material_class=record["material_class"],
            family=record["family"],
            is_process_sensitive=record["is_process_sensitive"],
        )

    # ----- Step 4: alias match (already folded into _NORMALISED_DB) -----
    # The normalised DB includes aliases, so if step 3 didn't hit we also
    # try direct upper-case alias lookup for edge cases the normaliser
    # might not handle perfectly.
    alias_key = _ALIASES.get(upper)
    if alias_key and alias_key in MATERIAL_DATABASE:
        record = MATERIAL_DATABASE[alias_key]
        logger.info("Alias match for '%s' -> '%s' -> %s",
                     raw, alias_key, record["material_code"])
        return MaterialResolution(
            status=ResolutionStatus.RESOLVED,
            input_text=raw,
            resolved_name=record["canonical_name"],
            material_code=record["material_code"],
            material_class=record["material_class"],
            family=record["family"],
            is_process_sensitive=record["is_process_sensitive"],
        )

    # ----- Step 5: AMS/AISI/UNS pattern -----
    spec_key = _try_spec_resolution(raw)
    if spec_key and spec_key in MATERIAL_DATABASE:
        record = MATERIAL_DATABASE[spec_key]
        logger.info("Spec match for '%s' -> '%s' -> %s",
                     raw, spec_key, record["material_code"])
        return MaterialResolution(
            status=ResolutionStatus.RESOLVED,
            input_text=raw,
            resolved_name=record["canonical_name"],
            material_code=record["material_code"],
            material_class=record["material_class"],
            family=record["family"],
            is_process_sensitive=record["is_process_sensitive"],
        )

    # ----- Step 6: fuzzy matching -----
    fuzzy_matches = _find_fuzzy_matches(raw, threshold=0.65)

    if fuzzy_matches:
        best = fuzzy_matches[0]
        # If the best match is very strong (>= 0.75), mark FUZZY and
        # present it as a likely match the engineer should confirm.
        if best["similarity"] >= 0.75:
            best_record = MATERIAL_DATABASE.get(best["db_key"], {})
            logger.info("Strong fuzzy match for '%s': '%s' (%.2f)",
                         raw, best["canonical_name"], best["similarity"])
            return MaterialResolution(
                status=ResolutionStatus.FUZZY,
                input_text=raw,
                resolved_name=best_record.get("canonical_name"),
                material_code=best_record.get("material_code"),
                material_class=best_record.get("material_class"),
                family=best_record.get("family"),
                is_process_sensitive=best_record.get("is_process_sensitive"),
                suggestions=fuzzy_matches,
            )

        # Weaker matches — still FUZZY but less confident.
        logger.info("Weak fuzzy matches for '%s': %d candidates", raw, len(fuzzy_matches))
        return MaterialResolution(
            status=ResolutionStatus.FUZZY,
            input_text=raw,
            suggestions=fuzzy_matches,
        )

    # ----- Step 7: unresolved -----
    logger.info("No match found for '%s' — UNRESOLVED.", raw)
    return MaterialResolution(
        status=ResolutionStatus.UNRESOLVED,
        input_text=raw,
    )


# ---------------------------------------------------------------------------
# Family helpers
# ---------------------------------------------------------------------------

def get_material_family(material_code: str) -> Optional[str]:
    """Look up the alloy family for a given MAPTIS material code.

    Args:
        material_code: A MAPTIS code, e.g. ``"MAT-A00210"``.

    Returns:
        The family string (e.g. ``"Al-2024"``), or ``None`` if the code is
        not found in the database.
    """
    if not material_code:
        return None

    for record in MATERIAL_DATABASE.values():
        if record["material_code"] == material_code:
            return record["family"]

    # Live MAPTIS codes are numeric strings (e.g., "10095"), so fall back to
    # designation-based family inference from the materials table.
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
        from mira.core.db_config import get_db_connection_params

        with psycopg2.connect(**get_db_connection_params()) as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT designation
                    FROM materials
                    WHERE material_code = %s
                    LIMIT 1
                    """,
                    (str(material_code),),
                )
                row = cursor.fetchone()
                if row and row.get("designation"):
                    family = _detect_family_from_text(str(row["designation"]))
                    if family:
                        return family
    except Exception:
        logger.debug("Could not infer family from DB for material code '%s'.", material_code)

    logger.debug("Material code '%s' not found in database.", material_code)
    return None


def is_same_family(code_a: str, code_b: str) -> bool:
    """Determine whether two MAPTIS material codes belong to the same family.

    This is the correct replacement for the v6 regex approach that compared
    first digits.  Two materials are in the same family only if they share
    an identical ``family`` string in the database.

    Examples:
        - ``is_same_family("MAT-A00210", "MAT-A00211")`` -> True
          (both Al-2024: 2024-T3 and 2024-T4)
        - ``is_same_family("MAT-A00210", "MAT-A00220")`` -> False
          (Al-2024 vs Al-2219 — different alloys despite both being 2xxx)
        - ``is_same_family("MAT-S00316", "MAT-S00430")`` -> False
          (SS-316 vs SS-430 — v6 lumped these together)

    Args:
        code_a: First MAPTIS material code.
        code_b: Second MAPTIS material code.

    Returns:
        True if both codes are in the database and share the same family.
        False otherwise (including when either code is unknown).
    """
    family_a = get_material_family(code_a)
    family_b = get_material_family(code_b)

    if family_a is None or family_b is None:
        logger.debug(
            "Cannot determine family equivalence: %s=%s, %s=%s",
            code_a, family_a, code_b, family_b,
        )
        return False

    return family_a == family_b


