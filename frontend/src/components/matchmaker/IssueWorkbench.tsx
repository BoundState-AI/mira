import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { IssueQuestionResponse, MatchmakerSession } from '@/lib/matchmaker-api';

interface IssueWorkbenchProps {
  session: MatchmakerSession | null;
  selectedIssue: string | null;
  issueQuestion: IssueQuestionResponse | null;
  loadingQuestion: boolean;
  answering: boolean;
  matching: boolean;
  onSelectIssue: (issue: string) => void;
  onSubmitAnswer: (issue: string, payload: {
    question_id?: string;
    answer?: unknown;
    answers?: Record<string, unknown>;
    selected_code?: string;
  }) => Promise<void>;
  onRunMatch: (issue: string) => Promise<void>;
}

type DisplayIssueStatus = 'pending' | 'in_progress' | 'done' | 'manual_required';

interface DisplayIssue {
  issue: string;
  label: string;
  status: DisplayIssueStatus;
  outOfScope?: boolean;
  requirementRef?: string | null;
}

const ISSUE_LABELS: Record<string, string> = {
  FLAM: 'Flammability',
  TOX: 'Toxicity / Offgassing',
  O2: 'O2 Compatibility',
  HEE: 'H2 Compatibility',
  SCC: 'Stress Corrosion Cracking',
  CORR: 'Corrosion',
  TVS: 'Thermal Vacuum Stability',
  FLUID: 'FC (Fluid Compatibility)',
  FC: 'FC (Fluid Compatibility)',
  FRACTURE_CRITICAL: 'Fracture Critical (Manual)',
};

function statusColor(status: string): string {
  if (status === 'done') return 'bg-emerald-100 text-emerald-700';
  if (status === 'manual_required') return 'bg-amber-100 text-amber-800';
  if (status === 'in_progress') return 'bg-blue-100 text-blue-700';
  return 'bg-slate-100 text-slate-700';
}

function statusLabel(status: DisplayIssueStatus): string {
  return status;
}

function issueLabel(issue: string): string {
  return ISSUE_LABELS[issue] || issue;
}

export default function IssueWorkbench({
  session,
  selectedIssue,
  issueQuestion,
  loadingQuestion,
  answering,
  matching,
  onSelectIssue,
  onSubmitAnswer,
  onRunMatch,
}: IssueWorkbenchProps) {
  const [answerValue, setAnswerValue] = useState('');
  const [answerValueB, setAnswerValueB] = useState('');
  const [selectedCode, setSelectedCode] = useState('');

  const issues = useMemo<DisplayIssue[]>(() => {
    if (!session) return [];

    const ordered = Object.values(session.issues || {}).map((issue) => ({
      issue: issue.issue,
      label: issueLabel(issue.issue),
      status: issue.status as DisplayIssueStatus,
      outOfScope: issue.out_of_scope,
      requirementRef: issue.requirement_ref,
    }));

    const order = ['FLAM', 'CORR', 'SCC', 'TVS', 'TOX', 'O2', 'HEE', 'FLUID', 'FRACTURE_CRITICAL'];
    return ordered.sort((a, b) => {
      const ai = order.indexOf(a.issue);
      const bi = order.indexOf(b.issue);
      const av = ai === -1 ? 999 : ai;
      const bv = bi === -1 ? 999 : bi;
      if (av !== bv) return av - bv;
      return a.label.localeCompare(b.label);
    });
  }, [session]);

  const question = issueQuestion?.next_question as Record<string, unknown> | null;
  const questionType = (question?.type as string) || '';
  const questionId = (question?.id as string) || '';

  const submitAnswer = async () => {
    if (!selectedIssue || !questionId) return;

    if (questionType === 'numeric_pair') {
      const fields = ((question?.fields as string[]) || []);
      const payload: Record<string, unknown> = {};
      if (fields[0]) payload[fields[0]] = Number(answerValue);
      if (fields[1]) payload[fields[1]] = Number(answerValueB);
      await onSubmitAnswer(selectedIssue, {
        question_id: questionId,
        answer: payload,
      });
      setAnswerValue('');
      setAnswerValueB('');
      return;
    }

    await onSubmitAnswer(selectedIssue, {
      question_id: questionId,
      answer: answerValue,
      selected_code: selectedCode || undefined,
    });
    setAnswerValue('');
  };

  const submitSelectedCode = async () => {
    if (!selectedIssue || !selectedCode) return;
    await onSubmitAnswer(selectedIssue, { selected_code: selectedCode });
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Issues</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {issues.map((issue) => (
            <button
              key={issue.issue}
              className={`flex w-full items-start justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm ${
                selectedIssue === issue.issue ? 'border-primary bg-primary/5' : ''
              }`}
              onClick={() => onSelectIssue(issue.issue)}
              type="button"
            >
              <span className="flex flex-col items-start gap-0.5">
                <span className="font-medium">{issue.label}</span>
                {issue.outOfScope && (
                  <span className="text-xs text-muted-foreground">
                    Manual review required{issue.requirementRef ? ` (${issue.requirementRef})` : ''}
                  </span>
                )}
              </span>
              <Badge className={statusColor(issue.status)}>{statusLabel(issue.status)}</Badge>
            </button>
          ))}
          {!issues.length && <div className="text-sm text-muted-foreground">No issues detected yet.</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Issue Workbench</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!selectedIssue && <div className="text-sm text-muted-foreground">Select an issue.</div>}
          {selectedIssue && issueQuestion?.manual_required && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              {issueQuestion.manual_message}
            </div>
          )}
          {selectedIssue && !issueQuestion?.manual_required && (
            <>
              <div className="flex items-center gap-2">
                <Badge className={statusColor(issueQuestion?.status || 'pending')}>
                  {issueQuestion?.status || 'pending'}
                </Badge>
                {issueQuestion?.outcome && (
                  <Badge variant="outline">{issueQuestion.outcome}</Badge>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={matching}
                  onClick={() => selectedIssue && onRunMatch(selectedIssue)}
                >
                  {matching ? 'Matching...' : 'Run Match'}
                </Button>
              </div>

              {issueQuestion?.candidate_codes?.length > 1 && (
                <div className="space-y-2">
                  <Label>Select Cat III Code</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={selectedCode}
                    onChange={(e) => setSelectedCode(e.target.value)}
                  >
                    <option value="">Select code...</option>
                    {issueQuestion.candidate_codes.map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                  <Button type="button" onClick={submitSelectedCode} disabled={!selectedCode || answering}>
                    Confirm Code
                  </Button>
                </div>
              )}

              {question && (
                <div className="space-y-2 rounded-md border p-3">
                  <div className="text-sm font-medium">{String(question.text || '')}</div>
                  {questionType === 'yes_no' && (
                    <select
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={answerValue}
                      onChange={(e) => setAnswerValue(e.target.value)}
                    >
                      <option value="">Select...</option>
                      <option value="Yes">Yes</option>
                      <option value="No">No</option>
                    </select>
                  )}
                  {questionType === 'select' && (
                    <select
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={answerValue}
                      onChange={(e) => setAnswerValue(e.target.value)}
                    >
                      <option value="">Select...</option>
                      {((question.options as string[]) || []).map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  )}
                  {questionType === 'numeric_pair' && (
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        type="number"
                        placeholder={String(((question.fields as string[]) || [])[0] || 'value_a')}
                        value={answerValue}
                        onChange={(e) => setAnswerValue(e.target.value)}
                      />
                      <Input
                        type="number"
                        placeholder={String(((question.fields as string[]) || [])[1] || 'value_b')}
                        value={answerValueB}
                        onChange={(e) => setAnswerValueB(e.target.value)}
                      />
                    </div>
                  )}
                  {(questionType === 'free_text' || questionType === 'numeric') && (
                    <Textarea
                      value={answerValue}
                      onChange={(e) => setAnswerValue(e.target.value)}
                      placeholder="Enter response"
                    />
                  )}
                  <Button type="button" onClick={submitAnswer} disabled={answering || loadingQuestion}>
                    {answering ? 'Saving...' : 'Submit Answer'}
                  </Button>
                </div>
              )}

              {!question && (
                <div className="text-sm text-muted-foreground">
                  No pending question for this issue.
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
