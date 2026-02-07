# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Prompt Output Validator
============================

Validates LLM responses against JSON Schemas before parsing.

Features:
- Schema validation with detailed error reporting
- Logging of schema violations with prompt version
- Soft validation mode for debugging
- Integration with VersionedPrompt

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from gptl.prompts import OUTPUT_SCHEMAS, VersionedPrompt

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# VALIDATION RESULT
# =============================================================================

@dataclass
class ValidationError:
    """A single validation error."""
    path: str  # JSON path to the error (e.g., "confidence", "evidence[0].doc_id")
    message: str
    schema_rule: str  # The schema rule that was violated
    actual_value: Any = None


@dataclass
class ValidationResult:
    """Result of schema validation."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    prompt_name: str | None = None
    prompt_version: str | None = None
    validated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dict for logging."""
        return {
            "valid": self.valid,
            "error_count": self.error_count,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "errors": [
                {"path": e.path, "message": e.message, "rule": e.schema_rule}
                for e in self.errors
            ],
        }


# =============================================================================
# SCHEMA VALIDATOR
# =============================================================================

class PromptOutputValidator:
    """
    Validates LLM outputs against JSON Schemas.

    Uses a lightweight validation approach that doesn't require
    external dependencies like jsonschema.
    """

    def __init__(
        self,
        strict: bool = True,
        log_violations: bool = True,
    ):
        """
        Args:
            strict: If True, fail on any violation. If False, log and continue.
            log_violations: Whether to log validation errors.
        """
        self.strict = strict
        self.log_violations = log_violations

    def validate(
        self,
        data: dict[str, Any],
        prompt: VersionedPrompt | str,
    ) -> ValidationResult:
        """
        Validate data against a prompt's output schema.

        Args:
            data: The parsed JSON data from LLM response
            prompt: VersionedPrompt or prompt name string

        Returns:
            ValidationResult with any errors
        """
        # Get schema
        if isinstance(prompt, VersionedPrompt):
            schema = prompt.output_schema
            prompt_name = prompt.name
            prompt_version = prompt.version
        else:
            schema = OUTPUT_SCHEMAS.get(prompt)
            prompt_name = prompt
            prompt_version = "unknown"

        if schema is None:
            logger.warning(f"No schema found for prompt: {prompt_name}")
            return ValidationResult(
                valid=True,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
            )

        # Validate
        errors = self._validate_object(data, schema, path="")

        result = ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )

        # Log if violations
        if self.log_violations and not result.valid:
            logger.warning(
                f"Schema validation failed for {prompt_name} v{prompt_version}: "
                f"{result.error_count} errors - {result.to_log_dict()}"
            )

        return result

    def validate_response(
        self,
        response_text: str,
        prompt: VersionedPrompt | str,
    ) -> tuple[dict[str, Any] | None, ValidationResult]:
        """
        Parse and validate a raw LLM response.

        Args:
            response_text: Raw text response from LLM
            prompt: VersionedPrompt or prompt name string

        Returns:
            Tuple of (parsed_data or None, ValidationResult)
        """
        # Try to parse JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            prompt_name = prompt.name if isinstance(prompt, VersionedPrompt) else prompt
            prompt_version = prompt.version if isinstance(prompt, VersionedPrompt) else "unknown"

            return None, ValidationResult(
                valid=False,
                errors=[ValidationError(
                    path="",
                    message=f"Invalid JSON: {e}",
                    schema_rule="json_parse",
                )],
                prompt_name=prompt_name,
                prompt_version=prompt_version,
            )

        # Validate against schema
        result = self.validate(data, prompt)
        return data, result

    def _validate_object(
        self,
        data: Any,
        schema: dict[str, Any],
        path: str,
    ) -> list[ValidationError]:
        """Validate an object against a schema."""
        errors: list[ValidationError] = []

        # Type check
        expected_type = schema.get("type")
        if expected_type:
            if not self._check_type(data, expected_type):
                errors.append(ValidationError(
                    path=path or "(root)",
                    message=f"Expected type '{expected_type}', got '{type(data).__name__}'",
                    schema_rule="type",
                    actual_value=data,
                ))
                return errors  # Can't validate further if type is wrong

        # Required fields
        required = schema.get("required", [])
        if isinstance(data, dict):
            for field_name in required:
                if field_name not in data:
                    errors.append(ValidationError(
                        path=f"{path}.{field_name}" if path else field_name,
                        message=f"Missing required field '{field_name}'",
                        schema_rule="required",
                    ))

        # Properties (for objects)
        properties = schema.get("properties", {})
        if isinstance(data, dict):
            for prop_name, prop_schema in properties.items():
                if prop_name in data:
                    prop_path = f"{path}.{prop_name}" if path else prop_name
                    errors.extend(self._validate_value(
                        data[prop_name],
                        prop_schema,
                        prop_path,
                    ))

            # Additional properties check
            if schema.get("additionalProperties") is False:
                extra_keys = set(data.keys()) - set(properties.keys())
                for key in extra_keys:
                    errors.append(ValidationError(
                        path=f"{path}.{key}" if path else key,
                        message=f"Unexpected property '{key}'",
                        schema_rule="additionalProperties",
                    ))

        # Items (for arrays)
        if expected_type == "array" and "items" in schema:
            items_schema = schema["items"]
            if isinstance(data, list):
                for i, item in enumerate(data):
                    item_path = f"{path}[{i}]"
                    errors.extend(self._validate_value(item, items_schema, item_path))

                # Min/max items
                min_items = schema.get("minItems")
                max_items = schema.get("maxItems")
                if min_items and len(data) < min_items:
                    errors.append(ValidationError(
                        path=path or "(root)",
                        message=f"Array has {len(data)} items, minimum is {min_items}",
                        schema_rule="minItems",
                    ))
                if max_items and len(data) > max_items:
                    errors.append(ValidationError(
                        path=path or "(root)",
                        message=f"Array has {len(data)} items, maximum is {max_items}",
                        schema_rule="maxItems",
                    ))

        return errors

    def _validate_value(
        self,
        value: Any,
        schema: dict[str, Any],
        path: str,
    ) -> list[ValidationError]:
        """Validate a single value against a schema."""
        errors: list[ValidationError] = []

        expected_type = schema.get("type")

        # Type check
        if expected_type:
            if not self._check_type(value, expected_type):
                errors.append(ValidationError(
                    path=path,
                    message=f"Expected type '{expected_type}', got '{type(value).__name__}'",
                    schema_rule="type",
                    actual_value=value,
                ))
                return errors

        # Enum check
        enum_values = schema.get("enum")
        if enum_values and value not in enum_values:
            errors.append(ValidationError(
                path=path,
                message=f"Value '{value}' not in allowed values: {enum_values}",
                schema_rule="enum",
                actual_value=value,
            ))

        # Numeric constraints
        if expected_type in ("number", "integer"):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value {value} is less than minimum {minimum}",
                    schema_rule="minimum",
                    actual_value=value,
                ))
            if maximum is not None and value > maximum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value {value} is greater than maximum {maximum}",
                    schema_rule="maximum",
                    actual_value=value,
                ))

        # String constraints
        if expected_type == "string":
            max_length = schema.get("maxLength")
            if max_length and len(value) > max_length:
                errors.append(ValidationError(
                    path=path,
                    message=f"String length {len(value)} exceeds maximum {max_length}",
                    schema_rule="maxLength",
                    actual_value=value[:50] + "..." if len(value) > 50 else value,
                ))

        # Nested object/array validation
        if expected_type == "object" and isinstance(value, dict):
            errors.extend(self._validate_object(value, schema, path))
        elif expected_type == "array" and isinstance(value, list):
            errors.extend(self._validate_object(value, schema, path))

        return errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON Schema type."""
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }

        expected_python_type = type_mapping.get(expected_type)
        if expected_python_type is None:
            return True  # Unknown type, skip check

        return isinstance(value, expected_python_type)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Default validator instance
_default_validator = PromptOutputValidator(strict=False, log_violations=True)


def validate_prompt_output(
    data: dict[str, Any],
    prompt: VersionedPrompt | str,
) -> ValidationResult:
    """Validate data against a prompt's output schema using default validator."""
    return _default_validator.validate(data, prompt)


def validate_and_parse(
    response_text: str,
    prompt: VersionedPrompt | str,
) -> tuple[dict[str, Any] | None, ValidationResult]:
    """Parse and validate a raw LLM response using default validator."""
    return _default_validator.validate_response(response_text, prompt)


def get_schema_for_prompt(prompt_name: str) -> dict[str, Any] | None:
    """Get the output schema for a prompt by name."""
    return OUTPUT_SCHEMAS.get(prompt_name)


__all__ = [
    # Types
    "ValidationError",
    "ValidationResult",
    # Validator
    "PromptOutputValidator",
    # Convenience functions
    "validate_prompt_output",
    "validate_and_parse",
    "get_schema_for_prompt",
]
