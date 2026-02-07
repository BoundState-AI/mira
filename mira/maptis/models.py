#!/usr/bin/env python3
"""
Module: Models
Purpose: Material models for MIRA lineage tracking.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    ForeignKey, Text, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship
from .base import Base, AuditMixin, VersionMixin
import uuid


class Material(Base, AuditMixin, VersionMixin):
    """
    Core material entity with full lineage tracking.

    Represents a unique material specification with version history.
    """
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_spec_id = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Material specification identifier (e.g., AMS-4928, AS-568)"
    )
    name = Column(
        String(255),
        nullable=False,
        comment="Material name/nomenclature"
    )
    material_type = Column(
        String(100),
        nullable=True,
        index=True,
        comment="Material type/category (e.g., metal, polymer, composite)"
    )
    designation = Column(
        String(255),
        nullable=True,
        comment="Full material designation"
    )

    # Physical properties
    density_g_cm3 = Column(Float, nullable=True, comment="Density in g/cm³")
    tensile_strength_psi = Column(Float, nullable=True, comment="Tensile strength in PSI")

    # Ratings (1-4 scale per MIUL spec)
    rating_flam = Column(Integer, nullable=True, comment="Flammability rating (1-4)")
    rating_scc = Column(Integer, nullable=True, comment="Stress corrosion cracking rating (1-4)")
    rating_corr = Column(Integer, nullable=True, comment="Corrosion rating (1-4)")
    rating_tvs = Column(Integer, nullable=True, comment="Total volatile solids rating (1-4)")

    # Compliance flags
    contains_pfas = Column(Boolean, default=False, comment="Contains PFAS substances")
    is_restricted = Column(Boolean, default=False, comment="Material is restricted")

    # Source tracking
    data_source = Column(
        String(100),
        nullable=True,
        comment="Source of material data (MAPTIS, manual entry, etc.)"
    )
    source_reference = Column(
        Text,
        nullable=True,
        comment="Reference to original data source"
    )

    # Test data count
    test_report_count = Column(
        Integer,
        default=0,
        comment="Number of test reports associated with this material"
    )

    # Relationships
    properties = relationship(
        "MaterialProperty",
        back_populates="material",
        cascade="all, delete-orphan"
    )
    tests = relationship(
        "MaterialTest",
        back_populates="material",
        cascade="all, delete-orphan"
    )
    lineages = relationship(
        "Lineage",
        back_populates="material",
        foreign_keys="Lineage.material_id"
    )

    # Indexes for performance
    __table_args__ = (
        Index('idx_material_spec_version', 'material_spec_id', 'version'),
        Index('idx_material_current', 'is_current', 'material_spec_id'),
        Index('idx_material_type', 'material_type'),
        CheckConstraint('rating_flam >= 1 AND rating_flam <= 4 OR rating_flam IS NULL', name='chk_rating_flam'),
        CheckConstraint('rating_scc >= 1 AND rating_scc <= 4 OR rating_scc IS NULL', name='chk_rating_scc'),
        CheckConstraint('rating_corr >= 1 AND rating_corr <= 4 OR rating_corr IS NULL', name='chk_rating_corr'),
        CheckConstraint('rating_tvs >= 1 AND rating_tvs <= 4 OR rating_tvs IS NULL', name='chk_rating_tvs'),
    )

    def __repr__(self):
        return f"<Material(id={self.id}, spec={self.material_spec_id}, name={self.name}, v={self.version})>"


class MaterialProperty(Base, AuditMixin):
    """
    Individual material properties with source tracking.

    Tracks each property value with its source and confidence.
    """
    __tablename__ = "material_properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(
        Integer,
        ForeignKey('materials.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    property_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Property name (e.g., tensile_strength, yield_strength)"
    )
    property_value = Column(
        Float,
        nullable=False,
        comment="Numeric property value"
    )
    property_unit = Column(
        String(50),
        nullable=True,
        comment="Unit of measurement (e.g., psi, MPa, kg/m³)"
    )

    # Source tracking
    source_test_id = Column(
        Integer,
        ForeignKey('material_tests.id', ondelete='SET NULL'),
        nullable=True,
        comment="Test that determined this property value"
    )
    source_reference = Column(
        Text,
        nullable=True,
        comment="Reference to data source"
    )
    confidence = Column(
        Float,
        default=1.0,
        comment="Confidence in this property value (0-1)"
    )

    # Statistical context
    is_basis_value = Column(
        Boolean,
        default=False,
        comment="True if this is an A-Basis or B-Basis value"
    )
    basis_type = Column(
        String(10),
        nullable=True,
        comment="A, B, or S (typical) basis"
    )
    sample_size = Column(
        Integer,
        nullable=True,
        comment="Sample size used to determine this value"
    )

    # Relationships
    material = relationship("Material", back_populates="properties")
    source_test = relationship("MaterialTest", foreign_keys=[source_test_id])

    __table_args__ = (
        Index('idx_property_material', 'material_id', 'property_name'),
        UniqueConstraint('material_id', 'property_name', 'source_test_id', name='uq_material_property_source'),
        CheckConstraint('confidence >= 0 AND confidence <= 1', name='chk_confidence_range'),
    )

    def __repr__(self):
        return f"<MaterialProperty(material_id={self.material_id}, property={self.property_name}, value={self.property_value})>"


class MaterialTest(Base, AuditMixin):
    """
    Test data associated with materials.

    Links to specific test procedures, conditions, and results.
    """
    __tablename__ = "material_tests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(
        Integer,
        ForeignKey('materials.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    test_id = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique test identifier"
    )

    # Test metadata
    test_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of test (tensile, compression, fatigue, etc.)"
    )
    test_method = Column(
        String(100),
        nullable=True,
        comment="Test standard/method (ASTM E8, ASTM D638, etc.)"
    )
    test_date = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date test was performed"
    )
    test_facility = Column(
        String(255),
        nullable=True,
        comment="Facility where test was performed"
    )

    # Test conditions
    temperature_c = Column(Float, nullable=True, comment="Test temperature (°C)")
    pressure_psi = Column(Float, nullable=True, comment="Test pressure (PSI)")
    environment = Column(String(100), nullable=True, comment="Test environment")

    # Test results (primary)
    result_value = Column(
        Float,
        nullable=True,
        comment="Primary test result value"
    )
    result_unit = Column(
        String(50),
        nullable=True,
        comment="Unit of primary result"
    )

    # Quality flags
    is_valid = Column(
        Boolean,
        default=True,
        comment="True if test result is valid"
    )
    is_outlier = Column(
        Boolean,
        default=False,
        comment="True if flagged as outlier"
    )
    quality_score = Column(
        Float,
        nullable=True,
        comment="Quality score for this test (0-100)"
    )

    # Source tracking
    data_source = Column(
        String(100),
        nullable=True,
        comment="Source of test data"
    )
    source_file = Column(
        String(500),
        nullable=True,
        comment="Path to source data file"
    )

    # Relationships
    material = relationship("Material", back_populates="tests")
    lineages = relationship(
        "Lineage",
        back_populates="test",
        foreign_keys="Lineage.test_id"
    )

    __table_args__ = (
        Index('idx_test_material_type', 'material_id', 'test_type'),
        Index('idx_test_date', 'test_date'),
        Index('idx_test_valid', 'is_valid', 'is_outlier'),
    )

    def __repr__(self):
        return f"<MaterialTest(id={self.id}, test_id={self.test_id}, type={self.test_type}, material_id={self.material_id})>"
