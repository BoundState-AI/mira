import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import MaterialInput from '@/components/matchmaker/MaterialInput';
import IssueWorkbench from '@/components/matchmaker/IssueWorkbench';
import RationaleSuggester from '@/components/matchmaker/RationaleSuggester';
import MatchmakerSummary from '@/components/matchmaker/MatchmakerSummary';
import {
  createSession,
  deleteSession,
  exportSession,
  getIssueQuestions,
  getSession,
  importMiul,
  listSessions,
  runIssueMatch,
  saveIssueRationale,
  submitIssueAnswer,
  type ExportResponse,
  type IssueQuestionResponse,
  type MatchmakerSession,
  type SessionSummary,
} from '@/lib/matchmaker-api';

export default function MUAMatchmaker() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<MatchmakerSession | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null);
  const [issueQuestion, setIssueQuestion] = useState<IssueQuestionResponse | null>(null);
  const [exportResult, setExportResult] = useState<ExportResponse | null>(null);

  const [loadingSessions, setLoadingSessions] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [loadingQuestion, setLoadingQuestion] = useState(false);
  const [answering, setAnswering] = useState(false);
  const [matching, setMatching] = useState(false);
  const [savingRationale, setSavingRationale] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedIssueState = useMemo(() => {
    if (!session || !selectedIssue) return null;
    return session.issues[selectedIssue] || null;
  }, [session, selectedIssue]);

  useEffect(() => {
    refreshSessions();
  }, []);

  const refreshSessions = async () => {
    setLoadingSessions(true);
    try {
      const response = await listSessions();
      setSessions(response.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to list sessions');
    } finally {
      setLoadingSessions(false);
    }
  };

  const loadSession = async (sessionId: string) => {
    try {
      const loaded = await getSession(sessionId);
      setSession(loaded);
      const firstIssue = Object.keys(loaded.issues)[0] || null;
      setSelectedIssue(firstIssue);
      setExportResult(null);
      if (firstIssue) {
        await loadIssueQuestion(loaded.session_id, firstIssue);
      } else {
        setIssueQuestion(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load session');
    }
  };

  const loadIssueQuestion = async (sessionId: string, issue: string) => {
    setLoadingQuestion(true);
    try {
      const response = await getIssueQuestions(sessionId, issue);
      setIssueQuestion(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load issue question');
    } finally {
      setLoadingQuestion(false);
    }
  };

  const handleCreate = async (payload: Parameters<typeof createSession>[0]) => {
    setCreating(true);
    setError(null);
    try {
      const created = await createSession(payload);
      setSession(created);
      await refreshSessions();
      const firstIssue = Object.keys(created.issues)[0] || null;
      setSelectedIssue(firstIssue);
      setExportResult(null);
      if (firstIssue) {
        await loadIssueQuestion(created.session_id, firstIssue);
      } else {
        setIssueQuestion(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create session');
    } finally {
      setCreating(false);
    }
  };

  const handleImportMiul = async (file: File) => {
    setImporting(true);
    setError(null);
    try {
      const response = await importMiul(file);
      await refreshSessions();
      if (response.created_sessions.length > 0) {
        await loadSession(response.created_sessions[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import MIUL');
    } finally {
      setImporting(false);
    }
  };

  const handleSelectIssue = async (issue: string) => {
    if (!session) return;
    setSelectedIssue(issue);
    await loadIssueQuestion(session.session_id, issue);
  };

  const refreshCurrentSession = async () => {
    if (!session) return;
    const loaded = await getSession(session.session_id);
    setSession(loaded);
    if (selectedIssue) {
      await loadIssueQuestion(loaded.session_id, selectedIssue);
    }
  };

  const handleSubmitAnswer = async (
    issue: string,
    payload: {
      question_id?: string;
      answer?: unknown;
      answers?: Record<string, unknown>;
      selected_code?: string;
    },
  ) => {
    if (!session) return;
    setAnswering(true);
    setError(null);
    try {
      const response = await submitIssueAnswer(session.session_id, issue, payload);
      setIssueQuestion(response);
      await refreshCurrentSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setAnswering(false);
    }
  };

  const handleRunMatch = async (issue: string) => {
    if (!session) return;
    setMatching(true);
    setError(null);
    try {
      await runIssueMatch(session.session_id, issue);
      await refreshCurrentSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run match');
    } finally {
      setMatching(false);
    }
  };

  const handleSaveRationale = async (payload: {
    rationale?: string;
    selected_phrases?: string[];
    manual_disposition?: string;
  }) => {
    if (!session || !selectedIssue) return;
    setSavingRationale(true);
    setError(null);
    try {
      await saveIssueRationale(session.session_id, selectedIssue, payload);
      await refreshCurrentSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save rationale');
    } finally {
      setSavingRationale(false);
    }
  };

  const handleExport = async (mode: 'draft' | 'board_ready') => {
    if (!session) return;
    setExporting(true);
    setError(null);
    try {
      const result = await exportSession(session.session_id, mode);
      setExportResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export');
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      if (session?.session_id === sessionId) {
        setSession(null);
        setSelectedIssue(null);
        setIssueQuestion(null);
        setExportResult(null);
      }
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete session');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">MUA V8 Matchmaker</h1>
          <p className="text-sm text-muted-foreground">
            Issue-by-issue evidence matching with rule-pack driven Appendix E routing.
          </p>
        </div>
      </div>

      {error && (
        <Card className="border-red-300 bg-red-50">
          <CardContent className="py-3 text-sm text-red-800">{error}</CardContent>
        </Card>
      )}

      <div className="space-y-4">
        <MaterialInput
          session={session}
          creating={creating}
          importing={importing}
          onCreate={handleCreate}
          onImportMiul={handleImportMiul}
        />

        <IssueWorkbench
          session={session}
          selectedIssue={selectedIssue}
          issueQuestion={issueQuestion}
          loadingQuestion={loadingQuestion}
          answering={answering}
          matching={matching}
          onSelectIssue={handleSelectIssue}
          onSubmitAnswer={handleSubmitAnswer}
          onRunMatch={handleRunMatch}
        />

        <RationaleSuggester
          issue={selectedIssueState}
          saving={savingRationale}
          onSave={handleSaveRationale}
        />

        <MatchmakerSummary
          session={session}
          exporting={exporting}
          exportResult={exportResult}
          onExport={handleExport}
        />

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Sessions</CardTitle>
            <Button type="button" variant="outline" size="sm" onClick={refreshSessions} disabled={loadingSessions}>
              {loadingSessions ? 'Refreshing...' : 'Refresh'}
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {sessions.map((item) => (
              <div key={item.session_id} className="rounded-md border p-2">
                <div className="text-sm font-medium">{item.material_input}</div>
                <div className="text-xs text-muted-foreground">
                  {item.done_count}/{item.issue_count} done | manual {item.manual_count}
                </div>
                <div className="mt-2 flex gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => loadSession(item.session_id)}>
                    Open
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => handleDelete(item.session_id)}>
                    Delete
                  </Button>
                </div>
              </div>
            ))}
            {!sessions.length && <div className="text-sm text-muted-foreground">No sessions yet.</div>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
