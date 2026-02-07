#!/usr/bin/env python3
"""
Module: Settings
Purpose: Global configuration defaults for the Athena stack.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033
Safety Critical: True
"""

from __future__ import annotations
from pydantic import BaseModel, field_validator, ConfigDict, Field
from typing import List, Literal, Optional
import uuid
import logging

__safety_critical__ = True  # Critical for system config
__all__ = ['AthenaConfig', 'CONFIG']

logger = logging.getLogger(__name__)

class AthenaConfig(BaseModel):
    """Production-ready Athena configuration with Pydantic validation.

    Compliance: SWE-032 (Data validation), SWE-013 (Traceability)
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    # Chunking configuration
    use_semantic_chunking: bool = False
    chunk_size_tokens: int = Field(default=420, gt=0)
    chunk_overlap_tokens: int = Field(default=60, ge=0)
    chunk_window: int = Field(default=200, gt=0)
    chunk_stride: int = Field(default=100, gt=0)


    # Embedding model configuration
    model_name: str = 'nomic-ai/nomic-embed-text-v1.5'
    batch_size: int = Field(default=16, gt=0)
    device: Literal['cuda', 'cpu'] = 'cuda'
    normalize_embeddings: bool = True
    max_seq_length: int = Field(default=8192, gt=0)


    # Prefixes for Nomic model
    query_prefix: str = 'search_query: '
    doc_prefix: str = 'search_document: '


    # Hybrid search settings
    use_hybrid_search: bool = True
    bm25_k1: float = Field(default=1.2, gt=0.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    rrf_k: int = Field(default=60, gt=0)
    topk_dense: int = Field(default=80, gt=0)
    topk_bm25: int = Field(default=80, gt=0)
    topk_rerank_candidates: int = Field(default=15, gt=0)
    topk_rerank: int = Field(default=12, gt=0)


    # Reranker settings
    reranker_model: str = 'mixedbread-ai/mxbai-rerank-base-v1'
    reranker_device: Literal['cuda', 'cpu'] = 'cuda'
    rerank_batch_size: int = Field(default=8, gt=0)


    # Index settings
    index_type: str = 'IndexFlatIP'
    use_fp16: bool = True


    # File and database settings
    tags_file: str = 'boundstate/tags.json'
    db_path: str = 'index/metadata'
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    allowed_extensions: List[str] = Field(default_factory=lambda: [
        '.pdf', '.docx', '.doc', '.ppt', '.pptx', '.xls', '.xlsx', '.zip',
        '.txt', '.md', '.mpp', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'
    ])


    # Ollama settings
    ollama_model: Optional[str] = 'llama3.1:8b-instruct-q4_K_M'  # Make optional for flexibility
    ollama_fast_model: Optional[str] = None
    ollama_timeout: int = Field(default=180, gt=0)
    ollama_url: str = 'http://localhost:11434'
    ollama_keep_alive: str = '1h'
    ollama_stream: bool = False

    max_context_tokens: int = Field(default=3000, gt=0)
    context_char_limit: int = Field(default=1800, gt=0)
    doc_context_char_limit: int = Field(default=2000, gt=0)


    # LLM generation settings
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=500, gt=0)
    require_citations: bool = True
    answer_max_chars: int = Field(default=2200, gt=0)


    # LLM execution controls
    use_two_stage_llm: bool = False
    force_big_model_on_table: bool = True
    table_mode_terms: List[str] = Field(default_factory=lambda: ['pto', 'table', 'per diem', 'hours', 'schedule'])
    fast_model_min_answer_chars: int = Field(default=120, gt=0)
    enable_validator_on_fast_model: bool = False
    fast_context_char_threshold: int = Field(default=2000, gt=0)
    llm_num_ctx: int = Field(default=2048, gt=0)
    llm_num_predict: int = Field(default=180, gt=0)
    llm_num_thread: int = Field(default=12, gt=0)
    llm_num_gpu: int = Field(default=1, ge=0)
    llm_gpu_layers: int = -1


    # Prompt template
    system_prompt: str = (
        'System: You are Athena. Answer only from the context.\n'
        'If the answer is not present, say: "I cannot find this in the provided documents."\n'
        'Always cite sources as [doc_id section]. Do not reveal chain-of-thought.\n\n'
        'User: {question}\n\nContext:\n<<<\n{context}\n>>>\n\n'
        'Instructions:\n1) Be concise and specific.\n'
        '2) Quote short phrases only when wording matters.\n'
        '3) List all sources you used as [doc_id section].'
    )


    # Observability settings
    enable_ranking_trace: bool = True
    log_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # Speed optimization settings
    fastpath_top_score: float = Field(default=0.82, ge=0.0, le=1.0)

    # System settings
    use_cag: bool = False
    use_ocr_for_figures: bool = True
    tqp_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    policy_doc_types: List[str] = Field(default_factory=lambda: ['policy', 'hr_policy', 'regulation', 'guideline'])

    # RTX GPU Memory Management
    clear_cache_frequency: int = Field(default=10, gt=0)
    max_memory_usage_gb: float = Field(default=6.0, gt=0.0)
    enable_memory_monitoring: bool = True

    # Additional fields for backward compatibility
    api_key: Optional[str] = None
    max_upload_size: int = Field(default=100*1024*1024)  # 100MB
    plugins_dir: str = 'boundstate/plugins'
    max_tags_per_section: int = Field(default=5, gt=0)
    gpu_name: Optional[str] = None

    @field_validator('batch_size')
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Validate batch size for GPU memory constraints.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if v > 64:
            logger.warning(f"Large batch size {v} may cause GPU OOM", extra={"req_id": str(uuid.uuid4())})
        return v

    @field_validator('chunk_size_tokens')
    @classmethod
    def validate_chunk_size(cls, v: int) -> int:
        """Validate chunk size is reasonable for processing.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if v > 8192:
            raise ValueError("Chunk size exceeds model max_seq_length")
        return v

    @field_validator('topk_dense', 'topk_bm25')
    @classmethod
    def validate_topk(cls, v: int) -> int:
        """Prevent excessive topk causing memory issues.

        Compliance: SWE-032 (Resource management)
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if v > 500:
            raise ValueError("Topk too large for efficient querying (max 500)")
        if v < 1:
            raise ValueError("Topk must be positive")
        return v

    @field_validator('ollama_timeout')
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout is reasonable for production.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if v > 600:  # 10 minutes max
            logger.warning(f"Very large timeout {v}s may cause blocking", extra={"req_id": str(uuid.uuid4())})
        return v

    def validate_production_readiness(self) -> Dict[str, Any]:
        """Comprehensive validation for production deployment.

        Returns:
            Dictionary with validation results and recommendations

        Compliance: SWE-032 (System validation)
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        results = {
            'status': 'passed',
            'warnings': [],
            'errors': [],
            'recommendations': []
        }

        # Memory efficiency checks
        total_topk = self.topk_dense + self.topk_bm25 + self.topk_rerank_candidates
        if total_topk > 200:
            results['warnings'].append(f"High total topk ({total_topk}) may impact memory")

        # GPU utilization checks
        if self.device == 'cuda' and self.batch_size < 8:
            results['recommendations'].append("Consider increasing batch_size for better GPU utilization")

        # Production safety checks
        if self.temperature > 0.5:
            results['warnings'].append("High temperature may reduce answer consistency")

        if not self.require_citations:
            results['errors'].append("Citations required for production compliance")
            results['status'] = 'failed'

        return results

class CompatibleConfig:
    """Wrapper to provide both dictionary and object access to AthenaConfig

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

    def __init__(self, config: AthenaConfig):
        self._config = config

    def __getattr__(self, name):
        return getattr(self._config, name)

    def __getitem__(self, key):
        return getattr(self._config, key)

    def get(self, key: str, default=None):
        return getattr(self._config, key, default)

    def __setattr__(self, name, value):
        if name == '_config':
            super().__setattr__(name, value)
        else:
            setattr(self._config, name, value)

# Create immutable singleton instance with validation
_athena_config = AthenaConfig()
CONFIG = CompatibleConfig(_athena_config)

# Validate production readiness on startup
_validation_results = CONFIG.validate_production_readiness()
if _validation_results['status'] == 'failed':
    raise ValueError(f"Configuration validation failed: {_validation_results['errors']}")
if _validation_results['warnings']:
    logger.warning(f"Configuration warnings: {_validation_results['warnings']}",
                   extra={"req_id": str(uuid.uuid4())})