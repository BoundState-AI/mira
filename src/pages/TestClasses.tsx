import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FlaskConical, ChevronRight } from "lucide-react";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";

interface TestClass {
  name: string;
  count: number;
  description: string;
}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function TestClasses() {
  const { t } = useTranslation('testClasses');
  const [testClasses, setTestClasses] = useState<TestClass[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  const toSlug = (name: string) =>
    name
      .toLowerCase()
      .replace(/[^a-z0-9\s\/-]/g, "")
      .replace(/[\s\/]+/g, "-")
      .replace(/-+/g, "-")
      .trim();

  useEffect(() => {
    const fetchTestClasses = async () => {
      try {
        // Fetch dynamic counts from API
        const response = await fetch(`${API_URL}/api/test-classes/counts`);
        const counts = await response.json();

        // Define test class metadata (descriptions)
        const testClassMetadata: Record<string, { name: string; description: string }> = {
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

        // Build test classes array from API counts
        const testClassesArray: TestClass[] = Object.entries(counts).map(([slug, count]) => ({
          name: testClassMetadata[slug]?.name || slug,
          count: count as number,
          description: testClassMetadata[slug]?.description || 'Test data',
        }));

        // Sort alphabetically by name
        const sortedTestClasses = testClassesArray.sort((a, b) =>
          a.name.localeCompare(b.name)
        );

        setTestClasses(sortedTestClasses);
        setIsLoading(false);
      } catch (error) {
        console.error('Failed to fetch test class counts:', error);
        setIsLoading(false);
      }
    };

    fetchTestClasses();
  }, []);

  const totalTests = testClasses.reduce((sum, tc) => sum + tc.count, 0);

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-serif font-bold mb-1 flex items-center gap-3">
          {t('title')}
          <PageHelp content={helpContent.testClasses} />
        </h1>
        <p className="text-sm text-muted-foreground">
          {isLoading ? t('common:loading', 'Loading...') : `${testClasses.length} test types | ${totalTests.toLocaleString()} total test records`}
        </p>
      </div>

      {/* Test classes grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {testClasses.map((testClass) => (
          <Card
            key={testClass.name}
            className="p-4 hover:border-primary transition-colors cursor-pointer group"
            onClick={() => navigate(`/test-classes/${toSlug(testClass.name)}`)}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-primary/10 rounded-lg">
                  <FlaskConical className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-medium group-hover:text-primary transition-colors">
                    {testClass.name}
                  </h3>
                  <Badge variant="secondary" className="mt-1">
                    {testClass.count.toLocaleString()} records
                  </Badge>
                </div>
              </div>
              <ChevronRight className="h-5 w-5 text-muted-foreground group-hover:text-primary transition-colors" />
            </div>
            <p className="text-sm text-muted-foreground">
              {testClass.description}
            </p>
          </Card>
        ))}
      </div>

      {/* Coming soon */}
      <Card className="p-6 bg-muted/50">
        <h3 className="font-medium mb-2">Coming Soon</h3>
        <ul className="text-sm text-muted-foreground space-y-1">
          <li>- Unit-aware filters (pressure, temperature, concentration)</li>
          <li>- Statistical summaries and distributions</li>
          <li>- Interactive plot builders</li>
          <li>- Export test datasets to CSV/JSON</li>
        </ul>
      </Card>
    </div>
  );
}
