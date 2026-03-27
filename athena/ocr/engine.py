#!/usr/bin/env python3
"""
Module: Engine
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import os
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import easyocr
from typing import Dict, List, Optional, Any, Tuple
import logging
import re
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class EngineeringOCR:
    """
    Specialized OCR engine for engineering documents and technical images
    Handles drawings, schematics, test photos, and technical diagrams
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.tesseract_config = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()-_/:'

        # Configure Tesseract (installed via winget as Windows App)
        self.tesseract_available = True
        try:
            pytesseract.pytesseract.tesseract_cmd = r'C:\Users\jwilde2\AppData\Local\Microsoft\WindowsApps\tesseract.bat'
            logger.info("Tesseract configured successfully")
        except Exception as e:
            logger.warning(f"Failed to configure Tesseract: {e} - will use EasyOCR only")
            self.tesseract_available = False

        # Initialize EasyOCR for better handling of technical text
        try:
            self.easyocr_reader = easyocr.Reader(['en'], gpu=True)
        except (RuntimeError, OSError):
            logger.warning("GPU not available for EasyOCR, using CPU")
            self.easyocr_reader = easyocr.Reader(['en'], gpu=False)

        # Engineering-specific patterns
        self.patterns = {
            'part_numbers': re.compile(r'\b[A-Z]{2,4}[-_]?\d{3,8}[-_]?[A-Z]?\d*\b'),
            'dimensions': re.compile(r'\d+\.?\d*\s*[x×]\s*\d+\.?\d*\s*[x×]?\s*\d*\.?\d*'),
            'tolerances': re.compile(r'[±]?\s*\d*\.?\d+\s*["\']?'),
            'materials': re.compile(r'\b(Al|Steel|Ti|Inconel|Hastelloy|SS|Aluminum|Titanium)\b', re.IGNORECASE),
            'temperatures': re.compile(r'\d+\.?\d*\s*[°]?\s*[FfCc]\b'),
            'pressures': re.compile(r'\d+\.?\d*\s*(psi|PSI|bar|BAR|Pa|kPa|MPa)\b'),
            'weights': re.compile(r'\d+\.?\d*\s*(lb|lbs|kg|g|oz)\b'),
            'nasa_standards': re.compile(r'\b(NASA[-_]?(STD|HDBK|TM|SP)[-_]?\d+[A-Z]?)\b'),
            'msfc_docs': re.compile(r'\b(MSFC[-_]?(STD|SPEC|HDBK|PRC)[-_]?\d+[A-Z]?)\b'),
        }

    def process_image(self, image_path: str) -> Dict[str, Any]:
        """
        Process engineering image with OCR and extract structured information
        """
        try:
            # Determine image type and processing strategy
            image_type = self._classify_image_type(image_path)

            # Load and preprocess image
            processed_image = self._preprocess_image(image_path, image_type)

            # Extract text using multiple OCR engines
            ocr_results = self._extract_text_multi_engine(processed_image)

            # Post-process and structure the extracted text
            structured_data = self._structure_extracted_text(ocr_results, image_type)

            # Add metadata
            metadata = self._extract_image_metadata(image_path)

            return {
                'image_path': image_path,
                'image_type': image_type,
                'metadata': metadata,
                'raw_text': ocr_results.get('combined_text', ''),
                'structured_data': structured_data,
                'confidence_score': ocr_results.get('avg_confidence', 0),
                'processing_notes': ocr_results.get('notes', [])
            }

        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}")
            return {
                'image_path': image_path,
                'error': str(e),
                'processed': False
            }

    def _classify_image_type(self, image_path: str) -> str:
        """
        Classify image type based on filename and initial analysis
        """
        filename_lower = Path(image_path).name.lower()

        # Drawing/Schematic indicators
        if any(keyword in filename_lower for keyword in
               ['drawing', 'dwg', 'schematic', 'diagram', 'blueprint', 'sketch']):
            return 'technical_drawing'

        # Test/Photo indicators
        elif any(keyword in filename_lower for keyword in
                 ['test', 'setup', 'experiment', 'specimen', 'sample']):
            return 'test_photo'

        # Weld-specific images
        elif any(keyword in filename_lower for keyword in
                 ['weld', 'fsw', 'joint', 'cross', 'section', 'macro', 'micro']):
            return 'weld_analysis'

        # Equipment/Tool photos
        elif any(keyword in filename_lower for keyword in
                 ['tool', 'equipment', 'machine', 'fixture', 'setup']):
            return 'equipment_photo'

        # Chart/Graph/Plot
        elif any(keyword in filename_lower for keyword in
                 ['chart', 'graph', 'plot', 'data', 'result']):
            return 'data_visualization'

        # Default
        else:
            return 'general_technical'

    def _preprocess_image(self, image_path: str, image_type: str) -> np.ndarray:
        """
        Preprocess image based on type for optimal OCR
        """
        # Load image
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not load image: {image_path}")

        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Apply preprocessing based on image type
        if image_type == 'technical_drawing':
            # High contrast, clean lines
            processed = self._preprocess_technical_drawing(gray)
        elif image_type == 'test_photo':
            # Handle various lighting conditions
            processed = self._preprocess_test_photo(gray)
        elif image_type == 'data_visualization':
            # Enhance text in charts/graphs
            processed = self._preprocess_data_viz(gray)
        else:
            # General preprocessing
            processed = self._preprocess_general(gray)

        return processed

    def _preprocess_technical_drawing(self, gray: np.ndarray) -> np.ndarray:
        """Preprocess technical drawings for OCR"""
        # Increase contrast
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)

        # Noise reduction
        denoised = cv2.fastNlMeansDenoising(enhanced)

        # Adaptive thresholding for clean text
        binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 11, 2)

        # Morphological operations to clean up
        kernel = np.ones((1,1), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return cleaned

    def _preprocess_test_photo(self, gray: np.ndarray) -> np.ndarray:
        """Preprocess test/equipment photos"""
        # Handle varying lighting
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)

        # Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(enhanced, (3,3), 0)

        # Adaptive threshold
        binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                      cv2.THRESH_BINARY, 15, 8)
        return binary

    def _preprocess_data_viz(self, gray: np.ndarray) -> np.ndarray:
        """Preprocess charts and data visualizations"""
        # Enhance contrast for text on plots
        enhanced = cv2.equalizeHist(gray)

        # Reduce noise
        denoised = cv2.medianBlur(enhanced, 3)

        # Binary threshold
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return binary

    def _preprocess_general(self, gray: np.ndarray) -> np.ndarray:
        """General preprocessing for unknown image types"""
        # Standard enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)

        # Light denoising
        denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

        # Adaptive threshold
        binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 11, 2)
        return binary

    def _extract_text_multi_engine(self, processed_image: np.ndarray) -> Dict[str, Any]:
        """
        Extract text using multiple OCR engines and combine results
        """
        results = {
            'tesseract_text': '',
            'easyocr_text': '',
            'combined_text': '',
            'avg_confidence': 0,
            'notes': []
        }

        try:
            # Tesseract OCR (only if available)
            if self.tesseract_available and pytesseract:
                tesseract_data = pytesseract.image_to_data(processed_image,
                                                          config=self.tesseract_config,
                                                          output_type=pytesseract.Output.DICT)

                tesseract_text = ' '.join([word for word in tesseract_data['text'] if word.strip()])
                tesseract_conf = np.mean([conf for conf in tesseract_data['conf'] if conf > 0])
            else:
                tesseract_text = ''
                tesseract_conf = 0

            results['tesseract_text'] = tesseract_text
            results['tesseract_confidence'] = tesseract_conf

        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")
            results['notes'].append(f"Tesseract failed: {e}")

        try:
            # EasyOCR
            easyocr_results = self.easyocr_reader.readtext(processed_image)
            easyocr_text = ' '.join([result[1] for result in easyocr_results])
            easyocr_conf = np.mean([result[2] for result in easyocr_results]) * 100

            results['easyocr_text'] = easyocr_text
            results['easyocr_confidence'] = easyocr_conf

        except Exception as e:
            logger.warning(f"EasyOCR failed: {e}")
            results['notes'].append(f"EasyOCR failed: {e}")

        # Combine results intelligently
        combined_text = self._combine_ocr_results(results['tesseract_text'],
                                                 results['easyocr_text'])
        results['combined_text'] = combined_text

        # Calculate average confidence
        confidences = []
        if 'tesseract_confidence' in results:
            confidences.append(results['tesseract_confidence'])
        if 'easyocr_confidence' in results:
            confidences.append(results['easyocr_confidence'])

        results['avg_confidence'] = np.mean(confidences) if confidences else 0

        return results

    def _combine_ocr_results(self, tesseract_text: str, easyocr_text: str) -> str:
        """
        Intelligently combine results from multiple OCR engines
        """
        if not tesseract_text and not easyocr_text:
            return ""

        if not tesseract_text:
            return easyocr_text
        if not easyocr_text:
            return tesseract_text

        # Simple combination - could be enhanced with more sophisticated merging
        # For now, prefer EasyOCR for technical text, fallback to Tesseract
        if len(easyocr_text) > len(tesseract_text) * 0.8:
            return easyocr_text
        else:
            return tesseract_text

    def _structure_extracted_text(self, ocr_results: Dict, image_type: str) -> Dict[str, Any]:
        """
        Structure the extracted text using engineering-specific patterns
        """
        text = ocr_results.get('combined_text', '')

        structured = {
            'part_numbers': self._extract_pattern_matches(text, 'part_numbers'),
            'dimensions': self._extract_pattern_matches(text, 'dimensions'),
            'materials': self._extract_pattern_matches(text, 'materials'),
            'temperatures': self._extract_pattern_matches(text, 'temperatures'),
            'pressures': self._extract_pattern_matches(text, 'pressures'),
            'nasa_standards': self._extract_pattern_matches(text, 'nasa_standards'),
            'msfc_docs': self._extract_pattern_matches(text, 'msfc_docs'),
            'numeric_values': self._extract_numeric_values(text),
            'text_summary': self._summarize_text(text, image_type)
        }

        return structured

    def _extract_pattern_matches(self, text: str, pattern_name: str) -> List[str]:
        """Extract matches for a specific pattern"""
        if pattern_name not in self.patterns:
            return []

        matches = self.patterns[pattern_name].findall(text)
        return list(set(matches))  # Remove duplicates

    def _extract_numeric_values(self, text: str) -> List[str]:
        """Extract all numeric values that might be measurements"""
        numeric_pattern = re.compile(r'\d+\.?\d*\s*[a-zA-Z]*')
        return numeric_pattern.findall(text)

    def _summarize_text(self, text: str, image_type: str) -> str:
        """Create a summary of extracted text"""
        if len(text) <= 200:
            return text

        # Extract key sentences/phrases
        sentences = re.split(r'[.!?]+', text)
        key_sentences = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10:  # Meaningful content
                # Prioritize sentences with technical content
                if any(pattern.search(sentence) for pattern in self.patterns.values()):
                    key_sentences.append(sentence)
                elif len(key_sentences) < 3:  # Fill with other content if needed
                    key_sentences.append(sentence)

        return '. '.join(key_sentences[:3]) + ('.' if key_sentences else '')

    def _extract_image_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extract basic image metadata"""
        try:
            with Image.open(image_path) as img:
                metadata = {
                    'width': img.width,
                    'height': img.height,
                    'format': img.format,
                    'mode': img.mode,
                    'size_mb': os.path.getsize(image_path) / (1024 * 1024)
                }

                # Extract EXIF if available
                if hasattr(img, '_getexif') and img._getexif():
                    exif = img._getexif()
                    if exif:
                        metadata['has_exif'] = True
                        # Extract relevant EXIF data
                        if 306 in exif:  # DateTime
                            metadata['datetime'] = str(exif[306])
                        if 271 in exif:  # Make
                            metadata['camera_make'] = str(exif[271])

                return metadata

        except Exception as e:
            return {'error': f"Could not extract metadata: {e}"}

    def batch_process_images(self, image_paths: List[str],
                           max_workers: int = 4) -> List[Dict[str, Any]]:
        """
        Process multiple images in parallel
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {executor.submit(self.process_image, path): path
                             for path in image_paths}

            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error processing {path}: {e}")
                    results.append({
                        'image_path': path,
                        'error': str(e),
                        'processed': False
                    })

        return results

def create_ocr_integration_config() -> Dict[str, Any]:
    """
    Create configuration for integrating OCR into Athena's hybrid system
    """
    return {
        'ocr_settings': {
            'enabled': True,
            'batch_size': 50,  # Process images in batches
            'max_image_size_mb': 10,  # Skip very large images
            'min_confidence_threshold': 30,  # Minimum OCR confidence
            'cache_results': True,
            'cache_ttl_days': 30
        },

        'processing_priorities': {
            'technical_drawing': 1,    # Highest priority
            'data_visualization': 2,
            'test_photo': 3,
            'weld_analysis': 3,
            'equipment_photo': 4,
            'general_technical': 5
        },

        'integration_with_discovery': {
            'add_to_document_index': True,  # Add OCR text to discovery index
            'create_separate_image_index': True,  # Separate searchable image index
            'link_to_parent_documents': True,  # Link images to containing documents
            'extract_image_metadata': True
        },

        'search_enhancements': {
            'enable_image_search': True,
            'search_extracted_text': True,
            'search_technical_patterns': True,  # Part numbers, standards, etc.
            'include_in_main_results': True
        }
    }