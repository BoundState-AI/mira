import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FlaskConical, ChevronRight, Search, X, Loader2 } from "lucide-react";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";

interface TestClass {
  slug: string;
  count: number;
}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const TEST_CLASS_FALLBACK: Record<string, { name: string; description: string }> = {
  'tvs-outgassing': { name: "TVS Outgassing", description: "Total Mass Loss, Collected Volatile Condensable Material" },
  'flammability': { name: "Flammability", description: "Upward and downward flame propagation ratings" },
  'mechanical-impact': { name: "Mechanical Impact", description: "Impact energy absorption and failure characteristics" },
  'toxicity': { name: "Toxicity", description: "Off-gassing toxicity measurements" },
  'stress-corrosion-cracking': { name: "Stress Corrosion Cracking", description: "Material susceptibility to stress corrosion" },
  'corrosion': { name: "Corrosion", description: "General corrosion resistance testing" },
  'fluid-compatibility': { name: "Fluid Compatibility", description: "Material compatibility with various fluids" },
  'odor': { name: "Odor", description: "Odor intensity ratings" },
  'flash-fire': { name: "Flash Fire", description: "Flash fire propagation characteristics" },
  'tensile-strength': { name: "Tensile Strength", description: "Tensile strength and elongation properties" },
  'pneumatic-impact': { name: "Pneumatic Impact", description: "Pneumatic impact resistance testing" },
  'promoted-combustion': { name: "Promoted Combustion", description: "Combustion promotion characteristics" },
  'particle-impact': { name: "Particle Impact", description: "Particle impact resistance" },
  'electrical-overload': { name: "Electrical Overload", description: "Electrical overload characteristics" },
  'vcm-optical': { name: "VCM Optical", description: "Volatile condensable material and optical properties" },
  'electric-wire-insulation': { name: "Electric Wire Insulation", description: "Wire insulation electrical properties" },
  'low-cycle-fatigue': { name: "Low Cycle Fatigue", description: "Low cycle fatigue resistance" },
  'fungus': { name: "Fungus", description: "Fungal resistance testing" },
  'fracture-mechanics': { name: "Fracture Mechanics", description: "Fracture toughness characteristics" },
  'creep-rupture': { name: "Creep Rupture", description: "Creep and rupture behavior" },
  'high-cycle-fatigue': { name: "High Cycle Fatigue", description: "High cycle fatigue resistance" },
  'friction-heat': { name: "Friction Heat", description: "Friction and heat generation characteristics" },
  'crack-growth': { name: "Crack Growth", description: "Crack propagation rates" },
  'arc-tracking': { name: "Arc Tracking", description: "Electrical arc tracking resistance" },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface SearchResult {
  query: string;
  total_materials: number;
  results: MaterialScorecard[];
}

interface MaterialScorecard {
  material_code: string;
  designation: string;
  composition: string | null;
  material_type: string | null;
  tested_classes: number;
  total_classes: number;
  test_profile: TestProfileEntry[];
}

interface TestProfileEntry {
  test_class: string;
  test_name: string;
  record_count: number;
  record_id: string;
  ratings: { value: string; context: string | null }[];
}

function getRatingVariant(rating: string): "default" | "secondary" | "destructive" | "outline" {
  const r = rating.toUpperCase();
  if (['A', 'P'].includes(r)) return 'default';
  if (['B', 'C', 'S', 'N', 'Z', 'H', 'K', 'V', '7'].includes(r)) return 'secondary';
  if (['D', 'X', 'I', 'U', 'F'].includes(r)) return 'destructive';
  return 'outline';
}

export default function TestClasses() {
  const { t, i18n } = useTranslation("testClasses");
  const [testClasses, setTestClasses] = useState<TestClass[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  // Material search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  // Filter state
  const [materialTypeFilter, setMaterialTypeFilter] = useState<string>("all");
  const [testClassFilter, setTestClassFilter] = useState<string>("all");
  const [ratingFilter, setRatingFilter] = useState<string>("all");
  const [materialTypes, setMaterialTypes] = useState<{ name: string; count: number }[]>([]);

  useEffect(() => {
    fetch(`${API_URL}/api/materials/types`)
      .then(r => r.json())
      .then(data => setMaterialTypes(data.types || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const fetchTestClasses = async () => {
      try {
        const response = await fetch(`${API_URL}/api/test-classes/counts`);
        const counts = await response.json();

        const testClassesArray: TestClass[] = Object.entries(counts).map(([slug, count]) => ({
          count: count as number,
          slug,
        }));

        const sortedTestClasses = testClassesArray.sort((a, b) =>
          t(`classes.${a.slug}.name`, {
            defaultValue: TEST_CLASS_FALLBACK[a.slug]?.name || a.slug,
          }).localeCompare(
            t(`classes.${b.slug}.name`, {
              defaultValue: TEST_CLASS_FALLBACK[b.slug]?.name || b.slug,
            })
          )
        );

        setTestClasses(sortedTestClasses);
        setIsLoading(false);
      } catch (error) {
        console.error('Failed to fetch test class counts:', error);
        setIsLoading(false);
      }
    };

    fetchTestClasses();
  }, [i18n.language, t]);

  const handleMaterialSearch = async () => {
    if (searchQuery.trim().length < 2) return;
    setIsSearching(true);
    try {
      const params = new URLSearchParams({ q: searchQuery.trim() });
      if (materialTypeFilter && materialTypeFilter !== "all") {
        params.append("material_type", materialTypeFilter);
      }
      if (testClassFilter && testClassFilter !== "all") {
        params.append("test_class", testClassFilter);
      }
      if (ratingFilter && ratingFilter !== "all") {
        params.append("rating", ratingFilter);
      }
      const response = await fetch(`${API_URL}/api/materials/search?${params}`);
      const data: SearchResult = await response.json();
      setSearchResults(data);
    } catch (error) {
      console.error('Material search failed:', error);
    } finally {
      setIsSearching(false);
    }
  };

  const clearSearch = () => {
    setSearchQuery("");
    setSearchResults(null);
    setMaterialTypeFilter("all");
    setTestClassFilter("all");
    setRatingFilter("all");
  };

  const totalTests = testClasses.reduce((sum, tc) => sum + tc.count, 0);

  // All test class slugs for gap analysis
  const allClassSlugs = Object.keys(TEST_CLASS_FALLBACK);

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-serif font-bold mb-1 flex items-center gap-3">
          {t("title", { defaultValue: "MAPTIS Search" })}
          <PageHelp content={helpContent.testClasses} />
        </h1>
        <p className="text-sm text-muted-foreground">
          {isLoading
            ? t("loading", { defaultValue: "Loading..." })
            : t("summary", {
                count: testClasses.length,
                total: totalTests.toLocaleString(),
                defaultValue: `${testClasses.length} test types | ${totalTests.toLocaleString()} total test records`,
              })}
        </p>
      </div>

      {/* Material Search Bar */}
      <Card className="p-4 space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search materials across all test classes (e.g., A286, Inconel, Teflon)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleMaterialSearch()}
              className="pl-10"
            />
          </div>
          {searchQuery && (
            <Button variant="ghost" size="icon" onClick={clearSearch}>
              <X className="h-4 w-4" />
            </Button>
          )}
          <Button onClick={handleMaterialSearch} disabled={searchQuery.trim().length < 2 || isSearching}>
            {isSearching ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
            Search
          </Button>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Select value={materialTypeFilter} onValueChange={setMaterialTypeFilter}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Material Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {materialTypes.map(mt => (
                <SelectItem key={mt.name} value={mt.name}>
                  {mt.name} ({mt.count.toLocaleString()})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={testClassFilter} onValueChange={setTestClassFilter}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Test Class" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Test Classes</SelectItem>
              {Object.entries(TEST_CLASS_FALLBACK).map(([slug, info]) => (
                <SelectItem key={slug} value={slug}>{info.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={ratingFilter} onValueChange={setRatingFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Rating" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Ratings</SelectItem>
              <SelectItem value="A">A (Pass)</SelectItem>
              <SelectItem value="B">B</SelectItem>
              <SelectItem value="C">C</SelectItem>
              <SelectItem value="X">X (Fail)</SelectItem>
              <SelectItem value="I">I</SelectItem>
              <SelectItem value="U">U</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Card>

      {/* Search Results — Material Scorecards */}
      {searchResults ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {searchResults.total_materials === 0
                ? `No materials found for "${searchResults.query}"`
                : `${searchResults.total_materials} material${searchResults.total_materials !== 1 ? 's' : ''} found for "${searchResults.query}"${
                    searchResults.total_materials > searchResults.results.length
                      ? ` (showing ${searchResults.results.length})`
                      : ''
                  }`}
            </p>
            <Button variant="outline" size="sm" onClick={clearSearch}>
              Back to all test classes
            </Button>
          </div>

          {searchResults.results.map((material) => {
            const testedSlugs = new Set(material.test_profile.map((tp) => tp.test_class));
            const untestedClasses = allClassSlugs.filter((slug) => !testedSlugs.has(slug));

            return (
              <Card key={material.material_code} className="p-6">
                {/* Material header */}
                <div className="mb-4">
                  <h2 className="text-lg font-bold">{material.designation}</h2>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground mt-1">
                    {material.composition && <span>{material.composition}</span>}
                    {material.material_type && (
                      <Badge variant="outline" className="text-xs">{material.material_type}</Badge>
                    )}
                  </div>
                  <p className="text-sm mt-2">
                    Tested in{' '}
                    <span className="font-semibold text-foreground">{material.tested_classes}</span>
                    {' '}of{' '}
                    <span className="font-semibold text-foreground">{material.total_classes}</span>
                    {' '}test classes
                  </p>
                </div>

                {/* Ratings table */}
                <div className="divide-y">
                  {material.test_profile.map((test) => (
                    <div
                      key={test.test_class}
                      className="flex items-center gap-4 py-2.5 group/row hover:bg-muted/50 px-2 -mx-2 rounded"
                    >
                      <span className="font-medium text-sm w-52 shrink-0">{test.test_name}</span>
                      <div className="flex gap-1.5 flex-wrap flex-1 min-w-0">
                        {test.ratings.length > 0 ? (
                          test.ratings.map((r, i) => (
                            <Badge key={i} variant={getRatingVariant(r.value)}>
                              {r.context ? `${r.context}: ${r.value}` : r.value}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-muted-foreground text-sm">—</span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground w-20 text-right shrink-0">
                        {test.record_count} record{test.record_count !== 1 ? 's' : ''}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="opacity-0 group-hover/row:opacity-100 transition-opacity shrink-0"
                        onClick={() =>
                          navigate(
                            `/test-classes/${test.test_class}?search=${encodeURIComponent(material.designation)}`
                          )
                        }
                      >
                        View <ChevronRight className="h-4 w-4 ml-1" />
                      </Button>
                    </div>
                  ))}
                </div>

                {/* Untested classes (gap analysis) */}
                {untestedClasses.length > 0 && (
                  <details className="mt-3">
                    <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
                      {untestedClasses.length} untested class{untestedClasses.length !== 1 ? 'es' : ''}
                    </summary>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {untestedClasses.map((slug) => (
                        <span
                          key={slug}
                          className="text-xs text-muted-foreground bg-muted px-2 py-1 rounded"
                        >
                          {TEST_CLASS_FALLBACK[slug]?.name || slug}
                        </span>
                      ))}
                    </div>
                  </details>
                )}
              </Card>
            );
          })}
        </div>
      ) : (
        <>
          {/* Test classes grid (default view) */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {testClasses.map((testClass) => (
              <Card
                key={testClass.slug}
                className="p-4 hover:border-primary transition-colors cursor-pointer group"
                onClick={() => navigate(`/test-classes/${testClass.slug}`)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-primary/10 rounded-lg">
                      <FlaskConical className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-medium group-hover:text-primary transition-colors">
                        {t(`classes.${testClass.slug}.name`, {
                          defaultValue: TEST_CLASS_FALLBACK[testClass.slug]?.name || testClass.slug,
                        })}
                      </h3>
                      <Badge variant="secondary" className="mt-1">
                        {t("recordsCount", {
                          count: testClass.count.toLocaleString(),
                          defaultValue: `${testClass.count.toLocaleString()} records`,
                        })}
                      </Badge>
                    </div>
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground group-hover:text-primary transition-colors" />
                </div>
                <p className="text-sm text-muted-foreground">
                  {t(`classes.${testClass.slug}.description`, {
                    defaultValue: TEST_CLASS_FALLBACK[testClass.slug]?.description || t("defaultDescription", { defaultValue: "Test data" }),
                  })}
                </p>
              </Card>
            ))}
          </div>

          {/* Coming soon */}
          <Card className="p-6 bg-muted/50">
            <h3 className="font-medium mb-2">
              {t("comingSoon.title", { defaultValue: "Coming Soon" })}
            </h3>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>- {t("comingSoon.unitAwareFilters", { defaultValue: "Unit-aware filters (pressure, temperature, concentration)" })}</li>
              <li>- {t("comingSoon.statisticalSummaries", { defaultValue: "Statistical summaries and distributions" })}</li>
              <li>- {t("comingSoon.interactivePlots", { defaultValue: "Interactive plot builders" })}</li>
              <li>- {t("comingSoon.exportDatasets", { defaultValue: "Export test datasets to CSV/JSON" })}</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
