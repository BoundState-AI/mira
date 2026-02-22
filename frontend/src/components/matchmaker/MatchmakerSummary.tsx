import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ExportResponse, MatchmakerSession } from '@/lib/matchmaker-api';

interface MatchmakerSummaryProps {
  session: MatchmakerSession | null;
  exporting: boolean;
  exportResult: ExportResponse | null;
  onExport: (mode: 'draft' | 'board_ready') => Promise<void>;
}

export default function MatchmakerSummary({
  session,
  exporting,
  exportResult,
  onExport,
}: MatchmakerSummaryProps) {
  const issues = Object.values(session?.issues || {});
  const done = issues.filter((i) => i.status === 'done').length;
  const manual = issues.filter((i) => i.status === 'manual_required').length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Summary</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!session && <div className="text-sm text-muted-foreground">Create or resume a session.</div>}
        {session && (
          <>
            <div className="text-sm">
              <div><strong>Material:</strong> {session.material_resolution.resolved_name || session.material_input}</div>
              <div><strong>Rule Pack:</strong> {session.rule_pack_version}</div>
              <div className="mt-2 flex gap-2">
                <Badge variant="outline">{done} done</Badge>
                <Badge variant="outline">{issues.length - done} open</Badge>
                <Badge className="bg-amber-100 text-amber-800">{manual} manual</Badge>
                {session.category && <Badge className="bg-blue-100 text-blue-700">Category {session.category}</Badge>}
              </div>
            </div>
            {!!session.banners.length && (
              <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
                {session.banners.map((banner, idx) => (
                  <div key={`${idx}-${banner.slice(0, 20)}`}>- {banner}</div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onExport('draft')} disabled={exporting}>
                {exporting ? 'Exporting...' : 'Export Draft'}
              </Button>
              <Button type="button" onClick={() => onExport('board_ready')} disabled={exporting}>
                {exporting ? 'Exporting...' : 'Export Board Ready'}
              </Button>
            </div>
          </>
        )}

        {exportResult && (
          <div className="space-y-2 rounded-md border p-3 text-sm">
            <div><strong>Mode:</strong> {exportResult.mode}</div>
            <div>
              <strong>Ready:</strong> {exportResult.export_ready ? 'Yes' : 'No'}
            </div>
            {!!exportResult.blockers?.length && (
              <div>
                <strong>Blockers:</strong>
                {exportResult.blockers.map((b, idx) => (
                  <div key={idx} className="text-xs text-muted-foreground">
                    {String(b.issue || 'session')}: {String(b.reason || '')}
                  </div>
                ))}
              </div>
            )}
            {!!exportResult.missing_fields?.length && (
              <div>
                <strong>Missing:</strong>
                {exportResult.missing_fields.map((m, idx) => (
                  <div key={idx} className="text-xs text-muted-foreground">
                    {String(m.field || '')}: {String(m.reason || '')}
                  </div>
                ))}
              </div>
            )}
            {exportResult.form_text && (
              <pre className="max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                {exportResult.form_text}
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

