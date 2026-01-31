import { useState, useRef, useCallback } from "react";
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
} from "@dnd-kit/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";
import {
  Upload,
  Download,
  GitBranch,
  ChevronRight,
  ChevronDown,
  GripVertical,
  Undo2,
  FileJson,
  FolderTree,
  Package,
  File,
  FileImage,
  Loader2,
} from "lucide-react";

// ============================================================================
// Types
// ============================================================================

interface TreeNode {
  drawing_number: string;
  title: string;
  parent: string | null;
  type: "ASSEMBLY" | "DETAIL";
}

interface TreeData {
  top_level: string;
  tree: TreeNode[];
}

interface HistoryEntry {
  tree: TreeNode[];
  description: string;
}

// ============================================================================
// Tree Utilities
// ============================================================================

function buildChildrenMap(tree: TreeNode[]): Map<string | null, TreeNode[]> {
  const childrenMap = new Map<string | null, TreeNode[]>();
  for (const node of tree) {
    const parent = node.parent;
    if (!childrenMap.has(parent)) {
      childrenMap.set(parent, []);
    }
    childrenMap.get(parent)!.push(node);
  }
  return childrenMap;
}

function countDescendants(
  nodeId: string,
  childrenMap: Map<string | null, TreeNode[]>
): number {
  const children = childrenMap.get(nodeId) || [];
  let count = children.length;
  for (const child of children) {
    count += countDescendants(child.drawing_number, childrenMap);
  }
  return count;
}

function isDescendant(
  potentialAncestor: string,
  potentialDescendant: string,
  tree: TreeNode[]
): boolean {
  const nodeMap = new Map(tree.map((n) => [n.drawing_number, n]));
  let current = nodeMap.get(potentialDescendant);
  while (current?.parent) {
    if (current.parent === potentialAncestor) return true;
    current = nodeMap.get(current.parent);
  }
  return false;
}

// ============================================================================
// Draggable Node Component
// ============================================================================

interface DraggableNodeProps {
  node: TreeNode;
  children: TreeNode[];
  childrenMap: Map<string | null, TreeNode[]>;
  depth: number;
  expandedNodes: Set<string>;
  toggleExpand: (id: string) => void;
  activeId: string | null;
}

function DraggableNode({
  node,
  children: childNodes,
  childrenMap,
  depth,
  expandedNodes,
  toggleExpand,
  activeId,
}: DraggableNodeProps) {
  const {
    attributes,
    listeners,
    setNodeRef: setDragRef,
    isDragging,
  } = useDraggable({
    id: node.drawing_number,
  });

  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: node.drawing_number,
  });

  const hasChildren = childNodes.length > 0;
  const isExpanded = expandedNodes.has(node.drawing_number);
  const descendantCount = countDescendants(node.drawing_number, childrenMap);

  // Combine refs
  const setRefs = (element: HTMLDivElement | null) => {
    setDragRef(element);
    setDropRef(element);
  };

  return (
    <div className="select-none">
      {/* Node Box */}
      <div
        ref={setRefs}
        className={`
          flex items-center gap-2 p-2 rounded-lg border-2 mb-1 transition-all
          ${isDragging ? "opacity-50 border-dashed border-primary" : ""}
          ${isOver && activeId !== node.drawing_number ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-border"}
          ${node.type === "ASSEMBLY" ? "bg-card" : "bg-muted/50"}
          hover:border-primary/50
        `}
        style={{ marginLeft: depth * 24 }}
      >
        {/* Drag Handle - touch target */}
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing touch-none p-1 -m-1"
        >
          <GripVertical className="h-5 w-5 text-muted-foreground" />
        </div>

        {/* Expand/Collapse */}
        <button
          onClick={() => hasChildren && toggleExpand(node.drawing_number)}
          className={`flex-shrink-0 p-1 ${hasChildren ? "cursor-pointer" : "cursor-default opacity-30"}`}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>

        {/* Icon */}
        {node.type === "ASSEMBLY" ? (
          <Package className="h-4 w-4 text-blue-600 flex-shrink-0" />
        ) : (
          <File className="h-4 w-4 text-gray-500 flex-shrink-0" />
        )}

        {/* Part Number */}
        <span className="font-mono font-semibold text-sm min-w-[100px] sm:min-w-[140px]">
          {node.drawing_number}
        </span>

        {/* Title - hide on very small screens */}
        <span className="text-sm text-muted-foreground truncate flex-1 hidden sm:block">
          {node.title}
        </span>

        {/* Type Badge */}
        <Badge
          variant={node.type === "ASSEMBLY" ? "default" : "secondary"}
          className="text-xs flex-shrink-0"
        >
          {node.type === "ASSEMBLY" ? "ASM" : "DTL"}
        </Badge>

        {/* Children Count */}
        {hasChildren && (
          <span className="text-xs text-muted-foreground flex-shrink-0">
            ({descendantCount})
          </span>
        )}
      </div>

      {/* Children */}
      {isExpanded && hasChildren && (
        <div className="relative">
          {/* Connector Line */}
          <div
            className="absolute left-0 top-0 bottom-4 w-px bg-border"
            style={{ marginLeft: depth * 24 + 20 }}
          />
          {childNodes.map((child) => (
            <DraggableNode
              key={child.drawing_number}
              node={child}
              children={childrenMap.get(child.drawing_number) || []}
              childrenMap={childrenMap}
              depth={depth + 1}
              expandedNodes={expandedNodes}
              toggleExpand={toggleExpand}
              activeId={activeId}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Drag Overlay Component (what you see while dragging)
// ============================================================================

function DragOverlayNode({ node }: { node: TreeNode }) {
  return (
    <div
      className={`
        flex items-center gap-2 p-2 rounded-lg border-2 border-primary bg-card shadow-lg
        ${node.type === "ASSEMBLY" ? "bg-card" : "bg-muted/50"}
      `}
    >
      <GripVertical className="h-5 w-5 text-primary" />
      {node.type === "ASSEMBLY" ? (
        <Package className="h-4 w-4 text-blue-600" />
      ) : (
        <File className="h-4 w-4 text-gray-500" />
      )}
      <span className="font-mono font-semibold text-sm">{node.drawing_number}</span>
      <Badge variant={node.type === "ASSEMBLY" ? "default" : "secondary"} className="text-xs">
        {node.type === "ASSEMBLY" ? "ASM" : "DTL"}
      </Badge>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function DTTreeEditor() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);

  // Tree state
  const [treeData, setTreeData] = useState<TreeData | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  // Drag state
  const [activeId, setActiveId] = useState<string | null>(null);

  // History for undo
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // PDF extraction state
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionProgress, setExtractionProgress] = useState<string>("");

  // Configure sensors for both mouse and touch
  const mouseSensor = useSensor(MouseSensor, {
    activationConstraint: {
      distance: 10, // 10px movement before drag starts
    },
  });
  const touchSensor = useSensor(TouchSensor, {
    activationConstraint: {
      delay: 200, // 200ms press before drag starts
      tolerance: 5,
    },
  });
  const sensors = useSensors(mouseSensor, touchSensor);

  // Stats
  const assemblyCount = treeData?.tree.filter((n) => n.type === "ASSEMBLY").length || 0;
  const detailCount = treeData?.tree.filter((n) => n.type === "DETAIL").length || 0;

  // ============================================================================
  // File Operations
  // ============================================================================

  const handleFileUpload = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const json = JSON.parse(e.target?.result as string);

          // Support both v3 flat format and nested format
          let flatTree: TreeData;

          if (json.top_level && json.tree) {
            flatTree = json as TreeData;
          } else if (json.root) {
            flatTree = convertNestedToFlat(json);
          } else {
            throw new Error("Unrecognized JSON format");
          }

          setTreeData(flatTree);
          const assemblies = flatTree.tree
            .filter((n) => n.type === "ASSEMBLY")
            .map((n) => n.drawing_number);
          setExpandedNodes(new Set(assemblies));

          setHistory([{ tree: flatTree.tree, description: "Loaded from file" }]);
          setHistoryIndex(0);

          toast({
            title: "Tree Loaded",
            description: `${flatTree.tree.length} nodes loaded from ${file.name}`,
          });
        } catch (err) {
          toast({
            title: "Error Loading File",
            description: String(err),
            variant: "destructive",
          });
        }
      };
      reader.readAsText(file);
    },
    [toast]
  );

  interface NestedNode {
    part_number: string;
    name?: string;
    title?: string;
    status?: string;
    children?: NestedNode[];
  }

  const convertNestedToFlat = (nested: { root: NestedNode }): TreeData => {
    const flatEntries: TreeNode[] = [];

    const flatten = (node: NestedNode, parentPn: string | null) => {
      const hasChildren = (node.children?.length || 0) > 0;
      flatEntries.push({
        drawing_number: node.part_number,
        title: node.name || node.title || "",
        parent: parentPn,
        type: hasChildren ? "ASSEMBLY" : "DETAIL",
      });
      for (const child of node.children || []) {
        flatten(child, node.part_number);
      }
    };

    flatten(nested.root, null);

    return {
      top_level: nested.root.part_number,
      tree: flatEntries,
    };
  };

  // ============================================================================
  // PDF Extraction
  // ============================================================================

  const handlePdfUpload = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;

      event.target.value = "";

      setIsExtracting(true);
      setExtractionProgress("Uploading PDF to extraction service...");

      try {
        const formData = new FormData();
        formData.append("dt_file", file);

        const response = await fetch("/api/miul/extract-dt", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Extraction failed: ${errorText}`);
        }

        const { session_id } = await response.json();
        if (!session_id) {
          throw new Error("No session_id returned from extraction");
        }

        setExtractionProgress("Analyzing drawing tree with Claude Vision...");

        const maxAttempts = 60;
        const pollInterval = 2000;

        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          await new Promise(resolve => setTimeout(resolve, pollInterval));

          const statusRes = await fetch(`/api/dt/session/${session_id}`);
          if (!statusRes.ok) {
            throw new Error("Failed to check extraction status");
          }

          const session = await statusRes.json();

          if (session.status === "complete") {
            setExtractionProgress("Processing extraction results...");

            if (!session.tree || session.tree.length === 0) {
              throw new Error("Extraction returned empty tree");
            }

            const flatTree: TreeData = {
              top_level: session.top_level,
              tree: session.tree,
            };

            setTreeData(flatTree);

            const assemblies = flatTree.tree
              .filter((n) => n.type === "ASSEMBLY")
              .map((n) => n.drawing_number);
            setExpandedNodes(new Set(assemblies));

            setHistory([{ tree: flatTree.tree, description: "Extracted from PDF" }]);
            setHistoryIndex(0);

            toast({
              title: "Extraction Complete",
              description: `${flatTree.tree.length} nodes extracted. Review and correct if needed.`,
            });
            return;
          } else if (session.status === "failed") {
            throw new Error(session.error || "Extraction failed");
          }

          setExtractionProgress(`Analyzing drawing tree... (${attempt * 2}s)`);
        }

        throw new Error("Extraction timed out after 2 minutes");
      } catch (err) {
        toast({
          title: "Extraction Failed",
          description: String(err),
          variant: "destructive",
        });
      } finally {
        setIsExtracting(false);
        setExtractionProgress("");
      }
    },
    [toast]
  );

  const handleExport = useCallback(() => {
    if (!treeData) return;

    const json = JSON.stringify(treeData, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${treeData.top_level}_corrected.json`;
    a.click();
    URL.revokeObjectURL(url);

    toast({
      title: "Exported",
      description: `Saved as ${treeData.top_level}_corrected.json`,
    });
  }, [treeData, toast]);

  // ============================================================================
  // Drag and Drop Handlers
  // ============================================================================

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      setActiveId(null);

      if (!treeData || !over || active.id === over.id) {
        return;
      }

      const draggedId = active.id as string;
      const targetId = over.id as string;

      // Can't drop onto descendants
      if (isDescendant(draggedId, targetId, treeData.tree)) {
        toast({
          title: "Invalid Move",
          description: "Cannot move a node under its own descendant",
          variant: "destructive",
        });
        return;
      }

      const draggedNodeData = treeData.tree.find((n) => n.drawing_number === draggedId);
      if (!draggedNodeData) return;

      const oldParent = draggedNodeData.parent;
      if (oldParent === targetId) return;

      // Update the tree
      const newTree = treeData.tree.map((node) => {
        if (node.drawing_number === draggedId) {
          return { ...node, parent: targetId };
        }
        return node;
      });

      // Update types
      const finalTree = newTree.map((node) => {
        if (node.drawing_number === targetId && node.type === "DETAIL") {
          return { ...node, type: "ASSEMBLY" as const };
        }
        if (
          node.drawing_number === oldParent &&
          !newTree.some((n) => n.parent === oldParent && n.drawing_number !== draggedId)
        ) {
          return { ...node, type: "DETAIL" as const };
        }
        return node;
      });

      // Save history
      const description = `Moved ${draggedId} from ${oldParent || "root"} to ${targetId}`;
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push({ tree: finalTree, description });
      setHistory(newHistory);
      setHistoryIndex(newHistory.length - 1);

      setTreeData({ ...treeData, tree: finalTree });

      toast({
        title: "Node Moved",
        description: `${draggedId} is now under ${targetId}`,
      });
    },
    [treeData, history, historyIndex, toast]
  );

  // ============================================================================
  // History / Undo
  // ============================================================================

  const handleUndo = useCallback(() => {
    if (historyIndex > 0 && treeData) {
      const prevIndex = historyIndex - 1;
      setHistoryIndex(prevIndex);
      setTreeData({ ...treeData, tree: history[prevIndex].tree });
      toast({
        title: "Undone",
        description: history[historyIndex].description,
      });
    }
  }, [historyIndex, history, treeData, toast]);

  // ============================================================================
  // Tree Expand/Collapse
  // ============================================================================

  const toggleExpand = useCallback((nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    if (treeData) {
      const allIds = treeData.tree.map((n) => n.drawing_number);
      setExpandedNodes(new Set(allIds));
    }
  }, [treeData]);

  const collapseAll = useCallback(() => {
    setExpandedNodes(new Set());
  }, []);

  // Build children map for rendering
  const childrenMap = treeData ? buildChildrenMap(treeData.tree) : new Map();
  const rootNodes = childrenMap.get(null) || [];

  // Find active node for overlay
  const activeNode = activeId ? treeData?.tree.find((n) => n.drawing_number === activeId) : null;

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 sm:gap-3">
          <FolderTree className="h-6 w-6 sm:h-8 sm:w-8 text-primary" />
          <div>
            <h1 className="text-xl sm:text-2xl font-bold">Drawing Tree Editor</h1>
            <p className="text-muted-foreground text-sm hidden sm:block">
              Drag and drop to correct hierarchy relationships
            </p>
          </div>
        </div>
        <PageHelp content={helpContent.dtTreeEditor || helpContent.miul} />
      </div>

      {/* Toolbar */}
      <Card>
        <CardContent className="p-3 sm:p-4">
          <div className="flex items-center gap-2 sm:gap-4 flex-wrap">
            {/* PDF Upload */}
            <input
              type="file"
              accept=".pdf"
              ref={pdfInputRef}
              onChange={handlePdfUpload}
              className="hidden"
            />
            <Button
              variant="default"
              size="sm"
              onClick={() => pdfInputRef.current?.click()}
              disabled={isExtracting}
              className="text-xs sm:text-sm"
            >
              {isExtracting ? (
                <Loader2 className="h-4 w-4 mr-1 sm:mr-2 animate-spin" />
              ) : (
                <FileImage className="h-4 w-4 mr-1 sm:mr-2" />
              )}
              {isExtracting ? "..." : "Extract PDF"}
            </Button>

            {/* JSON Upload */}
            <input
              type="file"
              accept=".json"
              ref={fileInputRef}
              onChange={handleFileUpload}
              className="hidden"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={isExtracting}
              className="text-xs sm:text-sm"
            >
              <Upload className="h-4 w-4 mr-1 sm:mr-2" />
              <span className="hidden sm:inline">Load</span> JSON
            </Button>

            {/* Export */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={!treeData || isExtracting}
              className="text-xs sm:text-sm"
            >
              <Download className="h-4 w-4 mr-1 sm:mr-2" />
              Export
            </Button>

            <div className="h-6 w-px bg-border hidden sm:block" />

            {/* Expand/Collapse - hide on mobile */}
            <div className="hidden sm:flex gap-2">
              <Button variant="ghost" size="sm" onClick={expandAll} disabled={!treeData}>
                Expand All
              </Button>
              <Button variant="ghost" size="sm" onClick={collapseAll} disabled={!treeData}>
                Collapse All
              </Button>
            </div>

            {/* Undo */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleUndo}
              disabled={historyIndex <= 0}
              className="text-xs sm:text-sm"
            >
              <Undo2 className="h-4 w-4 mr-1" />
              Undo
            </Button>

            {/* Stats - hide on mobile */}
            {treeData && (
              <div className="hidden md:flex items-center gap-4 ml-auto text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Package className="h-4 w-4 text-blue-600" />
                  {assemblyCount}
                </span>
                <span className="flex items-center gap-1">
                  <File className="h-4 w-4 text-gray-500" />
                  {detailCount}
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Extraction Progress */}
      {isExtracting && (
        <Card className="border-blue-200 bg-blue-50 dark:bg-blue-950 dark:border-blue-900">
          <CardContent className="p-4 sm:p-6">
            <div className="flex items-center gap-4">
              <Loader2 className="h-6 w-6 sm:h-8 sm:w-8 animate-spin text-blue-600" />
              <div>
                <h3 className="font-semibold text-sm sm:text-base">Extracting...</h3>
                <p className="text-xs sm:text-sm text-muted-foreground">{extractionProgress}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tree View with DnD */}
      {!treeData && !isExtracting ? (
        <Card className="border-dashed">
          <CardContent className="p-8 sm:p-12 text-center">
            <FolderTree className="h-12 w-12 sm:h-16 sm:w-16 mx-auto text-muted-foreground mb-4" />
            <h3 className="text-base sm:text-lg font-semibold mb-2">No Drawing Tree Loaded</h3>
            <p className="text-muted-foreground text-sm mb-6">
              Extract from PDF or load JSON
            </p>
            <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 justify-center">
              <Button size="default" onClick={() => pdfInputRef.current?.click()}>
                <FileImage className="h-5 w-5 mr-2" />
                Extract from PDF
              </Button>
              <Button variant="outline" size="default" onClick={() => fileInputRef.current?.click()}>
                <FileJson className="h-5 w-5 mr-2" />
                Load JSON
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : treeData ? (
        <Card>
          <CardHeader className="pb-2 px-3 sm:px-6">
            <CardTitle className="flex items-center gap-2 text-base sm:text-lg">
              <GitBranch className="h-4 w-4 sm:h-5 sm:w-5" />
              {treeData.top_level}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4">
            <div className="text-xs sm:text-sm text-muted-foreground mb-4 bg-muted/50 p-2 sm:p-3 rounded-lg">
              <strong>Tip:</strong> Hold the grip icon and drag to move nodes. Works on touch screens!
            </div>
            <DndContext
              sensors={sensors}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
            >
              <div className="space-y-1">
                {rootNodes.map((node) => (
                  <DraggableNode
                    key={node.drawing_number}
                    node={node}
                    children={childrenMap.get(node.drawing_number) || []}
                    childrenMap={childrenMap}
                    depth={0}
                    expandedNodes={expandedNodes}
                    toggleExpand={toggleExpand}
                    activeId={activeId}
                  />
                ))}
              </div>
              <DragOverlay>
                {activeNode ? <DragOverlayNode node={activeNode} /> : null}
              </DragOverlay>
            </DndContext>
          </CardContent>
        </Card>
      ) : null}

      {/* History Panel - hide on mobile */}
      {history.length > 1 && (
        <Card className="hidden sm:block">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Edit History</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <div className="space-y-1 text-sm">
              {history.map((entry, idx) => (
                <div
                  key={idx}
                  className={`px-2 py-1 rounded ${
                    idx === historyIndex
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-muted-foreground"
                  }`}
                >
                  {idx}. {entry.description}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
