import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { AppSidebar } from '@/components/AppSidebar';
import { MiraChatDock } from '@/components/mira/MiraChatDock';
import { UsageAnalyticsTracker } from '@/components/analytics/UsageAnalyticsTracker';
import { useLocation } from 'react-router-dom';

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const location = useLocation();
  const isWideWorkspace = location.pathname === '/chat';
  const isLanding = location.pathname === '/';

  if (isLanding) {
    return <main className="min-h-screen w-full">{children}</main>;
  }

  return (
    <SidebarProvider>
      <UsageAnalyticsTracker />
      <div className="min-h-screen flex w-full">
        <AppSidebar />
        <main className="flex-1 overflow-auto">
          <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur md:hidden">
            <SidebarTrigger className="h-9 w-9" />
            <span className="text-sm font-medium">Menu</span>
          </div>
          <div className="p-4 md:p-8">
            <div
              className={[
                'w-full animate-fade-in',
                isWideWorkspace
                  ? 'max-w-[min(110rem,calc(100vw-5rem))] lg:ml-6 lg:mr-0'
                  : 'max-w-4xl lg:ml-12 lg:mr-auto',
              ].join(' ')}
            >
              {children}
            </div>
          </div>
          <MiraChatDock />
        </main>
      </div>
    </SidebarProvider>
  );
}
