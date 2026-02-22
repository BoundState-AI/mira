import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FlaskConical, ChevronRight } from "lucide-react";
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

export default function TestClasses() {
  const { t, i18n } = useTranslation("testClasses");
  const [testClasses, setTestClasses] = useState<TestClass[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchTestClasses = async () => {
      try {
        // Fetch dynamic counts from API
        const response = await fetch(`${API_URL}/api/test-classes/counts`);
        const counts = await response.json();

        // Build test classes array from API counts
        const testClassesArray: TestClass[] = Object.entries(counts).map(([slug, count]) => ({
          count: count as number,
          slug,
        }));

        // Sort alphabetically by localized name
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

  const totalTests = testClasses.reduce((sum, tc) => sum + tc.count, 0);

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-serif font-bold mb-1 flex items-center gap-3">
          {t("title", { defaultValue: "Test Classes Browser" })}
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

      {/* Test classes grid */}
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
    </div>
  );
}
