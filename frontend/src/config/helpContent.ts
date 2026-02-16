/**
 * Help Content Configuration
 * Centralized help documentation for all MIRA pages
 */

import { PageHelpContent } from "@/components/PageHelp";

export const helpContent: Record<string, PageHelpContent> = {
  query: {
    title: "MIRA Query",
    description: "Ask questions about materials, search the knowledge base, and get AI-powered answers with source citations.",
    whatItDoes: [
      "Search the MAPTIS knowledge base with natural language queries",
      "Validate operating conditions vs material ratings",
      "Identify high-risk materials for oxygen service per test data",
      "Generate violation reports with recommendations",
      "Flag PFAS contamination and restricted materials",
    ],
    howToUse: [
      "Type your question in natural language (e.g., 'What materials are safe for liquid oxygen?')",
      "Review the AI-generated answer with source citations",
      "Click on sources to see the original document excerpts",
      "Ask follow-up questions to drill deeper",
      "Use filters to narrow results by material class or standard",
    ],
    useCases: [
      "What is the oxygen compatibility rating of Ti-6Al-4V?",
      "Which materials require ASTM G93 cleaning for LOX service?",
      "Show me all materials with flammability rating 1 or 2",
      "What are the pressure limits for Inconel 625 in hydrogen service?",
    ],
    tips: [
      "Be specific: 'Ti-6Al-4V oxygen compatibility at 3000 PSI' is better than 'titanium oxygen'",
      "Use follow-up questions to refine answers without re-typing context",
      "Check the confidence score on answers - low confidence means review sources carefully",
      "Export results before starting a new search to save your findings",
    ],
    relatedPages: [
      { name: "Materials", path: "/materials" },
      { name: "Knowledge Twins", path: "/" },
    ],
    apiEndpoint: "POST /api/search",
  },

  materials: {
    title: "Materials Database",
    description: "Browse, search, and manage material specifications with full property data and test history.",
    whatItDoes: [
      "View all materials in the database with key properties",
      "Search by material name, spec ID, or properties",
      "See complete test history for each material",
      "View ratings (flammability, corrosion, SCC, TVS)",
      "Track material revisions and version history",
      "Export material data to Excel/CSV",
    ],
    howToUse: [
      "Browse the table or use the search box to find materials",
      "Click on a material to see full details and test data",
      "Use column filters to find materials meeting specific criteria",
      "Click 'Export' to download the current view as Excel",
      "Sort by any column to find highest/lowest rated materials",
    ],
    useCases: [
      "Find all materials with oxygen rating A or B",
      "Compare properties of different stainless steel grades",
      "See which materials have been tested most recently",
      "Identify materials with high heritage (test count)",
    ],
    tips: [
      "Use the 'Quick Filters' for common searches (O2 compatible, high strength, etc.)",
      "Double-click a row for detailed view",
      "Export filtered results for custom reports",
    ],
    relatedPages: [
      { name: "Test Classes", path: "/test-classes" },
      { name: "Knowledge Twins", path: "/" },
    ],
  },

  testClasses: {
    title: "Test Classes & Methods",
    description: "Explore test data organized by test type (tensile, compression, flammability, etc.).",
    whatItDoes: [
      "Group test data by test type/method",
      "View test statistics (sample size, mean, std dev)",
      "See which materials have been tested with each method",
      "Identify data gaps - materials missing specific tests",
      "Compare test results across materials",
    ],
    howToUse: [
      "Select a test class from the list (e.g., 'Tensile', 'Compression')",
      "View all tests of that type with summary statistics",
      "Click on a specific test to see full details",
      "Use filters to find tests by date, facility, or result range",
      "Export test data for statistical analysis",
    ],
    useCases: [
      "Show me all tensile tests for aerospace alloys",
      "Which materials have flammability test data?",
      "Compare compression strength across steel grades",
      "Find tests performed in the last 6 months",
    ],
    tips: [
      "Use the 'Data Gap Analysis' tab to find missing tests",
      "Sort by sample size to prioritize well-characterized materials",
      "Check test dates - older data may need re-validation",
    ],
    relatedPages: [
      { name: "Materials", path: "/materials" },
      { name: "Knowledge Twins", path: "/" },
    ],
  },

  knowledgeTwins: {
    title: "O₂/H₂ Knowledge Twins",
    description: "Evidence-based material compatibility assessment for oxygen and hydrogen service using NASA Body of Knowledge.",
    whatItDoes: [
      "Search materials by oxygen (O₂) or hydrogen (H₂) compatibility",
      "Query NASA Body of Knowledge standards and safety documentation",
      "Display materials grouped by compatibility rating (A=Best → X=Fail)",
      "Show comprehensive ratings: flammability, corrosion, SCC, HEE",
      "Provide AI-generated summaries of BOK standards with key points",
      "Deterministic boundary checking against NASA-STD-6016C limits",
      "Hydrogen Environment Embrittlement (HEE) index assessment",
    ],
    howToUse: [
      "Select fluid type: Oxygen (O₂) or Hydrogen (H₂)",
      "Browse Mode: View materials grouped by compatibility rating",
      "Ask Mode: Enter natural language query (e.g., 'stainless steel at 3000 PSI')",
      "Review 'Recommended Materials' grouped by rating (A through X)",
      "Check 'Standards Guidance' for BOK documentation with AI summaries",
      "Click on materials to see all ratings (FLAMM, CORR, SCC, HEE)",
    ],
    useCases: [
      "Which materials are rated 'A' for liquid oxygen at 3000 PSI?",
      "What does NASA's H₂ BOK say about titanium alloys?",
      "Find all materials with excellent (A/B) hydrogen compatibility",
      "What is the HEE index for Inconel 718 at 69 MPa?",
      "What are the safety considerations for using aluminum in GOX?",
    ],
    tips: [
      "Rating A = best (high heritage), Rating X = not approved - avoid",
      "BOK results include AI summaries with key safety points extracted",
      "Search returns BOTH material ratings AND standards documentation",
      "For H₂: HEE Index < 0.50 = Extreme susceptibility, use with extreme caution",
      "For O₂: Check pressure limits - dynamic service has lower limits than static",
      "Use specific queries: 'Ti-6Al-4V oxygen 3000 PSI' better than just 'titanium'",
    ],
    relatedPages: [
      { name: "Materials", path: "/materials" },
      { name: "MIRA Query", path: "/query" },
      { name: "Test Classes", path: "/test-classes" },
    ],
    apiEndpoint: "POST /api/v1/o2/search-bok, POST /api/v1/h2/search-bok, POST /api/query/hybrid",
  },

  miulBuilder: {
    title: "MIUL Builder",
    description: "Generate Material Identification Usage Lists (MIULs) from engineering drawings with automated MAPTIS enrichment.",
    whatItDoes: [
      "Extract materials from PDF engineering drawings using AI vision",
      "Auto-detect Drawing Trees for parent/child assembly hierarchy",
      "Identify helicoils, finishes, and embedded hardware (3-pass extraction)",
      "Lookup MAPTIS material codes from designations",
      "Populate NASA rating columns (FLAMM, CORR, SCC, TVS, TOX, FS)",
      "Generate SSP 30234 / JSC 27301F compliant Excel output",
    ],
    howToUse: [
      "Select upload method: PDF Drawings, BOM File, or Compliant MIUL",
      "For Compliant MIUL: Upload all PDFs including Drawing Tree (auto-detected)",
      "Enter Program Name to identify your MIUL",
      "Configure Use Environment (pressure, temperature, media) or use SLS defaults",
      "Click 'Generate Base MIUL' to extract materials",
      "Click 'Enrich with MAPTIS Ratings' to populate rating columns",
      "Click 'Generate MUAs' for materials with rating gaps",
    ],
    useCases: [
      "Generate MIUL from DMLLV valve assembly drawings",
      "Build compliant material list for new flight hardware",
      "Identify all helicoils and finishes in an assembly",
      "Auto-populate MAPTIS ratings for 50+ materials in minutes",
    ],
    tips: [
      "Name your Drawing Tree PDF with 'Drawing Tree' in the filename for auto-detection",
      "Use 'Compliant MIUL' tab for best results - it uses 3-pass extraction with anti-hallucination",
      "The system extracts materials, helicoils, finishes, and hardware in separate passes",
      "Empty Material Code after enrichment means no MAPTIS match - manual lookup needed",
      "Check helicoil quantities - they're consolidated by thread size per parent drawing",
    ],
    relatedPages: [
      { name: "MUA Generator", path: "/mua-v7" },
      { name: "Materials", path: "/materials" },
    ],
    apiEndpoint: "POST /api/miul/compliant-extract, POST /api/miul/enrich",
  },

  muaGenerator: {
    title: "MUA Generator",
    description: "Generate Material Usage Agreements for materials with rating gaps per NASA-STD-6016C.",
    whatItDoes: [
      "Identify materials requiring MUAs based on rating gaps",
      "Route materials to appropriate MUA categories (Cat I, II, III, IV)",
      "Search historic MUA corpus for applicable precedents",
      "Auto-generate rationale using precedent matches",
      "Format MUAs per NASA-STD-6016C templates",
      "Export MUA documents for review and submission",
    ],
    howToUse: [
      "Start with an enriched MIUL (from MIUL Builder with ratings)",
      "Review materials flagged for MUA requirement",
      "Select rationale category for each material",
      "Review AI-suggested rationale based on precedents",
      "Edit and approve MUA content",
      "Export final MUA documents",
    ],
    useCases: [
      "Generate MUAs for new flight hardware materials",
      "Find precedent rationales from historic MUA corpus",
      "Batch-generate MUAs for entire MIUL",
      "Export MUA summary with all materials and rationales",
    ],
    tips: [
      "Category I = tested data available, Category IV = analysis/similarity required",
      "Precedent search finds similar materials with existing approved MUAs",
      "High heritage materials (many tests) typically route to Category I",
      "Novel materials without heritage will need engineering analysis (Cat III/IV)",
      "Review AI-generated rationale carefully - it's a starting point, not final",
    ],
    relatedPages: [
      { name: "MIUL Builder", path: "/miul" },
      { name: "Knowledge Twins", path: "/" },
    ],
    apiEndpoint: "POST /api/mua/generate-batch",
  },

  gasCompatibility: {
    title: "Gas Compatibility",
    description: "Assess material compatibility for O₂/H₂ environments, search NASA standards, and view material family rules.",
    whatItDoes: [
      "Evaluate materials against O₂ and H₂ gas environments",
      "Validate operating conditions (pressure, temperature, phase) against limits",
      "Search O2 Body of Knowledge (NASA-STD-6016, NASA-STD-6001B, JSC-27301F)",
      "View material family classifications (approved, restricted, prohibited)",
      "Check ignition thresholds for oxygen service (GOX vs LOX)",
      "Assess hydrogen embrittlement susceptibility",
      "Generate compatibility reports with evidence citations",
    ],
    howToUse: [
      "Compatibility Check: Select O₂ or H₂, enter material, pressure, temperature",
      "For O₂: Choose phase (GOX = gaseous, LOX = liquid/cryogenic)",
      "O2 Standards Search: Query the Body of Knowledge for standards guidance",
      "Material Families: View NASA-STD-6016 family-based approval rules",
      "Review classification (OK, CAUTION, PROHIBITED) with rationale",
      "Check supporting evidence from test data and standards",
    ],
    useCases: [
      "Is INCONEL 718 approved for LOX at 3000 PSI?",
      "Search: 'ignition temperature aluminum oxygen'",
      "Which material families are prohibited for O₂ service?",
      "What materials can be used for GH2 at -423°F?",
      "Find NASA guidance on promoted combustion testing",
    ],
    tips: [
      "For O₂: LOX has stricter limits than GOX - always specify phase",
      "Classification is based on MAPTIS material family, not string matching",
      "O2 BOK Search finds excerpts from NASA standards with relevance scores",
      "Approved families (austenitic steel, nickel alloys, copper) are generally safe",
      "For H₂: Check HEE index - values < 0.50 indicate extreme susceptibility",
      "Pressure limits are often the limiting factor for O₂ compatibility",
    ],
    relatedPages: [
      { name: "Knowledge Twins", path: "/" },
      { name: "MIRA Query", path: "/query" },
      { name: "MUA Generator", path: "/mua-v7" },
    ],
    apiEndpoint: "POST /api/o2/evaluate, POST /api/o2/search, GET /api/o2/families",
  },

  complianceAnalysis: {
    title: "NASA-STD-6016C Compliance Analysis",
    description: "Comprehensive compliance analysis against NASA-STD-6016C Material and Process Requirements (MPRs).",
    whatItDoes: [
      "Evaluate materials against all applicable NASA-STD-6016C MPRs",
      "Identify compliance gaps requiring MUA generation or engineering review",
      "Detect HEE (Hydrogen Environment Embrittlement) susceptibility for H₂ service",
      "Check oxygen compatibility and flammability requirements",
      "Generate operational constraints for conditional compliance",
      "Route materials to appropriate MUA categories based on gap analysis",
    ],
    howToUse: [
      "Enter the material key (e.g., 'SS316', 'Ti-6Al-4V', 'Inconel 718')",
      "Optionally provide the MAPTIS code for precise material lookup",
      "Set operating conditions: pressure (PSIA) and temperature (°F)",
      "Specify O₂ concentration if relevant (default 21% ambient)",
      "Check 'Hydrogen Service' for H₂ environment analysis",
      "Check 'Habitable Environment' for crew safety requirements",
      "Click 'Analyze Compliance' to run the assessment",
    ],
    useCases: [
      "Pre-flight material certification for new hardware",
      "Evaluate Ti-6Al-4V for GOX service at 3000 PSIA",
      "Check stainless steel compliance for LH₂ propellant lines",
      "Identify MUA requirements for materials with rating gaps",
      "Verify compliance before submitting materials to MIUL",
    ],
    tips: [
      "Green (Compliant) = material meets all MPRs with test data",
      "Yellow (Constraints) = compliant but with operational limits - review constraints carefully",
      "Red (Non-Compliant) = requires MUA or material substitution",
      "Critical gaps require immediate attention - may block certification",
      "HEE bands: Extreme/Severe = CRITICAL severity, High = HIGH severity",
      "For H₂ service, HEE index < 0.50 indicates extreme susceptibility",
      "Use MAPTIS code when available for most accurate material lookup",
    ],
    relatedPages: [
      { name: "MIRA Query", path: "/query" },
      { name: "MUA Generator", path: "/mua-v7" },
      { name: "Knowledge Twins", path: "/" },
    ],
    apiEndpoint: "POST /api/compliance/analyze",
  },

  dtTreeEditor: {
    title: "Drawing Tree Editor",
    description: "Visual drag-and-drop editor for correcting drawing tree hierarchy relationships.",
    whatItDoes: [
      "Visualize drawing tree hierarchy as interactive boxes",
      "Drag and drop nodes to change parent relationships",
      "Automatically update node types (ASSEMBLY vs DETAIL)",
      "Track edit history with undo capability",
      "Import/export JSON in flat format with parent pointers",
      "Support both v3 flat format and nested format JSON files",
    ],
    howToUse: [
      "Click 'Load JSON' to import a drawing tree extraction result",
      "The tree displays all parts with their current hierarchy",
      "Drag any node onto another node to make it a child",
      "The drop target highlights in blue when hovering",
      "Use 'Undo' to revert changes one at a time",
      "Click 'Export' to save the corrected hierarchy",
    ],
    useCases: [
      "Correct errors in AI-extracted drawing tree hierarchies",
      "Fix parent assignments when parts were placed under wrong assembly",
      "Move siblings that were incorrectly nested under each other",
      "Prepare corrected JSON for MIUL Builder input",
    ],
    tips: [
      "Load the v3 extraction JSON from automated DT extraction first",
      "Compare against the PDF to identify misplaced nodes",
      "Parts with children are marked as ASSEMBLY, leaf nodes as DETAIL",
      "Types update automatically when you move nodes",
      "Use Expand All to see the full tree before making corrections",
      "Export the corrected JSON and use as 'drawing_tree' input in MIUL Builder",
    ],
    relatedPages: [
      { name: "MIUL Builder", path: "/miul" },
    ],
  },
};

export default helpContent;
