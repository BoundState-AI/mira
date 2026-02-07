#!/usr/bin/env python3
"""
Module: Aliases
Purpose: Normalize a material name for matching.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import re
from typing import Optional

# =============================================================================
# MATERIAL ALIAS DICTIONARY
# =============================================================================
# Format: canonical_name -> (alias1, alias2, ...)
# Canonical names match exactly what appears in h2_evidence_merged.json
# Aliases are common variations users might type

MATERIAL_ALIASES: dict[str, tuple[str, ...]] = {
    # -------------------------------------------------------------------------
    # NICKEL SUPERALLOYS
    # -------------------------------------------------------------------------
    "Inconel 718": (
        "718", "in718", "in-718", "alloy 718", "uns n07718", "inconel718",
        "inc 718", "inc718", "ni718", "nickel 718",
    ),
    "PM Inconel 718": (
        "pm 718", "pm718", "pm in718", "powder 718", "powder inconel 718",
    ),
    "Inconel 625": (
        "625", "in625", "in-625", "alloy 625", "uns n06625", "inconel625",
        "inc 625", "inc625",
    ),
    "Inconel 706": (
        "706", "in706", "in-706", "alloy 706", "uns n09706", "inconel706",
    ),
    "Inconel 600": (
        "600", "in600", "in-600", "alloy 600", "uns n06600", "inconel600",
    ),
    "Inconel 617": (
        "617", "in617", "in-617", "alloy 617", "uns n06617",
    ),
    "Inconel 690": (
        "690", "in690", "in-690", "alloy 690", "uns n06690",
    ),
    "Inconel 700": (
        "700", "in700", "in-700", "alloy 700",
    ),
    "Inconel 713LC": (
        "713lc", "in713lc", "inconel 713", "713",
    ),
    "Inconel X-750": (
        "x750", "x-750", "inx750", "inconel x750", "alloy x-750", "uns n07750",
    ),
    "IN 100": (
        "in100", "in-100", "inconel 100",
    ),

    # Incoloy family
    "Incoloy 800": (
        "800", "incoloy800", "alloy 800", "uns n08800",
    ),
    "Incoloy 802": (
        "802", "incoloy802", "alloy 802",
    ),
    "Incoloy 825": (
        "825", "incoloy825", "alloy 825", "uns n08825",
    ),
    "Incoloy 901": (
        "901", "incoloy901", "alloy 901",
    ),
    "Incoloy 903": (
        "903", "incoloy903", "alloy 903",
    ),
    "Incoloy 907": (
        "907", "incoloy907", "alloy 907",
    ),
    "Incoloy 909 (ST + Aged)": (
        "909", "incoloy909", "incoloy 909", "alloy 909",
    ),

    # Hastelloy family
    "Hastelloy X": (
        "hastelloy-x", "hastelloyx", "has x", "alloy x",
    ),
    "Hastelloy C-276": (
        "c276", "c-276", "hastelloy c276", "alloy c-276", "uns n10276",
    ),

    # Haynes family
    "Haynes 188": (
        "188", "haynes188", "ha188",
    ),
    "Haynes 230": (
        "230", "haynes230", "ha230",
    ),
    "Haynes 242": (
        "242", "haynes242", "ha242",
    ),

    # Rene family
    "Rene 41": (
        "rene41", "r41", "rené 41",
    ),
    "Rene 95 (PM)": (
        "rene 95", "rene95", "r95",
    ),
    "Rene N-4 (single crystal)": (
        "rene n4", "rene n-4", "n4",
    ),

    # Waspaloy
    "Waspaloy": (
        "wasp", "waspalloy",
    ),

    # Astroloy
    "Astroloy": (
        "astro",
    ),

    # Udimet family
    "Udimet 500": (
        "u500", "udimet500",
    ),
    "Udimet 700": (
        "u700", "udimet700",
    ),
    "Udimet 720": (
        "u720", "udimet720",
    ),

    # MA (Mechanical Alloying) ODS alloys
    "MA 754 (Longitudinal)": (
        "ma754", "ma 754", "ma-754", "ods 754",
    ),
    "MA 754 (Transverse)": (
        "ma754 transverse", "ma 754 trans",
    ),
    "MA 956": (
        "ma956", "ma-956", "ods 956",
    ),
    "MA 956 (Longitudinal)": (
        "ma956 long", "ma 956 longitudinal",
    ),
    "MA 6000": (
        "ma6000", "ma-6000", "ods 6000",
    ),
    "MA 6000 (Longitudinal)": (
        "ma6000 long", "ma 6000 longitudinal",
    ),
    "MA 6000 (Transverse)": (
        "ma6000 trans", "ma 6000 transverse",
    ),

    # MAR-M family
    "MAR-M 246": (
        "marm246", "mar-m246", "marm 246",
    ),
    "MAR-M-247": (
        "marm247", "mar-m247", "marm 247", "mar m 247",
    ),
    "MAR-M200 (DS)": (
        "marm200", "mar-m200", "marm 200",
    ),
    "MAR-M246 (Hf) (single crystal)": (
        "marm246hf", "mar-m246 hf",
    ),

    # IN-7xx family
    "IN-738": (
        "in738", "in-738", "inconel 738",
    ),
    "IN-792": (
        "in792", "in-792", "inconel 792",
    ),

    # Other nickel alloys
    "Nickel 200": (
        "ni200", "nickel200", "pure nickel 200",
    ),
    "Nickel 201": (
        "ni201", "nickel201",
    ),
    "Nickel 270": (
        "ni270", "nickel270", "ni 270",
    ),
    "Nickel 301": (
        "ni301", "nickel301", "ni 301",
    ),
    "Nickel (electroformed)": (
        "electroformed nickel", "ed nickel", "electrodeposited nickel",
    ),
    "ED Nickel": (
        "ednickel", "electrodeposited ni",
    ),

    # Monel family
    "K-Monel": (
        "kmonel", "k monel", "monel k", "k-500",  # Note: K-Monel and K-500 are related
    ),
    "K-Monel (annealed)": (
        "k-monel annealed", "kmonel annealed",
    ),
    "Monel 400": (
        "monel400", "alloy 400", "uns n04400",
    ),
    "Monel K-500": (
        "k500", "monel k500", "uns n05500",
    ),

    # MP35N and related
    "MP35N": (
        "mp35", "mp 35n", "multiphase 35n",
    ),
    "MP159": (
        "mp 159",
    ),
    "MP98T": (
        "mp 98t",
    ),

    # A-286
    "A-286": (
        "a286", "a 286", "uns s66286", "aisi 660",
    ),
    "A286 (ST + Aged)": (
        "a286 sta", "a-286 sta", "a286 aged",
    ),
    "A-286 SS": (
        "a286 stainless", "a-286 ss",
    ),

    # JBK-75
    "JBK-75": (
        "jbk75", "jbk 75",
    ),
    "JBK-75 (ST + Aged)": (
        "jbk75 sta", "jbk-75 aged",
    ),

    # Elgiloy
    "Elgiloy": (
        "elgi", "phynox",
    ),

    # NASA-HR1
    "NASA-HR1": (
        "nasahr1", "nasa hr1", "hr1",
    ),

    # Ni-SPAN-C
    "Ni-SPAN-C (alloy 902)": (
        "nispan", "ni-span", "alloy 902", "902",
    ),

    # -------------------------------------------------------------------------
    # STAINLESS STEELS - AUSTENITIC (300 series)
    # -------------------------------------------------------------------------
    "304 Stainless Steel": (
        "304", "ss304", "304ss", "aisi 304", "uns s30400", "18-8", "18/8",
        "304 ss", "stainless 304",
    ),
    "304L": (
        "304l", "ss304l", "304lss", "aisi 304l", "uns s30403",
        "304l ss", "304 l",
    ),
    "304N Stainless Steel": (
        "304n", "ss304n", "304nss", "aisi 304n",
    ),
    "304 ELC SS": (
        "304elc", "304 elc", "extra low carbon 304",
    ),
    "305 Stainless Steel": (
        "305", "ss305", "305ss", "aisi 305",
    ),
    "306 Stainless Steel": (
        "306", "ss306", "306ss",
    ),
    "309S Stainless Steel": (
        "309s", "ss309s", "309sss", "aisi 309s",
    ),
    "310 Stainless Steel": (
        "310", "ss310", "310ss", "aisi 310", "uns s31000",
    ),
    "310 SS": (
        "310ss", "ss 310",
    ),
    "316 Stainless Steel": (
        "316", "ss316", "316ss", "aisi 316", "uns s31600",
        "316 ss", "stainless 316",
    ),
    "316L": (
        "316l", "ss316l", "316lss", "aisi 316l", "uns s31603",
        "316l ss", "316 l",
    ),
    "316 SS": (
        "ss 316", "316 stainless",
    ),
    "317 Stainless Steel": (
        "317", "ss317", "317ss", "aisi 317",
    ),
    "321 Stainless Steel": (
        "321", "ss321", "321ss", "aisi 321", "uns s32100",
    ),
    "AISI 321": (
        "aisi321", "321 aisi",
    ),
    "347 Stainless Steel": (
        "347", "ss347", "347ss", "aisi 347", "uns s34700",
    ),
    "348 Stainless Steel": (
        "348", "ss348", "348ss", "aisi 348",
    ),
    "300 Series Stainless Steel": (
        "300 series", "300 ss", "austenitic stainless",
    ),

    # High-nitrogen austenitic
    "21-6-9 Stainless Steel": (
        "21-6-9", "2169", "nitronic 40", "uns s21900",
    ),
    "21-6-9 + 0.3N (Nitronic 40)": (
        "nitronic 40 high n",
    ),
    "21-6-9 + 0.1N (Nitronic 40)": (
        "nitronic 40 low n",
    ),
    "22-13-5 Stainless": (
        "22-13-5", "221305", "nitronic 50", "uns s20910",
    ),
    "Nitronic 33": (
        "nitronic33", "18-2-12",
    ),
    "Nitronic 60": (
        "nitronic60", "uns s21800",
    ),
    "18-18 Plus": (
        "1818plus", "18-18plus",
    ),
    "18-3-Mn": (
        "183mn", "18-3mn",
    ),
    "Tenelon": (
        "tenel",
    ),

    # -------------------------------------------------------------------------
    # STAINLESS STEELS - MARTENSITIC (400 series)
    # -------------------------------------------------------------------------
    "410 Stainless Steel": (
        "410", "ss410", "410ss", "aisi 410", "uns s41000",
    ),
    "430 Stainless Steel": (
        "430", "ss430", "430ss", "aisi 430", "uns s43000",
    ),
    "430F Steel": (
        "430f", "ss430f", "430fss",
    ),
    "440A Steel": (
        "440a", "ss440a", "440ass", "aisi 440a",
    ),
    "440A Stainless Steel": (
        "440a stainless", "440a ss",
    ),
    "440C": (
        "440c", "ss440c", "aisi 440c", "uns s44004",
    ),
    "440C Stainless Steel": (
        "440c stainless", "440c ss",
    ),

    # -------------------------------------------------------------------------
    # STAINLESS STEELS - PRECIPITATION HARDENING
    # -------------------------------------------------------------------------
    "17-4 PH": (
        "174ph", "17-4ph", "17-4 ph", "630", "uns s17400",
        "174 ph", "17 4 ph",
    ),
    "17-4 PH (TH 1050)": (
        "174ph th1050", "17-4ph th1050", "17-4 th1050",
    ),
    "17-7 PH SS": (
        "177ph", "17-7ph", "17-7 ph", "631", "uns s17700",
    ),
    "15-5 PH": (
        "155ph", "15-5ph", "15-5 ph", "xm-12", "uns s15500",
    ),
    "PH 13-8 Mo": (
        "ph138mo", "13-8 mo", "138mo", "xm-13", "uns s13800",
    ),
    "PH 15-7 Mo": (
        "ph157mo", "15-7 mo", "157mo",
    ),
    "AM-350": (
        "am350", "am 350",
    ),
    "AM-355": (
        "am355", "am 355",
    ),
    "Custom 450": (
        "custom450", "cust 450",
    ),
    "Custom 455": (
        "custom455", "cust 455",
    ),

    # Other specialty stainless
    "D 879 Stainless": (
        "d879", "d-879", "d 879",
    ),
    "CG 27 Stainless": (
        "cg27", "cg-27", "cg 27",
    ),
    "CG-27 (precipitated)": (
        "cg27 precip", "cg-27 precip",
    ),
    "RA 220": (
        "ra220", "ra-220",
    ),

    # -------------------------------------------------------------------------
    # CARBON AND LOW-ALLOY STEELS
    # -------------------------------------------------------------------------
    "1008 Steel": (
        "1008", "aisi 1008", "sae 1008",
    ),
    "1010 Steel": (
        "1010", "aisi 1010", "sae 1010",
    ),
    "1018 Steel": (
        "1018", "aisi 1018", "sae 1018",
    ),
    "1020 Steel": (
        "1020", "aisi 1020", "sae 1020",
    ),
    "C1025 Steel": (
        "1025", "c1025", "aisi 1025",
    ),
    "1040 Steel": (
        "1040", "aisi 1040", "sae 1040",
    ),
    "1042 Steel": (
        "1042", "aisi 1042", "sae 1042",
    ),
    "1042 Steel (Q&T)": (
        "1042 qt", "1042 quenched",
    ),
    "1042 (Normalized)": (
        "1042 norm", "1042 normalized",
    ),
    "1042 Steel (Normalized)": (
        "1042 steel norm",
    ),
    "1045 Steel": (
        "1045", "aisi 1045", "sae 1045",
    ),
    "1080 Steel": (
        "1080", "aisi 1080", "sae 1080",
    ),
    "1080 Steel (Transverse)": (
        "1080 trans", "1080 transverse",
    ),
    "1095 Steel": (
        "1095", "aisi 1095", "sae 1095",
    ),

    # 41xx series
    "4130 Steel": (
        "4130", "aisi 4130", "sae 4130", "uns g41300",
    ),
    "4140 Steel": (
        "4140", "aisi 4140", "sae 4140", "uns g41400",
    ),
    "4140 Steel (normalized)": (
        "4140 norm", "4140 normalized",
    ),

    # 43xx series
    "4340 Steel (1652F austen.)": (
        "4340 1652f", "4340 austenitized",
    ),
    "SAE 4340 Steel Grade A": (
        "4340 grade a", "4340a", "sae 4340a",
    ),
    "SAE 4340 Steel Grade B VAR": (
        "4340 grade b", "4340b var", "4340 var",
    ),
    "SAE 4340 Steel with Cadmium Plating Treatment A": (
        "4340 cad a", "4340 cadmium a",
    ),
    "SAE 4340 Steel with Cadmium Plating Treatment B": (
        "4340 cad b", "4340 cadmium b",
    ),

    # Other alloy steels
    "4620 Steel": (
        "4620", "aisi 4620", "sae 4620",
    ),
    "8620 Steel": (
        "8620", "aisi 8620", "sae 8620",
    ),
    "9310 Steel": (
        "9310", "aisi 9310", "sae 9310",
    ),
    "300M Steel": (
        "300m", "aisi 300m",
    ),
    "305 Steel": (
        "305 carbon", "sae 305",
    ),
    "309S Steel": (
        "309s carbon",
    ),
    "216 Steel": (
        "216", "sae 216",
    ),

    # Armco Iron
    "Armco Iron": (
        "armco", "pure iron", "ingot iron",
    ),

    # -------------------------------------------------------------------------
    # HIGH-STRENGTH LOW-ALLOY STEELS
    # -------------------------------------------------------------------------
    "HY 80": (
        "hy80", "hy-80", "mil-s-16216",
    ),
    "HY-80 Steel": (
        "hy80 steel",
    ),
    "HY 100": (
        "hy100", "hy-100",
    ),
    "HY-100 Steel": (
        "hy100 steel",
    ),
    "HY-130": (
        "hy130", "hy 130",
    ),

    # HP steels
    "HP 9-4-20": (
        "hp9420", "hp 9-4-20", "hp9-4-20",
    ),
    "HP 9-4-30": (
        "hp9430", "hp 9-4-30", "hp9-4-30",
    ),

    # Tool steels
    "H-11": (
        "h11", "h-11 steel", "aisi h11",
    ),
    "H-11 Tool Steel": (
        "h11 tool",
    ),
    "H-11 Steel": (
        "h-11steel",
    ),

    # D6AC
    "D6AC Steel (300C tempered)": (
        "d6ac 300c", "d6ac 300",
    ),
    "D6AC Steel (600C tempered)": (
        "d6ac 600c", "d6ac 600",
    ),

    # -------------------------------------------------------------------------
    # MARAGING STEELS
    # -------------------------------------------------------------------------
    "250 Maraging Steel": (
        "maraging 250", "18ni250", "18ni 250",
    ),
    "250 Maraging": (
        "250 mar",
    ),
    "18 Ni 250 Maraging Steel": (
        "18ni250 maraging",
    ),
    "Maraging Steel 200": (
        "maraging 200", "18ni200",
    ),
    "Maraging Steel 250": (
        "marage 250",
    ),
    "Maraging Steel 300": (
        "maraging 300", "18ni300",
    ),
    "Maraging Steel 350": (
        "maraging 350", "18ni350",
    ),

    # -------------------------------------------------------------------------
    # PRESSURE VESSEL / PIPELINE STEELS
    # -------------------------------------------------------------------------
    "A 515-G70": (
        "a515", "a515-70", "a515 grade 70",
    ),
    "A515-Gr. 70": (
        "a515 gr70",
    ),
    "A 516": (
        "a516", "astm a516",
    ),
    "A 517-F (T-1)": (
        "a517f", "a517-f", "t-1 steel",
    ),
    "A-517 Steel": (
        "a517", "a 517",
    ),
    "A517-F (T-1)": (
        "a517 f t1",
    ),
    "A 533-B": (
        "a533b", "a533-b", "a 533b",
    ),
    "A 372-IV": (
        "a372", "a372-4", "a372 class iv",
    ),
    "A372 (grade J)": (
        "a372j", "a372 grade j",
    ),
    "A372 (class 4)": (
        "a372 cls4", "a372 class 4",
    ),
    "A 617-F (T-1)": (
        "a617f", "a617-f",
    ),
    "A106-Gr. B": (
        "a106", "a106b", "a106 grade b",
    ),
    "A212-61T (normalized)": (
        "a212", "a212-61t",
    ),
    "A302 Steel": (
        "a302", "a 302",
    ),
    "A302B": (
        "a302 b", "a302-b",
    ),

    # Pipeline steels
    "X42 Pipeline Steel": (
        "x42", "api x42",
    ),
    "X52 Pipeline Steel": (
        "x52", "api x52",
    ),
    "X52 Pipeline (6.9 MPa)": (
        "x52 6.9mpa",
    ),
    "X60 Pipeline Steel": (
        "x60", "api x60",
    ),
    "X70 Pipeline Steel": (
        "x70", "api x70",
    ),
    "X100 Pipeline Steel": (
        "x100", "api x100",
    ),

    # AerMet
    "AerMet 100 (peak aged)": (
        "aermet100", "aermet 100", "aer met 100",
    ),

    # Fe-Ni-Co
    "Fe-9Ni-4Co-0.20C": (
        "fe9ni4co", "9ni-4co",
    ),

    # -------------------------------------------------------------------------
    # TITANIUM ALLOYS
    # -------------------------------------------------------------------------
    "Titanium (pure)": (
        "pure titanium", "cp titanium", "ti pure",
    ),
    "Titanium (CP)": (
        "cp ti", "commercially pure ti",
    ),
    "CP Titanium Grade 2": (
        "cp grade 2", "ti grade 2", "cp ti grade 2",
    ),
    "Ti-6Al-4V": (
        "ti64", "ti-64", "ti6al4v", "ti 6al 4v", "6al4v", "ti6-4",
        "grade 5", "uns r56400",
    ),
    "Ti-6Al-4V (Annealed)": (
        "ti64 annealed", "ti-6al-4v ann",
    ),
    "Ti-6Al-4V (STA)": (
        "ti64 sta", "ti-6al-4v sta", "ti64 aged",
    ),
    "Ti-6Al-4V (STA 48 MPa)": (
        "ti64 sta 48mpa",
    ),
    "Ti-5Al-2.5Sn (ELI)": (
        "ti5al25sn", "ti-5al-2.5sn", "ti 5-2.5", "grade 6 eli",
    ),
    "Ti-6Al-2.5Sn ELI": (
        "ti6al25sn", "ti-6al-2.5sn",
    ),
    "Ti-6Al-2Sn-4Zr-2Mo": (
        "ti6242", "ti-6242", "ti 6al 2sn 4zr 2mo",
    ),
    "Ti-6Al-6V-2Sn": (
        "ti662", "ti-6al-6v-2sn",
    ),
    "Ti-10V-2Fe-3Al": (
        "ti1023", "ti-10-2-3",
    ),
    "Ti-15V-3Al-3Cr-3Sn": (
        "ti15333", "ti-15-3-3-3", "beta c",
    ),
    "Ti-11.5Mo-6Zr-4.5Sn (STA)": (
        "beta iii", "ti beta iii",
    ),
    "Ti-24Al-11Nb": (
        "ti24al11nb", "ti-24al-11nb", "alpha-2 ti3al",
    ),
    "Gamma-TiAl Alloy": (
        "gamma tial", "tial", "ti-al gamma",
    ),
    "Alpha-2 TiAl Alloy": (
        "alpha2 tial", "ti3al",
    ),

    # -------------------------------------------------------------------------
    # COPPER ALLOYS
    # -------------------------------------------------------------------------
    "Copper (OFHC)": (
        "ofhc", "ofhc copper", "oxygen free copper", "c10100",
    ),
    "OFHC Copper": (
        "ofhc cu",
    ),
    "Oxygen-free Copper": (
        "ofc", "of copper",
    ),
    "ETP Copper": (
        "etp", "electrolytic copper", "c11000",
    ),
    "Aluminum Bronze": (
        "al bronze", "albronze", "c95400",
    ),
    "Be-Cu Alloy 25": (
        "becu25", "be-cu 25", "beryllium copper 25", "c17200",
    ),
    "Be-Cu Alloy": (
        "becu", "be-cu", "beryllium copper",
    ),
    "Ba-Cu (Alloy 25)": (
        "bacu25",
    ),
    "Beryllium Copper": (
        "beryllium cu", "becu alloy",
    ),
    "GRCop-84 (Cu-8Cr-4Nb)": (
        "grcop84", "grcop-84", "grcop 84", "cu8cr4nb",
    ),
    "NARloy-Z (Cu-3Ag-0.5Zr)": (
        "narloyz", "narloy-z", "narloy z", "cu3ag05zr",
    ),
    "Phosphor Bronze": (
        "phos bronze", "c51000",
    ),
    "Silicon Bronze": (
        "si bronze", "c65500",
    ),
    "70-30 Brass": (
        "7030 brass", "c26000",
    ),
    "70/30 Brass": (
        "70 30 brass", "cartridge brass",
    ),
    "60/40 Brass": (
        "6040 brass", "muntz metal",
    ),
    "Naval Brass": (
        "naval", "c46400",
    ),
    "90/10 Cupronickel": (
        "9010 cupronickel", "c70600",
    ),
    "70/30 Cupronickel": (
        "7030 cupronickel", "c71500",
    ),

    # -------------------------------------------------------------------------
    # ALUMINUM ALLOYS
    # -------------------------------------------------------------------------
    "1100-T0 Aluminum": (
        "1100", "al1100", "1100 aluminum", "1100t0",
    ),
    "1100 Aluminum": (
        "al 1100", "1100 al",
    ),
    "2011 Aluminum": (
        "2011", "al2011",
    ),
    "2014 Aluminum": (
        "2014", "al2014",
    ),
    "2024 Aluminum": (
        "2024", "al2024", "2024-t3", "2024-t4",
    ),
    "2219 Aluminum": (
        "2219", "al2219",
    ),
    "5052 Aluminum": (
        "5052", "al5052",
    ),
    "5083 Aluminum": (
        "5083", "al5083",
    ),
    "5086 Aluminum": (
        "5086", "al5086",
    ),
    "6061-T6 Aluminum": (
        "6061", "al6061", "6061t6", "6061-t6", "6061 t6",
    ),
    "6061 Aluminum": (
        "al 6061",
    ),
    "7050 Aluminum": (
        "7050", "al7050",
    ),
    "7075-T73 Aluminum": (
        "7075", "al7075", "7075t73", "7075-t73", "7075 t73",
    ),
    "7075 Aluminum": (
        "al 7075", "7075 al",
    ),

    # -------------------------------------------------------------------------
    # COBALT ALLOYS
    # -------------------------------------------------------------------------
    "Stellite 6": (
        "stellite6", "haynes 6",
    ),
    "Stellite 21": (
        "stellite21", "haynes 21",
    ),
    "L-605": (
        "l605", "haynes 25", "alloy 25",
    ),
    "X-45 (superalloy)": (
        "x45", "x-45",
    ),

    # -------------------------------------------------------------------------
    # SINGLE CRYSTAL SUPERALLOYS
    # -------------------------------------------------------------------------
    "CM SX-2 (single crystal)": (
        "cmsx2", "cmsx-2", "sx2",
    ),
    "CM SX-3 (std)": (
        "cmsx3", "cmsx-3", "sx3",
    ),
    "CM SX-4C (single crystal)": (
        "cmsx4c", "cmsx-4c", "sx4c",
    ),
    "CM SX-4D": (
        "cmsx4d", "cmsx-4d", "sx4d",
    ),
    "CM-SX5": (
        "cmsx5", "cmsx-5", "sx5",
    ),
    "PWA 1480 (single crystal)": (
        "pwa1480", "pwa-1480", "1480",
    ),
    "PW1480": (
        "pw1480", "pw 1480",
    ),
    "PWA 1480E (111 plane)": (
        "pwa1480e",
    ),
    "AF-56 (single crystal)": (
        "af56", "af-56",
    ),
    "AF-115 (PM)": (
        "af115", "af-115",
    ),
    "RR 2000": (
        "rr2000", "rr-2000",
    ),

    # -------------------------------------------------------------------------
    # POWDER METALLURGY
    # -------------------------------------------------------------------------
    "MERL 76": (
        "merl76",
    ),
    "MERL 76 (PM)": (
        "merl76 pm", "merl 76 powder",
    ),

    # -------------------------------------------------------------------------
    # SPECIALTY ALLOYS
    # -------------------------------------------------------------------------
    "Inco 4005 (experimental)": (
        "inco4005", "inco 4005",
    ),
}


# =============================================================================
# NORMALIZATION AND LOOKUP
# =============================================================================

def normalize(name: str) -> str:
    """Normalize a material name for matching.

    - Lowercase
    - Replace common separators with space
    - Collapse multiple spaces
    - Strip leading/trailing whitespace
    """
    if not name:
        return ""

    # Lowercase
    s = name.lower()

    # Replace separators with space
    s = re.sub(r'[-_/\\()]', ' ', s)

    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s)

    # Strip
    s = s.strip()

    return s


# Build reverse lookup at module load time
CANONICAL_NAMES: dict[str, str] = {}

def _build_reverse_lookup() -> None:
    """Build the reverse lookup dictionary."""
    for canonical, aliases in MATERIAL_ALIASES.items():
        # Map the canonical name to itself (normalized)
        norm_canonical = normalize(canonical)
        CANONICAL_NAMES[norm_canonical] = canonical

        # Map each alias to its canonical name
        for alias in aliases:
            norm_alias = normalize(alias)
            if norm_alias and norm_alias not in CANONICAL_NAMES:
                CANONICAL_NAMES[norm_alias] = canonical

# Build on import
_build_reverse_lookup()


def get_canonical_name(query: str) -> Optional[str]:
    """Get the canonical material name for a query string.

    Args:
        query: User-provided material name (e.g., "718", "SS316L")

    Returns:
        Canonical name if found in aliases, None otherwise.

    Examples:
        >>> get_canonical_name("718")
        'Inconel 718'
        >>> get_canonical_name("SS316L")
        '316L'
        >>> get_canonical_name("unknown alloy")
        None
    """
    norm = normalize(query)
    return CANONICAL_NAMES.get(norm)


def get_all_aliases(canonical: str) -> tuple[str, ...]:
    """Get all aliases for a canonical material name.

    Args:
        canonical: The canonical material name.

    Returns:
        Tuple of aliases, empty tuple if not found.
    """
    return MATERIAL_ALIASES.get(canonical, ())


# =============================================================================
# ALLOY NUMBER EXTRACTION (for fuzzy fallback)
# =============================================================================

# Pattern to extract alloy numbers (e.g., "718", "316L", "6061")
ALLOY_NUMBER_PATTERN = re.compile(r'\b(\d{3,4}[A-Z]?)\b', re.IGNORECASE)

def extract_alloy_numbers(name: str) -> set[str]:
    """Extract potential alloy designation numbers from a material name.

    Used as fallback when alias lookup fails.

    Examples:
        >>> extract_alloy_numbers("Inconel 718")
        {'718'}
        >>> extract_alloy_numbers("316L Stainless")
        {'316L'}
    """
    matches = ALLOY_NUMBER_PATTERN.findall(name)
    return {m.upper() for m in matches}


# =============================================================================
# FAMILY KEYWORDS (for generic queries)
# =============================================================================

FAMILY_KEYWORDS: dict[str, str] = {
    # Nickel-based
    "inconel": "nickel_alloy",
    "incoloy": "nickel_alloy",
    "hastelloy": "nickel_alloy",
    "haynes": "nickel_alloy",
    "waspaloy": "nickel_alloy",
    "rene": "nickel_alloy",
    "udimet": "nickel_alloy",
    "astroloy": "nickel_alloy",
    "monel": "nickel_alloy",
    "nickel": "nickel_alloy",

    # Stainless
    "stainless": "stainless_steel",
    "austenitic": "stainless_steel",
    "ferritic": "stainless_steel",
    "martensitic": "stainless_steel",
    "duplex": "stainless_steel",
    "nitronic": "stainless_steel",

    # Titanium
    "titanium": "titanium",
    "ti-": "titanium",
    "ti6al": "titanium",

    # Copper
    "copper": "copper",
    "bronze": "copper",
    "brass": "copper",
    "cupronickel": "copper",

    # Aluminum
    "aluminum": "aluminum",
    "aluminium": "aluminum",

    # Steel
    "steel": "steel",
    "maraging": "steel",
    "carbon steel": "steel",
}

def detect_material_family(query: str) -> Optional[str]:
    """Detect material family from query keywords.

    Used when no specific alloy match is found.

    Returns:
        Material family string or None.
    """
    norm = normalize(query)

    for keyword, family in FAMILY_KEYWORDS.items():
        if keyword in norm:
            return family

    return None
