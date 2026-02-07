#!/usr/bin/env python3
"""
Module: Orchestrator
Purpose: ATHENA Pipeline Orchestrator.

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

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from athena.config import AthenaConfig
from athena.models.document import Document, ProcessingEvent
from athena.models.enums import DocumentStatus, RoutingDecision
from athena.pipeline.extract import ExtractionStage
from athena.pipeline.index import IndexingStage
from athena.pipeline.ingest import IngestPipeline
from athena.pipeline.reconcile import ConservativeReconciler, ReconciliationConfig
from athena.pipeline.triage import TriageStage
from athena.providers.base import LLMProvider
from athena.services.cache import ExtractionCache
from athena.services.cost import BudgetEnforcer, CostTracker
from athena.services.storage import FileStore

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrate the full ATHENA document processing pipeline."""

    def __init__(
        self,
        config: AthenaConfig,
        llm: LLMProvider,
        db,
        storage: FileStore | None = None,
        cache: ExtractionCache | None = None,
    ):
        """Initialize pipeline orchestrator.

        Args:
            config: ATHENA configuration
            llm: LLM provider
            db: Database client
            storage: Optional file storage
            cache: Optional extraction cache
        """
        self.config = config
        self.llm = llm
        self.db = db
        self.storage = storage
        self.cache = cache

        # Initialize stages
        self.cost_tracker = CostTracker(db)
        self.budget_enforcer = BudgetEnforcer(db)

        self.ingest = IngestPipeline(config, storage, db, llm) if storage else None
        self.triage = TriageStage(config, llm, self.cost_tracker)
        self.extract = ExtractionStage(config, llm, self.cost_tracker, storage)
        self.reconcile = ConservativeReconciler(ReconciliationConfig())
        self.index = IndexingStage(config)

    async def process_file(
        self,
        file_path: Path,
        batch_id: str,
        tenant_id: str,
    ) -> list[Document]:
        """Process a single file through the full pipeline.

        Args:
            file_path: Path to PDF file
            batch_id: Batch ID
            tenant_id: Tenant ID

        Returns:
            List of processed Document records
        """
        import fitz

        logger.info(f"Processing file: {file_path.name}")

        # Ingest
        if self.ingest:
            documents = await self.ingest.ingest_file(
                file_path, batch_id, tenant_id
            )
        else:
            # Create single document without storage
            doc = fitz.open(file_path)
            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=file_path.name,
                source_path=str(file_path),
                source_hash="",
                page_range=(1, len(doc)),
                page_count=len(doc),
                pipeline_version=self.config.pipeline_version,
            )
            documents = [document]
            doc.close()

        # Process each document
        processed = []
        for doc in documents:
            try:
                result = await self.process_document(doc, batch_id)
                processed.append(result)
            except Exception as e:
                logger.error(f"Failed to process document {doc.document_id}: {e}")
                doc.status = DocumentStatus.FAILED
                doc.processing_log.append(
                    ProcessingEvent(
                        stage="orchestrator",
                        status="failed",
                        error=str(e),
                    )
                )
                await self.db.update_document(doc)
                processed.append(doc)

        return processed

    async def process_document(
        self,
        doc: Document,
        batch_id: str,
    ) -> Document:
        """Process a single document through pipeline stages.

        Args:
            doc: Document to process
            batch_id: Batch ID

        Returns:
            Processed document
        """
        import fitz

        logger.info(f"Processing document {doc.document_id}")

        # Check budget
        can_proceed, budget_status = await self.budget_enforcer.check_budget(
            batch_id, estimated_cost=0.05  # Estimate
        )
        if not can_proceed:
            logger.warning(f"Budget exceeded for batch {batch_id}: {budget_status}")
            doc.status = DocumentStatus.FAILED
            doc.processing_log.append(
                ProcessingEvent(
                    stage="budget_check",
                    status="failed",
                    error=budget_status,
                )
            )
            return doc

        # Open PDF
        if self.storage:
            pdf_bytes = await self.storage.download(doc.source_path.replace("s3://", "").split("/", 1)[1])
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        else:
            pdf = fitz.open(doc.source_path)

        try:
            # Stage 1: Triage
            if doc.status == DocumentStatus.PENDING:
                triage_result = await self.triage.triage_document(doc, pdf)
                doc = await self.triage.update_document_status(doc, triage_result, self.db)
                logger.info(
                    f"Document {doc.document_id} triaged: "
                    f"type={triage_result.document_type}, routing={triage_result.routing.value}"
                )

            # Stage 2: Extraction (if not skip/rescan)
            if doc.status == DocumentStatus.TRIAGED and doc.routing in [
                RoutingDecision.EXTRACT_FULL,
                RoutingDecision.EXTRACT_LIGHT,
                RoutingDecision.EXTRACT_DRAWING,
                RoutingDecision.EXTRACT_STANDARD,
                RoutingDecision.EXTRACT_DATA_TABLE,
            ]:
                extraction_result = await self.extract.extract_document(doc, pdf)
                doc = await self.extract.update_document_status(
                    doc, extraction_result, self.db
                )
                logger.info(
                    f"Document {doc.document_id} extracted: "
                    f"{len(extraction_result.fields)} fields, "
                    f"coverage={extraction_result.evidence_coverage:.2%}"
                )

            # Stage 3: Indexing
            if doc.status == DocumentStatus.EXTRACTED:
                doc = await self.index.index_document(doc, self.db)
                logger.info(f"Document {doc.document_id} indexed")

        finally:
            pdf.close()

        return doc

    async def process_batch(
        self,
        batch_id: str,
        tenant_id: str,
        file_paths: list[Path] | None = None,
    ) -> dict:
        """Process a batch of files.

        Args:
            batch_id: Batch ID
            tenant_id: Tenant ID
            file_paths: Optional list of file paths

        Returns:
            Batch processing summary
        """
        start_time = datetime.utcnow()

        # Get files to process
        if file_paths:
            files = file_paths
        else:
            # Get pending documents from batch
            documents = await self.db.get_documents_by_batch(batch_id)
            files = None

        processed = 0
        failed = 0
        all_documents = []

        if files:
            # Process files concurrently with limit
            semaphore = asyncio.Semaphore(self.config.max_concurrent_jobs)

            async def process_with_limit(path):
                async with semaphore:
                    return await self.process_file(path, batch_id, tenant_id)

            results = await asyncio.gather(
                *[process_with_limit(f) for f in files],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    failed += 1
                    logger.error(f"File processing failed: {result}")
                else:
                    all_documents.extend(result)
                    processed += len(result)
        else:
            # Process existing documents
            documents = await self.db.get_documents_by_batch(batch_id)
            for doc in documents:
                if doc.status in [DocumentStatus.PENDING, DocumentStatus.TRIAGED]:
                    try:
                        result = await self.process_document(doc, batch_id)
                        all_documents.append(result)
                        processed += 1
                    except Exception as e:
                        failed += 1
                        logger.error(f"Document {doc.document_id} failed: {e}")

        # Get batch cost
        total_cost = await self.cost_tracker.get_batch_total(batch_id)

        duration = (datetime.utcnow() - start_time).total_seconds()

        return {
            "batch_id": batch_id,
            "documents_processed": processed,
            "documents_failed": failed,
            "total_documents": processed + failed,
            "total_cost_usd": total_cost,
            "duration_seconds": duration,
            "documents": [d.document_id for d in all_documents],
        }

    async def reconcile_batch(
        self,
        batch_id: str,
    ) -> dict:
        """Run entity reconciliation for a batch.

        Args:
            batch_id: Batch ID

        Returns:
            Reconciliation summary
        """
        # Get all entities from batch documents
        documents = await self.db.get_documents_by_batch(batch_id)

        all_mentions = []
        for doc in documents:
            if doc.triage_result and doc.triage_result.entities:
                # Convert entity bag to mentions
                mentions = self._entities_to_mentions(
                    doc.triage_result.entities,
                    doc.document_id,
                )
                all_mentions.extend(mentions)

        if not all_mentions:
            return {
                "batch_id": batch_id,
                "mentions_found": 0,
                "links_proposed": 0,
            }

        # Run reconciliation
        links = await self.reconcile.reconcile_entities(all_mentions)

        # Store proposed links
        for link in links:
            await self.db.insert_entity_link(link)

        # Create review items for manual review
        mentions_by_id = {m.mention_id: m for m in all_mentions}
        review_items = await self.reconcile.create_review_items(
            links, mentions_by_id, self.storage
        )

        for item in review_items:
            await self.db.insert_review_item(item)

        return {
            "batch_id": batch_id,
            "mentions_found": len(all_mentions),
            "links_proposed": len(links),
            "auto_approved": sum(1 for l in links if l.status.value == "auto_approved"),
            "pending_review": len(review_items),
        }

    def _entities_to_mentions(
        self,
        entities,
        document_id,
    ) -> list:
        """Convert EntityBag to EntityMention list.

        Args:
            entities: EntityBag from triage
            document_id: Document ID

        Returns:
            List of EntityMention objects
        """
        from athena.models.entity import EntityMention
        from athena.models.enums import EntityType
        from athena.models.evidence import BoundingBox, Evidence
        from athena.utils.parsing import normalize_text

        mentions = []

        type_mapping = {
            "equipment": EntityType.EQUIPMENT,
            "people": EntityType.PERSON,
            "locations": EntityType.LOCATION,
            "organizations": EntityType.ORGANIZATION,
            "references": EntityType.REFERENCE,
            "dates": EntityType.DATE,
            "materials": EntityType.MATERIAL,
        }

        for attr_name, entity_type in type_mapping.items():
            for text in getattr(entities, attr_name, []):
                if text:
                    mention = EntityMention(
                        text=text,
                        normalized_text=normalize_text(text),
                        document_id=document_id,
                        page=1,  # Would need actual page from evidence
                        evidence=Evidence(
                            page=1,
                            bbox=BoundingBox(x_min=0, y_min=0, x_max=1, y_max=1),
                            snippet_hash="",
                            confidence=0.5,
                        ),
                        entity_type=entity_type,
                        confidence=0.5,
                    )
                    mentions.append(mention)

        return mentions
