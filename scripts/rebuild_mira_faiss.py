#!/usr/bin/env python3
"""
Module: Rebuild MIRA FAISS Index
Purpose: Rebuild FAISS index from silver_report_rows for BoundState environment

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

This script rebuilds the MAPTIS FAISS index used by hybrid_search.py.
It reads from PostgreSQL silver_report_rows and outputs to mira_v2_faiss.

Usage:
    python scripts/rebuild_mira_faiss.py
    python scripts/rebuild_mira_faiss.py --dry-run  # Just count, don't build
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

# Configuration - matches existing BoundState infrastructure
FAISS_OUTPUT_DIR = Path(r"C:\BoundState\mira\databases\mira_v2_faiss")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384 dimensions
BATCH_SIZE = 500


def connect_db():
    """Connect to PostgreSQL mira database."""
    return psycopg2.connect(
        host="localhost",
        port=5432,
        database="mira",
        user="postgres",
        password="postgres"
    )


def get_material_names() -> Dict[int, Dict[str, Any]]:
    """Load material names from materials table if available."""
    print("[1/5] Loading material names...")
    try:
        conn = connect_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT material_key, designation, material_code
            FROM materials
        """)

        material_names = {}
        for row in cursor.fetchall():
            material_names[row['material_key']] = {
                'designation': row['designation'],
                'material_code': row['material_code'],
            }

        cursor.close()
        conn.close()
        print(f"  Loaded {len(material_names):,} material names from materials table")
        return material_names
    except Exception as e:
        print(f"  Warning: Could not load materials table: {e}")
        return {}


def extract_material_key(payload: dict) -> Optional[str]:
    """Extract material key from payload."""
    possible_keys = ['materialkey', 'material_key', 'matl_key', 'mtrl_key', 'mat_key']

    for key in possible_keys:
        if key in payload and payload[key]:
            val = payload[key]
            if val and str(val).strip() and str(val).strip() != 'NULL':
                return str(val).strip()

    return None


def load_silver_report_rows() -> List[Dict[str, Any]]:
    """Load all rows from silver_report_rows table."""
    print("[2/5] Loading data from silver_report_rows...")

    conn = connect_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
            row_uid::text as row_uid,
            contract_id,
            normalized_payload
        FROM silver_report_rows
        ORDER BY contract_id
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    print(f"  Loaded {len(rows):,} rows from database")

    # Convert to metadata format
    metadata = []
    for idx, row in enumerate(rows):
        payload = row['normalized_payload']
        contract_id = row['contract_id']

        # Extract material key from payload
        material_key = extract_material_key(payload)

        # Determine test type from contract_id
        test_type = contract_id.replace('_report', '')

        metadata.append({
            'idx': idx,
            'row_uid': row['row_uid'],
            'contract_id': contract_id,
            'material_key': material_key,
            'test_type': test_type,
            'payload': payload,
            'text_length': 0,  # Will be filled after creating corpus
        })

        if (idx + 1) % 10000 == 0:
            print(f"  Processed {idx + 1:,} rows...")

    print(f"  Created {len(metadata):,} metadata records")
    return metadata


def create_corpus(
    metadata: List[Dict[str, Any]],
    material_names: Dict[int, Dict[str, Any]]
) -> List[str]:
    """
    Create text corpus for embedding from metadata records.
    Uses material designation + payload fields for semantic content.
    """
    print("[3/5] Creating text corpus for embedding...")

    corpus = []
    for i, record in enumerate(metadata):
        material_key = record.get('material_key')
        test_type = record.get('test_type', 'unknown')
        payload = record.get('payload', {})

        text_parts = []

        # Material identification
        if material_key:
            # Try to get designation from materials table
            mat_key_int = None
            try:
                mat_key_int = int(material_key)
            except (ValueError, TypeError):
                pass

            if mat_key_int and mat_key_int in material_names:
                designation = material_names[mat_key_int].get('designation', '')
                if designation:
                    text_parts.append(f"Material: {designation}")

            # Also check payload for designation
            payload_desig = (
                payload.get('matl_designation') or
                payload.get('designation') or
                payload.get('name') or
                ''
            )
            if payload_desig and payload_desig not in text_parts:
                text_parts.append(f"Material: {payload_desig}")

            text_parts.append(f"Material Key: {material_key}")

        # Test type
        test_type_readable = test_type.replace('_', ' ').title()
        text_parts.append(f"Test: {test_type_readable}")

        # Extract key payload fields based on test type
        if 'flam' in test_type.lower() or 'flammability' in test_type.lower():
            if payload.get('flam_rating'):
                text_parts.append(f"Rating: {payload['flam_rating']}")
            if payload.get('flam_gasname'):
                text_parts.append(f"Gas: {payload['flam_gasname']}")
            if payload.get('flam_originalpercentoxygen'):
                text_parts.append(f"O2: {payload['flam_originalpercentoxygen']}%")

        elif 'pneumatic' in test_type.lower() or 'pneu' in test_type.lower():
            if payload.get('pneu_rating'):
                text_parts.append(f"Rating: {payload['pneu_rating']}")
            if payload.get('pneu_gasname'):
                text_parts.append(f"Gas: {payload['pneu_gasname']}")

        elif 'tvs' in test_type.lower() or 'outgassing' in test_type.lower():
            if payload.get('tvs_rating'):
                text_parts.append(f"Rating: {payload['tvs_rating']}")
            if payload.get('tvs_mlw'):
                text_parts.append(f"TML: {payload['tvs_mlw']}%")
            if payload.get('tvs_cvcm'):
                text_parts.append(f"CVCM: {payload['tvs_cvcm']}%")

        elif 'materials' in test_type.lower():
            # Materials report entries
            if payload.get('matl_spec1'):
                text_parts.append(f"Spec: {payload['matl_spec1']}")
            if payload.get('matl_manufacturer'):
                text_parts.append(f"Manufacturer: {payload['matl_manufacturer']}")
            if payload.get('matl_tradename'):
                text_parts.append(f"Trade Name: {payload['matl_tradename']}")

        # Fallback: include any spec fields
        for spec_key in ['matl_spec1', 'matl_testspec', 'spec', 'specification']:
            if payload.get(spec_key) and payload[spec_key] != 'NULL':
                if f"Spec" not in ' '.join(text_parts):
                    text_parts.append(f"Spec: {payload[spec_key]}")
                    break

        # Combine and clean
        text = ' | '.join(text_parts)
        corpus.append(text)

        # Update text_length in metadata
        record['text_length'] = len(text)

        if (i + 1) % 10000 == 0:
            print(f"  Processed {i + 1:,} records...")

    print(f"  Created corpus with {len(corpus):,} texts")
    return corpus


def build_faiss_index(corpus: List[str]):
    """Build FAISS index from corpus using sentence-transformers."""
    print(f"[4/5] Building FAISS index with {EMBEDDING_MODEL}...")

    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"  ERROR: Missing dependency: {e}")
        print("  Install with: pip install faiss-cpu sentence-transformers")
        sys.exit(1)

    # Load model
    print(f"  Loading embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    dimension = model.get_sentence_embedding_dimension()
    print(f"  Model loaded: {dimension} dimensions")

    # Encode in batches
    print(f"  Encoding {len(corpus):,} texts in batches of {BATCH_SIZE}...")
    all_embeddings = []

    for i in range(0, len(corpus), BATCH_SIZE):
        batch = corpus[i:i + BATCH_SIZE]
        embeddings = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)
        all_embeddings.append(embeddings)

        if (i + BATCH_SIZE) % 5000 == 0 or i + BATCH_SIZE >= len(corpus):
            print(f"    Encoded {min(i + BATCH_SIZE, len(corpus)):,} / {len(corpus):,}...")

    # Stack embeddings
    embeddings_matrix = np.vstack(all_embeddings).astype('float32')
    print(f"  Embeddings matrix shape: {embeddings_matrix.shape}")

    # Build FAISS index (Inner Product for cosine similarity with normalized vectors)
    print(f"  Building FAISS index...")
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings_matrix)

    print(f"  FAISS index built with {index.ntotal:,} vectors")
    return index


def save_index_and_metadata(
    index,
    metadata: List[Dict[str, Any]],
):
    """Save FAISS index and metadata to disk."""
    print("[5/5] Saving FAISS index and metadata...")

    import faiss

    # Ensure output directory exists
    FAISS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save FAISS index
    index_path = FAISS_OUTPUT_DIR / "maptis_faiss_index.bin"
    faiss.write_index(index, str(index_path))
    print(f"  Saved FAISS index: {index_path}")

    # Build metadata in expected format for hybrid_search.py
    # Format: {source_metadata: {metadata: [...records...]}}
    metadata_output = {
        'source_metadata': {
            'metadata': metadata,
            'embedding_model': EMBEDDING_MODEL,
            'dimension': index.d,
            'total_vectors': index.ntotal,
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    }

    metadata_path = FAISS_OUTPUT_DIR / "maptis_index_metadata.json"
    print(f"  Writing metadata to {metadata_path}...")
    with open(metadata_path, 'w') as f:
        json.dump(metadata_output, f, indent=2, default=str)
    print(f"  Saved metadata: {metadata_path}")

    # Calculate sizes
    index_size_mb = index_path.stat().st_size / (1024 * 1024)
    metadata_size_mb = metadata_path.stat().st_size / (1024 * 1024)

    print(f"\n  Index size: {index_size_mb:.1f} MB")
    print(f"  Metadata size: {metadata_size_mb:.1f} MB")


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild MIRA FAISS index from silver_report_rows"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Just count records, don't build index"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("REBUILD MIRA FAISS INDEX")
    print("=" * 70)
    print(f"Output directory: {FAISS_OUTPUT_DIR}")
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print()

    start_time = time.time()

    try:
        # Step 1: Load material names
        material_names = get_material_names()

        # Step 2: Load silver_report_rows
        metadata = load_silver_report_rows()

        if not metadata:
            print("\nERROR: No data found in silver_report_rows!")
            return 1

        # Count by contract_id
        contract_counts = defaultdict(int)
        for record in metadata:
            contract_counts[record['contract_id']] += 1

        print("\nRecords by contract_id:")
        for contract_id, count in sorted(contract_counts.items(), key=lambda x: -x[1]):
            print(f"  {contract_id:<40} {count:>8,}")

        if args.dry_run:
            print("\n[DRY RUN] Would build index with above records")
            return 0

        # Step 3: Create corpus
        corpus = create_corpus(metadata, material_names)

        # Step 4: Build FAISS index
        index = build_faiss_index(corpus)

        # Step 5: Save everything
        save_index_and_metadata(index, metadata)

        elapsed = time.time() - start_time

        print("\n" + "=" * 70)
        print("SUCCESS: FAISS index rebuilt!")
        print("=" * 70)
        print(f"Time elapsed: {elapsed / 60:.1f} minutes")
        print(f"Total vectors: {index.ntotal:,}")
        print(f"\nOutput files:")
        print(f"  {FAISS_OUTPUT_DIR / 'maptis_faiss_index.bin'}")
        print(f"  {FAISS_OUTPUT_DIR / 'maptis_index_metadata.json'}")
        print(f"\nRestart the API server to use the new index.")
        print("=" * 70)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
