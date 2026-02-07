# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Config Loader Tests
========================

Tests for config loading and validation in gptl.config_loader.
Updated to match actual GPTL v4.1 implementation.
"""

import tempfile
from pathlib import Path

import pytest

from gptl.config_loader import (
    ConfigNotFoundError,
    ConfigValidationError,
    DomainPackLoader,
    compute_config_hash,
)
from gptl.schema import DomainPack


class TestDomainPackLoader:
    """Tests for DomainPackLoader class."""

    def test_loader_creation(self, tmp_path):
        """Test loader can be created."""
        loader = DomainPackLoader(config_dirs=[tmp_path])  # Pass Path object
        assert loader is not None

    def test_loader_default_dirs(self):
        """Test loader has default directories."""
        loader = DomainPackLoader()
        assert hasattr(loader, "DEFAULT_CONFIG_DIRS")


class TestConfigNotFoundError:
    """Tests for ConfigNotFoundError exception."""

    def test_exception_is_raised(self):
        """Test exception can be raised."""
        with pytest.raises(ConfigNotFoundError):
            raise ConfigNotFoundError("test error")

    def test_exception_message(self):
        """Test exception has message."""
        try:
            raise ConfigNotFoundError("Domain not found: test")
        except ConfigNotFoundError as e:
            assert "test" in str(e)


class TestConfigValidationError:
    """Tests for ConfigValidationError exception."""

    def test_exception_is_raised(self):
        """Test exception can be raised."""
        with pytest.raises(ConfigValidationError):
            raise ConfigValidationError("validation failed")


class TestConfigHash:
    """Tests for config hash computation."""

    def test_hash_consistency(self, minimal_domain_pack):
        """Test that same config produces same hash."""
        hash1 = compute_config_hash(minimal_domain_pack)
        hash2 = compute_config_hash(minimal_domain_pack)
        assert hash1 == hash2

    def test_hash_format(self, minimal_domain_pack):
        """Test hash is proper format."""
        hash_value = compute_config_hash(minimal_domain_pack)
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0
        # Should be hex characters
        assert all(c in "0123456789abcdef" for c in hash_value.lower())

    def test_hash_changes_with_version(self, minimal_domain_pack):
        """Test different versions produce different hashes."""
        hash1 = compute_config_hash(minimal_domain_pack)

        # Create a new pack with different version
        from gptl.schema import DomainPack

        modified = DomainPack(
            domain_id=minimal_domain_pack.domain_id,
            version="2.0.0",  # Different version
            model_policy=minimal_domain_pack.model_policy,
            evidence_taxonomy=minimal_domain_pack.evidence_taxonomy,
        )
        hash2 = compute_config_hash(modified)

        assert hash1 != hash2


class TestDomainPackLoaderIntegration:
    """Integration tests for config loading."""

    def test_load_nonexistent_raises(self, tmp_path):
        """Test loading nonexistent pack raises error."""
        loader = DomainPackLoader(config_dirs=[tmp_path])  # Pass Path object
        with pytest.raises(ConfigNotFoundError):
            loader.load("nonexistent_domain_xyz")

    def test_loader_with_empty_dir(self, tmp_path):
        """Test loader with empty directory."""
        domains_dir = tmp_path / "domains"
        domains_dir.mkdir()

        loader = DomainPackLoader(config_dirs=[tmp_path])  # Pass Path object
        # Loading should fail since no YAML exists
        with pytest.raises(ConfigNotFoundError):
            loader.load("test")
