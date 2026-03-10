import { useState, useEffect, useCallback, DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { FlaskConical, FileStack, Brain, ClipboardList, FolderTree, GripVertical, RotateCcw, Zap, Sparkles, Wind, Shield, LayoutGrid, LucideIcon } from 'lucide-react';
import { NavLink } from '@/components/NavLink';
import { BoundStateLogo } from '@/components/BoundStateLogo';
import { LanguageSelector } from '@/components/LanguageSelector';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface NavItem {
  id: string;
  title: string;
  navKey: string;
  url: string;
  icon: LucideIcon;
}

const DEFAULT_NAV_ITEMS: NavItem[] = [
  { id: 'mp-plan', title: 'M&P Plan', navKey: 'mpPlan', url: '/mp-plan', icon: ClipboardList },
  { id: 'query', title: 'MIRA Query', navKey: 'query', url: '/query', icon: Zap },
  { id: 'gas-compatibility', title: 'Gas Compatibility', navKey: 'gasCompatibility', url: '/gas-compatibility', icon: Wind },
  { id: 'oca', title: 'OCA Workbench', navKey: 'ocaWorkbench', url: '/oca', icon: Shield },
  { id: 'oca-system', title: 'OCA System Builder', navKey: 'ocaSystemBuilder', url: '/oca/system-builder', icon: LayoutGrid },
  { id: 'test-classes', title: 'MAPTIS Search', navKey: 'testClasses', url: '/test-classes', icon: FlaskConical },
  { id: 'miul', title: 'MIUL Builder', navKey: 'miulBuilder', url: '/miul', icon: FileStack },
  { id: 'dt-editor', title: 'DT Editor', navKey: 'dtEditor', url: '/dt-editor', icon: FolderTree },
  { id: 'mua-v10', title: 'MUA Writer', navKey: 'muaV10', url: '/mua-v10', icon: Sparkles },
  { id: 'knowledge-twins', title: 'Knowledge Twins', navKey: 'knowledgeTwins', url: '/', icon: Brain },
];

const STORAGE_KEY = 'mira-sidebar-order';

function getOrderedItems(): NavItem[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const order: string[] = JSON.parse(stored);
      // Map stored order to items, filtering out any that no longer exist
      const itemMap = new Map(DEFAULT_NAV_ITEMS.map(item => [item.id, item]));
      const orderedItems = order
        .filter(id => itemMap.has(id))
        .map(id => itemMap.get(id)!);
      // Add any new items that weren't in stored order
      const orderedIds = new Set(order);
      for (const item of DEFAULT_NAV_ITEMS) {
        if (!orderedIds.has(item.id)) {
          orderedItems.push(item);
        }
      }
      return orderedItems;
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_NAV_ITEMS;
}

function saveOrder(items: NavItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.map(i => i.id)));
  } catch {
    // Ignore storage errors
  }
}

export function AppSidebar() {
  const { t } = useTranslation(['common', 'navigation']);
  const [items, setItems] = useState<NavItem[]>(DEFAULT_NAV_ITEMS);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dropTargetIndex, setDropTargetIndex] = useState<number | null>(null);
  const [isReorderMode, setIsReorderMode] = useState(false);

  // Load order from localStorage on mount
  useEffect(() => {
    setItems(getOrderedItems());
  }, []);

  const handleDragStart = useCallback((e: DragEvent, index: number) => {
    setDraggedIndex(index);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(index));
  }, []);

  const handleDragOver = useCallback((e: DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDropTargetIndex(index);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDropTargetIndex(null);
  }, []);

  const handleDrop = useCallback((e: DragEvent, targetIndex: number) => {
    e.preventDefault();
    setDropTargetIndex(null);

    if (draggedIndex === null || draggedIndex === targetIndex) {
      setDraggedIndex(null);
      return;
    }

    const newItems = [...items];
    const [removed] = newItems.splice(draggedIndex, 1);
    newItems.splice(targetIndex, 0, removed);

    setItems(newItems);
    saveOrder(newItems);
    setDraggedIndex(null);
  }, [draggedIndex, items]);

  const handleDragEnd = useCallback(() => {
    setDraggedIndex(null);
    setDropTargetIndex(null);
  }, []);

  const handleReset = useCallback(() => {
    setItems(DEFAULT_NAV_ITEMS);
    localStorage.removeItem(STORAGE_KEY);
    setIsReorderMode(false);
  }, []);

  const isCustomOrder = items.some((item, idx) => item.id !== DEFAULT_NAV_ITEMS[idx]?.id);

  return (
    <Sidebar className="border-r border-sidebar-border">
      <SidebarHeader className="p-6 border-b border-sidebar-border">
        <div className="flex items-center justify-between">
          <span className="text-sidebar-primary font-medium tracking-widest uppercase text-[10px]">
            {t('appName', { ns: 'common', defaultValue: 'MIRA V3' })}
          </span>
          <div className="flex items-center gap-1">
            <LanguageSelector />
            {isCustomOrder && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-sidebar-foreground/50 hover:text-sidebar-foreground"
                    onClick={handleReset}
                  >
                    <RotateCcw className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {t('tooltips.resetOrder', { ns: 'common', defaultValue: 'Reset menu order' })}
                </TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={`h-6 w-6 transition-colors ${
                    isReorderMode
                      ? 'text-primary bg-primary/10'
                      : 'text-sidebar-foreground/50 hover:text-sidebar-foreground'
                  }`}
                  onClick={() => setIsReorderMode(!isReorderMode)}
                >
                  <GripVertical className="h-3 w-3" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {isReorderMode
                  ? t('tooltips.doneReordering', { ns: 'common', defaultValue: 'Done reordering' })
                  : t('tooltips.reorderMenu', { ns: 'common', defaultValue: 'Reorder menu items' })}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="p-4">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu className="space-y-1">
              {items.map((item, index) => (
                <SidebarMenuItem
                  key={item.id}
                  draggable={isReorderMode}
                  onDragStart={(e) => isReorderMode && handleDragStart(e, index)}
                  onDragOver={(e) => isReorderMode && handleDragOver(e, index)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => isReorderMode && handleDrop(e, index)}
                  onDragEnd={handleDragEnd}
                  className={`
                    transition-all duration-150
                    ${isReorderMode ? 'cursor-grab active:cursor-grabbing' : ''}
                    ${draggedIndex === index ? 'opacity-50' : ''}
                    ${dropTargetIndex === index && draggedIndex !== index
                      ? 'ring-2 ring-primary ring-offset-1 ring-offset-sidebar rounded-md'
                      : ''
                    }
                  `}
                >
                  <SidebarMenuButton asChild>
                    <NavLink
                      to={item.url}
                      end={item.url === '/'}
                      className={`
                        flex items-center gap-3 px-3 py-2.5 rounded-md
                        text-sidebar-foreground/80 hover:text-sidebar-foreground
                        hover:bg-sidebar-accent transition-colors
                        ${isReorderMode ? 'pointer-events-none' : ''}
                      `}
                      activeClassName="bg-sidebar-accent text-sidebar-foreground font-medium"
                    >
                      {isReorderMode && (
                        <GripVertical className="h-4 w-4 text-sidebar-foreground/40 flex-shrink-0 -ml-1" />
                      )}
                      <item.icon className="h-4 w-4" />
                      <span>
                        {t(item.navKey, { ns: 'navigation', defaultValue: item.title })}
                      </span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-4 border-t border-sidebar-border">
        <BoundStateLogo variant="full" theme="dark" size="sm" />
      </SidebarFooter>
    </Sidebar>
  );
}
