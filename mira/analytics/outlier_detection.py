#!/usr/bin/env python3
"""
Module: Outlier Detection
Purpose: Statistical Outlier Detection for Materials Data

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: ASTM E178, CMH-17, SWE-032, SWE-134
Safety Critical: True
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import stats

__version__ = "1.0.0"
__safety_critical__ = True

logger = logging.getLogger(__name__)


class OutlierMethod(str, Enum):
    """Outlier detection method"""
    GRUBBS = "grubbs"  # For normal distributions, single extreme outlier
    DIXON = "dixon"  # For small samples (n<30)
    MODIFIED_Z = "modified_z"  # Robust method using MAD
    IQR = "iqr"  # Tukey fences, non-parametric
    ALL = "all"  # Run all methods and combine results


class OutlierSeverity(str, Enum):
    """Severity classification"""
    NONE = "none"
    MILD = "mild"  # Between 1.5 and 3 IQR
    EXTREME = "extreme"  # Beyond 3 IQR


@dataclass
class OutlierResult:
    """Result of outlier detection"""
    indices: List[int]  # Indices of outliers in original data
    values: List[float]  # Outlier values
    method: OutlierMethod
    test_statistic: float
    critical_value: float
    p_value: Optional[float]
    severity: List[OutlierSeverity]  # Severity for each outlier
    reason: str  # Human-readable explanation
    source: str = ""  # NASA SWE-013 traceability


    def to_dict(self) -> Dict:
        """Convert to dictionary for API response"""
        return {
            "indices": self.indices,
            "values": [round(v, 4) for v in self.values],
            "method": self.method.value,
            "test_statistic": round(self.test_statistic, 4),
            "critical_value": round(self.critical_value, 4),
            "p_value": round(self.p_value, 4) if self.p_value else None,
            "severity": [s.value for s in self.severity],
            "reason": self.reason,
        }


class OutlierDetector:
    """
    Detect statistical outliers in materials test data.

    Outliers in materials testing can indicate:
    - Test equipment malfunction
    - Specimen preparation errors
    - Material defects
    - Data entry errors
    - Genuinely extreme (but valid) behavior

    Always investigate outliers before removing them!

    References:
    - ASTM E178: Standard Practice for Dealing With Outlying Observations
    - Grubbs, F. (1969): Procedures for detecting outlying observations
    - Dean, R.B. and Dixon, W.J. (1951): Dixon's Q test
    """

    # Critical values for Dixon's Q test (alpha = 0.05)
    # Source: Dean & Dixon (1951), ASTM E178
    DIXON_Q_CRITICAL = {
        3: 0.970, 4: 0.829, 5: 0.710, 6: 0.625, 7: 0.568,
        8: 0.526, 9: 0.493, 10: 0.466, 11: 0.444, 12: 0.426,
        13: 0.410, 14: 0.396, 15: 0.384, 16: 0.374, 17: 0.365,
        18: 0.356, 19: 0.349, 20: 0.342, 21: 0.337, 22: 0.331,
        23: 0.326, 24: 0.321, 25: 0.317, 26: 0.312, 27: 0.308,
        28: 0.305, 29: 0.301, 30: 0.298
    }

    def __init__(self, alpha: float = 0.05):
        """
        Initialize detector.

        Args:
            alpha: Significance level (default 0.05 = 5%)
        """
        self.alpha = alpha

    def detect(
        self,
        data: Union[List[float], np.ndarray],
        method: OutlierMethod = OutlierMethod.MODIFIED_Z,
    ) -> OutlierResult:
        """
        Detect outliers using specified method.

        Args:
            data: Test data
            method: Detection method to use

        Returns:
            OutlierResult with detected outliers

        Raises:
            ValueError: If data is invalid or method not applicable
        """
        data = np.array(data)
        n = len(data)

        if n < 3:
            raise ValueError(f"Need at least 3 data points, got {n}")

        # Remove NaN values
        data = data[~np.isnan(data)]
        n = len(data)

        if method == OutlierMethod.GRUBBS:
            return self._grubbs_test(data)
        elif method == OutlierMethod.DIXON:
            return self._dixon_test(data)
        elif method == OutlierMethod.MODIFIED_Z:
            return self._modified_z_score(data)
        elif method == OutlierMethod.IQR:
            return self._iqr_method(data)
        elif method == OutlierMethod.ALL:
            return self._combined_detection(data)
        else:
            raise ValueError(f"Unknown method: {method}")

    def _grubbs_test(self, data: np.ndarray) -> OutlierResult:
        """
        Grubbs' test for detecting a single outlier.

        Tests the hypothesis that the most extreme value is an outlier.
        Assumes normal distribution.

        Reference: Grubbs, F.E. (1969), Technometrics 11(1):1-21
        """
        n = len(data)

        if n < 3:
            raise ValueError("Grubbs test requires n >= 3")

        mean = np.mean(data)
        std = np.std(data, ddof=1)

        # Calculate G statistic for maximum deviation
        abs_deviations = np.abs(data - mean)
        max_idx = np.argmax(abs_deviations)
        max_deviation = abs_deviations[max_idx]

        G = max_deviation / std if std > 0 else 0

        # Critical value from t-distribution
        t_crit = stats.t.ppf(1 - self.alpha / (2 * n), df=n - 2)
        G_crit = ((n - 1) / np.sqrt(n)) * np.sqrt(t_crit**2 / (n - 2 + t_crit**2))

        # Check if outlier
        is_outlier = G > G_crit

        if is_outlier:
            indices = [max_idx]
            values = [data[max_idx]]
            severity = [self._classify_severity(data[max_idx], data)]
            reason = f"Value {data[max_idx]:.4f} has G={G:.4f} > {G_crit:.4f}"
        else:
            indices = []
            values = []
            severity = []
            reason = f"No outlier detected (G={G:.4f} <= {G_crit:.4f})"

        return OutlierResult(
            indices=indices,
            values=values,
            method=OutlierMethod.GRUBBS,
            test_statistic=G,
            critical_value=G_crit,
            p_value=None,  # Grubbs test doesn't directly give p-value
            severity=severity,
            reason=reason,
        )

    def _dixon_test(self, data: np.ndarray) -> OutlierResult:
        """
        Dixon's Q test for small samples (n < 30).

        Tests if the most extreme value is significantly different
        from its neighbors.
import uuid

        Reference: Dean, R.B. and Dixon, W.J. (1951), Anal. Chem. 23(4):636-638
        """
        n = len(data)

        if n < 3 or n > 30:
            raise ValueError(f"Dixon test requires 3 <= n <= 30, got {n}")

        # Sort data
        sorted_data = np.sort(data)
        sorted_indices = np.argsort(data)

        # Test both extremes (lowest and highest)
        # Q = (gap to nearest neighbor) / (total range)

        # Test lowest value
        Q_low = (sorted_data[1] - sorted_data[0]) / (sorted_data[-1] - sorted_data[0])

        # Test highest value
        Q_high = (sorted_data[-1] - sorted_data[-2]) / (sorted_data[-1] - sorted_data[0])

        # Get critical value for this sample size
        Q_crit = self.DIXON_Q_CRITICAL.get(n, 0.298)  # Default to n=30 if larger

        # Determine which (if any) is an outlier
        outliers = []
        outlier_indices = []
        severity = []

        if Q_low > Q_crit:
            outliers.append(sorted_data[0])
            outlier_indices.append(sorted_indices[0])
            severity.append(self._classify_severity(sorted_data[0], data))

        if Q_high > Q_crit:
            outliers.append(sorted_data[-1])
            outlier_indices.append(sorted_indices[-1])
            severity.append(self._classify_severity(sorted_data[-1], data))

        max_Q = max(Q_low, Q_high)

        if outliers:
            reason = f"Q={max_Q:.4f} > {Q_crit:.4f}, outliers detected"
        else:
            reason = f"Q={max_Q:.4f} <= {Q_crit:.4f}, no outliers"

        return OutlierResult(
            indices=outlier_indices,
            values=outliers,
            method=OutlierMethod.DIXON,
            test_statistic=max_Q,
            critical_value=Q_crit,
            p_value=None,
            severity=severity,
            reason=reason,
        )

    def _modified_z_score(self, data: np.ndarray, threshold: float = 3.5) -> OutlierResult:
        """
        Modified Z-score using Median Absolute Deviation (MAD).

        More robust than standard Z-score for non-normal data.

        Reference: Iglewicz, B. and Hoaglin, D.C. (1993),
                   "How to Detect and Handle Outliers"

        Args:
            data: Input data
            threshold: Modified Z-score threshold (default 3.5)
        """
        median = np.median(data)

        # Median Absolute Deviation (MAD)
        mad = np.median(np.abs(data - median))

        # Modified Z-scores
        # Use 0.6745 as constant to make MAD consistent with std for normal dist
        if mad > 0:
            modified_z_scores = 0.6745 * (data - median) / mad
        else:
            # MAD = 0 means all values are identical
            modified_z_scores = np.zeros(len(data))

        # Find outliers
        outlier_mask = np.abs(modified_z_scores) > threshold
        outlier_indices = np.where(outlier_mask)[0].tolist()
        outlier_values = data[outlier_mask].tolist()

        max_z = np.max(np.abs(modified_z_scores))

        severity = [self._classify_severity(val, data) for val in outlier_values]

        if outlier_indices:
            reason = (
                f"{len(outlier_indices)} outlier(s) with "
                f"|Modified Z| > {threshold}"
            )
        else:
            reason = f"No outliers (max |Modified Z| = {max_z:.4f})"

        return OutlierResult(
            indices=outlier_indices,
            values=outlier_values,
            method=OutlierMethod.MODIFIED_Z,
            test_statistic=max_z,
            critical_value=threshold,
            p_value=None,
            severity=severity,
            reason=reason,
        )

    def _iqr_method(self, data: np.ndarray, k: float = 1.5) -> OutlierResult:
        """
        IQR (Interquartile Range) method with Tukey fences.

        Non-parametric method, doesn't assume normality.
        Standard choice for box plots.

        Args:
            data: Input data
            k: Fence multiplier (1.5 = mild outliers, 3.0 = extreme)
        """
        Q1 = np.percentile(data, 25)
        Q3 = np.percentile(data, 75)
        IQR = Q3 - Q1

        # Tukey fences
        lower_fence = Q1 - k * IQR
        upper_fence = Q3 + k * IQR

        # Find outliers
        outlier_mask = (data < lower_fence) | (data > upper_fence)
        outlier_indices = np.where(outlier_mask)[0].tolist()
        outlier_values = data[outlier_mask].tolist()

        # Calculate severity
        severity = [self._classify_severity(val, data) for val in outlier_values]

        # Max distance from fence (normalized by IQR)
        if len(outlier_values) > 0:
            distances = np.minimum(
                np.abs(data[outlier_mask] - lower_fence),
                np.abs(data[outlier_mask] - upper_fence)
            )
            max_distance = np.max(distances) / IQR if IQR > 0 else 0
        else:
            max_distance = 0

        if outlier_indices:
            reason = (
                f"{len(outlier_indices)} outlier(s) beyond "
                f"[{lower_fence:.4f}, {upper_fence:.4f}]"
            )
        else:
            reason = f"No outliers (all within Tukey fences)"

        return OutlierResult(
            indices=outlier_indices,
            values=outlier_values,
            method=OutlierMethod.IQR,
            test_statistic=max_distance,
            critical_value=k,
            p_value=None,
            severity=severity,
            reason=reason,
        )

    def _combined_detection(self, data: np.ndarray) -> OutlierResult:
        """
        Run multiple methods and combine results.

        An observation is flagged if ANY method identifies it as an outlier.
        """
        n = len(data)

        # Choose appropriate methods based on sample size
        if n <= 30:
            methods = [OutlierMethod.DIXON, OutlierMethod.MODIFIED_Z, OutlierMethod.IQR]
        else:
            methods = [OutlierMethod.GRUBBS, OutlierMethod.MODIFIED_Z, OutlierMethod.IQR]

        all_outlier_indices = set()
        reasons = []

        for method in methods:
            try:
                result = self.detect(data, method=method)
                all_outlier_indices.update(result.indices)
                if result.indices:
                    reasons.append(f"{method.value}: {len(result.indices)} outliers")
            except Exception as e:
                logger.warning(f"Method {method} failed: {e}")

        outlier_indices = sorted(list(all_outlier_indices))
        outlier_values = data[outlier_indices].tolist()
        severity = [self._classify_severity(val, data) for val in outlier_values]

        combined_reason = "; ".join(reasons) if reasons else "No outliers detected by any method"

        return OutlierResult(
            indices=outlier_indices,
            values=outlier_values,
            method=OutlierMethod.ALL,
            test_statistic=len(outlier_indices),
            critical_value=0,
            p_value=None,
            severity=severity,
            reason=combined_reason,
        )

    def _classify_severity(self, value: float, data: np.ndarray) -> OutlierSeverity:
        """Classify outlier severity based on IQR distance"""
        Q1 = np.percentile(data, 25)
        Q3 = np.percentile(data, 75)
        IQR = Q3 - Q1

        lower_mild = Q1 - 1.5 * IQR
        upper_mild = Q3 + 1.5 * IQR
        lower_extreme = Q1 - 3.0 * IQR
        upper_extreme = Q3 + 3.0 * IQR

        if value < lower_extreme or value > upper_extreme:
            return OutlierSeverity.EXTREME
        elif value < lower_mild or value > upper_mild:
            return OutlierSeverity.MILD
        else:
            return OutlierSeverity.NONE


# Example usage and self-test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Yield strength data with one outlier
    test_data = np.array([
        72.5, 74.2, 71.9, 73.7, 75.1, 72.8, 74.5, 73.2, 72.1,
        74.8, 73.5, 72.9, 89.3,  # <- Outlier (equipment error?)
        74.1, 73.8, 72.6, 75.3, 73.1, 74.6, 72.4
    ])

    detector = OutlierDetector()

    print(f"\n{'='*60}")
    print(f"Outlier Detection Results")
    print(f"{'='*60}")
    print(f"Data: n={len(test_data)}, mean={np.mean(test_data):.2f}, std={np.std(test_data, ddof=1):.2f}")
    print(f"{'='*60}\n")

    # Test all methods
    methods = [OutlierMethod.GRUBBS, OutlierMethod.MODIFIED_Z, OutlierMethod.IQR]

    for method in methods:
        result = detector.detect(test_data, method=method)
        print(f"{method.value.upper()} Test:")
        print(f"  Outliers: {result.values}")
        print(f"  Indices: {result.indices}")
        print(f"  Severity: {[s.value for s in result.severity]}")
        print(f"  Reason: {result.reason}\n")

    # Combined detection
    print("COMBINED Detection (all methods):")
    combined = detector.detect(test_data, method=OutlierMethod.ALL)
    print(f"  Outliers: {combined.values}")
    print(f"  Reason: {combined.reason}\n")
