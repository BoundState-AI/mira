#!/usr/bin/env python3
"""
Module: Cad
Purpose: [Automatically migrated - needs manual review]

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

import os
import re
import struct
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib
import json

# Import base parser
from boundstate.parsers import DocumentParser

logger = logging.getLogger(__name__)

@dataclass
class CADMetadata:
    """Metadata extracted from CAD files."""
    file_type: str
    part_name: Optional[str] = None
    part_number: Optional[str] = None
    material: Optional[str] = None
    mass: Optional[float] = None
    volume: Optional[float] = None
    surface_area: Optional[float] = None
    revision: Optional[str] = None
    created_by: Optional[str] = None
    modified_date: Optional[str] = None
    description: Optional[str] = None
    dependencies: List[str] = None
    custom_properties: Dict[str, str] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.custom_properties is None:
            self.custom_properties = {}

class EnhancedCADParser(DocumentParser):
    """Enhanced CAD parser for SolidWorks and engineering files."""

    def __init__(self, file_path: str, file_bytes: Optional[bytes] = None, doc_type: Optional[str] = None):
        super().__init__(file_path, file_bytes, doc_type)
        self.file_ext = Path(file_path).suffix.lower()

        # Common engineering keywords for text extraction
        self.engineering_keywords = [
            'material', 'steel', 'aluminum', 'titanium', 'composite',
            'mass', 'weight', 'volume', 'density', 'thickness',
            'pressure', 'temperature', 'stress', 'strain', 'load',
            'part', 'assembly', 'component', 'fastener', 'bolt',
            'weld', 'machined', 'fabricated', 'molded', 'cast'
        ]

    def parse(self) -> List[Dict[str, Any]]:
        """Parse CAD file based on extension."""
        try:
            if self.file_ext == '.par':
                return self._parse_solidworks_part()
            elif self.file_ext == '.asm':
                return self._parse_solidworks_assembly()
            elif self.file_ext in ['.igs', '.iges']:
                return self._parse_iges_file()
            elif self.file_ext in ['.1', '.2', '.3', '.4', '.5']:
                return self._parse_revision_file()
            elif self.file_ext in ['.dat', '.raww']:
                return self._parse_engineering_data()
            else:
                return self._parse_generic_cad()

        except Exception as e:
            logger.error(f"CAD parsing failed for {self.file_path}: {e}")
            return self._create_fallback_result()

    def _parse_solidworks_part(self) -> List[Dict[str, Any]]:
        """Parse SolidWorks .par (part) files."""
        try:
            metadata = CADMetadata(file_type='solidworks_part')

            # Extract filename-based information
            filename = Path(self.file_path).stem
            metadata.part_name = filename

            # Try to extract part number from filename
            part_number_match = re.search(r'([A-Z0-9\-_]+)', filename.upper())
            if part_number_match:
                metadata.part_number = part_number_match.group(1)

            # Try to read file properties (Windows COM or file system)
            file_props = self._extract_file_properties()
            if file_props:
                metadata.custom_properties.update(file_props)

            # Try binary metadata extraction
            binary_metadata = self._extract_solidworks_binary_metadata()
            if binary_metadata:
                metadata.description = binary_metadata.get('description')
                metadata.material = binary_metadata.get('material')
                metadata.revision = binary_metadata.get('revision')

            # Create searchable text
            searchable_text = self._create_cad_searchable_text(metadata)

            return [self._create_section(
                "1",
                f"SolidWorks Part: {metadata.part_name}",
                searchable_text,
                metadata={
                    'cad_metadata': metadata.__dict__,
                    'file_type': 'solidworks_part',
                    'searchable_keywords': self._extract_keywords_from_metadata(metadata)
                }
            )]

        except Exception as e:
            logger.error(f"SolidWorks part parsing failed: {e}")
            return self._create_fallback_result()

    def _parse_solidworks_assembly(self) -> List[Dict[str, Any]]:
        """Parse SolidWorks .asm (assembly) files."""
        try:
            metadata = CADMetadata(file_type='solidworks_assembly')

            filename = Path(self.file_path).stem
            metadata.part_name = filename

            # Extract assembly information
            assembly_info = self._extract_assembly_structure()
            if assembly_info:
                metadata.dependencies = assembly_info.get('components', [])
                metadata.description = f"Assembly with {len(metadata.dependencies)} components"

            # Look for related part files in same directory
            related_parts = self._find_related_parts()
            metadata.dependencies.extend(related_parts)

            searchable_text = self._create_assembly_searchable_text(metadata)

            return [self._create_section(
                "1",
                f"SolidWorks Assembly: {metadata.part_name}",
                searchable_text,
                metadata={
                    'cad_metadata': metadata.__dict__,
                    'file_type': 'solidworks_assembly',
                    'component_count': len(metadata.dependencies)
                }
            )]

        except Exception as e:
            logger.error(f"SolidWorks assembly parsing failed: {e}")
            return self._create_fallback_result()

    def _parse_iges_file(self) -> List[Dict[str, Any]]:
        """Parse IGES .igs files (text-based CAD format)."""
        try:
            # IGES files are partially text-readable
            with open(self.full_path, 'r', encoding='ascii', errors='ignore') as f:
                content = f.read(8192)  # Read first 8KB for metadata

            metadata = CADMetadata(file_type='iges')

            # Extract IGES header information
            iges_info = self._extract_iges_metadata(content)
            metadata.part_name = iges_info.get('part_name', Path(self.file_path).stem)
            metadata.description = iges_info.get('description')
            metadata.created_by = iges_info.get('author')

            # Extract geometric entities
            entities = self._extract_iges_entities(content)

            searchable_text = f"""
            IGES CAD File: {metadata.part_name}
            Description: {metadata.description or 'CAD geometry file'}
            Entities: {', '.join(entities) if entities else 'geometric data'}
            Created by: {metadata.created_by or 'unknown'}
            """

            return [self._create_section(
                "1",
                f"IGES File: {metadata.part_name}",
                searchable_text.strip(),
                metadata={
                    'cad_metadata': metadata.__dict__,
                    'file_type': 'iges',
                    'entities': entities
                }
            )]

        except Exception as e:
            logger.error(f"IGES parsing failed: {e}")
            return self._create_fallback_result()

    def _parse_revision_file(self) -> List[Dict[str, Any]]:
        """Parse revision files (.1, .2, .3, etc.)."""
        try:
            # These are typically revisions of other CAD files
            base_filename = Path(self.file_path).stem
            revision_number = self.file_ext[1:]  # Remove the dot

            metadata = CADMetadata(file_type='cad_revision')
            metadata.part_name = base_filename
            metadata.revision = revision_number

            # Try to find the base file
            base_file = self._find_base_file()
            if base_file:
                metadata.dependencies = [base_file]

            searchable_text = f"""
            CAD File Revision {revision_number}
            Base part: {base_filename}
            Revision history: Version {revision_number}
            """

            return [self._create_section(
                "1",
                f"Revision {revision_number}: {base_filename}",
                searchable_text.strip(),
                metadata={
                    'cad_metadata': metadata.__dict__,
                    'file_type': 'cad_revision',
                    'revision_number': revision_number
                }
            )]

        except Exception as e:
            logger.error(f"Revision file parsing failed: {e}")
            return self._create_fallback_result()

    def _parse_engineering_data(self) -> List[Dict[str, Any]]:
        """Parse engineering data files (.dat, .raww)."""
        try:
            metadata = CADMetadata(file_type='engineering_data')

            filename = Path(self.file_path).stem
            metadata.part_name = filename

            # Try to read as text first
            try:
                with open(self.full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(4096)  # Read first 4KB

                # Look for engineering keywords
                found_keywords = []
                for keyword in self.engineering_keywords:
                    if keyword.lower() in content.lower():
                        found_keywords.append(keyword)

                searchable_text = f"""
                Engineering Data File: {filename}
                Data type: {self.file_ext}
                Keywords found: {', '.join(found_keywords) if found_keywords else 'binary data'}
                Content preview: {content[:200]}...
                """

            except (UnicodeDecodeError, ValueError, OSError):
                # Binary file
                searchable_text = f"""
                Engineering Data File: {filename}
                Data type: Binary {self.file_ext} file
                Size: {os.path.getsize(self.full_path)} bytes
                """

            return [self._create_section(
                "1",
                f"Engineering Data: {filename}",
                searchable_text.strip(),
                metadata={
                    'cad_metadata': metadata.__dict__,
                    'file_type': 'engineering_data'
                }
            )]

        except Exception as e:
            logger.error(f"Engineering data parsing failed: {e}")
            return self._create_fallback_result()

    def _extract_file_properties(self) -> Dict[str, str]:
        """Extract file system properties."""
        try:
            file_stat = os.stat(self.full_path)
            return {
                'size_bytes': str(file_stat.st_size),
                'modified_time': str(file_stat.st_mtime),
                'created_time': str(file_stat.st_ctime) if hasattr(file_stat, 'st_ctime') else None
            }
        except OSError:
            return {}

    def _extract_solidworks_binary_metadata(self) -> Dict[str, str]:
        """Attempt to extract metadata from SolidWorks binary files."""
        try:
            # SolidWorks files contain embedded text strings
            with open(self.full_path, 'rb') as f:
                data = f.read(16384)  # Read first 16KB

            # Look for text strings in binary data
            text_strings = re.findall(b'[\x20-\x7E]{4,}', data)
            decoded_strings = []

            for text_bytes in text_strings:
                try:
                    decoded = text_bytes.decode('ascii')
                    if any(keyword in decoded.lower() for keyword in ['material', 'steel', 'aluminum', 'description']):
                        decoded_strings.append(decoded)
                except UnicodeDecodeError:
                    continue

            # Extract specific metadata
            metadata = {}
            for string in decoded_strings:
                if 'material' in string.lower():
                    metadata['material'] = string
                elif 'description' in string.lower():
                    metadata['description'] = string
                elif re.match(r'rev?\s*\d+', string.lower()):
                    metadata['revision'] = string

            return metadata

        except Exception as e:
            logger.debug(f"Binary metadata extraction failed: {e}")
            return {}

    def _extract_assembly_structure(self) -> Dict[str, Any]:
        """Extract assembly structure information."""
        try:
            # Look for component references in the directory
            file_dir = Path(self.full_path).parent
            components = []

            # Find related .par files that might be components
            for par_file in file_dir.glob("*.par"):
                if par_file.name != Path(self.full_path).name:
                    components.append(par_file.stem)

            return {
                'components': components[:20],  # Limit to 20 components
                'component_count': len(components)
            }

        except OSError:
            return {}

    def _find_related_parts(self) -> List[str]:
        """Find related part files in the same directory."""
        try:
            file_dir = Path(self.full_path).parent
            assembly_name = Path(self.full_path).stem

            related = []
            for file_path in file_dir.glob("*"):
                if file_path.suffix.lower() in ['.par', '.asm'] and file_path.stem != assembly_name:
                    # Check if filename suggests it's related
                    if assembly_name[:4] in file_path.stem or file_path.stem[:4] in assembly_name:
                        related.append(file_path.stem)

            return related[:10]  # Limit to 10 related parts

        except:
            return []

    def _extract_iges_metadata(self, content: str) -> Dict[str, str]:
        """Extract metadata from IGES file content."""
        try:
            metadata = {}

            # IGES files have structured headers
            lines = content.split('\n')

            for line in lines[:50]:  # Check first 50 lines
                if 'FILE NAME' in line:
                    metadata['part_name'] = line.split('FILE NAME')[-1].strip()
                elif 'AUTHOR' in line:
                    metadata['author'] = line.split('AUTHOR')[-1].strip()
                elif 'DESCRIPTION' in line:
                    metadata['description'] = line.split('DESCRIPTION')[-1].strip()

            return metadata

        except:
            return {}

    def _extract_iges_entities(self, content: str) -> List[str]:
        """Extract geometric entity types from IGES content."""
        try:
            # IGES entity type numbers
            entity_map = {
                '100': 'Circle',
                '110': 'Line',
                '120': 'Surface of Revolution',
                '126': 'NURBS Curve',
                '128': 'NURBS Surface',
                '144': 'Trimmed Surface',
                '186': 'Manifold Solid'
            }

            entities = []
            lines = content.split('\n')

            for line in lines:
                for entity_num, entity_name in entity_map.items():
                    if entity_num in line:
                        if entity_name not in entities:
                            entities.append(entity_name)

            return entities

        except:
            return []

    def _find_base_file(self) -> Optional[str]:
        """Find the base file for a revision file."""
        try:
            base_path = Path(self.full_path).with_suffix('')
            if base_path.exists():
                return base_path.name

            # Look for files with similar names
            file_dir = Path(self.full_path).parent
            base_stem = Path(self.full_path).stem

            for file_path in file_dir.glob(f"{base_stem}.*"):
                if file_path.suffix.lower() in ['.par', '.asm', '.dwg']:
                    return file_path.name

            return None

        except:
            return None

    def _create_cad_searchable_text(self, metadata: CADMetadata) -> str:
        """Create searchable text from CAD metadata."""
        text_parts = [
            f"SolidWorks Part: {metadata.part_name}",
        ]

        if metadata.part_number:
            text_parts.append(f"Part Number: {metadata.part_number}")

        if metadata.material:
            text_parts.append(f"Material: {metadata.material}")

        if metadata.description:
            text_parts.append(f"Description: {metadata.description}")

        if metadata.revision:
            text_parts.append(f"Revision: {metadata.revision}")

        # Add engineering keywords for searchability
        text_parts.append("Keywords: CAD part engineering design manufacturing")

        return "\n".join(text_parts)

    def _create_assembly_searchable_text(self, metadata: CADMetadata) -> str:
        """Create searchable text for assembly files."""
        text_parts = [
            f"SolidWorks Assembly: {metadata.part_name}",
            f"Components: {len(metadata.dependencies)} parts"
        ]

        if metadata.dependencies:
            text_parts.append(f"Component list: {', '.join(metadata.dependencies[:10])}")

        text_parts.append("Keywords: CAD assembly engineering design manufacturing structure")

        return "\n".join(text_parts)

    def _extract_keywords_from_metadata(self, metadata: CADMetadata) -> List[str]:
        """Extract searchable keywords from metadata."""
        keywords = ['CAD', 'engineering', 'design']

        if metadata.file_type:
            keywords.append(metadata.file_type)

        if metadata.material:
            keywords.append(metadata.material.lower())

        if metadata.part_number:
            keywords.append(metadata.part_number)

        return list(set(keywords))

    def _create_fallback_result(self) -> List[Dict[str, Any]]:
        """Create fallback result when parsing fails."""
        filename = Path(self.file_path).stem

        return [self._create_section(
            "1",
            f"CAD File: {filename}",
            f"CAD file: {filename}\nFile type: {self.file_ext}\nSize: {os.path.getsize(self.full_path)} bytes",
            metadata={
                'file_type': 'cad_generic',
                'parse_status': 'fallback'
            }
        )]

    def _parse_generic_cad(self) -> List[Dict[str, Any]]:
        """Generic CAD file parsing."""
        return self._create_fallback_result()

# Integration function for EM32 system
def enhance_cad_parsing():
    """Enhance the existing parser system with CAD capabilities."""

    # This would integrate with the existing get_parser function
    enhanced_extensions = {
        '.par': EnhancedCADParser,
        '.asm': EnhancedCADParser,
        '.igs': EnhancedCADParser,
        '.iges': EnhancedCADParser,
        '.1': EnhancedCADParser,
        '.2': EnhancedCADParser,
        '.3': EnhancedCADParser,
        '.4': EnhancedCADParser,
        '.5': EnhancedCADParser,
        '.dat': EnhancedCADParser,
        '.raww': EnhancedCADParser
    }

    return enhanced_extensions