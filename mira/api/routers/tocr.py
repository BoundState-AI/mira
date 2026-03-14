#!/usr/bin/env python3
"""
TOCR API router.

MIRA surface for SENTINEL-TOCR task order compliance review.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import ContractType, RevisionStatus
from sentinel.tocr.models.report import ComplianceReport
from sentinel.tocr.models.task_order import TaskOrder
from sentinel.tocr.parsers.atoms_parser import ATOMSParser
from sentinel.tocr.parsers.docx_parser import DOCXParser
from sentinel.tocr.parsers.essca_parser import ESSCAParser
from sentinel.tocr.parsers.pdf_parser import PDFParser


router = APIRouter()

_ROOT = Path(__file__).resolve().parents[3]
_GUIDANCE_PATH = _ROOT / "sentinel" / "tocr" / "data" / "guidance.json"
_GUIDANCE_CACHE: dict[str, Any] | None = None


class TOCRScanResponse(BaseModel):
    mode: Literal["scan"]
    parser_selected: str
    parsed_task_order: TaskOrder
    report: ComplianceReport
    guidance: dict[str, dict[str, str]] = Field(default_factory=dict)


class TOCRReviewResponse(BaseModel):
    mode: Literal["review"]
    prior_parser_selected: str
    proposed_parser_selected: str
    prior_task_order: TaskOrder
    proposed_task_order: TaskOrder
    report: ComplianceReport
    guidance: dict[str, dict[str, str]] = Field(default_factory=dict)


TOCRScanResponse.model_rebuild()
TOCRReviewResponse.model_rebuild()


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "tocr", "version": "0.1.0"}


@router.get("/guidance")
async def guidance() -> dict[str, Any]:
    return _load_guidance()


@router.post("/scan", response_model=TOCRScanResponse)
async def scan_task_order(
    source_file: UploadFile = File(...),
    parser_hint: str = Form("auto"),
    agency: str = Form("NASA"),
    center: str | None = Form(None),
    vehicle: str | None = Form("ESSCA"),
    local_policy_pack: str | None = Form("ESSCA-MSFC"),
    contract_types: str = Form("IDIQ,Task Order"),
    clauses_present: str = Form("FAR 52.232-22"),
    revision_status: str | None = Form(None),
    use_sonnet: bool = Form(False),
) -> TOCRScanResponse:
    task_order, parser_selected = await _parse_upload(source_file, parser_hint)
    config = _build_contract_config(
        agency=agency,
        center=center,
        vehicle=vehicle,
        local_policy_pack=local_policy_pack,
        contract_types=contract_types,
        clauses_present=clauses_present,
        revision_status=revision_status or task_order.revision_status.value,
    )
    conductor = TOCRConductor(config=config)
    report = await conductor.scan_with_sonnet(task_order) if use_sonnet else conductor.scan(task_order)
    return TOCRScanResponse(
        mode="scan",
        parser_selected=parser_selected,
        parsed_task_order=task_order,
        report=report,
        guidance=_guidance_for_report(report),
    )


@router.post("/review", response_model=TOCRReviewResponse)
async def review_task_order(
    prior_file: UploadFile = File(...),
    proposed_file: UploadFile = File(...),
    prior_parser_hint: str = Form("auto"),
    proposed_parser_hint: str = Form("auto"),
    agency: str = Form("NASA"),
    center: str | None = Form(None),
    vehicle: str | None = Form("ESSCA"),
    local_policy_pack: str | None = Form("ESSCA-MSFC"),
    contract_types: str = Form("IDIQ,Task Order"),
    clauses_present: str = Form("FAR 52.232-22"),
    revision_status: str | None = Form(None),
    use_sonnet: bool = Form(False),
) -> TOCRReviewResponse:
    prior_task_order, prior_parser_selected = await _parse_upload(prior_file, prior_parser_hint)
    proposed_task_order, proposed_parser_selected = await _parse_upload(proposed_file, proposed_parser_hint)
    config = _build_contract_config(
        agency=agency,
        center=center,
        vehicle=vehicle,
        local_policy_pack=local_policy_pack,
        contract_types=contract_types,
        clauses_present=clauses_present,
        revision_status=revision_status or proposed_task_order.revision_status.value,
    )
    conductor = TOCRConductor(config=config)
    report = (
        await conductor.review_with_sonnet(prior_task_order, proposed_task_order)
        if use_sonnet
        else conductor.review(prior_task_order, proposed_task_order)
    )
    return TOCRReviewResponse(
        mode="review",
        prior_parser_selected=prior_parser_selected,
        proposed_parser_selected=proposed_parser_selected,
        prior_task_order=prior_task_order,
        proposed_task_order=proposed_task_order,
        report=report,
        guidance=_guidance_for_report(report),
    )


def _load_guidance() -> dict[str, Any]:
    global _GUIDANCE_CACHE
    if _GUIDANCE_CACHE is None:
        if not _GUIDANCE_PATH.exists():
            raise HTTPException(status_code=500, detail="TOCR guidance pack is missing.")
        _GUIDANCE_CACHE = json.loads(_GUIDANCE_PATH.read_text(encoding="utf-8"))
    return _GUIDANCE_CACHE


def _guidance_for_report(report: ComplianceReport) -> dict[str, dict[str, str]]:
    entries = _load_guidance().get("entries", {})
    return {
        finding.rule_id: entries[finding.rule_id]
        for finding in report.findings
        if finding.rule_id in entries
    }


def _split_multi_value(raw_value: str) -> list[str]:
    return [item.strip() for chunk in raw_value.splitlines() for item in chunk.split(",") if item.strip()]


def _parse_contract_types(raw_value: str) -> list[ContractType]:
    parsed: list[ContractType] = []
    for item in _split_multi_value(raw_value):
        normalized = item.strip().upper().replace("_", " ").replace("-", " ")
        if normalized == "IDIQ":
            parsed.append(ContractType.IDIQ)
        elif normalized in {"TASK ORDER", "TASKORDER"}:
            parsed.append(ContractType.TASK_ORDER)
        elif normalized == "BPA":
            parsed.append(ContractType.BPA)
        elif normalized == "BOA":
            parsed.append(ContractType.BOA)
        elif normalized == "CPAF":
            parsed.append(ContractType.CPAF)
        elif normalized == "CPFF":
            parsed.append(ContractType.CPFF)
        elif normalized == "FFP":
            parsed.append(ContractType.FFP)
        elif normalized in {"T&M", "T M", "TIME AND MATERIAL", "TIME & MATERIAL"}:
            parsed.append(ContractType.T_AND_M)
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported contract type '{item}'.")
    return parsed or [ContractType.IDIQ, ContractType.TASK_ORDER]


def _parse_revision_status(raw_value: str) -> RevisionStatus:
    normalized = raw_value.strip().lower()
    if normalized == "draft":
        return RevisionStatus.DRAFT
    if normalized == "released":
        return RevisionStatus.RELEASED
    raise HTTPException(status_code=422, detail=f"Unsupported revision status '{raw_value}'.")


def _build_contract_config(
    *,
    agency: str,
    center: str | None,
    vehicle: str | None,
    local_policy_pack: str | None,
    contract_types: str,
    clauses_present: str,
    revision_status: str,
) -> ContractConfig:
    return ContractConfig(
        agency=agency.strip() or "NASA",
        center=center.strip() if center and center.strip() else None,
        vehicle=vehicle.strip() if vehicle and vehicle.strip() else None,
        local_policy_pack=local_policy_pack.strip() if local_policy_pack and local_policy_pack.strip() else None,
        contract_type=_parse_contract_types(contract_types),
        clauses_present=_split_multi_value(clauses_present),
        revision_status=_parse_revision_status(revision_status),
    )


async def _parse_upload(upload: UploadFile, parser_hint: str) -> tuple[TaskOrder, str]:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must include a filename.")

    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=400, detail=f"Uploaded file '{upload.filename}' is empty.")

    suffix = Path(upload.filename).suffix.lower()
    hint = parser_hint.strip().lower()

    if hint == "atoms":
        return _parse_atoms_payload(payload), "atoms"

    if hint not in {"auto", "docx", "essca", "pdf"}:
        raise HTTPException(status_code=422, detail=f"Unsupported parser hint '{parser_hint}'.")

    if suffix == ".json":
        return _parse_atoms_payload(payload), "atoms"

    with tempfile.TemporaryDirectory(prefix="tocr-upload-") as tmpdir:
        source_path = Path(tmpdir) / f"source{suffix or '.bin'}"
        source_path.write_bytes(payload)
        return _parse_path(source_path, hint)


def _parse_atoms_payload(payload: bytes) -> TaskOrder:
    try:
        return ATOMSParser().parse(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON upload must be UTF-8 encoded.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid TOCR JSON upload: {exc}") from exc


def _parse_path(source_path: Path, parser_hint: str) -> tuple[TaskOrder, str]:
    suffix = source_path.suffix.lower()

    if parser_hint == "pdf":
        if suffix != ".pdf":
            raise HTTPException(status_code=400, detail="PDF parser hint requires a .pdf upload.")
        return _safe_parse(lambda: PDFParser().parse(source_path), "pdf")

    if parser_hint == "essca":
        if suffix not in {".docx", ".docm"}:
            raise HTTPException(status_code=400, detail="ESSCA parser hint requires a DOCX upload.")
        return _safe_parse(lambda: ESSCAParser().parse(source_path), "essca")

    if parser_hint == "docx":
        if suffix not in {".docx", ".docm"}:
            raise HTTPException(status_code=400, detail="DOCX parser hint requires a DOCX upload.")
        return _safe_parse(lambda: DOCXParser().parse(source_path), "docx")

    if suffix == ".pdf":
        return _safe_parse(lambda: PDFParser().parse(source_path), "pdf")

    if suffix in {".docx", ".docm"}:
        essca_result, essca_error = _try_parse_essca(source_path)
        if essca_result is not None:
            return essca_result, "essca"
        docx_result, docx_error = _try_parse_docx(source_path)
        if docx_result is not None:
            return docx_result, "docx"
        detail = "Unable to parse DOCX task order."
        if essca_error or docx_error:
            detail = f"{detail} ESSCA error: {essca_error or 'n/a'}; DOCX error: {docx_error or 'n/a'}"
        raise HTTPException(status_code=400, detail=detail)

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported TOCR upload type '{suffix or 'unknown'}'. Use .json, .docx, .docm, or .pdf.",
    )


def _safe_parse(parse_fn, parser_name: str) -> tuple[TaskOrder, str]:
    try:
        return parse_fn(), parser_name
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse {parser_name} task order: {exc}") from exc


def _try_parse_essca(source_path: Path) -> tuple[TaskOrder | None, str | None]:
    try:
        task_order = ESSCAParser().parse(source_path)
    except Exception as exc:
        return None, str(exc)
    if _looks_like_essca_parse(task_order, source_path):
        return task_order, None
    return None, "document did not match ESSCA structure"


def _try_parse_docx(source_path: Path) -> tuple[TaskOrder | None, str | None]:
    try:
        return DOCXParser().parse(source_path), None
    except Exception as exc:
        return None, str(exc)


def _looks_like_essca_parse(task_order: TaskOrder, source_path: Path) -> bool:
    return bool(
        task_order.sub_tasks
        or task_order.funding_table
        or task_order.summary_of_changes.strip()
        or task_order.task_order_number != source_path.stem
        or task_order.source_format == "docx-essca"
    )
