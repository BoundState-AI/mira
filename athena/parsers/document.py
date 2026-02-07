#!/usr/bin/env python3
"""
Module: Document
Purpose: BoundState AI Athena Document Intelligence System

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-033 (Requirements Traceability), SWE-032 (Data Protection)
Safety Critical: True
"""

﻿"""
BoundState AI Athena Document Intelligence System
parsers.py
Document parsers for various file formats with PII detection
Compliance: SWE-033 (Requirements Traceability), SWE-032 (Data Protection)
Co-Authored-By: Claude Opus 4.0 <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI o3/4.0/4.5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI


Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
__safety_critical__ = True  # NASA document processing system

import os
import re
import json
import unicodedata
import uuid
import logging
from pathlib import Path
from collections import Counter
from io import BytesIO
from typing import List, Dict, Any, Optional, Tuple
import shutil

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
from .structured_parser import StructuredDocumentParser

try:
    import openpyxl
    from openpyxl import load_workbook
except ImportError:
    openpyxl = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

try:
    import pytesseract
    # Configure Tesseract path - check environment variable first, then default paths
    tesseract_cmd = os.getenv("TESSERACT_CMD")
    if not tesseract_cmd:
        candidates = []
        if os.name == 'nt':  # Windows
            program_files = os.environ.get('PROGRAMFILES')
            program_files_x86 = os.environ.get('PROGRAMFILES(X86)')
            for base in filter(None, (program_files, program_files_x86)):
                candidates.append(os.path.join(base, 'Tesseract-OCR', 'tesseract.exe'))
            candidates.append(os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Tesseract-OCR', 'tesseract.exe'))
        candidates.append('tesseract')

        for candidate in candidates:
            if candidate == 'tesseract' or os.path.exists(candidate):
                tesseract_cmd = candidate
                break

    pytesseract.pytesseract.tesseract_cmd = r"C:\Users\jwilde2\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
except ImportError:
    pytesseract = None

from boundstate.utils import parse_version, extract_version_and_id, clean_text, secure_filename
from boundstate.config import CONFIG
import logging
import string

logger = logging.getLogger(__name__)

def _clean_text(text: str) -> str:
    """Clean visual junk like table borders and normalize spacing."""
    text = re.sub(r"[│┃╱╲╳═║╔╗╝╚╩╦╬━┻┳┏┓┛┗─—–•·…]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def _is_mostly_line_junk(text: str, threshold: float = 0.6) -> bool:
    """Check if text is mostly visual symbols (lines, boxes, etc)."""
    junk_chars = re.findall(r"[│┃╱╲╳═║╔╗╝╚╩╦╬━┻┳┏┓┛┗─—–•·…]", text)
    return len(junk_chars) / max(1, len(text)) > threshold

def find_poppler_path():
    """Find poppler binaries path for pdf2image"""
    import shutil
    import platform

    # Check if pdftoppm is in PATH
    pdftoppm = shutil.which('pdftoppm')
    if pdftoppm:
        return os.path.dirname(pdftoppm)

    if platform.system() == "Windows":
        # Check conda environment first
        conda_env = os.environ.get('CONDA_PREFIX')
        if conda_env:
            conda_poppler = os.path.join(conda_env, 'Library', 'bin')
            if os.path.exists(os.path.join(conda_poppler, 'pdftoppm.exe')):
                return conda_poppler

        # Common Windows paths
        common_paths = [
            r"C:\Program Files\poppler\Library\bin",
            r"C:\Program Files (x86)\poppler\Library\bin",
            r"C:\poppler\Library\bin",
        ]

        for path in common_paths:
            if os.path.exists(os.path.join(path, "pdftoppm.exe")):
                return path

    return None


class PIIDetector:
    """NASA-compliant PII detection for document parsing

    Detects and masks personally identifiable information (PII) and
    sensitive data in document content before processing.

    Compliance: NASA-CSET, SWE-032 (Data Protection)
    Security Classification: CUI//SP-PRVCY
    Authorization: NASA ATO Required
    """

    def __init__(self, mask_pii: bool = True):
        """Initialize PII detector

        Args:
            mask_pii: Whether to mask detected PII (True) or just flag it (False)
        """
        self.mask_pii = mask_pii
        self.logger = logging.getLogger(__name__)

        # PII detection patterns (NIST compliant)
        self.pii_patterns = {
            'ssn': r'\b\d{3}-?\d{2}-?\d{4}\b',
            'phone': r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b',
            'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'credit_card': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
            'driver_license': r'\b[A-Z]{1,2}[0-9]{6,8}\b',
            'passport': r'\b[A-Z]{2}[0-9]{7}\b',
            'zip_code': r'\b\d{5}(?:-\d{4})?\b',
            'date_of_birth': r'\b(?:0[1-9]|1[0-2])[/\-.](?:0[1-9]|[12][0-9]|3[01])[/\-.]\d{4}\b',
            'ip_address': r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
        }

        # CUI marking patterns
        self.cui_patterns = {
            'cui_marking': r'\b(?:CUI|cui)\b.*?(?:SP-PRVCY|PRVCY|Privacy|FOUO|For Official Use Only)\b',
            'classified': r'\b(?:CONFIDENTIAL|SECRET|TOP SECRET|UNCLASSIFIED)\b',
            'export_control': r'\b(?:ITAR|EAR|Export Control|Technology Transfer)\b'
        }

    def detect_pii(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Detect and optionally mask PII in text

        Args:
            text: Input text to scan

        Returns:
            Tuple of (processed_text, detected_pii_list)
        """
        req_id = str(uuid.uuid4())
        detected_pii = []
        processed_text = text

        # Scan for PII patterns
        for pii_type, pattern in self.pii_patterns.items():
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for match in matches:
                pii_info = {
                    'type': pii_type,
                    'value': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'req_id': req_id
                }
                detected_pii.append(pii_info)

                if self.mask_pii:
                    # Replace with masked value
                    mask = f"[{pii_type.upper()}_REDACTED]"
                    processed_text = processed_text[:match.start()] + mask + processed_text[match.end():]

        # Scan for CUI/classified markings
        for cui_type, pattern in self.cui_patterns.items():
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for match in matches:
                cui_info = {
                    'type': cui_type,
                    'value': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'req_id': req_id,
                    'is_cui_marking': True
                }
                detected_pii.append(cui_info)

        # Log PII detection results
        if detected_pii:
            pii_types = [p['type'] for p in detected_pii]
            self.logger.warning(f"PII detected in document: {Counter(pii_types)}", extra={'req_id': req_id})

            if self.mask_pii:
                self.logger.info("PII automatically masked before processing", extra={'req_id': req_id})
        else:
            self.logger.info("No PII detected in document content", extra={'req_id': req_id})

        return processed_text, detected_pii

    def get_classification_level(self, detected_pii: List[Dict[str, Any]]) -> str:
        """Determine document classification level based on detected content

        Args:
            detected_pii: List of detected PII/sensitive information

        Returns:
            Classification level string
        """
        if not detected_pii:
            return "UNCLASSIFIED"

        # Check for explicit classification markings
        for pii in detected_pii:
            if pii.get('is_cui_marking'):
                if 'CONFIDENTIAL' in pii['value'].upper():
                    return "CONFIDENTIAL"
                elif 'SECRET' in pii['value'].upper():
                    return "SECRET"
                elif 'CUI' in pii['value'].upper() or 'PRVCY' in pii['value'].upper():
                    return "CUI//SP-PRVCY"

        # Classify based on PII types found
        high_sensitivity_types = {'ssn', 'credit_card', 'passport', 'driver_license'}
        medium_sensitivity_types = {'phone', 'email', 'date_of_birth'}

        pii_types = {p['type'] for p in detected_pii if not p.get('is_cui_marking')}

        if pii_types & high_sensitivity_types:
            return "CUI//SP-PRVCY"
        elif pii_types & medium_sensitivity_types:
            return "CUI"
        else:
            return "UNCLASSIFIED"


class DocumentParser:
    """Base class for document parsers with NASA-compliant PII detection.

    Compliance: NASA-CSET, SWE-032 (Data Protection)
    Security Classification: CUI//SP-PRVCY
    Authorization: NASA ATO Required
    """

    def __init__(self, file_path: str, file_bytes: Optional[bytes] = None, doc_type: Optional[str] = None, enable_pii_detection: bool = True):
        self.file_path = secure_filename(os.path.basename(file_path))
        self.full_path = file_path
        self.file_bytes = file_bytes
        self.doc_type_override = doc_type
        self.base_doc_id, self.version_str = extract_version_and_id(self.file_path)
        self.version_tuple = parse_version(self.version_str)
        self.sections = []

        # NASA COMPLIANCE: Initialize PII detection
        self.pii_detector = PIIDetector(mask_pii=True) if enable_pii_detection else None
        self.detected_pii = []
        self.classification_level = "UNCLASSIFIED"
        self.logger = logging.getLogger(__name__)

    def _process_text_with_pii_detection(self, text: str) -> str:
        """Process text through PII detection and masking

        Args:
            text: Raw text content

        Returns:
            Processed text with PII masked (if enabled)

        Compliance: NASA-CSET, SWE-032 (Data Protection)
        Security Classification: CUI//SP-PRVCY
        Authorization: NASA ATO Required
        """
        if not self.pii_detector:
            return text

        processed_text, detected_pii = self.pii_detector.detect_pii(text)

        # Accumulate all detected PII for document classification
        self.detected_pii.extend(detected_pii)

        # Update document classification based on detected content
        if detected_pii:
            new_classification = self.pii_detector.get_classification_level(detected_pii)
            # Use highest classification level found
            current_priority = {"UNCLASSIFIED": 0, "CUI": 1, "CUI//SP-PRVCY": 2, "CONFIDENTIAL": 3, "SECRET": 4}.get(self.classification_level, 0)
            new_priority = {"UNCLASSIFIED": 0, "CUI": 1, "CUI//SP-PRVCY": 2, "CONFIDENTIAL": 3, "SECRET": 4}.get(new_classification, 0)

            if new_priority > current_priority:
                self.classification_level = new_classification
                req_id = str(uuid.uuid4())
                self.logger.info(f"Document classification updated to: {self.classification_level}", extra={'req_id': req_id})

        return processed_text

    def _is_form_content(self, text: str) -> bool:
        """Detect if text resembles a form or questionnaire."""
        form_pattern = re.compile(r'^\d+\.\d+\s+[^?]+?\?', re.MULTILINE)
        numbered_pattern = re.compile(r'^\d+\.\d+\s+', re.MULTILINE)
        return bool(form_pattern.search(text)) or len(numbered_pattern.findall(text)) > 3
    
    def _extract_title_from_chunk(self, chunk_text: str, chunk_num: int) -> str:
        """Extract a meaningful title from chunk text."""
        import re
        # Try to find a section heading
        lines = chunk_text.split('\n')
        for line in lines[:3]:  # Check first 3 lines
            line = line.strip()
            if line and len(line) < 100:
                # Check if it looks like a heading (starts with number or has keywords)
                if re.match(r'^\d+\.[\d\s]*\w', line) or any(keyword in line.lower() for keyword in ['purpose', 'process', 'introduction', 'section', 'appendix', 'reference']):
                    return line
        
        # Fallback to first meaningful words
        words = chunk_text.split()[:10]
        if len(words) > 3:
            title = ' '.join(words[:5]) + "..."
            return title
        
        return f"Section {chunk_num}"
    
    def _extract_header_metadata(self, text: str) -> Dict[str, Any]:
        """Extract header metadata (e.g., company info, certifications)."""
        header_lines = []
        for line in text.split('\n')[:15]:  # Extended to 15 lines for robustness
            if line.strip() and not line.startswith(('F1740', 'G1301', 'G1800', 'Page ', 'Amentum', 'Rev.', 'Effective')):
                header_lines.append(line.strip())
        return {'header_info': ' | '.join(header_lines)} if header_lines else {}

    def _clean_ocr_text(self, text: str) -> str:
        """Clean OCR-extracted text for better parsing.
        
        Compliance: SWE-033
        """
        text = unicodedata.normalize('NFKD', text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        text = re.sub(r'\s{2,}', ' ', text)
        text = re.sub(r'(\n\s*){2,}', '\n\n', text)
        footer_patterns = [
            r'Page \d+ of \d+',
            r'Amentum Proprietary',
            r'F\d{4}\.\d+[A-Z]? Rev\. \d+ Effective \d{4}-\d{2}-\d{2}',
            r'G\d{4}\.\d+[A-Z]? Rev\. \d+ Effective \d{4}-\d{2}-\d{2}',
            r'Copyright.*Amentum.*rights reserved'
        ]
        for pattern in footer_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences for finer granularity."""
        sentence_pattern = r'(?<=[.!?;])\s+'
        sentences = re.split(sentence_pattern, text.strip())
        return [s.strip() for s in sentences if s.strip()]

    def _create_section(self, section_num: str, title: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a standardized section dictionary with PII detection.

        Compliance: SWE-033 (Requirements Traceability), SWE-032 (Data Protection)
        Security Classification: CUI//SP-PRVCY
        Authorization: NASA ATO Required
        """
        # NASA COMPLIANCE: Process text through PII detection before storage
        clean_text_content = clean_text(text)
        processed_text = self._process_text_with_pii_detection(clean_text_content)
        processed_title = self._process_text_with_pii_detection(title.strip())

        doc_type = self.doc_type_override or self._infer_doc_type(processed_text)

        section = {
            "doc_id": f"{self.base_doc_id}_v{self.version_str}",
            "base_doc_id": self.base_doc_id,
            "version": self.version_str,
            "version_tuple": self.version_tuple,
            "section": section_num,
            "title": processed_title,
            "text": processed_text,
            "tags": [],
            "doc_type": doc_type,
            "file_path": self.full_path,
            "file_name": self.file_path,
            "source": self.full_path,
            "has_table": bool(metadata and metadata.get('table_data')),
            "classification": self.classification_level,  # Add classification level
            "pii_detected": len(self.detected_pii) > 0,  # Flag for PII presence
            "metadata": metadata or {
                "source": self.full_path,
                "parser": self.__class__.__name__
            }
        }
        return section

    def _extract_table_context(self, table_data):
        """Extract semantic context from table data for better tagging."""
        if not table_data:
            return {}
        
        context = {
            'headers': [],
            'keywords': [],
            'has_numbers': False,
            'has_dates': False,
            'column_count': 0,
            'row_count': len(table_data) if table_data else 0
        }
        
        if table_data and len(table_data) > 0:
            # First row often contains headers
            if table_data[0]:
                context['headers'] = [str(h).lower() for h in table_data[0]]
                context['column_count'] = len(table_data[0])
            
            # Extract all text for keyword analysis
            all_text = ' '.join(' '.join(str(cell) for cell in row) for row in table_data)
            context['has_numbers'] = bool(re.search(r'\d+[\.,]?\d*', all_text))
            context['has_dates'] = bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}', all_text))
        
        return context

    def _infer_doc_type(self, text: str) -> str:
        """Infer document type from content."""
        text_lower = text.lower()
        if self._is_form_content(text):
            return 'form'
        if 'timecard' in text_lower or 'time recording' in text_lower or 'travel' in text_lower or 'telework' in text_lower:
            return 'hr_policy'
        if 'procurement' in text_lower or 'order request' in text_lower or 'basware' in text_lower:
            return 'procurement'
        if any(word in text_lower for word in ['policy', 'hr', 'human resources', 'employee', 'leave', 'benefits']):
            return 'hr_policy'
        if any(word in text_lower for word in ['specification', 'technical', 'mil-std', 'nasa-std', 'procedure', 'standard']):
            return 'technical_spec'
        if any(word in text_lower for word in ['contract', 'procurement', 'rfp', 'rfq', 'proposal', 'agreement']):
            return 'contract'
        if any(word in text_lower for word in ['material', 'composite', 'alloy', 'crystal', 'structure']):
            return 'technical_spec'
        if any(word in text_lower for word in ['safety', 'compliance', 'regulation', 'hazard', 'risk']):
            return 'safety_compliance'
        return 'general'

    def _extract_full_text(self) -> str:
        """Extract full raw text for counting/indexing.

        Compliance: SWE-013
        """
        return ''

class DocxParser(DocumentParser):
    """Parser for Microsoft Word documents."""
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse DOCX document."""
        if Document is None:
            logger.error("python-docx not available. Cannot parse DOCX files.")
            return []
        
        try:
            if self.file_bytes:
                doc = Document(BytesIO(self.file_bytes))
            else:
                doc = Document(self.full_path)
            
            current_section_num = [0]
            current_title = "Introduction"
            text = ""
            has_paragraph_content = False
            form_pattern = re.compile(r'^\d+\.\d+\s+[^?]+?\?', re.MULTILINE)
            score_pattern = re.compile(r'^(Overall Section Score:.*?(?:Acceptable|Not Acceptable))', re.MULTILINE)
            full_text = ''
            
            all_text = "\n".join(para.text for para in doc.paragraphs)
            full_text = all_text
            header_metadata = self._extract_header_metadata(all_text)
            if header_metadata:
                self.sections.append(self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            for para in doc.paragraphs:
                if para.text.strip():
                    has_paragraph_content = True
                
                block_match = re.compile(r'^Block\s+(\w+)\s*[-–]\s*(.+)', re.IGNORECASE).match(para.text.strip())
                score_match = score_pattern.match(para.text.strip())
                if block_match:
                    if text.strip():
                        sec_num = '.'.join(map(str, current_section_num))
                        section = self._create_section(sec_num, current_title, text)
                        if self._is_form_content(text):
                            section['doc_type'] = 'form'
                            section['tags'] = section.get('tags', []) + ['form']
                            qa_matches = form_pattern.finditer(text)
                            for qa_match in qa_matches:
                                qa_text = qa_match.group(0)
                                qa_num = qa_text.split()[0]
                                self.sections.append(self._create_section(
                                    f"{sec_num}.{qa_num}",
                                    qa_text.split('?')[0].strip(),
                                    qa_text
                                ))
                                self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                                self.sections[-1]['doc_type'] = 'form'
                        self.sections.append(section)
                    current_section_num = [block_match.group(1)]
                    current_title = block_match.group(2).strip()
                    text = ""
                elif score_match:
                    if text.strip():
                        sec_num = '.'.join(map(str, current_section_num))
                        self.sections.append(self._create_section(sec_num, current_title, text))
                    current_section_num[-1] += 1
                    current_title = score_match.group(1).strip()
                    text = ""
                elif para.style.name.startswith('Heading'):
                    if text.strip():
                        sec_num = '.'.join(map(str, current_section_num))
                        section = self._create_section(sec_num, current_title, text)
                        if self._is_form_content(text):
                            section['doc_type'] = 'form'
                            section['tags'] = section.get('tags', []) + ['form']
                            qa_matches = form_pattern.finditer(text)
                            for qa_match in qa_matches:
                                qa_text = qa_match.group(0)
                                qa_num = qa_text.split()[0]
                                self.sections.append(self._create_section(
                                    f"{sec_num}.{qa_num}",
                                    qa_text.split('?')[0].strip(),
                                    qa_text
                                ))
                                self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                                self.sections[-1]['doc_type'] = 'form'
                        self.sections.append(section)
                    
                    try:
                        level = int(para.style.name.split()[-1])
                    except (ValueError, IndexError):
                        level = 1
                    
                    if level > len(current_section_num):
                        current_section_num.extend([0] * (level - len(current_section_num)))
                    else:
                        current_section_num = current_section_num[:level]
                    
                    current_section_num[-1] += 1
                    current_title = para.text.strip() or "Untitled Section"
                    text = ""
                else:
                    text += para.text + "\n"
            
            if text.strip():
                sec_num = '.'.join(map(str, current_section_num))
                section = self._create_section(sec_num, current_title, text)
                if self._is_form_content(text):
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['form']
                    qa_matches = form_pattern.finditer(text)
                    for qa_match in qa_matches:
                        qa_text = qa_match.group(0)
                        qa_num = qa_text.split()[0]
                        self.sections.append(self._create_section(
                            f"{sec_num}.{qa_num}",
                            qa_text.split('?')[0].strip(),
                            qa_text
                        ))
                        self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                        self.sections[-1]['doc_type'] = 'form'
                self.sections.append(section)
            
            if not has_paragraph_content and doc.tables:
                logger.info(f"No paragraph content in {self.file_path}, extracting from tables")
                table_text = []
                table_data = []
                
                for table in doc.tables:
                    table_rows = []
                    for row in table.rows:
                        row_text = []
                        row_data = []
                        for cell in row.cells:
                            cell_text = cell.text.strip()
                            if cell_text and cell_text not in row_text:
                                row_text.append(cell_text)
                                row_data.append(cell_text)
                        if row_text:
                            table_text.append(' | '.join(row_text))
                            table_rows.append(row_data)
                    if table_rows:
                        table_data.append(table_rows)
                
                if table_text:
                    combined_text = "\n".join(table_text)
                    table_context = self._extract_table_context(table_data[0] if table_data else [])
                    metadata = {
                        'table_data': table_data,
                        'table_context': table_context,
                        'is_structured_form': True
                    }
                    section = self._create_section("1", "Form Content", combined_text, metadata=metadata)
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['table', 'form']
                    # Add context-based tags
                    if table_context.get('has_dates'):
                        section['tags'].append('schedule_table')
                    if table_context.get('has_numbers') and any('cost' in str(h).lower() or 'price' in str(h).lower() for h in table_context.get('headers', [])):
                        section['tags'].append('procurement_table')
                    if self._is_form_content(combined_text):
                        qa_matches = form_pattern.finditer(combined_text)
                        for qa_match in qa_matches:
                            qa_text = qa_match.group(0)
                            qa_num = qa_text.split()[0]
                            self.sections.append(self._create_section(
                                f"1.{qa_num}",
                                qa_text.split('?')[0].strip(),
                                qa_text
                            ))
                            self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                            self.sections[-1]['doc_type'] = 'form'
                    self.sections.append(section)
            
            if not self.sections:
                all_text = "\n".join([para.text for para in doc.paragraphs])
                if doc.tables:
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                if cell.text.strip():
                                    all_text += "\n" + cell.text.strip()
                
                if all_text.strip():
                    if len(all_text) < 300:
                        section = self._create_section("1", "Document Template", all_text)
                        section['tags'] = section.get('tags', []) + ['template']
                        if not self.doc_type_override:
                            section['doc_type'] = 'template'
                        self.sections.append(section)
                    else:
                        section = self._create_section("1", "Document Content", all_text)
                        if self._is_form_content(all_text):
                            section['doc_type'] = 'form'
                            section['tags'] = section.get('tags', []) + ['form']
                            qa_matches = form_pattern.finditer(all_text)
                            for qa_match in qa_matches:
                                qa_text = qa_match.group(0)
                                qa_num = qa_text.split()[0]
                                self.sections.append(self._create_section(
                                    f"1.{qa_num}",
                                    qa_text.split('?')[0].strip(),
                                    qa_text
                                ))
                                self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                                self.sections[-1]['doc_type'] = 'form'
                        self.sections.append(section)
            
            # Add full_text to sections for counting
            for sec in self.sections:
                sec['full_text'] = full_text
            
            logger.info(f"Parsed DOCX {self.file_path}: {len(self.sections)} sections")
            return self.sections
            
        except Exception as e:
            logger.error(f"Error parsing DOCX {self.file_path}: {e}")
            return []

class PdfParser(DocumentParser):
    """Parser for PDF documents."""
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse PDF document."""
        if fitz is None:
            logger.error("PyMuPDF not available. Cannot parse PDF files.")
            return []
        
        try:
            if self.file_bytes:
                doc = fitz.open(stream=self.file_bytes, filetype="pdf")
            else:
                doc = fitz.open(self.full_path)
            
            if not doc.is_encrypted:
                logger.debug(f"Opened {self.file_path} with {len(doc)} pages")
            else:
                logger.warning(f"{self.file_path} is encrypted, attempting decryption if possible")
            
            # Try table-aware extraction first
            all_text = ""
            has_table_structure = False
            used_table_extraction = False
            full_text = ''
            
            for page_num, page in enumerate(doc):
                # Get structured text with position data for table reconstruction
                blocks = page.get_text("dict")["blocks"]
                
                # Group text by Y-position (rows)
                rows_by_y = {}
                
                for block in blocks:
                    if "lines" in block:  # Text block
                        for line in block["lines"]:
                            for span in line["spans"]:
                                text = span["text"].strip()
                                if text and not text.isspace():
                                    # Get Y position (vertical position on page)
                                    y_pos = round(span["bbox"][1], 1)  # Round to nearest 0.1 for grouping
                                    x_pos = span["bbox"][0]  # X position for column ordering
                                    
                                    if y_pos not in rows_by_y:
                                        rows_by_y[y_pos] = []
                                    
                                    rows_by_y[y_pos].append({
                                        "x": x_pos,
                                        "text": text,
                                        "bbox": span["bbox"]
                                    })
                
                # Check if this looks like table structure (multiple columns)
                if rows_by_y:
                    avg_items_per_row = sum(len(items) for items in rows_by_y.values()) / len(rows_by_y)
                    if avg_items_per_row > 1.5:  # Multiple items per row suggests table
                        has_table_structure = True
                        used_table_extraction = True
                
                # Sort rows by Y position and reconstruct text
                page_lines = []
                for y_pos in sorted(rows_by_y.keys()):
                    # Sort items in each row by X position (left to right)
                    row_items = sorted(rows_by_y[y_pos], key=lambda item: item["x"])
                    
                    # Join items with appropriate spacing
                    row_text = ""
                    last_x_end = 0
                    
                    for i, item in enumerate(row_items):
                        # Add spacing based on position gap
                        if i > 0:
                            gap = item["x"] - last_x_end
                            if gap > 50:  # Significant gap = likely different column
                                row_text += " | "  # Use | as column separator for clarity
                            else:
                                row_text += " "
                        
                        row_text += item["text"]
                        last_x_end = item["bbox"][2]  # Right edge of current item
                    
                    if row_text:
                        page_lines.append(row_text)
                
                if page_lines:
                    all_text += "\n".join(page_lines) + "\n\n"
                    logger.debug(f"Extracted {len(page_lines)} lines from page {page_num + 1} of {self.file_path}")
                else:
                    # Fallback to simple text extraction
                    page_text = page.get_text("text")
                    if page_text.strip():
                        cleaned = clean_text(page_text)
                        all_text += page_text + "\n\n"
                        full_text += cleaned + '\n'
                    else:
                        logger.debug(f"No text extracted from page {page_num + 1} of {self.file_path}")
            
            # Clean line-art and junk
            all_text = _clean_text(all_text)
            if _is_mostly_line_junk(all_text):
                logger.warning(f"{self.file_path} appears to be mostly table borders. Consider OCR fallback.")
            
            all_text = self._clean_ocr_text(all_text)
            ocr_fallback = False
            
            header_metadata = self._extract_header_metadata(all_text)
            if header_metadata:
                self.sections.append(self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            size_counter = Counter()
            all_spans = []
            
            # We already collected blocks during table extraction, so reuse them
            # This ensures size_counter is populated even with table extraction
            for page in doc:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                size = round(span["size"], 2)
                                text = span["text"].strip()
                                if text:
                                    size_counter[size] += len(text)
                                    all_spans.append(span)
            
            # Changed condition to only check for empty text, not empty size_counter
            # Table-extracted text may not have size info but still has content
            if not all_text.strip():
                logger.warning(f"No text found in PDF {self.file_path}")
                if convert_from_path is None or pytesseract is None:
                    logger.error("pdf2image or pytesseract not available for OCR fallback.")
                    return []
                logger.info(f"Attempting OCR fallback for {self.file_path}")
                ocr_fallback = True
                all_text = all_text or ""  # Preserve any prior text if exists
                req_id = f"ocr-{Path(self.file_path).stem}"
                env_snapshot = {
                    "path": os.environ.get("PATH", ""),
                    "pdftotext": shutil.which("pdftotext"),
                    "cwd": os.getcwd(),
                }
                logger.debug(
                    "OCR fallback environment snapshot for %s",
                    self.file_path,
                    extra={"req_id": req_id, **env_snapshot},
                )
                try:
                    poppler_path = find_poppler_path()
                    if poppler_path:
                        images = convert_from_path(self.full_path, dpi=300, poppler_path=poppler_path)
                    else:
                        poppler_path = find_poppler_path()
                        if poppler_path:
                            images = convert_from_path(self.full_path, dpi=300, poppler_path=poppler_path)
                        else:
                            images = convert_from_path(self.full_path, dpi=300)
                    custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
                    for img in images:
                        pytesseract.pytesseract.tesseract_cmd = r"C:\Users\jwilde2\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
                        pytesseract.pytesseract.tesseract_cmd = r"C:\Users\jwilde2\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
                        page_text = pytesseract.image_to_string(img, lang='eng', config=custom_config)
                        all_text += self._clean_ocr_text(page_text) + "\n\n"
                    if not all_text.strip():
                        logger.warning(f"OCR extracted no text from {self.file_path}")
                        return []
                    # Simulate spans for OCR text
                    lines = all_text.split('\n')
                    for i, line in enumerate(lines):
                        if line.strip():
                            all_spans.append({
                                "size": 12.0,  # Default body size
                                "flags": 0,
                                "text": line.strip()
                            })
                    # Set default size_counter for OCR text
                    size_counter[12.0] = len(all_text)
                    used_table_extraction = True  # Treat OCR as potentially table-like
                except Exception as ocr_e:
                    logger.error(
                        f"OCR fallback failed for {self.file_path}: {ocr_e}",
                        extra={"req_id": req_id, **env_snapshot},
                    )
                    return []
            
            # Continue with span-based sectioning (preserves document structure)
            
            body_size = size_counter.most_common(1)[0][0] if size_counter else 12.0
            heading_sizes = sorted({sz for sz in size_counter if sz > body_size}, reverse=True)
            heading_levels = {sz: i + 1 for i, sz in enumerate(heading_sizes)}
            
            section_stack = [0] * (len(heading_levels) + 1)
            current_title = "Introduction"
            text = ""
            form_pattern = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE)
            score_pattern = re.compile(r'^(Overall Section Score:.*?(?:Acceptable|Not Acceptable))', re.MULTILINE)
            
            for span in all_spans:
                size = round(span["size"], 2)
                flags = span["flags"]
                is_bold = bool(flags & 2 ** 4)
                txt = span["text"].strip()
                
                if txt:
                    score_match = score_pattern.match(txt)
                    if score_match:
                        if text.strip():
                            level = 1
                            sec_num = '.'.join(map(str, section_stack[1:level + 1]))
                            section = self._create_section(sec_num, current_title, text)
                            if self._is_form_content(text):
                                section['doc_type'] = 'form'
                                section['tags'] = section.get('tags', []) + ['form']
                                qa_matches = form_pattern.finditer(text)
                                for qa_match in qa_matches:
                                    qa_text = qa_match.group(1)
                                    qa_num = qa_text.split()[0]
                                    self.sections.append(self._create_section(
                                        f"{sec_num}.{qa_num}",
                                        qa_text.split('?')[0].strip(),
                                        qa_text
                                    ))
                                    self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                                    self.sections[-1]['doc_type'] = 'form'
                            self.sections.append(section)
                        section_stack[1] += 1
                        current_title = score_match.group(1).strip()
                        text = ""
                    elif size in heading_levels and is_bold and len(txt) < 200:
                        if text.strip():
                            level = heading_levels.get(size, 1)
                            sec_num = '.'.join(map(str, section_stack[1:level + 1]))
                            section = self._create_section(sec_num, current_title, text)
                            if self._is_form_content(text):
                                section['doc_type'] = 'form'
                                section['tags'] = section.get('tags', []) + ['form']
                                qa_matches = form_pattern.finditer(text)
                                for qa_match in qa_matches:
                                    qa_text = qa_match.group(1)
                                    qa_num = qa_text.split()[0]
                                    self.sections.append(self._create_section(
                                        f"{sec_num}.{qa_num}",
                                        qa_text.split('?')[0].strip(),
                                        qa_text
                                    ))
                                    self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                                    self.sections[-1]['doc_type'] = 'form'
                            self.sections.append(section)
                        level = heading_levels[size]
                        section_stack[level] += 1
                        for deeper in range(level + 1, len(section_stack)):
                            section_stack[deeper] = 0
                        current_title = txt
                        text = ""
                    else:
                        text += txt + " "
            
            if text.strip():
                sec_num = '.'.join(map(str, section_stack[1:]))
                if sec_num:
                    section = self._create_section(sec_num, current_title, text)
                    if self._is_form_content(text):
                        section['doc_type'] = 'form'
                        section['tags'] = section.get('tags', []) + ['form']
                        qa_matches = form_pattern.finditer(text)
                        for qa_match in qa_matches:
                            qa_text = qa_match.group(1)
                            qa_num = qa_text.split()[0]
                            self.sections.append(self._create_section(
                                f"{sec_num}.{qa_num}",
                                qa_text.split('?')[0].strip(),
                                qa_text
                            ))
                            self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                            self.sections[-1]['doc_type'] = 'form'
                    self.sections.append(section)
            
            if not self.sections and all_text.strip():
                section = self._create_section("1", "Document Content", all_text)
                if self._is_form_content(all_text):
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['form']
                    qa_matches = form_pattern.finditer(all_text)
                    for qa_match in qa_matches:
                        qa_text = qa_match.group(1)
                        qa_num = qa_text.split()[0]
                        self.sections.append(self._create_section(
                            f"1.{qa_num}",
                            qa_text.split('?')[0].strip(),
                            qa_text
                        ))
                        self.sections[-1]['tags'] = self.sections[-1].get('tags', []) + ['question']
                        self.sections[-1]['doc_type'] = 'form'
                self.sections.append(section)
            
            # Conditional chunking fallback if span-based yielded poor results
            # This helps with table-heavy documents that don't have clear heading structure
            if len(self.sections) < max(1, len(all_text) // 1000) and used_table_extraction:
                logger.info(f"Falling back to chunking for {self.file_path} due to low section count from spans")
                self.sections = []  # Discard poor span sections
                
                # Split into chunks for better searchability
                text_parts = re.split(r'\n\n+|\n(?=\d+\.\d+\s)', all_text.strip())
                
                current_chunk = []
                current_size = 0
                chunk_num = 1
                target_chunk_size = 200  # Match original parser's avg section size
                
                for part in text_parts:
                    part = part.strip()
                    if not part:
                        continue
                    
                    part_size = len(part)
                    
                    if part_size > 400:
                        sentences = re.split(r'(?<=[.!?])\s+|(?<=[;:])\s+', part)
                        for sentence in sentences:
                            if current_size + len(sentence) > target_chunk_size and current_chunk:
                                chunk_text = ' '.join(current_chunk)
                                title = self._extract_title_from_chunk(chunk_text, chunk_num)
                                self.sections.append(self._create_section(str(chunk_num), title, chunk_text))
                                chunk_num += 1
                                current_chunk = [sentence]
                                current_size = len(sentence)
                            else:
                                current_chunk.append(sentence)
                                current_size += len(sentence)
                    elif current_size + part_size > target_chunk_size and current_chunk:
                        chunk_text = ' '.join(current_chunk)
                        title = self._extract_title_from_chunk(chunk_text, chunk_num)
                        self.sections.append(self._create_section(str(chunk_num), title, chunk_text))
                        chunk_num += 1
                        current_chunk = [part]
                        current_size = part_size
                    else:
                        current_chunk.append(part)
                        current_size += part_size
                
                if current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    title = self._extract_title_from_chunk(chunk_text, chunk_num)
                    self.sections.append(self._create_section(str(chunk_num), title, chunk_text))
            
            # Split non-Q&A content into sentences
            final_sections = []
            if ocr_fallback:
                logger.info(f"OCR fallback successful, processing {len(self.sections)} initial sections")
            for section in self.sections:
                if section['doc_type'] != 'form' or 'question' not in section['tags']:
                    sentences = self._split_sentences(section['text'])
                    for i, sentence in enumerate(sentences, 1):
                        if len(sentence.split()) > 5:  # Skip short fragments
                            final_sections.append(self._create_section(
                                f"{section['section']}.{i}",
                                f"{section['title']} Part {i}",
                                sentence
                            ))
                            final_sections[-1]['doc_type'] = section['doc_type']
                            final_sections[-1]['tags'] = section['tags']
                else:
                    final_sections.append(section)
            self.sections = final_sections
            
            # Add full_text to the last section for counting
            if self.sections:
                self.sections[-1]['full_text'] = full_text
            
            if 'doc' in locals() and doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            logger.info(f"Parsed PDF {self.file_path}: {len(self.sections)} sections")
            return self.sections
            
        except Exception as e:
            logger.error(f"Error parsing PDF {self.file_path}: {e}")
            return []

class ExcelParser(DocumentParser):
    """Parser for Excel spreadsheets."""
    
    def is_empty_spreadsheet(self, wb) -> bool:
        """Check if Excel file is an empty template."""
        total_cells = 0
        filled_cells = 0
        
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            for row in sheet.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        total_cells += 1
                        if str(cell).strip():
                            filled_cells += 1
        
        if total_cells > 0:
            fill_ratio = filled_cells / total_cells
            return fill_ratio < 0.1
        
        return True
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse Excel document."""
        if openpyxl is None:
            logger.error("openpyxl not available. Cannot parse Excel files.")
            return []
            
        try:
            if self.file_bytes:
                wb = load_workbook(filename=BytesIO(self.file_bytes), data_only=True)
            else:
                wb = load_workbook(filename=self.full_path, data_only=True)
            
            sections = []
            is_empty_template = self.is_empty_spreadsheet(wb)
            all_text = ""
            
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                text_content = []
                table_data = []
                
                for row in sheet.iter_rows(values_only=True):
                    row_text = ' '.join([str(cell) for cell in row if cell is not None])
                    row_data = [str(cell) for cell in row if cell is not None]
                    if row_text.strip():
                        text_content.append(row_text)
                        table_data.append(row_data)
                        all_text += row_text + "\n"
                
                if text_content:
                    section_text = '\n'.join(text_content[:100])
                    section = self._create_section(
                        section_num=str(len(sections) + 1),
                        title=f"Sheet: {sheet_name}",
                        text=section_text,
                        metadata={'table_data': table_data}
                    )
                    section['tags'] = section.get('tags', []) + ['table']
                    if self._is_form_content(section_text):
                        section['doc_type'] = 'form'
                        section['tags'] = section.get('tags', []) + ['form']
                        qa_matches = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE).finditer(section_text)
                        for qa_match in qa_matches:
                            qa_text = qa_match.group(1)
                            qa_num = qa_text.split()[0]
                            sections.append(self._create_section(
                                f"{len(sections) + 1}.{qa_num}",
                                qa_text.split('?')[0].strip(),
                                qa_text
                            ))
                            sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                            sections[-1]['doc_type'] = 'form'
                    sections.append(section)
            
            header_metadata = self._extract_header_metadata(all_text)
            if header_metadata:
                sections.insert(0, self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            wb.close()
            
            if not sections:
                if is_empty_template:
                    sections.append(self._create_section(
                        "1",
                        "Empty Template",
                        "Empty spreadsheet template - ready for data entry"
                    ))
                else:
                    sections.append(self._create_section(
                        "1",
                        "Empty Spreadsheet",
                        "No data found in spreadsheet"
                    ))
            
            self.sections = sections
            logger.info(f"Parsed Excel {self.file_path}: {len(self.sections)} sections")
            return sections
            
        except Exception as e:
            logger.error(f"Error parsing Excel {self.file_path}: {e}")
            return [self._create_section("1", "Parse Error", f"Could not parse Excel file: {str(e)}")]

class TextParser(DocumentParser):
    """Parser for plain text documents."""
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse text document."""
        try:
            if self.file_bytes:
                text = self.file_bytes.decode('utf-8', errors='ignore')
            else:
                with open(self.full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            text = self._clean_ocr_text(text)
            
            sections = []
            header_metadata = self._extract_header_metadata(text)
            if header_metadata:
                sections.append(self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            section_pattern = re.compile(r'^(\d+\.\d+\s+[^?\n]+(?:\?)?)', re.MULTILINE)
            score_pattern = re.compile(r'^(Overall Section Score:.*?(?:Acceptable|Not Acceptable))', re.MULTILINE)
            paragraphs = text.split('\n\n')
            section_num = 1
            
            for para in paragraphs:
                if para.strip():
                    score_match = score_pattern.match(para.strip())
                    section_match = section_pattern.match(para.strip())
                    if score_match:
                        section = self._create_section(str(section_num), score_match.group(1).strip(), para)
                        sections.append(section)
                        section_num += 1
                    elif section_match:
                        title = section_match.group(1).strip()
                        content = para[section_match.end():].strip()
                        section = self._create_section(str(section_num), title, content)
                        if self._is_form_content(content):
                            section['doc_type'] = 'form'
                            section['tags'] = section.get('tags', []) + ['form']
                            qa_matches = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE).finditer(content)
                            for qa_match in qa_matches:
                                qa_text = qa_match.group(1)
                                qa_num = qa_text.split()[0]
                                sections.append(self._create_section(
                                    f"{section_num}.{qa_num}",
                                    qa_text.split('?')[0].strip(),
                                    qa_text
                                ))
                                sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                                sections[-1]['doc_type'] = 'form'
                        sections.append(section)
                        section_num += 1
                    else:
                        sentences = self._split_sentences(para)
                        for i, sentence in enumerate(sentences, 1):
                            if len(sentence.split()) > 5:
                                section = self._create_section(f"{section_num}.{i}", f"Section {section_num} Part {i}", sentence)
                                if self._is_form_content(sentence):
                                    section['doc_type'] = 'form'
                                    section['tags'] = section.get('tags', []) + ['form']
                                    qa_matches = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE).finditer(sentence)
                                    for qa_match in qa_matches:
                                        qa_text = qa_match.group(1)
                                        qa_num = qa_text.split()[0]
                                        sections.append(self._create_section(
                                            f"{section_num}.{qa_num}",
                                            qa_text.split('?')[0].strip(),
                                            qa_text
                                        ))
                                        sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                                        sections[-1]['doc_type'] = 'form'
                                sections.append(section)
                        section_num += 1
            
            if not sections and text.strip():
                section = self._create_section("1", "Document Content", text)
                if self._is_form_content(text):
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['form']
                    qa_matches = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE).finditer(text)
                    for qa_match in qa_matches:
                        qa_text = qa_match.group(1)
                        qa_num = qa_text.split()[0]
                        sections.append(self._create_section(
                            f"1.{qa_num}",
                            qa_text.split('?')[0].strip(),
                            qa_text
                        ))
                        sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                        sections[-1]['doc_type'] = 'form'
                sections.append(section)
            
            self.sections = sections
            logger.info(f"Parsed text {self.file_path}: {len(self.sections)} sections")
            return self.sections
            
        except Exception as e:
            logger.error(f"Error parsing text {self.file_path}: {e}")
            return []

class MarkdownParser(DocumentParser):
    """Parser for Markdown documents."""
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse Markdown document."""
        try:
            if self.file_bytes:
                text = self.file_bytes.decode('utf-8', errors='ignore')
            else:
                with open(self.full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            text = self._clean_ocr_text(text)
            
            sections = []
            header_metadata = self._extract_header_metadata(text)
            if header_metadata:
                sections.append(self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
            form_pattern = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE)
            score_pattern = re.compile(r'^(Overall Section Score:.*?(?:Acceptable|Not Acceptable))', re.MULTILINE)
            last_end = 0
            section_num = 0
            current_title = "Introduction"
            
            for match in header_pattern.finditer(text):
                content = text[last_end:match.start()].strip()
                if content:
                    section_num += 1
                    section = self._create_section(str(section_num), current_title, content)
                    if self._is_form_content(content):
                        section['doc_type'] = 'form'
                        section['tags'] = section.get('tags', []) + ['form']
                        qa_matches = form_pattern.finditer(content)
                        for qa_match in qa_matches:
                            qa_text = qa_match.group(1)
                            qa_num = qa_text.split()[0]
                            sections.append(self._create_section(
                                f"{section_num}.{qa_num}",
                                qa_text.split('?')[0].strip(),
                                qa_text
                            ))
                            sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                            sections[-1]['doc_type'] = 'form'
                    elif score_pattern.search(content):
                        section['tags'] = section.get('tags', []) + ['score']
                    else:
                        sentences = self._split_sentences(content)
                        for i, sentence in enumerate(sentences, 1):
                            if len(sentence.split()) > 5:
                                sections.append(self._create_section(
                                    f"{section_num}.{i}",
                                    f"{current_title} Part {i}",
                                    sentence
                                ))
                                sections[-1]['doc_type'] = section['doc_type']
                                sections[-1]['tags'] = section['tags']
                    sections.append(section)
                
                current_title = match.group(2).strip()
                last_end = match.end()
            
            content = text[last_end:].strip()
            if content:
                section_num += 1
                section = self._create_section(str(section_num), current_title, content)
                if self._is_form_content(content):
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['form']
                    qa_matches = form_pattern.finditer(content)
                    for qa_match in qa_matches:
                        qa_text = qa_match.group(1)
                        qa_num = qa_text.split()[0]
                        sections.append(self._create_section(
                            f"{section_num}.{qa_num}",
                            qa_text.split('?')[0].strip(),
                            qa_text
                        ))
                        sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                        sections[-1]['doc_type'] = 'form'
                elif score_pattern.search(content):
                    section['tags'] = section.get('tags', []) + ['score']
                else:
                    sentences = self._split_sentences(content)
                    for i, sentence in enumerate(sentences, 1):
                        if len(sentence.split()) > 5:
                            sections.append(self._create_section(
                                f"{section_num}.{i}",
                                f"{current_title} Part {i}",
                                sentence
                            ))
                            sections[-1]['doc_type'] = section['doc_type']
                            sections[-1]['tags'] = section['tags']
                sections.append(section)
            
            if not sections and text.strip():
                section = self._create_section("1", "Document Content", text)
                if self._is_form_content(text):
                    section['doc_type'] = 'form'
                    section['tags'] = section.get('tags', []) + ['form']
                    qa_matches = form_pattern.finditer(text)
                    for qa_match in qa_matches:
                        qa_text = qa_match.group(1)
                        qa_num = qa_text.split()[0]
                        sections.append(self._create_section(
                            f"1.{qa_num}",
                            qa_text.split('?')[0].strip(),
                            qa_text
                        ))
                        sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                        sections[-1]['doc_type'] = 'form'
                elif score_pattern.search(text):
                    section['tags'] = section.get('tags', []) + ['score']
                else:
                    sentences = self._split_sentences(text)
                    for i, sentence in enumerate(sentences, 1):
                        if len(sentence.split()) > 5:
                            sections.append(self._create_section(
                                f"1.{i}",
                                f"Document Content Part {i}",
                                sentence
                            ))
                            sections[-1]['doc_type'] = section['doc_type']
                            sections[-1]['tags'] = section['tags']
                sections.append(section)
            
            self.sections = sections
            logger.info(f"Parsed Markdown {self.file_path}: {len(self.sections)} sections")
            return self.sections
            
        except Exception as e:
            logger.error(f"Error parsing Markdown {self.file_path}: {e}")
            return []

class PowerPointParser(DocumentParser):
    """Parser for PowerPoint presentations."""
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse PowerPoint presentation."""
        if Presentation is None:
            logger.error("python-pptx not available. Cannot parse PowerPoint files.")
            return []
            
        try:
            if self.file_bytes:
                prs = Presentation(BytesIO(self.file_bytes))
            else:
                prs = Presentation(self.full_path)
            
            sections = []
            all_text = ""
            form_pattern = re.compile(r'(\d+\.\d+\s+[^?\n]+?\?)', re.MULTILINE)
            score_pattern = re.compile(r'^(Overall Section Score:.*?(?:Acceptable|Not Acceptable))', re.MULTILINE)
            
            for i, slide in enumerate(prs.slides):
                slide_text = []
                slide_title = ""
                table_rows = []
                
                if hasattr(slide, 'shapes'):
                    for shape in slide.shapes:
                        if hasattr(shape, 'text_frame') and shape.has_text_frame:
                            if shape.text_frame.text and i == 0 and shape == slide.shapes[0]:
                                slide_title = shape.text_frame.text.strip()
                            else:
                                for paragraph in shape.text_frame.paragraphs:
                                    text = paragraph.text.strip()
                                    if text:
                                        slide_text.append(text)
                                        all_text += text + "\n"
                        
                        if hasattr(shape, 'table'):
                            for row in shape.table.rows:
                                row_text = []
                                row_data = []
                                for cell in row.cells:
                                    if cell.text_frame:
                                        cell_text = cell.text_frame.text.strip()
                                        if cell_text:
                                            row_text.append(cell_text)
                                            row_data.append(cell_text)
                                            all_text += cell_text + "\n"
                                if row_text:
                                    slide_text.append(' | '.join(row_text))
                                    table_rows.append(row_data)
                
                if slide_text or slide_title:
                    title = slide_title if slide_title else f"Slide {i + 1}"
                    text = '\n'.join(slide_text) if slide_text else "Slide with no text content"
                    section = self._create_section(
                        section_num=str(i + 1),
                        title=title,
                        text=text,
                        metadata={'table_data': table_rows} if table_rows else None
                    )
                    if self._is_form_content(text):
                        section['doc_type'] = 'form'
                        section['tags'] = section.get('tags', []) + ['form']
                        qa_matches = form_pattern.finditer(text)
                        for qa_match in qa_matches:
                            qa_text = qa_match.group(1)
                            qa_num = qa_text.split()[0]
                            sections.append(self._create_section(
                                f"{i + 1}.{qa_num}",
                                qa_text.split('?')[0].strip(),
                                qa_text
                            ))
                            sections[-1]['tags'] = sections[-1].get('tags', []) + ['question']
                            sections[-1]['doc_type'] = 'form'
                    elif score_pattern.search(text):
                        section['tags'] = section.get('tags', []) + ['score']
                    else:
                        sentences = self._split_sentences(text)
                        for j, sentence in enumerate(sentences, 1):
                            if len(sentence.split()) > 5:
                                sections.append(self._create_section(
                                    f"{i + 1}.{j}",
                                    f"{title} Part {j}",
                                    sentence
                                ))
                                sections[-1]['doc_type'] = section['doc_type']
                                sections[-1]['tags'] = section['tags']
                    sections.append(section)
            
            header_metadata = self._extract_header_metadata(all_text)
            if header_metadata:
                sections.insert(0, self._create_section("0", "Document Header", "", metadata=header_metadata))
            
            if not sections:
                sections.append(self._create_section(
                    "1",
                    "Empty Presentation",
                    "No slides or text content found in presentation"
                ))
            
            self.sections = sections
            logger.info(f"Parsed PowerPoint {self.file_path}: {len(self.sections)} sections")
            return sections
            
        except Exception as e:
            logger.error(f"Error parsing PowerPoint {self.file_path}: {e}")
            return [self._create_section("1", "Parse Error", f"Could not parse PowerPoint file: {str(e)}")]

class CadParser(DocumentParser):
    """Parser for CAD files (e.g., .dwg, .dxf).

    Compliance: SWE-013
    """
    def parse(self) -> List[Dict[str, Any]]:
        """Extract metadata and text from CAD files."""
        logger.warning("CAD parsing not fully implemented; extracting metadata only")
        import uuid
        metadata = {
            'doc_id': str(uuid.uuid4()),
            'filename': secure_filename(Path(self.full_path).name if self.full_path else 'cad_file'),
            'doc_type': 'cad',
            'tags': ['engineering', 'design']
        }
        return [{
            'section_number': '1',
            'title': 'CAD Metadata',
            'text': f"CAD file: {metadata['filename']}",
            'metadata': metadata,
            'full_text': f"CAD file: {metadata['filename']}"
        }]

class ImageParser(DocumentParser):
    """Parser for image files (e.g., .jpg, .png, .bmp).

    Uses OCR to extract text from engineering drawings and technical images.
    Compliance: SWE-013
    """
    def parse(self) -> List[Dict[str, Any]]:
        """Extract text and metadata from image files using OCR."""
        try:
            # Import OCR engine
            import sys
            sys.path.append('./EM32')
            from ocr_engine import EngineeringOCR

            import uuid
            from PIL import Image
            from io import BytesIO

            # Create metadata
            metadata = {
                'doc_id': str(uuid.uuid4()),
                'filename': secure_filename(Path(self.full_path).name if self.full_path else 'image_file'),
                'doc_type': 'image',
                'tags': ['visual', 'diagram', 'drawing']
            }

            # Process image with OCR
            extracted_text = ""
            patterns_found = []

            try:
                # Initialize OCR engine
                ocr = EngineeringOCR()

                # Save bytes to temp file for OCR processing
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=Path(self.full_path).suffix, delete=False) as tmp:
                    tmp.write(self.file_bytes)
                    tmp_path = tmp.name

                # Run OCR
                ocr_results = ocr.process_image(tmp_path)

                # Extract text
                if ocr_results.get('text'):
                    extracted_text = ocr_results['text']

                # Extract patterns
                if ocr_results.get('patterns'):
                    patterns_found = list(ocr_results['patterns'].keys())
                    metadata['patterns'] = patterns_found

                # Add to tags based on patterns
                if 'part_numbers' in patterns_found:
                    metadata['tags'].append('part_numbers')
                if 'dimensions' in patterns_found:
                    metadata['tags'].append('technical_drawing')

                # Clean up temp file
                import os
                os.unlink(tmp_path)

            except Exception as e:
                logger.warning(f"OCR processing failed: {e}, using basic metadata")
                extracted_text = f"Image file: {metadata['filename']}"

            # Return parsed sections
            sections = []

            # Add main content section
            sections.append({
                'section_number': '1',
                'title': 'Image Content',
                'text': extracted_text if extracted_text else f"Image file: {metadata['filename']}",
                'metadata': metadata,
                'full_text': extracted_text if extracted_text else f"Image file: {metadata['filename']}"
            })

            # Add patterns section if found
            if patterns_found:
                sections.append({
                    'section_number': '2',
                    'title': 'Detected Patterns',
                    'text': f"Technical patterns detected: {', '.join(patterns_found)}",
                    'metadata': metadata,
                    'full_text': f"Technical patterns detected: {', '.join(patterns_found)}"
                })

            return sections

        except Exception as e:
            logger.error(f"Error parsing image file: {e}")
            import uuid
            metadata = {
                'doc_id': str(uuid.uuid4()),
                'filename': secure_filename(Path(self.full_path).name if self.full_path else 'image_file'),
                'doc_type': 'image',
                'tags': ['visual']
            }
            return [{
                'section_number': '1',
                'title': 'Image Metadata',
                'text': f"Image file: {metadata['filename']} (OCR failed)",
                'metadata': metadata,
                'full_text': f"Image file: {metadata['filename']}"
            }]

class JSONParser(DocumentParser):
    """Parser for JSON files (e.g., .json metadata files).

    Handles CAD metadata sidecars and other JSON configuration files.
    Compliance: SWE-013
    """
    def parse(self) -> List[Dict[str, Any]]:
        """Extract content from JSON files."""
        try:
            import json
            import uuid

            # Parse JSON content
            json_data = json.loads(self.file_bytes.decode('utf-8'))

            # Create metadata
            metadata = {
                'doc_id': str(uuid.uuid4()),
                'filename': secure_filename(Path(self.full_path).name if self.full_path else 'json_file'),
                'doc_type': 'json',
                'tags': ['metadata', 'configuration']
            }

            # Extract meaningful content
            content_parts = []

            # Handle CAD metadata files specifically
            if self.full_path and '.meta.json' in self.full_path:
                metadata['tags'].extend(['cad_metadata', 'sidecar'])
                if 'original_path' in json_data:
                    content_parts.append(f"Original path: {json_data['original_path']}")
                if 'size' in json_data:
                    content_parts.append(f"File size: {json_data['size']} bytes")
                if 'extension' in json_data:
                    content_parts.append(f"File type: {json_data['extension']}")
                if 'category' in json_data:
                    content_parts.append(f"Category: {json_data['category']}")
            else:
                # Generic JSON handling
                for key, value in json_data.items():
                    if isinstance(value, (str, int, float)):
                        content_parts.append(f"{key}: {value}")
                    elif isinstance(value, (list, dict)):
                        content_parts.append(f"{key}: {str(value)[:200]}...")

            # Create content text
            if content_parts:
                content_text = "\n".join(content_parts)
            else:
                content_text = f"JSON file: {metadata['filename']}"

            return [{
                'section_number': '1',
                'title': 'JSON Content',
                'text': content_text,
                'metadata': metadata,
                'full_text': content_text
            }]

        except Exception as e:
            logger.error(f"Error parsing JSON file: {e}")
            import uuid
            metadata = {
                'doc_id': str(uuid.uuid4()),
                'filename': secure_filename(Path(self.full_path).name if self.full_path else 'json_file'),
                'doc_type': 'json',
                'tags': ['metadata']
            }
            return [{
                'section_number': '1',
                'title': 'JSON Metadata',
                'text': f"JSON file: {metadata['filename']} (parsing failed)",
                'metadata': metadata,
                'full_text': f"JSON file: {metadata['filename']}"
            }]

def get_parser(file_path: str, file_bytes: Optional[bytes] = None, doc_type: Optional[str] = None) -> DocumentParser:
    """Factory function to get appropriate parser for file type."""
    try:
        ext = Path(file_path).suffix.lower()
        
        if ext == '.docx':
            return DocxParser(file_path, file_bytes, doc_type)
        elif ext == '.pdf':
            return PdfParser(file_path, file_bytes, doc_type)
        elif ext in ['.xlsx', '.xls']:
            return ExcelParser(file_path, file_bytes, doc_type)
        elif ext in ['.pptx', '.ppt']:
            return PowerPointParser(file_path, file_bytes, doc_type)
        elif ext in ['.md', '.markdown']:
            return MarkdownParser(file_path, file_bytes, doc_type)
        elif ext in ['.txt', '.log']:
            return TextParser(file_path, file_bytes, doc_type)
        elif ext in ['.dwg', '.dxf', '.cad']:
            return CadParser(file_path, file_bytes, doc_type)
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif']:
            return ImageParser(file_path, file_bytes, doc_type)
        elif ext in ['.json']:
            return JSONParser(file_path, file_bytes, doc_type)
        else:
            logger.warning(f"Unknown file type {ext}, using text parser")
            return TextParser(file_path, file_bytes, doc_type)
    
    except Exception as e:
        logger.error(f"Error creating parser for {file_path}: {e}")
        return TextParser(file_path, file_bytes, doc_type)
