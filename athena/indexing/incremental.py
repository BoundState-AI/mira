#!/usr/bin/env python3
"""
Module: Incremental
Purpose: __safety_critical__ = False  # Indexing utility

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

__safety_critical__ = False  # Indexing utility

import argparse
import logging
import time
from pathlib import Path
from create_tracking_db import (
    create_tracking_db,
    is_file_changed,
    mark_file_indexed,
    get_indexing_stats
)

def incremental_scan(root_path, wave_name, max_files=None, force_rescan=False):
    """
    Scan directory and return only files that need indexing

    Args:
        root_path: Root directory to scan
        wave_name: Name of indexing wave
        max_files: Maximum files to process
        force_rescan: Force rescan all files (ignore tracking)

    Returns:
        List of file paths that need indexing
    """

    logging.info(f"[INCREMENTAL] Starting incremental scan: {root_path}")

    # Create tracking DB if it doesn't exist
    create_tracking_db()

    # Get current stats
    stats = get_indexing_stats()
    logging.info(f"[STATS] Already indexed: {stats['total']} files")

    new_files = []
    changed_files = []
    skipped_files = 0

    # Scan directory
    root = Path(root_path)

    for file_path in root.rglob('*'):
        if not file_path.is_file():
            continue

        file_str = str(file_path)

        # Check if file needs indexing
        if force_rescan or is_file_changed(file_str):
            if file_str in [f for f in Path("./").rglob('*') if f.is_file()]:  # Already indexed
                changed_files.append(file_str)
            else:
                new_files.append(file_str)
        else:
            skipped_files += 1

        # Apply max_files limit
        if max_files and (len(new_files) + len(changed_files)) >= max_files:
            break

    total_to_index = len(new_files) + len(changed_files)

    logging.info(f"[INCREMENTAL] Scan complete:")
    logging.info(f"  📁 New files: {len(new_files)}")
    logging.info(f"  🔄 Changed files: {len(changed_files)}")
    logging.info(f"  ⏭️  Skipped (unchanged): {skipped_files}")
    logging.info(f"  🎯 Total to index: {total_to_index}")

    return new_files + changed_files

def run_incremental_indexing(args):
    """Run incremental indexing with file tracking"""

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Get files that need indexing
    files_to_index = incremental_scan(
        root_path=args.root,
        wave_name=args.wave,
        max_files=args.cap,
        force_rescan=args.force_rescan
    )

    if not files_to_index:
        logging.info("✅ No files need indexing. All up to date!")
        return

    logging.info(f"🚀 Starting indexing of {len(files_to_index)} files...")

    # TODO: Integrate with your actual indexing logic here
    # For now, simulate indexing
    start_time = time.time()

    for i, file_path in enumerate(files_to_index):
        if i % 100 == 0:
            logging.info(f"📦 Processing file {i+1}/{len(files_to_index)}: {Path(file_path).name}")

        # Simulate processing based on file type
        processing_mode = determine_processing_mode(file_path)

        # Mark as indexed (in real implementation, do this after successful processing)
        mark_file_indexed(file_path, processing_mode, args.wave)

        # Simulate processing time
        time.sleep(0.001)  # Remove in real implementation

    duration = time.time() - start_time

    logging.info(f"✅ Incremental indexing complete!")
    logging.info(f"   📊 Files processed: {len(files_to_index)}")
    logging.info(f"   ⏱️  Duration: {duration:.1f}s")
    logging.info(f"   🚄 Speed: {len(files_to_index)/duration:.1f} files/sec")

    # Show updated stats
    final_stats = get_indexing_stats()
    logging.info(f"📈 Total indexed files: {final_stats['total']}")

def determine_processing_mode(file_path):
    """Determine how file should be processed based on extension"""
    ext = Path(file_path).suffix.lower()

    # Based on your scan results
    if ext == '.pdf':
        return 'pre_chunk'  # Allowlisted PDFs
    elif ext in ['.txt', '.xml', '.md']:
        return 'doc_level'
    else:
        return 'metadata_only'

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Incremental indexing with file tracking')
    parser.add_argument('--root', required=True, help='Root directory to scan')
    parser.add_argument('--wave', default='incremental', help='Wave name for tracking')
    parser.add_argument('--cap', type=int, help='Maximum files to process')
    parser.add_argument('--force-rescan', action='store_true', help='Force rescan all files')
    parser.add_argument('--stats-only', action='store_true', help='Show stats only')

    args = parser.parse_args()

    if args.stats_only:
        stats = get_indexing_stats()
        print(f"📊 Indexing Statistics:")
        print(f"   Total files: {stats['total']}")
        print(f"   By wave: {stats['by_wave']}")
        print(f"   By mode: {stats['by_mode']}")
    else:
        run_incremental_indexing(args)