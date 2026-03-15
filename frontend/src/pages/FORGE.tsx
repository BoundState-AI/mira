import { useState } from "react";
import { Database, FolderTree, Loader2, Network, ScrollText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  forgeCompile,
  type ForgeCompileJobResponse,
  type ForgeCompileRequest,
  type ForgeCompileResponse,
} from "@/lib/api";

const EXAMPLE_SQLITE_URL = "sqlite:////tmp/forge_demo.sqlite";

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export default function FORGE() {
  const [databaseUrl, setDatabaseUrl] = useState(EXAMPLE_SQLITE_URL);
  const [appName, setAppName] = useState("FORGE Generated App");
  const [outputDir, setOutputDir] = useState("");
  const [sampleRows, setSampleRows] = useState("50");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compileJob, setCompileJob] = useState<ForgeCompileJobResponse | null>(null);
  const [result, setResult] = useState<ForgeCompileResponse | null>(null);

  const runCompile = async () => {
    if (!databaseUrl.trim()) {
      setError("Database URL is required.");
      return;
    }

    const parsedSampleRows = Number(sampleRows);
    if (!Number.isFinite(parsedSampleRows) || parsedSampleRows < 5 || parsedSampleRows > 500) {
      setError("Sample rows must be a number between 5 and 500.");
      return;
    }

    setLoading(true);
    setError(null);
    setCompileJob(null);
    setResult(null);

    try {
      const payload: ForgeCompileRequest = {
        database_url: databaseUrl.trim(),
        app_name: appName.trim() || "FORGE Generated App",
        sample_rows_per_table: parsedSampleRows,
        output_dir: outputDir.trim() || undefined,
        generate_bundle: true,
        require_llm_refinement: true,
      };
      const response = await forgeCompile(payload, {
        onProgress: setCompileJob,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "FORGE compile failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-border bg-card px-6 py-8 shadow-sm">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">
              BoundState FORGE
            </p>
            <h1 className="text-4xl font-serif font-bold tracking-tight">FORGE Build Console</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              Operator surface for compiling a database into FORGE artifacts, inspecting raw output,
              validating generated bundles, and debugging what the compiler produced. This is the
              build and diagnostics page, not the exploration workflow.
            </p>
          </div>
          <Badge variant="outline">Additive</Badge>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <div className="md:col-span-2">
            <label className="mb-2 block text-sm font-medium">Database URL</label>
            <Input
              value={databaseUrl}
              onChange={(event) => setDatabaseUrl(event.target.value)}
              placeholder="sqlite:////path/to/db.sqlite"
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium">Application Name</label>
            <Input
              value={appName}
              onChange={(event) => setAppName(event.target.value)}
              placeholder="FORGE Generated App"
            />
          </div>
        </div>

        <div className="mt-4">
          <label className="mb-2 block text-sm font-medium">Output Directory</label>
          <Input
            value={outputDir}
            onChange={(event) => setOutputDir(event.target.value)}
            placeholder="./forge_output/forge-generated-app"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div className="w-full max-w-48">
            <label className="mb-2 block text-sm font-medium">Sample Rows / Table</label>
            <Input
              value={sampleRows}
              onChange={(event) => setSampleRows(event.target.value)}
              inputMode="numeric"
            />
          </div>

          <Button onClick={runCompile} disabled={loading} className="min-w-40">
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Building
              </>
            ) : (
              <>
                <Database className="mr-2 h-4 w-4" />
                Build Artifacts
              </>
            )}
          </Button>
        </div>

        {compileJob && (
          <Card className="mt-4 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                  Compile Status
                </p>
                <p className="mt-1 text-sm font-medium">{compileJob.message}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Stage: <code>{compileJob.stage}</code>
                </p>
              </div>
              <Badge variant="outline">{Math.round(compileJob.progress)}%</Badge>
            </div>
          </Card>
        )}

        <div className="mt-4 rounded-2xl border border-dashed border-border bg-background/70 p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Current guardrail</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Remote database URLs are blocked by default. Local SQLite and localhost-backed
            SQLAlchemy URLs are allowed unless the backend explicitly enables remote access.
            Use the Explorer page when you want to inspect compiled questions and run BSMS queries.
          </p>
        </div>

        {error && (
          <Card className="mt-4 border-destructive/40 p-4">
            <p className="text-sm text-destructive">{error}</p>
          </Card>
        )}
      </section>

      {result && (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Database className="h-4 w-4" />
                <span className="text-sm">Tables</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{result.summary.table_count}</p>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <ScrollText className="h-4 w-4" />
                <span className="text-sm">Questions</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{result.summary.generated_question_count}</p>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Network className="h-4 w-4" />
                <span className="text-sm">Relationships</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{result.summary.relationship_count}</p>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Network className="h-4 w-4" />
                <span className="text-sm">Latent Joins</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{result.summary.latent_relationship_count}</p>
            </Card>
          </section>

          <Card className="p-4">
            <div className="flex flex-wrap gap-2">
              <Badge>{result.summary.dialect}</Badge>
              {result.summary.schemas.map((schema) => (
                <Badge key={schema} variant="outline">
                  {schema}
                </Badge>
              ))}
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              Compiled from <code>{result.summary.database_url_redacted}</code>
            </p>
            {result.output_dir && (
              <p className="mt-2 text-sm text-muted-foreground">
                Output written to <code>{result.output_dir}</code>
              </p>
            )}
            {result.warnings.length > 0 && (
              <div className="mt-3 space-y-1">
                {result.warnings.map((warning) => (
                  <p key={warning} className="text-sm text-amber-700">
                    {warning}
                  </p>
                ))}
              </div>
            )}
          </Card>

          <Tabs defaultValue="questions">
            <TabsList className="flex w-full flex-wrap justify-start gap-2">
              <TabsTrigger value="questions">Questions</TabsTrigger>
              <TabsTrigger value="capabilities">Capabilities</TabsTrigger>
              <TabsTrigger value="relationships">Relationships</TabsTrigger>
              <TabsTrigger value="semantics">Semantics</TabsTrigger>
              <TabsTrigger value="authority">Authority Pack</TabsTrigger>
              <TabsTrigger value="bundle">Generated Bundle</TabsTrigger>
            </TabsList>

            <TabsContent value="questions">
              <Card className="p-4">
                <Textarea readOnly className="min-h-[32rem] font-mono text-xs" value={prettyJson(result.question_map)} />
              </Card>
            </TabsContent>

            <TabsContent value="capabilities">
              <Card className="p-4">
                <Textarea readOnly className="min-h-[32rem] font-mono text-xs" value={prettyJson(result.capabilities)} />
              </Card>
            </TabsContent>

            <TabsContent value="relationships">
              <Card className="p-4">
                <Textarea
                  readOnly
                  className="min-h-[32rem] font-mono text-xs"
                  value={prettyJson({
                    relationship_graph: result.relationship_graph,
                    latent_relationships: result.latent_relationships,
                  })}
                />
              </Card>
            </TabsContent>

            <TabsContent value="semantics">
              <Card className="p-4">
                <Textarea readOnly className="min-h-[32rem] font-mono text-xs" value={prettyJson(result.semantic_map)} />
              </Card>
            </TabsContent>

            <TabsContent value="authority">
              <Card className="p-4">
                <Textarea
                  readOnly
                  className="min-h-[32rem] font-mono text-xs"
                  value={prettyJson({
                    authority_pack: result.authority_pack,
                    bsms_pipeline: result.bsms_pipeline,
                    lineage_schema: result.lineage_schema,
                  })}
                />
              </Card>
            </TabsContent>

            <TabsContent value="bundle">
              <div className="space-y-4">
                <Card className="p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <FolderTree className="h-4 w-4" />
                    <h2 className="font-semibold">Generated Bundle</h2>
                  </div>

                  {result.generated_bundle ? (
                    <div className="space-y-3 text-sm">
                      <p>
                        <strong>Root:</strong> <code>{result.generated_bundle.root_dir}</code>
                      </p>
                      <p>
                        <strong>Backend:</strong> <code>{result.generated_bundle.backend_dir}</code>
                      </p>
                      <p>
                        <strong>Frontend:</strong> <code>{result.generated_bundle.frontend_dir}</code>
                      </p>
                      <p>
                        <strong>Authority Pack:</strong> <code>{result.generated_bundle.authority_pack_dir}</code>
                      </p>
                      <p>
                        <strong>BSMS Pipeline:</strong> <code>{result.generated_bundle.bsms_pipeline_dir}</code>
                      </p>
                      <p>
                        <strong>Files:</strong> {result.generated_bundle.files.length}
                      </p>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No generated bundle metadata was returned.
                    </p>
                  )}
                </Card>

                <Card className="p-4">
                  <Textarea
                    readOnly
                    className="min-h-[32rem] font-mono text-xs"
                    value={prettyJson(result.generated_bundle ?? { files: [] })}
                  />
                </Card>
              </div>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
