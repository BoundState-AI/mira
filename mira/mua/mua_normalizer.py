"""
MUA Issues Normalizer + Rationale Pattern Extractor

Pure regex/keyword matching. No LLM calls.

normalize_issues(raw_issue_text) -> list[str]  (canonical domain codes)
extract_patterns(rationale_text) -> list[dict]  (pattern_code, matched_text)
extract_evidence(rationale_text, application_text) -> list[dict]
classify_mua_type(application_text, issue_text, material) -> str
"""

import re
from typing import List, Dict, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# CONCERN DOMAIN NORMALIZER
# ═══════════════════════════════════════════════════════════════════════════

# Direct token map: handles pre-normalized values from issues_cleaned
# These are exact string matches (case-insensitive) for single tokens
_DIRECT_TOKEN_MAP = {
    # FLAMM
    'flammability': 'FLAMM',
    'flam': 'FLAMM',
    'flamm': 'FLAMM',
    # SCC
    'scc': 'SCC',
    'stress_corrosion': 'SCC',
    # CORR
    'corrosion': 'CORR',
    'dissimilar_metals': 'CORR',
    'galvanic': 'CORR',
    # TOX
    'toxicity': 'TOX',
    'offgassing': 'TOX',
    'offgas': 'TOX',
    'tox': 'TOX',
    # TVS
    'tvs': 'TVS',
    'outgassing': 'TVS',
    'thermal_vacuum': 'TVS',
    # FC
    'fluid_compat': 'FC',
    'o2_compat': 'FC',
    'oxygen_compat': 'FC',
    'propellant_compat': 'FC',
    # FORBIDDEN
    'forbidden': 'FORBIDDEN',
    'prohibited': 'FORBIDDEN',
    # FUNGUS
    'fungus': 'FUNGUS',
    'fungus_resistance': 'FUNGUS',
}

# Each entry: (compiled regex, canonical domain code)
# Order matters — more specific patterns first to avoid false positives
_DOMAIN_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # FLAMM — flammability
    (re.compile(r'\bflamm?abil[a-z]*\b', re.I), 'FLAMM'),  # flammability, flammibility (typo)
    (re.compile(r'\bflamm?\.?\b', re.I), 'FLAMM'),       # Flamm, Flamm., Flam, Flam.
    (re.compile(r'\bFLM?\b'), 'FLAMM'),                   # FLM, FL (as in "FL rated X")
    (re.compile(r'\bflammable\b', re.I), 'FLAMM'),
    (re.compile(r'\bignition\b', re.I), 'FLAMM'),
    (re.compile(r'\bcombust(?:ion|ible)\b', re.I), 'FLAMM'),
    (re.compile(r'\bfire\s+(?:hazard|propagat|barrier)\b', re.I), 'FLAMM'),
    (re.compile(r'\b[XABC][\s-]*rated\s+(?:for\s+)?[Ff]lam', re.I), 'FLAMM'),  # "X rated Flam", "B rated for Flam"
    (re.compile(r'\bTest\s+1\b', re.I), 'FLAMM'),
    (re.compile(r'\bTest\s+17\b', re.I), 'FLAMM'),

    # SCC — stress corrosion cracking
    (re.compile(r'\bstress\s+corrosion\b', re.I), 'SCC'),
    (re.compile(r'\bS\.?C\.?C\.?\b'), 'SCC'),
    (re.compile(r'\bMSFC[-\s]?(?:STD[-\s]?3029|SPEC[-\s]?522)\b', re.I), 'SCC'),
    (re.compile(r'\bsustained\s+load\b', re.I), 'SCC'),
    (re.compile(r'\bcracking\s+agent\b', re.I), 'SCC'),

    # FC — fluid compatibility (BEFORE CORR to catch "compatibility" correctly)
    (re.compile(r'\bfluid\s+(?:systems?\s+)?compatib', re.I), 'FC'),
    (re.compile(r'\bcompatib\w*\s+with\s+(?:hydrazine|nitrogen\s+tetroxide|NTO|MMH|UDMH)\b', re.I), 'FC'),
    (re.compile(r'\b(?:propellant|fuel|oxidizer)\s+compatib', re.I), 'FC'),
    (re.compile(r'\b(?:O2|oxygen|LOX|GOX)\s+compatib', re.I), 'FC'),
    (re.compile(r'\bLOX\s+compat', re.I), 'FC'),
    (re.compile(r'\bGOX\s+compat', re.I), 'FC'),
    (re.compile(r'\boxy\.?\s+comp\.?\b', re.I), 'FC'),    # "oxy comp.", "O2 COMPATIBILITY"
    (re.compile(r'\bO.?\s*COMPAT', re.I), 'FC'),          # "O₂ COMPATIBILITY"
    (re.compile(r'\b(?:hydrazine|nitrogen\s+tetroxide|NTO)\b', re.I), 'FC'),
    (re.compile(r'\bMSFC[-\s]?STD[-\s]?1813\b', re.I), 'FC'),
    (re.compile(r'\bFSC\b'), 'FC'),                        # Fluid Systems Compatibility
    (re.compile(r'\bLOX\b'), 'FC'),                        # bare "LOX" in issue field = fluid compat
    (re.compile(r'\bGOX\b'), 'FC'),                        # bare "GOX" in issue field

    # CORR — corrosion (general, galvanic, dissimilar metals)
    (re.compile(r'\bcorrosion\b', re.I), 'CORR'),
    (re.compile(r'\bCORR?\b'), 'CORR'),                    # CORR, COR (uppercase)
    (re.compile(r'\bCorr?\.?\b'), 'CORR'),                 # Corr, Corr., Cor (mixed case)
    (re.compile(r'\bgalvanic\b', re.I), 'CORR'),
    (re.compile(r'\bdissimilar[\s_]+metal', re.I), 'CORR'),
    (re.compile(r'\bMSFC[-\s]?SPEC[-\s]?250\b', re.I), 'CORR'),

    # TOX — toxicity / offgassing
    (re.compile(r'\btoxic(?:ity|ological)?\b', re.I), 'TOX'),
    (re.compile(r'\btox(?:ity|cit[yi])?\b', re.I), 'TOX'), # Tox, Tox., Toxity, Toxcity
    (re.compile(r'\boffgas(?:sing|sed)?\b', re.I), 'TOX'),
    (re.compile(r'\boff[\s-]?gas\b', re.I), 'TOX'),
    (re.compile(r'\bcrew\s+exposure\b', re.I), 'TOX'),
    (re.compile(r'\bTLV\b'), 'TOX'),
    (re.compile(r'\bTest\s+7\b', re.I), 'TOX'),
    (re.compile(r'\bodor\b', re.I), 'TOX'),

    # TVS — thermal vacuum stability
    (re.compile(r'\bthermal\s+vac(?:uum)?\.?\s*(?:stability)?\.?\b', re.I), 'TVS'),  # "Thermal Vac. Stability", "Thermal Vac"
    (re.compile(r'\bTVS\b', re.I), 'TVS'),                # TVS, tvs (case-insensitive now)
    (re.compile(r'\bVCM\b'), 'TVS'),                       # Volatile Condensable Material
    (re.compile(r'\bout[\s-]?gas(?:sing|sed)?\b', re.I), 'TVS'),  # outgassing, out gas, out-gas
    (re.compile(r'\bTML\b'), 'TVS'),
    (re.compile(r'\bCVCM\b'), 'TVS'),
    (re.compile(r'\bASTM\s+E595\b', re.I), 'TVS'),
    (re.compile(r'\bTV\s+(?:rated|not\s+rated)\b', re.I), 'TVS'),  # "TV rated B", "TV not rated"

    # FORBIDDEN — forbidden / prohibited material
    (re.compile(r'\bforbidden\s+material', re.I), 'FORBIDDEN'),
    (re.compile(r'\bforbidden\b', re.I), 'FORBIDDEN'),
    (re.compile(r'\bprohibited\s+material', re.I), 'FORBIDDEN'),

    # FUNGUS — fungus resistance per MIL-STD-454
    (re.compile(r'\bfungus\b', re.I), 'FUNGUS'),
    (re.compile(r'\bfungal\b', re.I), 'FUNGUS'),
    (re.compile(r'\bMIL[-\s]?STD[-\s]?454\b', re.I), 'FUNGUS'),
    (re.compile(r'\bfungus\s+(?:resistant|resistance|nutrient)\b', re.I), 'FUNGUS'),
    (re.compile(r'\bGroup\s+II\s+Fungus\b', re.I), 'FUNGUS'),
]

# Splitter: break compound issues into tokens
_ISSUE_SPLITTERS = re.compile(
    r"""
    \s*[,;/&]\s*                  # comma, semicolon, slash, ampersand
    | \s+and\s+                   # " and "
    | \s*\n\s*                    # newlines
    | \s*\d+[.)]\s*              # numbered lists: "1." "2)" etc.
    """,
    re.VERBOSE | re.IGNORECASE
)


def normalize_issues(raw_issue: Optional[str],
                     issues_cleaned: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """Normalize raw issue text into canonical concern domain codes.

    Trust hierarchy:
    1. Raw issue text is primary — always scanned via regex
    2. issues_cleaned tokens are secondary — used via direct token map ONLY
       when raw_issue is empty/missing (v6_cleaned tagger over-extracts from
       rationale context, producing false tags like "corrosion" from
       "corrosion protection" or "workmanship" for flammability-only MUAs)

    Args:
        raw_issue: The raw 'issue' field from extraction
        issues_cleaned: Pre-parsed issues from v6_cleaned (optional fallback)

    Returns:
        (matched_domains, unmapped_fragments)
        - matched_domains: list of canonical codes like ['FLAMM', 'TOX']
        - unmapped_fragments: issue fragments that didn't match any domain
    """
    domains = set()
    unmapped = []
    has_raw = bool(raw_issue and raw_issue.strip())

    # Phase 1: Direct token map for issues_cleaned — ONLY when raw_issue is absent
    if issues_cleaned and not has_raw:
        for token in issues_cleaned:
            if not token:
                continue
            token_lower = str(token).strip().lower()
            if token_lower in _DIRECT_TOKEN_MAP:
                domains.add(_DIRECT_TOKEN_MAP[token_lower])

    # Phase 2: Regex matching on raw issue text ONLY (never issues_cleaned)
    if not has_raw and not domains:
        return [], []

    if has_raw:
        text = raw_issue.strip()

        # Split compound issues into fragments
        fragments = []
        parts = _ISSUE_SPLITTERS.split(text)
        for part in parts:
            part = part.strip()
            if part and len(part) > 1:
                fragments.append(part)

        # Match fragments against domain patterns
        for fragment in fragments:
            fragment_matched = False
            for pattern, domain_code in _DOMAIN_PATTERNS:
                if pattern.search(fragment):
                    domains.add(domain_code)
                    fragment_matched = True
            if not fragment_matched:
                cleaned = re.sub(r'[^a-zA-Z\s]', '', fragment).strip()
                if cleaned and len(cleaned) > 2:
                    unmapped.append(fragment)

        # Scan full text for patterns that might span fragment boundaries
        for pattern, domain_code in _DOMAIN_PATTERNS:
            if pattern.search(text):
                domains.add(domain_code)

    return sorted(domains), unmapped


# ═══════════════════════════════════════════════════════════════════════════
# RATIONALE PATTERN EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════

_RATIONALE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ('small_amount',
     re.compile(
         r'small\s+(?:amount|quantit(?:y|ies))'  # "small quantity" / "small quantities"
         r'|minimal\s+(?:amount|quantity)'
         r'|negligible'
         r'|(?:used|present)\s+in\s+(?:such\s+)?small'
         r'|limited\s+(?:amount|quantity)',
         re.I)),
    ('metallic_enclosure',
     re.compile(
         r'metallic\s+enclosure'
         r'|alumini?um\s+(?:alloy\s+)?(?:housing|enclosure|box|closure)'  # US + British spelling, with optional "alloy"
         r'|metal(?:lic)?\s+(?:housing|box|case|container|enclosure)'
         r'|enclosed\s+(?:in|by|within)'          # "enclosed by the camera housing"
         r'|contained\s+within'
         r'|closed\s+metal'                        # "closed metal box"
         r'|(?:totally|completely|fully)\s+contained'
         r'|(?:inside|within)\s+(?:an?\s+)?(?:alumini?um|metal)',  # "inside an aluminum alloy enclosure"
         re.I)),
    ('no_ignition_source',
     re.compile(
         r'no\s+ignition\s+(?:source|mechanism)'
         r'|(?:un|not\s+)powered'                  # "unpowered" / "not powered"
         r'|no\s+power\s+(?:is\s+)?(?:applied|available)'  # "no power is applied"
         r'|powered?\s+off'                        # "powered off" / "power off"
         r'|not\s+(?:be\s+)?exposed\s+to\s+(?:a\s+)?(?:flame|ignition|fire)'  # "not exposed to a flame source"
         r'|no\s+(?:flame|fire)\s+source'
         r'|no\s+propagation\s+path',
         re.I)),
    ('heat_sink',
     re.compile(
         r'heat\s*sink'
         r'|heatsunk'                              # "HEATSUNK BY THE HOUSING"
         r'|acts?\s+as\s+(?:a\s+)?heat\s*sink'
         r'|adjacent\s+to\s+metal'
         r'|metallic\s+(?:heat\s*sink|thermal\s+mass)',
         re.I)),
    ('sandwich_config',
     re.compile(
         r'sandwiched\s+between'
         r'|between\s+(?:two\s+)?metal(?:lic)?\s+surfaces'
         r'|between\s+metal\s+layers'
         r'|trapped\s+between',
         re.I)),
    ('heritage_usage',
     re.compile(
         r'previously\s+(?:flown|approved|used)'   # "previously approved"
         r'|flown\s+successfully'
         r'|heritage'
         r'|proven\s+reliable'
         r'|(?:used|approved)\s+(?:in|for)\s+(?:a\s+)?similar\s+application'
         r'|already\s+been\s+approved'             # "HAS ALREADY BEEN APPROVED"
         r'|(?:has|have)\s+been\s+(?:used|qualified)\s+for'
         r'|same\s+application\s+by\s+MUA',        # "previously approved for the same application by MUA"
         re.I)),
    ('edge_exposure_only',
     re.compile(
         r'(?:minimal\s+)?edge\s+exposure'
         r'|only\s+edge(?:s)?\s+(?:are\s+)?exposed',
         re.I)),
    ('conformal_coating',
     re.compile(
         r'conformal\s+coat(?:ing|ed)?'
         r'|coated\s+with'
         r'|protective\s+coating'
         r'|surface\s+treatment',
         re.I)),
    ('compression_only',
     re.compile(
         r'compress(?:ion|ive)\s+(?:load(?:s|ing)?\s+)?only'  # "compression only" / "compressive loads only"
         r'|carry\s+compressive'                   # "carry compressive loads only"
         r'|no\s+tension'
         r'|no\s+tensile\s+(?:load|stress)',
         re.I)),
    ('plating_protection',
     re.compile(
         r'(?:gold|nickel|silver|solder|chromium|cadmium|zinc)\s+plat(?:ed|ing)'
         r'|iron[\s-]phosphate\s+coat'
         r'|(?:chrome|chromium)\s+(?:coat(?:ing|ed)?|plat(?:ed|ing))',  # "chromium coating"
         re.I)),
    ('inert_environment',
     re.compile(
         r'\binert\b'
         r'|argon'
         r'|nitrogen\s+(?:purge|environment|blanket)'
         r'|dry\s+nitrogen'
         r'|humidity\s+controlled',                # "humidity controlled environment"
         re.I)),
    ('test_data_supports',
     re.compile(
         r'test\s+data'
         r'|test\s+report'
         r'|WSTF'
         r'|JSC\s+Report'
         r'|tested\s+(?:per|to|in\s+accordance)',
         re.I)),
    ('material_nature',
     re.compile(
         r'(?:based\s+on\s+)?(?:the\s+)?nature\s+of\s+the\s+material'
         r'|inherently'
         r'|(?:is\s+(?:a\s+)?)?ceramic'
         r'|inorganic'
         r'|(?:is\s+(?:a\s+)?)?glass'
         r'|metallic\s+material',
         re.I)),
    ('not_exposed',
     re.compile(
         r'not\s+(?:directly\s+)?exposed'
         r'|no\s+exposed\s+(?:surface\s+)?area'    # "NO EXPOSED SURFACE AREA"
         r'|is\s+(?:fully\s+|totally\s+)?enclosed'
         r'|is\s+(?:fully\s+)?internal'
         r'|(?:no|zero)\s+(?:direct\s+)?(?:external\s+)?exposure'
         r'|sealed\s+(?:in|within|inside)',
         re.I)),
    ('vacuum_bake',
     re.compile(
         r'vacuum\s+baked?'
         r'|bake[\s-]?out'
         r'|cured\s+(?:at|for)'
         r'|outgassed'
         r'|pre[\s-]?condition',
         re.I)),
    ('no_fluid_contact',
     re.compile(
         r'will\s+not\s+(?:be\s+)?(?:exposed|in\s+contact)\b'
         r'|not\s+come\s+in\s+contact\s+with'
         r'|no\s+contact\s+with'
         r'|will\s+not\s+contact'
         r'|exposed\s+to\s+neither',               # "exposed to neither NTO nor hydrazine"
         re.I)),
    ('low_stress',
     re.compile(
         r'low\s+(?:stress|torque)'
         r'|not\s+(?:highly\s+)?stressed'
         r'|no\s+sustained'
         r'|transient\s+load'
         r'|stress\s+levels?\s+(?:are\s+)?not\s+excessive',  # "stress levels are not excessive"
         re.I)),
]


def extract_patterns(rationale: Optional[str],
                     application: Optional[str] = None) -> List[Dict]:
    """Extract mitigation patterns from rationale and application text.

    Returns list of dicts: [{pattern_code, matched_text}, ...]
    """
    results = []
    if not rationale and not application:
        return results

    # Search both fields
    text = " ".join(filter(None, [rationale, application]))
    if not text.strip():
        return results

    for pattern_code, regex in _RATIONALE_PATTERNS:
        match = regex.search(text)
        if match:
            # Extract surrounding context (up to 60 chars around match)
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            snippet = text[start:end].strip()
            results.append({
                'pattern_code': pattern_code,
                'matched_text': snippet,
            })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# EVIDENCE EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════

_EVIDENCE_PATTERNS = [
    # Test references: "Test 1", "Test 7", "Test 17"
    ('test_report', re.compile(r'Test\s+(\d+)', re.I)),
    # Standard citations: "MSFC-STD-3029", "NASA-STD-6001", "MSFC-SPEC-522"
    ('standard', re.compile(
        r'((?:MSFC|NASA|SSP|MIL|AMS|ASTM|SAE|NHB)[-\s]?'
        r'(?:STD|SPEC|HDBK|ARP|E)[-\s]?\d[\w.-]*)', re.I)),
    # Memo/letter citations: "NASA memo JEH021-91-0931", "JSC Report 02681"
    ('memo', re.compile(r'(?:memo|letter|report)\s+[A-Z0-9][\w\s-]{3,30}', re.I)),
    # Attachment references
    ('attachment', re.compile(r'(?:Attachment|Annex)\s+[A-Z0-9#]+', re.I)),
    # WSTF test references
    ('test_report', re.compile(r'WSTF\s+[\d-]+', re.I)),
    # JSC Report references
    ('test_report', re.compile(r'JSC\s+(?:Report\s+)?[\d-]+', re.I)),
]


def extract_evidence(rationale: Optional[str],
                     application: Optional[str] = None) -> List[Dict]:
    """Extract evidence citations from text.

    Returns list of dicts: [{evidence_type, reference_text, test_number, standard_cited}, ...]
    """
    results = []
    text = " ".join(filter(None, [rationale, application]))
    if not text.strip():
        return results

    seen = set()
    for evidence_type, regex in _EVIDENCE_PATTERNS:
        for match in regex.finditer(text):
            ref = match.group(0).strip()
            if ref in seen:
                continue
            seen.add(ref)

            test_number = None
            standard_cited = None
            if evidence_type == 'test_report' and match.lastindex:
                test_number = f"Test {match.group(1)}" if match.group(1).isdigit() else ref
            elif evidence_type == 'standard':
                standard_cited = match.group(1) if match.lastindex else ref

            results.append({
                'evidence_type': evidence_type,
                'reference_text': ref,
                'test_number': test_number,
                'standard_cited': standard_cited,
            })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# MUA TYPE CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

_CERTIFICATION_SIGNALS = re.compile(
    r'(?:certifi(?:cation|ed)|provides\s+certification|'
    r'final\s+materials?\s+list|reciprocal\s+agreement|'
    r'all\s+\w+\s+hardware|this\s+MUA\s+provides\s+certification)',
    re.I
)


def classify_mua_type(application: Optional[str],
                      issue: Optional[str],
                      material: Optional[str]) -> str:
    """Classify MUA as 'component' (specific material) or 'certification' (blanket approval).

    Certification MUAs cover entire hardware assemblies rather than specific materials.
    """
    text = " ".join(filter(None, [application, issue]))
    if not text:
        return 'component'

    # Check for certification signals
    if _CERTIFICATION_SIGNALS.search(text):
        return 'certification'

    # If material is generic/missing, more likely certification
    if material and material.lower() in ('see miul', 'see attached', 'see below',
                                          'various', 'several', 'see miul attached'):
        return 'certification'

    return 'component'
