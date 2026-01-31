import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { AppSidebar } from '@/components/AppSidebar';
import { Menu } from 'lucide-react';

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full">
        <AppSidebar />
        <div className="flex-1 flex flex-col">
          {/* Mobile header with menu trigger */}
          <header className="md:hidden flex items-center gap-2 p-4 border-b border-border bg-background sticky top-0 z-10">
            <SidebarTrigger>
              <Menu className="h-5 w-5" />
            </SidebarTrigger>
            <span className="text-sm font-medium tracking-widest uppercase text-muted-foreground">
              MIRA V3
            </span>
          </header>
          <main className="flex-1 p-4 md:p-8 overflow-auto">
            <div className="max-w-4xl mx-auto animate-fade-in">
              {children}
            </div>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}
