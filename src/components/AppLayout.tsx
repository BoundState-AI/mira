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
          {/* Mobile header */}
          <header
            className="md:hidden"
            style={{
              background: '#18181b',
              padding: '12px 16px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              borderBottom: '1px solid #3f3f46',
              position: 'sticky',
              top: 0,
              zIndex: 50
            }}
          >
            <SidebarTrigger />
            <span style={{ color: '#a1a1aa', fontSize: '11px', fontWeight: 500, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
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
