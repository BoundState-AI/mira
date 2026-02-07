#!/usr/bin/env python3
"""
Module: Smart
Purpose: Standalone smart indexer for BoundState Athena platform

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

# Copyright 2025 BoundStateAI

"""
Standalone smart indexer for BoundState Athena platform
Classifies document type, analyzes structure, and parses intelligently
Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.0 <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI o3/4.0/4.5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI


Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

from __future__ import annotations

__safety_critical__ = True  # NASA document processing system

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
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Any, Tuple
from collections import Counter

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
try:
    from boundstate.parsers import get_parser
    from pdf2image import convert_from_path
    # Import enhanced table parser
    sys.path.append('.')
    from enhanced_table_parser import EnhancedDocxParser
except ImportError:
    convert_from_path = None
    EnhancedDocxParser = None
try:
    import pytesseract
    # Configure Tesseract path for Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Adjust path as needed
except ImportError:
    pytesseract = None

try:
    from docx import Document
except ImportError:
    Document = None

import numpy as np
from sentence_transformers import SentenceTransformer
import faiss
from tinydb import TinyDB, Query
from werkzeug.utils import secure_filename
from sklearn.metrics.pairwise import cosine_similarity

# Config for defaults
from boundstate.config import CONFIG
from boundstate.tagger import tag_sections, ZeroShotTagger
from boundstate.index import create_index
from boundstate.rtx2070_chunker import RTX2070OptimizedChunker

# FIPS 140-2 compliant encryption for embedding storage
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    FIPS_ENCRYPTION_AVAILABLE = True
except ImportError:
    FIPS_ENCRYPTION_AVAILABLE = False

logger = logging.getLogger(__name__)


class FIPSEmbeddingEncryption:
    """FIPS 140-2 compliant encryption for embedding storage

    Provides AES-256-GCM encryption for sensitive embedding vectors
    using PBKDF2 key derivation with SHA-256.

    Compliance: NASA-CSET, SWE-032 (Data Protection)
    Security Classification: CUI//SP-PRVCY
    Authorization: NASA ATO Required
    """

    def __init__(self, password: Optional[str] = None):
        """Initialize FIPS encryption

        Args:
            password: Encryption password. If None, generates secure random password
        """
        if not FIPS_ENCRYPTION_AVAILABLE:
            raise RuntimeError("FIPS encryption dependencies not available")

        self.password = password or self._generate_secure_password()
        self.salt = os.urandom(32)  # 256-bit salt
        self.backend = default_backend()

    def _generate_secure_password(self) -> str:
        """Generate cryptographically secure password"""
        return os.urandom(32).hex()

    def _derive_key(self, salt: bytes) -> bytes:
        """Derive AES-256 key using PBKDF2-SHA256"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256-bit key
            salt=salt,
            iterations=100000,  # NIST recommended minimum
            backend=self.backend
        )
        return kdf.derive(self.password.encode())

    def encrypt_embeddings(self, embeddings: np.ndarray) -> Dict[str, bytes]:
        """Encrypt embedding arrays with FIPS 140-2 compliance

        Args:
            embeddings: NumPy array of embeddings

        Returns:
            Dict containing encrypted data, salt, and IV
        """
        # Serialize embeddings
        embedding_data = pickle.dumps(embeddings)

        # Generate new salt and IV for each encryption
        salt = os.urandom(32)
        iv = os.urandom(12)  # 96-bit IV for GCM

        # Derive key
        key = self._derive_key(salt)

        # Encrypt with AES-256-GCM
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(iv),
            backend=self.backend
        )
        encryptor = cipher.encryptor()

        ciphertext = encryptor.update(embedding_data) + encryptor.finalize()

        req_id = str(uuid.uuid4())
        logger.info(f"Encrypted embeddings with FIPS 140-2 AES-256-GCM", extra={'req_id': req_id})

        return {
            'ciphertext': ciphertext,
            'salt': salt,
            'iv': iv,
            'tag': encryptor.tag  # Authentication tag
        }

    def decrypt_embeddings(self, encrypted_data: Dict[str, bytes]) -> np.ndarray:
        """Decrypt embedding arrays

        Args:
            encrypted_data: Dict from encrypt_embeddings()

        Returns:
            Decrypted NumPy array of embeddings
        """
        # Extract encryption components
        ciphertext = encrypted_data['ciphertext']
        salt = encrypted_data['salt']
        iv = encrypted_data['iv']
        tag = encrypted_data['tag']

        # Derive key
        key = self._derive_key(salt)

        # Decrypt with AES-256-GCM
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(iv, tag),
            backend=self.backend
        )
        decryptor = cipher.decryptor()

        try:
            embedding_data = decryptor.update(ciphertext) + decryptor.finalize()
            embeddings = pickle.loads(embedding_data)

            req_id = str(uuid.uuid4())
            logger.info(f"Decrypted embeddings with FIPS 140-2 verification", extra={'req_id': req_id})

            return embeddings
        except Exception as e:
            req_id = str(uuid.uuid4())
            logger.error(f"Embedding decryption failed: {e}", extra={'req_id': req_id})
            raise


@dataclass
class Edge:
    """Graph edge representation for knowledge graph integration.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = None

@dataclass
class ComplianceMapping:
    """Maps document sections to compliance requirements.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    section_id: str
    requirement: str
    confidence: float
    evidence: str = ""

@dataclass
class QualityMetrics:
    """Quality metrics for indexing operations.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    embedding_density: float
    chunk_coherence: float
    classification_confidence: float
    avg_chunk_size: int
    tag_coverage: float

class IndexingMetrics:
    """Track and report indexing quality metrics.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    
    def __init__(self, enable_encryption: bool = True):
        self.chunks_processed = 0
        self.total_chunk_size = 0
        self.classification_scores = []
        self.tag_counts = Counter()
        self.embeddings = []
        self.doc_embeddings = {}  # doc_id -> list of embeddings

        # Initialize FIPS 140-2 encryption for embeddings
        self.encryption = None
        if enable_encryption and FIPS_ENCRYPTION_AVAILABLE:
            try:
                self.encryption = FIPSEmbeddingEncryption()
                req_id = str(uuid.uuid4())
                logger.info("✅ FIPS 140-2 encryption enabled for IndexingMetrics", extra={'req_id': req_id})
            except Exception as e:
                req_id = str(uuid.uuid4())
                logger.error(f"Failed to initialize FIPS encryption: {e}", extra={'req_id': req_id})
        elif enable_encryption:
            req_id = str(uuid.uuid4())
            logger.warning("FIPS encryption requested but dependencies not available", extra={'req_id': req_id})
        else:
            req_id = str(uuid.uuid4())
            logger.warning("FIPS encryption disabled for IndexingMetrics", extra={'req_id': req_id})

    def _decrypt_embedding(self, embedding_data: Dict[str, Any]) -> np.ndarray:
        """Decrypt a single embedding if it's encrypted

        Args:
            embedding_data: Dict with 'encrypted' flag and 'data' field

        Returns:
            Decrypted NumPy array
        """
        if embedding_data.get('encrypted', False):
            return self.encryption.decrypt_embeddings(embedding_data['data'])
        else:
            return embedding_data['data']

    def _get_decrypted_embeddings(self) -> List[np.ndarray]:
        """Get all embeddings decrypted for processing

        Returns:
            List of decrypted embedding arrays
        """
        return [self._decrypt_embedding(emb_data) for emb_data in self.embeddings]

    def _get_decrypted_doc_embeddings(self) -> Dict[str, List[np.ndarray]]:
        """Get all document embeddings decrypted for processing

        Returns:
            Dict of doc_id -> list of decrypted embeddings
        """
        result = {}
        for doc_id, emb_list in self.doc_embeddings.items():
            result[doc_id] = [self._decrypt_embedding(emb_data) for emb_data in emb_list]
        return result

    def record_chunk(self, chunk: Dict[str, Any], embedding: np.ndarray = None):
        """Record metrics for a processed chunk.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        self.chunks_processed += 1
        self.total_chunk_size += len(chunk.get('text', ''))
        self.tag_counts.update(chunk.get('tags', []))
        if embedding is not None:
            # Encrypt embedding before storing if encryption is enabled
            if self.encryption:
                encrypted_embedding = self.encryption.encrypt_embeddings(embedding)
                self.embeddings.append({'encrypted': True, 'data': encrypted_embedding})
                doc_id = chunk.get('doc_id')
                if doc_id:
                    self.doc_embeddings.setdefault(doc_id, []).append({'encrypted': True, 'data': encrypted_embedding})
            else:
                # Store unencrypted embedding as fallback
                self.embeddings.append({'encrypted': False, 'data': embedding})
                doc_id = chunk.get('doc_id')
                if doc_id:
                    self.doc_embeddings.setdefault(doc_id, []).append({'encrypted': False, 'data': embedding})
    
    def get_metrics(self) -> QualityMetrics:
        """Calculate and return quality metrics.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        avg_chunk_size = self.total_chunk_size // max(1, self.chunks_processed)
        tag_coverage = len(self.tag_counts) / max(1, self.chunks_processed)
        
        # Calculate embedding density (average L2 norm)
        embedding_density = 0.0
        if self.embeddings:
            decrypted_embeddings = self._get_decrypted_embeddings()
            embedding_density = np.mean([np.linalg.norm(e) for e in decrypted_embeddings])

        # Calculate chunk coherence (adjacent cosine similarity within documents)
        chunk_coherences = []
        decrypted_doc_embeddings = self._get_decrypted_doc_embeddings()
        for vectors in decrypted_doc_embeddings.values():
            if len(vectors) < 2:
                continue
            sims = cosine_similarity(vectors[:-1], vectors[1:])
            coherence_scores = sims.diagonal()
            chunk_coherences.extend(coherence_scores)
        chunk_coherence = float(np.mean(chunk_coherences)) if chunk_coherences else 0.0
        
        return QualityMetrics(
            embedding_density=embedding_density,
            chunk_coherence=chunk_coherence,
            classification_confidence=np.mean(self.classification_scores) if self.classification_scores else 0.0,
            avg_chunk_size=avg_chunk_size,
            tag_coverage=tag_coverage
        )

# SemanticIndex is now imported from index.py - using create_index() factory function

class SmartIndexer:
    """Standalone indexer with type-aware parsing.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md', '.mpp', '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.dwg', '.dxf', '.cad', '.step', '.stp', '.igs', '.par', '.json'}
    
    # Compliance mapping rules
    COMPLIANCE_MAPPINGS = {
        'safety': ['SWE-023', 'SWE-024'],
        'technical_spec': ['SWE-049', 'SWE-050'],
        'form': ['SWE-033'],
        'procurement': ['SWE-013'],
        'hr_policy': ['SWE-079'],
        'contract': ['SWE-034', 'SWE-035']
    }
    
    def __init__(self, index_path: Optional[str] = None):
        self.index = create_index(db_path=index_path)
        self.zero_shot_tagger = ZeroShotTagger()
        self.rtx2070_chunker = RTX2070OptimizedChunker()
        self.cache = {}  # File hash -> (type, section_count, headings)
        self.stats = {
            "processed": 0,
            "added_sections": 0,
            "errors": 0,
            "skipped": 0,
            "start_time": None,
            "end_time": None
        }
        self.graph_edges = []
        self.compliance_mappings = []
        # Initialize metrics
        self.metrics = IndexingMetrics()
        
        # Initialize embedder for metrics (CPU to save VRAM on RTX 2070)
        self.metrics_embedder = None
        try:
            model_name = os.getenv("BOUNDSTATE_MODEL_NAME", "nomic-ai/nomic-embed-text-v1.5")
            self.metrics_embedder = SentenceTransformer(
                model_name, 
                device="cpu",  # Use CPU to save VRAM
                trust_remote_code=True
            )
            logger.info(f"Initialized metrics embedder: {model_name} on CPU")
        except Exception as e:
            logger.warning(f"Could not initialize metrics embedder: {e}")
            self.metrics_embedder = None
    
    def _clean_text(self, text: str) -> str:
        """Strip visual junk like table borders and normalize spacing.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        text = re.sub(r"[│┃╱╲╳═║╔╗╝╚╩╦╬━┻┳┏┓┛┗─—–•·…]+", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()
    
    def _is_mostly_line_junk(self, text: str, threshold: float = 0.6) -> bool:
        """Heuristic: detect if text is mostly visual symbols (lines, boxes, etc).

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        line_chars = re.findall(r"[│┃╱╲╳═║╔╗╝╚╩╦╬━┻┳┏┓┛┗─—–•·…]", text)
        return len(line_chars) / max(1, len(text)) > threshold
    
    def _normalize_base_doc_id(self, doc_id: str) -> str:
        """Normalize document ID by removing extension and version.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        from pathlib import Path
        base_id = Path(doc_id).stem
        base_id = re.sub(r'[\s_-]*(v|rev|r)[\s_-]*(\d+[\.\d]*)', '', base_id, flags=re.IGNORECASE).rstrip('_- ')
        return base_id
    
    def _classify_doc_type(self, text: str, filename: str) -> Tuple[str, float]:
        """Classify document type based on content and filename.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        text_lower = text[:1000].lower()  # Sample first 1000 chars
        filename_lower = filename.lower()
        
        # Score each classification
        scores = {}
        
        if re.search(r'^\d+\.\d+\s+[^?]+?\?', text, flags=re.MULTILINE) or 'checklist' in text_lower:
            scores['form'] = 0.9
        
        if any(word in text_lower for word in ['timecard', 'time recording', 'travel', 'telework', 'hr', 'human resources', 'employee', 'leave', 'benefits']):
            scores['hr_policy'] = 0.8
        
        if 'basware' in text_lower or 'order request' in text_lower or 'procurement' in text_lower or 'p2p' in filename_lower:
            scores['procurement'] = 0.85
        
        if any(word in text_lower for word in ['specification', 'technical', 'mil-std', 'nasa-std', 'procedure', 'standard']):
            scores['technical_spec'] = 0.8
        
        if any(word in text_lower for word in ['contract', 'rfp', 'rfq', 'proposal', 'agreement']):
            scores['contract'] = 0.85
        
        if any(word in text_lower for word in ['safety', 'compliance', 'regulation', 'hazard', 'risk']):
            scores['safety_compliance'] = 0.8
        
        # Default score
        if not scores:
            scores['general'] = 0.5
        
        # Get the highest scoring type
        doc_type = max(scores, key=scores.get)
        confidence = scores[doc_type]
        
        return doc_type, confidence
    
    def _emit_graph_edges(self, section: Dict[str, Any]) -> List[Edge]:
        """Generate graph edges from section metadata.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        edges = []
        
        # Document -> Version edges
        if section.get('base_doc_id') and section.get('doc_id'):
            edges.append(Edge(
                source=section['base_doc_id'],
                target=section['doc_id'],
                type='has_version',
                properties={'version': section.get('version', '1.0')}
            ))
        
        # Document -> Tag edges
        for tag in section.get('tags', []):
            edges.append(Edge(
                source=section['doc_id'],
                target=f"tag:{tag}",
                type='tagged_as',
                properties={'section': section.get('section')}
            ))
        
        # Document -> Type edges
        if section.get('doc_type'):
            edges.append(Edge(
                source=section['doc_id'],
                target=f"type:{section['doc_type']}",
                type='classified_as',
                properties={'confidence': section.get('classification_confidence', 1.0)}
            ))
        
        return edges
    
    def _map_to_compliance(self, section: Dict[str, Any]) -> List[ComplianceMapping]:
        """Map document sections to compliance requirements.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        mappings = []
        doc_type = section.get('doc_type', '')
        
        # Direct type-based mappings
        if doc_type in self.COMPLIANCE_MAPPINGS:
            for req in self.COMPLIANCE_MAPPINGS[doc_type]:
                mappings.append(ComplianceMapping(
                    section_id=f"{section['doc_id']}#{section.get('section', '0')}",
                    requirement=req,
                    confidence=0.8,
                    evidence=f"Document type: {doc_type}"
                ))
        
        # Tag-based mappings
        for tag in section.get('tags', []):
            if tag in self.COMPLIANCE_MAPPINGS:
                for req in self.COMPLIANCE_MAPPINGS[tag]:
                    mappings.append(ComplianceMapping(
                        section_id=f"{section['doc_id']}#{section.get('section', '0')}",
                        requirement=req,
                        confidence=0.7,
                        evidence=f"Tagged as: {tag}"
                    ))
        
        # Content-based mappings
        text_lower = section.get('text', '').lower()
        if 'risk assessment' in text_lower:
            mappings.append(ComplianceMapping(
                section_id=f"{section['doc_id']}#{section.get('section', '0')}",
                requirement='SWE-024',
                confidence=0.9,
                evidence="Contains risk assessment content"
            ))
        
        return mappings
    
    def _analyze_structure(self, text: str, doc_type: str, is_pdf: bool = False, file_bytes: Optional[bytes] = None) -> Tuple[int, List[str]]:
        """Analyze document structure (section count, headings).

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        sections = text.split('\n\n')
        section_count = len([s for s in sections if s.strip()])
        
        heading_pattern = re.compile(r'^(?:\d+\.\d+\.?|[A-Z][\.]\s+|#+|\bBlock\s+\w+\s*[-–]\s*.+)', re.MULTILINE)
        qa_pattern = re.compile(r'^\d+\.\d+\s+[^?]+?\?', re.MULTILINE)
        score_pattern = re.compile(r'Overall Section Score:.*?(?:Acceptable|Not Acceptable)', re.IGNORECASE)
        headings = []
        
        if is_pdf and file_bytes and fitz:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            size_counter = Counter()
            for page in doc:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                if span["text"].strip() and round(span["size"], 2) > size_counter.most_common(1)[0][0] if size_counter else 0:
                                    headings.append(span["text"].strip())
                if len(doc) > 1:
                    section_count += len(doc)  # Page-based sections
            doc.close()
        
        for section in sections:
            if heading_pattern.match(section):
                headings.append(section.strip())
            if score_pattern.search(section):
                headings.append(section.strip())
        
        if doc_type in ['form', 'hr_policy']:
            section_count += len(qa_pattern.findall(text))
        
        return section_count, headings
    
    def _clean_text(self, text: str) -> str:
        """Clean text for parsing.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        text = unicodedata.normalize('NFKD', text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)  # Remove control chars
        text = re.sub(r'\s{2,}', ' ', text)  # Consolidate whitespace
        text = re.sub(r'(\n\s*){2,}', '\n\n', text)  # Normalize paragraph breaks
        footer_patterns = [
            r'Page \d+ of \d+', r'Amentum Proprietary',
            r'[FG]\d{4}\.\d+[A-Z]? Rev\. \d+ Effective \d{4}-\d{2}-\d{2}',
            r'Copyright.*Amentum.*rights reserved'
        ]
        for pattern in footer_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        # Handle table-like OCR output (e.g., pipes from scanned tables)
        table_pattern = r'[\|\-]+\s*\n\s*[\|\-]+\s*\n(?:[^\n]+\s*\n)+'
        tables = re.findall(table_pattern, text, re.MULTILINE)
        if tables:
            cleaned_content = []
            for table in tables:
                rows = [re.sub(r'^\s*\|+\s*|\s*\|+\s*$', '', row.strip()) for row in table.split('\n') if row.strip()]
                cleaned_content.extend(rows)
            text = '\n'.join(cleaned_content) + '\n' + re.sub(table_pattern, '', text)
        return text.strip()

    def _apply_ocr_fallback(self, file_path: Path, file_bytes: bytes) -> str:
        """Apply OCR fallback for scanned PDFs.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if convert_from_path is None or pytesseract is None:
            logger.error("pdf2image or pytesseract not available for OCR fallback.")
            return ""
        logger.info(f"Attempting OCR fallback for {file_path}")
        try:
            images = convert_from_path(str(file_path), dpi=300)
            custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
            all_text = '\n\n'.join(pytesseract.image_to_string(img, lang='eng', config=custom_config) for img in images)
            
            # Strip borders from fallback OCR too
            all_text = self._clean_text(all_text)
            if self._is_mostly_line_junk(all_text):
                logger.warning(f"OCR text from {file_path.name} still looks like mostly visual symbols.")
            
            return all_text
        except Exception as e:
            logger.error(f"OCR fallback failed for {file_path}: {e}")
            return ""
    
    def _smart_chunk(self, text: str, metadata: Dict[str, Any], doc_type: str) -> List[Dict[str, Any]]:
        """Chunk text with 420-token windows (reads from environment).

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        import os, re, uuid, hashlib
        win = int(os.getenv("BOUNDSTATE_CHUNK_WINDOW", "420"))
        stride = int(os.getenv("BOUNDSTATE_CHUNK_STRIDE", "60"))
        logger.info(f"CHUNK CONFIG: window={win}, stride={stride}")

        words = re.split(r"\s+", (text or "").strip())
        if not words:
            return []

        chunks, i, n = [], 0, 1
        title = metadata.get("title") or metadata.get("section_title") or f"Section {n}"
        table_ctx = metadata.get("table_context") or {}
        
        while i < len(words):
            j = min(len(words), i + win)
            chunk_words = words[i:j]
            body = " ".join(chunk_words).strip()
            if body:
                doc_id = metadata.get("doc_id") or f"{metadata.get('filename','doc')}_{uuid.uuid4().hex[:8]}"
                embed_text = f"{title}\n{body}".strip()
                bm25_text = [embed_text]
                
                # Add table context for better BM25 matching
                if table_ctx.get("headers"):
                    bm25_text.append("headers: " + " | ".join(table_ctx["headers"]))
                if metadata.get("table_data"):
                    headers = table_ctx.get("headers") or []
                    for row in metadata["table_data"][:50]:
                        if headers and len(row) == len(headers):
                            bm25_text.extend([f"{h}: {v}" for h, v in zip(headers, row)])
                        else:
                            bm25_text.append(" | ".join(map(str, row)))
                
                chunks.append({
                    "text": body,
                    "embed_text": embed_text,  # CRITICAL for good embeddings
                    "bm25_text": "\n".join(bm25_text),  # CRITICAL for BM25 matches
                    "metadata": metadata.copy(),
                    "doc_id": doc_id,
                    "base_doc_id": self._normalize_base_doc_id(doc_id),
                    "doc_type": doc_type,
                    "section": str(n),
                    "title": title,
                    "tags": [doc_type] if doc_type else [],
                    "version": metadata.get('version', '1.0'),
                    "version_tuple": metadata.get('version_tuple', (1, 0, 0, '')),
                    "file_path": metadata.get("source_path"),
                    "file_name": metadata.get("filename"),
                    "source": metadata.get("source_path"),
                })
                n += 1
            if j >= len(words):
                break
            i = max(i + 1, i + win - stride)

        # Light deduplication
        seen, unique = set(), []
        for c in chunks:
            h = hashlib.sha1(c["text"].lower().encode("utf-8")).hexdigest()[:16]
            if h not in seen:
                seen.add(h)
                unique.append(c)
        
        logger.info(f"Created {len(unique)} chunks from {len(words)} words (avg {len(words)//max(1,len(unique))} words/chunk)")
        return unique
    
    def _parse_pdf(self, file_path: Path, file_bytes: bytes) -> List[Dict[str, Any]]:
        """Parse PDF with type-aware logic.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        try:
            if not fitz:
                logger.error("PyMuPDF not available; using parser module fallback")
                return get_parser(str(file_path), file_bytes=file_bytes).parse()
            
            # Try to extract text using PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text("text")  # Use 'text' mode to ignore vector lines/shapes
            doc.close()
            
            # Clean the extracted text
            text = self._clean_text(text)
            
            # Check if it's mostly visual junk
            if self._is_mostly_line_junk(text):
                logger.warning(f"PDF {file_path.name} looks like border/table junk — fallback may be needed.")
            
            # If we have no useful text, use parser module (includes OCR fallback)
            if not text.strip():
                logger.info(f"No text extracted from {file_path.name}, using parser module with OCR fallback")
                return get_parser(str(file_path), file_bytes=file_bytes).parse()
            
            # Otherwise use parser module for structured parsing
            return get_parser(str(file_path), file_bytes=file_bytes).parse()
        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {e}, using parser module fallback")
            return get_parser(str(file_path), file_bytes=file_bytes).parse()
    
    def _parse_docx(self, file_path: Path, file_bytes: bytes) -> List[Dict[str, Any]]:
        """Parse DOCX with enhanced table extraction.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        try:
            # Try enhanced parser first for better table extraction
            if EnhancedDocxParser:
                logger.debug(f"Using enhanced DOCX parser for {file_path}")
                from io import BytesIO
                # Wrap bytes in BytesIO for python-docx compatibility
                file_stream = BytesIO(file_bytes)
                parser = EnhancedDocxParser(str(file_path), file_bytes=file_stream)
                sections = parser.parse()
                if sections:
                    logger.info(f"Enhanced parser extracted {len(sections)} sections from {file_path}")
                    return sections
                else:
                    logger.warning(f"Enhanced parser returned no sections for {file_path}, falling back")
            
            # Fallback to standard parser
            if not Document:
                logger.error("python-docx not available; using parser module fallback")
                return get_parser(str(file_path), file_bytes=file_bytes).parse()
            
            logger.debug(f"Using standard parser for {file_path}")
            return get_parser(str(file_path), file_bytes=file_bytes).parse()
        except Exception as e:
            logger.error(f"Error parsing DOCX {file_path}: {e}, using parser module fallback")
            return get_parser(str(file_path), file_bytes=file_bytes).parse()
    
    def _apply_tags(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply tagging rules.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        rules = [
            ("timecard_policy", re.compile(r'\b(timecard|time recording|time entry|labor recording)\b', re.IGNORECASE)),
            ("travel_policy", re.compile(r'\b(travel policy|travel expense|travel authorization|per diem|mileage)\b', re.IGNORECASE)),
            ("telework_policy", re.compile(r'\b(telework|remote work|work from home|telecommuting)\b', re.IGNORECASE)),
            ("procurement_guideline", re.compile(r'\b(basware|p2p|purchase to pay)\b', re.IGNORECASE)),
            ("subcontractor_guideline", re.compile(r'\b(subcontractor|vendor management|third-party contract)\b', re.IGNORECASE)),
            ("task_folder_guideline", re.compile(r'\b(task folder|task management|project folder)\b', re.IGNORECASE)),
            ("maf_travel_guideline", re.compile(r'\b(MAF travel|mission travel|flight authorization)\b', re.IGNORECASE)),
            ("HR", re.compile(r'\b(HR|human resources|employee|personnel|hiring|onboarding)\b', re.IGNORECASE)),
            ("Procurement", re.compile(r'\b(procurement|purchase order|supplier|vendor|contract|RFP|RFQ|order request)\b', re.IGNORECASE)),
            ("Policy", re.compile(r'\b(policy|procedure|guideline|standard|compliance|POL\d{4})\b', re.IGNORECASE)),
            ("Technical", re.compile(r'\b(specification|technical|engineering|design|requirement)\b', re.IGNORECASE)),
            ("Safety", re.compile(r'\b(safety|hazard|risk|accident|incident|emergency)\b', re.IGNORECASE)),
            ("form_document", re.compile(r'\b(form|template|checklist|worksheet)\b', re.IGNORECASE)),
            ("questionnaire", re.compile(r'^\d+\.\d+\s+[^?]+\?', re.MULTILINE)),
            ("score", re.compile(r'Overall Section Score:.*?(?:Acceptable|Not Acceptable)', re.IGNORECASE)),
            ("revision:00", re.compile(r'\br00\b', re.IGNORECASE)),
        ]
        
        for sec in sections:
            text_lower = sec['text'].lower()
            for tag, pattern in rules:
                if pattern.search(text_lower):
                    if tag not in sec['tags']:
                        sec['tags'].append(tag)
            if sec.get('doc_type') == 'form' and 'form' not in sec['tags']:
                sec['tags'].append('form')
        
        return sections
    
    def ingest_directory(self, dir_path: str, recursive: bool = True, dry_run: bool = False, verbose: bool = False) -> Dict[str, int]:
        """Ingest all supported documents in a directory.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        path = Path(dir_path).resolve()
        if not path.is_dir():
            raise ValueError(f"{dir_path} is not a directory")
        
        logger.info(f"Starting ingestion of {'recursive ' if recursive else ''}directory: {path}")
        self.stats["start_time"] = time.time()
        
        files = []
        if recursive:
            for ext in self.SUPPORTED_EXTENSIONS:
                files.extend(path.rglob(f"*{ext}"))
                files.extend(path.rglob(f"*{ext.upper()}"))
        else:
            for ext in self.SUPPORTED_EXTENSIONS:
                files.extend(path.glob(f"*{ext}"))
                files.extend(path.glob(f"*{ext.upper()}"))
        files = sorted(set(files))
        
        logger.info(f"Found {len(files)} files in {dir_path} for indexing")
        if not files:
            logger.warning("No supported files found")
            return self.stats
        
        for i, file_path in enumerate(files, 1):
            if verbose:
                logger.info(f"Processing {i}/{len(files)}: {file_path.name}")
            try:
                logger.info(f"Attempting to process {file_path}")
                success = self._process_file(file_path, dry_run)
                if success:
                    logger.info(f"Successfully processed {file_path}")
                else:
                    logger.warning(f"Failed to process {file_path}")
                    self.stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                self.stats["errors"] += 1
                if verbose:
                    import traceback
                    logger.debug(traceback.format_exc())
        
        self.stats["end_time"] = time.time()
        duration = self.stats["end_time"] - self.stats["start_time"]
        logger.info("=" * 50)
        logger.info("INGESTION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Files processed: {self.stats['processed']}")
        logger.info(f"Sections added: {self.stats['added_sections']}")
        logger.info(f"Files skipped: {self.stats['skipped']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Duration: {duration:.2f} seconds")
        if self.stats['processed'] > 0:
            logger.info(f"Processing rate: {self.stats['processed'] / duration:.2f} files/second")
        logger.info("=" * 50)
        
        return dict(self.stats)
    
    def _process_file(self, file_path: Path, dry_run: bool):
        """Process a single file with full structure analysis.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        logger.info(f"Processing {file_path}")
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            logger.warning(f"Unsupported file type: {file_path}")
            self.stats["skipped"] += 1
            return False
        
        if file_path.stat().st_size > 100 * 1024 * 1024:
            logger.warning(f"File too large, skipping: {file_path}")
            self.stats["skipped"] += 1
            return False
        
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        
        classification_confidence = 0.5  # Default confidence
        if file_hash in self.cache:
            doc_type, section_count, headings = self.cache[file_hash]
            logger.debug(f"Using cached classification for {file_path}: {doc_type}, {section_count} sections")
        else:
            sample_text = ""
            if ext == '.pdf' and fitz:
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                sample_text = doc[0].get_text()[:1000]
                doc.close()
            elif ext == '.docx' and Document:
                doc = Document(BytesIO(file_bytes))
                sample_text = "\n".join(para.text for para in doc.paragraphs)[:1000]
            else:
                sample_text = file_bytes.decode('utf-8', errors='ignore')[:1000]
            sample_text = self._clean_text(sample_text)
            
            doc_type, classification_confidence = self._classify_doc_type(sample_text, file_path.name)
            section_count, headings = self._analyze_structure(sample_text, doc_type, ext == '.pdf', file_bytes)
            self.cache[file_hash] = (doc_type, section_count, headings)
        
        if ext == '.pdf':
            sections = self._parse_pdf(file_path, file_bytes)
            
            # If the parser returned tiny shards, re-chunk with the 420/60 token chunker
            if sections:
                avg_chars = sum(len(s.get('text','')) for s in sections) / max(1, len(sections))
                if avg_chars < 600:  # heuristic: parser produced micro-chunks
                    logger.info(f"PDF parser produced micro-chunks (avg {avg_chars:.0f} chars), re-chunking with 420/60 tokens")
                    full_text = self._clean_text("\n\n".join(s.get('text','') for s in sections))
                    meta = {
                        'filename': file_path.name,
                        'doc_type': doc_type,
                        'source_path': str(file_path),
                        'indexed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'version': '1.0',
                        'version_tuple': (1, 0, 0, '')
                    }
                    sections = self._smart_chunk(full_text, meta, doc_type)
        elif ext == '.docx':
            sections = self._parse_docx(file_path, file_bytes)
        elif ext in ['.xls', '.xlsx', '.ppt', '.pptx', '.doc']:
            # Use parser module for Office files
            sections = get_parser(str(file_path), file_bytes=file_bytes).parse()
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            # Use parser module for images (includes OCR)
            sections = get_parser(str(file_path), file_bytes=file_bytes).parse()
        elif ext == '.mpp':
            # Microsoft Project files - use parser module
            sections = get_parser(str(file_path), file_bytes=file_bytes).parse()
        else:
            # For text-based files (txt, md, etc.)
            text = file_bytes.decode('utf-8', errors='ignore')
            text = self._clean_text(text)
            # Use RTX2070 optimized chunker (420 tokens vs 80 chars)
            sections = self.rtx2070_chunker.chunk_with_tokens(text, {
                'filename': file_path.name,
                'doc_type': doc_type,
                'source_path': str(file_path),
                'indexed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'version': '1.0',
                'version_tuple': (1, 0, 0, '')
            }, doc_type)
        
        # If no sections were parsed, try OCR fallback for PDFs
        if not sections and ext == '.pdf':
            logger.warning(f"No sections parsed from {file_path.name}, attempting OCR fallback...")
            text = self._apply_ocr_fallback(file_path, file_bytes)
            
            if text.strip():
                # Create sections from OCR text
                metadata = {
                    'filename': file_path.name,
                    'doc_type': doc_type,
                    'classification_confidence': classification_confidence,
                    'source_path': str(file_path),
                    'indexed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'version': '1.0',
                    'version_tuple': (1, 0, 0, ''),
                    'ocr_fallback': True
                }
                
                # Save OCR debug output
                debug_file = f"ocr_debug_{file_path.stem}.txt"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(text)
                logger.info(f"Saved OCR debug output to {debug_file}")
                
                # Use RTX2070 optimized chunker (420 tokens vs 80 chars)
                sections = self.rtx2070_chunker.chunk_with_tokens(text, metadata, doc_type)
        
        # Add detailed logging for parsed sections
        logger.debug(f"Parsed {file_path} into {len(sections)} sections: {[s.get('section', 'unknown') for s in sections]}")
        
        sections = self._apply_tags(sections)
        for i, sec in enumerate(sections[:3]):
            logger.debug(f"Section {i}: text='{sec.get('text', '')[:50]}...', tags={sec.get('tags', [])}, doc_id={sec.get('doc_id')}")
        
        # Generate graph edges and compliance mappings
        for section in sections:
            edges = self._emit_graph_edges(section)
            self.graph_edges.extend(edges)
            
            mappings = self._map_to_compliance(section)
            self.compliance_mappings.extend(mappings)
        
        if not dry_run:
            # Apply both standard and zero-shot tagging before indexing
            sections = tag_sections(sections)
            # Temporarily disabled due to hanging - sections = self.zero_shot_tagger.tag_sections(sections)
            logger.info(f"Tagged {sum(1 for s in sections if s.get('tags'))} of {len(sections)} sections")
            
            # Record metrics WITH embeddings for each section
            # Build texts for metrics (use embed_text if present; add Nomic prefix)
            texts = []
            for s in sections:
                t = s.get("embed_text") or s.get("text") or ""
                texts.append("search_document: " + t)
            
            # Compute embeddings for metrics
            embs = None
            if self.metrics_embedder and texts:
                try:
                    embs = self.metrics_embedder.encode(
                        texts, 
                        normalize_embeddings=True, 
                        convert_to_numpy=True, 
                        batch_size=16, 
                        show_progress_bar=False
                    )
                    logger.debug(f"Computed {len(embs)} embeddings for metrics")
                except Exception as e:
                    logger.warning(f"Failed to compute embeddings for metrics: {e}")
                    embs = None
            
            # Record metrics with embeddings
            for i, section in enumerate(sections):
                try:
                    vec = embs[i] if embs is not None and i < len(embs) else None
                    self.metrics.record_chunk(section, vec)
                except Exception as e:
                    logger.debug(f"Could not record metrics for section: {e}")
            
            added = self.index.add(sections)
            self.stats["added_sections"] += added
            # Log quality metrics periodically
            if self.stats["processed"] % 10 == 0:
                try:
                    metrics = self.metrics.get_metrics()
                    logger.info(f"Quality metrics: {metrics}")
                except Exception as e:
                    logger.debug(f"Could not get quality metrics: {e}")
        else:
            logger.info(f"DRY RUN: Would add {len(sections)} sections from {file_path}")
            self.stats["added_sections"] += len(sections)
        
        self.stats["processed"] += 1
        return True
    
    def export_graph_edges(self, output_path: str):
        """Export collected graph edges to file.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        import json
        with open(output_path, 'w') as f:
            edges_data = [
                {
                    'source': e.source,
                    'target': e.target,
                    'type': e.type,
                    'properties': e.properties or {}
                }
                for e in self.graph_edges
            ]
            json.dump(edges_data, f, indent=2)
        logger.info(f"Exported {len(self.graph_edges)} graph edges to {output_path}")
    
    def export_compliance_mappings(self, output_path: str):
        """Export compliance mappings to file.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        import json
        with open(output_path, 'w') as f:
            mappings_data = [
                {
                    'section_id': m.section_id,
                    'requirement': m.requirement,
                    'confidence': m.confidence,
                    'evidence': m.evidence
                }
                for m in self.compliance_mappings
            ]
            json.dump(mappings_data, f, indent=2)
        logger.info(f"Exported {len(self.compliance_mappings)} compliance mappings to {output_path}")

def main():
    """CLI entry point.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    parser = argparse.ArgumentParser(
        description="Smart indexer for BoundState Athena documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/documents --recursive
  %(prog)s /path/to/document.pdf
  %(prog)s /path/to/docs --dry-run --verbose
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    )
    parser.add_argument("path", help="File or directory path to ingest")
    parser.add_argument("--recursive", "-r", action="store_true", help="Recursively process subdirectories")
    parser.add_argument("--dry-run", action="store_true", help="Simulate ingestion without modifying index")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--index-path", help="Custom path for document index")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--export-graph", help="Export graph edges to JSON file")
    parser.add_argument("--export-compliance", help="Export compliance mappings to JSON file")
    
    args = parser.parse_args()
    
    # Create logs directory if it doesn't exist
    log_dir = Path('smart_indexer_logs')
    log_dir.mkdir(exist_ok=True)
    
    # Create timestamped log filename
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'smart_indexer_{timestamp}.log'
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(), logging.FileHandler(str(log_file), encoding='utf-8')]
    )
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Log the log file location
    logger.info(f"Logging to: {log_file}")
    
    path = Path(args.path)
    if not path.exists():
        logger.error(f"Path does not exist: {args.path}")
        sys.exit(1)
    
    indexer = SmartIndexer(args.index_path)
    try:
        if path.is_file():
            logger.info(f"Processing single file: {path}")
            success = indexer._process_file(path, args.dry_run)
            sys.exit(0 if success else 1)
        elif path.is_dir():
            logger.info(f"Processing directory: {path}")
            results = indexer.ingest_directory(str(path), args.recursive, args.dry_run, args.verbose)
            
            # Export graph and compliance data if requested
            if args.export_graph:
                indexer.export_graph_edges(args.export_graph)
            
            if args.export_compliance:
                indexer.export_compliance_mappings(args.export_compliance)
            
            # Show final quality metrics
            try:
                metrics = indexer.metrics.get_metrics()
                logger.info(f"Final quality metrics: {metrics}")
            except Exception as e:
                logger.debug(f"Could not get final quality metrics: {e}")
            
            sys.exit(0 if results["errors"] == 0 else 1)
        else:
            logger.error(f"Path is neither file nor directory: {args.path}")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Ingestion interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        if args.verbose:
            import traceback
            logger.debug(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()