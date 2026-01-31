import { useState } from "react";
import { Search, Sparkles, Info, List, Table as TableIcon, Eye, ArrowUpDown, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  ColumnDef,
  SortingState,
} from "@tanstack/react-table";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const exampleQueries = [
  "Show me oxygen-compatible metals for cryogenic service",
  "Materials rated for 3000 psi GOX with low permeability",
  "Compare Inconel 718 vs Hastelloy C-276 mechanical properties",
  "Test results for polymers exposed to hydrazine",
];

interface MaterialResult {
  materialkey: string;
  material_key: string | number;
  canonical_name: string;
  material_code: string;
  spec_ids: string[];
  o2_rating: string | null;
  flamm_rating: string | null;
  corr_rating: string | null;
  scc_rating: string | null;
  tvs_rating: string | null;
  tox_rating: string | null;
  fs_rating: string | null;
  mech_rating: string | null;
  fluid_rating: string | null;
  yield_strength: number;
  test_classes: string[];
  provenance_count: number;
  data_quality_score: number;
  ui_percent: number;
  temperature_range: { min_f: number; max_f: number } | null;
  preview: string;
  row_uid: string;
  material_type_name?: string;
  test_counts?: Record<string, number>;
  total_tests?: number;
}

export default function Query() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MaterialResult[]>([]);
  const [debugInfo, setDebugInfo] = useState<{ servedPath: string; pipeline: string } | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [activeTab, setActiveTab] = useState("cards");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [selectedMaterial, setSelectedMaterial] = useState<MaterialResult | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;

    setIsSearching(true);

    try {
      // Use simple MAPTIS semantic search
      const response = await fetch(`${API_URL}/api/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          top_k: 25
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();

      setDebugInfo({
        servedPath: data.served_path || "/api/search",
        pipeline: data.pipeline || "semantic"
      });

      // Transform /api/search results to display format
      const searchResults = Array.isArray(data.results) ? data.results : [];
      const transformedResults: MaterialResult[] = searchResults.map((result: Record<string, unknown>, idx: number) => ({
        materialkey: (result.material_key as string) ?? `result-${idx}`,
        material_key: (result.material_key as string) ?? idx,
        canonical_name: (result.material_designation as string) || (result.preview as string) || `Material ${idx + 1}`,
        material_code: (result.material_code as string) || "N/A",
        spec_ids: [],
        o2_rating: (result.o2_rating as string) || null,
        flamm_rating: (result.flamm_rating as string) || null,
        corr_rating: (result.cor_rating as string) || (result.corr_rating as string) || null,
        scc_rating: (result.stress_rating as string) || (result.scc_rating as string) || null,
        tvs_rating: (result.tvs_rating as string) || null,
        tox_rating: (result.tox_rating as string) || null,
        fs_rating: (result.fs_rating as string) || null,
        mech_rating: (result.mech_rating as string) || null,
        fluid_rating: (result.fluid_rating as string) || null,
        yield_strength: 0,
        test_classes: [],
        provenance_count: 1,
        data_quality_score: (result.score as number) || (result.similarity_score as number) || 0,
        ui_percent: Math.round(((result.score as number) || (result.similarity_score as number) || 0) * 100),
        temperature_range: null,
        preview: (result.preview as string) || (result.material_designation as string) || "",
        row_uid: (result.row_uid as string) || `result-${idx}`,
      }));

      setResults(transformedResults);
    } catch (error) {
      console.error("Search error:", error);
      alert("Search failed. Make sure the MAPTIS backend is running (uvicorn on port 8000)");
      setResults([]);
      setDebugInfo(null);
    } finally {
      setIsSearching(false);
    }
  };

  const handleViewDetails = async (result: MaterialResult) => {
    try {
      const response = await fetch(`${API_URL}/api/material/${result.materialkey}/summary`);

      if (!response.ok) {
        console.error("Failed to fetch material summary");
        setSelectedMaterial({
          ...result,
          material_key: result.materialkey || result.material_key,
        });
        setIsDialogOpen(true);
        return;
      }

      const summary = await response.json();

      const enrichedMaterial: MaterialResult = {
        ...result,
        materialkey: result.materialkey,
        material_key: summary.material_key || result.materialkey || result.material_key,
        material_code: summary.material_code || result.material_code,
        material_type_name: summary.material_type_name || result.material_type_name,
        flamm_rating: summary.maptis_ratings?.flamm_rating || summary.flamm_rating,
        corr_rating: summary.maptis_ratings?.corr_rating || summary.corr_rating,
        scc_rating: summary.maptis_ratings?.scc_rating || summary.scc_rating,
        tvs_rating: summary.maptis_ratings?.tvs_rating || summary.tvs_rating,
        tox_rating: summary.maptis_ratings?.tox_rating || summary.tox_rating,
        fs_rating: summary.maptis_ratings?.fs_rating || summary.fs_rating,
        o2_rating: summary.maptis_ratings?.o2_rating || summary.o2_rating,
        mech_rating: summary.maptis_ratings?.mech_rating,
        test_counts: summary.test_counts,
        total_tests: summary.total_tests,
      };

      setSelectedMaterial(enrichedMaterial);
      setIsDialogOpen(true);
    } catch (error) {
      console.error("Error fetching material details:", error);
      setSelectedMaterial(result);
      setIsDialogOpen(true);
    }
  };

  const getRatingBadgeClass = (rating: string | null) => {
    if (!rating || rating === "No data") return "";
    switch (rating) {
      case "A": return "bg-green-100 text-green-800 border-green-300";
      case "B": return "bg-blue-100 text-blue-800 border-blue-300";
      case "C": return "bg-yellow-100 text-yellow-800 border-yellow-300";
      case "D":
      case "X": return "bg-red-100 text-red-800 border-red-300";
      default: return "";
    }
  };

  // Table columns definition
  const columns: ColumnDef<MaterialResult>[] = [
    {
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
        />
      ),
    },
    {
      accessorKey: "canonical_name",
      header: ({ column }) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-auto p-0 hover:bg-transparent"
        >
          Material Name
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.canonical_name}</div>
          <div className="text-xs text-muted-foreground font-mono">
            {row.original.materialkey}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "o2_rating",
      header: "O2",
      cell: ({ row }) => {
        const rating = row.original.o2_rating;
        if (!rating || rating === "No data") {
          return <span className="text-xs text-muted-foreground">-</span>;
        }
        return <Badge variant="outline" className={getRatingBadgeClass(rating)}>{rating}</Badge>;
      },
    },
    {
      accessorKey: "flamm_rating",
      header: "Flammability",
      cell: ({ row }) => {
        const rating = row.original.flamm_rating;
        if (!rating || rating === "No data") {
          return <span className="text-xs text-muted-foreground">-</span>;
        }
        return <Badge variant="outline" className={getRatingBadgeClass(rating)}>{rating}</Badge>;
      },
    },
    {
      accessorKey: "corr_rating",
      header: "Corrosion",
      cell: ({ row }) => {
        const rating = row.original.corr_rating;
        if (!rating || rating === "No data") {
          return <span className="text-xs text-muted-foreground">-</span>;
        }
        return <Badge variant="outline" className={getRatingBadgeClass(rating)}>{rating}</Badge>;
      },
    },
    {
      accessorKey: "scc_rating",
      header: "Stress Corr",
      cell: ({ row }) => {
        const rating = row.original.scc_rating;
        if (!rating || rating === "No data") {
          return <span className="text-xs text-muted-foreground">-</span>;
        }
        return <Badge variant="outline" className={getRatingBadgeClass(rating)}>{rating}</Badge>;
      },
    },
    {
      accessorKey: "tvs_rating",
      header: "Outgassing",
      cell: ({ row }) => {
        const rating = row.original.tvs_rating;
        if (!rating || rating === "No data") {
          return <span className="text-xs text-muted-foreground">-</span>;
        }
        return <Badge variant="outline" className={getRatingBadgeClass(rating)}>{rating}</Badge>;
      },
    },
    {
      accessorKey: "ui_percent",
      header: ({ column }) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-auto p-0 hover:bg-transparent"
        >
          Match Score
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const score = row.original.ui_percent || 0;
        return (
          <div className="flex items-center gap-2">
            <div className="w-12 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary"
                style={{ width: `${score}%` }}
              />
            </div>
            <span className="text-xs text-muted-foreground">
              {score}%
            </span>
          </div>
        );
      },
    },
    {
      id: "actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => handleViewDetails(row.original)}
          >
            <Eye className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data: results,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: setSorting,
    state: {
      sorting,
    },
  });

  return (
    <div className="min-h-full bg-background">
      {/* Hero search area */}
      <div className="bg-card border-b border-border">
        <div className="max-w-4xl mx-auto px-6 py-12">
          <div className="mb-8">
            <h1 className="text-4xl font-serif font-bold mb-1 text-balance flex items-center gap-3">
              MIRA
              <PageHelp content={helpContent.query} />
            </h1>
            <p className="text-lg text-muted-foreground mb-1">
              Materials Intelligence & Risk Analysis
            </p>
            <p className="text-sm text-muted-foreground">
              Ask MAPTIS questions in natural language
            </p>
          </div>

          <div className="flex gap-2 mb-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="Describe what you're looking for..."
                className="pl-10 h-12 text-base"
              />
            </div>

            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="icon" className="h-12 w-12 shrink-0">
                  <Sparkles className="h-5 w-5" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80" align="end">
                <div className="space-y-3">
                  <div className="flex items-start gap-2">
                    <Info className="h-4 w-4 mt-0.5 text-primary shrink-0" />
                    <p className="text-sm text-muted-foreground">
                      <span className="text-primary font-medium">Hybrid Search Active.</span> Queries are parsed for intent, constraints, and entities before semantic search.
                    </p>
                  </div>
                  {query.trim() ? (
                    <div className="p-3 bg-primary/5 border border-primary/20 rounded-md text-sm">
                      <p className="font-medium mb-2">Your query:</p>
                      <p className="text-muted-foreground italic">"{query}"</p>
                      <p className="text-xs text-primary mt-3">
                        Intent classification + constraint extraction active
                      </p>
                    </div>
                  ) : (
                    <div className="p-3 bg-muted rounded-md text-sm font-mono text-muted-foreground">
                      <p className="mb-2 font-medium">Parsed constraints:</p>
                      intent: comparison<br/>
                      materials: [Inconel 718, Hastelloy C-276]<br/>
                      properties: mechanical
                    </div>
                  )}
                </div>
              </PopoverContent>
            </Popover>

            <Button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="h-12 px-6"
            >
              {isSearching ? "Searching..." : "Search"}
            </Button>
          </div>

          {/* Example queries */}
          <div className="flex flex-wrap gap-2">
            {exampleQueries.map((example, i) => (
              <Button
                key={i}
                variant="ghost"
                size="sm"
                onClick={() => setQuery(example)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* Results area */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {results.length === 0 && !isSearching && (
          <div className="text-center py-16">
            <Search className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-medium mb-2">No search yet</h3>
            <p className="text-muted-foreground text-sm">
              Try one of the example queries above to get started
            </p>
          </div>
        )}

        {isSearching && (
          <div className="space-y-4">
            {[1, 2].map((i) => (
              <Card key={i} className="p-6 animate-pulse">
                <div className="h-6 bg-muted rounded w-1/3 mb-4" />
                <div className="h-4 bg-muted rounded w-2/3 mb-3" />
                <div className="flex gap-2">
                  <div className="h-6 bg-muted rounded w-20" />
                  <div className="h-6 bg-muted rounded w-20" />
                </div>
              </Card>
            ))}
          </div>
        )}

        {debugInfo && (
          <div className="flex justify-end mb-4">
            <Badge variant="secondary" className="text-xs font-mono">
              {debugInfo.servedPath} - {debugInfo.pipeline}
            </Badge>
          </div>
        )}

        {results.length > 0 && (
          <div className="animate-subtle-fade-in">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <div className="flex items-center justify-between mb-4">
                <TabsList>
                  <TabsTrigger value="cards" className="gap-2">
                    <List className="h-4 w-4" />
                    Cards
                  </TabsTrigger>
                  <TabsTrigger value="table" className="gap-2">
                    <TableIcon className="h-4 w-4" />
                    Table
                  </TabsTrigger>
                </TabsList>
                <div className="flex items-center gap-2">
                  <p className="text-sm text-muted-foreground">
                    Found {results.length} materials
                  </p>
                  <Button variant="outline" size="sm">
                    <Download className="h-4 w-4 mr-2" />
                    Export CSV
                  </Button>
                </div>
              </div>

              <TabsContent value="cards" className="space-y-4 mt-0">
                {results.map((result) => (
                  <Card
                    key={result.row_uid}
                    className="p-6 hover:border-primary transition-colors cursor-pointer"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <h3 className="text-lg font-serif font-semibold mb-1">
                          {result.canonical_name}
                        </h3>
                        <p className="text-sm text-muted-foreground font-mono">
                          Code: {result.material_code || (result.material_key ? `MAT-${result.material_key}` : 'N/A')}
                        </p>
                      </div>
                      <Badge variant="outline" className="shrink-0">
                        Score: {result.ui_percent ?? 0}%
                      </Badge>
                    </div>

                    <div className="flex flex-wrap gap-2 mb-4">
                      {result.test_classes.map((tc: string) => (
                        <Badge key={tc} variant="secondary">{tc}</Badge>
                      ))}
                      {result.temperature_range && (
                        <Badge variant="outline">
                          Temp: {result.temperature_range.min_f || 'N/A'}F to {result.temperature_range.max_f || 'N/A'}F
                        </Badge>
                      )}
                    </div>

                    {result.preview && result.preview.trim() && (
                      <p className="text-sm text-muted-foreground mb-4 font-mono truncate">
                        {result.preview}
                      </p>
                    )}

                    <div className="flex items-center gap-4 text-sm">
                      <Button
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => handleViewDetails(result)}
                      >
                        View details
                      </Button>
                      <span className="text-muted-foreground">
                        {result.row_uid}
                      </span>
                    </div>
                  </Card>
                ))}
              </TabsContent>

              <TabsContent value="table" className="mt-0">
                <Card>
                  <Table>
                    <TableHeader>
                      {table.getHeaderGroups().map((headerGroup) => (
                        <TableRow key={headerGroup.id}>
                          {headerGroup.headers.map((header) => (
                            <TableHead key={header.id} className="bg-muted/50">
                              {header.isPlaceholder
                                ? null
                                : flexRender(
                                    header.column.columnDef.header,
                                    header.getContext()
                                  )}
                            </TableHead>
                          ))}
                        </TableRow>
                      ))}
                    </TableHeader>
                    <TableBody>
                      {table.getRowModel().rows.length ? (
                        table.getRowModel().rows.map((row) => (
                          <TableRow
                            key={row.id}
                            data-state={row.getIsSelected() && "selected"}
                            className="cursor-pointer hover:bg-muted/50"
                          >
                            {row.getVisibleCells().map((cell) => (
                              <TableCell key={cell.id}>
                                {flexRender(
                                  cell.column.columnDef.cell,
                                  cell.getContext()
                                )}
                              </TableCell>
                            ))}
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell
                            colSpan={columns.length}
                            className="h-24 text-center"
                          >
                            No results found
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </Card>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>

      {/* Material Details Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-serif">
              {selectedMaterial?.canonical_name || 'Material Details'}
            </DialogTitle>
          </DialogHeader>

          {selectedMaterial && (
            <div className="space-y-6">
              <div>
                <h3 className="font-semibold mb-3">Basic Information</h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">Material Code</p>
                    <p className="font-mono font-bold">{selectedMaterial.material_code || (selectedMaterial.material_key ? `MAT-${selectedMaterial.material_key}` : 'N/A')}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Material Key</p>
                    <p className="font-mono">{selectedMaterial.material_key || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Material Type</p>
                    <p>{selectedMaterial.material_type_name || 'Unknown'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Match Score</p>
                    <p>{selectedMaterial.ui_percent}%</p>
                  </div>
                </div>
              </div>

              <div>
                <h3 className="font-semibold mb-3">MAPTIS Ratings</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Flammability</p>
                    {selectedMaterial.flamm_rating && selectedMaterial.flamm_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.flamm_rating)}>{selectedMaterial.flamm_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Corrosion</p>
                    {selectedMaterial.corr_rating && selectedMaterial.corr_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.corr_rating)}>{selectedMaterial.corr_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">SCC</p>
                    {selectedMaterial.scc_rating && selectedMaterial.scc_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.scc_rating)}>{selectedMaterial.scc_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">TVS</p>
                    {selectedMaterial.tvs_rating && selectedMaterial.tvs_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.tvs_rating)}>{selectedMaterial.tvs_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Toxicity</p>
                    {selectedMaterial.tox_rating && selectedMaterial.tox_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.tox_rating)}>{selectedMaterial.tox_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Fluid Systems</p>
                    {selectedMaterial.fs_rating && selectedMaterial.fs_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.fs_rating)}>{selectedMaterial.fs_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">O2 Compatibility</p>
                    {selectedMaterial.o2_rating && selectedMaterial.o2_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.o2_rating)}>{selectedMaterial.o2_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs mb-1">Mechanical Impact</p>
                    {selectedMaterial.mech_rating && selectedMaterial.mech_rating !== 'No data' ? (
                      <Badge className={getRatingBadgeClass(selectedMaterial.mech_rating)}>{selectedMaterial.mech_rating}</Badge>
                    ) : <span className="text-xs text-muted-foreground">-</span>}
                  </div>
                </div>
              </div>

              {selectedMaterial.yield_strength && selectedMaterial.yield_strength > 0 && (
                <div>
                  <h3 className="font-semibold mb-3">Mechanical Properties</h3>
                  <div className="text-sm">
                    <p className="text-muted-foreground">Yield Strength</p>
                    <p>{selectedMaterial.yield_strength.toLocaleString()} ksi</p>
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button onClick={() => setIsDialogOpen(false)}>
                  Close
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
