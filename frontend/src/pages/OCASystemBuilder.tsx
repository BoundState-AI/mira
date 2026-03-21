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

import {
  GuidanceContextIndicator,
  GuidanceInlineHelp,
  GuidanceModeSelector,
  GuidanceProvider,
} from '@/components/guidance';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Loader2, AlertTriangle, XCircle, Flame, Download, Zap, Info,
  ChevronRight, LayoutGrid, Clock3,
} from 'lucide-react';

import ComponentNode, { type ComponentNodeData } from '@/components/oca-system/ComponentNode';
import ComponentEditorSheet from '@/components/oca-system/ComponentEditorSheet';
import ComponentPalette from '@/components/oca-system/ComponentPalette';
import SystemInputBar from '@/components/oca-system/SystemInputBar';
import PathInspectorPanel from '@/components/oca-system/PathInspectorPanel';

import {
  ocaCreateSystem, ocaAddComponent, ocaAddConnection,
  ocaUpdateInputs, ocaUpdateComponent,
  ocaRemoveComponent, ocaRemoveConnection,
  ocaAssessSystem, ocaGetPathInspector, ocaExportSystem,
  type ComponentConfig,
  type ComponentUpdateRequest,
  type MaterialSlotValue,
  type SystemInputs, type SystemComponent, type SystemAssessmentResult,
  type PathInspectorResult, type ComponentArchetype,
  ZONE_COLORS, ZONE_LABELS,
} from '@/lib/oca-system-api';
import { authorityRegistry, createOcaContext, ocaGuidancePack } from '@/lib/guidance/oca-pack';
import type { GuidanceModeName } from '@/lib/guidance/types';

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
const DRAFT_STORAGE_KEY = 'boundstate:oca-system-builder:draft:v1';

interface BuilderDraftComponent {
  component_id: string;
  archetype: ComponentArchetype;
  label: string;
  position_x: number;
  position_y: number;
  materials: MaterialSlotValue[];
  config: Partial<ComponentConfig>;
  is_rigid_metallic_tubing?: boolean;
  is_metallic_flex_hose?: boolean;
  is_all_metal_seal?: boolean;
  is_metallic_pressure_vessel?: boolean;
}

interface BuilderDraft {
  version: 1;
  saved_at: string;
  inputs: SystemInputs;
  components: BuilderDraftComponent[];
  connections: Array<{
    source_component_id: string;
    target_component_id: string;
  }>;
}

function readDraft(): BuilderDraft | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BuilderDraft;
    if (parsed?.version !== 1) return null;
    return parsed;
  } catch {
    return null;
  }
}

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

function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false,
  );

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < breakpoint);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, [breakpoint]);

  return isMobile;
}

export default function OCASystemBuilder() {
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
        <LayoutGrid className="h-12 w-12 text-slate-400" />
        <h2 className="text-lg font-semibold text-slate-800">Desktop Required</h2>
        <p className="max-w-sm text-sm text-slate-500">
          The System Builder requires a desktop browser for the drag-and-drop canvas.
          Please open this page on a laptop or desktop computer.
        </p>
        <a
          href="/oca/workbench"
          className="mt-2 rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
        >
          Go to Workbench instead
        </a>
      </div>
    );
  }

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
  const [guidanceMode, setGuidanceMode] = useState<GuidanceModeName>('live');
  const [editorComponentId, setEditorComponentId] = useState<string | null>(null);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  // React Flow
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);

  const guidanceContext = createOcaContext({
    user_mode: guidanceMode,
    program: inputs.project_name || undefined,
    service_environment: inputs.phase,
    pressure_regime:
      inputs.system_pressure_max_psia >= 265
        ? 'high'
        : inputs.system_pressure_max_psia >= 50
          ? 'medium'
          : 'low',
  });

  // Component ID → server component map
  const componentMap = useRef<Map<string, SystemComponent>>(new Map());
  // Node ID → server component ID
  const nodeToComponentId = useRef<Map<string, string>>(new Map());
  // Edge ID → server connection ID
  const edgeToConnectionId = useRef<Map<string, string>>(new Map());
  const selectedNodeComponentId = useMemo(() => {
    const selectedNode = nodes.find((node) => node.selected);
    if (!selectedNode) return null;
    return nodeToComponentId.current.get(selectedNode.id) ?? null;
  }, [nodes]);

  const selectedComponent = useMemo(
    () => (editorComponentId ? componentMap.current.get(editorComponentId) ?? null : null),
    [editorComponentId, nodes, assessment],
  );

  const handleOpenEditor = useCallback((componentId: string) => {
    setEditorComponentId(componentId);
  }, []);

  const handleInspect = useCallback(async (componentId: string) => {
    if (!systemId) return;
    try {
      const result = await ocaGetPathInspector(systemId, componentId);
      setPathResult(result);
    } catch {
      // ignore
    }
  }, [systemId]);

  const buildNode = useCallback((component: SystemComponent): Node => ({
    id: `node-${component.component_id}`,
    type: 'component',
    position: { x: component.position_x, y: component.position_y },
    data: {
      component,
      onInspect: handleInspect,
      onEdit: handleOpenEditor,
    } as ComponentNodeData,
  }), [handleInspect, handleOpenEditor]);

  const syncComponentLocal = useCallback((componentId: string, nextComponent: SystemComponent) => {
    componentMap.current.set(componentId, nextComponent);
    setNodes((currentNodes) => currentNodes.map((node) => {
      if (nodeToComponentId.current.get(node.id) !== componentId) return node;
      return {
        ...node,
        data: {
          ...(node.data as ComponentNodeData),
          component: nextComponent,
          onInspect: handleInspect,
          onEdit: handleOpenEditor,
        },
      };
    }));
    setAssessment((currentAssessment) => {
      if (!currentAssessment) return currentAssessment;
      return {
        ...currentAssessment,
        components: currentAssessment.components.map((component) => (
          component.component_id === componentId ? nextComponent : component
        )),
      };
    });
  }, [handleInspect, handleOpenEditor, setNodes]);

  const buildDraftSnapshot = useCallback((): BuilderDraft => {
    const nodePositionByComponentId = new Map<string, { x: number; y: number }>();
    for (const node of nodes) {
      const componentId = nodeToComponentId.current.get(node.id);
      if (componentId) {
        nodePositionByComponentId.set(componentId, node.position);
      }
    }

    const components: BuilderDraftComponent[] = Array.from(componentMap.current.values()).map((component) => {
      const position = nodePositionByComponentId.get(component.component_id);
      return {
        component_id: component.component_id,
        archetype: component.archetype,
        label: component.label,
        position_x: position?.x ?? component.position_x,
        position_y: position?.y ?? component.position_y,
        materials: component.materials,
        config: component.config,
        is_rigid_metallic_tubing: component.is_rigid_metallic_tubing,
        is_metallic_flex_hose: component.is_metallic_flex_hose,
        is_all_metal_seal: component.is_all_metal_seal,
        is_metallic_pressure_vessel: component.is_metallic_pressure_vessel,
      };
    });

    const connections = edges.flatMap((edge) => {
      const sourceComponentId = nodeToComponentId.current.get(edge.source ?? '');
      const targetComponentId = nodeToComponentId.current.get(edge.target ?? '');
      if (!sourceComponentId || !targetComponentId) return [];
      return [{
        source_component_id: sourceComponentId,
        target_component_id: targetComponentId,
      }];
    });

    return {
      version: 1,
      saved_at: new Date().toISOString(),
      inputs,
      components,
      connections,
    };
  }, [edges, inputs, nodes]);

  const restoreDraft = useCallback(async (nextSystemId: string, draft: BuilderDraft) => {
    const componentIdMap = new Map<string, string>();
    const restoredNodes: Node[] = [];
    const restoredEdges: Edge[] = [];

    for (const component of draft.components) {
      const addResult = await ocaAddComponent(
        nextSystemId,
        component.archetype,
        component.label,
        component.position_x,
        component.position_y,
        component.materials,
        component.config,
      );

      const restoredComponent: SystemComponent = {
        component_id: addResult.component_id,
        archetype: component.archetype,
        label: component.label,
        position_x: component.position_x,
        position_y: component.position_y,
        materials: component.materials,
        config: component.config,
        features: addResult.features,
        inferred_facts: addResult.inferred_facts,
        zones: addResult.zones,
        mechanism_assessments: [],
        overall_status: 'pending',
        highest_rating: 0,
        credible_mechanisms: [],
        connected: false,
        is_rigid_metallic_tubing: component.is_rigid_metallic_tubing,
        is_metallic_flex_hose: component.is_metallic_flex_hose,
        is_all_metal_seal: component.is_all_metal_seal,
        is_metallic_pressure_vessel: component.is_metallic_pressure_vessel,
      };

      if (
        component.is_rigid_metallic_tubing
        || component.is_metallic_flex_hose
        || component.is_all_metal_seal
        || component.is_metallic_pressure_vessel
      ) {
        await ocaUpdateComponent(nextSystemId, addResult.component_id, {
          is_rigid_metallic_tubing: component.is_rigid_metallic_tubing,
          is_metallic_flex_hose: component.is_metallic_flex_hose,
          is_all_metal_seal: component.is_all_metal_seal,
          is_metallic_pressure_vessel: component.is_metallic_pressure_vessel,
        });
      }

      componentIdMap.set(component.component_id, addResult.component_id);
      componentMap.current.set(addResult.component_id, restoredComponent);
      nodeToComponentId.current.set(`node-${addResult.component_id}`, addResult.component_id);
      restoredNodes.push(buildNode(restoredComponent));
    }

    for (const connection of draft.connections) {
      const sourceComponentId = componentIdMap.get(connection.source_component_id);
      const targetComponentId = componentIdMap.get(connection.target_component_id);
      if (!sourceComponentId || !targetComponentId) continue;

      const addResult = await ocaAddConnection(nextSystemId, sourceComponentId, targetComponentId);
      const edgeId = `edge-${addResult.connection_id}`;
      edgeToConnectionId.current.set(edgeId, addResult.connection_id);
      restoredEdges.push({
        id: edgeId,
        source: `node-${sourceComponentId}`,
        target: `node-${targetComponentId}`,
        animated: true,
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      });
    }

    setNodes(restoredNodes);
    setEdges(restoredEdges);
    setDraftSavedAt(draft.saved_at);
    if (draft.components.length > 0 || draft.connections.length > 0) {
      setRestoreNotice(
        `Restored local draft with ${draft.components.length} component${draft.components.length === 1 ? '' : 's'}.`,
      );
      setIsDirty(true);
    }
  }, [buildNode, setEdges, setNodes]);

  // ---------------------------------------------------------------------------
  // Initialize system on mount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function init() {
      const draft = readDraft();
      const seedInputs = draft?.inputs ?? DEFAULT_INPUTS;
      setInputs(seedInputs);

      try {
        const res = await ocaCreateSystem('New O2 System', seedInputs);
        if (cancelled) return;
        setSystemId(res.system_id);

        if (draft) {
          await restoreDraft(res.system_id, draft);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to create system');
        }
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [restoreDraft]);

  useEffect(() => {
    if (!systemId) return undefined;

    const timeoutId = window.setTimeout(async () => {
      try {
        await ocaUpdateInputs(systemId, inputs);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update system inputs');
      }
    }, 250);

    return () => window.clearTimeout(timeoutId);
  }, [inputs, systemId]);

  useEffect(() => {
    if (!systemId || typeof window === 'undefined') return undefined;

    const timeoutId = window.setTimeout(() => {
      try {
        const draft = buildDraftSnapshot();
        window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
        setDraftSavedAt(draft.saved_at);
      } catch {
        // ignore local draft persistence errors
      }
    }, 300);

    return () => window.clearTimeout(timeoutId);
  }, [buildDraftSnapshot, systemId]);

  useEffect(() => {
    if (!restoreNotice) return undefined;
    const timeoutId = window.setTimeout(() => setRestoreNotice(null), 5000);
    return () => window.clearTimeout(timeoutId);
  }, [restoreNotice]);

  // ---------------------------------------------------------------------------
  // Update inputs
  // ---------------------------------------------------------------------------
  const handleInputChange = useCallback((updates: Partial<SystemInputs>) => {
    setInputs(prev => ({ ...prev, ...updates }));
    setIsDirty(true);
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

      setNodes(nds => [...nds, buildNode(serverComp)]);
      setIsDirty(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add component');
    }
  }, [buildNode, rfInstance, setNodes, systemId]);

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
      setIsDirty(true);
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
          if (editorComponentId === compId) {
            setEditorComponentId(null);
          }
          setIsDirty(true);
        } catch {
          // ignore
        }
      }
    }
  }, [editorComponentId, systemId]);

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
          setIsDirty(true);
        } catch {
          // ignore
        }
      }
    }
  }, [systemId]);

  // ---------------------------------------------------------------------------
  // Save component edits
  // ---------------------------------------------------------------------------
  const handleSaveComponent = useCallback(async (componentId: string, updates: ComponentUpdateRequest) => {
    if (!systemId) return;
    const response = await ocaUpdateComponent(systemId, componentId, updates);

    const currentComponent = componentMap.current.get(componentId);
    if (!currentComponent) return;

    const nextComponent: SystemComponent = response.component ?? {
      ...currentComponent,
      ...updates,
      label: updates.label ?? currentComponent.label,
      materials: updates.materials ?? currentComponent.materials,
      config: {
        ...currentComponent.config,
        ...(updates.config ?? {}),
      },
      is_rigid_metallic_tubing: updates.is_rigid_metallic_tubing ?? currentComponent.is_rigid_metallic_tubing,
      is_metallic_flex_hose: updates.is_metallic_flex_hose ?? currentComponent.is_metallic_flex_hose,
      is_all_metal_seal: updates.is_all_metal_seal ?? currentComponent.is_all_metal_seal,
      is_metallic_pressure_vessel: updates.is_metallic_pressure_vessel ?? currentComponent.is_metallic_pressure_vessel,
    };

    syncComponentLocal(componentId, nextComponent);
    setIsDirty(true);
  }, [syncComponentLocal, systemId]);

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
      setIsDirty(false);

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
            onEdit: handleOpenEditor,
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
  }, [handleInspect, handleOpenEditor, setNodes, setEdges, systemId]);

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
    <GuidanceProvider
      schema={ocaGuidancePack}
      context={guidanceContext}
      mode={guidanceMode}
      telemetryEnabled
      onModeChange={(newMode) => setGuidanceMode(newMode)}
      authorityRegistry={authorityRegistry}
    >
      <div className="flex h-[calc(100vh-60px)] flex-col">
        {/* Page Header */}
        <div className="space-y-3 border-b px-4 py-2">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
                <LayoutGrid className="h-5 w-5" />
                OCA System Builder
              </h1>
              <p className="text-xs text-muted-foreground">
                Visual topology-aware oxygen hazard assessment per BS-SPEC-OCA-002-REV0
              </p>
            </div>
            <div className="flex items-center gap-2">
              {assessment && (
                <div className="flex items-center gap-2">
                  <Badge className={DISPOSITION_LABELS[assessment.system_disposition]?.color || 'bg-gray-600 text-white'}>
                    {DISPOSITION_LABELS[assessment.system_disposition]?.label || assessment.system_disposition}
                  </Badge>
                  <GuidanceInlineHelp name={`disposition.${assessment.system_disposition}`} />
                </div>
              )}
              <Badge variant="outline" className="text-xs">Phase 2</Badge>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
            <GuidanceContextIndicator context={guidanceContext} />
            <GuidanceModeSelector
              currentMode={guidanceMode}
              context={guidanceContext}
              onModeChange={(newMode) => setGuidanceMode(newMode)}
            />
          </div>
        </div>

        {/* MPR 67 Banner */}
        {assessment?.mpr67_active && (
          <Alert variant="destructive" className="mx-4 mt-2 border-red-700 bg-red-950">
            <XCircle className="h-4 w-4" />
            <AlertTitle className="flex items-center gap-2 text-sm font-bold">
              <span>MPR 67 GOVERNING PROHIBITION — Titanium forbidden in LOX/GOX at any pressure</span>
              <GuidanceInlineHelp name="mpr.MPR_67" className="h-4 w-4 text-red-100" iconClassName="h-3.5 w-3.5" />
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

        {restoreNotice && (
          <div className="px-4 pt-2">
            <Alert className="border-sky-200 bg-sky-50 text-sky-900">
              <Clock3 className="h-4 w-4" />
              <AlertDescription className="text-xs">{restoreNotice}</AlertDescription>
            </Alert>
          </div>
        )}

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
                  <div key={i} className="mt-1 text-xs">
                    <strong className="uppercase">{b.state_type.replace(/_/g, ' ')}</strong>: {b.description}
                  </div>
                ))}
              </AlertDescription>
            </Alert>
          </div>
        )}

        {/* Action bar */}
        <div className="flex items-center gap-2 border-b px-4 py-1.5">
        <Button size="sm" onClick={runAssessment} disabled={loading || !systemId} className="gap-1.5" data-testid="oca-system-assess">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
          Assess System
        </Button>
        <Button size="sm" variant="outline" onClick={handleExport} disabled={!assessment} className="gap-1.5" data-testid="oca-system-export">
          <Download className="h-3 w-3" />
          Export
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => selectedNodeComponentId && handleOpenEditor(selectedNodeComponentId)}
          disabled={!selectedNodeComponentId}
          className="gap-1.5"
          data-testid="oca-system-edit-selected"
        >
          <LayoutGrid className="h-3 w-3" />
          Edit Selected
        </Button>
        {assessment && assessment.kindling_chains.length > 0 && (
          <Button size="sm" variant={showKindling ? 'default' : 'outline'} onClick={() => setShowKindling(!showKindling)} className="gap-1.5">
            <Flame className="h-3 w-3" />
            Kindling Chains ({assessment.kindling_chains.length})
          </Button>
        )}
        {isDirty && (
          <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-900">
            Needs reassessment
          </Badge>
        )}
        {draftSavedAt && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock3 className="h-3.5 w-3.5" />
            Draft saved {new Date(draftSavedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </div>
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
            data-testid="oca-system-canvas"
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            onNodeClick={(event, node) => {
              const clickTarget = event.target;
              if (
                clickTarget instanceof Element
                && clickTarget.closest('.react-flow__handle')
              ) {
                return;
              }
              const componentId = nodeToComponentId.current.get(node.id);
              if (componentId) {
                handleOpenEditor(componentId);
              }
            }}
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

        <ComponentEditorSheet
          component={selectedComponent}
          open={Boolean(selectedComponent)}
          onOpenChange={(open) => {
            if (!open) {
              setEditorComponentId(null);
            }
          }}
          onSave={handleSaveComponent}
          onInspect={handleInspect}
        />

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
                    <div className="mt-1 flex items-center justify-center gap-1.5">
                      <Badge className={`text-[10px] ${DISPOSITION_LABELS[assessment.system_disposition]?.color || ''}`}>
                        {DISPOSITION_LABELS[assessment.system_disposition]?.label || assessment.system_disposition}
                      </Badge>
                      <GuidanceInlineHelp name={`disposition.${assessment.system_disposition}`} />
                    </div>
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
                      <div key={`${r.requirement_id}-${i}`} className="inline-flex items-center gap-1">
                        <Badge
                          variant={r.is_prohibition ? 'destructive' : r.satisfied ? 'default' : 'secondary'}
                          className="text-[9px] gap-1"
                        >
                          {r.requirement_id}
                          {r.is_prohibition && ' — PROHIBITION'}
                        </Badge>
                        <GuidanceInlineHelp name={`mpr.${r.requirement_id}`} className="h-3.5 w-3.5" iconClassName="h-3 w-3" />
                      </div>
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
    </GuidanceProvider>
  );
}
