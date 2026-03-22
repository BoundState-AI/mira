#!/usr/bin/env python3
"""
FORGE bundle generator.

Emits a standalone generated app bundle from FORGE artifacts without
modifying the host MIRA application.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any

from .models import ForgeGeneratedBundle


class ForgeBundleGenerator:
    """Generate a standalone backend/frontend bundle from FORGE artifacts."""

    def generate(
        self,
        *,
        base_dir: Path,
        app_name: str,
        database_url_redacted: str,
        schema_manifest: dict[str, Any],
        semantic_map: dict[str, Any],
        relationship_graph: dict[str, Any],
        latent_relationships: dict[str, Any],
        data_quality_report: dict[str, Any],
        capabilities: dict[str, Any],
        question_map: dict[str, Any],
        scaffold_plan: dict[str, Any],
        bsms_pipeline: dict[str, Any],
        authority_pack: dict[str, Any],
        lineage_schema: dict[str, Any],
    ) -> ForgeGeneratedBundle:
        artifacts_dir = base_dir / "artifacts"
        app_dir = base_dir / "generated_app"
        backend_dir = app_dir / "backend"
        frontend_dir = app_dir / "frontend"
        authority_dir = app_dir / "authority_pack"
        bsms_dir = app_dir / "bsms_pipeline"
        lineage_dir = app_dir / "lineage"
        workflow_dir = app_dir / ".github" / "workflows"

        for directory in (
            artifacts_dir,
            backend_dir / "routers",
            backend_dir / "bsms",
            backend_dir / "tests",
            frontend_dir / "src" / "components",
            frontend_dir / "src" / "pages",
            frontend_dir / "src" / "lib",
            authority_dir / "bouncer",
            authority_dir / "parser",
            authority_dir / "rules",
            authority_dir / "evidence",
            authority_dir / "formatter",
            authority_dir / "gates",
            bsms_dir / "bouncer",
            bsms_dir / "parser",
            bsms_dir / "rules",
            bsms_dir / "formatter",
            lineage_dir,
            workflow_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        artifact_payloads = {
            "schema_manifest.json": schema_manifest,
            "semantic_map.json": semantic_map,
            "relationship_graph.json": relationship_graph,
            "latent_relationships.json": latent_relationships,
            "data_quality_report.json": data_quality_report,
            "capabilities.json": capabilities,
            "question_map.json": question_map,
            "scaffold_plan.json": scaffold_plan,
            "bsms_pipeline.json": bsms_pipeline,
            "authority_pack.json": authority_pack,
            "lineage_schema.json": lineage_schema,
        }
        for filename, payload in artifact_payloads.items():
            self._write_json(artifacts_dir / filename, payload)

        generated_config = {
            "app_name": app_name,
            "database_url_redacted": database_url_redacted,
            "manifest": schema_manifest,
            "semantic_map": semantic_map,
            "relationship_graph": relationship_graph,
            "latent_relationships": latent_relationships,
            "data_quality_report": data_quality_report,
            "capabilities": capabilities,
            "question_map": question_map,
            "scaffold_plan": scaffold_plan,
            "lineage_schema": lineage_schema,
        }

        question_routes = self._generated_routes_module(question_map)

        self._write_text(app_dir / "README.md", self._readme_template())
        self._write_text(app_dir / "run_backend.sh", self._run_backend_script())
        self._write_text(app_dir / "run_frontend.sh", self._run_frontend_script())
        self._write_text(app_dir / "docker-compose.yml", self._docker_compose())
        self._write_text(workflow_dir / "generated-ci.yml", self._workflow_yaml())

        self._write_json(backend_dir / "generated_config.json", generated_config)
        self._write_text(backend_dir / "__init__.py", "")
        self._write_text(backend_dir / "requirements.txt", self._backend_requirements())
        self._write_text(backend_dir / "Dockerfile", self._backend_dockerfile())
        self._write_text(backend_dir / "config.py", self._backend_config_py())
        self._write_text(backend_dir / "database.py", self._backend_database_py())
        self._write_text(backend_dir / "models.py", self._backend_models_py())
        self._write_text(backend_dir / "llm.py", self._llm_runtime_py())
        self._write_text(backend_dir / "authority_pack.py", self._authority_pack_py())
        self._write_text(backend_dir / "audit.py", self._audit_py())
        self._write_text(backend_dir / "monitoring.py", self._monitoring_py())
        self._write_text(backend_dir / "lineage.py", self._lineage_py())
        self._write_text(backend_dir / "schema_diff.py", self._schema_diff_py())
        self._write_text(backend_dir / "query_service.py", self._query_service_py())
        self._write_text(backend_dir / "app.py", self._backend_app_py())

        self._write_text(backend_dir / "routers" / "__init__.py", self._routers_init_py())
        self._write_text(backend_dir / "routers" / "manifest.py", self._router_manifest_py())
        self._write_text(backend_dir / "routers" / "questions.py", self._router_questions_py())
        self._write_text(backend_dir / "routers" / "query.py", self._router_query_py())
        self._write_text(backend_dir / "routers" / "bsms.py", self._router_bsms_py())
        self._write_text(backend_dir / "routers" / "generated.py", question_routes)

        self._write_text(backend_dir / "bsms" / "__init__.py", self._bsms_init_py())
        self._write_text(backend_dir / "bsms" / "bouncer.py", self._bsms_bouncer_py())
        self._write_text(backend_dir / "bsms" / "parser.py", self._bsms_parser_py())
        self._write_text(backend_dir / "bsms" / "rules.py", self._bsms_rules_py())
        self._write_text(backend_dir / "bsms" / "formatter.py", self._bsms_formatter_py())
        self._write_text(backend_dir / "bsms" / "service.py", self._bsms_service_py())

        self._write_text(backend_dir / "tests" / "test_health.py", self._backend_test_health_py())
        self._write_text(backend_dir / "tests" / "test_generated_routes.py", self._backend_test_routes_py())
        self._write_text(backend_dir / "tests" / "test_bsms.py", self._backend_test_bsms_py())

        self._write_json(frontend_dir / "src" / "generated-config.json", generated_config)
        self._write_text(frontend_dir / "package.json", self._frontend_package_json(app_name))
        self._write_text(frontend_dir / "vite.config.js", self._frontend_vite_config())
        self._write_text(frontend_dir / "index.html", self._frontend_index_html())
        self._write_text(frontend_dir / "Dockerfile", self._frontend_dockerfile())
        self._write_text(frontend_dir / "src" / "main.jsx", self._frontend_main_jsx())
        self._write_text(frontend_dir / "src" / "App.jsx", self._frontend_app_jsx())
        self._write_text(frontend_dir / "src" / "styles.css", self._frontend_styles())
        self._write_text(frontend_dir / "src" / "lib" / "api.js", self._frontend_api_js())
        self._write_text(frontend_dir / "src" / "components" / "Layout.jsx", self._frontend_layout_jsx())
        self._write_text(frontend_dir / "src" / "components" / "QuestionNav.jsx", self._frontend_question_nav_jsx())
        self._write_text(frontend_dir / "src" / "components" / "ResultView.jsx", self._frontend_result_view_jsx())
        self._write_text(frontend_dir / "src" / "components" / "SummaryCards.jsx", self._frontend_summary_cards_jsx())
        self._write_text(frontend_dir / "src" / "pages" / "Home.jsx", self._frontend_home_jsx())
        self._write_text(frontend_dir / "src" / "pages" / "Analysis.jsx", self._frontend_analysis_jsx())
        self._write_text(frontend_dir / "src" / "pages" / "Detail.jsx", self._frontend_detail_jsx())
        self._write_text(frontend_dir / "src" / "pages" / "Admin.jsx", self._frontend_admin_jsx())

        self._write_json(authority_dir / "manifest.json", authority_pack["manifest"])
        self._write_json(authority_dir / "bouncer" / "keywords.json", authority_pack["bouncer"]["keywords"])
        self._write_json(authority_dir / "bouncer" / "intents.json", authority_pack["bouncer"]["intents"])
        self._write_json(
            authority_dir / "bouncer" / "rejection_templates.json",
            authority_pack["bouncer"]["rejection_templates"],
        )
        self._write_json(
            authority_dir / "parser" / "field_mappings.json",
            authority_pack["parser"]["field_mappings"],
        )
        self._write_json(
            authority_dir / "parser" / "query_templates.json",
            authority_pack["parser"]["query_templates"],
        )
        self._write_json(authority_dir / "parser" / "examples.json", authority_pack["parser"]["examples"])
        self._write_json(authority_dir / "rules" / "categorical.json", authority_pack["rules"]["categorical"])
        self._write_json(authority_dir / "rules" / "threshold.json", authority_pack["rules"]["threshold"])
        self._write_json(authority_dir / "rules" / "relationship.json", authority_pack["rules"]["relationship"])
        self._write_json(authority_dir / "evidence" / "schema.json", authority_pack["evidence"]["schema"])
        self._write_json(
            authority_dir / "formatter" / "citation_style.json",
            authority_pack["formatter"]["citation_style"],
        )
        self._write_json(authority_dir / "formatter" / "vocabulary.json", authority_pack["formatter"]["vocabulary"])
        self._write_json(
            authority_dir / "formatter" / "response_templates.json",
            authority_pack["formatter"]["response_templates"],
        )
        self._write_json(authority_dir / "gates" / "human_review.json", authority_pack["gates"]["human_review"])
        self._write_json(authority_dir / "gates" / "escalation.json", authority_pack["gates"]["escalation"])

        self._write_json(bsms_dir / "pipeline_config.json", bsms_pipeline)
        self._write_json(bsms_dir / "bouncer" / "config.json", bsms_pipeline["bouncer_config"])
        self._write_json(bsms_dir / "parser" / "config.json", bsms_pipeline["parser_config"])
        self._write_json(bsms_dir / "rules" / "config.json", bsms_pipeline["rules_engine"])
        self._write_json(bsms_dir / "formatter" / "config.json", bsms_pipeline["formatter_config"])
        self._write_json(lineage_dir / "decision_lineage_schema.json", lineage_schema)

        files = sorted(
            str(path.relative_to(base_dir))
            for path in base_dir.rglob("*")
            if path.is_file()
        )
        return ForgeGeneratedBundle(
            root_dir=str(base_dir.resolve()),
            artifacts_dir=str(artifacts_dir.resolve()),
            app_dir=str(app_dir.resolve()),
            backend_dir=str(backend_dir.resolve()),
            frontend_dir=str(frontend_dir.resolve()),
            authority_pack_dir=str(authority_dir.resolve()),
            bsms_pipeline_dir=str(bsms_dir.resolve()),
            lineage_dir=str(lineage_dir.resolve()),
            files=files,
        )

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _write_text(self, path: Path, content: str) -> None:
        path.write_text(content.rstrip() + "\n", encoding="utf-8")

    def _generated_routes_module(self, question_map: dict[str, Any]) -> str:
        lines = [
            "from fastapi import APIRouter",
            "",
            "from models import GeneratedQueryRequest",
            "from query_service import execute_question",
            "",
            'router = APIRouter(prefix="/api/generated", tags=["generated"])',
            "",
        ]
        for question in question_map["questions"]:
            route_slug = self._slugify(f"{question['table']}-{question['question_type']}")
            fn_name = self._python_name(f"route_{route_slug}_{question['id']}")
            lines.extend(
                [
                    f'@router.post("/{route_slug}")',
                    f"async def {fn_name}(request: GeneratedQueryRequest) -> dict:",
                    f'    return execute_question("{question["id"]}", request.limit, request.filters)',
                    "",
                ]
            )
        return "\n".join(lines)

    def _readme_template(self) -> str:
        return dedent(
            """
            # FORGE Generated App

            This application bundle was generated by BoundState FORGE.

            Included modules:

            - Generated backend with deterministic query execution and optional LLM-backed BSMS
            - Generated React frontend with Home, Analysis, Detail, and Admin pages
            - Authority Pack scaffold
            - BSMS pipeline scaffold
            - Decision lineage schema
            - Generated tests, Dockerfiles, and CI workflow

            Optional runtime environment:

            - `DATABASE_URL` points at the target database
            - `FORGE_BSMS_ENABLE_LLM=1` enables Anthropic-backed BSMS enrichment
            - `ANTHROPIC_API_KEY` supplies the Anthropic credential
            - `FORGE_BSMS_MODEL` overrides the default Anthropic model
            """
        )

    def _run_backend_script(self) -> str:
        return dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail
            cd "$(dirname "$0")/backend"
            python -m venv .venv
            . .venv/bin/activate
            pip install -r requirements.txt
            uvicorn app:app --reload
            """
        )

    def _run_frontend_script(self) -> str:
        return dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail
            cd "$(dirname "$0")/frontend"
            npm install
            npm run dev
            """
        )

    def _docker_compose(self) -> str:
        return dedent(
            """
            version: "3.9"
            services:
              backend:
                build: ./backend
                environment:
                  DATABASE_URL: ${DATABASE_URL:-sqlite:///./demo.sqlite}
                  FORGE_BSMS_ENABLE_LLM: ${FORGE_BSMS_ENABLE_LLM:-0}
                  FORGE_BSMS_MODEL: ${FORGE_BSMS_MODEL:-claude-sonnet-4-5-20250929}
                  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
                ports:
                  - "8000:8000"
              frontend:
                build: ./frontend
                ports:
                  - "5173:5173"
                depends_on:
                  - backend
            """
        )

    def _workflow_yaml(self) -> str:
        return dedent(
            """
            name: Generated FORGE CI

            on:
              push:
              pull_request:

            jobs:
              backend:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-python@v5
                    with:
                      python-version: "3.11"
                  - run: pip install -r generated_app/backend/requirements.txt pytest
                  - run: pytest generated_app/backend/tests

              frontend:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-node@v4
                    with:
                      node-version: "20"
                  - run: cd generated_app/frontend && npm install && npm run build
            """
        )

    def _backend_requirements(self) -> str:
        return dedent(
            """
            fastapi>=0.111.0
            uvicorn[standard]>=0.30.0
            sqlalchemy>=2.0.0
            pydantic>=2.7.0
            anthropic>=0.75.0
            """
        )

    def _backend_dockerfile(self) -> str:
        return dedent(
            """
            FROM python:3.11-slim
            WORKDIR /app
            RUN apt-get update \
                && apt-get install -y --no-install-recommends curl \
                && rm -rf /var/lib/apt/lists/*
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt
            COPY . .
            HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
                CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
            CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
            """
        )

    def _backend_config_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            from functools import lru_cache
            from pathlib import Path
            from typing import Any

            CONFIG_PATH = Path(__file__).with_name("generated_config.json")
            AUTHORITY_PACK_DIR = Path(__file__).parents[1] / "authority_pack"
            LINEAGE_DIR = Path(__file__).parents[1] / "lineage"


            @lru_cache(maxsize=1)
            def load_config() -> dict[str, Any]:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            """
        )

    def _backend_database_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import os
            from functools import lru_cache

            from fastapi import HTTPException
            from sqlalchemy import MetaData, Table, create_engine
            from sqlalchemy.engine import Engine


            @lru_cache(maxsize=1)
            def get_engine() -> Engine:
                database_url = os.getenv("DATABASE_URL")
                if not database_url:
                    raise HTTPException(status_code=500, detail="DATABASE_URL is required")
                connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
                kwargs = {"future": True, "connect_args": connect_args}
                if not database_url.startswith("sqlite"):
                    kwargs.update({"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10})
                return create_engine(database_url, **kwargs)


            def reflect_table(qualified_name: str) -> Table:
                metadata = MetaData()
                if "." in qualified_name:
                    schema, table_name = qualified_name.split(".", 1)
                else:
                    schema, table_name = None, qualified_name
                return Table(table_name, metadata, schema=schema, autoload_with=get_engine())
            """
        )

    def _backend_models_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from typing import Any, Dict

            from pydantic import BaseModel, Field


            class GeneratedQueryRequest(BaseModel):
                limit: int = Field(25, ge=1, le=200)
                filters: Dict[str, Any] = Field(default_factory=dict)


            class QueryRequest(GeneratedQueryRequest):
                question_id: str = Field(..., min_length=1)


            class BSMSQueryRequest(BaseModel):
                query: str = Field(..., min_length=1)
                limit: int = Field(25, ge=1, le=200)
            """
        )

    def _authority_pack_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            from functools import lru_cache

            from config import AUTHORITY_PACK_DIR


            def _load_json(relative_path: str):
                return json.loads((AUTHORITY_PACK_DIR / relative_path).read_text(encoding="utf-8"))


            @lru_cache(maxsize=1)
            def load_authority_pack() -> dict:
                return {
                    "manifest": _load_json("manifest.json"),
                    "bouncer_keywords": _load_json("bouncer/keywords.json"),
                    "bouncer_intents": _load_json("bouncer/intents.json"),
                    "bouncer_rejection_templates": _load_json("bouncer/rejection_templates.json"),
                    "parser_field_mappings": _load_json("parser/field_mappings.json"),
                    "parser_query_templates": _load_json("parser/query_templates.json"),
                    "parser_examples": _load_json("parser/examples.json"),
                    "rules_categorical": _load_json("rules/categorical.json"),
                    "rules_threshold": _load_json("rules/threshold.json"),
                    "rules_relationship": _load_json("rules/relationship.json"),
                    "evidence_schema": _load_json("evidence/schema.json"),
                    "citation_style": _load_json("formatter/citation_style.json"),
                    "formatter_vocabulary": _load_json("formatter/vocabulary.json"),
                    "formatter_response_templates": _load_json("formatter/response_templates.json"),
                    "human_review": _load_json("gates/human_review.json"),
                    "escalation": _load_json("gates/escalation.json"),
                }
            """
        )

    def _llm_runtime_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            import os
            import re
            from functools import lru_cache
            from typing import Any


            class LLMDisabledError(RuntimeError):
                pass


            def _env_flag(name: str, default: bool = False) -> bool:
                raw = os.environ.get(name)
                if raw is None:
                    return default
                return raw.strip().lower() in {"1", "true", "yes", "on"}


            def _model_name() -> str:
                return (os.environ.get("FORGE_BSMS_MODEL") or "claude-sonnet-4-5-20250929").strip()


            def llm_status() -> dict[str, Any]:
                has_api_key = bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
                enabled = _env_flag("FORGE_BSMS_ENABLE_LLM", False) and has_api_key
                return {
                    "provider": "anthropic",
                    "configured": has_api_key,
                    "enabled": enabled,
                    "model": _model_name(),
                    "require_llm": _env_flag("FORGE_BSMS_REQUIRE_LLM", False),
                }


            @lru_cache(maxsize=1)
            def _client():
                api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
                if not api_key:
                    raise LLMDisabledError("ANTHROPIC_API_KEY is missing")
                import anthropic

                return anthropic.Anthropic(api_key=api_key)


            def _extract_text(response: Any) -> str:
                parts: list[str] = []
                for block in getattr(response, "content", []):
                    text = getattr(block, "text", None)
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                return "\\n".join(parts).strip()


            def _extract_json_object(text: str) -> dict[str, Any]:
                text = text.strip()
                candidates = [text]
                fenced = re.findall(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", text, flags=re.DOTALL)
                candidates.extend(fenced)
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    candidates.append(text[start : end + 1])
                for candidate in candidates:
                    try:
                        payload = json.loads(candidate)
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        return payload
                raise ValueError("LLM did not return a valid JSON object")


            def complete_text(
                system: str,
                user: str,
                *,
                max_tokens: int = 900,
                temperature: float = 0.0,
            ) -> dict[str, Any]:
                status = llm_status()
                if not status["enabled"]:
                    raise LLMDisabledError("FORGE_BSMS_ENABLE_LLM is off or ANTHROPIC_API_KEY is unavailable")
                response = _client().messages.create(
                    model=status["model"],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return {
                    "text": _extract_text(response),
                    "model": getattr(response, "model", status["model"]),
                    "input_tokens": getattr(getattr(response, "usage", None), "input_tokens", None),
                    "output_tokens": getattr(getattr(response, "usage", None), "output_tokens", None),
                }


            def complete_json(
                system: str,
                user: str,
                *,
                max_tokens: int = 900,
                temperature: float = 0.0,
            ) -> tuple[dict[str, Any], dict[str, Any]]:
                payload = complete_text(system, user, max_tokens=max_tokens, temperature=temperature)
                return _extract_json_object(payload["text"]), payload
            """
        )

    def _audit_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            from datetime import datetime
            from pathlib import Path
            from typing import Any

            AUDIT_LOG = Path(__file__).with_name("audit.log.jsonl")


            def log_event(event_type: str, payload: dict[str, Any]) -> None:
                entry = {
                    "event_type": event_type,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": payload,
                }
                with AUDIT_LOG.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry) + "\\n")


            def read_recent(limit: int = 100) -> list[dict[str, Any]]:
                if not AUDIT_LOG.exists():
                    return []
                lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
                return [json.loads(line) for line in lines[-limit:]]
            """
        )

    def _monitoring_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from collections import Counter

            _COUNTERS = Counter()


            def incr(metric: str, amount: int = 1) -> None:
                _COUNTERS[metric] += amount


            def metrics_text() -> str:
                lines = []
                for key, value in sorted(_COUNTERS.items()):
                    lines.append(f"forge_{key} {value}")
                return "\\n".join(lines) + ("\\n" if lines else "")
            """
        )

    def _lineage_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            from datetime import datetime
            from pathlib import Path
            from typing import Any

            from config import LINEAGE_DIR

            LINEAGE_LOG = LINEAGE_DIR / "decision_lineage.jsonl"


            def record_lineage(payload: dict[str, Any]) -> dict[str, Any]:
                enriched = {
                    **payload,
                    "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat() + "Z",
                }
                LINEAGE_DIR.mkdir(parents=True, exist_ok=True)
                with LINEAGE_LOG.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(enriched) + "\\n")
                return enriched
            """
        )

    def _schema_diff_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from typing import Any


            def diff_manifests(old_manifest: dict[str, Any], new_manifest: dict[str, Any]) -> dict[str, Any]:
                old_tables = {table["qualified_name"]: table for table in old_manifest.get("tables", [])}
                new_tables = {table["qualified_name"]: table for table in new_manifest.get("tables", [])}
                changes = []

                for table_name in sorted(new_tables.keys() - old_tables.keys()):
                    changes.append({"change_type": "table_added", "table": table_name})
                for table_name in sorted(old_tables.keys() - new_tables.keys()):
                    changes.append({"change_type": "table_removed", "table": table_name})

                for table_name in sorted(old_tables.keys() & new_tables.keys()):
                    old_columns = {column["name"]: column for column in old_tables[table_name].get("columns", [])}
                    new_columns = {column["name"]: column for column in new_tables[table_name].get("columns", [])}
                    for column_name in sorted(new_columns.keys() - old_columns.keys()):
                        changes.append({"change_type": "column_added", "table": table_name, "column": column_name})
                    for column_name in sorted(old_columns.keys() - new_columns.keys()):
                        changes.append({"change_type": "column_removed", "table": table_name, "column": column_name})
                    for column_name in sorted(old_columns.keys() & new_columns.keys()):
                        if old_columns[column_name].get("data_type") != new_columns[column_name].get("data_type"):
                            changes.append(
                                {
                                    "change_type": "column_type_changed",
                                    "table": table_name,
                                    "column": column_name,
                                    "old_type": old_columns[column_name].get("data_type"),
                                    "new_type": new_columns[column_name].get("data_type"),
                                }
                            )

                alembic_stub = [
                    "def upgrade():",
                    "    pass  # Fill in migration steps from FORGE diff report",
                    "",
                    "def downgrade():",
                    "    pass",
                ]
                return {"changes": changes, "alembic_stub": "\\n".join(alembic_stub)}
            """
        )

    def _query_service_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from typing import Any

            from fastapi import HTTPException
            from sqlalchemy import func, select

            from audit import log_event
            from authority_pack import load_authority_pack
            from config import load_config
            from database import get_engine, reflect_table
            from lineage import record_lineage
            from monitoring import incr


            def list_questions() -> dict[str, Any]:
                return load_config()["question_map"]


            def manifest() -> dict[str, Any]:
                return load_config()["manifest"]


            def find_question(question_id: str) -> dict[str, Any]:
                for question in load_config()["question_map"]["questions"]:
                    if question["id"] == question_id:
                        return question
                raise HTTPException(status_code=404, detail=f"Unknown question_id: {question_id}")


            def _find_relationship(qualified_table: str) -> dict[str, Any] | None:
                for relationship in load_config()["relationship_graph"]["relationships"]:
                    if relationship["source_table"] == qualified_table or relationship["target_table"] == qualified_table:
                        return relationship
                return None


            def _tokenize(text: str) -> set[str]:
                normalized = []
                for char in text.lower():
                    normalized.append(char if char.isalnum() else " ")
                return {token for token in "".join(normalized).split() if token}


            def candidate_questions(query: str, limit: int = 8) -> list[dict[str, Any]]:
                tokens = _tokenize(query)
                ranked: list[tuple[int, float, dict[str, Any]]] = []
                questions = load_config()["question_map"]["questions"]
                for question in questions:
                    question_tokens = _tokenize(
                        " ".join(
                            [
                                question["question"],
                                question["table"],
                                question["question_type"],
                                " ".join(question.get("path_tables", [])),
                                " ".join(question.get("path_node_types", [])),
                            ]
                        )
                    )
                    overlap = len(tokens & question_tokens)
                    ranked.append((overlap, float(question.get("utility_score", 0.0)), question))
                ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
                shortlist = [question for overlap, _, question in ranked if overlap > 0][:limit]
                if shortlist:
                    return shortlist
                return questions[:limit]


            def execute_question(
                question_id: str,
                limit: int = 25,
                filters: dict[str, Any] | None = None,
                execution_context: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                filters = filters or {}
                execution_context = execution_context or {}
                question = find_question(question_id)
                config = load_config()
                authority = load_authority_pack()
                engine = get_engine()
                table = reflect_table(question["table"])
                stmt = select(table)

                for key, value in filters.items():
                    if key not in table.c:
                        raise HTTPException(status_code=400, detail=f"Unknown filter column: {key}")
                    stmt = stmt.where(table.c[key] == value)

                question_type = question["question_type"]
                payload: dict[str, Any]
                with engine.connect() as connection:
                    if question_type in {"detail_view", "filter", "text_search"}:
                        stmt = stmt.limit(limit)
                        payload = {"rows": [dict(row) for row in connection.execute(stmt).mappings()]}
                    elif question_type == "relationship":
                        if question.get("join_path"):
                            select_tables = []
                            reflected = {}
                            first_table_name = question["path_tables"][0]
                            reflected[first_table_name] = reflect_table(first_table_name)
                            select_tables.append(reflected[first_table_name])
                            join_stmt = select(reflected[first_table_name])
                            for step in question["join_path"]:
                                source_name = step["source_table"]
                                target_name = step["target_table"]
                                source_table = reflected.setdefault(source_name, reflect_table(source_name))
                                target_table = reflected.setdefault(target_name, reflect_table(target_name))
                                if target_table not in select_tables:
                                    join_stmt = join_stmt.add_columns(target_table)
                                    select_tables.append(target_table)
                                join_stmt = join_stmt.join(
                                    target_table,
                                    source_table.c[step["source_column"]] == target_table.c[step["target_column"]],
                                )
                            for key, value in filters.items():
                                if key not in reflected[first_table_name].c:
                                    raise HTTPException(status_code=400, detail=f"Unknown filter column: {key}")
                                join_stmt = join_stmt.where(reflected[first_table_name].c[key] == value)
                            join_stmt = join_stmt.limit(limit)
                            payload = {
                                "join_path": question["join_path"],
                                "path_tables": question.get("path_tables", []),
                                "rows": [dict(row) for row in connection.execute(join_stmt).mappings()],
                            }
                            stmt = join_stmt
                        else:
                            relationship = _find_relationship(question["table"])
                            if relationship is None:
                                raise HTTPException(status_code=400, detail="No relationship available")
                            if relationship["source_table"] == question["table"]:
                                right_table = reflect_table(relationship["target_table"])
                                join_stmt = select(table, right_table).join(
                                    right_table,
                                    table.c[relationship["source_column"]] == right_table.c[relationship["target_column"]],
                                ).limit(limit)
                            else:
                                right_table = reflect_table(relationship["source_table"])
                                join_stmt = select(table, right_table).join(
                                    right_table,
                                    table.c[relationship["target_column"]] == right_table.c[relationship["source_column"]],
                                ).limit(limit)
                            payload = {
                                "relationship": relationship,
                                "rows": [dict(row) for row in connection.execute(join_stmt).mappings()],
                            }
                            stmt = join_stmt
                    elif question_type == "aggregation":
                        numeric_columns = config["capabilities"]["table_capabilities"][question["table"]]["numeric_columns"]
                        if not numeric_columns:
                            raise HTTPException(status_code=400, detail="No numeric columns available")
                        metric = numeric_columns[0]
                        stmt = select(
                            func.min(table.c[metric]).label("min"),
                            func.max(table.c[metric]).label("max"),
                            func.avg(table.c[metric]).label("avg"),
                        )
                        payload = {"metric": metric, "summary": dict(connection.execute(stmt).mappings().one())}
                    elif question_type == "comparison":
                        numeric_columns = config["capabilities"]["table_capabilities"][question["table"]]["numeric_columns"][:2]
                        if len(numeric_columns) < 2:
                            raise HTTPException(status_code=400, detail="No comparison columns available")
                        stmt = select(*[table.c[name] for name in numeric_columns]).limit(limit)
                        payload = {"columns": numeric_columns, "rows": [dict(row) for row in connection.execute(stmt).mappings()]}
                    elif question_type == "time_series":
                        table_cap = config["capabilities"]["table_capabilities"][question["table"]]
                        if not table_cap["timestamp_columns"] or not table_cap["numeric_columns"]:
                            raise HTTPException(status_code=400, detail="No time-series columns available")
                        timestamp_col = table_cap["timestamp_columns"][0]
                        numeric_col = table_cap["numeric_columns"][0]
                        stmt = select(table.c[timestamp_col], table.c[numeric_col]).limit(limit)
                        payload = {"columns": [timestamp_col, numeric_col], "rows": [dict(row) for row in connection.execute(stmt).mappings()]}
                    else:
                        raise HTTPException(status_code=400, detail=f"Unsupported question type: {question_type}")

                lineage = record_lineage(
                    {
                        "question": question["question"],
                        "bouncer_verdict": execution_context.get("bouncer_verdict", "PASS"),
                        "parsed_intent": execution_context.get(
                            "parsed_intent",
                            {"question_type": question_type, "table": question["table"], "question_id": question_id},
                        ),
                        "executed_query": str(stmt),
                        "rules_applied": execution_context.get("rules_applied", [question_type]),
                        "evidence_sources": question.get("path_tables", [question["table"]]),
                        "confidence": execution_context.get("confidence", question.get("utility_score", 0.5)),
                        "authority_pack_status": authority["manifest"].get("status"),
                        "user": execution_context.get("user", "generated_app"),
                        "decision_source": execution_context.get("decision_source", "deterministic"),
                        "original_query": execution_context.get("original_query"),
                        "bsms_runtime": execution_context.get("bsms_runtime"),
                    }
                )
                incr("queries_total")
                incr(f"query_type_{question_type}")
                log_event(
                    "QUERY_EXECUTED",
                    {
                        "question_id": question_id,
                        "question_type": question_type,
                        "filters": sorted(filters.keys()),
                        "decision_source": execution_context.get("decision_source", "deterministic"),
                    },
                )
                return {"question": question, "results": payload, "executed_query": str(stmt), "lineage": lineage}
            """
        )

    def _backend_app_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from fastapi import FastAPI
            from fastapi.responses import PlainTextResponse

            from audit import read_recent
            from monitoring import metrics_text
            from routers.bsms import router as bsms_router
            from routers.generated import router as generated_router
            from routers.manifest import router as manifest_router
            from routers.query import router as query_router
            from routers.questions import router as questions_router


            app = FastAPI(title="FORGE Generated App", version="1.0.0")
            app.include_router(manifest_router)
            app.include_router(questions_router)
            app.include_router(query_router)
            app.include_router(bsms_router)
            app.include_router(generated_router)


            @app.get("/health")
            async def health() -> dict[str, str]:
                return {"status": "ok", "service": "forge-generated-app"}


            @app.get("/ready")
            async def ready() -> dict[str, str]:
                return {"status": "ready"}


            @app.get("/metrics", response_class=PlainTextResponse)
            async def metrics() -> str:
                return metrics_text()


            @app.get("/api/audit")
            async def audit() -> dict:
                return {"entries": read_recent(100)}
            """
        )

    def _routers_init_py(self) -> str:
        return dedent(
            """
            from .manifest import router as manifest_router
            from .questions import router as questions_router
            from .query import router as query_router
            from .bsms import router as bsms_router
            from .generated import router as generated_router
            """
        )

    def _router_manifest_py(self) -> str:
        return dedent(
            """
            from fastapi import APIRouter

            from query_service import manifest

            router = APIRouter(tags=["manifest"])


            @router.get("/api/manifest")
            async def get_manifest() -> dict:
                return manifest()
            """
        )

    def _router_questions_py(self) -> str:
        return dedent(
            """
            from fastapi import APIRouter

            from query_service import list_questions

            router = APIRouter(tags=["questions"])


            @router.get("/api/questions")
            async def get_questions() -> dict:
                return list_questions()
            """
        )

    def _router_query_py(self) -> str:
        return dedent(
            """
            from fastapi import APIRouter

            from models import QueryRequest
            from query_service import execute_question

            router = APIRouter(tags=["query"])


            @router.post("/api/query")
            async def run_query(request: QueryRequest) -> dict:
                return execute_question(request.question_id, request.limit, request.filters)
            """
        )

    def _router_bsms_py(self) -> str:
        return dedent(
            """
            from fastapi import APIRouter

            from bsms.service import run_bsms_query
            from models import BSMSQueryRequest

            router = APIRouter(tags=["bsms"])


            @router.post("/api/bsms/query")
            async def bsms_query(request: BSMSQueryRequest) -> dict:
                return run_bsms_query(request.query, request.limit)
            """
        )

    def _bsms_init_py(self) -> str:
        return ""

    def _bsms_bouncer_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json

            from authority_pack import load_authority_pack
            from llm import complete_json, llm_status

            _MUTATION_TERMS = {
                "delete",
                "drop",
                "truncate",
                "update",
                "insert",
                "alter",
                "create",
                "grant",
                "revoke",
            }


            def _deterministic_bouncer(query: str, pack: dict) -> dict:
                lowered = query.lower()
                mutation_flags = sorted(term for term in _MUTATION_TERMS if term in lowered)
                if mutation_flags:
                    return {
                        "status": "rejected",
                        "reason": "Mutation or administrative requests are outside the generated BSMS authority.",
                        "risk_flags": mutation_flags,
                        "decision_source": "deterministic_guardrail",
                    }
                keywords = [str(keyword).lower() for keyword in pack["bouncer_keywords"]]
                keyword_match = any(keyword and keyword in lowered for keyword in keywords[:200])
                accepted = keyword_match or len(query.split()) >= 3
                return {
                    "status": "accepted" if accepted else "rejected",
                    "reason": None if accepted else "Query appears outside generated domain vocabulary",
                    "risk_flags": [],
                    "decision_source": "deterministic_guardrail",
                }


            def _llm_bouncer(query: str, pack: dict) -> tuple[dict, dict]:
                system = (
                    "You are the FORGE BSMS bouncer. "
                    "Allow only analytical read-only questions grounded in the generated database domain. "
                    "Reject requests for mutation, privileged administration, credential handling, or out-of-domain tasks. "
                    "Return only JSON."
                )
                user = json.dumps(
                    {
                        "query": query,
                        "allowed_intents": pack["bouncer_intents"],
                        "domain_keywords": pack["bouncer_keywords"][:80],
                        "rejection_templates": pack["bouncer_rejection_templates"],
                        "required_json_schema": {
                            "status": "accepted|rejected",
                            "reason": "short string or null",
                            "matched_intent": "string or null",
                            "risk_flags": ["string"],
                            "confidence": 0.0,
                        },
                    },
                    indent=2,
                )
                parsed, meta = complete_json(system, user, max_tokens=300, temperature=0.0)
                return {
                    "status": "accepted" if parsed.get("status") == "accepted" else "rejected",
                    "reason": parsed.get("reason"),
                    "matched_intent": parsed.get("matched_intent"),
                    "risk_flags": [str(flag) for flag in parsed.get("risk_flags", [])][:8],
                    "confidence": float(parsed.get("confidence", 0.0) or 0.0),
                    "decision_source": "llm_bouncer",
                    "llm": {"model": meta.get("model")},
                }, meta


            def run_bouncer(query: str) -> dict:
                pack = load_authority_pack()
                deterministic = _deterministic_bouncer(query, pack)
                status = llm_status()
                if deterministic["status"] == "rejected" and deterministic["decision_source"] == "deterministic_guardrail" and deterministic["risk_flags"]:
                    deterministic["llm_runtime"] = status
                    return deterministic
                if status["enabled"]:
                    try:
                        llm_result, _ = _llm_bouncer(query, pack)
                        llm_result["llm_runtime"] = status
                        return llm_result
                    except Exception as exc:
                        if status["require_llm"]:
                            return {
                                "status": "rejected",
                                "reason": f"BSMS LLM bouncer failed closed: {exc}",
                                "risk_flags": ["llm_failure"],
                                "decision_source": "llm_bouncer_failed_closed",
                                "llm_runtime": status,
                            }
                        deterministic["llm_error"] = str(exc)
                deterministic["llm_runtime"] = status
                return deterministic
            """
        )

    def _bsms_parser_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json
            from typing import Any

            from authority_pack import load_authority_pack
            from llm import complete_json, llm_status
            from query_service import candidate_questions, find_question, list_questions


            def _sanitize_filters(raw_filters: dict[str, Any], table: str, pack: dict) -> dict[str, Any]:
                allowed_columns = set(pack["parser_field_mappings"].get(table, {}).keys())
                sanitized = {}
                for key, value in raw_filters.items():
                    if key not in allowed_columns:
                        continue
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        sanitized[key] = value
                    else:
                        sanitized[key] = str(value)
                return sanitized


            def _deterministic_parse(query: str) -> dict:
                best_question = candidate_questions(query, limit=1)[0]
                return {
                    "question_id": best_question["id"],
                    "question_type": best_question["question_type"],
                    "table": best_question["table"],
                    "filters": {},
                    "confidence": float(best_question.get("utility_score", 0.5)),
                    "rationale": "Selected by deterministic overlap ranking.",
                    "decision_source": "deterministic_parser",
                }


            def _llm_parse(query: str, pack: dict) -> tuple[dict, dict]:
                candidates = candidate_questions(query, limit=8)
                system = (
                    "You are the FORGE BSMS parser. "
                    "Map the user query onto exactly one generated question when possible. "
                    "Only emit equality filters using fields that exist on the selected table. "
                    "Return only JSON."
                )
                user = json.dumps(
                    {
                        "query": query,
                        "candidate_questions": candidates,
                        "field_mappings": {
                            question["table"]: pack["parser_field_mappings"].get(question["table"], {})
                            for question in candidates
                        },
                        "examples": pack["parser_examples"][:6],
                        "required_json_schema": {
                            "question_id": "string",
                            "filters": {"field": "scalar"},
                            "confidence": 0.0,
                            "rationale": "short string",
                            "clarification_needed": False,
                            "clarification_question": "string or null",
                        },
                    },
                    indent=2,
                )
                parsed, meta = complete_json(system, user, max_tokens=500, temperature=0.0)
                question = find_question(str(parsed["question_id"]))
                return {
                    "question_id": question["id"],
                    "question_type": question["question_type"],
                    "table": question["table"],
                    "filters": _sanitize_filters(parsed.get("filters", {}), question["table"], pack),
                    "confidence": float(parsed.get("confidence", question.get("utility_score", 0.5)) or 0.0),
                    "rationale": parsed.get("rationale") or "Selected by LLM parser.",
                    "clarification_needed": bool(parsed.get("clarification_needed", False)),
                    "clarification_question": parsed.get("clarification_question"),
                    "decision_source": "llm_parser",
                    "llm": {"model": meta.get("model")},
                }, meta


            def parse_query(query: str) -> dict:
                if not list_questions()["questions"]:
                    raise ValueError("No generated questions available")
                pack = load_authority_pack()
                fallback = _deterministic_parse(query)
                status = llm_status()
                if status["enabled"]:
                    try:
                        parsed, _ = _llm_parse(query, pack)
                        parsed["llm_runtime"] = status
                        return parsed
                    except Exception as exc:
                        if status["require_llm"]:
                            raise RuntimeError(f"BSMS parser failed closed: {exc}") from exc
                        fallback["llm_error"] = str(exc)
                fallback["llm_runtime"] = status
                return fallback
            """
        )

    def _bsms_rules_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from authority_pack import load_authority_pack
            from query_service import execute_question, find_question

            _HUMAN_REVIEW_TERMS = {
                "approve",
                "certify",
                "guarantee",
                "sign off",
                "safety critical",
                "compliance decision",
            }


            def _gate_query(query: str) -> dict:
                lowered = query.lower()
                hits = sorted(term for term in _HUMAN_REVIEW_TERMS if term in lowered)
                return {
                    "status": "human_review_required" if hits else "approved",
                    "matches": hits,
                }


            def run_rules(parsed_intent: dict, limit: int, *, query: str, bouncer: dict) -> dict:
                pack = load_authority_pack()
                question = find_question(parsed_intent["question_id"])
                filters = parsed_intent.get("filters", {})
                gate = _gate_query(query)
                rules_applied = [question["question_type"], "authority_pack", "gate_check"]
                if gate["status"] != "approved":
                    return {
                        "verdict": "HUMAN_REVIEW_REQUIRED",
                        "confidence": parsed_intent.get("confidence", question.get("utility_score", 0.5)),
                        "payload": None,
                        "gate": gate,
                        "rules_applied": rules_applied,
                        "authority_pack_status": pack["manifest"].get("status"),
                    }

                result = execute_question(
                    parsed_intent["question_id"],
                    limit=limit,
                    filters=filters,
                    execution_context={
                        "bouncer_verdict": "PASS" if bouncer["status"] == "accepted" else "REJECT",
                        "parsed_intent": parsed_intent,
                        "rules_applied": rules_applied,
                        "confidence": parsed_intent.get("confidence", question.get("utility_score", 0.5)),
                        "user": "generated_app_bsms",
                        "decision_source": parsed_intent.get("decision_source", "deterministic_parser"),
                        "original_query": query,
                        "bsms_runtime": parsed_intent.get("llm_runtime"),
                    },
                )
                return {
                    "verdict": "SUPPORTED",
                    "confidence": parsed_intent.get("confidence", result["question"].get("utility_score", 0.5)),
                    "payload": result,
                    "gate": gate,
                    "rules_applied": rules_applied,
                    "authority_pack_status": pack["manifest"].get("status"),
                }
            """
        )

    def _bsms_formatter_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            import json

            from llm import complete_json, llm_status


            def _preview_payload(result: dict) -> dict:
                results = result.get("results", {})
                preview = {}
                for key, value in results.items():
                    if key == "rows" and isinstance(value, list):
                        preview[key] = value[:5]
                    else:
                        preview[key] = value
                return {
                    "question": result.get("question"),
                    "results": preview,
                    "executed_query": result.get("executed_query"),
                    "lineage": result.get("lineage"),
                }


            def _deterministic_answer(rules_packet: dict) -> str:
                if rules_packet["verdict"] == "HUMAN_REVIEW_REQUIRED":
                    return "This request requires human review before FORGE can return an authoritative answer."
                result = rules_packet["payload"]
                question = result["question"]
                results = result["results"]
                if "summary" in results:
                    summary = results["summary"]
                    return (
                        f"FORGE ran '{question['question']}' on '{question['table']}' "
                        f"and computed min={summary.get('min')}, max={summary.get('max')}, avg={summary.get('avg')}."
                    )
                if "rows" in results:
                    return (
                        f"FORGE matched '{question['question']}' on '{question['table']}' "
                        f"and returned {len(results['rows'])} row(s)."
                    )
                return f"FORGE matched '{question['question']}' on '{question['table']}'."


            def _llm_format(query: str, parsed_intent: dict, rules_packet: dict) -> tuple[dict, dict]:
                system = (
                    "You are the FORGE BSMS formatter. "
                    "Write a concise answer grounded only in the provided result packet. "
                    "Do not invent facts or claim certainty beyond the payload. "
                    "Return only JSON."
                )
                user = json.dumps(
                    {
                        "query": query,
                        "parsed_intent": parsed_intent,
                        "rules_packet": {
                            "verdict": rules_packet["verdict"],
                            "confidence": rules_packet["confidence"],
                            "gate": rules_packet.get("gate"),
                            "rules_applied": rules_packet.get("rules_applied"),
                            "payload_preview": _preview_payload(rules_packet["payload"]) if rules_packet.get("payload") else None,
                        },
                        "required_json_schema": {
                            "answer": "string",
                            "follow_up": "string or null",
                            "confidence_label": "low|medium|high",
                        },
                    },
                    indent=2,
                )
                return complete_json(system, user, max_tokens=500, temperature=0.1)


            def format_response(query: str, parsed_intent: dict, rules_packet: dict) -> dict:
                result = rules_packet.get("payload")
                citations = result["lineage"]["evidence_sources"] if result else []
                answer = _deterministic_answer(rules_packet)
                rendering_source = "deterministic_formatter"
                status = llm_status()
                llm_meta = None
                if status["enabled"]:
                    try:
                        formatted, meta = _llm_format(query, parsed_intent, rules_packet)
                        answer = formatted.get("answer") or answer
                        llm_meta = {"model": meta.get("model"), "confidence_label": formatted.get("confidence_label")}
                        rendering_source = "llm_formatter"
                    except Exception as exc:
                        if status["require_llm"]:
                            raise RuntimeError(f"BSMS formatter failed closed: {exc}") from exc
                        llm_meta = {"error": str(exc)}
                return {
                    "answer": answer,
                    "citations": citations,
                    "lineage": result["lineage"] if result else None,
                    "parsed_intent": parsed_intent,
                    "result": result,
                    "rendering_source": rendering_source,
                    "llm_runtime": status,
                    "llm": llm_meta,
                }
            """
        )

    def _bsms_service_py(self) -> str:
        return dedent(
            """
            from __future__ import annotations

            from bsms.bouncer import run_bouncer
            from bsms.formatter import format_response
            from bsms.parser import parse_query
            from bsms.rules import run_rules
            from llm import llm_status


            def run_bsms_query(query: str, limit: int = 25) -> dict:
                bouncer = run_bouncer(query)
                if bouncer["status"] != "accepted":
                    return {
                        "status": "rejected",
                        "pipeline": "B-S-M-S",
                        "bouncer": bouncer,
                        "answer": bouncer["reason"],
                        "runtime": {"llm": llm_status()},
                    }
                parsed_intent = parse_query(query)
                if parsed_intent.get("clarification_needed"):
                    return {
                        "status": "needs_clarification",
                        "pipeline": "B-S-M-S",
                        "bouncer": bouncer,
                        "parsed_intent": parsed_intent,
                        "answer": parsed_intent.get("clarification_question") or "Clarification is required.",
                        "runtime": {"llm": llm_status()},
                    }
                rules_packet = run_rules(parsed_intent, limit, query=query, bouncer=bouncer)
                formatted = format_response(query, parsed_intent, rules_packet)
                status = "ok" if rules_packet["verdict"] == "SUPPORTED" else "human_review_required"
                return {
                    "status": status,
                    "pipeline": "B-S-M-S",
                    "bouncer": bouncer,
                    "rules": {
                        "verdict": rules_packet["verdict"],
                        "gate": rules_packet.get("gate"),
                        "rules_applied": rules_packet.get("rules_applied", []),
                        "authority_pack_status": rules_packet.get("authority_pack_status"),
                        "confidence": rules_packet.get("confidence"),
                    },
                    "runtime": {"llm": llm_status()},
                    **formatted,
                }
            """
        )

    def _backend_test_health_py(self) -> str:
        return dedent(
            """
            from fastapi.testclient import TestClient

            from app import app


            def test_health():
                client = TestClient(app)
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
            """
        )

    def _backend_test_routes_py(self) -> str:
        return dedent(
            """
            from config import load_config


            def test_generated_questions_have_ids():
                for question in load_config()["question_map"]["questions"]:
                    assert question["id"]
            """
        )

    def _backend_test_bsms_py(self) -> str:
        return dedent(
            """
            from unittest.mock import patch

            from bsms.bouncer import run_bouncer
            from bsms.parser import parse_query
            from config import load_config


            def test_bouncer_accepts_reasonable_query():
                result = run_bouncer("show me the generated data summary")
                assert result["status"] in {"accepted", "rejected"}


            def test_bouncer_rejects_mutation_language():
                result = run_bouncer("delete all rows from the generated database")
                assert result["status"] == "rejected"


            def test_parser_falls_back_without_llm():
                parsed = parse_query("view the full record details for generated data")
                assert parsed["question_id"]
                assert parsed["decision_source"] == "deterministic_parser"


            def test_parser_can_use_llm_when_enabled():
                question = load_config()["question_map"]["questions"][0]
                with patch("bsms.parser.llm_status", return_value={"enabled": True, "require_llm": False, "configured": True, "provider": "anthropic", "model": "fake"}):
                    with patch(
                        "bsms.parser.complete_json",
                        return_value=(
                            {
                                "question_id": question["id"],
                                "filters": {},
                                "confidence": 0.91,
                                "rationale": "Matched by fake LLM.",
                                "clarification_needed": False,
                                "clarification_question": None,
                            },
                            {"model": "fake"},
                        ),
                    ):
                        parsed = parse_query("show me something useful")
                assert parsed["question_id"] == question["id"]
                assert parsed["decision_source"] == "llm_parser"
            """
        )

    def _frontend_package_json(self, app_name: str) -> str:
        return json.dumps(
            {
                "name": self._slugify(app_name),
                "private": True,
                "version": "1.0.0",
                "type": "module",
                "scripts": {
                    "dev": "vite",
                    "build": "vite build",
                    "preview": "vite preview",
                },
                "dependencies": {
                    "react": "^18.3.1",
                    "react-dom": "^18.3.1",
                    "react-router-dom": "^6.30.1",
                },
                "devDependencies": {
                    "@vitejs/plugin-react": "^4.3.1",
                    "vite": "^5.4.19",
                },
            },
            indent=2,
        )

    def _frontend_vite_config(self) -> str:
        return dedent(
            """
            import { defineConfig } from "vite";
            import react from "@vitejs/plugin-react";

            export default defineConfig({
              plugins: [react()],
              server: {
                port: 5173,
                proxy: {
                  "/api": "http://localhost:8000",
                  "/metrics": "http://localhost:8000",
                },
              },
            });
            """
        )

    def _frontend_index_html(self) -> str:
        return dedent(
            """
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <title>FORGE Generated App</title>
              </head>
              <body>
                <div id="root"></div>
                <script type="module" src="/src/main.jsx"></script>
              </body>
            </html>
            """
        )

    def _frontend_dockerfile(self) -> str:
        return dedent(
            """
            FROM node:20-alpine
            WORKDIR /app
            COPY package.json .
            RUN npm install
            COPY . .
            CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
            """
        )

    def _frontend_main_jsx(self) -> str:
        return dedent(
            """
            import React from "react";
            import ReactDOM from "react-dom/client";
            import { BrowserRouter } from "react-router-dom";
            import App from "./App";
            import "./styles.css";

            ReactDOM.createRoot(document.getElementById("root")).render(
              <React.StrictMode>
                <BrowserRouter>
                  <App />
                </BrowserRouter>
              </React.StrictMode>,
            );
            """
        )

    def _frontend_app_jsx(self) -> str:
        return dedent(
            """
            import { Navigate, Route, Routes } from "react-router-dom";

            import Layout from "./components/Layout";
            import Admin from "./pages/Admin";
            import Analysis from "./pages/Analysis";
            import Detail from "./pages/Detail";
            import Home from "./pages/Home";

            export default function App() {
              return (
                <Layout>
                  <Routes>
                    <Route path="/" element={<Home />} />
                    <Route path="/analysis" element={<Analysis />} />
                    <Route path="/detail/:questionId" element={<Detail />} />
                    <Route path="/admin" element={<Admin />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </Layout>
              );
            }
            """
        )

    def _frontend_api_js(self) -> str:
        return dedent(
            """
            export async function getManifest() {
              const response = await fetch("/api/manifest");
              if (!response.ok) throw new Error("Manifest fetch failed");
              return response.json();
            }

            export async function getQuestions() {
              const response = await fetch("/api/questions");
              if (!response.ok) throw new Error("Question fetch failed");
              return response.json();
            }

            export async function runQuestion(questionId, limit = 25, filters = {}) {
              const response = await fetch("/api/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question_id: questionId, limit, filters }),
              });
              if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.detail || "Query failed");
              }
              return response.json();
            }

            export async function runBSMS(query, limit = 25) {
              const response = await fetch("/api/bsms/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, limit }),
              });
              if (!response.ok) throw new Error("BSMS query failed");
              return response.json();
            }

            export async function getAudit() {
              const response = await fetch("/api/audit");
              if (!response.ok) throw new Error("Audit fetch failed");
              return response.json();
            }

            export async function getMetrics() {
              const response = await fetch("/metrics");
              if (!response.ok) throw new Error("Metrics fetch failed");
              return response.text();
            }
            """
        )

    def _frontend_layout_jsx(self) -> str:
        return dedent(
            """
            import { NavLink } from "react-router-dom";

            import generated from "../generated-config.json";

            export default function Layout({ children }) {
              return (
                <div className="shell">
                  <aside className="sidebar">
                    <p className="eyebrow">BoundState FORGE</p>
                    <h1 className="title">{generated.app_name}</h1>
                    <nav className="nav">
                      <NavLink to="/">Home</NavLink>
                      <NavLink to="/analysis">Analysis</NavLink>
                      <NavLink to="/admin">Admin</NavLink>
                    </nav>
                    <div className="sidebarCard">
                      <p><strong>Questions</strong></p>
                      <p>{generated.question_map.questions.length}</p>
                      <p><strong>Relationships</strong></p>
                      <p>{generated.relationship_graph.relationships.length}</p>
                    </div>
                  </aside>
                  <main className="content">{children}</main>
                </div>
              );
            }
            """
        )

    def _frontend_question_nav_jsx(self) -> str:
        return dedent(
            """
            import { Link } from "react-router-dom";

            export default function QuestionNav({ questions }) {
              return (
                <div className="panel">
                  <h2>Generated Questions</h2>
                  <div className="questionList">
                    {questions.map((question) => (
                      <Link key={question.id} className="questionLink" to={`/detail/${question.id}`}>
                        <span>{question.question}</span>
                        <small>{question.table} · {question.question_type}</small>
                      </Link>
                    ))}
                  </div>
                </div>
              );
            }
            """
        )

    def _frontend_result_view_jsx(self) -> str:
        return dedent(
            """
            export default function ResultView({ result }) {
              return (
                <div className="panel">
                  <h2>Result</h2>
                  <pre>{JSON.stringify(result, null, 2)}</pre>
                </div>
              );
            }
            """
        )

    def _frontend_summary_cards_jsx(self) -> str:
        return dedent(
            """
            export default function SummaryCards({ summary }) {
              const items = [
                ["Tables", summary.table_count],
                ["Columns", summary.column_count],
                ["Relationships", summary.relationship_count],
                ["Questions", summary.generated_question_count],
              ];
              return (
                <div className="cardGrid">
                  {items.map(([label, value]) => (
                    <div key={label} className="panel statCard">
                      <p className="statLabel">{label}</p>
                      <p className="statValue">{value}</p>
                    </div>
                  ))}
                </div>
              );
            }
            """
        )

    def _frontend_home_jsx(self) -> str:
        return dedent(
            """
            import { useMemo, useState } from "react";

            import generated from "../generated-config.json";
            import { runBSMS } from "../lib/api";
            import QuestionNav from "../components/QuestionNav";
            import ResultView from "../components/ResultView";
            import SummaryCards from "../components/SummaryCards";

            export default function Home() {
              const [query, setQuery] = useState(generated.question_map.questions[0]?.question || "");
              const [result, setResult] = useState(null);
              const [error, setError] = useState("");
              const [loading, setLoading] = useState(false);
              const summary = useMemo(() => generated.summary || {
                table_count: generated.manifest.tables.length,
                column_count: generated.manifest.tables.reduce((count, table) => count + table.columns.length, 0),
                relationship_count: generated.relationship_graph.relationships.length,
                generated_question_count: generated.question_map.questions.length,
              }, []);

              async function submit() {
                setLoading(true);
                setError("");
                try {
                  setResult(await runBSMS(query, 25));
                } catch (err) {
                  setError(err instanceof Error ? err.message : "BSMS query failed");
                } finally {
                  setLoading(false);
                }
              }

              return (
                <div className="page">
                  <section className="hero">
                    <p className="eyebrow">Generated App</p>
                    <h1>{generated.app_name}</h1>
                    <p className="lede">Evidence-first database intelligence compiled by FORGE.</p>
                    <div className="queryBar">
                      <input value={query} onChange={(event) => setQuery(event.target.value)} />
                      <button onClick={submit} disabled={loading}>{loading ? "Running..." : "Run BSMS"}</button>
                    </div>
                    {error && <p className="error">{error}</p>}
                  </section>

                  <SummaryCards summary={summary} />

                  <div className="twoCol">
                    <QuestionNav questions={generated.question_map.questions} />
                    <ResultView result={result} />
                  </div>
                </div>
              );
            }
            """
        )

    def _frontend_analysis_jsx(self) -> str:
        return dedent(
            """
            import generated from "../generated-config.json";

            export default function Analysis() {
              return (
                <div className="page">
                  <div className="panel">
                    <h2>Capabilities</h2>
                    <pre>{JSON.stringify(generated.capabilities, null, 2)}</pre>
                  </div>
                  <div className="panel">
                    <h2>Relationships</h2>
                    <pre>{JSON.stringify(generated.relationship_graph, null, 2)}</pre>
                  </div>
                </div>
              );
            }
            """
        )

    def _frontend_detail_jsx(self) -> str:
        return dedent(
            """
            import { useEffect, useState } from "react";
            import { useParams } from "react-router-dom";

            import generated from "../generated-config.json";
            import { runQuestion } from "../lib/api";
            import ResultView from "../components/ResultView";

            export default function Detail() {
              const { questionId } = useParams();
              const [result, setResult] = useState(null);
              const [error, setError] = useState("");
              const question = generated.question_map.questions.find((item) => item.id === questionId);

              useEffect(() => {
                async function load() {
                  if (!questionId) return;
                  try {
                    setResult(await runQuestion(questionId, 25, {}));
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Query failed");
                  }
                }
                load();
              }, [questionId]);

              return (
                <div className="page">
                  <div className="panel">
                    <h2>{question?.question || questionId}</h2>
                    <p>{question?.table} · {question?.question_type}</p>
                    {error && <p className="error">{error}</p>}
                  </div>
                  <ResultView result={result} />
                </div>
              );
            }
            """
        )

    def _frontend_admin_jsx(self) -> str:
        return dedent(
            """
            import { useEffect, useState } from "react";

            import generated from "../generated-config.json";
            import { getAudit, getMetrics } from "../lib/api";

            export default function Admin() {
              const [audit, setAudit] = useState({ entries: [] });
              const [metrics, setMetrics] = useState("");

              useEffect(() => {
                getAudit().then(setAudit).catch(() => setAudit({ entries: [] }));
                getMetrics().then(setMetrics).catch(() => setMetrics(""));
              }, []);

              return (
                <div className="page">
                  <div className="panel">
                    <h2>Manifest</h2>
                    <pre>{JSON.stringify(generated.manifest, null, 2)}</pre>
                  </div>
                  <div className="panel">
                    <h2>Audit</h2>
                    <pre>{JSON.stringify(audit, null, 2)}</pre>
                  </div>
                  <div className="panel">
                    <h2>Metrics</h2>
                    <pre>{metrics}</pre>
                  </div>
                </div>
              );
            }
            """
        )

    def _frontend_styles(self) -> str:
        return dedent(
            """
            :root {
              --bg: #efe8dc;
              --card: rgba(255, 252, 246, 0.92);
              --line: #d9cbb8;
              --text: #201a14;
              --muted: #6a6055;
              --accent: #204b57;
              --accent-2: #a95a2a;
            }

            * { box-sizing: border-box; }

            body {
              margin: 0;
              color: var(--text);
              font-family: "Georgia", "DM Sans", serif;
              background:
                radial-gradient(circle at top left, rgba(32, 75, 87, 0.15), transparent 30%),
                radial-gradient(circle at bottom right, rgba(169, 90, 42, 0.12), transparent 24%),
                linear-gradient(180deg, #f6f1e8, var(--bg));
            }

            a { color: inherit; text-decoration: none; }
            pre {
              white-space: pre-wrap;
              word-break: break-word;
              overflow: auto;
              min-height: 220px;
              padding: 16px;
              border-radius: 16px;
              background: #f8f3ea;
              border: 1px solid #e7dccb;
            }

            .shell {
              display: grid;
              grid-template-columns: 280px minmax(0, 1fr);
              min-height: 100vh;
            }

            .sidebar {
              padding: 24px;
              border-right: 1px solid var(--line);
              background: rgba(255, 248, 239, 0.85);
              backdrop-filter: blur(8px);
            }

            .content { padding: 28px; }
            .eyebrow {
              font-size: 11px;
              text-transform: uppercase;
              letter-spacing: 0.22em;
              color: var(--muted);
            }
            .title { margin: 0 0 18px; }
            .nav { display: grid; gap: 8px; margin-bottom: 20px; }
            .nav a { padding: 10px 12px; border-radius: 12px; border: 1px solid transparent; }
            .nav a.active { background: #fffaf1; border-color: var(--line); }

            .sidebarCard,
            .panel,
            .hero {
              border: 1px solid var(--line);
              border-radius: 22px;
              background: var(--card);
              box-shadow: 0 12px 30px rgba(32, 26, 20, 0.06);
            }

            .sidebarCard,
            .panel { padding: 18px; }
            .hero { padding: 24px; margin-bottom: 22px; }
            .lede { color: var(--muted); max-width: 720px; line-height: 1.6; }
            .queryBar {
              display: grid;
              grid-template-columns: minmax(0, 1fr) 180px;
              gap: 12px;
              margin-top: 18px;
            }

            input,
            button {
              width: 100%;
              border-radius: 14px;
              padding: 12px 14px;
              border: 1px solid var(--line);
              font: inherit;
            }

            button {
              color: white;
              border: none;
              background: linear-gradient(135deg, var(--accent), var(--accent-2));
              cursor: pointer;
            }

            .page { display: grid; gap: 20px; }
            .twoCol { display: grid; grid-template-columns: minmax(280px, 380px) minmax(0, 1fr); gap: 20px; }
            .questionList { display: grid; gap: 10px; }
            .questionLink {
              display: grid;
              gap: 4px;
              padding: 12px;
              border-radius: 16px;
              border: 1px solid var(--line);
              background: #fffaf3;
            }
            .cardGrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
            .statLabel { margin: 0; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; }
            .statValue { margin: 10px 0 0; font-size: 32px; font-weight: 700; }
            .error { color: #8a1c1c; font-weight: 600; }

            @media (max-width: 980px) {
              .shell,
              .twoCol,
              .cardGrid,
              .queryBar {
                grid-template-columns: 1fr;
              }
            }
            """
        )

    def _slugify(self, value: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")

    def _python_name(self, value: str) -> str:
        collapsed = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
        collapsed = collapsed.strip("_")
        if not collapsed:
            return "generated_route"
        if collapsed[0].isdigit():
            return f"route_{collapsed}"
        return collapsed
