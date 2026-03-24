import { Fragment, useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ArrowLeft, ChevronLeft, ChevronRight, Search, Download, Copy, FileText, Code, Printer } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ModuleAvailabilityGate,
  TemporarilyUnavailableNotice,
} from "@/components/TemporarilyUnavailableModule";
import { isUnavailableModuleId } from "@/lib/moduleAvailability";

interface TestRecord {
  id: string;
  material_key: number;
  material_code?: string;
  material_designation?: string;
  tested_fluid?: string | null;
  test_conditions?: Record<string, any>;
  test_results?: Record<string, any>;
  rating?: string;
  created_at?: string;
}

interface PaginationInfo {
  page: number;
  per_page: number;
  total_records: number;
  total_pages: number;
}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const TEST_CLASS_FALLBACK: Record<string, { name: string; description: string }> = {
  'tvs-outgassing': { name: 'TVS Outgassing', description: 'Total Mass Loss, Collected Volatile Condensable Material' },
  'flammability': { name: 'Flammability', description: 'Upward and downward flame propagation ratings' },
  'mechanical-impact': { name: 'Mechanical Impact', description: 'Impact resistance and energy absorption' },
  'toxicity': { name: 'Toxicity', description: 'Toxic gas generation and exposure limits' },
  'stress-corrosion-cracking': { name: 'Stress Corrosion Cracking', description: 'Material degradation under tensile stress' },
  'corrosion': { name: 'Corrosion', description: 'Chemical degradation and protective coatings' },
  'fluid-compatibility': { name: 'Fluid Compatibility', description: 'Material reactions with fluids and propellants' },
  'odor': { name: 'Odor', description: 'Odor intensity and acceptability ratings' },
  'flash-fire': { name: 'Flash Fire', description: 'Ignition temperature and burn characteristics' },
  'tensile-strength': { name: 'Tensile Strength', description: 'Ultimate tensile strength and yield' },
  'pneumatic-impact': { name: 'Pneumatic Impact', description: 'Pneumatic shock and impact resistance' },
  'promoted-combustion': { name: 'Promoted Combustion', description: 'Oxygen-enriched combustion behavior' },
  'particle-impact': { name: 'Particle Impact', description: 'Hypervelocity particle impact damage' },
  'electrical-overload': { name: 'Electrical Overload', description: 'Electrical arc tracking and breakdown' },
  'vcm-optical': { name: 'VCM Optical', description: 'Vacuum-deposited contamination on optics' },
  'electric-wire-insulation': { name: 'Electric Wire Insulation', description: 'Wire insulation integrity and dielectric' },
  'low-cycle-fatigue': { name: 'Low Cycle Fatigue', description: 'Cyclic loading failure at high strain' },
  'fungus': { name: 'Fungus', description: 'Fungal growth resistance and nutrient rating' },
  'fracture-mechanics': { name: 'Fracture Mechanics', description: 'Crack propagation and toughness' },
  'creep-rupture': { name: 'Creep Rupture', description: 'Time-dependent deformation under load' },
  'high-cycle-fatigue': { name: 'High Cycle Fatigue', description: 'Cyclic loading failure at low strain' },
  'friction-heat': { name: 'Friction Heat', description: 'Thermal generation from friction' },
  'crack-growth': { name: 'Crack Growth', description: 'Fatigue crack growth rate analysis' },
  'arc-tracking': { name: 'Arc Tracking', description: 'Electrical arc resistance in insulation' },
};

export default function TestClassDetail() {
  const { t } = useTranslation(["testClasses", "common"]);
  const isTemporarilyUnavailable = isUnavailableModuleId("test-classes");
  const { testType } = useParams<{ testType: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [records, setRecords] = useState<TestRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || "");
  const [ratingFilter, setRatingFilter] = useState<string>("all");
  const [ratingType, setRatingType] = useState<string>("all");
  const [stdTestFlag, setStdTestFlag] = useState<string>("all");
  const [availableRatings, setAvailableRatings] = useState<string[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo>({
    page: 1,
    per_page: 50,
    total_records: 0,
    total_pages: 0,
  });
  const [selectedRecord, setSelectedRecord] = useState<TestRecord | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [viewMode, setViewMode] = useState<"report" | "json">("report");

  const translatedName = testType
    ? t(`classes.${testType}.name`, { ns: "testClasses", defaultValue: "" })
    : "";
  const translatedDescription = testType
    ? t(`classes.${testType}.description`, { ns: "testClasses", defaultValue: "" })
    : "";
  const testInfo = testType
    ? {
        name: translatedName || TEST_CLASS_FALLBACK[testType]?.name || testType,
        description: translatedDescription || TEST_CLASS_FALLBACK[testType]?.description || "",
      }
    : null;
  const isKnownTestType = !!(testType && (translatedName || TEST_CLASS_FALLBACK[testType]));
  const isFluidCompatibility = testType === 'fluid-compatibility';

  // Fetch available ratings for this test type
  useEffect(() => {
    if (!testType) return;
    if (isTemporarilyUnavailable) {
      setAvailableRatings([]);
      return;
    }

    fetch(`${API_URL}/api/test-records/${testType}/ratings`)
      .then(response => response.json())
      .then(data => {
        setAvailableRatings(data.ratings || []);
      })
      .catch(err => {
        console.error('Failed to load ratings:', err);
        setAvailableRatings([]);
      });
  }, [isTemporarilyUnavailable, testType]);

  useEffect(() => {
    if (isTemporarilyUnavailable) {
      setRecords([]);
      setError(null);
      setIsLoading(false);
      setPagination((prev) => ({
        ...prev,
        total_records: 0,
        total_pages: 0,
      }));
      return;
    }

    if (!testType || !isKnownTestType) {
      setError(t("detail.unknownTestType", { ns: "testClasses", defaultValue: "Unknown test type" }));
      setIsLoading(false);
      return;
    }

    fetchRecords(pagination.page, pagination.per_page);
  }, [isKnownTestType, isTemporarilyUnavailable, pagination.page, ratingFilter, ratingType, stdTestFlag, t, testType]);

  const fetchRecords = async (page: number, perPage: number) => {
    if (isTemporarilyUnavailable) return;
    setIsLoading(true);
    setError(null);

    try {
      // Build query parameters
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: perPage.toString(),
      });

      if (ratingFilter && ratingFilter !== "all") {
        params.append("rating", ratingFilter);
      }

      if (ratingType && ratingType !== "all") {
        params.append("rating_type", ratingType);
      }

      if (stdTestFlag && stdTestFlag !== "all") {
        params.append("std_test_flag", stdTestFlag);
      }

      if (searchQuery) {
        params.append("search", searchQuery);
      }

      const response = await fetch(`${API_URL}/api/test-records/${testType}?${params}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch records: ${response.statusText}`);
      }

      const data = await response.json();
      setRecords(data.records || []);
      setPagination(data.pagination || pagination);
    } catch (err: any) {
      setError(err.message || "Failed to load test records");
      setRecords([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearch = () => {
    setPagination({ ...pagination, page: 1 });
    fetchRecords(1, pagination.per_page);
  };

  const handlePageChange = (newPage: number) => {
    setPagination({ ...pagination, page: newPage });
  };

  const handleExport = async () => {
    if (isTemporarilyUnavailable) return;
    try {
      const params = new URLSearchParams({
        format: 'csv',
      });
      if (ratingFilter && ratingFilter !== "all") {
        params.append("rating", ratingFilter);
      }
      if (searchQuery) {
        params.append("search", searchQuery);
      }

      const response = await fetch(`${API_URL}/api/test-records/${testType}/export?${params}`);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${testType}-records.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export failed:", err);
    }
  };

  if (!testInfo) {
    return (
      <div className="min-h-full p-6">
        <Card className="p-6">
          <h2 className="text-xl font-semibold mb-2">
            {t("detail.notFoundTitle", { ns: "testClasses", defaultValue: "Test Type Not Found" })}
          </h2>
          <p className="text-muted-foreground mb-4">
            {t("detail.notFoundDescription", {
              ns: "testClasses",
              defaultValue: "The requested test type could not be found.",
            })}
          </p>
          <Button onClick={() => navigate('/test-classes')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            {t("detail.backToClasses", { ns: "testClasses", defaultValue: "Back to MAPTIS Search" })}
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Header */}
      <div>
        <Button
          variant="ghost"
          onClick={() => navigate('/test-classes')}
          className="mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          {t("detail.backToClasses", { ns: "testClasses", defaultValue: "Back to MAPTIS Search" })}
        </Button>

        <h1 className="text-2xl font-serif font-bold mb-1">{testInfo.name}</h1>
        <p className="text-sm text-muted-foreground">{testInfo.description}</p>
        <p className="text-sm text-muted-foreground mt-1">
          {t("detail.totalRecords", {
            ns: "testClasses",
            count: (pagination.total_records || 0).toLocaleString(),
            defaultValue: `${(pagination.total_records || 0).toLocaleString()} total records`,
          })}
        </p>
      </div>

      {isTemporarilyUnavailable ? (
        <TemporarilyUnavailableNotice moduleName={testInfo.name} />
      ) : null}

      <ModuleAvailabilityGate unavailable={isTemporarilyUnavailable} className="space-y-6">
      {/* Filters */}
      <Card className="p-4">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1">
            <div className="flex gap-2">
              <Input
                placeholder={t("detail.searchPlaceholder", {
                  ns: "testClasses",
                  defaultValue: "Search materials...",
                })}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                className="flex-1"
              />
              <Button onClick={handleSearch}>
                <Search className="h-4 w-4 mr-2" />
                {t("buttons.search", { ns: "common", defaultValue: "Search" })}
              </Button>
            </div>
          </div>

          {testType === 'toxicity' ? (
            // Three-filter layout for toxicity
            <>
              <Select value={ratingType} onValueChange={setRatingType}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="Rating Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="tox_emurating">EMU Rating</SelectItem>
                  <SelectItem value="tox_orionrating">Orion Rating</SelectItem>
                  <SelectItem value="tox_shuttlerating">Shuttle Rating</SelectItem>
                  <SelectItem value="tox_spacestationrating">Space Station</SelectItem>
                </SelectContent>
              </Select>

              <Select value={ratingFilter} onValueChange={setRatingFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Rating" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="A">A</SelectItem>
                  <SelectItem value="H">H</SelectItem>
                  <SelectItem value="K">K</SelectItem>
                  <SelectItem value="V">V</SelectItem>
                  <SelectItem value="X">X</SelectItem>
                </SelectContent>
              </Select>

              <Select value={stdTestFlag} onValueChange={setStdTestFlag}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Test Standard" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Tests</SelectItem>
                  <SelectItem value="A">Standard (A)</SelectItem>
                  <SelectItem value="N">Non-Standard (N)</SelectItem>
                  <SelectItem value="S">Special (S)</SelectItem>
                </SelectContent>
              </Select>
            </>
          ) : (
            // Original single dropdown for other test types
            <Select value={ratingFilter} onValueChange={setRatingFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Filter by rating" />
              </SelectTrigger>
              <SelectContent className="max-h-[300px]">
                <SelectItem value="all">All Ratings</SelectItem>
                {availableRatings.map(rating => (
                  <SelectItem key={rating} value={rating}>
                    {rating}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          <Button variant="outline" onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" />
            {t("buttons.exportCsv", { ns: "common", defaultValue: "Export CSV" })}
          </Button>
        </div>
      </Card>

      {/* Results */}
      {error && (
        <Card className="p-6 bg-destructive/10">
          <p className="text-destructive">{error}</p>
        </Card>
      )}

      {isLoading ? (
        <Card className="p-12">
          <div className="text-center text-muted-foreground">
            {t("detail.loadingRecords", { ns: "testClasses", defaultValue: "Loading records..." })}
          </div>
        </Card>
      ) : records.length === 0 ? (
        <Card className="p-12">
          <div className="text-center text-muted-foreground">
            {t("detail.noRecords", {
              ns: "testClasses",
              defaultValue: "No records found. Try adjusting your filters.",
            })}
          </div>
        </Card>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("table.materialCode", { ns: "testClasses", defaultValue: "Material Code" })}</TableHead>
                <TableHead>{t("table.materialName", { ns: "testClasses", defaultValue: "Material Name" })}</TableHead>
                <TableHead>{t("table.rating", { ns: "testClasses", defaultValue: "Rating" })}</TableHead>
                {isFluidCompatibility && <TableHead>{t("table.testedFluid", { ns: "testClasses", defaultValue: "Tested Fluid" })}</TableHead>}
                <TableHead>{t("labels.details", { ns: "common", defaultValue: "Details" })}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((record) => (
                <TableRow key={record.id}>
                  <TableCell className="font-mono text-sm">
                    {record.material_code || `MAT-${record.material_key}`}
                  </TableCell>
                  <TableCell>
                    {record.material_designation || `Material #${record.material_key}`}
                  </TableCell>
                  <TableCell>
                    {record.rating ? (
                      <Badge variant={getRatingVariant(record.rating)}>
                        {record.rating}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  {isFluidCompatibility && (
                    <TableCell>
                      {record.tested_fluid ? (
                        <span className="text-sm">{record.tested_fluid}</span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                  )}
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSelectedRecord(record);
                        setDialogOpen(true);
                      }}
                    >
                      {t("buttons.view", { ns: "common", defaultValue: "View" })}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {/* Pagination */}
          <div className="flex items-center justify-between px-6 py-4 border-t">
            <div className="text-sm text-muted-foreground">
              {t("detail.paginationSummary", {
                ns: "testClasses",
                start: ((pagination.page - 1) * pagination.per_page) + 1,
                end: Math.min(pagination.page * pagination.per_page, pagination.total_records),
                total: pagination.total_records,
                defaultValue:
                  `Showing ${((pagination.page - 1) * pagination.per_page) + 1} to ${Math.min(pagination.page * pagination.per_page, pagination.total_records)} of ${pagination.total_records} records`,
              })}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(pagination.page - 1)}
                disabled={pagination.page === 1}
              >
                <ChevronLeft className="h-4 w-4" />
                {t("detail.previous", { ns: "testClasses", defaultValue: "Previous" })}
              </Button>
              <div className="text-sm">
                {t("detail.pageOf", {
                  ns: "testClasses",
                  page: pagination.page,
                  total: pagination.total_pages,
                  defaultValue: `Page ${pagination.page} of ${pagination.total_pages}`,
                })}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(pagination.page + 1)}
                disabled={pagination.page === pagination.total_pages}
              >
                {t("detail.next", { ns: "testClasses", defaultValue: "Next" })}
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Record Detail Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-5xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <span>{t("detail.reportTitle", { ns: "testClasses", defaultValue: "Test Record Report" })}</span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.print()}
                >
                  <Printer className="h-4 w-4 mr-2" />
                  Print
                </Button>
              </div>
            </DialogTitle>
            <DialogDescription>
              {selectedRecord?.material_designation || `Material #${selectedRecord?.material_key}`}
            </DialogDescription>
          </DialogHeader>

          {selectedRecord && (
            <div className="space-y-6" id="test-report">
              {/* Material Info Header */}
              <div className="bg-primary/5 rounded-lg p-4 border-2 border-primary/20">
                <div className={`grid grid-cols-2 ${isFluidCompatibility ? 'md:grid-cols-5' : 'md:grid-cols-4'} gap-4`}>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase">Material Code</p>
                    <p className="text-lg font-mono font-bold">{selectedRecord.material_code || `MAT-${selectedRecord.material_key}`}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase">Material Key</p>
                    <p className="text-lg font-semibold">{selectedRecord.material_key}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase">Rating</p>
                    {selectedRecord.rating ? (
                      <Badge variant={getRatingVariant(selectedRecord.rating)} className="text-base px-3 py-1">
                        {selectedRecord.rating}
                      </Badge>
                    ) : (
                      <p className="text-muted-foreground">-</p>
                    )}
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase">Test Type</p>
                    <p className="text-sm font-medium">{testInfo?.name}</p>
                  </div>
                  {isFluidCompatibility && (
                    <div>
                      <p className="text-xs font-semibold text-muted-foreground uppercase">Tested Fluid</p>
                      <p className="text-sm font-medium">{selectedRecord.tested_fluid || '-'}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Tabbed View */}
              <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as "report" | "json")}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="report" className="flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Formatted Report
                  </TabsTrigger>
                  <TabsTrigger value="json" className="flex items-center gap-2">
                    <Code className="h-4 w-4" />
                    Raw JSON
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="report" className="mt-4">
                  <FormattedReport
                    record={selectedRecord}
                    testType={testInfo?.name || ""}
                    isFluidCompatibility={isFluidCompatibility}
                  />
                </TabsContent>

                <TabsContent value="json" className="mt-4">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-semibold">Test Record Data</h3>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          navigator.clipboard.writeText(JSON.stringify(selectedRecord.test_results, null, 2));
                        }}
                      >
                        <Copy className="h-4 w-4 mr-2" />
                        Copy JSON
                      </Button>
                    </div>
                    <div className="bg-muted rounded-lg p-4 border">
                      <pre className="text-sm overflow-auto max-h-[500px]">
                        {JSON.stringify(selectedRecord.test_results, null, 2)}
                      </pre>
                    </div>
                  </div>
                </TabsContent>
              </Tabs>

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>
                  Close
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      </ModuleAvailabilityGate>
    </div>
  );
}

// Comprehensive field name to display label mapping
const FIELD_LABELS: Record<string, string> = {
  // Material & Identification
  'materialkey': 'Material Key',
  'materialcode': 'Material Code',
  'testreportnumber': 'Test Report Number',
  'testtype': 'Test Type',
  'testtypecaption': 'Test Type',
  'requestdate': 'Date Tested',

  // Ratings (all test types)
  'rating': 'Rating',
  'rtg': 'Rating',
  'rating_6001': '6001 Rating',
  'rating_6001b': '6001B Rating',
  'flam_rtg': '6001 Rating',
  // Flash Fire (two rating fields in contract)
  'fla_firerating': 'Fire Rating',
  'fla_flashrating': 'Flash Rating',

  // Test-specific ratings
  'cor_rating': 'Rating',
  'stress_rating': 'Rating',
  'fluid_rating': 'Rating',
  'fluc_rating': 'Rating',
  'tested_fluid': 'Tested Fluid',
  'odor_rating': 'Rating',
  'fla_rating': 'Rating',
  'pneu_rating': 'Rating',
  'partimp_rating': 'Rating',
  'elo_rating': 'Rating',
  'ewi_rating': 'Rating',
  'lowcyc_rating': 'Rating',
  'highcyc_rating': 'Rating',
  'fri_rating': 'Rating',
  'crk_rating': 'Rating',

  // Corrosion-specific
  'cor_media': 'Media',
  'cor_pitdepth': 'Pit Depth',
  'cor_pitdepthunits': 'Pit Depth Units',
  'cor_corrosionrate': 'Corrosion Rate',
  'cor_corrosionunits': 'Corrosion Units',
  'cor_time': 'Time (hrs)',
  'cor_timehours': 'Time (hrs)',
  'cor_temperature': 'Temperature (F)',
  'cor_surfacearea': 'Surface Area (in²)',
  'cor_materialchanges': 'Material Changes',
  'cor_pressure': 'Pressure (psia)',
  'cor_testno': 'Test No.',
  'cor_reference': 'Reference',
  'cor_datasource': 'Data Source',
  'cor_standardflag': 'Standard Flag',

  // Flammability
  'flam_rating': '6001 Rating',
  'flam_rating_6001b': '6001B Rating',
  'flam_pressure': 'Pressure (psia)',
  'flam_moc_o2_pct': 'Oxygen %',
  'flam_gasname': 'Gas Name',
  'flam_gaspercent': 'Gas %',
  'flam_substratethickness': 'Substrate Thickness (in)',
  'flam_substratematerial': 'Substrate Material',
  'flam_substrateindicator': 'Substrate ID',
  'flam_sampletemperature': 'Sample Temperature (F)',
  'flam_pressurepsiarange': 'Pressure Spread',
  'flam_percentoxygenrange': 'Oxygen Spread',
  'flam_mount_dev': 'Mounting Device',
  'flam_sealventflag': 'Seal/Vent Flag',
  'flam_standardflag': 'Standard Flag',
  'flam_samplecount': 'Sample Count',

  // Arc Tracking
  'arc_rating': 'Rating',
  'arc_wiregauge': 'Wire Gauge (AWG)',
  'arc_insulationthickness': 'Insul. Thick (in.)',
  'arc_arctrackcount': 'Arc Track Count',
  'arc_appliedvolts': 'Appl. Volts (volt)',
  'arc_outsidediameter': 'Outside Diam. (in.)',
  'arc_chambervolume': 'Chamber Vol. (l)',
  'arc_initialarccounts': 'Init. Arc Counts',
  'arc_init_arc_cnt': 'Init. Arc Counts',
  'arc_singlewire': 'Single Wire (in.)',
  'arc_specification': 'Spec.',
  'arc_percentoxygen': 'Oxy. %',
  'arc_oxygenpercent': 'Oxy. %',
  'arc_gasname': 'Gas Name',
  'arc_gaspercent': 'Gas %',
  'arc_moc_o2_pct': 'Oxy. %',
  'arc_mountdev': 'Mount Device',
  'arc_nulltime': 'Null Time',
  'arc_reappliedtime': 'Reapplied Time (sec.)',
  'arc_int_applied_time': 'Init. Appl. Time (sec.)',
  'arc_testreportkey': 'Test Rpt. No',

  // TVS Outgassing
  'tvs_rating': 'Rating',
  'tvs_tml': 'TML (%)',
  'tvs_cvcm': 'CVCM (%)',
  'tvs_wvr': 'WVR (%)',
  'tvs_temperature': 'Temperature (°C)',
  'tvs_pressure': 'Pressure (torr)',
  'tvs_duration': 'Duration (hrs)',

  // Toxicity
  'tox_rating': 'Rating',
  'tox_rtg': 'Rating',
  'tox_emurating': 'EMU Rating',
  'tox_orionrating': 'Orion Rating',
  'tox_shuttlerating': 'Shuttle Rating',
  'tox_spacestationrating': 'Space Station Rating',
  'tox_spacestationrtg': 'Space Station Rating',
  'tox_lc50': 'LC50',
  'tox_exposure': 'Exposure Time',
  'tox_concentration': 'Concentration',
  'tox_temperature': 'Temperature (°C)',

  // Mechanical Impact
  'mech_rating': 'Rating',
  'mech_energy': 'Impact Energy',
  'mech_velocity': 'Velocity',
  'mech_temperature': 'Temperature',

  // Generic fields that apply to multiple test types
  'pressure': 'Press. (psia)',
  'temperature': 'Temperature',
  'temperaturemaximum': 'Use Temp Max(F)',
  'temperatureminimum': 'Use Temp Min(F)',
  'oxygen_percent': 'Oxy. %',
  'gas_name': 'Gas Name',
  'gas_percent': 'Gas %',
  'weight': 'Wt. (gm)',
  'duration': 'Duration',
  'mount_device': 'Mount Device',
  'datasource': 'Data Source',
  'standardflag': 'Std. Flag',
  'samplecount': 'Sample Count',
  'nonstandardflag': 'Non-Standard Flag',
  'testreportkey': 'Test Rpt. Key',
  'testtypekey': 'Test Type Key',
  'testno': 'Test No./Type',
  'composition': 'Composition',
  'usetype': 'Use Type',
};

// Helper to check if a value is populated
function isPopulated(value: any): boolean {
  if (value === undefined || value === null || value === '') return false;

  // Check for string representations of null/empty
  if (typeof value === 'string') {
    const normalized = value.trim().toUpperCase();
    if (normalized === 'NULL' || normalized === 'N/A' || normalized === 'NONE') return false;
  }

  return true;
}

// Helper to format field value for display
function formatValue(value: any): string {
  if (!isPopulated(value)) return '—';
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'boolean') return value ? 'Y' : 'N';
  return String(value);
}

// Get human-readable label for a field
function getFieldLabel(fieldName: string): string {
  // Try exact match first
  const lower = fieldName.toLowerCase();
  if (FIELD_LABELS[lower]) return FIELD_LABELS[lower];

  // Try without prefix (e.g., "flam_pressure" -> "pressure")
  const parts = lower.split('_');
  if (parts.length > 1) {
    const withoutPrefix = parts.slice(1).join('_');
    if (FIELD_LABELS[withoutPrefix]) return FIELD_LABELS[withoutPrefix];
  }

  // Fallback: convert snake_case to Title Case
  return fieldName
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

// Formatted Report Component - DYNAMIC based on populated fields
function FormattedReport({
  record,
  testType,
  isFluidCompatibility = false,
}: {
  record: TestRecord;
  testType: string;
  isFluidCompatibility?: boolean;
}) {
  const data = {
    ...(record.test_results || {}),
    ...(record.tested_fluid ? { tested_fluid: record.tested_fluid } : {}),
  };

  // Blacklist of internal/technical fields that should never display
  const BLACKLIST_FIELDS = [
    'materialkey',
    'materialcode',
    'composition',
    'usetype',
    'temperaturemaximum',
    'temperatureminimum',
    'arc_key',
    'arc_moc_raw',
    'arc_moc_units',
    'arc_moc_o2_pct',  // Duplicate of arc_oxygenpercent
    'arc_nhbtest',
    'arc_dataexpireflag',
    'arc_updateoperatorid',
    'testreportkey',
    'testtypekey',
    'arc_cleanflag',
    'arc_cleannumber',
    'arc_curesequence',
    'arc_datacatagory',
    'arc_seq_res',
    'arc_sequence',
    'arc_tr_cure',
    'arc_reference',
    'nonstandardflag',
    'specification',
  ];

  // Get all populated fields
  const populatedFields = Object.entries(data)
    .filter(([key, value]) => isPopulated(value))
    .filter(([key]) => !BLACKLIST_FIELDS.includes(key.toLowerCase())) // Exclude blacklisted fields
    .sort(([keyA], [keyB]) => {
      // Prioritize certain fields first
      const priority: Record<string, number> = {
        'testreportnumber': 1,
        'testtype': 2,
        'testtypecaption': 2,
        'rating': 3,
      };

      const prioA = priority[keyA.toLowerCase()] || 100;
      const prioB = priority[keyB.toLowerCase()] || 100;

      if (prioA !== prioB) return prioA - prioB;
      return keyA.localeCompare(keyB);
    });

  // Group fields into rows of 2 columns (MAPTIS style: 2 label+value pairs per row)
  const rows: Array<Array<[string, any]>> = [];
  for (let i = 0; i < populatedFields.length; i += 2) {
    rows.push(populatedFields.slice(i, i + 2));
  }

  return (
    <div className="space-y-6 print:text-black print:bg-white">
      {/* Report Title - MAPTIS Style */}
      <div className="text-center pb-3">
        <h2 className="text-2xl font-bold">Non-Metals {testType}</h2>
      </div>

      {/* Material Definition Properties - MAPTIS Style */}
      <div className="space-y-2">
        <h3 className="font-bold text-base">Material Definition Properties</h3>
        <div className="pl-4 space-y-1 text-sm">
          <div><span className="font-semibold">Material Code:</span> {record.material_code || `MAT-${record.material_key}`}</div>
          <div><span className="font-semibold">Designation:</span> {record.material_designation || 'N/A'}</div>
          {isFluidCompatibility && record.tested_fluid && (
            <div><span className="font-semibold">Tested Fluid:</span> {record.tested_fluid}</div>
          )}
          {data.composition && <div><span className="font-semibold">Composition:</span> {data.composition}</div>}
          {data.usetype && <div><span className="font-semibold">Use Type:</span> {data.usetype}</div>}
          {data.temperatureminimum !== undefined && data.temperatureminimum !== null && (
            <div><span className="font-semibold">Use Temp Min(F):</span> {data.temperatureminimum}</div>
          )}
          {data.temperaturemaximum !== undefined && data.temperaturemaximum !== null && (
            <div><span className="font-semibold">Use Temp Max(F):</span> {data.temperaturemaximum}</div>
          )}
        </div>
      </div>

      {/* Test Parameters Table - MAPTIS 2-Column Style */}
      <div className="space-y-2">
        <h3 className="font-bold text-base">Non-Metals: {testType}</h3>

        <table className="w-full border-collapse border border-black text-sm">
          <tbody>
            {rows.map((row, rowIdx) => (
              <tr key={rowIdx}>
                {row.map(([fieldName, value], colIdx) => (
                  <Fragment key={`${rowIdx}-${fieldName}-${colIdx}`}>
                    <td className="border border-black px-3 py-2 font-semibold bg-gray-50 print:bg-gray-50 w-[25%]">
                      {getFieldLabel(fieldName)}
                    </td>
                    <td className="border border-black px-3 py-2 w-[25%]">
                      {formatValue(value)}
                    </td>
                  </Fragment>
                ))}
                {/* Fill empty columns if row has only 1 field */}
                {row.length === 1 && (
                  <>
                    <td className="border border-black px-3 py-2 bg-gray-50 print:bg-gray-50 w-[25%]"></td>
                    <td className="border border-black px-3 py-2 w-[25%]"></td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer - MAPTIS Style */}
      <div className="text-center text-xs text-muted-foreground pt-4 print:text-gray-600">
        <p className="font-semibold">MIRA - Materials Intelligence & Risk Analysis</p>
        <p className="mt-1">Test Report Reference: {data.testreportnumber || 'N/A'} | Material Key: {record.material_key}</p>
        <p className="mt-2 font-semibold text-primary">BoundState.AI</p>
      </div>

      {/* Page Footer - MAPTIS Style */}
      <div className="text-xs text-muted-foreground print:text-gray-600 flex justify-between border-t pt-2 mt-4">
        <span>{new Date().toLocaleDateString()} {new Date().toLocaleTimeString()}</span>
        <span>Page 1</span>
      </div>
    </div>
  );
}

// Helper to format dates
function formatDate(dateStr: any): string | null {
  if (!dateStr || dateStr === 'NULL' || dateStr === null) return null;
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return null;
    return date.toLocaleDateString('en-US');
  } catch {
    return null;
  }
}

function getRatingVariant(rating: string): "default" | "secondary" | "destructive" | "outline" {
  const r = rating.toUpperCase();

  // Green/Blue (Good/Pass)
  if (['A', 'P'].includes(r)) return 'default';

  // Yellow/Gray (Borderline/Conditional)
  if (['B', 'C', 'S', 'N', 'Z', 'H', 'K', 'V', '7'].includes(r)) return 'secondary';

  // Red (Fail/Dangerous)
  if (['D', 'X', 'I', 'U', 'F'].includes(r)) return 'destructive';

  // Default
  return 'outline';
}
