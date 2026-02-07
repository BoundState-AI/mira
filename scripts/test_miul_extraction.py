"""Test MIUL V1 extraction on GPE and DMLLV drawing sets."""

import sys
import logging
from pathlib import Path

# Add BoundState to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v1_archive.dt_miul_builder import DTMIULBuilder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_extraction(name: str, drawing_dir: Path, dt_filename: str):
    """Run MIUL extraction on a drawing set."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Running MIUL extraction on {name}")
    logger.info(f"{'='*60}")

    # Find DT PDF
    dt_path = drawing_dir / dt_filename
    if not dt_path.exists():
        logger.error(f"Drawing Tree not found: {dt_path}")
        return None

    output_path = drawing_dir / f"MIUL_{name}.xlsx"

    try:
        builder = DTMIULBuilder(miul_number=name, project=name)
        result = builder.build(
            dt_pdf_path=dt_path,
            drawing_dir=drawing_dir,
            output_path=output_path,
            extract_epl=True,
            strict_validation=False,
        )
        logger.info(f"SUCCESS: Generated {result}")
        return result
    except Exception as e:
        logger.error(f"FAILED: {e}", exc_info=True)
        return None


def main():
    # GPE extraction
    gpe_dir = Path(r"C:\Users\jwilde2\Desktop\GPE")
    gpe_dt = "GPE-DOC-004-D (GPE Drawing Tree).pdf"
    gpe_result = run_extraction("GPE", gpe_dir, gpe_dt)

    # DMLLV extraction
    dmllv_dir = Path(r"C:\Users\jwilde2\Desktop\DMLLV")
    dmllv_dt = "MER07540-DT.DRW_-.6.pdf"
    dmllv_result = run_extraction("DMLLV", dmllv_dir, dmllv_dt)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("EXTRACTION SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"GPE:   {'SUCCESS' if gpe_result else 'FAILED'}")
    logger.info(f"DMLLV: {'SUCCESS' if dmllv_result else 'FAILED'}")


if __name__ == "__main__":
    main()
