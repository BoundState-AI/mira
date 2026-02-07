#!/usr/bin/env python3
"""
Module: Structured
Purpose: BoundState AI - Structured Document Parser

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Safety Critical: False
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import re
from pathlib import Path
import logging
import warnings

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from .config import CONFIG

# OCR imports - made optional to avoid breaking system when not available
try:
    from pdf2image import convert_from_path
    import pytesseract  
except ImportError:
    convert_from_path = None
    pytesseract = None

logger = logging.getLogger(__name__)

@dataclass
class Section:
    """A document section with hierarchy and location.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    doc_id: str
    section_path: str  # "1.2.3" or "Introduction.Setup"
    heading: str
    text: str
    page_span: Tuple[int, int]  # (start_page, end_page)
    level: int  # Heading level 1-6
    tags: List[str]
    cross_refs: List[str]  # References to other sections/docs

@dataclass
class Table:
    """A structured table with searchable text.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    doc_id: str
    table_id: str
    caption: str
    headers: List[str]
    rows: List[List[str]]
    extracted_text: str  # Flattened searchable version
    page: int
    bbox: Optional[Tuple[float, float, float, float]]  # (x0, y0, x1, y1)

@dataclass
class Figure:
    """A figure or image with caption.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    doc_id: str
    figure_id: str
    caption: str
    page: int
    bbox: Optional[Tuple[float, float, float, float]]
    extracted_text: str  # OCR text if available

@dataclass
class CrossRef:
    """A cross-reference to another document or section.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    source_doc: str
    source_section: str
    target_id: str  # Could be doc ID or section path
    ref_type: str  # "refers_to", "defines", "updates", "see_also"
    text: str  # The referencing text

@dataclass
class DocumentStructure:
    """Complete structured representation of a document.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    doc_id: str
    title: str
    sections: List[Section]
    tables: List[Table]
    figures: List[Figure]
    cross_refs: List[CrossRef]
    metadata: Dict[str, Any]
    total_pages: int

class StructuredDocumentParser:
    """Layout-aware document parser that preserves structure.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    
    def __init__(self, extract_images: bool = False):
        self.extract_images = extract_images
        self.heading_patterns = [
            r'^(\d+(?:\.\d+)*)\s+(.+)$',  # "1.2.3 Title"
            r'^([A-Z]+)\.\s+(.+)$',       # "A. Title"
            r'^([IVX]+)\.\s+(.+)$',       # "III. Title"
        ]
        self.cross_ref_patterns = [
            r'(?:see|refer to|per|according to|as defined in)\s+(?:section\s+)?([A-Z0-9\.-]+)',
            r'([A-Z]{2,}\d+(?:\.\d+)*(?:\s+REV\s+[A-Z])?)',  # Document IDs like "F1301.1 REV F"
            r'\(([A-Z0-9\.-]+)\)',  # References in parentheses
        ]
    
    def parse(self, file_path: str) -> DocumentStructure:
        """Parse a document and return structured representation.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        doc_id = file_path.stem
        
        if file_path.suffix.lower() == '.pdf':
            return self._parse_pdf(file_path, doc_id)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")
    
    def _parse_pdf(self, file_path: Path, doc_id: str) -> DocumentStructure:
        """Parse PDF with structure preservation and error handling.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if not pdfplumber:
            raise ImportError("pdfplumber required for PDF parsing: pip install pdfplumber")
        
        sections = []
        tables = []
        figures = []
        cross_refs = []
        title = ""
        parse_errors = []
        total_pages = 0
        
        # Suppress pdfminer warnings about invalid float values  
        warnings.filterwarnings("ignore", message="Cannot set gray non-stroke color because.*is an invalid float value", module="pdfminer.pdfinterp")
        
        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                full_text = ''
                
                # Extract title from first page
                if pdf.pages:
                    try:
                        first_page_text = pdf.pages[0].extract_text() or ""
                        title = self._extract_title(first_page_text, doc_id)
                    except Exception as e:
                        logger.warning(f"Failed to extract title from page 1: {e}")
                        parse_errors.append(f"Title extraction: {str(e)}")
                        title = doc_id
                
                current_section = None
                current_text_buffer = []
                all_text = []  # Track if we got any text at all
                
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        page_text = page.extract_text() or ""
                        all_text.append(page_text)
                        full_text += page_text + '\n'
                        
                        # Extract tables from this page
                        try:
                            page_tables = self._extract_tables_from_page(page, doc_id, page_num)
                            tables.extend(page_tables)
                            # Add table text to full_text for counting
                            for table in page_tables:
                                full_text += table.extracted_text + '\n'
                        except Exception as e:
                            logger.warning(f"Failed to extract tables from page {page_num}: {e}")
                            parse_errors.append(f"Page {page_num} tables: {str(e)}")
                        
                        # Extract figures/images if enabled
                        if self.extract_images or CONFIG.get('use_ocr_for_figures', False):
                            try:
                                page_figures = self._extract_figures_from_page(page, doc_id, page_num)
                                figures.extend(page_figures)
                                # Add figure text to full_text for counting
                                for figure in page_figures:
                                    if figure.extracted_text:
                                        full_text += figure.extracted_text + '\n'
                            except Exception as e:
                                logger.warning(f"Failed to extract figures from page {page_num}: {e}")
                                parse_errors.append(f"Page {page_num} figures: {str(e)}")
                        
                        # Process text line by line for sections and cross-refs
                        lines = page_text.split('\n')
                        
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            # Check if this line is a heading
                            heading_match = self._match_heading(line)
                            if heading_match:
                                # Save previous section if exists
                                if current_section:
                                    current_section.text = '\n'.join(current_text_buffer).strip()
                                    current_section.page_span = (current_section.page_span[0], page_num)
                                    sections.append(current_section)
                                
                                # Start new section
                                section_path, heading_text, level = heading_match
                                current_section = Section(
                                    doc_id=doc_id,
                                    section_path=section_path,
                                    heading=heading_text,
                                    text="",
                                    page_span=(page_num, page_num),
                                    level=level,
                                    tags=[],
                                    cross_refs=[]
                                )
                                current_text_buffer = []
                            else:
                                # Add to current section
                                current_text_buffer.append(line)
                                
                                # Extract cross-references from this line
                                try:
                                    line_cross_refs = self._extract_cross_refs(line, doc_id, current_section.section_path if current_section else "")
                                    cross_refs.extend(line_cross_refs)
                                    
                                    if current_section:
                                        current_section.cross_refs.extend([ref.target_id for ref in line_cross_refs])
                                except Exception as e:
                                    logger.warning(f"Failed to extract cross-refs from line: {e}")
                                    parse_errors.append(f"Cross-ref extraction: {str(e)}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract page {page_num}: {e}")
                        parse_errors.append(f"Page {page_num}: {str(e)}")
                        continue
                
                # Save final section
                if current_section:
                    current_section.text = '\n'.join(current_text_buffer).strip()
                    current_section.page_span = (current_section.page_span[0], total_pages)
                    sections.append(current_section)
                
                # Check if we got any meaningful text - OCR fallback
                all_text_combined = '\n'.join(all_text).strip()
                if not all_text_combined and convert_from_path and pytesseract:
                    logger.info(f"No text extracted from {file_path}, attempting OCR...")
                    try:
                        ocr_result = self._extract_with_ocr(file_path)
                        if ocr_result:
                            # Create a single section from OCR text
                            sections = [Section(
                                doc_id=doc_id,
                                section_path="OCR_TEXT",
                                heading="OCR Extracted Text",
                                text=ocr_result,
                                page_span=(1, total_pages),
                                level=1,
                                tags=["ocr"],
                                cross_refs=[]
                            )]
                            parse_errors.append("Used OCR for text extraction")
                    except Exception as e:
                        logger.error(f"OCR extraction failed: {e}")
                        parse_errors.append(f"OCR failed: {str(e)}")
                
        except Exception as e:
            logger.error(f"Failed to open or process PDF {file_path}: {e}")
            # Return minimal structure with error
            return DocumentStructure(
                doc_id=doc_id,
                title=f"ERROR: {doc_id}",
                sections=[],
                tables=[],
                figures=[],
                cross_refs=[],
                metadata={
                    'file_path': str(file_path),
                    'parse_errors': [f"Fatal error: {str(e)}"],
                    'parser_version': '1.0'
                },
                total_pages=0
            )
        
        # Add full_text to all sections for counting
        for section in sections:
            if not hasattr(section, 'full_text'):
                section.full_text = full_text
        
        # Create document structure with error tracking
        metadata = {
            'file_path': str(file_path),
            'total_pages': total_pages,
            'parser_version': '1.0',
            'full_text': full_text  # Include full_text in metadata for counting
        }
        
        if parse_errors:
            metadata['parse_errors'] = parse_errors
            logger.info(f"Parsing completed with {len(parse_errors)} warnings for {doc_id}")
        
        return DocumentStructure(
            doc_id=doc_id,
            title=title,
            sections=sections,
            tables=tables,
            figures=figures,
            cross_refs=cross_refs,
            metadata=metadata,
            total_pages=total_pages
        )
    
    def _extract_title(self, first_page_text: str, doc_id: str) -> str:
        """Extract document title from first page.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        lines = first_page_text.split('\n')
        
        # Look for title patterns
        for line in lines[:10]:  # Check first 10 lines
            line = line.strip()
            if len(line) > 10 and len(line) < 100:  # Reasonable title length
                if not re.match(r'^\d+', line):  # Not starting with numbers
                    return line
        
        return doc_id  # Fallback to filename
    
    def _match_heading(self, line: str) -> Optional[Tuple[str, str, int]]:
        """Check if line is a heading, return (section_path, text, level).

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        for i, pattern in enumerate(self.heading_patterns):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                section_path = match.group(1)
                heading_text = match.group(2).strip()
                
                # Determine level based on section numbering
                level = len(section_path.split('.')) if '.' in section_path else 1
                
                return section_path, heading_text, level
        
        # Check for simple uppercase headings (often used in policies)
        if len(line) < 50 and line.isupper() and not re.search(r'\d{3,}', line):
            return line, line, 1
        
        return None
    
    def _extract_tables_from_page(self, page, doc_id: str, page_num: int) -> List[Table]:
        """Extract tables from a single page.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        tables = []
        
        try:
            page_tables = page.extract_tables()
            
            for i, table_data in enumerate(page_tables):
                if not table_data or len(table_data) < 2:  # Skip empty or single-row tables
                    continue
                
                table_id = f"{doc_id}_p{page_num}_t{i+1}"
                
                # Smart header detection instead of assuming first row
                headers, rows = self._detect_table_headers(table_data)
                
                # Create searchable text version
                extracted_text = self._table_to_text(headers, rows)
                
                # Look for table caption (check text above table)
                caption = self._find_table_caption(page, page_num, i)
                
                table = Table(
                    doc_id=doc_id,
                    table_id=table_id,
                    caption=caption,
                    headers=headers,
                    rows=rows,
                    extracted_text=extracted_text,
                    page=page_num,
                    bbox=None  # Could add bbox detection here
                )
                
                tables.append(table)
                
        except Exception as e:
            logger.warning(f"Failed to extract tables from page {page_num}: {e}")
        
        return tables
    
    def _detect_table_headers(self, table_data: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
        """Detect table headers using heuristics instead of assuming first row.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if not table_data:
            return [], []
        
        if len(table_data) == 1:
            # Single row - treat as headers
            headers = [str(cell).strip() if cell else "" for cell in table_data[0]]
            return headers, []
        
        first_row = table_data[0]
        second_row = table_data[1] if len(table_data) > 1 else []
        
        # Apply heuristics to determine if first row is headers
        if self._looks_like_headers(first_row, second_row):
            headers = [str(cell).strip() if cell else "" for cell in first_row]
            rows = []
            for row in table_data[1:]:
                clean_row = [str(cell).strip() if cell else "" for cell in row]
                rows.append(clean_row)
            return headers, rows
        else:
            # No clear headers, generate generic ones
            if first_row:
                headers = [f"Column {i+1}" for i in range(len(first_row))]
            else:
                headers = []
            
            rows = []
            for row in table_data:
                clean_row = [str(cell).strip() if cell else "" for cell in row]
                rows.append(clean_row)
            return headers, rows
    
    def _looks_like_headers(self, first_row: List[str], second_row: List[str]) -> bool:
        """Determine if first row looks like headers based on content patterns.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if not first_row:
            return False
        
        if not second_row:
            return True  # Only one data row, assume first is headers
        
        # Convert to strings for analysis
        first_cells = [str(cell).strip() for cell in first_row if cell]
        second_cells = [str(cell).strip() for cell in second_row if cell]
        
        if not first_cells or not second_cells:
            return True  # Default to treating first row as headers
        
        # Heuristic 1: Headers are usually shorter than data
        avg_first_len = sum(len(cell) for cell in first_cells) / len(first_cells)
        avg_second_len = sum(len(cell) for cell in second_cells) / len(second_cells)
        
        if avg_first_len < avg_second_len * 0.6:  # Headers much shorter
            return True
        
        # Heuristic 2: Headers often don't contain numbers, data does
        first_has_numbers = any(re.search(r'\b\d{2,}\b', cell) for cell in first_cells)
        second_has_numbers = any(re.search(r'\b\d{2,}\b', cell) for cell in second_cells)
        
        if not first_has_numbers and second_has_numbers:
            return True
        
        # Heuristic 3: Headers often contain common header words
        header_words = {'name', 'type', 'description', 'value', 'id', 'number', 'date', 
                       'status', 'item', 'part', 'spec', 'requirement', 'section',
                       'title', 'category', 'code', 'ref', 'reference'}
        
        first_text_lower = ' '.join(first_cells).lower()
        header_word_count = sum(1 for word in header_words if word in first_text_lower)
        
        if header_word_count >= 2:  # Contains multiple header-like words
            return True
        
        # Heuristic 4: Check for formatting patterns (ALL CAPS, Title Case)
        first_formatted = sum(1 for cell in first_cells 
                             if cell.isupper() or cell.istitle())
        second_formatted = sum(1 for cell in second_cells 
                              if cell.isupper() or cell.istitle())
        
        if len(first_cells) > 0 and first_formatted / len(first_cells) > 0.5:
            if len(second_cells) == 0 or second_formatted / len(second_cells) < 0.3:
                return True
        
        # Heuristic 5: Headers often don't contain units or measurements
        unit_patterns = [r'\b\d+\s*(mm|cm|in|ft|kg|lbs|°[CF]|%|\$)\b', 
                        r'\b\d+\.\d+\b',  # Decimal numbers
                        r'\b\d+/\d+\b']    # Fractions
        
        first_has_units = any(re.search(pattern, ' '.join(first_cells), re.IGNORECASE) 
                             for pattern in unit_patterns)
        second_has_units = any(re.search(pattern, ' '.join(second_cells), re.IGNORECASE) 
                              for pattern in unit_patterns)
        
        if not first_has_units and second_has_units:
            return True
        
        # Default: if no strong indicators, assume first row is headers
        # This is safer for most business documents
        return True

    def _table_to_text(self, headers: List[str], rows: List[List[str]]) -> str:
        """Convert table to searchable text format.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        text_parts = []
        
        # Add headers
        if headers:
            text_parts.append("Headers: " + " | ".join(headers))
        
        # Add key rows (limit to avoid too much noise)
        for i, row in enumerate(rows[:10]):  # First 10 rows
            if any(cell.strip() for cell in row):  # Skip empty rows
                row_text = " | ".join(row)
                text_parts.append(f"Row {i+1}: {row_text}")
        
        return "\n".join(text_parts)
    
    def _find_table_caption(self, page, page_num: int, table_index: int) -> str:
        """Attempt to find table caption.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        # This is a simplified approach - could be enhanced with bbox detection
        page_text = page.extract_text() or ""
        
        # Look for "Table" patterns
        table_patterns = [
            r'Table\s+\d+[:\-\s]+(.+)',
            r'TABLE\s+\d+[:\-\s]+(.+)',
            r'Tab\.\s+\d+[:\-\s]+(.+)'
        ]
        
        for pattern in table_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE | re.MULTILINE)
            if matches and table_index < len(matches):
                return matches[table_index].strip()
        
        return f"Table {table_index + 1}"
    
    def _extract_figures_from_page(self, page, doc_id: str, page_num: int) -> List[Figure]:
        """Extract figures/images from page (placeholder implementation).

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        figures = []
        
        # This would require more sophisticated image detection
        # For now, just look for figure captions in text
        page_text = page.extract_text() or ""
        
        figure_patterns = [
            r'Figure\s+(\d+)[:\-\s]+(.+)',
            r'FIGURE\s+(\d+)[:\-\s]+(.+)',
            r'Fig\.\s+(\d+)[:\-\s]+(.+)'
        ]
        
        for pattern in figure_patterns:
            matches = re.finditer(pattern, page_text, re.IGNORECASE | re.MULTILINE)
            
            for i, match in enumerate(matches):
                figure_id = f"{doc_id}_p{page_num}_f{i+1}"
                caption = match.group(2).strip()
                
                figure = Figure(
                    doc_id=doc_id,
                    figure_id=figure_id,
                    caption=caption,
                    page=page_num,
                    bbox=None,
                    extracted_text=caption  # Could add OCR here
                )
                
                figures.append(figure)
        
        return figures
    
    def _extract_cross_refs(self, line: str, doc_id: str, current_section: str) -> List[CrossRef]:
        """Extract cross-references from a text line.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        cross_refs = []
        
        for pattern in self.cross_ref_patterns:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            
            for match in matches:
                target_id = match.group(1)
                
                # Skip if it's just the current document
                if target_id == doc_id:
                    continue
                
                # Normalize document IDs
                normalized_target = self._normalize_doc_id(target_id)
                
                cross_ref = CrossRef(
                    source_doc=doc_id,
                    source_section=current_section,
                    target_id=normalized_target,
                    ref_type="refers_to",
                    text=match.group(0)
                )
                
                cross_refs.append(cross_ref)
        
        return cross_refs
    
    def _normalize_doc_id(self, doc_id: str) -> str:
        """Normalize document ID for consistent matching.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        # Remove extra spaces and standardize format
        normalized = re.sub(r'\s+', ' ', doc_id.strip())
        
        # Convert "REV F" to "F" format
        normalized = re.sub(r'\s+REV\s+([A-Z])', r'\1', normalized, flags=re.IGNORECASE)
        
        return normalized.upper()
    
    def _extract_with_ocr(self, file_path: Path) -> str:
        """Extract text using OCR for scanned PDFs.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if not convert_from_path or not pytesseract:
            logger.warning("OCR dependencies not available (pdf2image, pytesseract)")
            return ""
        
        try:
            # Convert PDF pages to images
            images = convert_from_path(str(file_path), dpi=150)
            
            ocr_text_parts = []
            for i, image in enumerate(images[:10]):  # Limit to first 10 pages for performance
                try:
                    # Extract text from image
                    page_text = pytesseract.image_to_string(image, lang='eng')
                    if page_text.strip():
                        ocr_text_parts.append(f"--- Page {i+1} ---\\n{page_text.strip()}")
                except Exception as e:
                    logger.warning(f"OCR failed for page {i+1}: {e}")
                    continue
            
            if ocr_text_parts:
                return "\\n\\n".join(ocr_text_parts)
            else:
                return ""
                
        except Exception as e:
            logger.error(f"OCR extraction failed for {file_path}: {e}")
            return ""


def main():
    """Test the parser.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python structured_parser.py <pdf_file>")
        sys.exit(1)
    
    parser = StructuredDocumentParser()
    
    try:
        doc_structure = parser.parse(sys.argv[1])
        
        print(f"Parsed: {doc_structure.title}")
        print(f"Sections: {len(doc_structure.sections)}")
        print(f"Tables: {len(doc_structure.tables)}")
        print(f"Figures: {len(doc_structure.figures)}")
        print(f"Cross-refs: {len(doc_structure.cross_refs)}")
        
        # Show first few sections
        for i, section in enumerate(doc_structure.sections[:3]):
            print(f"\nSection {i+1}: {section.section_path} - {section.heading}")
            print(f"  Pages: {section.page_span}")
            print(f"  Text preview: {section.text[:100]}...")
        
        # Show tables
        for i, table in enumerate(doc_structure.tables[:2]):
            print(f"\nTable {i+1}: {table.table_id}")
            print(f"  Caption: {table.caption}")
            print(f"  Headers: {table.headers}")
            print(f"  Rows: {len(table.rows)}")
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()