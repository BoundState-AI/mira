import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { useToast } from "@/hooks/use-toast";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";
import { Sparkles, FileSpreadsheet, CheckCircle2, FileCheck, Download, FileText, Settings2 } from "lucide-react";

// SLS Default environment values
const SLS_DEFAULTS = {
  minPressure: 0.0,
  maxPressure: 14.7,
  minTemp: 0,
  maxTemp: 120,
  media: ["Air", "Vacuum"],
  o2Percent: 20.9,
};

export default function MIULBuilder() {
  const { t } = useTranslation('miulBuilder');
  const { toast } = useToast();
  const [drawingFiles, setDrawingFiles] = useState<FileList | null>(null);
  const [bomFile, setBomFile] = useState<File | null>(null);
  const [uploadMethod, setUploadMethod] = useState<"pdf" | "bom" | "msfc">("pdf");

  // MIUL extractor state
  const [msfcDrawings, setMsfcDrawings] = useState<FileList | null>(null);
  const [drawingTreeFile, setDrawingTreeFile] = useState<File | null>(null);
  const [nhaOverridesFile, setNhaOverridesFile] = useState<File | null>(null);
  const [programName, setProgramName] = useState<string>("");
  const [hardwareName, setHardwareName] = useState<string>("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [generatedFile, setGeneratedFile] = useState<string | null>(null);
  const [verificationResult, setVerificationResult] = useState<{
    status: string;
    missing_from_miul: string[];
    hierarchy_errors: { child: string; dt_parent: string; miul_nha: string }[];
    summary: { dt_count: number; miul_count: number; missing_count: number; hierarchy_error_count: number };
  } | null>(null);
  const [isEnriching, setIsEnriching] = useState(false);
  const [enrichedFile, setEnrichedFile] = useState<string | null>(null);
  const [isGeneratingMUAs, setIsGeneratingMUAs] = useState(false);
  const [muaProgress, setMuaProgress] = useState(0);
  const [muaResults, setMuaResults] = useState<{ materials_processed: number; muas_generated: number } | null>(null);

  // Environment configuration
  const [useSLSDefaults, setUseSLSDefaults] = useState(true);
  const [minPressure, setMinPressure] = useState(SLS_DEFAULTS.minPressure);
  const [maxPressure, setMaxPressure] = useState(SLS_DEFAULTS.maxPressure);
  const [minTemp, setMinTemp] = useState<number | string>(SLS_DEFAULTS.minTemp);
  const [maxTemp, setMaxTemp] = useState<number | string>(SLS_DEFAULTS.maxTemp);
  const [selectedMedia, setSelectedMedia] = useState<string[]>(SLS_DEFAULTS.media);
  const [o2Percent, setO2Percent] = useState(SLS_DEFAULTS.o2Percent);

  const availableMedia = ["Air", "Vacuum", "GOX", "LOX", "GH2", "LH2", "GN2", "LN2", "Helium", "Hydraulic Fluid"];

  const toggleMedia = (medium: string) => {
    setSelectedMedia(prev =>
      prev.includes(medium) ? prev.filter(m => m !== medium) : [...prev, medium]
    );
  };

  const handleSLSDefaultsChange = (checked: boolean) => {
    setUseSLSDefaults(checked);
    if (checked) {
      setMinPressure(SLS_DEFAULTS.minPressure);
      setMaxPressure(SLS_DEFAULTS.maxPressure);
      setMinTemp(SLS_DEFAULTS.minTemp);
      setMaxTemp(SLS_DEFAULTS.maxTemp);
      setSelectedMedia(SLS_DEFAULTS.media);
      setO2Percent(SLS_DEFAULTS.o2Percent);
    }
  };

  const generateMIUL = async () => {
    if (uploadMethod === 'pdf' && (!drawingFiles || drawingFiles.length === 0)) {
      alert('Please select PDF drawings first');
      return;
    }
    if (uploadMethod === 'bom' && !bomFile) {
      alert('Please upload a BOM file first');
      return;
    }
    if (uploadMethod === 'msfc' && (!msfcDrawings || msfcDrawings.length === 0)) {
      alert('Please select PDF drawings first');
      return;
    }

    setIsProcessing(true);
    setGeneratedFile(null);
    setEnrichedFile(null);
    setVerificationResult(null);

    try {
      const form = new FormData();

      if (uploadMethod === 'msfc') {
        // Compliant MIUL - 3-pass extraction with anti-hallucination
        Array.from(msfcDrawings!).forEach((f) => form.append('drawings', f));

        // Add Drawing Tree file if provided
        if (drawingTreeFile) {
          form.append('drawing_tree', drawingTreeFile);
        }

        // Add NHA overrides file if provided
        if (nhaOverridesFile) {
          form.append('nha_overrides', nhaOverridesFile);
        }

        form.append('project', programName || '');
        form.append('miul_number', programName || '');

        // Add environment fields
        form.append('min_pressure', String(minPressure));
        form.append('max_pressure', String(maxPressure));
        form.append('min_temperature', String(minTemp));
        form.append('max_temperature', String(maxTemp));
        form.append('o2_concentration', String(o2Percent));
        form.append('service_media', selectedMedia.join(', '));

        // Use v3 pipeline (enhanced multi-location material search)
        // Call Railway directly to avoid Vercel proxy timeout (extraction takes 2-3 min)
        const endpoint = 'https://mira-production-33c3.up.railway.app/api/miul/v3-extract';
        const pipelineDesc = "v3: PDF → Vision → OCR Correction → Material Form → MIUL";

        toast({ title: "MIUL Pipeline Running", description: pipelineDesc });

        const resp = await fetch(endpoint, { method: 'POST', body: form });
        if (!resp.ok) {
          const errorText = await resp.text();
          throw new Error(`Vision extraction failed: ${resp.status} - ${errorText}`);
        }

        // Read verification headers if present (v1 format)
        const verificationStatus = resp.headers.get('X-DT-Verification-Status');
        if (verificationStatus) {
          const missingCount = parseInt(resp.headers.get('X-DT-Missing-Count') || '0');
          const hierarchyErrors = parseInt(resp.headers.get('X-DT-Hierarchy-Error-Count') || '0');
          const miulCount = parseInt(resp.headers.get('X-DT-MIUL-Count') || '0');
          const dtCount = parseInt(resp.headers.get('X-DT-Count') || '0');
          const missingAssemblies = JSON.parse(resp.headers.get('X-DT-Missing-Assemblies') || '[]');

          setVerificationResult({
            status: verificationStatus,
            missing_from_miul: missingAssemblies,
            hierarchy_errors: [],  // Not included in headers for brevity
            summary: {
              dt_count: dtCount,
              miul_count: miulCount,
              missing_count: missingCount,
              hierarchy_error_count: hierarchyErrors,
            },
          });
        }

        // Read v2/v3 pipeline headers if present
        const v2MiulCount = resp.headers.get('X-MIUL-Count');
        const v2DrawingCount = resp.headers.get('X-Drawing-Count');
        const v2BlockerCount = resp.headers.get('X-Blocker-Count');
        const v2WarningCount = resp.headers.get('X-Warning-Count');
        const v2RootAssembly = resp.headers.get('X-Root-Assembly');
        const v2PackageId = resp.headers.get('X-Package-ID');
        const dtConfidence = resp.headers.get('X-DT-Confidence');
        const nhaOverrideCount = resp.headers.get('X-NHA-Override-Count');
        const manualOverrideUsed = resp.headers.get('X-Manual-Override-Used');

        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        setGeneratedFile(url);

        const a = document.createElement('a');
        a.href = url;
        a.download = `MIUL_${programName || 'DMLLV'}.xlsx`;
        a.click();

        // Toast with results info
        if (v2MiulCount) {
          const blockers = parseInt(v2BlockerCount || '0');
          const warnings = parseInt(v2WarningCount || '0');
          const root = v2RootAssembly || 'auto-detected';
          const confidence = dtConfidence || 'N/A';
          const overrides = nhaOverrideCount || '0';
          const usedManual = manualOverrideUsed === 'true';

          const confidenceNote = confidence === 'HIGH'
            ? 'DT extraction: HIGH confidence'
            : confidence === 'MEDIUM'
            ? 'DT extraction: MEDIUM confidence (review NHA)'
            : confidence === 'LOW'
            ? 'DT extraction: LOW confidence (recommend manual override)'
            : '';

          if (blockers > 0) {
            toast({
              title: "MIUL Pipeline Complete (with blockers)",
              description: `${v2MiulCount} MIUL entries, ${v2DrawingCount} drawings. ${blockers} blockers. ${confidenceNote}`,
              variant: "destructive",
            });
          } else {
            toast({
              title: "MIUL Pipeline Complete",
              description: `${v2MiulCount} MIUL entries. ${overrides} NHA mappings${usedManual ? ' (manual override)' : ' (auto-generated)'}. ${confidenceNote}`,
            });
          }
        } else {
          toast({
            title: "MIUL Pipeline Complete",
            description: `Processed ${msfcDrawings!.length} drawings`,
          });
        }

      } else if (uploadMethod === 'pdf') {
        Array.from(drawingFiles!).forEach((f) => form.append('drawings', f));

        // Add environment fields
        form.append('min_pressure', String(minPressure));
        form.append('max_pressure', String(maxPressure));
        form.append('min_temperature', String(minTemp));
        form.append('max_temperature', String(maxTemp));
        form.append('o2_concentration', String(o2Percent));
        form.append('service_media', selectedMedia.join(', '));
        if (programName) form.append('project', programName);

        toast({ title: "MIUL Pipeline Running", description: "v1: Drawing Tree → Vision → Merge → MIUL" });

        const resp = await fetch(`/api/miul/extract`, { method: 'POST', body: form });
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);

        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        setGeneratedFile(url);

        const a = document.createElement('a');
        a.href = url;
        a.download = 'MIUL_base.xlsx';
        a.click();
      } else {
        form.append('file', bomFile!);

        // Add environment fields
        form.append('min_pressure', String(minPressure));
        form.append('max_pressure', String(maxPressure));
        form.append('min_temperature', String(minTemp));
        form.append('max_temperature', String(maxTemp));
        form.append('o2_concentration', String(o2Percent));
        form.append('service_media', selectedMedia.join(', '));

        const resp = await fetch(`/api/bom/convert-to-miul`, { method: 'POST', body: form });
        if (!resp.ok) throw new Error(`BOM conversion failed: ${resp.status}`);

        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        setGeneratedFile(url);

        const a = document.createElement('a');
        a.href = url;
        a.download = 'MIUL_from_BOM.xlsx';
        a.click();

        toast({ title: "MIUL Generated from BOM", description: "You can now enrich it with MAPTIS ratings." });
      }
    } catch (e) {
      console.error('MIUL generation failed:', e);
      toast({ title: "Generation Failed", description: String(e), variant: "destructive" });
    } finally {
      setIsProcessing(false);
    }
  };

  const enrichWithRatings = async () => {
    if (!generatedFile) {
      alert('Please generate a MIUL first');
      return;
    }

    setIsEnriching(true);

    try {
      const fileBlob = await fetch(generatedFile).then(r => r.blob());
      const form = new FormData();
      form.append('file', fileBlob, 'miul.xlsx');

      const resp = await fetch(`/api/miul/enrich`, { method: 'POST', body: form });
      if (!resp.ok) throw new Error(`Enrichment API error: ${resp.status}`);

      const enrichedBlob = await resp.blob();
      const enrichedUrl = window.URL.createObjectURL(enrichedBlob);
      setEnrichedFile(enrichedUrl);

      const a = document.createElement('a');
      a.href = enrichedUrl;
      a.download = 'MIUL_enriched.xlsx';
      a.click();
    } catch (e) {
      console.error('Enrichment failed:', e);
      toast({ title: "Enrichment Failed", description: String(e), variant: "destructive" });
    } finally {
      setIsEnriching(false);
    }
  };

  const generateMUAs = async () => {
    if (!enrichedFile) {
      toast({ title: "Missing Enriched MIUL", description: "Please complete enrichment first", variant: "destructive" });
      return;
    }

    setIsGeneratingMUAs(true);
    setMuaProgress(0);
    setMuaResults(null);

    try {
      const fileBlob = await fetch(enrichedFile).then(r => r.blob());
      const formData = new FormData();
      formData.append('file', fileBlob, 'MIUL_enriched.xlsx');

      const progressInterval = setInterval(() => {
        setMuaProgress(prev => Math.min(prev + 10, 90));
      }, 200);

      const response = await fetch(
        `/api/mua/generate-batch?program=${encodeURIComponent(programName)}&hardware=${encodeURIComponent(hardwareName)}`,
        { method: 'POST', body: formData }
      );

      clearInterval(progressInterval);
      setMuaProgress(100);

      if (!response.ok) throw new Error('MUA generation failed');

      const data = await response.json();
      setMuaResults(data);

      toast({ title: "MUAs Generated", description: `Generated ${data.muas_generated} MUA documents` });
    } catch (error) {
      toast({ title: "Generation Failed", description: "Failed to generate MUA documents", variant: "destructive" });
    } finally {
      setIsGeneratingMUAs(false);
    }
  };

  const downloadMUAExcel = async () => {
    if (!enrichedFile) return;

    try {
      const fileBlob = await fetch(enrichedFile).then(r => r.blob());
      const formData = new FormData();
      formData.append('file', fileBlob, 'MIUL_enriched.xlsx');

      const response = await fetch(
        `/api/mua/generate-batch-excel?program=${encodeURIComponent(programName)}&hardware=${encodeURIComponent(hardwareName)}`,
        { method: 'POST', body: formData }
      );

      if (!response.ok) throw new Error('Download failed');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `MIUL_with_MUAs_${Date.now()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast({ title: "Download Complete", description: "Excel file with MUA documents has been downloaded" });
    } catch (error) {
      toast({ title: "Download Failed", description: "Failed to download Excel file", variant: "destructive" });
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Sparkles className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold flex items-center gap-3">
              MIUL Builder
              <PageHelp content={helpContent.miulBuilder} />
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Complete end-to-end workflow: Drawing → MIUL → MAPTIS Enrichment → MUA Generation
          </p>
        </div>
        <Badge variant="secondary">Production Ready</Badge>
      </div>

      <div className="max-w-4xl mx-auto space-y-6">
        {/* Program Configuration */}
        <Card className="bg-primary/5 border-primary/20">
          <CardContent className="pt-6">
            <h3 className="font-semibold text-lg mb-4">Program Configuration</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
              <div>
                <Label className="text-sm font-medium mb-2 block">Program Name</Label>
                <Input value={programName} onChange={(e) => setProgramName(e.target.value)} placeholder="Enter program name" />
              </div>
              <div>
                <Label className="text-sm font-medium mb-2 block">Hardware/System Name</Label>
                <Input value={hardwareName} onChange={(e) => setHardwareName(e.target.value)} placeholder="Enter hardware name" />
              </div>
            </div>

            {/* Environment Configuration */}
            <div className="border-t pt-4">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Settings2 className="h-4 w-4 text-muted-foreground" />
                  <h4 className="font-medium">Use Environment</h4>
                </div>
                <div className="flex items-center gap-2">
                  <Label htmlFor="sls-defaults" className="text-sm">Use SLS Defaults</Label>
                  <Switch id="sls-defaults" checked={useSLSDefaults} onCheckedChange={handleSLSDefaultsChange} />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Pressure Range */}
                <div>
                  <Label className="text-sm text-muted-foreground mb-2 block">Pressure Range (psia)</Label>
                  <div className="flex gap-2 items-center">
                    <Input
                      type="number"
                      value={minPressure}
                      onChange={(e) => setMinPressure(parseFloat(e.target.value))}
                      disabled={useSLSDefaults}
                      className="w-24"
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="number"
                      value={maxPressure}
                      onChange={(e) => setMaxPressure(parseFloat(e.target.value))}
                      disabled={useSLSDefaults}
                      className="w-24"
                    />
                  </div>
                </div>

                {/* Temperature Range */}
                <div>
                  <Label className="text-sm text-muted-foreground mb-2 block">Temperature Range (°F)</Label>
                  <div className="flex gap-2 items-center">
                    <Input
                      type="text"
                      inputMode="numeric"
                      value={minTemp}
                      onChange={(e) => {
                        const val = e.target.value;
                        // Allow empty, minus sign, or valid numbers (including negatives)
                        if (val === '' || val === '-' || /^-?\d*\.?\d*$/.test(val)) {
                          setMinTemp(val);
                        }
                      }}
                      onBlur={(e) => {
                        const num = parseFloat(e.target.value);
                        if (!isNaN(num)) setMinTemp(num);
                      }}
                      disabled={useSLSDefaults}
                      className="w-24"
                      placeholder="-423"
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="text"
                      inputMode="numeric"
                      value={maxTemp}
                      onChange={(e) => {
                        const val = e.target.value;
                        if (val === '' || val === '-' || /^-?\d*\.?\d*$/.test(val)) {
                          setMaxTemp(val);
                        }
                      }}
                      onBlur={(e) => {
                        const num = parseFloat(e.target.value);
                        if (!isNaN(num)) setMaxTemp(num);
                      }}
                      disabled={useSLSDefaults}
                      className="w-24"
                      placeholder="120"
                    />
                  </div>
                </div>

                {/* O2 Percentage */}
                <div>
                  <Label className="text-sm text-muted-foreground mb-2 block">Oxygen Concentration (%)</Label>
                  <Input
                    type="number"
                    step="0.1"
                    value={o2Percent}
                    onChange={(e) => setO2Percent(parseFloat(e.target.value))}
                    disabled={useSLSDefaults}
                    className="w-24"
                  />
                </div>

                {/* Media Selection */}
                <div>
                  <Label className="text-sm text-muted-foreground mb-2 block">Service Media</Label>
                  <div className="flex flex-wrap gap-2">
                    {availableMedia.map(medium => (
                      <div key={medium} className="flex items-center gap-1">
                        <Checkbox
                          id={`media-${medium}`}
                          checked={selectedMedia.includes(medium)}
                          onCheckedChange={() => toggleMedia(medium)}
                          disabled={useSLSDefaults}
                        />
                        <Label htmlFor={`media-${medium}`} className="text-xs cursor-pointer">{medium}</Label>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Step 1: Upload Source Files */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-sm font-bold text-primary">1</span>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Upload Source Files</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Choose between PDF drawings or direct BOM file upload
                </p>

                <Tabs defaultValue="pdf" onValueChange={(v) => setUploadMethod(v as "pdf" | "bom" | "msfc")}>
                  <TabsList className="grid w-full grid-cols-3 mb-4">
                    <TabsTrigger value="pdf" className="flex items-center gap-2">
                      <FileText className="h-4 w-4" />PDF Drawings
                    </TabsTrigger>
                    <TabsTrigger value="bom" className="flex items-center gap-2">
                      <FileSpreadsheet className="h-4 w-4" />BOM File
                    </TabsTrigger>
                    <TabsTrigger value="msfc" className="flex items-center gap-2 data-[state=active]:bg-purple-100 data-[state=active]:text-purple-700">
                      <Sparkles className="h-4 w-4" />MIUL v3
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="pdf" className="space-y-3">
                    <div className="p-4 border border-primary/20 bg-primary/5 rounded-lg">
                      <p className="text-xs text-muted-foreground mb-3">
                        Upload PDF drawings containing Bills of Materials.
                      </p>
                      <Input type="file" accept=".pdf" multiple onChange={(e) => setDrawingFiles(e.target.files)} />
                      {drawingFiles && (
                        <div className="text-sm text-muted-foreground mt-2">
                          <CheckCircle2 className="inline h-4 w-4 text-green-600 mr-1" />
                          {drawingFiles.length} file(s) selected
                        </div>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="bom">
                    <div className="p-4 border border-primary/20 bg-primary/5 rounded-lg">
                      <p className="text-xs text-muted-foreground mb-3">
                        Upload Excel, CSV, or text BOM file.
                      </p>
                      <Input type="file" accept=".xlsx,.xls,.csv,.txt" onChange={(e) => setBomFile(e.target.files?.[0] || null)} />
                      {bomFile && (
                        <div className="text-sm text-muted-foreground mt-2">
                          <CheckCircle2 className="inline h-4 w-4 text-green-600 mr-1" />
                          {bomFile.name} selected
                        </div>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="msfc" className="space-y-4">
                    <div className="p-4 border border-green-200 bg-green-50/50 rounded-lg">
                      <div className="flex items-start gap-3 mb-3">
                        <Sparkles className="h-5 w-5 text-green-600 mt-0.5" />
                        <div>
                          <p className="text-sm font-medium text-green-900">MIUL v3 Extractor</p>
                          <p className="text-xs text-green-700">
                            Enhanced extraction with NOTES parsing, OCR correction, and MAPTIS-compliant Excel output.
                          </p>
                        </div>
                      </div>

                      {/* Pipeline Info */}
                      <div className="mb-4 p-3 bg-purple-50 border border-purple-200 rounded-lg">
                        <p className="text-xs text-purple-700">
                          <strong>v3 Pipeline:</strong> PDF → Vision → OCR Correction → Material Form → MIUL
                        </p>
                        <p className="text-xs text-purple-600 mt-1">
                          Multi-location material search (title block, notes, flag notes, EPL). OCR error correction, spec validation, part number correction.
                        </p>
                      </div>

                      {/* Drawing Upload */}
                      <div>
                        <Label className="text-sm font-medium mb-2 block">
                          Engineering Drawing PDFs <span className="text-red-500">*</span>
                        </Label>
                        <p className="text-xs text-muted-foreground mb-2">
                          Upload PDF drawings containing Bills of Materials
                        </p>
                        <Input
                          type="file"
                          accept=".pdf"
                          multiple
                          onChange={(e) => setMsfcDrawings(e.target.files)}
                        />
                        {msfcDrawings && msfcDrawings.length > 0 && (
                          <div className="text-sm text-green-700 mt-2">
                            <CheckCircle2 className="inline h-4 w-4 mr-1" />
                            {msfcDrawings.length} drawing{msfcDrawings.length !== 1 ? 's' : ''} selected
                          </div>
                        )}
                      </div>

                      {/* Drawing Tree Upload */}
                      <div className="mt-4 pt-4 border-t border-green-200">
                        <Label className="text-sm font-medium mb-2 block">
                          Drawing Tree PDF <span className="text-yellow-600">(Optional - for hierarchy)</span>
                        </Label>
                        <p className="text-xs text-muted-foreground mb-2">
                          Upload Drawing Tree PDF to provide assembly hierarchy authority
                        </p>
                        <Input
                          type="file"
                          accept=".pdf"
                          onChange={(e) => setDrawingTreeFile(e.target.files?.[0] || null)}
                        />
                        {drawingTreeFile && (
                          <div className="text-sm text-yellow-700 mt-2">
                            <FileCheck className="inline h-4 w-4 mr-1" />
                            {drawingTreeFile.name} selected
                          </div>
                        )}
                      </div>

                      {/* NHA Overrides Upload */}
                      <div className="mt-4 pt-4 border-t border-green-200">
                        <Label className="text-sm font-medium mb-2 block">
                          NHA Overrides JSON <span className="text-blue-600">(Optional - manual corrections)</span>
                        </Label>
                        <p className="text-xs text-muted-foreground mb-2">
                          Upload JSON file with manual NHA corrections. Format: {`{"child_pn": "parent_pn", ...}`}
                        </p>
                        <Input
                          type="file"
                          accept=".json"
                          onChange={(e) => setNhaOverridesFile(e.target.files?.[0] || null)}
                        />
                        {nhaOverridesFile && (
                          <div className="text-sm text-blue-700 mt-2">
                            <FileCheck className="inline h-4 w-4 mr-1" />
                            {nhaOverridesFile.name} selected
                          </div>
                        )}
                      </div>
                    </div>
                  </TabsContent>
                </Tabs>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Step 2: Generate Base MIUL */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-sm font-bold text-primary">2</span>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Generate MIUL</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Extract parts, materials, and hierarchy from drawings.
                </p>
                <Button
                  onClick={generateMIUL}
                  disabled={
                    (uploadMethod === 'pdf' && !drawingFiles) ||
                    (uploadMethod === 'bom' && !bomFile) ||
                    (uploadMethod === 'msfc' && (!msfcDrawings || msfcDrawings.length === 0)) ||
                    isProcessing
                  }
                  size="lg"
                  className="w-full"
                >
                  {isProcessing ? (
                    <>
                      <Sparkles className="h-5 w-5 mr-2 animate-spin" />
                      Running V3 Pipeline...
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-5 w-5 mr-2" />
                      Generate MIUL
                      <Badge variant="secondary" className="ml-2 bg-purple-100 text-purple-700">v3</Badge>
                    </>
                  )}
                </Button>
                {generatedFile && !isProcessing && (
                  <div className="mt-3 space-y-3">
                    <div className="p-3 bg-green-50 border border-green-200 rounded-md">
                      <div className="flex items-center text-sm text-green-800">
                        <CheckCircle2 className="h-4 w-4 mr-2" />Base MIUL generated and downloaded!
                      </div>
                    </div>

                    {/* DT Verification Results */}
                    {verificationResult && (
                      <div className={`p-3 rounded-md border ${
                        verificationResult.status === 'PASS'
                          ? 'bg-green-50 border-green-300'
                          : 'bg-yellow-50 border-yellow-300'
                      }`}>
                        <div className="flex items-start gap-2">
                          {verificationResult.status === 'PASS' ? (
                            <CheckCircle2 className="h-5 w-5 text-green-600 mt-0.5" />
                          ) : (
                            <Settings2 className="h-5 w-5 text-yellow-600 mt-0.5" />
                          )}
                          <div className="flex-1">
                            <div className={`font-medium ${
                              verificationResult.status === 'PASS' ? 'text-green-800' : 'text-yellow-800'
                            }`}>
                              Drawing Tree Verification: {verificationResult.status}
                            </div>
                            <div className="text-sm text-muted-foreground mt-1">
                              DT assemblies: {verificationResult.summary.dt_count} |
                              MIUL assemblies: {verificationResult.summary.miul_count}
                            </div>
                            {verificationResult.status === 'FAIL' && (
                              <div className="mt-2 text-sm">
                                {verificationResult.summary.missing_count > 0 && (
                                  <div className="text-yellow-700">
                                    Missing from MIUL: {verificationResult.summary.missing_count} assemblies
                                    {verificationResult.missing_from_miul.length > 0 && (
                                      <span className="text-xs ml-1">
                                        ({verificationResult.missing_from_miul.slice(0, 5).join(', ')}
                                        {verificationResult.missing_from_miul.length > 5 && '...'})
                                      </span>
                                    )}
                                  </div>
                                )}
                                {verificationResult.summary.hierarchy_error_count > 0 && (
                                  <div className="text-yellow-700">
                                    Hierarchy mismatches: {verificationResult.summary.hierarchy_error_count}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Step 3: Enrich with MAPTIS Ratings */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-sm font-bold text-primary">3</span>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Enrich with MAPTIS Ratings</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Auto-populate NASA rating columns from MAPTIS test database:
                </p>
                <div className="grid grid-cols-3 gap-2 mb-4 text-xs">
                  {['FLAMM', 'CORR', 'SCC', 'TVS', 'TOX', 'FS'].map(r => (
                    <Badge key={r} variant="outline" className="text-xs">{r}</Badge>
                  ))}
                </div>
                <Button onClick={enrichWithRatings} disabled={!generatedFile || isEnriching} size="lg" variant="secondary" className="w-full">
                  {isEnriching ? <><Sparkles className="h-5 w-5 mr-2 animate-spin" />Enriching...</> : <><FileSpreadsheet className="h-5 w-5 mr-2" />Enrich with Ratings</>}
                </Button>
                {enrichedFile && !isEnriching && (
                  <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-md">
                    <div className="flex items-center text-sm text-green-800">
                      <CheckCircle2 className="h-4 w-4 mr-2" />Enriched MIUL downloaded! Ready for MUA generation.
                    </div>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Step 4: Generate MUAs */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-sm font-bold text-primary">4</span>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Generate Material Usage Agreements</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Auto-generate MUA documents for materials with rating gaps per NASA-STD-6016.
                </p>

                <Button onClick={generateMUAs} disabled={!enrichedFile || isGeneratingMUAs} size="lg" className="w-full">
                  {isGeneratingMUAs ? <><Sparkles className="h-5 w-5 mr-2 animate-spin" />Generating...</> : <><FileCheck className="h-5 w-5 mr-2" />Generate MUAs</>}
                </Button>

                {isGeneratingMUAs && (
                  <div className="mt-3">
                    <Progress value={muaProgress} className="h-2" />
                    <p className="text-xs text-muted-foreground mt-2">Analyzing materials...</p>
                  </div>
                )}

                {muaResults && !isGeneratingMUAs && (
                  <div className="mt-3 space-y-3">
                    <div className="p-3 bg-green-50 border border-green-200 rounded-md">
                      <div className="flex items-center text-sm text-green-800">
                        <CheckCircle2 className="h-4 w-4 mr-2" />
                        Generated {muaResults.muas_generated} MUAs from {muaResults.materials_processed} materials!
                      </div>
                    </div>
                    <Button onClick={downloadMUAExcel} variant="secondary" size="sm" className="w-full">
                      <Download className="h-4 w-4 mr-2" />Download Excel (Summary + Drafts)
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Info Card */}
        <Card className="bg-primary/5 border-primary/20">
          <CardContent className="pt-6">
            <h4 className="font-medium mb-2">Complete End-to-End Workflow</h4>
            <ol className="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
              <li>Upload engineering drawing PDFs containing parts lists</li>
              <li>System extracts parts, materials, and assembly hierarchy</li>
              <li>Base MIUL is generated with proper Parent/Child relationships</li>
              <li>Material ratings populated from MAPTIS (181,752 records)</li>
              <li>MUAs auto-generated for materials with rating gaps</li>
              <li>Download complete package ready for NASA compliance review</li>
            </ol>
            <div className="mt-4 p-3 bg-white rounded-md border">
              <p className="text-xs font-medium">Time Savings:</p>
              <p className="text-xs text-muted-foreground">Traditional: 2-4 months per material → MIRA: ~10 seconds for 5 materials</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
