import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { AppSidebar } from '@/components/AppSidebar';

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full">
        <AppSidebar />
        <div className="flex-1 flex flex-col min-w-0">
          {/* Mobile header with menu trigger - visible on all screens for debugging */}
          <header className="flex items-center gap-2 p-4 border-b border-zinc-700 bg-zinc-900 sticky top-0 z-50">
            <SidebarTrigger className="text-white" />
            <span className="text-sm font-medium tracking-widest uppercase text-zinc-400">
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
