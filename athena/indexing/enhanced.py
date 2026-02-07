#!/usr/bin/env python3
"""
Module: Enhanced
Purpose: Enhanced analysis result with promotion metadata.

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

import argparse
import logging
import sys
import time
import re
import uuid
import hashlib
import unicodedata
import os
import pickle
import json
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Any, Tuple
from collections import Counter, defaultdict

# Import existing BoundState components
from boundstate.smart_indexer import SmartIndexer
from boundstate.config import CONFIG

# Import enhanced parser dispatcher for CAD files
try:
    from EM32.enhanced_parser_dispatcher import get_enhanced_parser as get_parser
    logger.info("Enhanced smart indexer using enhanced parser dispatcher")
except ImportError:
    from boundstate.parsers import get_parser
    logger.info("Enhanced smart indexer using standard BoundState parsers")

logger = logging.getLogger(__name__)

@dataclass
class DocumentAnalysisResult:
    """Enhanced analysis result with promotion metadata."""
    doc_id: str
    file_path: str
    content_hash: str
    document_type: str
    classification_confidence: float
    processing_mode: str  # 'pre_chunk', 'doc_level', 'metadata_only'

    # Content analysis
    text_length: int
    section_count: int
    table_count: int
    figure_count: int

    # Promotion tracking
    indexed_at: float
    access_count: int = 0
    unique_users: List[str] = None
    last_accessed: Optional[float] = None

    # NASA compliance
    has_requirements: bool = False
    requirement_count: int = 0
    has_verification: bool = False
    compliance_tags: List[str] = None

    def __post_init__(self):
        if self.unique_users is None:
            self.unique_users = []
        if self.compliance_tags is None:
            self.compliance_tags = []

class PromotionTrackingIndexer(SmartIndexer):
    """
    Enhanced Smart Indexer with promotion tracking and content hashing.

    Extends the existing SmartIndexer with:
    - Document usage tracking
    - Content hash computation
    - Promotion candidate detection
    - Enhanced NASA compliance analysis
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Usage tracking
        self.access_tracker = defaultdict(lambda: {
            'count': 0,
            'users': set(),
            'last_access': 0.0,
            'content_hash': ''
        })

        # Promotion candidates
        self.promotion_candidates = set()

        # Content hashes for cache invalidation
        self.content_hashes = {}

        # Enhanced analysis storage
        self.analysis_results = {}

        # Promotion thresholds (configurable)
        self.promotion_config = {
            'min_hits': getattr(CONFIG, 'promotion_min_hits', 3),
            'min_users': getattr(CONFIG, 'promotion_min_users', 2),
            'window_hours': getattr(CONFIG, 'promotion_window_hours', 48),
            'auto_promote_allowlist': getattr(CONFIG, 'auto_promote_allowlist', True)
        }

        # NASA compliance patterns
        self.compliance_patterns = {
            'requirements': [
                r'\bshall\b',
                r'\bmust\b',
                r'\brequirement\s+\d+',
                r'\b[A-Z]+-\d+\.\d+',  # NASA requirement IDs
            ],
            'verification': [
                r'\bverif(?:y|ication)\b',
                r'\btest\s+method\b',
                r'\baccept(?:ance|able)\s+criteri[ao]n?\b',
            ],
            'standards': [
                r'\bNASA-STD-\d+',
                r'\bNPR-\d+',
                r'\bMSFC-STD-\d+',
                r'\bASTM-[A-Z]\d+',
            ]
        }

        logger.info("Initialized PromotionTrackingIndexer")

    def compute_content_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file content for cache invalidation."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            hash_value = hasher.hexdigest()[:16]  # First 16 chars for brevity

            # Store for later reference
            self.content_hashes[file_path] = hash_value
            return hash_value

        except Exception as e:
            logger.error(f"Failed to hash {file_path}: {e}")
            return "unknown"

    def analyze_document_enhanced(self, file_path: str, doc_id: str = None) -> DocumentAnalysisResult:
        """
        Enhanced document analysis with promotion tracking.

        Extends the base analysis with:
        - Content hashing
        - NASA compliance analysis
        - Processing mode determination
        - Promotion metadata initialization
        """
        try:
            if doc_id is None:
                doc_id = str(uuid.uuid4())

            # Compute content hash
            content_hash = self.compute_content_hash(file_path)

            # Parse document using enhanced parser for CAD files
            file_ext = os.path.splitext(file_path)[1].lower()
            cad_extensions = {'.par', '.asm', '.igs', '.iges', '.1', '.2', '.3', '.4', '.5', '.dat', '.raww'}

            if file_ext in cad_extensions and CAD_PARSER_AVAILABLE:
                parser = EnhancedCADParser(file_path)
                logger.debug(f"Using enhanced CAD parser for {file_ext} file")
            else:
                parser = get_parser(file_path)

            parsed_result = parser.parse()

            if not parsed_result:
                logger.warning(f"Failed to parse {file_path}")
                return None

            full_text = parsed_result.get('full_text', '')

            # Perform existing classification
            doc_type, confidence = self._classify_document_type_enhanced(full_text, file_path)

            # Determine processing mode based on classification and file characteristics
            processing_mode = self._determine_processing_mode(file_path, doc_type, len(full_text))

            # Analyze content structure
            structure_analysis = self._analyze_content_structure(parsed_result)

            # NASA compliance analysis
            compliance_analysis = self._analyze_nasa_compliance(full_text)

            # Create analysis result
            result = DocumentAnalysisResult(
                doc_id=doc_id,
                file_path=file_path,
                content_hash=content_hash,
                document_type=doc_type,
                classification_confidence=confidence,
                processing_mode=processing_mode,
                text_length=len(full_text),
                section_count=structure_analysis['sections'],
                table_count=structure_analysis['tables'],
                figure_count=structure_analysis['figures'],
                indexed_at=time.time(),
                has_requirements=compliance_analysis['has_requirements'],
                requirement_count=compliance_analysis['requirement_count'],
                has_verification=compliance_analysis['has_verification'],
                compliance_tags=compliance_analysis['tags']
            )

            # Store analysis result
            self.analysis_results[doc_id] = result

            logger.debug(f"Enhanced analysis complete for {doc_id}: {doc_type} ({processing_mode})")
            return result

        except Exception as e:
            logger.error(f"Enhanced document analysis failed for {file_path}: {e}")
            return None

    def _classify_document_type_enhanced(self, content: str, file_path: str) -> Tuple[str, float]:
        """Enhanced document classification with NASA-specific types."""
        content_lower = content.lower()
        filename = os.path.basename(file_path).lower()

        # NASA document type patterns
        nasa_patterns = {
            'nasa_standard': (
                [r'nasa-std-\d+', r'nasa\s+standard', r'technical\s+standard'],
                0.9
            ),
            'nasa_handbook': (
                [r'nasa-hdbk-\d+', r'nasa\s+handbook', r'design\s+handbook'],
                0.85
            ),
            'nasa_procedure': (
                [r'npr-\d+', r'procedure', r'operating\s+procedure'],
                0.8
            ),
            'specification': (
                [r'specification', r'spec\b', r'shall\b.*requirement'],
                0.85
            ),
            'policy': (
                [r'policy', r'directive', r'instruction'],
                0.8
            ),
            'test_report': (
                [r'test\s+report', r'analysis\s+report', r'test\s+results'],
                0.75
            ),
            'form': (
                [r'form\s+\d+', r'questionnaire', r'checklist'],
                0.7
            )
        }

        # Check NASA patterns first
        for doc_type, (patterns, base_confidence) in nasa_patterns.items():
            pattern_matches = 0
            for pattern in patterns:
                if re.search(pattern, content_lower) or re.search(pattern, filename):
                    pattern_matches += 1

            if pattern_matches > 0:
                confidence = min(0.95, base_confidence + (pattern_matches - 1) * 0.05)
                return doc_type, confidence

        # Fallback to existing classification if available
        if hasattr(super(), '_classify_document_type'):
            return super()._classify_document_type(content, file_path)

        # Basic classification fallback
        if any(term in content_lower for term in ['requirement', 'shall', 'must']):
            return 'specification', 0.6
        elif any(term in content_lower for term in ['procedure', 'step', 'instruction']):
            return 'procedure', 0.6
        elif any(term in content_lower for term in ['report', 'analysis', 'result']):
            return 'report', 0.6
        else:
            return 'general', 0.5

    def _determine_processing_mode(self, file_path: str, doc_type: str, text_length: int) -> str:
        """Determine processing mode based on document characteristics."""
        filename = os.path.basename(file_path).lower()
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Check if matches allowlist patterns for pre-chunking
        allowlist_patterns = [
            r'nasa-std-\d+',
            r'nasa-hdbk-\d+',
            r'npr-\d+',
            r'msfc-std-\d+',
            r'msfc-spec-\d+'
        ]

        for pattern in allowlist_patterns:
            if re.search(pattern, filename):
                # Pre-chunk if small enough
                if file_size_mb <= getattr(CONFIG, 'prechunk_size_limit_mb', 50):
                    return 'pre_chunk'
                else:
                    return 'doc_level'

        # Size-based routing
        if file_size_mb > getattr(CONFIG, 'skip_if_mb_gt', 100):
            return 'metadata_only'
        elif file_size_mb > getattr(CONFIG, 'prechunk_size_limit_mb', 50):
            return 'doc_level'

        # Content-based routing
        if doc_type in ['nasa_standard', 'specification', 'policy']:
            return 'pre_chunk'
        else:
            return 'doc_level'

    def _analyze_content_structure(self, parsed_result: Dict) -> Dict[str, int]:
        """Analyze document content structure."""
        structure = {
            'sections': 0,
            'tables': 0,
            'figures': 0
        }

        try:
            # Count sections from parsed result
            if 'sections' in parsed_result:
                structure['sections'] = len(parsed_result['sections'])

            # Count tables and figures
            full_text = parsed_result.get('full_text', '')
            structure['tables'] = len(re.findall(r'\btable\s+\d+', full_text, re.IGNORECASE))
            structure['figures'] = len(re.findall(r'\bfigure\s+\d+', full_text, re.IGNORECASE))

        except Exception as e:
            logger.debug(f"Structure analysis error: {e}")

        return structure

    def _analyze_nasa_compliance(self, content: str) -> Dict[str, Any]:
        """Analyze NASA compliance indicators in document."""
        analysis = {
            'has_requirements': False,
            'requirement_count': 0,
            'has_verification': False,
            'tags': []
        }

        try:
            content_lower = content.lower()

            # Check for requirements
            req_count = 0
            for pattern in self.compliance_patterns['requirements']:
                matches = re.findall(pattern, content_lower)
                req_count += len(matches)

            if req_count > 0:
                analysis['has_requirements'] = True
                analysis['requirement_count'] = req_count
                analysis['tags'].append('SWE-033')  # Requirements traceability

            # Check for verification methods
            for pattern in self.compliance_patterns['verification']:
                if re.search(pattern, content_lower):
                    analysis['has_verification'] = True
                    analysis['tags'].append('SWE-013')  # Verification
                    break

            # Check for standards references
            for pattern in self.compliance_patterns['standards']:
                if re.search(pattern, content_lower):
                    analysis['tags'].append('standards_compliant')
                    break

        except Exception as e:
            logger.debug(f"Compliance analysis error: {e}")

        return analysis

    def track_document_access(self, doc_id: str, user_id: str = "anonymous",
                            query: str = None):
        """Track document access for promotion decisions."""
        current_time = time.time()

        # Update access tracking
        tracker = self.access_tracker[doc_id]
        tracker['count'] += 1
        tracker['users'].add(user_id)
        tracker['last_access'] = current_time

        # Update analysis result if exists
        if doc_id in self.analysis_results:
            result = self.analysis_results[doc_id]
            result.access_count = tracker['count']
            if user_id not in result.unique_users:
                result.unique_users.append(user_id)
            result.last_accessed = current_time

        # Check promotion eligibility
        if self._check_promotion_eligibility(doc_id):
            self.promotion_candidates.add(doc_id)

        logger.debug(f"Tracked access: {doc_id} by {user_id}")

    def _check_promotion_eligibility(self, doc_id: str) -> bool:
        """Check if document meets promotion criteria."""
        if doc_id not in self.access_tracker:
            return False

        tracker = self.access_tracker[doc_id]

        # Check thresholds
        enough_hits = tracker['count'] >= self.promotion_config['min_hits']
        enough_users = len(tracker['users']) >= self.promotion_config['min_users']

        # Check recency
        window_seconds = self.promotion_config['window_hours'] * 3600
        recent_access = (time.time() - tracker['last_access']) <= window_seconds

        return enough_hits and enough_users and recent_access

    def get_promotion_candidates(self) -> List[str]:
        """Get list of documents eligible for promotion."""
        # Refresh candidate list
        current_candidates = set()
        for doc_id in self.access_tracker:
            if self._check_promotion_eligibility(doc_id):
                current_candidates.add(doc_id)

        self.promotion_candidates = current_candidates
        return list(self.promotion_candidates)

    def get_document_analysis(self, doc_id: str) -> Optional[DocumentAnalysisResult]:
        """Get enhanced analysis result for a document."""
        return self.analysis_results.get(doc_id)

    def validate_content_hash(self, file_path: str, expected_hash: str) -> bool:
        """Validate that file content hasn't changed."""
        current_hash = self.compute_content_hash(file_path)
        return current_hash == expected_hash

    def get_processing_statistics(self) -> Dict[str, Any]:
        """Get comprehensive processing statistics."""
        total_docs = len(self.analysis_results)
        processing_modes = defaultdict(int)
        doc_types = defaultdict(int)

        for result in self.analysis_results.values():
            processing_modes[result.processing_mode] += 1
            doc_types[result.document_type] += 1

        return {
            'total_documents': total_docs,
            'processing_modes': dict(processing_modes),
            'document_types': dict(doc_types),
            'promotion_candidates': len(self.promotion_candidates),
            'access_tracking': {
                'tracked_documents': len(self.access_tracker),
                'total_accesses': sum(t['count'] for t in self.access_tracker.values()),
                'unique_users': len(set().union(*(t['users'] for t in self.access_tracker.values())))
            }
        }

    def export_analysis_results(self, output_path: str):
        """Export analysis results to JSON file."""
        try:
            export_data = {}
            for doc_id, result in self.analysis_results.items():
                export_data[doc_id] = asdict(result)

            with open(output_path, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)

            logger.info(f"Exported analysis results to {output_path}")

        except Exception as e:
            logger.error(f"Failed to export analysis results: {e}")

def main():
    """CLI for enhanced smart indexer."""
    parser = argparse.ArgumentParser(description="Enhanced Smart Indexer with Promotion Tracking")
    parser.add_argument("repository_path", help="Path to repository to analyze")
    parser.add_argument("--output", "-o", help="Output file for analysis results")
    parser.add_argument("--track-usage", action="store_true", help="Enable usage tracking")
    parser.add_argument("--promotion-stats", action="store_true", help="Show promotion statistics")
    parser.add_argument("--max-files", type=int, help="Maximum files to process")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        # Initialize enhanced indexer
        indexer = PromotionTrackingIndexer()

        # Process repository
        logger.info(f"Starting enhanced analysis of {args.repository_path}")

        processed_count = 0
        repo_path = Path(args.repository_path)

        for file_path in repo_path.rglob("*.*"):
            if args.max_files and processed_count >= args.max_files:
                break

            if file_path.is_file():
                try:
                    result = indexer.analyze_document_enhanced(str(file_path))
                    if result:
                        processed_count += 1

                        if processed_count % 100 == 0:
                            logger.info(f"Processed {processed_count} documents...")

                except Exception as e:
                    logger.debug(f"Skipped {file_path}: {e}")

        # Print statistics
        stats = indexer.get_processing_statistics()
        print("\n" + "="*60)
        print("ENHANCED INDEXER STATISTICS")
        print("="*60)
        print(f"Total documents processed: {stats['total_documents']}")
        print(f"Promotion candidates: {stats['promotion_candidates']}")

        print("\nProcessing modes:")
        for mode, count in stats['processing_modes'].items():
            print(f"  {mode}: {count}")

        print("\nDocument types:")
        for doc_type, count in stats['document_types'].items():
            print(f"  {doc_type}: {count}")

        if args.promotion_stats:
            candidates = indexer.get_promotion_candidates()
            print(f"\nPromotion candidates: {len(candidates)}")
            for doc_id in candidates[:10]:  # Show first 10
                analysis = indexer.get_document_analysis(doc_id)
                if analysis:
                    print(f"  {doc_id}: {analysis.document_type} ({analysis.access_count} accesses)")

        # Export results if requested
        if args.output:
            indexer.export_analysis_results(args.output)
            print(f"\nResults exported to: {args.output}")

    except Exception as e:
        logger.error(f"Enhanced indexer failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())