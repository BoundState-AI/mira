import { useState, useEffect, useCallback, DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Droplet, FlaskConical, FileStack, FileCheck, MessageSquare, Brain, ShieldCheck, ClipboardList, FolderTree, GripVertical, RotateCcw, LucideIcon } from 'lucide-react';
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
  titleKey: string;
  url: string;
  icon: LucideIcon;
}

const DEFAULT_NAV_ITEMS: NavItem[] = [
  { id: 'mp-plan', titleKey: 'mpPlan', url: '/mp-plan', icon: ClipboardList },
  { id: 'query', titleKey: 'query', url: '/query', icon: MessageSquare },
  { id: 'test-classes', titleKey: 'testClasses', url: '/test-classes', icon: FlaskConical },
  { id: 'miul', titleKey: 'miulBuilder', url: '/miul', icon: FileStack },
  { id: 'dt-editor', titleKey: 'dtEditor', url: '/dt-editor', icon: FolderTree },
  { id: 'mua', titleKey: 'muaGenerator', url: '/mua', icon: FileCheck },
  { id: 'compliance', titleKey: 'compliance', url: '/compliance', icon: ShieldCheck },
  { id: 'gas-compatibility', titleKey: 'gasCompatibility', url: '/gas-compatibility', icon: Droplet },
  { id: 'knowledge-twins', titleKey: 'knowledgeTwins', url: '/', icon: Brain },
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
  const { t } = useTranslation('navigation');
  const { t: tCommon } = useTranslation('common');
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
            MIRA V3
          </span>
          <div className="flex items-center gap-1">
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
                <TooltipContent side="right">{tCommon('tooltips.resetOrder')}</TooltipContent>
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
                {isReorderMode ? tCommon('tooltips.doneReordering') : tCommon('tooltips.reorderMenu')}
              </TooltipContent>
            </Tooltip>
            <LanguageSelector />
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
                      <span>{t(item.titleKey)}</span>
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
