#!/usr/bin/env python3
"""
Module: Analyzer
Purpose: Main Statistical Analyzer - Orchestrates All Statistical Analysis

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-134
Safety Critical: True
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import numpy as np

from .ab_basis import ABasisCalculator, BasisResult, BasisType
from .outlier_detection import OutlierDetector, OutlierResult, OutlierMethod
from .quality_control import QualityController, QualityMetrics
import uuid

__version__ = "1.0.0"
__safety_critical__ = True

logger = logging.getLogger(__name__)


@dataclass
class StatisticalAnalysisResult:
    """Complete statistical analysis result"""
    # Input summary
    sample_size: int
    data_summary: Dict

    # Quality metrics
    quality_metrics: QualityMetrics

    # Outlier detection
    outliers: OutlierResult

    # Basis values (if calculated)
    a_basis: Optional[BasisResult] = None
    b_basis: Optional[BasisResult] = None

    # Recommendations
    recommendations: List[str] = None
    source: str = ""  # NASA SWE-013 traceability


    def to_dict(self) -> Dict:
        """Convert to dictionary for API response"""
        result = {
            "sample_size": self.sample_size,
            "data_summary": self.data_summary,
            "quality_metrics": self.quality_metrics.to_dict(),
            "outliers": self.outliers.to_dict(),
        }

        if self.a_basis:
            result["a_basis"] = self.a_basis.to_dict()

        if self.b_basis:
            result["b_basis"] = self.b_basis.to_dict()

        if self.recommendations:
            result["recommendations"] = self.recommendations

        return result


class StatisticalAnalyzer:
    """
    High-level statistical analyzer for materials data.

    Provides a unified interface for:
    - A-Basis and B-Basis calculations (CMH-17 compliance)
    - Outlier detection (multiple methods)
    - Quality control metrics
    - Statistical summaries with recommendations

    Example Usage:
        analyzer = StatisticalAnalyzer()
        result = analyzer.analyze(
            data=tensile_strength_data,
            property_name="Tensile Strength",
            calculate_basis=True,
            lower_spec_limit=80.0,
            upper_spec_limit=90.0
        )
        print(f"B-Basis: {result.b_basis.basis_value:.2f} ksi")
        print(f"Quality Grade: {result.quality_metrics.quality_grade}")
    """

    def __init__(
        self,
        confidence_level: float = 0.95,
        outlier_method: OutlierMethod = OutlierMethod.MODIFIED_Z,
    ):
        """
        Initialize analyzer with default settings.

        Args:
            confidence_level: Confidence level for all calculations (default 0.95)
            outlier_method: Default outlier detection method
        """
        self.confidence_level = confidence_level
        self.outlier_method = outlier_method

        # Initialize component analyzers
        self.ab_calculator = ABasisCalculator(confidence_level=confidence_level)
        self.outlier_detector = OutlierDetector(alpha=1 - confidence_level)
        self.quality_controller = QualityController(confidence_level=confidence_level)

    def analyze(
        self,
        data: Union[List[float], np.ndarray],
        property_name: str = "Property",
        calculate_basis: bool = False,
        basis_type: Optional[BasisType] = None,
        lower_spec_limit: Optional[float] = None,
        upper_spec_limit: Optional[float] = None,
        target: Optional[float] = None,
        detect_outliers: bool = True,
        remove_outliers: bool = False,
    ) -> StatisticalAnalysisResult:
        """
        Perform comprehensive statistical analysis.

        Args:
            data: Measurement data
            property_name: Name of property being analyzed (for reporting)
            calculate_basis: Whether to calculate A/B-Basis values
            basis_type: Which basis to calculate (None = both if n sufficient)
            lower_spec_limit: Lower specification limit (for capability)
            upper_spec_limit: Upper specification limit (for capability)
            target: Target value (nominal)
            detect_outliers: Whether to detect outliers
            remove_outliers: Whether to remove outliers before other calculations

        Returns:
            StatisticalAnalysisResult with all analysis results
        """
        data = np.array(data)
        original_n = len(data)

        # Remove NaN
        data = data[~np.isnan(data)]
        n_after_nan = len(data)

        if n_after_nan < original_n:
            logger.warning(
                f"Removed {original_n - n_after_nan} NaN values "
                f"from {property_name} data"
            )

        if n_after_nan < 3:
            raise ValueError(
                f"Insufficient data for {property_name}: "
                f"{n_after_nan} samples (need at least 3)"
            )

        # Step 1: Outlier detection
        outliers = None
        if detect_outliers:
            outliers = self.outlier_detector.detect(data, method=self.outlier_method)

            if outliers.indices:
                logger.info(
                    f"Detected {len(outliers.indices)} outlier(s) in {property_name} "
                    f"using {outliers.method.value} method"
                )

                if remove_outliers:
                    # Remove outliers for subsequent calculations
                    mask = np.ones(len(data), dtype=bool)
                    mask[outliers.indices] = False
                    data = data[mask]
                    logger.info(
                        f"Removed {len(outliers.indices)} outlier(s), "
                        f"{len(data)} samples remaining"
                    )

        # Step 2: Quality control metrics
        quality_metrics = self.quality_controller.calculate_metrics(
            data=data,
            lower_spec_limit=lower_spec_limit,
            upper_spec_limit=upper_spec_limit,
            target=target,
        )

        # Step 3: Basis calculations (if requested)
        a_basis, b_basis = None, None

        if calculate_basis:
            # Determine which basis values to calculate
            if basis_type is None:
                # Auto-determine based on sample size
                if len(data) >= ABasisCalculator.MIN_SAMPLES_A_BASIS:
                    basis_type = BasisType.A_BASIS
                elif len(data) >= ABasisCalculator.MIN_SAMPLES_B_BASIS:
                    basis_type = BasisType.B_BASIS
                else:
                    logger.warning(
                        f"Insufficient samples ({len(data)}) for basis calculation"
                    )
                    basis_type = None

            if basis_type == BasisType.A_BASIS:
                try:
                    a_basis = self.ab_calculator.calculate_a_basis(data)
                    # Also calculate B-Basis if enough samples
                    if len(data) >= ABasisCalculator.MIN_SAMPLES_B_BASIS:
                        b_basis = self.ab_calculator.calculate_b_basis(data)
                except Exception as e:
                    logger.error(f"A-Basis calculation failed: {e}")

            elif basis_type == BasisType.B_BASIS:
                try:
                    b_basis = self.ab_calculator.calculate_b_basis(data)
                except Exception as e:
                    logger.error(f"B-Basis calculation failed: {e}")

        # Step 4: Data summary
        data_summary = {
            "property_name": property_name,
            "original_sample_size": original_n,
            "valid_sample_size": len(data),
            "outliers_detected": len(outliers.indices) if outliers else 0,
            "outliers_removed": remove_outliers,
        }

        # Step 5: Generate recommendations
        recommendations = self._generate_recommendations(
            quality_metrics=quality_metrics,
            outliers=outliers,
            a_basis=a_basis,
            b_basis=b_basis,
            property_name=property_name,
        )

        return StatisticalAnalysisResult(
            sample_size=len(data),
            data_summary=data_summary,
            quality_metrics=quality_metrics,
            outliers=outliers,
            a_basis=a_basis,
            b_basis=b_basis,
            recommendations=recommendations,
        )

    def _generate_recommendations(
        self,
        quality_metrics: QualityMetrics,
        outliers: Optional[OutlierResult],
        a_basis: Optional[BasisResult],
        b_basis: Optional[BasisResult],
        property_name: str,
    ) -> List[str]:
        """Generate actionable recommendations based on analysis"""
        recommendations = []

        # Sample size recommendations
        if quality_metrics.sample_size < ABasisCalculator.MIN_SAMPLES_B_BASIS:
            recommendations.append(
                f"⚠️ Sample size ({quality_metrics.sample_size}) is below minimum "
                f"for B-Basis ({ABasisCalculator.MIN_SAMPLES_B_BASIS}). "
                f"Perform additional testing."
            )
        elif quality_metrics.sample_size < ABasisCalculator.MIN_SAMPLES_A_BASIS:
            recommendations.append(
                f"ℹ️ Sample size ({quality_metrics.sample_size}) is sufficient for "
                f"B-Basis but below recommended minimum for A-Basis "
                f"({ABasisCalculator.MIN_SAMPLES_A_BASIS})."
            )

        # Coefficient of variation recommendations
        cv = quality_metrics.coefficient_of_variation
        if cv > 0.20:
            recommendations.append(
                f"⚠️ High coefficient of variation ({cv:.3f}). "
                f"Review test procedures and specimen preparation for consistency."
            )
        elif cv < 0.05:
            recommendations.append(
                f"✓ Excellent data consistency (CV = {cv:.3f})"
            )

        # Process capability recommendations
        if quality_metrics.cpk is not None:
            cpk = quality_metrics.cpk
            if cpk < 1.0:
                recommendations.append(
                    f"❌ Process not capable (Cpk = {cpk:.3f} < 1.0). "
                    f"Material does not meet specification limits."
                )
            elif cpk < 1.33:
                recommendations.append(
                    f"⚠️ Process marginally capable (Cpk = {cpk:.3f}). "
                    f"Consider process improvements or tighter controls."
                )
            elif cpk >= 1.67:
                recommendations.append(
                    f"✓ Process highly capable (Cpk = {cpk:.3f})"
                )

        # Outlier recommendations
        if outliers and len(outliers.indices) > 0:
            n_outliers = len(outliers.indices)
            pct_outliers = (n_outliers / quality_metrics.sample_size) * 100

            if pct_outliers > 10:
                recommendations.append(
                    f"⚠️ High outlier rate ({pct_outliers:.1f}%). "
                    f"Investigate test equipment, procedures, or material variability."
                )
            else:
                recommendations.append(
                    f"ℹ️ {n_outliers} outlier(s) detected ({pct_outliers:.1f}%). "
                    f"Review individual data points for validity."
                )

        # Basis value recommendations
        if b_basis:
            recommendations.append(
                f"ℹ️ B-Basis design allowable for {property_name}: "
                f"{b_basis.basis_value:.2f} "
                f"(90% survival, 95% confidence)"
            )

        if a_basis:
            recommendations.append(
                f"ℹ️ A-Basis design allowable for {property_name}: "
                f"{a_basis.basis_value:.2f} "
                f"(99% survival, 95% confidence)"
            )

        # Quality grade recommendations
        if quality_metrics.quality_grade:
            if quality_metrics.quality_grade == "A":
                recommendations.append("✓ Overall data quality: EXCELLENT")
            elif quality_metrics.quality_grade == "F":
                recommendations.append(
                    "⚠️ Overall data quality: POOR. Review test methodology."
                )

        return recommendations if recommendations else ["✓ No issues detected"]


# Example usage and self-test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Ultimate tensile strength (UTS) for aluminum 7075-T6
    uts_data = np.array([
        82.5, 84.2, 81.9, 83.7, 85.1, 82.8, 84.5, 83.2, 82.1, 84.8,
        83.5, 82.9, 84.1, 83.8, 82.6, 85.3, 83.1, 84.6, 82.4, 83.9,
        84.3, 82.7, 83.4, 84.9, 83.6, 82.3, 84.7, 83.3, 82.5, 84.2,
        # Add some more to reach 50 samples for B-Basis demonstration
        83.1, 84.1, 82.9, 83.5, 84.3, 82.7, 83.8, 84.4, 82.6, 83.2,
        84.0, 82.8, 83.6, 84.2, 82.4, 83.3, 84.5, 82.9, 83.7, 84.1
    ])

    # Spec limits: 78 ksi minimum, 88 ksi maximum (typical for 7075-T6)
    analyzer = StatisticalAnalyzer()

    result = analyzer.analyze(
        data=uts_data,
        property_name="Ultimate Tensile Strength",
        calculate_basis=True,
        basis_type=BasisType.B_BASIS,
        lower_spec_limit=78.0,
        upper_spec_limit=88.0,
        target=83.0,
        detect_outliers=True,
        remove_outliers=False,
    )

    print(f"\n{'='*70}")
    print(f"COMPREHENSIVE STATISTICAL ANALYSIS")
    print(f"{'='*70}")
    print(f"Property: {result.data_summary['property_name']}")
    print(f"Sample Size: {result.sample_size}")
    print(f"\nQuality Metrics:")
    print(f"  Mean: {result.quality_metrics.mean:.2f} ksi")
    print(f"  Std Dev: {result.quality_metrics.std_dev:.2f} ksi")
    print(f"  CV: {result.quality_metrics.coefficient_of_variation:.4f}")
    print(f"  Cpk: {result.quality_metrics.cpk:.3f}")
    print(f"  Quality Score: {result.quality_metrics.quality_score:.1f}/100 "
          f"(Grade {result.quality_metrics.quality_grade})")

    if result.b_basis:
        print(f"\nB-Basis Value: {result.b_basis.basis_value:.2f} ksi")

    if result.outliers.indices:
        print(f"\nOutliers: {len(result.outliers.indices)} detected")

    print(f"\nRecommendations:")
    for rec in result.recommendations:
        print(f"  {rec}")
    print(f"{'='*70}\n")
