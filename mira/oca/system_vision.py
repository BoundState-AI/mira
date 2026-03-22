#!/usr/bin/env python3
"""
Module: OCA System Vision
Purpose: Build provisional OCA system-builder graph mockups from uploaded
         system images using Claude vision.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Compliance: SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from mira.providers.llm_provider import resolve_model

from .system_models import (
    ComponentArchetype,
    ComponentConfig,
    InferenceConfidence,
    InferenceSource,
    InferredFact,
    MaterialSlotValue,
    SystemInputs,
    VisionImportQuestionSeverity,
    VisionMockupComponent,
    VisionMockupConnection,
    VisionMockupQuestion,
    VisionMockupResponse,
)

LOGGER = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).resolve().parent / "data"

DEFAULT_MODEL_BEDROCK = os.getenv("OCA_SYSTEM_VISION_MODEL_BEDROCK") or resolve_model("sonnet")
DEFAULT_MODEL_DIRECT = os.getenv("OCA_SYSTEM_VISION_MODEL_DIRECT", "claude-sonnet-4-5-20250929")
USE_BEDROCK = os.getenv("OCA_SYSTEM_VISION_USE_BEDROCK", os.getenv("USE_BEDROCK", "1")).lower() in (
    "1",
    "true",
    "yes",
)
BEDROCK_REGION = os.getenv("OCA_SYSTEM_VISION_BEDROCK_REGION", os.getenv("BEDROCK_REGION", "us-east-1"))
MAX_UPLOAD_BYTES = int(os.getenv("OCA_SYSTEM_VISION_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
SUPPORTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class _VisionLLMComponent(BaseModel):
    temp_id: str
    archetype: ComponentArchetype
    label: str = ""
    materials: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    confidence: str = "medium"
    observations: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class _VisionLLMConnection(BaseModel):
    source_temp_id: str
    source_port: str = "output"
    target_temp_id: str
    target_port: str = "input"
    label: Optional[str] = None
    confidence: str = "medium"
    observations: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class _VisionLLMQuestion(BaseModel):
    severity: str = "review"
    prompt: str
    target_temp_id: Optional[str] = None
    field_path: Optional[str] = None

    model_config = {"extra": "ignore"}


class _VisionLLMResponse(BaseModel):
    suggested_inputs_patch: dict[str, Any] = Field(default_factory=dict)
    components: list[_VisionLLMComponent] = Field(default_factory=list)
    connections: list[_VisionLLMConnection] = Field(default_factory=list)
    questions: list[_VisionLLMQuestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class OCASystemVisionService:
    """Generate provisional OCA system-builder graph drafts from images."""

    def __init__(
        self,
        *,
        use_bedrock: Optional[bool] = None,
        bedrock_region: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> None:
        self._use_bedrock = USE_BEDROCK if use_bedrock is None else use_bedrock
        self._bedrock_region = bedrock_region or BEDROCK_REGION
        self._model_id = model_id
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self._use_bedrock:
                from anthropic import AnthropicBedrock

                self._client = AnthropicBedrock(aws_region=self._bedrock_region)
                if not self._model_id:
                    self._model_id = DEFAULT_MODEL_BEDROCK
            else:
                from anthropic import Anthropic

                self._client = Anthropic()
                if not self._model_id:
                    self._model_id = DEFAULT_MODEL_DIRECT
        return self._client

    def build_mockup(
        self,
        *,
        system_id: str,
        image_bytes: bytes,
        media_type: str,
        filename: str,
        flow_direction_hint: str = "unknown",
        notes: str = "",
        current_inputs: Optional[SystemInputs] = None,
    ) -> VisionMockupResponse:
        if not image_bytes:
            raise ValueError("Uploaded file was empty.")
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"Uploaded file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB vision-import limit."
            )

        normalized_media_type = (media_type or "").strip().lower() or _guess_media_type(filename)
        if normalized_media_type not in SUPPORTED_MEDIA_TYPES:
            raise ValueError(
                "Unsupported file type for OCA vision import. Use PNG, JPEG, WEBP, or GIF."
            )

        client = self._get_client()
        prompt = _build_prompt(flow_direction_hint=flow_direction_hint, notes=notes, current_inputs=current_inputs)
        image_b64 = base64.standard_b64encode(image_bytes).decode()

        LOGGER.info(
            "[OCA Vision] Generating mockup for %s from %s (%s bytes)",
            system_id,
            filename,
            len(image_bytes),
        )

        response = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": normalized_media_type,
                                "data": image_b64,
                            },
                        },
                    ],
                }
            ],
        )

        raw_text = _collect_text_blocks(response.content)
        parsed = _VisionLLMResponse(**_extract_json_object(raw_text))
        positions = _assign_positions(parsed.components, parsed.connections)
        suggested_inputs_patch = _coerce_inputs_patch(parsed.suggested_inputs_patch, current_inputs)

        components: list[VisionMockupComponent] = []
        existing_question_keys = {
            (q.target_temp_id or "", q.field_path or "")
            for q in parsed.questions
        }

        for item in parsed.components:
            temp_id = _normalize_temp_id(item.temp_id)
            label = (item.label or item.archetype.value.replace("_", " ")).strip()
            materials = _coerce_materials(item.materials)
            config = _coerce_config(item.config)
            confidence = _normalize_confidence(item.confidence)
            inferred_facts = [
                InferredFact(
                    fact_name="vision_import",
                    value=True,
                    source=InferenceSource.IMPORTED,
                    confidence=confidence,
                    rule_id="VISION-001",
                    explanation=_build_component_explanation(filename, item.observations, item.archetype, label),
                    missing_assumptions=[],
                )
            ]

            components.append(
                VisionMockupComponent(
                    temp_id=temp_id,
                    archetype=item.archetype,
                    label=label,
                    position_x=positions[temp_id][0],
                    position_y=positions[temp_id][1],
                    materials=materials,
                    config=config,
                    is_provisional=True,
                    human_confirmed=False,
                    inferred_facts=inferred_facts,
                    confidence=confidence,
                )
            )

            if not materials and (temp_id, "materials") not in existing_question_keys:
                parsed.questions.append(
                    _VisionLLMQuestion(
                        severity="blocking",
                        prompt=f"Confirm wetted materials for '{label}'.",
                        target_temp_id=temp_id,
                        field_path="materials",
                    )
                )
                existing_question_keys.add((temp_id, "materials"))

        questions = [
            VisionMockupQuestion(
                severity=_normalize_question_severity(item.severity),
                prompt=item.prompt.strip(),
                target_temp_id=_normalize_temp_id(item.target_temp_id) if item.target_temp_id else None,
                field_path=item.field_path.strip() if item.field_path else None,
            )
            for item in parsed.questions
            if item.prompt.strip()
        ]

        connections = [
            VisionMockupConnection(
                source_temp_id=_normalize_temp_id(item.source_temp_id),
                source_port=(item.source_port or "output").strip() or "output",
                target_temp_id=_normalize_temp_id(item.target_temp_id),
                target_port=(item.target_port or "input").strip() or "input",
                label=item.label.strip() if item.label else None,
                confidence=_normalize_confidence(item.confidence),
            )
            for item in parsed.connections
            if item.source_temp_id and item.target_temp_id
        ]

        warnings = [warning.strip() for warning in parsed.warnings if warning.strip()]
        if not components:
            warnings.append("Vision import could not confidently identify a system topology from the uploaded image.")

        return VisionMockupResponse(
            system_id=system_id,
            model_used=self._model_id or "",
            suggested_inputs_patch=suggested_inputs_patch,
            components=components,
            connections=connections,
            questions=questions,
            warnings=warnings,
        )


def _guess_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def _build_prompt(*, flow_direction_hint: str, notes: str, current_inputs: Optional[SystemInputs]) -> str:
    current_inputs_json = json.dumps(current_inputs.model_dump() if current_inputs else {}, indent=2, default=str)
    library = _load_component_library()
    archetype_lines = []
    for item in library.get("archetypes", []):
        archetype_id = item.get("archetype_id", "")
        slots = ", ".join(slot.get("slot", "") for slot in item.get("material_slots", []) if slot.get("slot"))
        config_fields = ", ".join(field.get("field", "") for field in item.get("config_fields", []) if field.get("field"))
        archetype_lines.append(
            f"- {archetype_id}: slots=[{slots or 'none'}]; config=[{config_fields or 'none'}]"
        )

    notes_text = notes.strip() or "None"
    return f"""You are generating a provisional OCA system-builder graph from a single uploaded system image.

Goal:
- Produce a first-pass topology mockup for the OCA System Builder.
- This is a screening draft, not a final engineering assessment.
- Favor explicit uncertainty over guessing.

Current system inputs:
{current_inputs_json}

Flow direction hint: {flow_direction_hint}
User notes: {notes_text}

Allowed component archetypes:
{chr(10).join(archetype_lines)}

Return JSON only with this schema:
{{
  "suggested_inputs_patch": {{
    "project_name": "",
    "hardware_name": "",
    "design_flow_rate_m3_s": null,
    "cleanliness_spec": null
  }},
  "components": [
    {{
      "temp_id": "cmp_1",
      "archetype": "valve",
      "label": "Main Isolation Valve",
      "materials": [
        {{
          "slot_name": "body_material",
          "material": {{
            "material_name": "316L Stainless Steel",
            "spec": null,
            "identity_confidence": 0.92,
            "is_titanium": false,
            "is_nonmetal": false
          }}
        }}
      ],
      "config": {{
        "valve_type": "ball",
        "actuation_type": "manual"
      }},
      "confidence": "medium",
      "observations": ["Label 'ISO VLV' is visible.", "Symbol matches a manual valve."]
    }}
  ],
  "connections": [
    {{
      "source_temp_id": "cmp_1",
      "source_port": "output",
      "target_temp_id": "cmp_2",
      "target_port": "input",
      "label": null,
      "confidence": "medium",
      "observations": ["A single line connects the valve to the downstream regulator."]
    }}
  ],
  "questions": [
    {{
      "severity": "blocking",
      "prompt": "Confirm the seat material for Main Isolation Valve.",
      "target_temp_id": "cmp_1",
      "field_path": "materials"
    }}
  ],
  "warnings": ["Short note about global ambiguity."]
}}

Rules:
1. Use only the allowed component archetypes.
2. Infer topology and flow order. Do not infer precise geometry.
3. Only populate materials when the image text or symbols make them reasonably explicit.
4. If a material, component type, or connection is ambiguous, add a question instead of guessing.
5. Use "blocking" questions for missing materials or unclear topology that would block assessment.
6. Use "review" questions for labels, config values, or non-critical ambiguity.
7. Keep components in approximate flow order.
8. Return empty component and connection lists if the image is not usable.
9. Return valid JSON only. No markdown fences.
"""


def _load_component_library() -> dict[str, Any]:
    with open(_DATA_DIR / "oca_component_library.json", encoding="utf-8") as handle:
        return json.load(handle)


def _collect_text_blocks(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("Claude vision response did not contain a valid JSON object.")


def _coerce_inputs_patch(
    patch: dict[str, Any],
    current_inputs: Optional[SystemInputs],
) -> dict[str, Any]:
    if not patch:
        return {}
    valid_fields = set(SystemInputs.model_fields)
    base = current_inputs.model_dump() if current_inputs else SystemInputs().model_dump()
    merged = dict(base)
    for key, value in patch.items():
        if key in valid_fields:
            merged[key] = value
    validated = SystemInputs(**merged).model_dump()
    return {key: validated[key] for key in patch if key in validated and validated[key] != base.get(key)}


def _coerce_materials(materials: list[dict[str, Any]]) -> list[MaterialSlotValue]:
    coerced: list[MaterialSlotValue] = []
    for item in materials:
        try:
            coerced.append(MaterialSlotValue(**item))
        except Exception:
            LOGGER.debug("[OCA Vision] Dropping invalid material payload: %s", item, exc_info=True)
    return coerced


def _coerce_config(config: dict[str, Any]) -> ComponentConfig:
    try:
        return ComponentConfig(**config)
    except Exception:
        LOGGER.debug("[OCA Vision] Dropping invalid config payload: %s", config, exc_info=True)
        return ComponentConfig()


def _normalize_temp_id(raw_value: Optional[str]) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", (raw_value or "").strip()).strip("_")
    return token or "cmp"


def _normalize_confidence(raw_value: Any) -> InferenceConfidence:
    if isinstance(raw_value, InferenceConfidence):
        return raw_value
    normalized = str(raw_value or "medium").strip().lower()
    if normalized not in {"high", "medium", "low"}:
        normalized = "medium"
    return InferenceConfidence(normalized)


def _normalize_question_severity(raw_value: Any) -> VisionImportQuestionSeverity:
    normalized = str(raw_value or "review").strip().lower()
    if normalized != VisionImportQuestionSeverity.BLOCKING.value:
        normalized = VisionImportQuestionSeverity.REVIEW.value
    return VisionImportQuestionSeverity(normalized)


def _build_component_explanation(
    filename: str,
    observations: list[str],
    archetype: ComponentArchetype,
    label: str,
) -> str:
    observation_text = " ".join(obs.strip() for obs in observations if obs.strip())
    if observation_text:
        return (
            f"Imported from uploaded image '{filename}' as {archetype.value} '{label}'. "
            f"{observation_text}"
        ).strip()
    return f"Imported from uploaded image '{filename}' as {archetype.value} '{label}'."


def _assign_positions(
    components: list[_VisionLLMComponent],
    connections: list[_VisionLLMConnection],
) -> dict[str, tuple[float, float]]:
    order = [_normalize_temp_id(component.temp_id) for component in components]
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {temp_id: 0 for temp_id in order}

    for item in connections:
        source = _normalize_temp_id(item.source_temp_id)
        target = _normalize_temp_id(item.target_temp_id)
        if source not in indegree or target not in indegree:
            continue
        adjacency[source].append(target)
        indegree[target] += 1

    queue = deque(temp_id for temp_id in order if indegree[temp_id] == 0)
    topo_order: list[str] = []
    while queue:
        current = queue.popleft()
        topo_order.append(current)
        for neighbor in adjacency.get(current, []):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    for temp_id in order:
        if temp_id not in topo_order:
            topo_order.append(temp_id)

    depth: dict[str, int] = {temp_id: 0 for temp_id in order}
    for temp_id in topo_order:
        for neighbor in adjacency.get(temp_id, []):
            depth[neighbor] = max(depth.get(neighbor, 0), depth[temp_id] + 1)

    lanes: dict[int, list[str]] = defaultdict(list)
    for temp_id in topo_order:
        lanes[depth.get(temp_id, 0)].append(temp_id)

    positions: dict[str, tuple[float, float]] = {}
    for lane_index in sorted(lanes):
        for row_index, temp_id in enumerate(lanes[lane_index]):
            positions[temp_id] = (120.0 + (lane_index * 280.0), 120.0 + (row_index * 180.0))
    return positions

