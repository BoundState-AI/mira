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
          {/* Mobile header - DEBUG: bright red background */}
          <header style={{ background: 'red', padding: '20px', position: 'relative', zIndex: 9999 }}>
            <SidebarTrigger className="text-white" />
            <span style={{ color: 'white', fontWeight: 'bold' }}>
              MIRA V3 - DEBUG HEADER
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
