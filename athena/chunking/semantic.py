#!/usr/bin/env python3
"""
Module: Semantic
Purpose: Semantic chunking that respects document structure.

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

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Section:
    """Represents a document section.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    number: str
    title: str
    text: str
    depth: int
    parent: Optional[str] = None
    
class SemanticChunker:
    """Chunk documents by semantic boundaries, not fixed sizes.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    
    def __init__(self, 
                 max_chunk_size: int = 1000,  # words
                 min_chunk_size: int = 100,   # words
                 overlap_size: int = 50):     # words
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap_size = overlap_size
        
    def chunk_document(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Chunk a document while preserving semantic structure.
        
        Returns list of chunk dictionaries with metadata.
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        # Special handling for policy documents
        doc_id = metadata.get('doc_id', '')
        doc_type = metadata.get('doc_type', '')
        
        # Force section detection for policy documents
        if 'POL' in doc_id or doc_type in ['policy', 'hr_policy', 'regulation']:
            # Try harder to detect sections for policies
            sections = self._detect_policy_sections(text)
            if sections:
                return self._chunk_by_sections(sections, metadata)
        
        # Try normal section detection
        sections = self._detect_sections(text)
        
        if sections:
            # Use section-based chunking
            return self._chunk_by_sections(sections, metadata)
        else:
            # Fall back to paragraph-based chunking
            return self._chunk_by_paragraphs(text, metadata)
    
    def _detect_sections(self, text: str) -> List[Section]:
        """Detect section structure in document.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        sections = []
        
        # Common section patterns - updated to be more flexible
        patterns = [
            # Numbered sections: "3.3.3 Title" or "3.3.3. Title" or just "3.3.3"
            (r'^(\d+(?:\.\d+)*\.?)\s*(.*)$', 'numbered'),
            # Letter sections: "A. Title" or "(A) Title"
            (r'^(?:\()?([A-Z])\)?\.\s+(.+?)$', 'letter'),
            # Roman numerals: "III. Title"
            (r'^([IVX]+)\.\s+(.+?)$', 'roman'),
            # Markdown headers: "### Title"
            (r'^(#+)\s+(.+?)$', 'markdown'),
        ]
        
        lines = text.split('\n')
        current_section = None
        section_text = []
        
        for line in lines:
            # Check if this line is a section header
            is_header = False
            for pattern, style in patterns:
                match = re.match(pattern, line.strip())
                if match:
                    # Save previous section if exists
                    if current_section and section_text:
                        current_section.text = '\n'.join(section_text).strip()
                        if current_section.text:  # Only add non-empty sections
                            sections.append(current_section)
                    
                    # Start new section
                    if style == 'numbered':
                        number = match.group(1).rstrip('.')
                        title = match.group(2)
                        depth = len(number.split('.'))
                        parent = '.'.join(number.split('.')[:-1]) if depth > 1 else None
                    elif style == 'markdown':
                        number = str(len(sections) + 1)
                        title = match.group(2)
                        depth = len(match.group(1))
                        parent = None
                    else:
                        number = match.group(1)
                        title = match.group(2)
                        depth = 1
                        parent = None
                    
                    current_section = Section(
                        number=number,
                        title=title,
                        text='',
                        depth=depth,
                        parent=parent
                    )
                    section_text = []
                    is_header = True
                    break
            
            if not is_header and current_section:
                section_text.append(line)
        
        # Save last section
        if current_section and section_text:
            current_section.text = '\n'.join(section_text).strip()
            if current_section.text:
                sections.append(current_section)
        
        return sections
    
    def _detect_policy_sections(self, text: str) -> List[Section]:
        """Enhanced section detection specifically for policy documents.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        sections = []
        
        # More aggressive patterns for policies
        lines = text.split('\n')
        current_section = None
        section_text = []
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check if this looks like a section number at the start of a line
            # Match patterns like "3.3.3" or "3.3.3." or "3.3.3 Something"
            section_match = re.match(r'^(\d+(?:\.\d+)*\.?)\s*(.*)$', stripped)
            
            if section_match:
                section_num = section_match.group(1).rstrip('.')
                remainder = section_match.group(2).strip()
                
                # Check if this is likely a section header
                # - Line is short (likely a header)
                # - Next line is not another number
                # - Or remainder looks like a title
                is_section = False
                
                if len(stripped) < 100:  # Short line, likely a header
                    # Check next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        # If next line doesn't start with a number, this is likely a section
                        if not re.match(r'^\d+(?:\.\d+)*\.?\s', next_line):
                            is_section = True
                    else:
                        is_section = True
                
                # Also check if remainder looks like a title
                if remainder and len(remainder) < 100 and not remainder[0].islower():
                    is_section = True
                
                if is_section:
                    # Save previous section
                    if current_section and section_text:
                        current_section.text = '\n'.join(section_text).strip()
                        if current_section.text:
                            sections.append(current_section)
                    
                    # Start new section
                    depth = len(section_num.split('.'))
                    parent = '.'.join(section_num.split('.')[:-1]) if depth > 1 else None
                    
                    current_section = Section(
                        number=section_num,
                        title=remainder or f"Section {section_num}",
                        text='',
                        depth=depth,
                        parent=parent
                    )
                    section_text = []
                    continue
            
            # Add line to current section
            if current_section:
                section_text.append(line)
        
        # Save last section
        if current_section and section_text:
            current_section.text = '\n'.join(section_text).strip()
            if current_section.text:
                sections.append(current_section)
        
        # If we didn't find many sections, try a different approach
        if len(sections) < 5:
            # Look for sections in the format "Section 3.3.3"
            alt_sections = self._detect_sections(text)
            if len(alt_sections) > len(sections):
                return alt_sections
        
        return sections
    
    def _chunk_by_sections(self, sections: List[Section], metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create chunks based on document sections.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        chunks = []
        
        for section in sections:
            section_words = section.text.split()
            
            # If section is small enough, keep it as one chunk
            if len(section_words) <= self.max_chunk_size:
                chunk_metadata = metadata.copy()
                chunk_metadata.update({
                    'section_number': section.number,
                    'section_title': section.title,
                    'section_depth': section.depth,
                    'parent_section': section.parent,
                    'chunk_type': 'section',
                    'chunk_id': 0,
                    'total_chunks': 1
                })
                
                chunks.append({
                    'text': section.text,
                    **chunk_metadata
                })
            else:
                # Split large sections into sub-chunks
                sub_chunks = self._split_section(section, metadata)
                chunks.extend(sub_chunks)
        
        return chunks
    
    def _split_section(self, section: Section, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Split a large section into smaller chunks while preserving context.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        chunks = []
        text = section.text
        
        # Try to split by paragraphs first
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        current_chunk = []
        current_size = 0
        chunk_id = 0
        
        for para in paragraphs:
            para_words = para.split()
            para_size = len(para_words)
            
            # If this paragraph alone is too large, split it
            if para_size > self.max_chunk_size:
                # Save current chunk if any
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append(self._create_chunk(
                        chunk_text, section, metadata, chunk_id, -1
                    ))
                    chunk_id += 1
                    current_chunk = []
                    current_size = 0
                
                # Split the large paragraph
                para_chunks = self._split_paragraph(para, section, metadata, chunk_id)
                chunks.extend(para_chunks)
                chunk_id += len(para_chunks)
            
            # If adding this paragraph would exceed limit, start new chunk
            elif current_size + para_size > self.max_chunk_size:
                # Save current chunk
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append(self._create_chunk(
                        chunk_text, section, metadata, chunk_id, -1
                    ))
                    chunk_id += 1
                
                # Start new chunk with this paragraph
                current_chunk = [para]
                current_size = para_size
            
            # Add paragraph to current chunk
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # Save final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append(self._create_chunk(
                chunk_text, section, metadata, chunk_id, -1
            ))
        
        # Update total chunks count
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk['total_chunks'] = total_chunks
        
        return chunks
    
    def _split_paragraph(self, paragraph: str, section: Section, 
                        metadata: Dict[str, Any], start_id: int) -> List[Dict[str, Any]]:
        """Split a large paragraph into chunks.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        chunks = []
        words = paragraph.split()
        
        for i in range(0, len(words), self.max_chunk_size - self.overlap_size):
            chunk_words = words[i:i + self.max_chunk_size]
            chunk_text = ' '.join(chunk_words)
            
            chunks.append(self._create_chunk(
                chunk_text, section, metadata, start_id + len(chunks), -1
            ))
        
        return chunks
    
    def _create_chunk(self, text: str, section: Section, metadata: Dict[str, Any],
                     chunk_id: int, total_chunks: int) -> Dict[str, Any]:
        """Create a chunk with full metadata.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        chunk_metadata = metadata.copy()
        chunk_metadata.update({
            'text': text,
            'section_number': section.number,
            'section_title': section.title,
            'section_depth': section.depth,
            'parent_section': section.parent,
            'chunk_type': 'section_part',
            'chunk_id': chunk_id,
            'total_chunks': total_chunks
        })
        
        return chunk_metadata
    
    def _chunk_by_paragraphs(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback: chunk by paragraphs when no clear structure.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        chunks = []
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        current_chunk = []
        current_size = 0
        chunk_id = 0
        
        for para in paragraphs:
            para_words = para.split()
            para_size = len(para_words)
            
            if current_size + para_size > self.max_chunk_size and current_chunk:
                # Save current chunk
                chunk_text = '\n\n'.join(current_chunk)
                chunk_metadata = metadata.copy()
                chunk_metadata.update({
                    'text': chunk_text,
                    'chunk_type': 'paragraph',
                    'chunk_id': chunk_id,
                })
                chunks.append(chunk_metadata)
                
                chunk_id += 1
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # Save final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunk_metadata = metadata.copy()
            chunk_metadata.update({
                'text': chunk_text,
                'chunk_type': 'paragraph',
                'chunk_id': chunk_id,
            })
            chunks.append(chunk_metadata)
        
        # Update total chunks
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk['total_chunks'] = total_chunks
        
        return chunks


def semantic_chunk(text: str, metadata: Dict[str, Any] = None, 
                  max_chunk_size: int = 1000, debug: bool = False) -> List[Dict[str, Any]]:
    """
    Convenience function for semantic chunking.
    
    Args:
        text: Document text to chunk
        metadata: Document metadata to preserve
        max_chunk_size: Maximum chunk size in words
        
    Returns:
        List of chunk dictionaries with text and metadata
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    chunker = SemanticChunker(max_chunk_size=max_chunk_size)
    chunks = chunker.chunk_document(text, metadata or {})
    
    if debug and metadata:
        doc_id = metadata.get('doc_id', 'Unknown')
        logger.info(f"[Semantic Chunking] {doc_id}:")
        logger.info(f"  Original size: {len(text.split())} words")
        logger.info(f"  Created {len(chunks)} chunks")
        for i, chunk in enumerate(chunks[:5]):  # Show first 5
            section = chunk.get('section_number', chunk.get('section', 'N/A'))
            words = len(chunk.get('text', '').split())
            logger.info(f"  Chunk {i}: Section {section}, {words} words")
    
    return chunks