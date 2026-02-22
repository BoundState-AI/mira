import { useEffect, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import type { IssueState } from '@/lib/matchmaker-api';

interface RationaleSuggesterProps {
  issue: IssueState | null;
  saving: boolean;
  onSave: (payload: {
    rationale?: string;
    selected_phrases?: string[];
    manual_disposition?: string;
  }) => Promise<void>;
}

export default function RationaleSuggester({ issue, saving, onSave }: RationaleSuggesterProps) {
  const [manualText, setManualText] = useState('');
  const [rationale, setRationale] = useState('');
  const [selectedPhrases, setSelectedPhrases] = useState<string[]>([]);

  useEffect(() => {
    setManualText(issue?.manual_disposition || '');
    setRationale(issue?.rationale || '');
    setSelectedPhrases([]);
  }, [issue?.issue, issue?.manual_disposition, issue?.rationale]);

  const phraseList = issue?.phrases || [];
  const conflictList = issue?.conflicts || [];

  const selectedPhraseSet = useMemo(() => new Set(selectedPhrases), [selectedPhrases]);

  if (!issue) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Rationale</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">Select an issue.</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rationale - {issue.issue}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {issue.out_of_scope ? (
          <div className="space-y-2">
            <Badge className="bg-amber-100 text-amber-800">Manual Required</Badge>
            <Textarea
              placeholder="Enter manual disposition for this out-of-scope issue"
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
            />
            <Button
              type="button"
              onClick={() => onSave({ manual_disposition: manualText })}
              disabled={saving || !manualText.trim()}
            >
              {saving ? 'Saving...' : 'Save Manual Disposition'}
            </Button>
          </div>
        ) : (
          <>
            {!!conflictList.length && (
              <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3">
                <div className="text-sm font-semibold text-amber-900">Conflicting precedents found</div>
                {conflictList.slice(0, 3).map((conflict, idx) => (
                  <div key={`${conflict.approved.mua_number}-${conflict.negative.mua_number}-${idx}`} className="text-xs text-amber-900">
                    APPROVED {conflict.approved.mua_number} vs {conflict.negative.determination.toUpperCase()} {conflict.negative.mua_number}
                    <div>{conflict.overlap_description}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-2">
              <div className="text-sm font-medium">Suggested phrases</div>
              {!phraseList.length && (
                <div className="text-xs text-muted-foreground">Run matching to extract rationale phrases.</div>
              )}
              {phraseList.map((phrase) => {
                const checked = selectedPhraseSet.has(phrase.phrase);
                return (
                  <label key={`${phrase.mua_number}-${phrase.phrase.slice(0, 24)}`} className="flex items-start gap-2 rounded-md border p-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedPhrases([...selectedPhrases, phrase.phrase]);
                        } else {
                          setSelectedPhrases(selectedPhrases.filter((item) => item !== phrase.phrase));
                        }
                      }}
                    />
                    <span>
                      {phrase.phrase}
                      <span className="ml-2 text-xs text-muted-foreground">- {phrase.mua_number}</span>
                    </span>
                  </label>
                );
              })}
            </div>

            <Textarea
              placeholder="Write or refine rationale"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
            <Button
              type="button"
              onClick={() => onSave({ rationale, selected_phrases: selectedPhrases })}
              disabled={saving || (!rationale.trim() && selectedPhrases.length === 0)}
            >
              {saving ? 'Saving...' : 'Save Rationale'}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
