"""Global FORGE configuration."""

from pathlib import Path

from pydantic import BaseModel, Field


# Default output directory for generated projects
DEFAULT_OUTPUT_DIR = Path("output")

# Default number of sample values per column
DEFAULT_SAMPLE_COUNT = 5

# Threshold ratio for enum-like columns (unique_count / row_count)
ENUM_LIKE_THRESHOLD = 0.05

# Maximum rows to scan for sampling
MAX_SAMPLE_SCAN = 1000


class ForgeConfig(BaseModel):
    """Runtime configuration for FORGE."""

    output_dir: Path = Field(default=DEFAULT_OUTPUT_DIR)
    sample_count: int = Field(default=DEFAULT_SAMPLE_COUNT)
    enum_like_threshold: float = Field(default=ENUM_LIKE_THRESHOLD)
