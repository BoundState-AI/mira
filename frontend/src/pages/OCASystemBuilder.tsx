/**
 * OCASystemBuilder — Visual System Builder for OCA Phase 2.
 * React Flow canvas with drag-drop component palette, live assessment,
 * topology zones, kindling chain visualization, and path inspector.
 *
 * BS-SPEC-OCA-002-REV0
 *
 * BoundState AI 2026
 * Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
  ReactFlow, addEdge, useNodesState, useEdgesState,
  Controls, MiniMap, Background, BackgroundVariant,
  type Connection, type Edge, type Node, type OnConnect,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Loader2, AlertTriangle, XCircle, Shield, Flame, Download, Zap, Info,
  ChevronRight, LayoutGrid,
} from 'lucide-react';

import ComponentNode, { type ComponentNodeData } from '@/components/oca-system/ComponentNode';
import ComponentPalette from '@/components/oca-system/ComponentPalette';
import SystemInputBar from '@/components/oca-system/SystemInputBar';
import PathInspectorPanel from '@/components/oca-system/PathInspectorPanel';

import {
  ocaCreateSystem, ocaAddComponent, ocaAddConnection,
  ocaRemoveComponent, ocaRemoveConnection,
  ocaAssessSystem, ocaGetPathInspector, ocaExportSystem,
  type SystemInputs, type SystemComponent, type SystemAssessmentResult,
  type PathInspectorResult, type ComponentArchetype, type SystemKindlingChain,
  ZONE_COLORS, ZONE_LABELS,
} from '@/lib/oca-system-api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DISPOSITION_LABELS: Record<string, { label: string; color: string }> = {
  compatible_as_configured: { label: 'Compatible As Configured', color: 'bg-emerald-600 text-white' },
  compatible_with_controls: { label: 'Compatible With Controls', color: 'bg-amber-500 text-black' },
  requires_mua: { label: 'Requires MUA', color: 'bg-orange-600 text-white' },
  requires_acceptance_test: { label: 'Requires Acceptance Test', color: 'bg-orange-600 text-white' },
  requires_supplemental_testing: { label: 'Requires Supplemental Testing', color: 'bg-red-600 text-white' },
  insufficient_evidence: { label: 'Insufficient Evidence', color: 'bg-red-800 text-white' },
};

const REACTION_LABELS: Record<string, string> = {
  A: 'A — Negligible', B: 'B — Marginal', C: 'C — Critical', D: 'D — Catastrophic',
};
const REACTION_COLORS: Record<string, string> = {
  A: 'bg-emerald-600 text-white', B: 'bg-amber-500 text-black',
  C: 'bg-orange-600 text-white', D: 'bg-red-700 text-white',
};

const nodeTypes = { component: ComponentNode };

// Default system inputs
const DEFAULT_INPUTS: SystemInputs = {
  o2_fraction: 1.0,
  system_pressure_min_psia: 14.7,
  system_pressure_max_psia: 3000,
  phase: 'gox',
  oxygen_phase: 'gas',
  temp_min_c: null,
  temp_max_c: null,
  design_flow_rate_m3_s: null,
  cleanliness_spec: null,
  mission_phase: 'ground_test',
  project_name: '',
  hardware_name: '',
  reviewer_name: '',
  bi_directional_flow_risk: false,
};

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function OCASystemBuilder() {
  // System state
  const [systemId, setSystemId] = useState<string | null>(null);
  const [inputs, setInputs] = useState<SystemInputs>(DEFAULT_INPUTS);
  const [assessment, setAssessment] = useState<SystemAssessmentResult | null>(null);
  const [pathResult, setPathResult] = useState<PathInspectorResult | null>(null);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showKindling, setShowKindling] = useState(false);
  const [activeTab, setActiveTab] = useState('canvas');

  // React Flow
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);

  // Component ID → server component map
  const componentMap = useRef<Map<string, SystemComponent>>(new Map());
  // Node ID → server component ID
  const nodeToComponentId = useRef<Map<string, string>>(new Map());
  // Edge ID → server connection ID
  const edgeToConnectionId = useRef<Map<string, string>>(new Map());

  // ---------------------------------------------------------------------------
  // Initialize system on mount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    async function init() {
      try {
        const res = await ocaCreateSystem('New O2 System', inputs);
        setSystemId(res.system_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create system');
      }
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------------------
  // Update inputs
  // ---------------------------------------------------------------------------
  const handleInputChange = useCallback((updates: Partial<SystemInputs>) => {
    setInputs(prev => ({ ...prev, ...updates }));
  }, []);

  // ---------------------------------------------------------------------------
  // Handle drop from palette
  // ---------------------------------------------------------------------------
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(async (event: React.DragEvent) => {
    event.preventDefault();

    const archetype = event.dataTransfer.getData('application/oca-archetype') as ComponentArchetype;
    const label = event.dataTransfer.getData('application/oca-label');

    if (!archetype || !systemId || !rfInstance) return;

    const position = rfInstance.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });

    try {
      const res = await ocaAddComponent(
        systemId, archetype, label, position.x, position.y,
      );

      const serverComp: SystemComponent = {
        component_id: res.component_id,
        archetype,
        label: label || archetype,
        position_x: position.x,
        position_y: position.y,
        materials: [],
        config: {},
        features: res.features,
        inferred_facts: res.inferred_facts,
        zones: res.zones,
        mechanism_assessments: [],
        overall_status: 'pending',
        highest_rating: 0,
        credible_mechanisms: [],
        connected: false,
      };

      componentMap.current.set(res.component_id, serverComp);

      const nodeId = `node-${res.component_id}`;
      nodeToComponentId.current.set(nodeId, res.component_id);

      const newNode: Node = {
        id: nodeId,
        type: 'component',
        position: { x: position.x, y: position.y },
        data: {
          component: serverComp,
          onInspect: handleInspect,
        } as ComponentNodeData,
      };

      setNodes(nds => [...nds, newNode]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add component');
    }
  }, [systemId, rfInstance, setNodes]);

  // ---------------------------------------------------------------------------
  // Handle connections
  // ---------------------------------------------------------------------------
  const onConnect: OnConnect = useCallback(async (connection: Connection) => {
    if (!systemId || !connection.source || !connection.target) return;

    const sourceCompId = nodeToComponentId.current.get(connection.source);
    const targetCompId = nodeToComponentId.current.get(connection.target);

    if (!sourceCompId || !targetCompId) return;

    try {
      const res = await ocaAddConnection(systemId, sourceCompId, targetCompId);

      const edgeId = `edge-${res.connection_id}`;
      edgeToConnectionId.current.set(edgeId, res.connection_id);

      setEdges(eds => addEdge({
        ...connection,
        id: edgeId,
        animated: true,
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      }, eds));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect');
    }
  }, [systemId, setEdges]);

  // ---------------------------------------------------------------------------
  // Handle node deletion
  // ---------------------------------------------------------------------------
  const onNodesDelete = useCallback(async (deletedNodes: Node[]) => {
    if (!systemId) return;
    for (const node of deletedNodes) {
      const compId = nodeToComponentId.current.get(node.id);
      if (compId) {
        try {
          await ocaRemoveComponent(systemId, compId);
          componentMap.current.delete(compId);
          nodeToComponentId.current.delete(node.id);
        } catch {
          // ignore
        }
      }
    }
  }, [systemId]);

  // ---------------------------------------------------------------------------
  // Handle edge deletion
  // ---------------------------------------------------------------------------
  const onEdgesDelete = useCallback(async (deletedEdges: Edge[]) => {
    if (!systemId) return;
    for (const edge of deletedEdges) {
      const connId = edgeToConnectionId.current.get(edge.id);
      if (connId) {
        try {
          await ocaRemoveConnection(systemId, connId);
          edgeToConnectionId.current.delete(edge.id);
        } catch {
          // ignore
        }
      }
    }
  }, [systemId]);

  // ---------------------------------------------------------------------------
  // Run Assessment
  // ---------------------------------------------------------------------------
  const runAssessment = useCallback(async () => {
    if (!systemId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await ocaAssessSystem(systemId);
      setAssessment(result);

      // Update node data with assessment results
      setNodes(nds => nds.map(node => {
        const compId = nodeToComponentId.current.get(node.id);
        if (!compId) return node;

        const updatedComp = result.components.find(c => c.component_id === compId);
        if (!updatedComp) return node;

        componentMap.current.set(compId, updatedComp);

        return {
          ...node,
          data: {
            ...node.data,
            component: updatedComp,
            onInspect: handleInspect,
          },
        };
      }));

      // Update edges — highlight kindling chain paths
      if (result.kindling_chains.length > 0) {
        const chainComponentIds = new Set<string>();
        for (const chain of result.kindling_chains) {
          chain.propagation_path.forEach(id => chainComponentIds.add(id));
        }

        setEdges(eds => eds.map(edge => {
          const sourceCompId = nodeToComponentId.current.get(edge.source || '');
          const targetCompId = nodeToComponentId.current.get(edge.target || '');
          const isInChain = sourceCompId && targetCompId &&
            chainComponentIds.has(sourceCompId) && chainComponentIds.has(targetCompId);

          return {
            ...edge,
            style: {
              stroke: isInChain ? '#ef4444' : '#3b82f6',
              strokeWidth: isInChain ? 3 : 2,
            },
            animated: true,
          };
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Assessment failed');
    } finally {
      setLoading(false);
    }
  }, [systemId, setNodes, setEdges]);

  // ---------------------------------------------------------------------------
  // Path Inspector
  // ---------------------------------------------------------------------------
  const handleInspect = useCallback(async (componentId: string) => {
    if (!systemId) return;
    try {
      const result = await ocaGetPathInspector(systemId, componentId);
      setPathResult(result);
    } catch {
      // ignore
    }
  }, [systemId]);

  // ---------------------------------------------------------------------------
  // Export
  // ---------------------------------------------------------------------------
  const handleExport = useCallback(async () => {
    if (!systemId) return;
    try {
      const data = await ocaExportSystem(systemId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `oca-system-${systemId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    }
  }, [systemId]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="flex flex-col h-[calc(100vh-60px)]">
      {/* Page Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <div>
          <h1 className="text-lg font-semibold tracking-tight flex items-center gap-2">
            <LayoutGrid className="h-5 w-5" />
            OCA System Builder
          </h1>
          <p className="text-xs text-muted-foreground">
            Visual topology-aware oxygen hazard assessment per BS-SPEC-OCA-002-REV0
          </p>
        </div>
        <div className="flex items-center gap-2">
          {assessment && (
            <Badge className={DISPOSITION_LABELS[assessment.system_disposition]?.color || 'bg-gray-600 text-white'}>
              {DISPOSITION_LABELS[assessment.system_disposition]?.label || assessment.system_disposition}
            </Badge>
          )}
          <Badge variant="outline" className="text-xs">Phase 2</Badge>
        </div>
      </div>

      {/* MPR 67 Banner */}
      {assessment?.mpr67_active && (
        <Alert variant="destructive" className="mx-4 mt-2 border-red-700 bg-red-950">
          <XCircle className="h-4 w-4" />
          <AlertTitle className="text-sm font-bold">
            MPR 67 GOVERNING PROHIBITION — Titanium forbidden in LOX/GOX at any pressure
          </AlertTitle>
          <AlertDescription className="text-xs">
            One or more components contain titanium alloys. Per NASA-STD-6016C §4.2.1.3c,
            titanium SHALL NOT be used with LOX or GOX at any pressure, or with air above 5 psia O2 partial pressure.
          </AlertDescription>
        </Alert>
      )}

      {/* Disclaimer */}
      <div className="px-4 pt-2">
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription className="text-xs">
            Screening aid only. Topology, not geometry. Every inferred state is visible. Every rule has provenance.
          </AlertDescription>
        </Alert>
      </div>

      {/* System Input Bar */}
      <div className="px-4 py-2">
        <SystemInputBar inputs={inputs} onChange={handleInputChange} />
      </div>

      {/* Blocked States */}
      {assessment && assessment.blocked_states.length > 0 && (
        <div className="px-4">
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle className="text-sm">Blocked States</AlertTitle>
            <AlertDescription>
              {assessment.blocked_states.map((b, i) => (
                <div key={i} className="text-xs mt-1">
                  <strong className="uppercase">{b.state_type.replace(/_/g, ' ')}</strong>: {b.description}
                </div>
              ))}
            </AlertDescription>
          </Alert>
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center gap-2 px-4 py-1.5 border-b">
        <Button size="sm" onClick={runAssessment} disabled={loading || !systemId} className="gap-1.5">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
          Assess System
        </Button>
        <Button size="sm" variant="outline" onClick={handleExport} disabled={!assessment} className="gap-1.5">
          <Download className="h-3 w-3" />
          Export
        </Button>
        {assessment && assessment.kindling_chains.length > 0 && (
          <Button size="sm" variant={showKindling ? 'default' : 'outline'} onClick={() => setShowKindling(!showKindling)} className="gap-1.5">
            <Flame className="h-3 w-3" />
            Kindling Chains ({assessment.kindling_chains.length})
          </Button>
        )}

        {/* Zone legend */}
        <div className="flex items-center gap-2 ml-auto">
          {(Object.entries(ZONE_COLORS) as [string, string][]).map(([zone, color]) => (
            <div key={zone} className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[9px] text-muted-foreground">{(ZONE_LABELS as Record<string, string>)[zone]?.split(' ')[0]}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-1">
          <Alert variant="destructive">
            <XCircle className="h-4 w-4" />
            <AlertDescription className="text-xs">{error}</AlertDescription>
          </Alert>
        </div>
      )}

      {/* Main content area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Component Palette */}
        <div className="p-2">
          <ComponentPalette />
        </div>

        {/* React Flow Canvas */}
        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onInit={setRfInstance}
            nodeTypes={nodeTypes}
            fitView
            deleteKeyCode="Delete"
            className="bg-background"
          >
            <Controls />
            <MiniMap
              className="!bg-card"
              nodeColor={(node) => {
                const data = node.data as ComponentNodeData | undefined;
                if (!data?.component) return '#666';
                switch (data.component.overall_status) {
                  case 'green': return '#22c55e';
                  case 'yellow': return '#f59e0b';
                  case 'red': return '#ef4444';
                  default: return '#666';
                }
              }}
            />
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          </ReactFlow>
        </div>

        {/* Path Inspector Panel */}
        {pathResult && (
          <div className="p-2">
            <PathInspectorPanel result={pathResult} onClose={() => setPathResult(null)} />
          </div>
        )}
      </div>

      {/* Bottom Panel — Assessment Results & Kindling Chains */}
      {assessment && (
        <div className="border-t bg-card">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="w-full justify-start rounded-none border-b px-4 h-8">
              <TabsTrigger value="canvas" className="text-xs h-7">Canvas</TabsTrigger>
              <TabsTrigger value="summary" className="text-xs h-7">
                Summary
                {assessment && <Badge className="ml-1 text-[8px]" variant="outline">{assessment.components.length}</Badge>}
              </TabsTrigger>
              <TabsTrigger value="kindling" className="text-xs h-7">
                Kindling Chains
                {assessment.kindling_chains.length > 0 && (
                  <Badge className="ml-1 text-[8px] bg-red-600 text-white">{assessment.kindling_chains.length}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="controls" className="text-xs h-7">
                Hazard Controls
                {assessment.hazard_controls.length > 0 && (
                  <Badge className="ml-1 text-[8px]" variant="outline">{assessment.hazard_controls.length}</Badge>
                )}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="canvas" className="m-0 p-0" />

            <TabsContent value="summary" className="m-0">
              <div className="max-h-48 overflow-y-auto p-4 space-y-2">
                {/* System stats */}
                <div className="grid grid-cols-5 gap-2">
                  <div className="p-2 rounded bg-muted text-center">
                    <div className="text-[10px] text-muted-foreground uppercase">Disposition</div>
                    <Badge className={`mt-1 text-[10px] ${DISPOSITION_LABELS[assessment.system_disposition]?.color || ''}`}>
                      {DISPOSITION_LABELS[assessment.system_disposition]?.label || assessment.system_disposition}
                    </Badge>
                  </div>
                  <div className="p-2 rounded bg-muted text-center">
                    <div className="text-[10px] text-muted-foreground uppercase">Reaction Effect</div>
                    <Badge className={`mt-1 text-[10px] ${REACTION_COLORS[assessment.system_reaction_effect] || ''}`}>
                      {REACTION_LABELS[assessment.system_reaction_effect] || assessment.system_reaction_effect}
                    </Badge>
                  </div>
                  <div className="p-2 rounded bg-muted text-center">
                    <div className="text-[10px] text-muted-foreground uppercase">Components</div>
                    <div className="text-sm font-semibold mt-1">{assessment.components.length}</div>
                  </div>
                  <div className="p-2 rounded bg-muted text-center">
                    <div className="text-[10px] text-muted-foreground uppercase">Red</div>
                    <div className="text-sm font-semibold mt-1 text-red-400">
                      {assessment.components.filter(c => c.overall_status === 'red').length}
                    </div>
                  </div>
                  <div className="p-2 rounded bg-muted text-center">
                    <div className="text-[10px] text-muted-foreground uppercase">Chains</div>
                    <div className="text-sm font-semibold mt-1">{assessment.kindling_chains.length}</div>
                  </div>
                </div>

                {/* Requirements */}
                {assessment.triggered_requirements.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {assessment.triggered_requirements.map((r, i) => (
                      <Badge
                        key={i}
                        variant={r.is_prohibition ? 'destructive' : r.satisfied ? 'default' : 'secondary'}
                        className="text-[9px] gap-1"
                      >
                        {r.requirement_id}
                        {r.is_prohibition && ' — PROHIBITION'}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </TabsContent>

            <TabsContent value="kindling" className="m-0">
              <div className="max-h-48 overflow-y-auto p-4 space-y-2">
                {assessment.kindling_chains.length === 0 ? (
                  <div className="text-xs text-muted-foreground">No kindling chains detected.</div>
                ) : (
                  assessment.kindling_chains.map((chain, i) => (
                    <div key={i} className="p-2 rounded bg-muted space-y-1">
                      <div className="flex items-center gap-2">
                        <Flame className="h-3 w-3 text-red-400" />
                        <Badge className={REACTION_COLORS[chain.reaction_effect] || ''}>
                          {REACTION_LABELS[chain.reaction_effect] || chain.reaction_effect}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          {chain.longest_continuous_length} component(s) in chain
                        </span>
                        {chain.chain_broken_at && (
                          <Badge variant="outline" className="text-[9px]">
                            Chain broken: {chain.break_reason}
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-1 flex-wrap">
                        {chain.materials_in_path.map((mat, j) => (
                          <span key={j} className="flex items-center gap-0.5">
                            {j > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                            <Badge variant="outline" className="text-[9px]">{mat}</Badge>
                          </span>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </TabsContent>

            <TabsContent value="controls" className="m-0">
              <div className="max-h-48 overflow-y-auto p-4">
                {assessment.hazard_controls.length === 0 ? (
                  <div className="text-xs text-muted-foreground">No hazard controls required.</div>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="text-left py-1 pr-2">Hazard</th>
                        <th className="text-left py-1 pr-2">Rating</th>
                        <th className="text-left py-1 pr-2">Recommendation</th>
                        <th className="text-left py-1">Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assessment.hazard_controls.map((hc, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="py-1 pr-2 capitalize">{hc.ignition_hazard.replace(/_/g, ' ')}</td>
                          <td className="py-1 pr-2">{hc.probability_rating}/4</td>
                          <td className="py-1 pr-2">{hc.recommendation}</td>
                          <td className="py-1">{hc.confidence}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
}
