#!/usr/bin/env python3
"""
Module: Quality Control
Purpose: Quality Control Metrics and Control Charts

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: ISO 9001, AS9100, SWE-032, SWE-134
Safety Critical: True
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import stats
import uuid

__version__ = "1.0.0"
__safety_critical__ = True

logger = logging.getLogger(__name__)


class ControlChartType(str, Enum):
    """Type of control chart"""
    XBAR = "xbar"  # Mean chart (average of subgroups)
    R_CHART = "r"  # Range chart (variability)
    S_CHART = "s"  # Standard deviation chart
    I_CHART = "i"  # Individual measurements chart
    MR_CHART = "mr"  # Moving range chart
    CUSUM = "cusum"  # Cumulative sum chart


@dataclass
class QualityMetrics:
    """Quality control metrics for a dataset"""
    sample_size: int
    mean: float
    std_dev: float
    median: float
    min_value: float
    max_value: float
    range: float
    coefficient_of_variation: float

    # Confidence intervals
    mean_ci_lower: float
    mean_ci_upper: float
    std_ci_lower: float
    std_ci_upper: float

    # Process capability (if spec limits provided)
    cp: Optional[float] = None
    cpk: Optional[float] = None
    pp: Optional[float] = None
    ppk: Optional[float] = None

    # Control chart limits
    ucl: Optional[float] = None  # Upper control limit
    lcl: Optional[float] = None  # Lower control limit

    # Quality score
    quality_score: Optional[float] = None
    quality_grade: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability


    def to_dict(self) -> Dict:
        """Convert to dictionary for API response"""
        return {
            "sample_size": self.sample_size,
            "mean": round(self.mean, 4),
            "std_dev": round(self.std_dev, 4),
            "median": round(self.median, 4),
            "min_value": round(self.min_value, 4),
            "max_value": round(self.max_value, 4),
            "range": round(self.range, 4),
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
            "mean_ci_95": [round(self.mean_ci_lower, 4), round(self.mean_ci_upper, 4)],
            "std_ci_95": [round(self.std_ci_lower, 4), round(self.std_ci_upper, 4)],
            "cp": round(self.cp, 4) if self.cp else None,
            "cpk": round(self.cpk, 4) if self.cpk else None,
            "pp": round(self.pp, 4) if self.pp else None,
            "ppk": round(self.ppk, 4) if self.ppk else None,
            "ucl": round(self.ucl, 4) if self.ucl else None,
            "lcl": round(self.lcl, 4) if self.lcl else None,
            "quality_score": round(self.quality_score, 2) if self.quality_score else None,
            "quality_grade": self.quality_grade,
        }


class QualityController:
    """
    Calculate quality control metrics and generate control charts.

    Process Capability Indices:
    - Cp: Potential capability (centered process)
    - Cpk: Actual capability (accounts for centering)
    - Pp: Overall performance (long-term)
    - Ppk: Overall performance capability

    Interpretation:
    - Cpk >= 1.33: Process capable (manufacturing standard)
    - Cpk >= 1.67: Process highly capable
    - Cpk < 1.0: Process not capable

    References:
    - ISO 9001:2015: Quality management systems
    - AS9100: Aerospace quality management
    - Montgomery, D.C.: Introduction to Statistical Quality Control
    """

    def __init__(self, confidence_level: float = 0.95):
        """
        Initialize quality controller.

        Args:
            confidence_level: Confidence level for intervals (default 0.95)
        """
        self.confidence_level = confidence_level

    def calculate_metrics(
        self,
        data: Union[List[float], np.ndarray],
        lower_spec_limit: Optional[float] = None,
        upper_spec_limit: Optional[float] = None,
        target: Optional[float] = None,
    ) -> QualityMetrics:
        """
        Calculate comprehensive quality metrics.

        Args:
            data: Measurement data
            lower_spec_limit: Lower specification limit (LSL)
            upper_spec_limit: Upper specification limit (USL)
            target: Target value (nominal)

        Returns:
            QualityMetrics with all calculated values
        """
        data = np.array(data)
        data = data[~np.isnan(data)]  # Remove NaN
        n = len(data)

        if n < 2:
            raise ValueError(f"Need at least 2 data points, got {n}")

        # Basic statistics
        mean = np.mean(data)
        std_dev = np.std(data, ddof=1)
        median = np.median(data)
        min_val = np.min(data)
        max_val = np.max(data)
        data_range = max_val - min_val
        cv = std_dev / mean if mean != 0 else 0

        # Confidence intervals
        mean_ci = self._confidence_interval_mean(data)
        std_ci = self._confidence_interval_std(data)

        # Process capability indices (if spec limits provided)
        cp, cpk, pp, ppk = None, None, None, None
        if lower_spec_limit is not None and upper_spec_limit is not None:
            cp, cpk = self._calculate_capability(
                data, lower_spec_limit, upper_spec_limit, target
            )
            pp, ppk = cp, cpk  # For now, same calculation (would differ for subgroups)

        # Control chart limits (3-sigma)
        ucl = mean + 3 * std_dev
        lcl = mean - 3 * std_dev

        # Quality score
        quality_score = self._calculate_quality_score(
            cv=cv,
            cpk=cpk,
            n=n,
        )

        quality_grade = self._grade_quality(quality_score)

        return QualityMetrics(
            sample_size=n,
            mean=mean,
            std_dev=std_dev,
            median=median,
            min_value=min_val,
            max_value=max_val,
            range=data_range,
            coefficient_of_variation=cv,
            mean_ci_lower=mean_ci[0],
            mean_ci_upper=mean_ci[1],
            std_ci_lower=std_ci[0],
            std_ci_upper=std_ci[1],
            cp=cp,
            cpk=cpk,
            pp=pp,
            ppk=ppk,
            ucl=ucl,
            lcl=lcl,
            quality_score=quality_score,
            quality_grade=quality_grade,
        )

    def _confidence_interval_mean(
        self,
        data: np.ndarray,
    ) -> Tuple[float, float]:
        """Calculate confidence interval for mean using t-distribution"""
        n = len(data)
        mean = np.mean(data)
        std_err = stats.sem(data)  # Standard error of the mean

        # t-critical value
        alpha = 1 - self.confidence_level
        t_crit = stats.t.ppf(1 - alpha/2, df=n-1)

        margin = t_crit * std_err

        return (mean - margin, mean + margin)

    def _confidence_interval_std(
        self,
        data: np.ndarray,
    ) -> Tuple[float, float]:
        """Calculate confidence interval for standard deviation using chi-square"""
        n = len(data)
        std_dev = np.std(data, ddof=1)
        variance = std_dev ** 2

        alpha = 1 - self.confidence_level
        df = n - 1

        # Chi-square critical values
        chi2_lower = stats.chi2.ppf(alpha/2, df=df)
        chi2_upper = stats.chi2.ppf(1 - alpha/2, df=df)

        # Confidence interval for variance
        var_lower = (df * variance) / chi2_upper
        var_upper = (df * variance) / chi2_lower

        # Convert to standard deviation
        std_lower = np.sqrt(var_lower)
        std_upper = np.sqrt(var_upper)

        return (std_lower, std_upper)

    def _calculate_capability(
        self,
        data: np.ndarray,
        lsl: float,
        usl: float,
        target: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Calculate process capability indices Cp and Cpk.

        Cp: Potential capability (assumes centered)
        Cpk: Actual capability (accounts for centering)

        Returns:
            (Cp, Cpk)
        """
        mean = np.mean(data)
        std_dev = np.std(data, ddof=1)

        # Cp: Process potential
        # Cp = (USL - LSL) / (6 * sigma)
        cp = (usl - lsl) / (6 * std_dev) if std_dev > 0 else np.inf

        # Cpk: Process capability (accounts for centering)
        # Cpk = min((USL - mean) / (3 * sigma), (mean - LSL) / (3 * sigma))
        cpu = (usl - mean) / (3 * std_dev) if std_dev > 0 else np.inf
        cpl = (mean - lsl) / (3 * std_dev) if std_dev > 0 else np.inf
        cpk = min(cpu, cpl)

        return (cp, cpk)

    def _calculate_quality_score(
        self,
        cv: float,
        cpk: Optional[float],
        n: int,
    ) -> float:
        """
        Calculate overall quality score (0-100).

        Factors:
        - Sample size (more is better)
        - Coefficient of variation (lower is better)
        - Process capability Cpk (higher is better)

        Returns:
            Quality score between 0 and 100
        """
        score = 0

        # Sample size component (0-30 points)
        if n >= 100:
            score += 30
        elif n >= 50:
            score += 25
        elif n >= 30:
            score += 20
        elif n >= 10:
            score += 15
        else:
            score += 10

        # CV component (0-35 points)
        # Excellent CV < 0.05, Poor CV > 0.20
        if cv < 0.05:
            score += 35
        elif cv < 0.10:
            score += 30
        elif cv < 0.15:
            score += 20
        elif cv < 0.20:
            score += 10
        else:
            score += 5

        # Cpk component (0-35 points) - if available
        if cpk is not None:
            if cpk >= 1.67:
                score += 35  # Highly capable
            elif cpk >= 1.33:
                score += 30  # Capable
            elif cpk >= 1.0:
                score += 20  # Marginally capable
            elif cpk >= 0.67:
                score += 10  # Not capable
            else:
                score += 5  # Poor
        else:
            # If no Cpk, redistribute points to other factors
            score += 17.5  # Neutral score

        return min(score, 100)

    def _grade_quality(self, score: float) -> str:
        """Assign quality grade based on score"""
        if score >= 90:
            return "A"  # Excellent
        elif score >= 80:
            return "B"  # Good
        elif score >= 70:
            return "C"  # Fair
        elif score >= 60:
            return "D"  # Marginal
        else:
            return "F"  # Poor

    def generate_control_limits(
        self,
        data: Union[List[float], np.ndarray],
        chart_type: ControlChartType = ControlChartType.I_CHART,
        sigma_level: float = 3.0,
    ) -> Dict[str, float]:
        """
        Generate control chart limits.

        Args:
            data: Process data
            chart_type: Type of control chart
            sigma_level: Number of standard deviations for limits (default 3)

        Returns:
            Dictionary with UCL, CL, LCL
        """
        data = np.array(data)

        if chart_type == ControlChartType.I_CHART:
            # Individual measurements chart
            mean = np.mean(data)
            std_dev = np.std(data, ddof=1)

            ucl = mean + sigma_level * std_dev
            cl = mean
            lcl = mean - sigma_level * std_dev

        elif chart_type == ControlChartType.MR_CHART:
            # Moving range chart
            moving_ranges = np.abs(np.diff(data))
            mr_mean = np.mean(moving_ranges)

            # Constants for MR chart
            d2 = 1.128  # For n=2 (consecutive pairs)
            d3 = 0.853  # For UCL calculation

            ucl = d3 * mr_mean / d2
            cl = mr_mean
            lcl = 0  # LCL for range charts is typically 0

        else:
            raise NotImplementedError(f"Chart type {chart_type} not yet implemented")

        return {
            "ucl": ucl,
            "cl": cl,
            "lcl": lcl,
            "chart_type": chart_type.value,
        }


# Example usage and self-test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Tensile strength measurements with spec limits
    measurements = np.array([
        82.5, 84.2, 81.9, 83.7, 85.1, 82.8, 84.5, 83.2, 82.1, 84.8,
        83.5, 82.9, 84.1, 83.8, 82.6, 85.3, 83.1, 84.6, 82.4, 83.9,
        84.3, 82.7, 83.4, 84.9, 83.6, 82.3, 84.7, 83.3, 82.5, 84.2
    ])

    # Specification: 80 ksi minimum, 90 ksi maximum, target 85 ksi
    lsl = 80.0
    usl = 90.0
    target = 85.0

    qc = QualityController()

    metrics = qc.calculate_metrics(
        measurements,
        lower_spec_limit=lsl,
        upper_spec_limit=usl,
        target=target
    )

    print(f"\n{'='*60}")
    print(f"Quality Control Metrics")
    print(f"{'='*60}")
    print(f"Sample Size: {metrics.sample_size}")
    print(f"Mean: {metrics.mean:.2f} ksi")
    print(f"Std Dev: {metrics.std_dev:.2f} ksi")
    print(f"CV: {metrics.coefficient_of_variation:.4f}")
    print(f"95% CI for Mean: [{metrics.mean_ci_lower:.2f}, {metrics.mean_ci_upper:.2f}]")
    print(f"\nProcess Capability:")
    print(f"  Cp: {metrics.cp:.3f}")
    print(f"  Cpk: {metrics.cpk:.3f}")
    if metrics.cpk >= 1.33:
        print(f"  Status: CAPABLE ✓")
    else:
        print(f"  Status: NOT CAPABLE ✗")
    print(f"\nQuality Score: {metrics.quality_score:.1f}/100 (Grade {metrics.quality_grade})")
    print(f"{'='*60}\n")
