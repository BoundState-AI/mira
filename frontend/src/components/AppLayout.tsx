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
        <main className="flex-1 overflow-auto">
          <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur md:hidden">
            <SidebarTrigger className="h-9 w-9" />
            <span className="text-sm font-medium">Menu</span>
          </div>
          <div className="p-4 md:p-8">
            <div className="max-w-4xl animate-fade-in lg:ml-24 lg:mr-auto">
              {children}
            </div>
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
