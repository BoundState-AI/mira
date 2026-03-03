"""Process Sensitivity Handler for MUA v7.

Handles Step 1b of the MUA pipeline: additional field collection for
process-sensitive materials whose performance properties depend on
fabrication parameters (cure cycle, mix ratio, layup orientation, etc.).

Why this matters
----------------
A standard material-only MUA is dangerous for process-sensitive classes.
The same adhesive, for example, can have radically different flammability,
offgassing, and mechanical properties depending on cure temperature,
cure time, and mix ratio.  A precedent MUA that approved FM-73 adhesive
cured at 250 degF for 90 minutes does **not** transfer to FM-73 cured at
350 degF for 60 minutes -- the outgassing profile and bond strength differ.

Process-sensitive material classes:
    - Adhesives:   cure_temp, cure_time, mix_ratio
    - Composites:  cure_temp, cure_time, cure_pressure, layup_orientation
    - Potting:     cure_temp, cure_time, mix_ratio
    - Sealants:    cure_temp, cure_time

This module provides:
    1. Detection of process-sensitive materials.
    2. Required-field specification per material class.
    3. Validation that the engineer provided the necessary parameters.
    4. Comparison of query process parameters against precedent parameters
       (for precedent applicability analysis in Step 2).
"""

from __future__ import annotations

import math
from typing import Optional

from .models import MaterialClass, ProcessParams


# ---------------------------------------------------------------------------
# Field definitions per material class
# ---------------------------------------------------------------------------

# Each entry is a dict with:
#   field_name  -- attribute name on ProcessParams
#   label       -- human-readable label
#   unit        -- display unit
#   required    -- whether the field must be present
#   description -- engineer-facing explanation
_ADHESIVE_FIELDS: list[dict] = [
    {
        "field_name": "cure_temp_f",
        "label": "Cure Temperature",
        "unit": "\u00b0F",
        "required": True,
        "description": (
            "Primary cure temperature.  Affects cross-link density, "
            "outgassing profile, and bond strength."
        ),
    },
    {
        "field_name": "cure_time_min",
        "label": "Cure Time",
        "unit": "minutes",
        "required": True,
        "description": (
            "Total cure duration at the specified temperature.  "
            "Under-cure produces volatile residuals; over-cure degrades "
            "the polymer backbone."
        ),
    },
    {
        "field_name": "mix_ratio",
        "label": "Mix Ratio",
        "unit": "by weight or volume (specify)",
        "required": True,
        "description": (
            "Resin-to-hardener ratio.  Stoichiometric deviations change "
            "cure kinetics and residual amine/epoxide content."
        ),
    },
]

_COMPOSITE_FIELDS: list[dict] = [
    {
        "field_name": "cure_temp_f",
        "label": "Cure Temperature",
        "unit": "\u00b0F",
        "required": True,
        "description": (
            "Autoclave or oven cure temperature.  Determines resin flow, "
            "fiber wetting, and glass-transition temperature."
        ),
    },
    {
        "field_name": "cure_time_min",
        "label": "Cure Time",
        "unit": "minutes",
        "required": True,
        "description": (
            "Total cure duration.  Affects degree-of-cure and volatile "
            "content."
        ),
    },
    {
        "field_name": "cure_pressure_psi",
        "label": "Cure Pressure",
        "unit": "psi",
        "required": True,
        "description": (
            "Autoclave or press pressure during cure.  Controls void "
            "content and fiber volume fraction."
        ),
    },
    {
        "field_name": "layup_orientation",
        "label": "Layup Orientation",
        "unit": "ply schedule",
        "required": True,
        "description": (
            "Fiber orientation schedule (e.g. [0/45/-45/90]s).  "
            "Determines directional mechanical and thermal properties."
        ),
    },
]

_POTTING_FIELDS: list[dict] = [
    {
        "field_name": "cure_temp_f",
        "label": "Cure Temperature",
        "unit": "\u00b0F",
        "required": True,
        "description": (
            "Cure temperature for the potting compound.  Affects "
            "encapsulant shrinkage and dielectric properties."
        ),
    },
    {
        "field_name": "cure_time_min",
        "label": "Cure Time",
        "unit": "minutes",
        "required": True,
        "description": (
            "Cure duration.  Incomplete cure leaves unreacted isocyanate "
            "or amine groups that outgas in vacuum."
        ),
    },
    {
        "field_name": "mix_ratio",
        "label": "Mix Ratio",
        "unit": "by weight or volume (specify)",
        "required": True,
        "description": (
            "Base-to-catalyst ratio.  Off-ratio mixes produce excess "
            "volatiles and compromised physical properties."
        ),
    },
]

_SEALANT_FIELDS: list[dict] = [
    {
        "field_name": "cure_temp_f",
        "label": "Cure Temperature",
        "unit": "\u00b0F",
        "required": True,
        "description": (
            "Ambient or oven cure temperature.  Many polysulfide and "
            "silicone sealants have drastically different cure behavior "
            "above and below room temperature."
        ),
    },
    {
        "field_name": "cure_time_min",
        "label": "Cure Time",
        "unit": "minutes",
        "required": True,
        "description": (
            "Cure duration.  Sealant that is not fully cured will "
            "continue to outgas and may fail adhesion requirements."
        ),
    },
]

# Master registry keyed by MaterialClass.
_FIELDS_BY_CLASS: dict[MaterialClass, list[dict]] = {
    MaterialClass.ADHESIVE: _ADHESIVE_FIELDS,
    MaterialClass.COMPOSITE: _COMPOSITE_FIELDS,
    MaterialClass.POTTING: _POTTING_FIELDS,
    MaterialClass.SEALANT: _SEALANT_FIELDS,
}

# ---------------------------------------------------------------------------
# Default comparison tolerances
# ---------------------------------------------------------------------------

# For numeric fields, define the relative tolerance (fraction) within which
# two values are considered matching.  Values outside this tolerance but
# within 2x are "close"; beyond 2x are "different".
_DEFAULT_NUMERIC_TOLERANCE: float = 0.10  # 10 %
_CLOSE_NUMERIC_FACTOR: float = 2.0  # within 2x tolerance = "close"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class ProcessSensitivityHandler:
    """Handles Step 1b: additional fields for process-sensitive materials.

    Process-sensitive materials are those whose performance properties
    (flammability, offgassing, mechanical strength) depend on fabrication
    parameters.  This handler:

    - Detects whether a material class is process-sensitive.
    - Specifies which process fields the engineer must provide.
    - Validates that the provided :class:`ProcessParams` contain all
      required values.
    - Compares query parameters against a precedent's parameters to assess
      whether the precedent is applicable (Step 2 investigation).
    """

    #: Material classes that are process-sensitive.
    PROCESS_SENSITIVE_CLASSES: frozenset[MaterialClass] = frozenset({
        MaterialClass.ADHESIVE,
        MaterialClass.COMPOSITE,
        MaterialClass.POTTING,
        MaterialClass.SEALANT,
    })

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_process_sensitive(material_class: MaterialClass) -> bool:
        """Return True if the material class is process-sensitive.

        Parameters
        ----------
        material_class:
            The material class to check.

        Returns
        -------
        bool
            ``True`` if the material class requires process parameter
            collection in Step 1b.
        """
        return material_class in ProcessSensitivityHandler.PROCESS_SENSITIVE_CLASSES

    # ------------------------------------------------------------------
    # Required fields
    # ------------------------------------------------------------------

    @staticmethod
    def get_required_fields(material_class: MaterialClass) -> list[dict]:
        """Return the required process parameter fields for this material class.

        Each element is a dict with keys:

        - ``field_name``:  Attribute name on :class:`ProcessParams`.
        - ``label``:       Human-readable label for the UI.
        - ``unit``:        Display unit string.
        - ``required``:    Whether the field must be provided.
        - ``description``: Engineer-facing explanation of why the field
          matters for this material class.

        Parameters
        ----------
        material_class:
            The material class to retrieve fields for.

        Returns
        -------
        list[dict]
            Ordered list of field definitions.  Returns an empty list
            if the material class is not process-sensitive.
        """
        return list(_FIELDS_BY_CLASS.get(material_class, []))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_process_params(
        material_class: MaterialClass,
        params: ProcessParams,
    ) -> tuple[bool, list[str]]:
        """Validate that required process parameters are provided.

        Parameters
        ----------
        material_class:
            The material class whose required fields define the
            validation criteria.
        params:
            The process parameters supplied by the engineer.

        Returns
        -------
        tuple[bool, list[str]]
            ``(valid, missing_fields)`` where ``valid`` is ``True``
            only when every required field has a non-``None`` value.
            ``missing_fields`` contains human-readable labels for
            every missing required field.
        """
        fields = _FIELDS_BY_CLASS.get(material_class, [])
        missing: list[str] = []

        for field_def in fields:
            if not field_def["required"]:
                continue
            value = getattr(params, field_def["field_name"], None)
            if value is None:
                missing.append(
                    f"{field_def['label']} ({field_def['field_name']})"
                )

        return (len(missing) == 0, missing)

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    @staticmethod
    def compare_process_params(
        query_params: ProcessParams,
        precedent_params: dict,
    ) -> dict:
        """Compare query process parameters to a precedent's parameters.

        Performs a field-by-field comparison, classifying each shared
        field as ``"match"``, ``"close"``, ``"different"``, or
        ``"missing"`` (when the precedent does not record the field).

        Numeric fields use a configurable tolerance (default 10 %).
        String fields (``mix_ratio``, ``layup_orientation``) are
        compared for exact equality after whitespace normalization.

        Parameters
        ----------
        query_params:
            The process parameters for the current MUA query.
        precedent_params:
            A dict of process parameter values from a historic
            precedent MUA.  Keys should match :class:`ProcessParams`
            attribute names.

        Returns
        -------
        dict
            A comparison result with the following structure::

                {
                    "overall_match": bool,
                    "field_comparisons": {
                        "<field_name>": {
                            "status": "match" | "close" | "different" | "missing",
                            "query_value": <value>,
                            "precedent_value": <value or None>,
                            "explanation": str,
                        },
                        ...
                    },
                    "summary": str,
                }

            ``overall_match`` is ``True`` only when every compared
            numeric field is within tolerance and every string field
            is an exact match.
        """
        numeric_fields = {"cure_temp_f", "cure_time_min", "cure_pressure_psi"}
        string_fields = {"mix_ratio", "layup_orientation"}

        field_comparisons: dict[str, dict] = {}
        all_match = True

        # Determine which fields to compare: all fields present on query_params
        all_field_names = [
            "cure_temp_f", "cure_time_min", "cure_pressure_psi",
            "mix_ratio", "layup_orientation",
        ]

        for field_name in all_field_names:
            query_val = getattr(query_params, field_name, None)
            if query_val is None:
                # Query does not specify this field; skip comparison.
                continue

            precedent_val = precedent_params.get(field_name)

            if precedent_val is None:
                field_comparisons[field_name] = {
                    "status": "missing",
                    "query_value": query_val,
                    "precedent_value": None,
                    "explanation": (
                        f"Precedent does not record {field_name}; "
                        f"cannot verify process equivalence for this parameter"
                    ),
                }
                all_match = False
                continue

            if field_name in numeric_fields:
                comparison = _compare_numeric(
                    field_name, query_val, precedent_val,
                )
            elif field_name in string_fields:
                comparison = _compare_string(
                    field_name, query_val, precedent_val,
                )
            else:
                # Fallback: treat as string
                comparison = _compare_string(
                    field_name, str(query_val), str(precedent_val),
                )

            field_comparisons[field_name] = comparison
            if comparison["status"] not in ("match",):
                all_match = False

        # Build summary
        statuses = [c["status"] for c in field_comparisons.values()]
        if not field_comparisons:
            summary = (
                "No process parameters available for comparison; "
                "precedent applicability cannot be assessed on "
                "process grounds"
            )
            all_match = False
        elif all_match:
            summary = (
                "All process parameters match within tolerance; "
                "precedent process conditions are applicable"
            )
        else:
            mismatches = [
                fname for fname, comp in field_comparisons.items()
                if comp["status"] != "match"
            ]
            summary = (
                f"Process parameter mismatch on: "
                f"{', '.join(mismatches)}. "
                f"Precedent may not be directly applicable; "
                f"engineering evaluation required"
            )

        return {
            "overall_match": all_match,
            "field_comparisons": field_comparisons,
            "summary": summary,
        }


# ---------------------------------------------------------------------------
# Private comparison helpers
# ---------------------------------------------------------------------------


def _compare_numeric(
    field_name: str,
    query_val: float,
    precedent_val: float | int | str,
) -> dict:
    """Compare two numeric values with tolerance.

    Parameters
    ----------
    field_name:
        Name of the field being compared (for messages).
    query_val:
        The value from the current MUA query.
    precedent_val:
        The value from the precedent (may be a string that needs
        conversion).

    Returns
    -------
    dict
        Comparison result with status, values, and explanation.
    """
    try:
        prec_float = float(precedent_val)
    except (ValueError, TypeError):
        return {
            "status": "different",
            "query_value": query_val,
            "precedent_value": precedent_val,
            "explanation": (
                f"Precedent {field_name} value '{precedent_val}' is not "
                f"numeric; cannot compare to query value {query_val}"
            ),
        }

    # Avoid division by zero: if both are zero, they match.
    if query_val == 0.0 and prec_float == 0.0:
        return {
            "status": "match",
            "query_value": query_val,
            "precedent_value": prec_float,
            "explanation": f"{field_name}: both values are 0 (exact match)",
        }

    # Use the larger absolute value as the reference for relative difference.
    reference = max(abs(query_val), abs(prec_float))
    if reference == 0.0:
        relative_diff = 0.0
    else:
        relative_diff = abs(query_val - prec_float) / reference

    if relative_diff <= _DEFAULT_NUMERIC_TOLERANCE:
        return {
            "status": "match",
            "query_value": query_val,
            "precedent_value": prec_float,
            "explanation": (
                f"{field_name}: query={query_val}, precedent={prec_float} "
                f"(within {_DEFAULT_NUMERIC_TOLERANCE * 100:.0f}% tolerance)"
            ),
        }
    elif relative_diff <= _DEFAULT_NUMERIC_TOLERANCE * _CLOSE_NUMERIC_FACTOR:
        return {
            "status": "close",
            "query_value": query_val,
            "precedent_value": prec_float,
            "explanation": (
                f"{field_name}: query={query_val}, precedent={prec_float} "
                f"({relative_diff * 100:.1f}% difference -- close but "
                f"outside {_DEFAULT_NUMERIC_TOLERANCE * 100:.0f}% tolerance; "
                f"engineering judgment needed)"
            ),
        }
    else:
        return {
            "status": "different",
            "query_value": query_val,
            "precedent_value": prec_float,
            "explanation": (
                f"{field_name}: query={query_val}, precedent={prec_float} "
                f"({relative_diff * 100:.1f}% difference -- significantly "
                f"outside tolerance; precedent process conditions do not "
                f"apply)"
            ),
        }


def _compare_string(
    field_name: str,
    query_val: str,
    precedent_val: str | None,
) -> dict:
    """Compare two string values after whitespace normalization.

    Parameters
    ----------
    field_name:
        Name of the field being compared (for messages).
    query_val:
        The value from the current MUA query.
    precedent_val:
        The value from the precedent.

    Returns
    -------
    dict
        Comparison result with status, values, and explanation.
    """
    if precedent_val is None:
        return {
            "status": "missing",
            "query_value": query_val,
            "precedent_value": None,
            "explanation": (
                f"Precedent does not record {field_name}"
            ),
        }

    q_norm = " ".join(str(query_val).strip().split())
    p_norm = " ".join(str(precedent_val).strip().split())

    if q_norm.lower() == p_norm.lower():
        return {
            "status": "match",
            "query_value": query_val,
            "precedent_value": precedent_val,
            "explanation": (
                f"{field_name}: exact match ('{q_norm}')"
            ),
        }
    else:
        return {
            "status": "different",
            "query_value": query_val,
            "precedent_value": precedent_val,
            "explanation": (
                f"{field_name}: query='{q_norm}', "
                f"precedent='{p_norm}' -- values differ; "
                f"engineering evaluation required to determine "
                f"whether the difference is material"
            ),
        }
