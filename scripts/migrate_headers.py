#!/usr/bin/env python3
"""
Module: Header Migration Script
Purpose: Standardize Python file headers across BoundState codebase

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

import re
import sys
from pathlib import Path
from typing import Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def extract_module_info(content: str, filepath: Path) -> Tuple[str, str, str, str, bool]:
    """Extract module information from existing docstring.

    Returns:
        Tuple of (module_name, purpose, compliance, version, is_safety_critical)
    """
    # Default values
    module_name = filepath.stem.replace('_', ' ').title()
    purpose = f"[Automatically migrated - needs manual review]"
    compliance = "SWE-013, NASA-STD-8739.8B"
    version = "1.0.0"
    is_safety_critical = False

    # Try to extract purpose from first docstring line
    docstring_match = re.search(r'"""([^"]+?)(?:"""|$)', content, re.DOTALL)
    if docstring_match:
        docstring = docstring_match.group(1).strip()

        # Get first meaningful line as purpose
        lines = [line.strip() for line in docstring.split('\n') if line.strip()]
        if lines:
            first_line = lines[0]
            # Clean up common patterns
            first_line = re.sub(r'^Module:\s*', '', first_line, flags=re.IGNORECASE)
            first_line = re.sub(r'^Purpose:\s*', '', first_line, flags=re.IGNORECASE)
            first_line = re.sub(r'^Copyright:.*', '', first_line, flags=re.IGNORECASE)
            if first_line and len(first_line) > 10:
                purpose = first_line

        # Extract compliance if present
        compliance_match = re.search(r'Compliance[:\s]+([^\n]+)', docstring, re.IGNORECASE)
        if compliance_match:
            extracted_compliance = compliance_match.group(1).strip()
            if extracted_compliance:
                compliance = extracted_compliance

        # Extract version if present
        version_match = re.search(r'Version[:\s]+([0-9.]+)', docstring, re.IGNORECASE)
        if version_match:
            version = version_match.group(1).strip()

        # Check if safety critical
        safety_patterns = [
            r'safety.?critical',
            r'safety.?class',
            r'__safety_critical__\s*=\s*True',
            r'SafetyCriticalError',
        ]
        for pattern in safety_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                is_safety_critical = True
                break

    # Additional heuristics for safety critical detection
    safety_keywords = [
        'policy_engine', 'h2_', 'o2_', 'oxygen', 'hydrogen',
        'material_resolver', 'safety', 'compliance', 'pfas',
        'risk', 'anti_pattern'
    ]
    filename_lower = filepath.name.lower()
    for keyword in safety_keywords:
        if keyword in filename_lower:
            is_safety_critical = True
            break

    return module_name, purpose, compliance, version, is_safety_critical


def generate_standard_header(module_name: str, purpose: str, compliance: str,
                            version: str, is_safety_critical: bool) -> str:
    """Generate the standardized BoundState header."""

    header = f'''#!/usr/bin/env python3
"""
Module: {module_name}
Purpose: {purpose}

BoundState AI 2025
Version: {version}
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: {compliance}
Safety Critical: {is_safety_critical}
"""
'''
    return header


def migrate_file_header(filepath: Path, dry_run: bool = False) -> bool:
    """Migrate a single Python file to the standard header format.

    Returns:
        True if file was modified, False otherwise
    """
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
        return False

    # Skip empty files
    if not content.strip():
        return False

    # Skip __init__.py files that are just imports
    if filepath.name == '__init__.py' and len(content.strip().split('\n')) < 5:
        return False

    # Extract existing information
    module_name, purpose, compliance, version, is_safety_critical = extract_module_info(content, filepath)

    # Generate new header
    new_header = generate_standard_header(module_name, purpose, compliance, version, is_safety_critical)

    # Remove old header (shebang + docstring)
    # Pattern: optional shebang, optional docstring(s), then rest of file
    pattern = r'^(#!.*?\n)?(""".*?"""\s*)*(.*)'
    match = re.match(pattern, content, re.DOTALL)

    if match:
        rest_of_file = match.group(3).lstrip('\n')
    else:
        rest_of_file = content

    # Build new content
    new_content = new_header + '\n' + rest_of_file

    # Check if content actually changed
    if new_content == content:
        return False

    if not dry_run:
        # Create backup
        backup_path = filepath.with_suffix('.py.bak')
        filepath.rename(backup_path)

        try:
            filepath.write_text(new_content, encoding='utf-8')
            logger.info(f"✓ Migrated: {filepath}")
            backup_path.unlink()  # Remove backup if successful
            return True
        except Exception as e:
            logger.error(f"Failed to write {filepath}: {e}")
            backup_path.rename(filepath)  # Restore backup
            return False
    else:
        logger.info(f"[DRY RUN] Would migrate: {filepath}")
        logger.debug(f"  Module: {module_name}")
        logger.debug(f"  Purpose: {purpose}")
        logger.debug(f"  Safety Critical: {is_safety_critical}")
        return True


def migrate_directory(directory: Path, dry_run: bool = False, recursive: bool = True) -> dict:
    """Migrate all Python files in a directory.

    Returns:
        Dictionary with statistics
    """
    stats = {
        'total': 0,
        'migrated': 0,
        'skipped': 0,
        'failed': 0
    }

    pattern = "**/*.py" if recursive else "*.py"

    for filepath in directory.glob(pattern):
        # Skip __pycache__ and other special directories
        if '__pycache__' in filepath.parts or '.pytest_cache' in filepath.parts:
            continue

        # Skip this migration script itself
        if filepath.name == 'migrate_headers.py':
            continue

        stats['total'] += 1

        try:
            if migrate_file_header(filepath, dry_run):
                stats['migrated'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error processing {filepath}: {e}")
            stats['failed'] += 1

    return stats


def main():
    """Main entry point for header migration."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Migrate Python file headers to BoundState standard format'
    )
    parser.add_argument(
        'directories',
        nargs='+',
        type=Path,
        help='Directories to process'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Validate directories
    for directory in args.directories:
        if not directory.exists():
            logger.error(f"Directory does not exist: {directory}")
            sys.exit(1)
        if not directory.is_dir():
            logger.error(f"Not a directory: {directory}")
            sys.exit(1)

    # Process each directory
    total_stats = {'total': 0, 'migrated': 0, 'skipped': 0, 'failed': 0}

    for directory in args.directories:
        logger.info(f"\nProcessing directory: {directory}")
        stats = migrate_directory(directory, dry_run=args.dry_run)

        for key in total_stats:
            total_stats[key] += stats[key]

        logger.info(f"  Total files: {stats['total']}")
        logger.info(f"  Migrated: {stats['migrated']}")
        logger.info(f"  Skipped: {stats['skipped']}")
        logger.info(f"  Failed: {stats['failed']}")

    # Summary
    logger.info("\n" + "="*60)
    logger.info("SUMMARY")
    logger.info("="*60)
    logger.info(f"Total files processed: {total_stats['total']}")
    logger.info(f"Successfully migrated: {total_stats['migrated']}")
    logger.info(f"Skipped (no changes): {total_stats['skipped']}")
    logger.info(f"Failed: {total_stats['failed']}")

    if args.dry_run:
        logger.info("\nThis was a DRY RUN. No files were modified.")
        logger.info("Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
