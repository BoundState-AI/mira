import { useState, useRef, useCallback, DragEvent } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
// Tree Node Component
// ============================================================================

interface TreeNodeItemProps {
  node: TreeNode;
  children: TreeNode[];
  childrenMap: Map<string | null, TreeNode[]>;
  depth: number;
  expandedNodes: Set<string>;
  toggleExpand: (id: string) => void;
  onDragStart: (e: DragEvent, nodeId: string) => void;
  onDragOver: (e: DragEvent) => void;
  onDrop: (e: DragEvent, targetId: string) => void;
  draggedNode: string | null;
  dropTarget: string | null;
  setDropTarget: (id: string | null) => void;
}

function TreeNodeItem({
  node,
  children,
  childrenMap,
  depth,
  expandedNodes,
  toggleExpand,
  onDragStart,
  onDragOver,
  onDrop,
  draggedNode,
  dropTarget,
  setDropTarget,
}: TreeNodeItemProps) {
  const hasChildren = children.length > 0;
  const isExpanded = expandedNodes.has(node.drawing_number);
  const isBeingDragged = draggedNode === node.drawing_number;
  const isDropTarget = dropTarget === node.drawing_number;
  const descendantCount = countDescendants(node.drawing_number, childrenMap);

  return (
    <div className="select-none">
      {/* Node Box */}
      <div
        className={`
          flex items-center gap-2 p-2 rounded-lg border-2 mb-1 transition-all cursor-grab
          ${isBeingDragged ? "opacity-50 border-dashed" : ""}
          ${isDropTarget ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-border"}
          ${node.type === "ASSEMBLY" ? "bg-card" : "bg-muted/50"}
          hover:border-primary/50
        `}
        style={{ marginLeft: depth * 24 }}
        draggable
        onDragStart={(e) => onDragStart(e, node.drawing_number)}
        onDragOver={(e) => {
          onDragOver(e);
          setDropTarget(node.drawing_number);
        }}
        onDragLeave={() => setDropTarget(null)}
        onDrop={(e) => onDrop(e, node.drawing_number)}
      >
        {/* Drag Handle */}
        <GripVertical className="h-4 w-4 text-muted-foreground flex-shrink-0" />

        {/* Expand/Collapse */}
        <button
          onClick={() => hasChildren && toggleExpand(node.drawing_number)}
          className={`flex-shrink-0 ${hasChildren ? "cursor-pointer" : "cursor-default opacity-30"}`}
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
        <span className="font-mono font-semibold text-sm min-w-[140px]">
          {node.drawing_number}
        </span>

        {/* Title */}
        <span className="text-sm text-muted-foreground truncate flex-1">
          {node.title}
        </span>

        {/* Type Badge */}
        <Badge
          variant={node.type === "ASSEMBLY" ? "default" : "secondary"}
          className="text-xs flex-shrink-0"
        >
          {node.type}
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
          {children.map((child) => (
            <TreeNodeItem
              key={child.drawing_number}
              node={child}
              children={childrenMap.get(child.drawing_number) || []}
              childrenMap={childrenMap}
              depth={depth + 1}
              expandedNodes={expandedNodes}
              toggleExpand={toggleExpand}
              onDragStart={onDragStart}
              onDragOver={onDragOver}
              onDrop={onDrop}
              draggedNode={draggedNode}
              dropTarget={dropTarget}
              setDropTarget={setDropTarget}
            />
          ))}
        </div>
      )}
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
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  // History for undo
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // PDF extraction state
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionProgress, setExtractionProgress] = useState<string>("");

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
            // Already flat format
            flatTree = json as TreeData;
          } else if (json.root) {
            // Nested format - convert
            flatTree = convertNestedToFlat(json);
          } else {
            throw new Error("Unrecognized JSON format");
          }

          setTreeData(flatTree);
          // Expand all assemblies by default
          const assemblies = flatTree.tree
            .filter((n) => n.type === "ASSEMBLY")
            .map((n) => n.drawing_number);
          setExpandedNodes(new Set(assemblies));

          // Initialize history
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

  const convertNestedToFlat = (nested: { root: NestedNode }): TreeData => {
    interface NestedNode {
      part_number: string;
      name?: string;
      title?: string;
      status?: string;
      children?: NestedNode[];
    }

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

      // Clear the input so the same file can be selected again
      event.target.value = "";

      setIsExtracting(true);
      setExtractionProgress("Uploading PDF to extraction service...");

      try {
        const formData = new FormData();
        formData.append("dt_file", file);
        formData.append("max_iterations", "3");

        setExtractionProgress("Analyzing drawing tree with Claude Vision...");

        const response = await fetch("/api/miul/extract-dt", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Extraction failed: ${errorText}`);
        }

        setExtractionProgress("Processing extraction results...");
        const result = await response.json();

        if (!result.tree || result.tree.length === 0) {
          throw new Error("Extraction returned empty tree");
        }

        // Load into editor
        const flatTree: TreeData = {
          top_level: result.top_level,
          tree: result.tree,
        };

        setTreeData(flatTree);

        // Expand all assemblies by default
        const assemblies = flatTree.tree
          .filter((n) => n.type === "ASSEMBLY")
          .map((n) => n.drawing_number);
        setExpandedNodes(new Set(assemblies));

        // Initialize history
        setHistory([{ tree: flatTree.tree, description: "Extracted from PDF" }]);
        setHistoryIndex(0);

        toast({
          title: "Extraction Complete",
          description: `${flatTree.tree.length} nodes extracted from ${file.name}. Review and correct if needed.`,
        });
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
  // Drag and Drop
  // ============================================================================

  const handleDragStart = useCallback((e: DragEvent, nodeId: string) => {
    setDraggedNode(nodeId);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", nodeId);
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent, targetId: string) => {
      e.preventDefault();
      setDropTarget(null);

      if (!treeData || !draggedNode || draggedNode === targetId) {
        setDraggedNode(null);
        return;
      }

      // Can't drop onto descendants (would create cycle)
      if (isDescendant(draggedNode, targetId, treeData.tree)) {
        toast({
          title: "Invalid Move",
          description: "Cannot move a node under its own descendant",
          variant: "destructive",
        });
        setDraggedNode(null);
        return;
      }

      // Find the dragged node
      const draggedNodeData = treeData.tree.find(
        (n) => n.drawing_number === draggedNode
      );
      if (!draggedNodeData) {
        setDraggedNode(null);
        return;
      }

      const oldParent = draggedNodeData.parent;
      if (oldParent === targetId) {
        // Already under this parent
        setDraggedNode(null);
        return;
      }

      // Update the tree
      const newTree = treeData.tree.map((node) => {
        if (node.drawing_number === draggedNode) {
          return { ...node, parent: targetId };
        }
        return node;
      });

      // Update types - target becomes ASSEMBLY if it wasn't
      const finalTree = newTree.map((node) => {
        if (node.drawing_number === targetId && node.type === "DETAIL") {
          return { ...node, type: "ASSEMBLY" as const };
        }
        // Old parent might become DETAIL if no children left
        if (
          node.drawing_number === oldParent &&
          !newTree.some(
            (n) => n.parent === oldParent && n.drawing_number !== draggedNode
          )
        ) {
          return { ...node, type: "DETAIL" as const };
        }
        return node;
      });

      // Save history
      const description = `Moved ${draggedNode} from ${oldParent || "root"} to ${targetId}`;
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push({ tree: finalTree, description });
      setHistory(newHistory);
      setHistoryIndex(newHistory.length - 1);

      setTreeData({ ...treeData, tree: finalTree });
      setDraggedNode(null);

      toast({
        title: "Node Moved",
        description: `${draggedNode} is now under ${targetId}`,
      });
    },
    [treeData, draggedNode, history, historyIndex, toast]
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

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FolderTree className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Drawing Tree Editor</h1>
            <p className="text-muted-foreground">
              Drag and drop to correct hierarchy relationships
            </p>
          </div>
        </div>
        <PageHelp content={helpContent.dtTreeEditor || helpContent.miul} />
      </div>

      {/* Toolbar */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4 flex-wrap">
            {/* PDF Upload for extraction */}
            <input
              type="file"
              accept=".pdf"
              ref={pdfInputRef}
              onChange={handlePdfUpload}
              className="hidden"
            />
            <Button
              variant="default"
              onClick={() => pdfInputRef.current?.click()}
              disabled={isExtracting}
            >
              {isExtracting ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <FileImage className="h-4 w-4 mr-2" />
              )}
              {isExtracting ? "Extracting..." : "Extract from PDF"}
            </Button>

            {/* JSON File Upload */}
            <input
              type="file"
              accept=".json"
              ref={fileInputRef}
              onChange={handleFileUpload}
              className="hidden"
            />
            <Button
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={isExtracting}
            >
              <Upload className="h-4 w-4 mr-2" />
              Load JSON
            </Button>

            {/* Export */}
            <Button
              variant="outline"
              onClick={handleExport}
              disabled={!treeData || isExtracting}
            >
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>

            <div className="h-6 w-px bg-border" />

            {/* Expand/Collapse */}
            <Button variant="ghost" size="sm" onClick={expandAll} disabled={!treeData}>
              Expand All
            </Button>
            <Button variant="ghost" size="sm" onClick={collapseAll} disabled={!treeData}>
              Collapse All
            </Button>

            <div className="h-6 w-px bg-border" />

            {/* Undo */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleUndo}
              disabled={historyIndex <= 0}
            >
              <Undo2 className="h-4 w-4 mr-2" />
              Undo
            </Button>

            {/* Stats */}
            {treeData && (
              <div className="flex items-center gap-4 ml-auto text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Package className="h-4 w-4 text-blue-600" />
                  {assemblyCount} Assemblies
                </span>
                <span className="flex items-center gap-1">
                  <File className="h-4 w-4 text-gray-500" />
                  {detailCount} Details
                </span>
                <span>Total: {treeData.tree.length}</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Extraction Progress */}
      {isExtracting && (
        <Card className="border-blue-200 bg-blue-50 dark:bg-blue-950 dark:border-blue-900">
          <CardContent className="p-6">
            <div className="flex items-center gap-4">
              <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
              <div>
                <h3 className="font-semibold">Extracting Drawing Tree...</h3>
                <p className="text-sm text-muted-foreground">{extractionProgress}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  This may take 30-60 seconds depending on PDF complexity
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tree View */}
      {!treeData && !isExtracting ? (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <FolderTree className="h-16 w-16 mx-auto text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Drawing Tree Loaded</h3>
            <p className="text-muted-foreground mb-6">
              Extract from a Drawing Tree PDF or load an existing JSON file
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Button size="lg" onClick={() => pdfInputRef.current?.click()}>
                <FileImage className="h-5 w-5 mr-2" />
                Extract from PDF
              </Button>
              <Button variant="outline" size="lg" onClick={() => fileInputRef.current?.click()}>
                <FileJson className="h-5 w-5 mr-2" />
                Load JSON File
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-6">
              PDF extraction uses Claude Vision to analyze the drawing tree structure.
              <br />
              After extraction, review and correct any hierarchy errors before exporting.
            </p>
          </CardContent>
        </Card>
      ) : treeData ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-5 w-5" />
              {treeData.top_level}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground mb-4 bg-muted/50 p-3 rounded-lg">
              <strong>Tip:</strong> Drag any node and drop it onto another node
              to change its parent. The drop target will highlight in blue.
            </div>
            <div className="space-y-1">
              {rootNodes.map((node) => (
                <TreeNodeItem
                  key={node.drawing_number}
                  node={node}
                  children={childrenMap.get(node.drawing_number) || []}
                  childrenMap={childrenMap}
                  depth={0}
                  expandedNodes={expandedNodes}
                  toggleExpand={toggleExpand}
                  onDragStart={handleDragStart}
                  onDragOver={handleDragOver}
                  onDrop={handleDrop}
                  draggedNode={draggedNode}
                  dropTarget={dropTarget}
                  setDropTarget={setDropTarget}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* History Panel */}
      {history.length > 1 && (
        <Card>
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
