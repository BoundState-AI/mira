"""FORGE namespace exposed from MIRA.

MIRA still carries a partial in-repo FORGE tree, but the standalone FORGE repo
owns newer subpackages such as ``contracts`` and ``bsms_engine``. Extending the
package path lets ``mira.forge_claude.*`` resolve locally first and fall
through to ``boundstate_forge/forge_claude`` for modules that do not exist in
this repo.
"""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__version__ = "0.1.0"

__path__ = extend_path(__path__, __name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE_SOURCE_CANDIDATES = (
    _REPO_ROOT.parent / "boundstate_forge" / "forge_claude",
    _REPO_ROOT / "boundstate_forge" / "forge_claude",
)
for _forge_source in _FORGE_SOURCE_CANDIDATES:
    if _forge_source.exists():
        __path__.append(str(_forge_source))
