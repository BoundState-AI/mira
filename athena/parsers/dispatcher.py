#!/usr/bin/env python3
"""
Module: Dispatcher
Purpose: import logging

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

import logging
from pathlib import Path
from typing import Optional, Dict, Any

# Import original BoundState parser
from boundstate.parsers import get_parser as boundstate_get_parser, DocumentParser

# Import enhanced CAD parser
try:
    from EM32.enhanced_cad_parser import EnhancedCADParser
    ENHANCED_CAD_AVAILABLE = True
except ImportError:
    EnhancedCADParser = None
    ENHANCED_CAD_AVAILABLE = False

logger = logging.getLogger(__name__)

# CAD file extensions that benefit from enhanced parsing
ENHANCED_CAD_EXTENSIONS = {
    '.par',      # SolidWorks parts - 58,884 files
    '.asm',      # Assembly files - 11,331 files
    '.igs',      # IGES CAD files - 7,532 files
    '.iges',     # IGES alternate extension
    '.1',        # CAD revisions - 14,783 files
    '.2',        # CAD revisions
    '.3',        # CAD revisions
    '.4',        # CAD revisions
    '.5',        # CAD revisions
    '.dat',      # Data files - 16,790 files
    '.raww'      # Raw engineering data - 11,000 files
}

def get_enhanced_parser(file_path: str, file_bytes: Optional[bytes] = None,
                       doc_type: Optional[str] = None) -> DocumentParser:
    """
    Enhanced parser dispatcher that extends BoundState's parser system.

    Args:
        file_path: Path to file
        file_bytes: Optional file content bytes
        doc_type: Optional document type hint

    Returns:
        DocumentParser instance (enhanced or original)
    """
    try:
        ext = Path(file_path).suffix.lower()

        # Use enhanced CAD parser for supported engineering file types
        if ext in ENHANCED_CAD_EXTENSIONS and ENHANCED_CAD_AVAILABLE:
            logger.debug(f"Using enhanced CAD parser for {ext} file: {file_path}")
            return EnhancedCADParser(file_path, file_bytes, doc_type)

        # For all other file types, use original BoundState parser
        else:
            return boundstate_get_parser(file_path, file_bytes, doc_type)

    except Exception as e:
        logger.error(f"Enhanced parser dispatcher failed for {file_path}: {e}")
        # Fallback to original parser
        return boundstate_get_parser(file_path, file_bytes, doc_type)

def get_parser_info(file_path: str) -> Dict[str, Any]:
    """
    Get information about which parser would be used for a file.

    Args:
        file_path: Path to file

    Returns:
        Dictionary with parser information
    """
    ext = Path(file_path).suffix.lower()

    parser_info = {
        'file_extension': ext,
        'file_path': file_path,
        'enhanced_cad_available': ENHANCED_CAD_AVAILABLE
    }

    if ext in ENHANCED_CAD_EXTENSIONS:
        parser_info.update({
            'parser_type': 'enhanced_cad' if ENHANCED_CAD_AVAILABLE else 'boundstate_fallback',
            'specialized_parsing': True,
            'file_category': 'engineering_cad'
        })
    else:
        parser_info.update({
            'parser_type': 'boundstate_standard',
            'specialized_parsing': False,
            'file_category': 'standard_document'
        })

    return parser_info

def get_supported_extensions() -> Dict[str, str]:
    """
    Get mapping of supported file extensions to parser types.

    Returns:
        Dictionary mapping extensions to parser descriptions
    """
    extensions = {}

    # Enhanced CAD extensions
    for ext in ENHANCED_CAD_EXTENSIONS:
        if ext == '.par':
            extensions[ext] = 'SolidWorks Part (Enhanced CAD Parser)'
        elif ext == '.asm':
            extensions[ext] = 'Assembly File (Enhanced CAD Parser)'
        elif ext in ['.igs', '.iges']:
            extensions[ext] = 'IGES CAD File (Enhanced CAD Parser)'
        elif ext in ['.1', '.2', '.3', '.4', '.5']:
            extensions[ext] = 'CAD Revision File (Enhanced CAD Parser)'
        elif ext == '.dat':
            extensions[ext] = 'Engineering Data File (Enhanced CAD Parser)'
        elif ext == '.raww':
            extensions[ext] = 'Raw Engineering Data (Enhanced CAD Parser)'

    # Add note about BoundState parser fallback
    extensions['_fallback'] = 'All other file types use BoundState standard parsers'

    return extensions

def validate_enhanced_cad_setup() -> Dict[str, Any]:
    """
    Validate that enhanced CAD parsing is properly configured.

    Returns:
        Dictionary with validation results
    """
    validation = {
        'enhanced_cad_parser_available': ENHANCED_CAD_AVAILABLE,
        'supported_extensions_count': len(ENHANCED_CAD_EXTENSIONS),
        'supported_extensions': list(ENHANCED_CAD_EXTENSIONS)
    }

    if ENHANCED_CAD_AVAILABLE:
        validation['status'] = 'ready'
        validation['message'] = f'Enhanced CAD parsing ready for {len(ENHANCED_CAD_EXTENSIONS)} file types'
    else:
        validation['status'] = 'fallback_only'
        validation['message'] = 'Enhanced CAD parser not available, using BoundState fallback'

    return validation

# For backwards compatibility, also export as get_parser
get_parser = get_enhanced_parser