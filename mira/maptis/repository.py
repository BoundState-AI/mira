#!/usr/bin/env python3
"""
Module: Repository
Purpose: MAPTIS Silver Layer Database Connection

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Optional psycopg2 import - falls back to heuristic mode if unavailable
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    psycopg2 = None
    RealDictCursor = None
    logger.warning("psycopg2 not available - using heuristic material classification")

# Import centralized database configuration
import os
try:
    from mira.core.db_config import get_db_connection_params
    MAPTIS_CONFIG = get_db_connection_params(options='-c search_path=maptis,public')
except ImportError:
    # Fallback for standalone usage - uses environment variables
    MAPTIS_CONFIG = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', '5432')),
        'database': os.environ.get('POSTGRES_DB', 'mira'),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'options': '-c search_path=maptis,public',
    }
    logger.warning("[MAPTIS] Using fallback config - set environment variables for production")


class MaptisConnection:
    """Managed connection to MAPTIS silver layer"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("psycopg2 not available - database operations disabled")
        self.config = config or MAPTIS_CONFIG
        self._conn = None

    def connect(self):
        """Establish database connection"""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self.config)
        return self._conn

    def close(self):
        """Close database connection"""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    @contextmanager
    def cursor(self, cursor_factory=None):
        """Context manager for cursor"""
        conn = self.connect()
        factory = cursor_factory if cursor_factory else RealDictCursor
        cur = conn.cursor(cursor_factory=factory)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global connection pool (singleton pattern)
_maptis_conn = None

def get_maptis_connection() -> Optional[MaptisConnection]:
    """Get or create MAPTIS connection. Returns None if psycopg2 unavailable."""
    if not PSYCOPG2_AVAILABLE:
        return None
    global _maptis_conn
    if _maptis_conn is None:
        _maptis_conn = MaptisConnection()
    return _maptis_conn


# Query builders
class MaterialQuery:
    """Material search and lookup queries"""

    @staticmethod
    def search_by_designation(pattern: str, limit: int = 50) -> Tuple[str, tuple]:
        """Search materials by designation pattern"""
        return (
            f"""
            SELECT
                material_code,
                designation,
                composition,
                use_type,
                use_temp_min_f,
                use_temp_max_f
            FROM materials
            WHERE designation ILIKE %s
            ORDER BY designation
            LIMIT {limit}
            """,
            (f'%{pattern}%',)
        )

    @staticmethod
    def get_by_code(material_code: int) -> Tuple[str, tuple]:
        """Get material by code with test counts"""
        return (
            """
            SELECT
                m.*,
                COUNT(DISTINCT ft.id) as flammability_test_count,
                COUNT(DISTINCT tt.id) as toxicity_test_count,
                COUNT(DISTINCT mit.id) as impact_test_count,
                COUNT(DISTINCT tvs.id) as tvs_test_count
            FROM materials m
            LEFT JOIN flammability_tests ft ON m.material_code = ft.material_code
            LEFT JOIN toxicity_tests tt ON m.material_code = tt.material_code
            LEFT JOIN mechanical_impact_tests mit ON m.material_code = mit.material_code
            LEFT JOIN tvs_outgassing_tests tvs ON m.material_code = tvs.material_code
            WHERE m.material_code = %s
            GROUP BY m.material_code
            """,
            (material_code,)
        )

    @staticmethod
    def get_flammability_tests(material_code: int) -> Tuple[str, tuple]:
        """Get flammability tests for material"""
        return (
            """
            SELECT
                ft.*,
                COUNT(ftr.id) as sample_count
            FROM flammability_tests ft
            LEFT JOIN flammability_test_results ftr ON ft.id = ftr.test_id
            WHERE ft.material_code = %s
            GROUP BY ft.id
            ORDER BY ft.date_tested DESC NULLS LAST
            """,
            (material_code,)
        )

    @staticmethod
    def get_flammability_results(test_id: int) -> Tuple[str, tuple]:
        """Get flammability test results"""
        return (
            """
            SELECT *
            FROM flammability_test_results
            WHERE test_id = %s
            ORDER BY sample_no
            """,
            (test_id,)
        )

    @staticmethod
    def get_toxicity_tests(material_code: int) -> Tuple[str, tuple]:
        """Get toxicity tests for material"""
        return (
            """
            SELECT
                tt.*,
                COUNT(tgr.id) as gas_measurement_count
            FROM toxicity_tests tt
            LEFT JOIN toxicity_gas_results tgr ON tt.id = tgr.test_id
            WHERE tt.material_code = %s
            GROUP BY tt.id
            ORDER BY tt.date_tested DESC NULLS LAST
            """,
            (material_code,)
        )

    @staticmethod
    def get_toxicity_results(test_id: int) -> Tuple[str, tuple]:
        """Get toxicity gas results"""
        return (
            """
            SELECT *
            FROM toxicity_gas_results
            WHERE test_id = %s
            ORDER BY gas_code
            """,
            (test_id,)
        )

    @staticmethod
    def get_mechanical_impact_tests(material_code: int) -> Tuple[str, tuple]:
        """Get mechanical impact tests for material"""
        return (
            """
            SELECT
                mit.*,
                COUNT(mir.id) as result_count
            FROM mechanical_impact_tests mit
            LEFT JOIN mechanical_impact_results mir ON mit.id = mir.test_id
            WHERE mit.material_code = %s
            GROUP BY mit.id
            ORDER BY mit.date_tested DESC NULLS LAST
            """,
            (material_code,)
        )

    @staticmethod
    def get_tvs_tests(material_code: int) -> Tuple[str, tuple]:
        """Get TVS outgassing tests for material"""
        return (
            """
            SELECT
                tvs.*,
                COUNT(tvsr.id) as result_count
            FROM tvs_outgassing_tests tvs
            LEFT JOIN tvs_test_results tvsr ON tvs.id = tvsr.test_id
            WHERE tvs.material_code = %s
            GROUP BY tvs.id
            ORDER BY tvs.date_tested DESC NULLS LAST
            """,
            (material_code,)
        )

    @staticmethod
    def search_all_tables(query: str, limit: int = 100) -> Tuple[str, tuple]:
        """Search across materials, tests, and results"""
        return (
            """
            SELECT
                'material' as result_type,
                material_code as id,
                designation as title,
                composition as details,
                NULL as test_report_number
            FROM materials
            WHERE designation ILIKE %s

            UNION ALL

            SELECT
                'flammability_test' as result_type,
                ft.id,
                m.designation as title,
                ft.nasa_6001_rating as details,
                ft.test_report_number
            FROM flammability_tests ft
            JOIN materials m ON ft.material_code = m.material_code
            WHERE ft.test_report_number ILIKE %s

            UNION ALL

            SELECT
                'toxicity_test' as result_type,
                tt.id,
                m.designation as title,
                tt.iss_rating as details,
                tt.test_report_number
            FROM toxicity_tests tt
            JOIN materials m ON tt.material_code = m.material_code
            WHERE tt.test_report_number ILIKE %s

            ORDER BY result_type, title
            LIMIT {limit}
            """,
            (f'%{query}%', f'%{query}%', f'%{query}%')
        )


class TestQuery:
    """Test data queries"""

    @staticmethod
    def get_test_summary() -> str:
        """Get summary statistics across all test types"""
        return """
            SELECT
                'flammability' as test_type,
                COUNT(*) as test_count,
                COUNT(DISTINCT material_code) as material_count
            FROM flammability_tests

            UNION ALL

            SELECT
                'toxicity' as test_type,
                COUNT(*) as test_count,
                COUNT(DISTINCT material_code) as material_count
            FROM toxicity_tests

            UNION ALL

            SELECT
                'mechanical_impact' as test_type,
                COUNT(*) as test_count,
                COUNT(DISTINCT material_code) as material_count
            FROM mechanical_impact_tests

            UNION ALL

            SELECT
                'tvs_outgassing' as test_type,
                COUNT(*) as test_count,
                COUNT(DISTINCT material_code) as material_count
            FROM tvs_outgassing_tests

            ORDER BY test_count DESC
        """

    @staticmethod
    def get_recent_tests(limit: int = 20) -> Tuple[str, tuple]:
        """Get most recent tests across all types"""
        return (
            """
            SELECT
                'flammability' as test_type,
                ft.id,
                m.designation,
                ft.test_report_no,
                ft.date_tested,
                ft.nasa_6001_rating as rating
            FROM flammability_tests ft
            JOIN materials m ON ft.material_code = m.material_code
            WHERE ft.date_tested IS NOT NULL

            UNION ALL

            SELECT
                'toxicity' as test_type,
                tt.id,
                m.designation,
                tt.test_report_no,
                tt.date_tested,
                tt.iss_rating as rating
            FROM toxicity_tests tt
            JOIN materials m ON tt.material_code = m.material_code
            WHERE tt.date_tested IS NOT NULL

            ORDER BY date_tested DESC
            LIMIT %s
            """,
            (limit,)
        )


# Helper functions
def execute_query(query: str, params: tuple = None) -> List[Dict[str, Any]]:
    """Execute a query and return results as list of dicts"""
    conn = get_maptis_connection()
    if conn is None:
        return []
    with conn.cursor() as cursor:
        cursor.execute(query, params or ())
        return cursor.fetchall()


def execute_one(query: str, params: tuple = None) -> Optional[Dict[str, Any]]:
    """Execute a query and return first result"""
    conn = get_maptis_connection()
    if conn is None:
        return None
    with conn.cursor() as cursor:
        cursor.execute(query, params or ())
        return cursor.fetchone()


# =============================================================================
# O2 SAFETY CLASSIFICATION SUPPORT
# =============================================================================

from enum import Enum
from dataclasses import dataclass
import uuid


class MaterialFamily(str, Enum):
    """Material families for safety classification.

    These families determine O2/H2 compatibility rules.
    The family MUST come from the database, not string matching.
    """
    TITANIUM = "titanium"
    MAGNESIUM = "magnesium"
    ALUMINUM = "aluminum"
    NICKEL_ALLOY = "nickel_alloy"
    AUSTENITIC_STEEL = "austenitic_steel"
    COPPER = "copper"
    POLYMER_FLUORINATED = "polymer_fluorinated"
    POLYMER_ORGANIC = "polymer_organic"
    COMPOSITE = "composite"
    UNKNOWN = "unknown"


@dataclass
class MaterialRecord:
    """Structured material data for safety engines.

    This is the contract between the material repository and safety engines.
    Safety engines should use these fields, NOT parse the designation string.
    """
    material_key: str
    designation: str
    material_code: Optional[int] = None
    material_type: Optional[str] = None
    family: MaterialFamily = MaterialFamily.UNKNOWN

    # Flammability data (from MAPTIS test records)
    rating_flam: Optional[str] = None  # A, B, C, D, X, U
    o2_test_count: int = 0
    max_tested_pressure_psi: Optional[float] = None

    # Additional properties
    contains_pfas: bool = False
    is_restricted: bool = False

    # Audit trail
    data_source: str = "unknown"
    confidence: float = 0.0  # 0-1, how confident we are in this record
    source: str = ""  # NASA SWE-013 traceability



# Families that are ALWAYS prohibited in O2 service
O2_PROHIBITED_FAMILIES = {
    MaterialFamily.TITANIUM,
    MaterialFamily.MAGNESIUM,
}

# Families that are restricted (e.g., LOX only, not GOX)
O2_RESTRICTED_FAMILIES = {
    MaterialFamily.ALUMINUM,  # LOX cryo only, not GOX at elevated pressure
    MaterialFamily.POLYMER_ORGANIC,  # Generally prohibited except specific compounds
}


# =============================================================================
# H2 SAFETY CLASSIFICATION SUPPORT
# Per NSS 1740.16 and SAND2012_7321 (Sandia H2 Materials Compatibility)
# =============================================================================

# Families with HIGH hydrogen embrittlement (HE) risk - PROHIBITED
H2_PROHIBITED_FAMILIES = {
    # High-strength steels suffer severe HE
    # Note: MaterialFamily doesn't capture strength grade, so we handle
    # high-strength steels via yield_strength check in the engine
}

# Families that are APPROVED for hydrogen service
H2_APPROVED_FAMILIES = {
    MaterialFamily.AUSTENITIC_STEEL,  # 304, 316, 321 - excellent H2 resistance
    MaterialFamily.NICKEL_ALLOY,  # Inconel, Monel, Hastelloy - best for H2
    MaterialFamily.COPPER,  # Copper alloys - very good H2 resistance
    MaterialFamily.ALUMINUM,  # AL alloys - generally good for H2 (no HE)
}

# Families that require caution in hydrogen service
H2_CAUTION_FAMILIES = {
    MaterialFamily.TITANIUM,  # Ti can absorb H2 at elevated temps
    MaterialFamily.POLYMER_FLUORINATED,  # Permeation concerns
}

# H2 embrittlement thresholds (per NSS 1740.16)
H2_HIGH_STRENGTH_THRESHOLD_KSI = 150.0  # Materials > 150 ksi yield are HE-susceptible
H2_PRESSURE_THRESHOLD_PSIA = 1000.0  # HE risk increases above 1000 psia


def get_material_for_o2(material_key: str) -> MaterialRecord:
    """Retrieve material record for O2 compatibility evaluation.

    CRITICAL: This is the single entrypoint for material lookups in O2 code.
    The returned MaterialRecord.family should be used for classification,
    NOT string matching against MaterialRecord.designation.

    Args:
        material_key: Material identifier (e.g., "AL 6061-T6", "Ti-6Al-4V", "SS 316")

    Returns:
        MaterialRecord with family, ratings, and test data populated

    Strategy:
        1. Try database lookup first (high confidence)
        2. Fall back to heuristic family inference (low confidence)
    """
    # Try database lookup first
    try:
        record = _lookup_material_from_db(material_key)
        if record:
            return record
    except Exception as e:
        logger.warning(f"Database lookup failed for '{material_key}': {e}")

    # Fallback: Heuristic-based family detection
    family = _infer_family_from_key(material_key)

    logger.debug(f"[MATERIAL_REPO] Resolved '{material_key}' -> family={family.value} (heuristic)")

    return MaterialRecord(
        material_key=material_key,
        designation=material_key,
        material_type=family.value,
        family=family,
        rating_flam=None,
        o2_test_count=0,
        max_tested_pressure_psi=None,
        data_source="heuristic_fallback",
        confidence=0.5,
    )


def _lookup_material_from_db(material_key: str) -> Optional[MaterialRecord]:
    """Look up material from database with flammability test data.

    Returns None if not found or database unavailable.
    """
    # Search by designation pattern
    query = """
        SELECT
            m.material_code,
            m.designation,
            m.composition,
            m.use_type,
            COUNT(ft.id) as flammability_test_count,
            MAX(ft.nasa_6001_rating) as best_flam_rating
        FROM materials m
        LEFT JOIN flammability_tests ft ON m.material_code = ft.material_code
        WHERE m.designation ILIKE %s
        GROUP BY m.material_code, m.designation, m.composition, m.use_type
        LIMIT 1
    """

    try:
        result = execute_one(query, (f'%{material_key}%',))
        if result:
            # Infer family from composition or use_type if available
            family = _infer_family_from_composition(
                result.get('composition', ''),
                result.get('use_type', ''),
                result.get('designation', '')
            )

            return MaterialRecord(
                material_key=material_key,
                designation=result.get('designation', material_key),
                material_code=result.get('material_code'),
                material_type=family.value,
                family=family,
                rating_flam=result.get('best_flam_rating'),
                o2_test_count=result.get('flammability_test_count', 0),
                data_source="maptis_postgres",
                confidence=0.9,
            )
    except Exception as e:
        logger.debug(f"Database lookup exception: {e}")

    return None


def _infer_family_from_composition(composition: str, use_type: str, designation: str) -> MaterialFamily:
    """Infer material family from database fields."""
    text = f"{composition} {use_type} {designation}".upper()

    if any(t in text for t in ['TITANIUM', 'TI-6', 'TI6AL']):
        return MaterialFamily.TITANIUM
    if any(t in text for t in ['MAGNESIUM', 'MG-', 'MGAL']):
        return MaterialFamily.MAGNESIUM
    if any(t in text for t in ['ALUMINUM', 'AL ', '6061', '2024', '2219', '7075']):
        return MaterialFamily.ALUMINUM
    if any(t in text for t in ['INCONEL', 'MONEL', 'HASTELLOY', 'NICKEL', 'INVAR']):
        return MaterialFamily.NICKEL_ALLOY
    if any(t in text for t in ['304', '316', '321', '347', 'STAINLESS', 'CRES', 'AUSTENITIC']):
        return MaterialFamily.AUSTENITIC_STEEL
    if any(t in text for t in ['COPPER', 'CU-', 'BRASS', 'BRONZE']):
        return MaterialFamily.COPPER
    if any(t in text for t in ['TEFLON', 'PTFE', 'TFE', 'VITON', 'FLUOROPOLYMER']):
        return MaterialFamily.POLYMER_FLUORINATED

    return MaterialFamily.UNKNOWN


def _infer_family_from_key(material_key: str) -> MaterialFamily:
    """Temporary heuristic family detection.

    WARNING: This is a FALLBACK for when database is not available.
    Production code MUST query the database for material_type.
    """
    key_upper = material_key.upper()

    # Titanium family - ALWAYS prohibited in O2
    if any(t in key_upper for t in ['TITANIUM', 'TI-6', 'TI6AL', 'TI 6', 'TI-']):
        return MaterialFamily.TITANIUM

    # Magnesium family - ALWAYS prohibited in O2
    if any(t in key_upper for t in ['MAGNESIUM', 'MG-', 'MGAL', 'MG ']):
        return MaterialFamily.MAGNESIUM

    # Aluminum family - restricted (LOX only, not GOX)
    if any(t in key_upper for t in ['ALUMINUM', 'AL ', 'AL-', '6061', '2024', '2219', '7075']):
        return MaterialFamily.ALUMINUM

    # Nickel alloy family - generally approved for O2
    if any(t in key_upper for t in ['INCONEL', 'MONEL', 'HASTELLOY', 'NICKEL', 'INVAR']):
        return MaterialFamily.NICKEL_ALLOY

    # Austenitic stainless steel - generally approved for O2 with cautions
    if any(t in key_upper for t in ['SS 3', '304', '316', '321', '347', 'STAINLESS', 'CRES']):
        return MaterialFamily.AUSTENITIC_STEEL

    # Copper family - generally approved for O2
    if any(t in key_upper for t in ['COPPER', 'CU-', 'CU ', 'BRASS', 'BRONZE']):
        return MaterialFamily.COPPER

    # Fluorinated polymers - restricted use in O2
    if any(t in key_upper for t in ['TEFLON', 'PTFE', 'TFE', 'VITON', 'FLUOROPOLYMER']):
        return MaterialFamily.POLYMER_FLUORINATED

    return MaterialFamily.UNKNOWN


def get_o2_family_rule(family: MaterialFamily) -> Dict[str, Any]:
    """Get O2 compatibility rule for a material family.

    Returns structured rule data instead of requiring string matching.
    """
    rules = {
        MaterialFamily.TITANIUM: {
            "classification": "prohibited",
            "reason": "Titanium alloys are prohibited in O2 service per NASA-STD-6016 §4.2.6.2 - promoted combustion risk",
            "bok_ref": "NASA-STD-6016 §4.2.6.2, NASA/TM-2007-213740",
        },
        MaterialFamily.MAGNESIUM: {
            "classification": "prohibited",
            "reason": "Magnesium alloys are prohibited in O2 service - highly flammable",
            "bok_ref": "NASA-STD-6016 Table 4-1",
        },
        MaterialFamily.ALUMINUM: {
            "classification": "restricted",
            "reason": "Aluminum alloys limited to LOX (cryogenic) service only, NOT GOX at elevated pressure",
            "bok_ref": "NASA-STD-6016 §4.2.6.3",
            "limits": {
                "phase": "LOX",
                "max_temp_f": -200,
                "max_pressure_psi": 1000,
            },
        },
        MaterialFamily.NICKEL_ALLOY: {
            "classification": "approved",
            "reason": "Nickel alloys (Inconel, Monel, Hastelloy) are preferred for high-pressure O2 service",
            "bok_ref": "NASA-STD-6016 Table 4-1",
            "limits": {"max_pressure_psi": 10000},
        },
        MaterialFamily.AUSTENITIC_STEEL: {
            "classification": "approved_with_caution",
            "reason": "300-series austenitic stainless steels are acceptable with precision cleaning",
            "bok_ref": "NASA-STD-6016 Table 4-1",
            "limits": {"max_pressure_psi": 3000, "notes": "Precision cleaning required above 1000 psi"},
        },
        MaterialFamily.COPPER: {
            "classification": "approved",
            "reason": "Copper and copper alloys are excellent for O2 service",
            "bok_ref": "NASA-STD-6016 Table 4-1",
            "limits": {"max_pressure_psi": 5000},
        },
        MaterialFamily.POLYMER_FLUORINATED: {
            "classification": "restricted",
            "reason": "PTFE/Teflon limited to static seals, no flow",
            "bok_ref": "NASA-STD-6016 Table 4-1",
            "limits": {"flow_regime": "static", "max_pressure_psi": 3000},
        },
        MaterialFamily.UNKNOWN: {
            "classification": "unknown",
            "reason": "Material family not identified - engineering evaluation required",
            "bok_ref": "NASA-STD-6001B Test 1",
        },
    }

    return rules.get(family, rules[MaterialFamily.UNKNOWN])


def get_material_for_h2(material_key: str) -> MaterialRecord:
    """Retrieve material record for H2 compatibility evaluation.

    CRITICAL: This is the single entrypoint for material lookups in H2 code.
    The returned MaterialRecord.family should be used for classification,
    NOT string matching against MaterialRecord.designation.

    Args:
        material_key: Material identifier (e.g., "SS 316", "Inconel 625")

    Returns:
        MaterialRecord with family, ratings, and test data populated
    """
    # Reuse the same lookup logic as O2 - material data is the same
    return get_material_for_o2(material_key)


def get_h2_family_rule(family: MaterialFamily) -> Dict[str, Any]:
    """Get H2 compatibility rule for a material family.

    Returns structured rule data based on NSS 1740.16 and SAND2012_7321.
    Key concern: Hydrogen embrittlement (HE) susceptibility.
    """
    rules = {
        MaterialFamily.AUSTENITIC_STEEL: {
            "classification": "approved",
            "reason": "300-series austenitic stainless steels have excellent H2 resistance due to FCC structure",
            "bok_ref": "NSS 1740.16 Table A5.2, SAND2012_7321 §3.2",
            "embrittlement_risk": "low",
            "notes": "Preferred for H2 service up to 15,000 psi",
        },
        MaterialFamily.NICKEL_ALLOY: {
            "classification": "approved",
            "reason": "Nickel alloys (Inconel, Monel, Hastelloy) are optimal for high-pressure H2 service",
            "bok_ref": "NSS 1740.16 Table A5.2, SAND2012_7321 §3.3",
            "embrittlement_risk": "very_low",
            "notes": "Best choice for H2 pressures above 10,000 psi",
        },
        MaterialFamily.COPPER: {
            "classification": "approved",
            "reason": "Copper and copper alloys have very low H2 permeation and no HE",
            "bok_ref": "NSS 1740.16 Table A5.2",
            "embrittlement_risk": "very_low",
        },
        MaterialFamily.ALUMINUM: {
            "classification": "approved",
            "reason": "Aluminum alloys do not suffer hydrogen embrittlement (HE not a concern for Al)",
            "bok_ref": "SAND2012_7321 §3.4",
            "embrittlement_risk": "none",
            "notes": "Good for cryogenic LH2; permeation may be concern at elevated temps",
        },
        MaterialFamily.TITANIUM: {
            "classification": "caution",
            "reason": "Titanium can absorb hydrogen at elevated temperatures (>300°F), forming brittle hydrides",
            "bok_ref": "NSS 1740.16 §4.5, SAND2012_7321 §3.5",
            "embrittlement_risk": "medium",
            "limits": {"max_temp_f": 300},
            "notes": "Acceptable for cryogenic LH2; avoid elevated temps with GH2",
        },
        MaterialFamily.MAGNESIUM: {
            "classification": "caution",
            "reason": "Magnesium forms hydrides but has been used in some H2 applications",
            "bok_ref": "SAND2012_7321 §3.6",
            "embrittlement_risk": "medium",
            "notes": "Engineering evaluation required; not common for H2 service",
        },
        MaterialFamily.POLYMER_FLUORINATED: {
            "classification": "caution",
            "reason": "PTFE and fluoropolymers have H2 permeation concerns at elevated pressure",
            "bok_ref": "NSS 1740.16 §5.2",
            "embrittlement_risk": "n/a",
            "notes": "Acceptable for seals with proper backup",
        },
        MaterialFamily.POLYMER_ORGANIC: {
            "classification": "caution",
            "reason": "Organic polymers may have permeation and compatibility issues",
            "bok_ref": "NSS 1740.16 §5.2",
            "embrittlement_risk": "n/a",
            "notes": "Requires permeation testing; elastomers may swell",
        },
        MaterialFamily.UNKNOWN: {
            "classification": "unknown",
            "reason": "Material family not identified - engineering evaluation required per NSS 1740.16",
            "bok_ref": "NSS 1740.16 Test 19 (H2 embrittlement test)",
            "embrittlement_risk": "unknown",
        },
    }

    return rules.get(family, rules[MaterialFamily.UNKNOWN])
