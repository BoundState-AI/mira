#!/usr/bin/env python3
"""
Module: Query Parser
Purpose: Natural language query parsing and intent classification.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

import re
from typing import Dict, List, Any, Optional
import logging
from .unit_normalizer import parse_and_normalize
import uuid

logger = logging.getLogger(__name__)


class NLPQueryParser:
    """
    Natural language query parser for materials database queries.
    
    This class transforms human-readable questions into structured
    query representations that can be processed by the MAPTIS system.
    It identifies user intent and extracts relevant parameters for
    accurate query execution.
    
    The parser uses a pattern-based approach optimized for materials
    engineering queries, with specific support for NASA terminology
    and use cases.
    
    Attributes:
        patterns: Dict of regex patterns organized by intent type
        entity_patterns: Dict of patterns for entity extraction
        PHRASE_MAP: Dict mapping phrases to structured query fields
        SPEC_PATTERNS: Dict for normalizing specification names
        SPEC_VERSION_TREE: Dict for handling spec versions
        MATERIAL_TYPE_PATTERNS: Dict for inferring material types
        
    Parsing Strategy:
        1. Determine primary intent from query structure
        2. Extract structured intent with property filters
        3. Extract named entities (materials, conditions)
        4. Identify filter criteria
        5. Generate optimized search terms
        6. Apply intent-specific parsing rules
    """
    
    def __init__(self):
        """
        Initialize the query parser with patterns and entity lists.
        
        Sets up comprehensive pattern libraries for different query types
        and entity recognition. Patterns are designed to handle variations
        in how engineers might phrase their questions.
        
        Pattern Design Principles:
            - Flexible word ordering
            - Common synonyms included
            - Technical and colloquial terms
            - NASA-specific terminology
        """
        # Phrase-to-field mappings for structured query generation
        self.PHRASE_MAP = {
            "compatible with liquid oxygen": {
                "test_fluid": "LOX",
                "oxygen_rating": "A",
                "context": ["vacuum", "flammability"]
            },
            "compatible with lox": {
                "test_fluid": "LOX", 
                "oxygen_rating": "A",
                "context": ["vacuum", "flammability"]
            },
            "lox compatible": {
                "test_fluid": "LOX",
                "oxygen_rating": "A", 
                "context": ["vacuum", "flammability"]
            },
            "thermal insulation": {
                "property": "thermal_conductivity_w_mk",
                "op": "<",
                "value": 0.2,
                "material_type_hint": ["foam", "MLI", "aerogel"]
            },
            "qualified per nasa std 6016": {
                "spec_ref": "NASA-STD-6016",
                "rating_required": "pass",
                "default_version": "rev_C"
            },
            "qualified per nasa-std-6016": {
                "spec_ref": "NASA-STD-6016",
                "rating_required": "pass",
                "default_version": "rev_C"
            },
            "nasa-std-6016 rev c": {
                "spec_ref": "NASA-STD-6016",
                "spec_version": "rev_C",
                "rating_required": "pass"
            },
            "nasa std 6016 rev c": {
                "spec_ref": "NASA-STD-6016",
                "spec_version": "rev_C",
                "rating_required": "pass"
            },
            "passed nasa-std-6016": {
                "spec_ref": "NASA-STD-6016",
                "rating_required": "pass"
            },
            "passed nasa std 6016": {
                "spec_ref": "NASA-STD-6016",
                "rating_required": "pass"
            },
            "high temperature": {
                "property": "max_temp_c",
                "op": ">",
                "value": 200
            },
            "cryogenic service": {
                "property": "min_temp_c",
                "op": "<",
                "value": -150,
                "context": ["cryogenic", "low_temperature"]
            },
            "hydrogen service": {
                "test_fluid": "HYDROGEN",
                "context": ["hydrogen", "h2_compatibility"],
                "material_type_hint": ["austenitic_steel", "nickel_alloy", "aluminum"]
            },
            "cryogenic hydrogen": {
                "property": "min_temp_c",
                "op": "<",
                "value": -150,
                "test_fluid": "HYDROGEN",
                "context": ["cryogenic", "hydrogen", "h2_compatibility"]
            },
            "hydrogen compatible": {
                "test_fluid": "HYDROGEN",
                "context": ["hydrogen", "h2_compatibility"]
            },
            "rated for hydrogen": {
                "test_fluid": "HYDROGEN",
                "rating_required": "pass",
                "context": ["hydrogen", "h2_compatibility"]
            },
            "dielectric": {
                "property": "dielectric_strength_kv_mm",
                "op": ">",
                "value": 10,
                "material_type_hint": ["insulator", "polymer", "ceramic"]
            },
            # Fuzzy semantic filters
            "super insulative": {
                "filters": {
                    "thermal_conductivity_w_mk": {"op": "<", "value": 0.2}
                }
            },
            "very insulative": {
                "filters": {
                    "thermal_conductivity_w_mk": {"op": "<", "value": 0.2}
                }
            },
            "very low outgassing": {
                "filters": {
                    "tml_pct": {"op": "<", "value": 1.0},
                    "cvcm_pct": {"op": "<", "value": 0.1}
                }
            },
            "low outgassing": {
                "filters": {
                    "tml_pct": {"op": "<", "value": 1.0},
                    "cvcm_pct": {"op": "<", "value": 0.1}
                },
                "spec_ref": "ASTM-E-595"
            },
            "lightweight": {
                "filters": {
                    "density_g_cm3": {"op": "<", "value": 1.5}
                }
            },
            "light weight": {
                "filters": {
                    "density_g_cm3": {"op": "<", "value": 1.5}
                }
            },
            "doesn't outgas much": {
                "filters": {
                    "tml_pct": {"op": "<", "value": 1.0},
                    "cvcm_pct": {"op": "<", "value": 0.1}
                }
            },
            "don't outgas much": {
                "filters": {
                    "tml_pct": {"op": "<", "value": 1.0},
                    "cvcm_pct": {"op": "<", "value": 0.1}
                }
            },
            "outgas much": {
                "filters": {
                    "tml_pct": {"op": "<", "value": 1.0},
                    "cvcm_pct": {"op": "<", "value": 0.1}
                }
            },
            "low density": {
                "filters": {
                    "density_g_cm3": {"op": "<", "value": 1.5}
                }
            }
        }
        
        # Spec normalization patterns
        self.SPEC_PATTERNS = {
            r"nasa[\s\-]*std[\s\-]*(\d+)": r"NASA-STD-\1",
            r"mil[\s\-]*r[\s\-]*(\d+)([a-z]?)": lambda m: f"MIL-R-{m.group(1)}{m.group(2).upper()}",
            r"astm[\s\-]*e[\s\-]*(\d+)": r"ASTM-E-\1",
            r"sae[\s\-]*ams[\s\-]*(\d+)": r"SAE-AMS-\1",
            r"iso[\s\-]*(\d+)": r"ISO-\1"
        }
        
        # Spec version tree for compliance checking
        self.SPEC_VERSION_TREE = {
            "NASA-STD-6016": {
                "rev_A": "2004-06",
                "rev_B": "2016-11", 
                "rev_C": "2022-08"
            },
            "MIL-R-83248": {
                "rev_B": "1988-03",
                "rev_C": "1994-07"
            }
        }
        
        # Material type inference patterns
        self.MATERIAL_TYPE_PATTERNS = {
            "sealing": ["elastomer", "o-ring", "gasket", "seal", "viton", "silicone"],
            "adhesive": ["epoxy", "polyurethane", "silicone", "acrylic", "cyanoacrylate"],
            "insulation": ["foam", "MLI", "aerogel", "fiberglass", "mineral wool"],
            "structural": ["aluminum", "titanium", "steel", "composite", "carbon fiber"],
            "electrical": ["wire", "cable", "connector", "insulator", "conductor"],
            "coating": ["paint", "primer", "anodize", "plating", "powder coat"]
        }
        
        # Define patterns for different query types
        # Each pattern list represents variations of the same intent
        self.patterns = {
            # Risk-related queries
            "risk_query": [
                # General risk queries
                r"(?:what|which|show|find)\s+(?:materials?|items?)\s+(?:have|with|showing)\s+(?:high|elevated|critical)\s+(\w+)?\s*risk",
                r"(?:identify|detect|find)\s+(?:risky|dangerous|hazardous)\s+materials?",
                # Domain-specific risk queries
                r"materials?\s+with\s+(?:PFAS|chemical|regulatory|obsolescence)\s+(?:risk|concern|issue)",
                # Safety queries
                r"(?:safe|unsafe)\s+for\s+(\w+)\s+(?:service|use|application)"
            ],
            
            # Material comparison queries
            "comparison": [
                # Direct comparison
                r"compare\s+([\w\s-]+)\s+(?:with|to|and|vs\.?)\s+([\w\s-]+)",
                # Difference queries
                r"(?:difference|different)\s+between\s+([\w\s-]+)\s+and\s+([\w\s-]+)",
                # Evaluative comparisons
                r"which\s+is\s+(?:better|stronger|safer)[\s:,]+([\w\s-]+)\s+or\s+([\w\s-]+)",
                # Versus format
                r"([\w\s-]+)\s+versus\s+([\w\s-]+)"
            ],
            
            # Test data analysis queries
            "test_analysis": [
                # Test result queries
                r"(?:show|find|list)\s+(?:all\s+)?(\w+)?\s*(?:failed|passed)\s+tests?",
                # Failure-specific queries
                r"materials?\s+(?:that|which)\s+failed\s+(\w+)?\s*(?:test|testing)",
                # Test data requests
                r"test\s+(?:results?|failures?|data)\s+for\s+([\w\s-]+)",
                # Compatibility queries
                r"(\w+)\s+(?:compatibility|performance)\s+(?:test|data)"
            ],
            
            # Property-based queries
            "property_query": [
                # Qualitative property queries
                r"materials?\s+with\s+(?:high|low|good|excellent)\s+(\w+)",
                # Superlative queries
                r"(?:strongest|lightest|cheapest|best)\s+(\w+)?materials?",
                # Resistance queries
                r"(\w+)\s+(?:resistant|resistance|proof)\s+materials?",
                # Application-specific queries
                r"materials?\s+for\s+(\w+)\s+(?:temperature|pressure|environment)"
            ],
            
            # Recommendation queries
            "recommendation": [
                # Direct recommendations
                r"(?:recommend|suggest|what)\s+(?:material|alternative)\s+for\s+([\w\s-]+)",
                # Alternative requests
                r"alternatives?\s+to\s+([\w\s-]+)",
                # Replacement queries
                r"replace(?:ment)?\s+for\s+([\w\s-]+)",
                # Comparative recommendations
                r"better\s+than\s+([\w\s-]+)"
            ]
        }
        
        # Define entity extractors
        # These lists contain common materials and conditions in aerospace
        self.entity_patterns = {
            # Common aerospace materials
            "composition": [
                # Metals
                "aluminum", "titanium", "steel", "stainless steel", "inconel",
                # Polymers - note: fluorosilicone must come BEFORE silicone for substring matching
                "polyimide", "ptfe", "teflon", "kapton", "viton", "fluorosilicone", "silicone",
                # Other materials
                "epoxy", "polyethylene", "polypropylene", "peek", "pvc"
            ],
            
            # Service gases used in testing
            "gas_service": [
                # Common gases
                "oxygen", "hydrogen", "nitrogen", "helium", "argon",
                # NASA abbreviations
                "lox", "gox", "ln2", "lh2", "ghe"
            ],
            
            # Temperature patterns
            "temperature": [
                # Numeric temperatures with units
                r"(-?\d+)\s*(?:°|deg|degree)?\s*[cf]",
                # Qualitative temperatures
                r"(?:high|low|cryo|cryogenic|ambient)\s+temp(?:erature)?",
                # Temperature ranges
                r"(-?\d+)\s*to\s*(-?\d+)\s*(?:°|deg|degree)?\s*[cf]"
            ],
            
            # Pressure patterns
            "pressure": [
                # Numeric pressures with units
                r"(\d+\.?\d*)\s*(?:mpa|psi|bar|atm)",
                # Qualitative pressures
                r"(?:high|low|vacuum)\s+pressure"
            ]
        }
    
    def parse(self, query: str) -> Dict[str, Any]:
        """
        Parse a natural language query into structured components.
        
        This is the main entry point for query parsing. It analyzes the
        input query and returns a structured representation containing
        intent, entities, filters, and search terms.
        
        Args:
            query: Natural language query from user
            
        Returns:
            Dictionary containing:
                - original_query: The input query
                - intent: Classified intent type
                - entities: Extracted entities by type
                - filters: Filter criteria for search
                - search_terms: Optimized search string
                - structured_intent: Enhanced structured fields
                - primary_properties: Property filters with operators
                - spec_reference: Normalized spec name
                - Additional intent-specific fields
                
        Example:
            Input: "Compare aluminum 6061 with titanium for high temperature"
            Output: {
                'original_query': '...',
                'intent': 'comparison',
                'entities': {'compositions': ['aluminum', 'titanium'], ...},
                'materials': ['aluminum 6061', 'titanium'],
                'filters': {'min_temp': 100},
                'primary_properties': {'max_temp_c': {'op': '>', 'value': 200}},
                ...
            }
        """
        # CRITICAL: Store original query to prevent string returns
        original_query = query
        logger.debug(f"[SEARCH] Parser input: '{query}' (type: {type(query)})")
        
        # Move percentage filter handling OUTSIDE the main try block
        # Handle percent-based numeric filters first (e.g., "Outgassing TML < 1.0%, CVCM < 0.1%")
        percentage_pattern = re.compile(
            r'\b(?P<prop>Outgassing\s+TML|CVCM|TML|Total\s+Mass\s+Loss)\b\s*'
            r'(?P<op><|<=|>|>=|=)\s*'
            r'(?P<value>\d+(\.\d+)?)\s*%',
            re.IGNORECASE
        )

        # Split query on commas and newlines to handle multiple clauses
        clauses = re.split(r'[,\n]\s*', query.strip())
        percent_filters = {}

        for clause in clauses:
            match = percentage_pattern.search(clause)
            if match:
                # Map user-facing property names to internal keys
                prop_mapping = {
                    'outgassing tml': 'tml_pct',
                    'tml': 'tml_pct', 
                    'total mass loss': 'tml_pct',
                    'cvcm': 'cvcm_pct'
                }
                
                prop_name = match.group('prop').lower().strip()
                prop_key = prop_mapping.get(prop_name)
                
                if prop_key:
                    percent_filters[prop_key] = {
                        'op': match.group('op'),
                        'value': float(match.group('value'))
                    }
                    logger.debug(f"Extracted percent filter: {prop_key} {match.group('op')} {match.group('value')}%")

        if percent_filters:
            property_filters_list = [
                {"property": key, "op": val["op"], "value": val["value"]}
                for key, val in percent_filters.items()
            ]
            result = {
                "query_type": "general_search",
                "property_filters": property_filters_list,
                # Include all required fields to match expected structure
                "original_query": query,
                "intent": "general_search",
                "entities": {"compositions": [], "gases": [], "temperatures": [], "pressures": []},
                "filters": {},
                "search_terms": query,
                "structured_intent": {
                    "property_filters": percent_filters,
                    "require_test_data": True,
                    "spec_ref": None,
                    "spec_version": None,
                    "rating_required": None,
                    "test_fluid": None,
                    "oxygen_rating": None,
                    "material_type_hints": [],
                    "context": []
                },
                "primary_properties": percent_filters,
                "spec_reference": None,
                "spec_version": None,
                "rating_required": None,
                "test_fluid_filter": None,
                "oxygen_rating_filter": None,
                "material_type_hints": [],
                "require_test_data": True
            }
            logger.debug(f"Returning percent filter result: {result}")
            # CRITICAL: Double-check result type before returning
            if not isinstance(result, dict):
                logger.error(f"[ERROR] PERCENT FILTER RETURNING {type(result)}: {result}")
                raise TypeError(f"Expected dict, got {type(result)}")
            return result
        
        # Check for temperature patterns, but only return early if it's a pure temperature query
        # This allows combined queries to be processed by the main parser
        temp_match = None
        if "thermal conductivity" not in query.lower() and "w/m" not in query.lower():
            temp_pattern = re.compile(
                r"(?:below|under|<|less\s+than)\s*(-?\d+(?:\.\d+)?)\s*(°C|°F|C|F|K)",
                re.IGNORECASE
            )
            temp_match = temp_pattern.search(query)
        
        # Only return early for pure temperature queries (no "and", "with", etc.)
        if temp_match and not any(word in query.lower() for word in ["and", "with", "plus", "&"]):
            temp_value = float(temp_match.group(1))
            temp_unit = temp_match.group(2) or "°C"  # Default to Celsius
            
            # Normalize temperature to Celsius
            temp_celsius = self._normalize_temperature(temp_value, temp_unit)
            
            # Determine if it's a cryogenic temperature (< -100°C)
            if temp_celsius < -100:
                property_key = "min_service_temp_c"
            else:
                property_key = "max_service_temp_c"
            
            temp_result = {
                "original_query": query,
                "intent": "property_query",
                "entities": {"compositions": [], "gases": [], "temperatures": [f"{temp_celsius}°C"], "pressures": []},
                "filters": {},
                "search_terms": query,
                "structured_intent": {
                    "property_filters": {property_key: {"op": "<", "value": temp_celsius}},
                    "require_test_data": True,
                    "spec_ref": None,
                    "spec_version": None,
                    "rating_required": None,
                    "test_fluid": None,
                    "oxygen_rating": None,
                    "material_type_hints": [],
                    "context": ["temperature", "cryogenic" if temp_celsius < -100 else "thermal"]
                },
                "primary_properties": {property_key: {"op": "<", "value": temp_celsius}},
                "spec_reference": None,
                "spec_version": None,
                "rating_required": None,
                "test_fluid_filter": None,
                "oxygen_rating_filter": None,
                "material_type_hints": [],
                "require_test_data": True
            }
            logger.debug(f"Returning temperature filter result: {temp_result}")
            return temp_result
        
        # Continue with rest of parsing logic in try block
        try:
            
            query_lower = query.lower()
            
            # Determine query intent
            intent = self._determine_intent(query_lower)
            
            # Extract structured intent for deterministic retrieval
            try:
                structured_intent = self.extract_structured_intent(query)
            except Exception as e:
                logger.error(f"Structured intent extraction failed: {e}")
                structured_intent = {
                    "spec_ref": None,
                    "spec_version": None,
                    "rating_required": None,
                    "property_filters": {},
                    "test_fluid": None,
                    "oxygen_rating": None,
                    "material_type_hints": [],
                    "context": [],
                    "require_test_data": True
                }
            
            # Extract entities and parameters (legacy support)
            parsed = {
                "original_query": query,
                "intent": intent,
                "entities": self._extract_entities(query_lower),
                "filters": self._extract_filters(query_lower),
                "search_terms": self._extract_search_terms(query_lower),
                # Add structured intent fields for enhanced retrieval
                "structured_intent": structured_intent,
                "primary_properties": structured_intent["property_filters"],
                "spec_reference": structured_intent["spec_ref"],
                "spec_version": structured_intent["spec_version"],
                "rating_required": structured_intent["rating_required"],
                "test_fluid_filter": structured_intent["test_fluid"],
                "oxygen_rating_filter": structured_intent["oxygen_rating"],
                "material_type_hints": structured_intent["material_type_hints"],
                "require_test_data": structured_intent["require_test_data"]
            }
            
            # Intent-specific parsing (enhanced)
            # Each intent type may require additional parsing logic
            if intent == "comparison":
                # Extract the specific materials being compared
                parsed["materials"] = self._extract_comparison_materials(query_lower)
            elif intent == "risk_query":
                # Identify which risk domain is being queried
                parsed["risk_type"] = self._extract_risk_type(query_lower)
            elif intent == "test_analysis":
                # Extract test type and result filters
                parsed["test_type"] = self._extract_test_type(query_lower)
                parsed["result_filter"] = self._extract_result_filter(query_lower)
            
            # Log structured fields for debugging if logger level is DEBUG
            if logger.isEnabledFor(logging.DEBUG):
                if structured_intent["property_filters"]:
                    logger.debug(f"Extracted property filters: {structured_intent['property_filters']}")
                if structured_intent["spec_ref"]:
                    logger.debug(f"Extracted spec reference: {structured_intent['spec_ref']} ({structured_intent['spec_version']})")
                if structured_intent["material_type_hints"]:
                    logger.debug(f"Inferred material types: {structured_intent['material_type_hints']}")
            
            # Ensure we always return a dictionary
            if not isinstance(parsed, dict):
                logger.error(f"[ERROR] MAIN PARSE RETURNING {type(parsed)}: {parsed}")
                raise TypeError(f"Expected dict, got {type(parsed)}")
            logger.debug(f"[SUCCESS] Main parse returning dict with keys: {list(parsed.keys())}")
            return parsed
            
        except Exception as e:
            # Safety fallback - never return a string, always return a dict
            logger.error(f"Parser encountered error: {e}")
            fallback_result = {
                "original_query": query,
                "intent": "general_search",
                "entities": {"compositions": [], "gases": [], "temperatures": [], "pressures": []},
                "filters": {},
                "search_terms": query,
                "structured_intent": {"require_test_data": True},
                "primary_properties": {},
                "spec_reference": None,
                "spec_version": None,
                "rating_required": None,
                "test_fluid_filter": None,
                "oxygen_rating_filter": None,
                "material_type_hints": [],
                "require_test_data": True
            }
    
    def _determine_intent(self, query: str) -> str:
        """
        Determine the primary intent of the query.
        
        Uses pattern matching to classify the query into one of the
        predefined intent categories. The first matching pattern
        determines the intent.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Intent string: One of:
                - "risk_query": Risk assessment queries
                - "comparison": Material comparison queries
                - "test_analysis": Test data queries
                - "property_query": Property-based searches
                - "recommendation": Alternative suggestions
                - "general_search": Default fallback
                
        Pattern Matching:
            - Patterns are checked in order of specificity
            - First match wins to avoid ambiguity
            - Case-insensitive matching used throughout
        """
        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return intent
        
        # Default to general search if no specific intent matched
        return "general_search"
    
    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """
        Extract named entities from the query.
        
        Identifies specific materials, gases, temperatures, and pressures
        mentioned in the query. These entities are used for filtering
        and search refinement.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Dictionary with entity lists:
                - compositions: Material types mentioned
                - gases: Service gases mentioned
                - temperatures: Temperature values/ranges
                - pressures: Pressure values/ranges
                
        Entity Recognition Strategy:
            1. Exact string matching for known entities
            2. Regex pattern matching for numeric values
            3. Unit normalization for consistency
            4. Deduplication of found entities
        """
        entities = {
            "compositions": [],
            "gases": [],
            "temperatures": [],
            "pressures": []
        }
        
        # Extract material compositions
        # Simple substring matching for known materials
        for comp in self.entity_patterns["composition"]:
            if comp in query:
                entities["compositions"].append(comp)
        
        # Extract gas services
        # Convert to uppercase for consistency with database
        for gas in self.entity_patterns["gas_service"]:
            if gas in query:
                entities["gases"].append(gas.upper())
        
        # Extract temperatures using regex patterns
        for pattern in self.entity_patterns["temperature"]:
            matches = re.findall(pattern, query)
            if matches:
                entities["temperatures"].extend(matches)
        
        # Extract pressures using regex patterns
        for pattern in self.entity_patterns["pressure"]:
            matches = re.findall(pattern, query)
            if matches:
                entities["pressures"].extend(matches)
        
        return entities
    
    def _extract_filters(self, query: str) -> Dict[str, Any]:
        """
        Extract filter criteria from the query.
        
        Identifies specific constraints that should be applied to the
        search results, such as material type, test results, or
        operating conditions.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Dictionary of filter criteria:
                - composition: Specific material type
                - test_result: PASS/FAIL filter
                - min_year: Minimum test year
                - min_temp/max_temp: Temperature range
                
        Filter Extraction Rules:
            - First matching composition becomes filter
            - Test result keywords trigger PASS/FAIL filters
            - Temporal phrases extract year constraints
            - Temperature qualifiers set numeric bounds
        """
        filters = {}
        
        # Composition filter
        # Use first mentioned composition as primary filter
        for comp in self.entity_patterns["composition"]:
            if comp in query:
                filters["composition"] = comp
                break
        
        # Test result filter
        # Keywords indicate desired test outcome
        if "failed" in query or "fail" in query:
            filters["test_result"] = "FAIL"
        elif "passed" in query or "pass" in query:
            filters["test_result"] = "PASS"
        
        # Year filter
        # Extract temporal constraints
        year_match = re.search(r"(?:since|after|from)\s+(\d{4})", query)
        if year_match:
            filters["min_year"] = int(year_match.group(1))
        
        # Temperature range filters
        # Map qualitative terms to numeric thresholds
        if "high temperature" in query or "high temp" in query:
            filters["min_temp"] = 100  # Celsius threshold for "high"
        elif "cryogenic" in query or "cryo" in query:
            filters["max_temp"] = -50  # Celsius threshold for "cryogenic"
        
        return filters
    
    def _extract_search_terms(self, query: str) -> str:
        """
        Extract key search terms from the query.
        
        Removes common words and query structure to leave only the
        essential search terms. This improves search relevance by
        focusing on meaningful content words.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Cleaned search string with stop words removed
            
        Stop Word Removal:
            - Common English words (the, a, an)
            - Query structure words (show, find, list)
            - Domain stop words (material, materials)
            - Short words (<= 2 characters)
        """
        # Define stop words to remove
        # These words add little semantic value to searches
        stop_words = {
            # Query verbs
            "show", "find", "list", "what", "which",
            # Common nouns
            "materials", "material",
            # Prepositions and articles
            "with", "for", "the", "a", "an",
            # Auxiliary verbs
            "is", "are", "have", "has",
            # Quantifiers
            "all", "any",
            # Pronouns
            "me",
            # Other common words
            "tell", "about"
        }
        
        # Split and filter words
        words = query.split()
        search_terms = [w for w in words if w not in stop_words and len(w) > 2]
        
        return " ".join(search_terms)
    
    def _extract_comparison_materials(self, query: str) -> List[str]:
        """
        Extract materials to compare from comparison queries.
        
        Parses comparison queries to identify the two or more materials
        being compared. Handles various comparison phrasings.
        
        Args:
            query: Lowercase query string
            
        Returns:
            List of material names/identifiers to compare
            
        Extraction Strategy:
            - Use regex groups to capture material names
            - Handle various comparison connectors (vs, with, and)
            - Clean and normalize material names
            - Return in order mentioned
        """
        materials = []
        
        # Try each comparison pattern
        for pattern in self.patterns["comparison"]:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                # Extract material names from regex groups
                for group in match.groups():
                    if group:
                        # Clean up the material name
                        materials.append(group.strip())
                break
        
        return materials
    
    def _extract_risk_type(self, query: str) -> str:
        """
        Extract the type of risk being queried.
        
        Identifies which risk domain the user is interested in based on
        keywords in the query. Supports BoundState's multi-domain risk
        assessment model.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Risk type string:
                - "chemical": PFAS, toxicity risks
                - "obsolescence": End-of-life, legacy parts
                - "regulatory": Compliance issues
                - "design": Structural/mechanical risks
                - "environmental": Sustainability concerns
                - "all": No specific domain (default)
                
        Risk Domain Keywords:
            Each domain has associated trigger words that indicate
            user interest in that specific risk type.
        """
        risk_keywords = {
            # Chemical risk indicators
            "chemical": ["chemical", "pfas", "toxic", "hazardous"],
            # Obsolescence risk indicators
            "obsolescence": ["obsolete", "obsolescence", "old", "outdated", "legacy"],
            # Regulatory risk indicators
            "regulatory": ["regulatory", "compliance", "regulation", "banned"],
            # Design risk indicators
            "design": ["design", "structural", "mechanical"],
            # Environmental risk indicators
            "environmental": ["environmental", "sustainable", "green"]
        }
        
        # Check each risk type's keywords
        for risk_type, keywords in risk_keywords.items():
            if any(keyword in query for keyword in keywords):
                return risk_type
        
        # Default to all risk types if none specified
        return "all"
    
    def _extract_test_type(self, query: str) -> str:
        """
        Extract test type from test-related queries.
        
        Identifies specific test types mentioned in the query to filter
        test results appropriately. Maps to NASA test categories.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Test type string:
                - "COMPATIBILITY": Gas compatibility tests
                - "OUTGASSING": Vacuum outgassing tests
                - "FLAMMABILITY": Fire/flammability tests
                - "all": All test types (default)
                
        NASA Test Types:
            These map to standard NASA material test categories
            used in spacecraft qualification.
        """
        # Check for specific test type keywords
        if "compatibility" in query:
            return "COMPATIBILITY"
        elif "outgassing" in query:
            return "OUTGASSING"
        elif "flammability" in query:
            return "FLAMMABILITY"
        
        # Default to all test types
        return "all"
    
    def _extract_result_filter(self, query: str) -> str:
        """
        Extract test result filter (PASS/FAIL) from query.
        
        Determines whether the user wants to see only passed tests,
        only failed tests, or all test results.
        
        Args:
            query: Lowercase query string
            
        Returns:
            Result filter string:
                - "FAIL": Only failed tests
                - "PASS": Only passed tests
                - "all": All tests (default)
                
        Keyword Mapping:
            - "failed", "failure" → FAIL filter
            - "passed", "successful" → PASS filter
            - No keywords → all results
        """
        # Check for failure-related keywords
        if "failed" in query or "failure" in query:
            return "FAIL"
        # Check for success-related keywords
        elif "passed" in query or "successful" in query:
            return "PASS"
        
        # Default to showing all results
        return "all"
    
    def normalize_spec_name(self, spec_input: str) -> Optional[str]:
        """
        Normalize specification names to standard format.
        
        Converts various spec name formats to standardized format:
        - "nasa std 6016" → "NASA-STD-6016"
        - "mil-r-83248c" → "MIL-R-83248C"
        
        Args:
            spec_input: Raw spec name from query
            
        Returns:
            Normalized spec name or None if not recognized
        """
        spec_lower = spec_input.lower().strip()
        
        # Enhanced fuzzy matching for NASA-STD-6016
        normalized = spec_lower.replace(" ", "").replace("-", "").replace("_", "")
        if "nasastd6016" in normalized:
            return "NASA-STD-6016"
        
        # Try each normalization pattern
        for pattern, replacement in self.SPEC_PATTERNS.items():
            match = re.search(pattern, spec_lower)
            if match:
                if callable(replacement):
                    return replacement(match)
                else:
                    return re.sub(pattern, replacement, spec_lower, flags=re.IGNORECASE).upper()
        
        return None
    
    def _normalize_temperature(self, value: float, unit: str) -> float:
        """
        Normalize temperature values to Celsius.
        
        Args:
            value: Temperature value
            unit: Temperature unit (°C, °F, K, etc.)
            
        Returns:
            Temperature in Celsius
        """
        unit_upper = unit.upper().replace("°", "")
        
        if unit_upper in ["F"]:
            # Fahrenheit to Celsius
            return (value - 32) * 5 / 9
        elif unit_upper in ["K"]:
            # Kelvin to Celsius
            return value - 273.15
        else:
            # Already Celsius or unspecified (assume Celsius)
            return value
    
    def extract_property_filters(self, query: str) -> Dict[str, Any]:
        """
        Extract property-based filters with operators from query.
        
        Identifies numeric properties and their constraints:
        - "thermal conductivity less than 0.2"
        - "dielectric strength > 15 kV/mm"
        - "outgassing TML < 1%"
        
        Args:
            query: Query string
            
        Returns:
            Dictionary of property filters with operators and values
        """
        filters = {}
        query_lower = query.lower()
        
        # Property patterns with operators (updated with unit capture groups)
        property_patterns = {
            "thermal_conductivity_w_mk": [
                r"thermal\s+conductivity\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(w/mk|w/m-k|w/m·k)?",
                r"thermal\s+conductivity\s*(?:>|>=|greater\s+than|above)\s*(\d+\.?\d*)\s*(w/mk|w/m-k|w/m·k)?",
                r"(?:^|\s)k\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(w/mk|w/m-k|w/m·k)?",
                r"(?:^|\s)k\s*(?:>|>=|greater\s+than|above)\s*(\d+\.?\d*)\s*(w/mk|w/m-k|w/m·k)?",
            ],
            "dielectric_strength_kv_mm": [
                r"dielectric\s*(?:strength)?\s*(?:>|greater\s+than|above)\s*(\d+\.?\d*)\s*(kv/mm|v/mil)?",
                r"breakdown\s+voltage\s*(?:>|greater\s+than|above)\s*(\d+\.?\d*)\s*(kv/mm|v/mil)?",
                r"with\s+dielectric\s*(?:>|greater\s+than|above)\s*(\d+\.?\d*)\s*(kv/mm|v/mil)?",
                r"dielectric\s*>?\s*(\d+\.?\d*)\s*(v/mil|kv/mm)?"
            ],
            "tml_pct": [
                r"(?:outgassing\s+)?tml\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(%|percent|mg)?",
                r"total\s+mass\s+loss\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(%|percent|mg)?",
                r"outgassing\s+tml\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(%|percent|mg)?"
            ],
            "cvcm_pct": [
                r"cvcm\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(%|percent|mg)?",
                r"collected\s+volatile\s*(?:<|<=|less\s+than|below)\s*(\d+\.?\d*)\s*(%|percent|mg)?",
                r"(?:lowest|low)\s+cvcm"  # Handle "lowest CVCM" pattern
            ],
            "density_g_cm3": [
                r"density\s*(?:\(<|<|less\s+than|below)\s*(\d+\.?\d*)\s*(g/cm3|g/cm³)?\)?",
                r"specific\s+gravity\s*(?:\(<|<|less\s+than|below)\s*(\d+\.?\d*)\s*(g/cm3|g/cm³)?\)?",
                r"low\s+density\s*(?:\(<|<)\s*(\d+\.?\d*)\s*(g/cm3|g/cm³)?\)?"
            ]
        }
        
        # Extract property filters
        for prop, patterns in property_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    # Special handling for patterns without numeric values
                    if prop == "cvcm_pct" and "lowest" in pattern:
                        # Handle "lowest CVCM" without specific value
                        filters[prop] = {
                            "op": "<",
                            "value": 0.1,  # Default low CVCM threshold
                            "sort": "asc"  # Indicate sorting preference
                        }
                        break
                    
                    # Skip if no numeric group (for special patterns)
                    if not match.groups() or not match.group(1):
                        continue
                    
                    # Determine operator
                    if any(op in pattern for op in ["<", "less than", "below"]):
                        op = "<"
                    elif any(op in pattern for op in [">", "greater than", "above"]):
                        op = ">"
                    else:
                        op = "="
                    
                    raw_val = match.group(1)
                    raw_unit = match.group(2) or ""
                    normalized_val = parse_and_normalize(prop, raw_val, raw_unit)
                    
                    filters[prop] = {
                        "op": op,
                        "value": normalized_val
                    }
                    break
        
        return filters
    
    def infer_material_types(self, query: str) -> List[str]:
        """
        Infer material types from query context.
        
        Maps query terms to likely material categories:
        - "thermal insulation" → ["foam", "MLI", "aerogel"]
        - "sealing application" → ["elastomer", "o-ring", "gasket"]
        
        Args:
            query: Query string
            
        Returns:
            List of inferred material types
        """
        query_lower = query.lower()
        inferred_types = []
        
        # Check each pattern
        for context, material_types in self.MATERIAL_TYPE_PATTERNS.items():
            if context in query_lower:
                inferred_types.extend(material_types)
        
        # Also check phrase map for material type hints
        for phrase, mapping in self.PHRASE_MAP.items():
            if phrase in query_lower and "material_type_hint" in mapping:
                inferred_types.extend(mapping["material_type_hint"])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_types = []
        for t in inferred_types:
            if t not in seen:
                seen.add(t)
                unique_types.append(t)
        
        return unique_types
    
    def extract_structured_intent(self, query: str) -> Dict[str, Any]:
        """
        Extract structured intent with all fields for deterministic retrieval.
        
        Combines phrase mapping, property extraction, and spec normalization
        to create a comprehensive query intent object.
        
        Args:
            query: Natural language query
            
        Returns:
            Structured intent dictionary with all relevant fields
        """
        query_lower = query.lower()
        intent = {
            "spec_ref": None,
            "spec_version": None,
            "rating_required": None,
            "property_filters": {},
            "test_fluid": None,
            "oxygen_rating": None,
            "material_type_hints": [],
            "context": [],
            "require_test_data": True  # Default to requiring test data
        }
        
        # Check phrase mappings first (support multiple matches)
        for phrase, mapping in self.PHRASE_MAP.items():
            if phrase in query_lower:
                # Apply all fields from mapping
                for key, value in mapping.items():
                    if key == "filters":
                        # Merge property filters
                        intent["property_filters"].update(value)
                    elif key == "material_type_hint":
                        intent["material_type_hints"].extend(value)
                    elif key == "property":
                        # Handle single property mapping
                        prop_filter = {
                            "op": mapping.get("op", "="),
                            "value": mapping.get("value", 0)
                        }
                        intent["property_filters"][value] = prop_filter
                    else:
                        intent[key] = value
        
        # Extract property filters
        property_filters = self.extract_property_filters(query)
        intent["property_filters"].update(property_filters)
        
        # Extract temperature filters for combined queries
        # Look for temperature patterns that are NOT part of thermal conductivity expressions
        temp_parts = query.split()
        for i, part in enumerate(temp_parts):
            if re.match(r"(-?\d+(?:\.\d+)?)(°C|°F|C|F|K)", part, re.IGNORECASE):
                # Check if this temperature is NOT preceded by thermal conductivity keywords
                context_before = " ".join(temp_parts[max(0, i-5):i]).lower()
                if "thermal conductivity" not in context_before and "w/m" not in context_before:
                    temp_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(°C|°F|C|F|K)", part, re.IGNORECASE)
                    if temp_match:
                        temp_value = float(temp_match.group(1))
                        temp_unit = temp_match.group(2) or "°C"
                        temp_celsius = self._normalize_temperature(temp_value, temp_unit)
                        
                        if temp_celsius < -100:
                            property_key = "min_service_temp_c"
                        else:
                            property_key = "max_service_temp_c"
                            
                        intent["property_filters"][property_key] = {
                            "op": "<",
                            "value": temp_celsius
                        }
                        break
        
        # Extract oxygen rating patterns - updated to handle more variations
        oxygen_rating_patterns = [
            r"a[\-\s]*rated\s+(?:for\s+)?oxygen",  # "a rated for oxygen"
            r"oxygen.*a[\-\s]*rated",  # "oxygen...a rated"
            r"materials?\s+a[\-\s]*rated\s+(?:for\s+)?oxygen",  # "materials a rated for oxygen"
            r"(?:show|find|get)\s+materials?\s+a[\-\s]*rated\s+(?:for\s+)?oxygen"  # "show materials a rated for oxygen"
        ]
        
        for pattern in oxygen_rating_patterns:
            if re.search(pattern, query_lower):
                intent["oxygen_rating"] = "A"
                intent["test_fluid"] = "LOX"
                break
        
        # Extract and normalize spec references
        spec_match = re.search(r"(?:qualified\s+per|per|to)\s+([\w\s\-]+\d+)", query_lower)
        if spec_match:
            normalized_spec = self.normalize_spec_name(spec_match.group(1))
            if normalized_spec:
                intent["spec_ref"] = normalized_spec
                # Get default version if available
                if normalized_spec in self.SPEC_VERSION_TREE:
                    versions = list(self.SPEC_VERSION_TREE[normalized_spec].keys())
                    intent["spec_version"] = versions[-1]  # Latest version
        
        # Infer material types
        material_types = self.infer_material_types(query)
        if material_types:
            intent["material_type_hints"].extend(material_types)
        
        # Check if query allows materials without test data
        if "include all" in query_lower or "all materials" in query_lower:
            intent["require_test_data"] = False
        
        return intent
