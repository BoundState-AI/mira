/**
 * PathInspectorPanel — Shows upstream contributors, local triggers,
 * downstream propagation risk, and controls for a selected component.
 *
 * BS-SPEC-OCA-002-REV0 §7.2
 */

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { X, ArrowUp, Target, ArrowDown, Wrench } from 'lucide-react';
import type { PathInspectorResult } from '@/lib/oca-system-api';

interface PathInspectorPanelProps {
  result: PathInspectorResult | null;
  onClose: () => void;
}

export default function PathInspectorPanel({ result, onClose }: PathInspectorPanelProps) {
  if (!result) return null;

  return (
    <Card className="w-72 flex-shrink-0">
      <CardHeader className="py-2 px-3 flex-row items-center justify-between">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Path Inspector
        </CardTitle>
        <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[calc(100vh-320px)]">
          <div className="space-y-3 p-3">
            {/* Upstream Contributors */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <ArrowUp className="h-3 w-3 text-blue-400" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Upstream Contributors
                </span>
              </div>
              {result.upstream_contributors.length > 0 ? (
                <div className="space-y-1">
                  {result.upstream_contributors.map((uc, i) => (
                    <div key={i} className="text-[10px] border-l-2 border-blue-500/30 pl-2 py-0.5">
                      <div className="font-medium">{uc.label}</div>
                      <div className="text-muted-foreground">{uc.contributions}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground">No upstream components</div>
              )}
            </div>

            {/* Local Triggers */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Target className="h-3 w-3 text-red-400" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Local Mechanism Triggers
                </span>
              </div>
              {result.local_mechanism_triggers.length > 0 ? (
                <div className="space-y-1">
                  {result.local_mechanism_triggers.map((mt, i) => (
                    <div key={i} className="text-[10px] border-l-2 border-red-500/30 pl-2 py-0.5">
                      <div className="flex items-center gap-1">
                        <Badge variant="outline" className="text-[8px] px-1 py-0 font-mono">
                          {mt.abbreviation}
                        </Badge>
                        <span className="capitalize">{mt.mechanism.replace(/_/g, ' ')}</span>
                        <Badge
                          className={`text-[7px] px-1 py-0 ${
                            mt.status === 'credible' ? 'bg-red-600 text-white' : 'bg-amber-500 text-black'
                          }`}
                        >
                          {mt.rating}/4
                        </Badge>
                      </div>
                      <div className="text-muted-foreground">{mt.observed_elements}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground">No credible mechanisms</div>
              )}
            </div>

            {/* Downstream Propagation */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <ArrowDown className="h-3 w-3 text-orange-400" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Downstream Propagation
                </span>
              </div>
              {result.downstream_propagation_risk.length > 0 ? (
                <div className="space-y-0.5">
                  {result.downstream_propagation_risk.map((risk, i) => (
                    <div key={i} className="text-[10px] text-muted-foreground border-l-2 border-orange-500/30 pl-2">
                      {risk}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground">No downstream components</div>
              )}
            </div>

            {/* Controls */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Wrench className="h-3 w-3 text-emerald-400" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Controls That Would Change Result
                </span>
              </div>
              {result.controls_that_would_change.length > 0 ? (
                <div className="space-y-1.5">
                  {result.controls_that_would_change.map((ctrl, i) => (
                    <div key={i} className="text-[10px] border-l-2 border-emerald-500/30 pl-2 py-0.5">
                      <div className="font-medium">{ctrl.action}</div>
                      <div className="text-muted-foreground">{ctrl.expected_effect}</div>
                      <Badge variant="outline" className="text-[7px] px-1 py-0 mt-0.5 font-mono">
                        {ctrl.mechanism}
                      </Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground">No control actions available</div>
              )}
            </div>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
