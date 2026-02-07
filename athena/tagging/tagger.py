#!/usr/bin/env python3
"""
Module: Tagger
Purpose: Document tagging and classification engine

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-033 (Requirements Traceability)
Safety Critical: True
"""

# Copyright 2025 BoundStateAI

"""
Document tagging and classification engine
Enhanced with Amentum/NASA contractor documentation support
Applies pattern-based rules and plugin-based extensions for document categorization
Compliance: SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.0 <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI o3/4.0/4.5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI


Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
import json
import os
import glob
import importlib.util
import re
import uuid
from typing import List, Dict, Any, Tuple
from pathlib import Path
from boundstate.config import CONFIG
import logging

# Import TQP detection
# Configurable domain pattern detection - no hardcoded rules!
def _load_domain_patterns():
    """Load domain-specific patterns from config

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    import json
    
    config_paths = [
        Path("config/domain_patterns.json"),
        Path(__file__).parent.parent / "config" / "domain_patterns.json"
    ]
    
    for path in config_paths:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
    
    # Minimal fallback
    return {
        "acronym_detection": {
            "tqp": {
                "patterns": [{"regex": "\\bT\\.?Q\\.?P\\.?\\b", "weight": 0.2}],
                "threshold": 0.3
            }
        }
    }

def tqp_decision(text: str, threshold: float = None) -> dict:
    """Configurable TQP detection using domain patterns config

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    import re
    
    patterns_config = _load_domain_patterns()
    tqp_config = patterns_config.get("acronym_detection", {}).get("tqp", {})
    
    if threshold is None:
        threshold = tqp_config.get("threshold", 0.3)
    
    patterns = tqp_config.get("patterns", [])
    
    score = 0.0
    evidence = []
    
    for pattern_config in patterns:
        pattern = pattern_config.get("regex", "")
        weight = pattern_config.get("weight", 0.1)
        description = pattern_config.get("description", "")
        
        try:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                score += weight
                evidence.append({
                    'pattern': pattern,
                    'description': description,
                    'match': match.group(),
                    'span': match.span(),
                    'weight': weight
                })
        except re.error:
            continue  # Skip invalid regex patterns
    
    return {
        'decision': 'present' if score >= threshold else 'absent',
        'confidence': min(score, 1.0),
        'score': score,
        'evidence': evidence
    }

def tqp_evidence(text: str) -> list:
    """Extract TQP evidence from text

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    result = tqp_decision(text)
    return result.get('evidence', [])

# Generic acronym detection
ACRONYM_RE = re.compile(r'\b[A-Z]{2,}[0-9]*\b')  # 2+ capitals, optional trailing digits
DOC_ID_RE = re.compile(r'\b[GPWTF]\d{4}(?:\.\d+[A-Z]?)?(?:\s*r\d+)?\b', re.I)  # Document IDs

def find_acronyms(text: str) -> set:
    """Find all acronyms in text (2+ capitals, optional digits), excluding document IDs.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    # Find all potential acronyms
    potential_acronyms = set(ACRONYM_RE.findall(text))
    
    # Find all document IDs
    doc_ids = set(DOC_ID_RE.findall(text))
    
    # Remove document IDs from acronyms
    acronyms = potential_acronyms - doc_ids
    
    # Also remove common patterns that aren't real acronyms
    exclude_patterns = {
        r'^[A-Z]\d+$',  # A1, B2, etc. (cell references)
        r'^\d+[A-Z]+$',  # 1A, 2B, etc.
        r'^[IVX]+$',    # Roman numerals
    }
    
    filtered_acronyms = set()
    for acronym in acronyms:
        # Check if it matches any exclude pattern
        exclude = False
        for pattern in exclude_patterns:
            if re.match(pattern, acronym):
                exclude = True
                break
        
        if not exclude:
            filtered_acronyms.add(acronym)
    
    return filtered_acronyms

# Enhanced tag weights for Amentum/NASA + EM32 Manufacturing documentation
TAG_WEIGHTS = {
    # EM32 Manufacturing specific - HIGHEST PRIORITY
    "Friction_Welding": 1.5,
    "Manufacturing_Tools": 1.3,
    "Maintenance_Operations": 1.2,

    # Amentum/NASA specific - HIGH PRIORITY
    "Task_Order_Management": 1.2,
    "Cost_Estimation": 1.1,
    "Quality_Planning": 1.1,
    "Engineering_Aids": 1.0,
    "Product_Development": 1.0,
    "NASA_Contractor": 0.9,
    "Aerospace_Engineering": 0.9,
    "ESSCA_Contract": 1.0,
    "ASED_Process": 1.0,
    "Verification_Control": 1.0,
    "Criticality_Assessment": 1.0,
    "Safety_Critical": 1.1,
    "Finance": 1.0,
    "Procurement": 0.8,
    "ODC": 0.9,
    "Training": 1.0,
    "Travel": 1.0,
    "HR": 0.9,
    "Subcontractor": 0.8,
    "IWA": 0.9,
    "Project_Management": 0.9,
    "Task_Order": 1.0,
    "Contract": 0.8,
    "Materials": 0.9,
    "Equipment": 0.9,
    "Relocation": 0.9,
    "Labor": 0.9,
    "References": 0.7,
    "JTOMS": 0.8,
    "J-Plan": 0.8,
    "Engineering": 0.7,
    "Safety": 0.7,
    "Quality": 0.7,
    "Technology": 0.6,
    "Research": 0.6,
    "form_document": 0.8,
    "questionnaire": 0.9,
    "task_folder_guideline": 0.8,
    "travel_policy": 0.9,
    "time_recording_policy": 0.9,
    "audit": 0.8,
    "form": 0.8,
    "checklist": 0.8,
    "procurement_table": 0.9,
    "schedule_table": 0.9,
    "requirements_table": 0.9,
    "labor_table": 0.9,
    "cost_table": 0.9,
    # Standards and compliance
    "NASA_STD": 0.9,
    "MIL_STD": 0.9,
    "ASTM": 0.8,
    "AS9100": 1.0,
    "ISO": 0.8,
    # Additional tags - Higher priority for estimation tags
    "Labor_Estimation": 1.3,  # Increased to outrank generic Labor
    "Travel_Cost": 1.2  # Increased to ensure visibility
}

# Domain-specific keywords help boost or penalize tags when particular
# vocabulary is present or absent.
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    # EM32 Manufacturing specific - HIGHEST PRIORITY
    'Friction_Welding': ['friction pull plug', 'friction stir welding', 'fsw', 'friction welding',
                        'pull plug', 'weld program', 'welding technician', 'weld tool'],
    'Manufacturing_Tools': ['pds', 'rwt', 'hwt', 'vwt', 'tui', 'tool user interface',
                           'mandrel', 'fixture', 'clamp', 'slider', 'holding fixture',
                           'barrel clocking', 'drive ring', 'platform'],
    'Maintenance_Operations': ['maintenance checklist', 'maintenance training', 'maintenance record',
                              'chiller', 'accumulator', 'pump specs', 'baseline settings',
                              'grounding check', 'calibration'],

    # Amentum/NASA specific
    'Task_Order_Management': ['task order', 'sub-task', 'jtoms', 'tqp', 'release authority',
                            'task lead', 'team lead', 'department manager', 'ddm'],
    'Cost_Estimation': ['estimate', 'j-plan', 'labor hour', 'nte', 'eac', 'boe',
                      'productive hours', 'accounting month', 'labor rate'],
    'Quality_Planning': ['quality plan', 'controlling document', 'verification', 'as9100',
                       'product verification', 'release approval', 'quality system'],
    'Engineering_Aids': ['engineering aid', 'criticality', 'impact assessment', 'peer review',
                       'low criticality', 'medium criticality', 'high criticality'],
    'NASA_Contractor': ['nasa', 'msfc', 'essca', 'ased', 'amentum', 'marshall'],
    'Aerospace_Engineering': ['aerospace', 'spacecraft', 'launch vehicle', 'flight hardware'],
    'Product_Development': ['product development', 'formal product', 'informal product',
                          'product release', 'living product', 'product id'],
    'Verification_Control': ['verification', 'validation', 'inspection', 'nonconforming',
                           'review checklist', 'final inspection'],
    'Safety_Critical': ['safety critical', 'hazard', 'mishap', 'product safety',
                      'failure mode', 'risk assessment'],
    'ESSCA_Contract': ['essca', 'contract year', 'period of performance', 'cy'],
    'ASED_Process': ['ased', 'p7', 'w7', 'g7', 'f7'],
    # Labour estimation keywords - expanded
    'Labor_Estimation': ['labor estimation', 'labor estimate', 'labor hour', 'labor hours',
                         'fte', 'fte estimate', 'hours per', 'productive hour',
                         'estimate', 'estimates', 'estimation', 'man-hours', 'person-hours',
                         'level of effort', 'loe', 'work estimate', 'resource estimate'],
    # Travel cost keywords - expanded
    'Travel_Cost': ['travel cost', 'travel costs', 'travel expense', 'travel expenses',
                   'per diem', 'lodging cost', 'mileage reimbursement', 'flight cost',
                   'travel budget', 'travel allowance', 'trip expense', 'transportation cost',
                   'hotel cost', 'airfare', 'travel reimbursement', 'travel funding'],
    # Existing domain keywords
    'Research': ['experiment', 'study', 'research', 'development'],
    'Safety': ['hazard', 'risk', 'safety', 'accident'],
    'Engineering': ['design', 'engineering', 'technical', 'specification'],
    'Technology': ['software', 'hardware', 'system', 'technology'],
    'Quality': ['quality', 'qa', 'quality assurance', 'quality control'],
    'Technical_Spec': ['specification', 'technical', 'mil-std', 'nasa-std'],
    'Government': ['government', 'federal', 'nasa', 'contract'],
    'Aerospace': ['aerospace', 'aviation', 'spacecraft', 'rocket']
}

logger = logging.getLogger(__name__)

class ZeroShotTagger:
    """Zero-shot tagger for document chunks without prior knowledge.

    Compliance: SWE-013, SWE-033
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    def __init__(self, llm_client=None, embedding_model: str = "all-MiniLM-L6-v2"):
        self.llm_client = llm_client
        try:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer(embedding_model)
            logger.info(f"Loaded embedder for tagging: {embedding_model}")
        except Exception as e:
            logger.warning(f"Failed to load embedder: {e}")
            self.embedder = None

    def tag_sections(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Infer tags for sections using clustering and keyword extraction.

        Args:
            sections: List of section dicts with text, metadata

        Returns:
            Sections with added tags
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        if not sections:
            return sections

        texts = [sec.get('text', '') for sec in sections]
        tags = self._infer_tags(texts)

        for sec, sec_tags in zip(sections, tags):
            if 'tags' not in sec:
                sec['tags'] = []
            sec['tags'].extend(sec_tags)
            sec['tags'] = list(set(sec['tags']))[:5]
            logger.debug(f"Section {sec.get('section', 'unknown')} tagged: {sec['tags']}",
                        extra={'req_id': f'tag-{sec.get("doc_id", "unknown")}'})

        return sections

    def _infer_tags(self, texts: List[str]) -> List[List[str]]:
        """Infer tags via embeddings and keywords.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        try:
            from sklearn.cluster import KMeans
        except ImportError:
            logger.warning("sklearn not available, using basic keyword tagging only")
            return self._basic_keyword_tags(texts)
            
        base_tags = self._basic_keyword_tags(texts)

        if not self.embedder or len(texts) < 2:
            return base_tags

        try:
            embeddings = self.embedder.encode(texts, batch_size=CONFIG['batch_size'])
            n_clusters = min(5, len(texts) // 2)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            clusters = kmeans.fit_predict(embeddings)

            cluster_texts = [[] for _ in range(n_clusters)]
            for i, cluster_id in enumerate(clusters):
                cluster_texts[cluster_id].append(texts[i])

            cluster_tags = []
            for cluster_text in cluster_texts:
                cluster_summary = ' '.join(cluster_text[:3])[:1000]
                tags = self._extract_cluster_keywords(cluster_text)
                if self.llm_client:
                    prompt = f"""Generate 2-3 tags for this engineering/policy doc cluster (e.g., material_spec, test_report, travel_policy, tqp_policy):
                    Text: {cluster_summary}
                    Output: comma-separated tags

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
                    try:
                        response = self.llm_client.generate(prompt)
                        tags = [t.strip() for t in response.split(',') if t.strip()][:3]
                    except Exception as e:
                        logger.error(f"LLM tag failed: {e}", extra={'req_id': str(uuid.uuid4())})
                cluster_tags.append(tags)

            result_tags = []
            for cluster_id in clusters:
                result_tags.append(list(set(base_tags[cluster_id] + cluster_tags[cluster_id])))

            return result_tags
        except Exception as e:
            logger.error(f"Clustering failed: {e}", extra={'req_id': str(uuid.uuid4())})
            return base_tags

    def _basic_keyword_tags(self, texts: List[str]) -> List[List[str]]:
        """Fallback keyword-based tagging with engineering/policy terms.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        keywords = {
            'material_spec': ['material', 'spec', 'tensile', 'yield', 'ASTM'],
            'test_report': ['test', 'report', 'fatigue', 'results', 'data'],
            'design': ['design', 'drawing', 'CAD', 'schematic'],
            'compliance': ['compliance', 'regulation', 'standard', 'NASA'],
            'travel_policy': ['travel', 'TDY', 'per diem', 'reimbursement'],
            'tqp_policy': ['tqp', 'technical qualification program']
        }
        result = []
        for text in texts:
            tags = []
            text_lower = text.lower()
            for tag, words in keywords.items():
                if any(word in text_lower for word in words):
                    tags.append(tag)
            result.append(tags)
        return result

    def _extract_cluster_keywords(self, texts: List[str]) -> List[str]:
        """Extract top keywords for a cluster.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        from collections import Counter
        words = ' '.join(texts).lower()
        words = re.findall(r'\b\w+\b', words)
        common = {'the', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'of'}
        word_counts = Counter(word for word in words if word not in common and len(word) > 3)
        return [word for word, _ in word_counts.most_common(3)]

class Tagger:
    """Document tagging and classification engine.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    
    @staticmethod
    def _calculate_tag_score(tag: str, text: str, title: str, metadata: Dict[str, Any], matches: int) -> float:
        """Calculate comprehensive tag score based on multiple factors.
        
        Args:
            tag: Tag name
            text: Section text
            title: Section title
            metadata: Section metadata
            matches: Number of regex matches
            
        Returns:
            Calculated score
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        base_score = matches * TAG_WEIGHTS.get(tag, 0.5)
        
        # Boost Amentum-specific tags when document patterns match
        amentum_tags = ['Task_Order_Management', 'Cost_Estimation', 'Quality_Planning', 
                       'Engineering_Aids', 'Product_Development', 'ASED_Process']
        if tag in amentum_tags:
            # Check for document identifiers
            if re.search(r'\b[PGWF]\d{4}\.\d+\b', text):
                base_score *= 1.5
        
        # Title boost
        if any(keyword in title.lower() for keyword in tag.lower().split('_')):
            base_score *= 1.5
        
        # Table context boost
        if metadata.get('has_table') or metadata.get('table_data'):
            if tag in ['procurement_table', 'schedule_table', 'requirements_table', 'Materials', 'Equipment', 'ODC']:
                base_score *= 1.3
        
        # Structured form boost
        if metadata.get('is_structured_form') and tag in ['form', 'questionnaire', 'checklist']:
            base_score *= 1.4
        
        return base_score
    
    @staticmethod
    def apply_tags(sections: List[Dict[str, Any]], rules: List[Tuple[str, re.Pattern]]) -> List[Dict[str, Any]]:
        """Apply tagging rules to document sections.
        
        Args:
            sections: List of section dictionaries
            rules: List of (tag, regex) tuples
            
        Returns:
            Tagged sections
            
        Compliance: SWE-033
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        max_tags = CONFIG.get('max_tags_per_section', 5)
        # Use the global DOMAIN_KEYWORDS mapping
        domain_keywords = DOMAIN_KEYWORDS

        for sec in sections:
            text_lower = sec.get('text', '').lower()
            title_lower = sec.get('title', '').lower()
            metadata = sec.get('metadata', {})
            tag_scores = {}
            
            # Check table context first for better precision
            # Preserve metadata by copying all keys so nothing is lost
            if 'metadata' not in sec:
                sec['metadata'] = {}
            if metadata:
                for k, v in metadata.items():
                    sec['metadata'][k] = v
            
            table_context = metadata.get('table_context', {})
            if table_context:
                headers = table_context.get('headers', [])
                # Normalize headers and derive high-level signals
                norm_headers = [h.lower() if isinstance(h, str) else '' for h in headers]
                has_labor_hdr = any(re.search(r'\b(labor|labour|hours?|rate)\b', h) for h in norm_headers)
                has_cost_hdr = any(re.search(r'\b(cost|price|budget|total cost|estimate)\b', h) for h in norm_headers)
                has_proc_hdr = any(re.search(r'\b(vendor|supplier|item|part|material|equipment|component|description)\b', h)
                                   for h in norm_headers)

                # Assign labour_table when labour-related columns present
                if has_labor_hdr:
                    tag_scores['labor_table'] = TAG_WEIGHTS.get('labor_table', 0.9) * 1.5

                # Assign cost_table on cost columns; boost if labour columns also present
                if has_cost_hdr:
                    multiplier = 1.8 if has_labor_hdr else 1.5
                    tag_scores['cost_table'] = TAG_WEIGHTS.get('cost_table', 0.9) * multiplier

                # Assign procurement_table only if procurement-specific headers detected
                if has_proc_hdr:
                    tag_scores['procurement_table'] = TAG_WEIGHTS.get('procurement_table', 0.9) * 1.5

                # Assign schedule/requirements tables based on explicit indicators
                if any(re.search(r'\b(date|schedule|deadline|timeline)\b', h) for h in norm_headers):
                    tag_scores['schedule_table'] = TAG_WEIGHTS.get('schedule_table', 0.9) * 1.5
                if any(re.search(r'\b(requirement|spec|specification)\b', h) for h in norm_headers):
                    tag_scores['requirements_table'] = TAG_WEIGHTS.get('requirements_table', 0.9) * 1.5
            
            # FORCE Amentum-specific tags based on document content patterns
            # Check for task order related content
            if any(term in text_lower for term in ['task order', 'ased', 'to revision', 'task lead']):
                tag_scores['Task_Order_Management'] = TAG_WEIGHTS.get('Task_Order_Management', 1.2) * 2.0
            
            # Check for cost/estimation content
            if any(term in text_lower for term in ['estimate', 'labor hour', 'cost', 'budget', 'nte']):
                tag_scores['Cost_Estimation'] = TAG_WEIGHTS.get('Cost_Estimation', 1.1) * 2.0
                # Also boost Labor_Estimation when estimation keywords present
                if any(term in text_lower for term in ['labor', 'hour', 'fte', 'estimate', 'man-hour']):
                    tag_scores['Labor_Estimation'] = TAG_WEIGHTS.get('Labor_Estimation', 1.3) * 1.5
            
            # Check for engineering aids content
            if any(term in text_lower for term in ['engineering aid', 'ea ', 'criticality', 'p7208']):
                tag_scores['Engineering_Aids'] = TAG_WEIGHTS.get('Engineering_Aids', 1.0) * 2.0
            
            # Check for quality planning content
            if any(term in text_lower for term in ['quality plan', 'tqp', 'p7301', 'controlling document']):
                tag_scores['Quality_Planning'] = TAG_WEIGHTS.get('Quality_Planning', 1.1) * 2.0
                tag_scores['TQP'] = TAG_WEIGHTS.get('TQP', 1.0) * 1.5
            
            # Check for product development content
            if any(term in text_lower for term in ['product development', 'p7103', 'verification', 'non-hardware']):
                tag_scores['Product_Development'] = TAG_WEIGHTS.get('Product_Development', 1.0) * 2.0
            
            # Check for ASED process indicators
            if re.search(r'\b[PGW]\d{4}\.\d+\b', text_lower):
                tag_scores['ASED_Process'] = TAG_WEIGHTS.get('ASED_Process', 1.0) * 1.5
            
            for tag, pattern in rules:
                matches = len(pattern.findall(text_lower))
                if matches > 0:
                    score = Tagger._calculate_tag_score(tag, text_lower, title_lower, metadata, matches)
                    
                    # Boost domain-specific tags when keywords are present
                    # Domain keyword verification
                    if tag in domain_keywords and not any(kw in text_lower for kw in domain_keywords[tag]):
                        score *= 0.3  # Stronger penalty if no domain keywords
                    elif tag in domain_keywords and any(kw in text_lower for kw in domain_keywords[tag]):
                        score *= 1.2  # Boost if domain keywords present
                    
                    # Special handling for document type patterns
                    if 'p7103' in text_lower and tag == 'Product_Development':
                        score *= 2.0
                    elif 'p7208' in text_lower and tag == 'Engineering_Aids':
                        score *= 2.0
                    elif 'p7301' in text_lower and tag == 'Quality_Planning':
                        score *= 2.0
                    elif 'g7102' in text_lower and tag == 'Task_Order_Management':
                        score *= 2.0
                    
                    # Accumulate scores for tags that appear multiple times
                    tag_scores[tag] = tag_scores.get(tag, 0) + score
            
            sorted_tags = sorted(tag_scores.items(), key=lambda x: x[1], reverse=True)[:max_tags]
            sec['tags'] = [tag for tag, _ in sorted_tags]
            
            # Log tag scores for debugging
            if tag_scores:
                logger.debug(
                    f"Section {sec.get('section', 'unknown')} tags: {sec['tags']} (scores: {tag_scores})",
                    extra={'req_id': f'tag-{sec.get("doc_id", "unknown")}'}
                )
        
        return sections
    
    @staticmethod
    def tag_forms_and_questionnaires(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect and tag forms, questionnaires, and audit checklists.
        
        Args:
            sections: List of section dictionaries
            
        Returns:
            Sections with form-related tags
            
        Compliance: SWE-033
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        form_patterns = [
            (re.compile(r'^\d+\.\d+\s+[^?]+\?', re.MULTILINE), "questionnaire"),
            (re.compile(r'\b(audit|checklist|assessment|evaluation form)\b', re.IGNORECASE), "audit"),
            (re.compile(r'\b(yes\s*/\s*no|check\s+one|select\s+all|fill\s+in)\b', re.IGNORECASE), "form"),
            (re.compile(r'□|☐|☑|☒|\[\s*\]|\[x\]', re.IGNORECASE), "checklist"),
            (re.compile(r'Overall Section Score:.*?(?:Acceptable|Not Acceptable)', re.IGNORECASE), "score"),
        ]
        
        for sec in sections:
            text_lower = sec.get('text', '').lower()
            title_lower = sec.get('title', '').lower()
            metadata = sec.get('metadata', {})
            tag_scores = {}

            if sec.get('doc_type') == 'form':
                tag_scores['form'] = TAG_WEIGHTS.get('form', 0.5)
            
            for pattern, tag in form_patterns:
                matches = len(pattern.findall(sec.get('text', '')))
                if matches > 0:
                    tag_scores[tag] = Tagger._calculate_tag_score(tag, text_lower, title_lower, metadata, matches)
            
            numbered_pattern = re.compile(r'^\d+\.\d+\s+', re.MULTILINE)
            if len(numbered_pattern.findall(sec.get('text', ''))) > 3:
                tag_scores['questionnaire'] = TAG_WEIGHTS.get('questionnaire', 0.5) * 1.5
            
            hr_patterns = [
                # Restrict travel_policy to explicit policy/guidelines wording only
                (re.compile(r'\b(travel\s+(?:policy|policies)|travel\s+authorization\s+(?:procedure|process)|travel\s+guidelines?|employee\s+travel\s+(?:policy|guideline))\b', re.IGNORECASE), "travel_policy"),
                # New pattern to capture travel cost and expenses - expanded
                (re.compile(r'\b(travel\s*costs?|travel\s*expenses?|per\s*diem|lodging\s*cost|'
                           r'mileage\s*(?:reimbursement)?|flight\s*cost|travel\s*budget|travel\s*allowance|'
                           r'trip\s*expense|hotel\s*cost|airfare)\b', re.IGNORECASE), "Travel_Cost"),
                (re.compile(r'\b(time recording|timecard|overtime|compensatory time|PTO)\b', re.IGNORECASE), "time_recording_policy"),
                (re.compile(r'\b(telework|remote work|work from home)\b', re.IGNORECASE), "telework_policy"),
                (re.compile(r'\b(basware|p2p|purchase to pay)\b', re.IGNORECASE), "procurement_guideline"),
                (re.compile(r'\b(subcontractor|vendor management|third-party contract)\b', re.IGNORECASE), "subcontractor_guideline"),
                (re.compile(r'\b(task folder|task management|project folder)\b', re.IGNORECASE), "task_folder_guideline"),
                (re.compile(r'\b(MAF travel|mission travel|flight authorization)\b', re.IGNORECASE), "maf_travel_guideline"),
            ]
            for pattern, tag in hr_patterns:
                matches = len(pattern.findall(text_lower))
                if matches > 0:
                    tag_scores[tag] = Tagger._calculate_tag_score(tag, text_lower, title_lower, metadata, matches)
            
            # Final tag assignment - merge with existing tags
            max_tags = CONFIG.get('max_tags_per_section', 5)
            current_tags = {tag: TAG_WEIGHTS.get(tag, 0.5) for tag in sec.get('tags', [])}
            current_tags.update(tag_scores)
            sec['tags'] = [tag for tag, _ in sorted(current_tags.items(), key=lambda x: x[1], reverse=True)[:max_tags]]
        
        return sections
    
    @staticmethod
    def process_table_metadata(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process and tag sections with table metadata for structured queries.
        
        Args:
            sections: List of section dictionaries
            
        Returns:
            Sections with table-related tags
            
        Compliance: SWE-033
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        for sec in sections:
            text_lower = sec.get('text', '').lower()
            title_lower = sec.get('title', '').lower()
            metadata = sec.get('metadata', {})
            tag_scores = {}

            # Enhanced table detection: require multiple pipe-delimited lines or many pipes
            text_raw = sec.get('text', '')
            lines = text_raw.split('\n')
            pipe_lines = [l for l in lines if '|' in l]
            pipe_count = text_raw.count('|')
            has_pipe_table = (pipe_count > 10) or (len(pipe_lines) >= 2)
            has_table = (
                metadata.get('table_data') or
                metadata.get('has_table') or
                metadata.get('is_structured_form') or
                has_pipe_table
            )
            
            if has_table:
                # Ensure table tag gets high priority when table is detected
                tag_scores['table'] = TAG_WEIGHTS.get('table', 0.5) * 2.0
                
                # Copy all metadata keys to preserve context
                if 'metadata' not in sec:
                    sec['metadata'] = {}
                if metadata:
                    for k, v in metadata.items():
                        sec['metadata'][k] = v
                
                # Use table context if available
                table_context = metadata.get('table_context', {})
                aggregate_context = metadata.get('aggregate_context', {})
                
                # Combine all available text sources
                table_text = text_lower
                if metadata.get('table_data'):
                    table_text += ' ' + str(metadata.get('table_data', '')).lower()
                
                # Smart procurement detection – require vendor/supplier/item cues
                if any(word in table_text for word in
                       ['vendor', 'supplier', 'vendor name', 'supplier name',
                        'item', 'part', 'material', 'equipment', 'component']):
                    score = TAG_WEIGHTS.get('procurement_table', 0.9)
                    if table_context.get('has_numbers'):
                        score *= 1.3
                    tag_scores['procurement_table'] = score

                # Smart cost table detection – detect cost terms without procurement signals
                if any(word in table_text for word in ['cost', 'price', 'budget', 'total cost', 'estimate']):
                    labour_signals = ['labor', 'labour', 'hour', 'hours', 'rate']
                    has_labour = any(sig in table_text for sig in labour_signals)
                    score = TAG_WEIGHTS.get('cost_table', 0.9)
                    if has_labour:
                        score *= 1.6
                    tag_scores['cost_table'] = max(tag_scores.get('cost_table', 0), score)
                
                # Smart schedule detection
                if any(word in table_text for word in ['date', 'schedule', 'timeline', 'deadline']) or table_context.get('has_dates'):
                    score = TAG_WEIGHTS.get('schedule_table', 0.9)
                    if aggregate_context.get('has_dates'):
                        score *= 1.4
                    tag_scores['schedule_table'] = score
                
                # Smart requirements detection
                if any(word in table_text for word in ['requirement', 'shall', 'must', 'specification']):
                    score = TAG_WEIGHTS.get('requirements_table', 0.9)
                    tag_scores['requirements_table'] = score
                
                # Apply granular table tags from table_text
                for tag, pattern in [
                    ('Materials', re.compile(r'\b(materials|material|equipment|hardware|components)\b', re.IGNORECASE)),
                    ('Equipment', re.compile(r'\b(equipment|tools|machinery|devices)\b', re.IGNORECASE)),
                    ('ODC', re.compile(r'\b(other direct costs?|ODC)\b', re.IGNORECASE)),
                    ('Travel', re.compile(r'\b(travel|per diem|lodging|mileage|expense report)\b', re.IGNORECASE)),
                    # Additional granular tag for travel costs within tables - expanded
                    ('Travel_Cost', re.compile(r'\b(travel\s*costs?|per\s*diem|lodging\s*cost|'
                                             r'mileage\s*(?:reimbursement)?|flight\s*cost|travel\s*budget|'
                                             r'hotel\s*cost|airfare|travel\s*expense)\b', re.IGNORECASE)),
                    ('Subcontractor', re.compile(r'\b(subcontractor|vendor management|third-party contract)\b', re.IGNORECASE)),
                    ('IWA', re.compile(r'\b(intersegment work|IWA|intercompany work)\b', re.IGNORECASE)),
                    ('JTOMS', re.compile(r'\b(JTOMS|job task order management)\b', re.IGNORECASE)),
                    ('J-Plan', re.compile(r'\b(J-Plan|job plan|project plan)\b', re.IGNORECASE))
                ]:
                    matches = len(pattern.findall(table_text))
                    if matches > 0:
                        tag_scores[tag] = Tagger._calculate_tag_score(tag, text_lower, title_lower, metadata, matches)
                
                # Merge with existing tags
                max_tags = CONFIG.get('max_tags_per_section', 5)
                current_tags = {tag: TAG_WEIGHTS.get(tag, 0.5) for tag in sec.get('tags', [])}
                current_tags.update(tag_scores)
                sec['tags'] = [tag for tag, _ in sorted(current_tags.items(), key=lambda x: x[1], reverse=True)[:max_tags]]
        
        return sections

    @staticmethod
    def flag_risks(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flag potentially risky or outdated content.
        
        Args:
            sections: List of section dictionaries
            
        Returns:
            Sections with risk-related tags
            
        Compliance: SWE-033
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        risk_patterns = [
            (re.compile(r'\b(deprecated|outdated|obsolete|discontinued)\b', re.IGNORECASE), "risk:deprecated"),
            (re.compile(r'\b(draft|preliminary|not final|subject to change)\b', re.IGNORECASE), "status:draft"),
            (re.compile(r'\b(review required|needs update|todo|fixme)\b', re.IGNORECASE), "action:review"),
            (re.compile(r'\br00\b', re.IGNORECASE), "revision:00"),
        ]
        
        classified_patterns = [
            re.compile(r'\b(classified|confidential|secret|restricted|ITAR|EAR)\b', re.IGNORECASE),
        ]
        
        security_patterns = [
            (re.compile(r'\b(security|badge|access control|physical security)\b', re.IGNORECASE), "physical_security"),
        ]
        
        for sec in sections:
            text_lower = sec.get('text', '').lower()
            tag_scores = {}
            
            for pattern, tag in risk_patterns:
                matches = len(pattern.findall(text_lower))
                if matches > 0:
                    score = matches * TAG_WEIGHTS.get(tag, 0.5)
                    tag_scores[tag] = score
            
            classified_hits = 0
            for pattern in classified_patterns:
                matches = pattern.findall(text_lower)
                classified_hits += len(matches)
            
            if classified_hits >= 2 or any(word in text_lower for word in ['CLASSIFIED', 'CONFIDENTIAL', 'SECRET', 'ITAR']):
                tag_scores['security:classified'] = TAG_WEIGHTS.get('security:classified', 0.5)
            
            for pattern, tag in security_patterns:
                matches = len(pattern.findall(text_lower))
                if matches > 0:
                    score = matches * TAG_WEIGHTS.get(tag, 0.5)
                    tag_scores[tag] = score
            
            # Merge with existing tags
            max_tags = CONFIG.get('max_tags_per_section', 5)
            current_tags = {tag: TAG_WEIGHTS.get(tag, 0.5) for tag in sec.get('tags', [])}
            current_tags.update(tag_scores)
            sec['tags'] = [tag for tag, _ in sorted(current_tags.items(), key=lambda x: x[1], reverse=True)[:max_tags]]
        
        return sections
    
    @staticmethod
    def extract_compliance_refs(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract and tag compliance references (MIL-STD, NASA-STD, etc.).
        
        Args:
            sections: List of section dictionaries
            
        Returns:
            Sections with compliance reference tags
            
        Compliance: SWE-033
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        compliance_patterns = [
            (re.compile(r'\bMIL-STD-(\d+[A-Z]?)\b', re.IGNORECASE), lambda m: f"ref:mil-std-{m.lower()}"),
            (re.compile(r'\bNASA-STD-(\d+)\b', re.IGNORECASE), lambda m: f"ref:nasa-std-{m}"),
            (re.compile(r'\bNPR[\s-](\d+\.?\d*)\b', re.IGNORECASE), lambda m: f"ref:npr-{m}"),
            (re.compile(r'\bNID[\s-](\d+\.?\d*)\b', re.IGNORECASE), lambda m: f"ref:nid-{m}"),
            (re.compile(r'\bP(\d{4}\.\d+)\b'), lambda m: f"ref:ased-p{m}"),
            (re.compile(r'\bW(\d{4}\.\d+)\b'), lambda m: f"ref:ased-w{m}"),
            (re.compile(r'\bAS9100[A-Z]?\b', re.IGNORECASE), "compliance:as9100"),
            (re.compile(r'\bASTM\s+([A-Z]\d+)\b', re.IGNORECASE), lambda m: f"ref:astm-{m.lower()}"),
            (re.compile(r'\bISO\s+(\d+)\b', re.IGNORECASE), lambda m: f"ref:iso-{m}"),
            (re.compile(r'\bITAR\b', re.IGNORECASE), "compliance:itar"),
        ]
        
        for sec in sections:
            text = sec.get('text', '')
            tag_scores = {}
            
            for pattern, tag_func in compliance_patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    if callable(tag_func):
                        tag = tag_func(match.group(1) if match.groups() else match.group(0))
                    else:
                        tag = tag_func
                    score = TAG_WEIGHTS.get(tag, 0.5)
                    tag_scores[tag] = score
            
            # Merge with existing tags
            max_tags = CONFIG.get('max_tags_per_section', 5)
            current_tags = {tag: TAG_WEIGHTS.get(tag, 0.5) for tag in sec.get('tags', [])}
            current_tags.update(tag_scores)
            sec['tags'] = [tag for tag, _ in sorted(current_tags.items(), key=lambda x: x[1], reverse=True)[:max_tags]]
        
        return sections

def load_tags() -> List[Tuple[str, re.Pattern]]:
    """Load tagging rules from JSON configuration file.
    
    Returns:
        List of (tag, regex) tuples
        
    Compliance: SWE-033
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    tags_file = CONFIG.get('tags_file', 'boundstate/tags.json')
    
    if not os.path.exists(tags_file):
        logger.warning(f"Tags file {tags_file} not found, using default rules")
        return _get_default_rules()
    
    try:
        with open(tags_file, 'r') as f:
            rules_data = json.load(f)
        
        rules = []
        for rule in rules_data:
            try:
                name = rule['name']
                pattern = rule['pattern']
                if 'weight' in rule:
                    TAG_WEIGHTS[name] = rule['weight']
                # Update global DOMAIN_KEYWORDS mapping if domain keywords are defined
                if 'domain_keywords' in rule:
                    DOMAIN_KEYWORDS[name] = [kw.lower() for kw in rule['domain_keywords']]
                flags = re.IGNORECASE if rule.get('case_insensitive', True) else 0
                compiled_pattern = re.compile(pattern, flags)
                rules.append((name, compiled_pattern))
            except (KeyError, re.error) as e:
                logger.error(f"Invalid rule in {tags_file}: {rule}, error: {e}")
                continue
        
        logger.info(f"Loaded {len(rules)} tagging rules from {tags_file}")
        return rules
        
    except Exception as e:
        logger.error(f"Error loading tags file {tags_file}: {e}")
        return _get_default_rules()

def _get_default_rules() -> List[Tuple[str, re.Pattern]]:
    """Get default tagging rules with refined weights for policy documents.
    
    Returns:
        List of (tag, regex) tuples
        
    Compliance: SWE-033
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    default_rules = [
        # Amentum/NASA-specific patterns - ADDED FIRST FOR PRIORITY
        ("Task_Order_Management", re.compile(
            r'(task.{0,5}order|TO\b|ased|task.{0,5}lead|team.{0,5}lead|'
            r'department.{0,5}manager|ddm|task.{0,5}folder|revision|'
            r'release.{0,5}authority)', re.IGNORECASE
        )),
        ("Cost_Estimation", re.compile(
            r'(estimat|labor.{0,5}hour|budget|cost|nte\b|'
            r'not.{0,5}to.{0,5}exceed|eac\b|boe\b|'
            r'productive.{0,5}hour)', re.IGNORECASE
        )),
        ("Quality_Planning", re.compile(
            r'(tqp\b|quality.{0,5}plan|controlling.{0,5}document|'
            r'verification|as9100|p7301)', re.IGNORECASE
        )),
        ("Engineering_Aids", re.compile(
            r'(engineering.{0,5}aid|ea\b|criticality|'
            r'impact.{0,5}assessment|p7208)', re.IGNORECASE
        )),
        ("Product_Development", re.compile(
            r'(product.{0,5}development|formal.{0,5}product|'
            r'informal.{0,5}product|product.{0,5}release|'
            r'p7103|verification|non.{0,5}hardware)', re.IGNORECASE
        )),
        ("NASA_Contractor", re.compile(
            r'(nasa|msfc|marshall|essca|ased|amentum)', re.IGNORECASE
        )),
        ("Aerospace_Engineering", re.compile(
            r'(aerospace|spacecraft|launch.{0,5}vehicle|'
            r'flight.{0,5}hardware)', re.IGNORECASE
        )),
        ("Verification_Control", re.compile(
            r'(verification|validation|inspection|'
            r'nonconforming)', re.IGNORECASE
        )),
        ("Safety_Critical", re.compile(
            r'(safety.{0,5}critical|hazard|risk.{0,5}assessment|'
            r'failure.{0,5}mode|mishap)', re.IGNORECASE
        )),
        ("ESSCA_Contract", re.compile(
            r'(essca|contract.{0,5}year|cy\d+)', re.IGNORECASE
        )),
        ("ASED_Process", re.compile(
            r'(ased|[pgwf]\d{4}\.\d)', re.IGNORECASE
        )),
        ("TQP", re.compile(r'\b(tqp|task\s*order\s*quality\s*plan)\b', re.IGNORECASE)),
        # Added reverse phrase matching for criticality assessment
        ("Criticality_Assessment", re.compile(r'\b(criticality\s*assessment|criticality\s*level|assessment\s*of\s*criticality)\b', re.IGNORECASE)),
        # Expanded labour estimation patterns - more comprehensive
        ("Labor_Estimation", re.compile(
            r'(labor.{0,5}estimat|labor.{0,5}hour|labor\s*hour|labor\s*hours|fte\b|hours.{0,5}per|'
            r'productive.{0,5}hour|\bestimat[ei]|man.{0,3}hour|person.{0,3}hour|'
            r'level.{0,5}of.{0,5}effort|\bloe\b|work.{0,5}estimat|resource.{0,5}estimat)', re.IGNORECASE
        )),
        ("Deliverable_Management", re.compile(
            r'(deliverable|cdrl|customer.{0,5}requirement)', re.IGNORECASE
        )),
        ("NASA_STD", re.compile(r'(nasa.{0,5}std|npr.{0,5}\d+|nid.{0,5}\d+)', re.IGNORECASE)),
        ("MIL_STD", re.compile(r'(mil.{0,5}std.{0,5}\d+)', re.IGNORECASE)),
        ("ASTM", re.compile(r'(astm.{0,5}[a-z]?\d+)', re.IGNORECASE)),
        ("AS9100", re.compile(r'(as9100)', re.IGNORECASE)),

        # New pattern for travel cost and expenses - expanded
        ("Travel_Cost", re.compile(
            r'(travel.{0,5}cost|travel.{0,5}expense|travel\s*expenses|per\s*diem|lodging\s*cost|'
            r'mileage\s*(?:reimbursement)?|flight\s*cost|travel.{0,5}budget|travel.{0,5}allowance|'
            r'trip.{0,5}expense|transportation.{0,5}cost|hotel.{0,5}cost|airfare|travel.{0,5}reimbursement|'
            r'travel.{0,5}funding)',
            re.IGNORECASE)),
        
        # HR and Policy-specific patterns
        ("timecard_policy", re.compile(r'\b(timecard|time recording|time entry|labor recording)\b', re.IGNORECASE)),
        # Restrict travel_policy to explicit policy/authorization wording
        ("travel_policy", re.compile(
            r'\b(travel\s+(?:policy|policies)|travel\s+authorization(?:\s*(?:procedure|process))?'
            r'|travel\s+guidelines?|employee\s+travel\s+(?:policy|guideline))\b',
            re.IGNORECASE)),
        ("telework_policy", re.compile(r'\b(telework|remote work|work from home|telecommuting)\b', re.IGNORECASE)),
        ("leave_policy", re.compile(r'\b(leave policy|vacation|sick leave|PTO|time off)\b', re.IGNORECASE)),
        ("procurement_guideline", re.compile(r'\b(basware|p2p|purchase to pay)\b', re.IGNORECASE)),
        ("subcontractor_guideline", re.compile(r'\b(subcontractor|vendor management|third-party contract)\b', re.IGNORECASE)),
        ("task_folder_guideline", re.compile(r'\b(task folder|task management|project folder)\b', re.IGNORECASE)),
        ("maf_travel_guideline", re.compile(r'\b(MAF travel|mission travel|flight authorization)\b', re.IGNORECASE)),
        
        # General HR patterns
        ("HR", re.compile(r'\b(HR|human resources|employee|personnel|hiring|onboarding)\b', re.IGNORECASE)),
        ("Labor", re.compile(r'\b(labor|workforce|manpower|staffing|hours per person)\b', re.IGNORECASE)),
        ("Materials", re.compile(r'\b(materials|material|equipment|hardware|components)\b', re.IGNORECASE)),
        ("Equipment", re.compile(r'\b(equipment|tools|machinery|devices)\b', re.IGNORECASE)),
        ("ODC", re.compile(r'\b(other direct costs?|ODC)\b', re.IGNORECASE)),
        ("Relocation", re.compile(r'\b(relocation|move|transfer|employee relocation)\b', re.IGNORECASE)),
        ("Recruiting", re.compile(r'\b(recruiting|recruitment|hiring|talent acquisition)\b', re.IGNORECASE)),
        ("Timecard", re.compile(r'\b(timecard|timesheet|time recording)\b', re.IGNORECASE)),
        ("References", re.compile(r'\b(reference|internal reference|citation|document reference)\b', re.IGNORECASE)),
        ("JTOMS", re.compile(r'\b(JTOMS|job task order management)\b', re.IGNORECASE)),
        ("J-Plan", re.compile(r'\b(J-Plan|job plan|project plan)\b', re.IGNORECASE)),
        
        # Procurement patterns
        ("Procurement", re.compile(r'\b(procurement|purchase order|supplier|vendor|contract|RFP|RFQ|order request)\b', re.IGNORECASE)),
        
        # Policy and compliance patterns
        ("Policy", re.compile(r'\b(policy|procedure|guideline|standard|compliance|POL\d{4})\b', re.IGNORECASE)),
        
        # Technical patterns
        ("Technical", re.compile(r'\b(specification|technical|engineering|design|requirement)\b', re.IGNORECASE)),
        ("Engineering", re.compile(r'\b(engineering|design|technical|specification)\b', re.IGNORECASE)),
        ("Quality", re.compile(r'\b(quality|QA|quality assurance|quality control)\b', re.IGNORECASE)),
        ("Technology", re.compile(r'\b(technology|software|hardware|system)\b', re.IGNORECASE)),
        ("Research", re.compile(r'\b(research|development|R&D|experiment|study)\b', re.IGNORECASE)),
        
        # Safety patterns
        ("Safety", re.compile(r'\b(safety|hazard|risk|accident|incident|emergency)\b', re.IGNORECASE)),
        
        # Form-specific patterns
        ("form_document", re.compile(r'\b(form|template|checklist|worksheet)\b', re.IGNORECASE)),
    ]
    return default_rules

def load_plugins() -> List[Tuple[str, re.Pattern]]:
    """Load additional tagging rules from secure JSON plugin files.
    
    Returns:
        List of (tag, regex) tuples
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    try:
        from boundstate.secure_plugins import load_secure_plugins
        return load_secure_plugins(CONFIG['plugins_dir'])
    except ImportError:
        logger.error("Secure plugin loader not available")
        return []
    except Exception as e:
        logger.error(f"Error loading plugins: {e}")
        return []

# Global rules cache
_TAGGING_RULES = None
_LAST_TAGS_MTIME = 0

def get_tagging_rules() -> List[Tuple[str, re.Pattern]]:
    """Get current tagging rules, reloading if files have changed.
    
    Returns:
        List of (tag, regex) tuples
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    global _TAGGING_RULES, _LAST_TAGS_MTIME
    
    tags_file = CONFIG['tags_file']
    current_mtime = 0
    
    if os.path.exists(tags_file):
        current_mtime = os.path.getmtime(tags_file)
    
    if _TAGGING_RULES is None or current_mtime > _LAST_TAGS_MTIME:
        _TAGGING_RULES = load_tags() + load_plugins()
        _LAST_TAGS_MTIME = current_mtime
        logger.info("Reloaded tagging rules")
    
    return _TAGGING_RULES

def tag_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply all tagging rules to document sections.
    
    Args:
        sections: List of section dictionaries
        
    Returns:
        Tagged sections
        
    Compliance: SWE-033
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    if not sections:
        return sections
    
    try:
        rules = get_tagging_rules()
        
        sections = Tagger.apply_tags(sections, rules)
        sections = Tagger.tag_forms_and_questionnaires(sections)
        sections = Tagger.process_table_metadata(sections)
        sections = Tagger.flag_risks(sections)
        sections = Tagger.extract_compliance_refs(sections)
        
        # Add acronym detection for all sections
        for sec in sections:
            text = sec.get('text', '')
            if text.strip():
                acronyms = find_acronyms(text)
                if acronyms:
                    if 'tags' not in sec:
                        sec['tags'] = []
                    # Add acronym tags
                    for acronym in acronyms:
                        # Skip common non-meaningful acronyms
                        if acronym not in ['THE', 'AND', 'FOR', 'WITH', 'ARE', 'NOT']:
                            tag = f"acronym:{acronym}"
                            if tag not in sec['tags']:
                                sec['tags'].append(tag)
                    logger.debug(f"Found acronyms in section: {acronyms}")
                
                # Add specific document type tagging
                if 'new employee' in text.lower() or 'processing checklist' in text.lower():
                    if 'tags' not in sec:
                        sec['tags'] = []
                    sec['tags'].extend(['new_employee', 'checklist'])
                
                if 'transition plan' in text.lower() or 'departing org' in text.lower():
                    if 'tags' not in sec:
                        sec['tags'] = []
                    sec['tags'].extend(['transition_plan', 'departing_org'])
                
                if 'request for quotation' in text.lower() or 'rfq' in text.lower():
                    if 'tags' not in sec:
                        sec['tags'] = []
                    sec['tags'].extend(['rfq', 'quotation'])
                
                # Add specific TQP policy tagging
                if 'tqp' in text.lower():
                    if 'tqp_policy' not in sec.get('tags', []):
                        sec['tags'].append('tqp_policy')
        
        total_tags = sum(len(sec.get('tags', [])) for sec in sections)
        logger.info(f"Applied tags to {len(sections)} sections, total tags: {total_tags}", extra={'req_id': str(uuid.uuid4())})
        
        for sec in sections:
            if sec.get('tags'):
                # Extract identifiers outside f-string to avoid nested-quote issues
                doc_id_val = sec.get('doc_id', 'unknown')
                section_val = sec.get('section', 'unknown')
                logger.debug(
                    f"Document {doc_id_val} section {section_val} tagged with: {sec['tags']}",
                    extra={'req_id': f'tag-{doc_id_val}'}
                )

        # Conflict resolution: if Travel_Cost present, remove travel_policy
        for sec in sections:
            tags = sec.get('tags', [])
            if 'Travel_Cost' in tags and 'travel_policy' in tags:
                sec['tags'] = [t for t in tags if t != 'travel_policy']
        
        # Refine TQP detection to avoid over-tagging
        has_tqp_acronym = any('acronym:TQP' in sec.get('tags', []) for sec in sections)
        
        # Also check with full text decision for context
        full_text = "\n\n".join(sec.get('text', '') for sec in sections)
        has_tqp_context = full_text.strip() and tqp_decision(full_text).get('score', 0) >= 0.3
        
        if has_tqp_acronym or has_tqp_context:
            # Add TQP tag to all sections of the document
            for sec in sections:
                if 'tags' not in sec:
                    sec['tags'] = []
                if 'tqp' not in sec['tags']:
                    sec['tags'].append('tqp')
            logger.info(f"TQP detected (acronym={has_tqp_acronym}, context={has_tqp_context})")
        
        return sections
        
    except Exception as e:
        logger.error(f"Error during tagging: {e}", extra={'req_id': str(uuid.uuid4())})
        return sections

def reload_tags_if_changed():
    """Force reload of tagging rules if configuration has changed.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    global _TAGGING_RULES, _LAST_TAGS_MTIME
    _TAGGING_RULES = None
    _LAST_TAGS_MTIME = 0
    get_tagging_rules()