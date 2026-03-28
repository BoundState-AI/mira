import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { TemporarilyUnavailableNotice } from "@/components/TemporarilyUnavailableModule";
import KnowledgeTwins from "./pages/KnowledgeTwins";
// import MIULBuilder from "./pages/MIULBuilder";  // Deprecated: replaced by V4 production builder
import MPPlanGenerator from "./pages/MPPlanGenerator";
import DTTreeEditor from "./pages/DTTreeEditor";
import MIULBuilderV4 from "./pages/MIULBuilderV4";
import MiraChat from "./pages/MiraChat";
import MiraV4Query from "./pages/MiraV4Query";
import BSMHQuery from "./pages/BSMHQuery";
import GasCompatibility from "./pages/GasCompatibility";
import GalvanicCompatibility from "./pages/GalvanicCompatibility";
import FractureControl from "./pages/FractureControl";
import OCAWorkbench from "./pages/OCAWorkbench";
import OCASystemBuilder from "./pages/OCASystemBuilder";
import NotFound from "./pages/NotFound";
import TOCR from "./pages/TOCR";

const queryClient = new QueryClient();

function InactiveModulePage({ moduleName }: { moduleName: string }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">
      <TemporarilyUnavailableNotice moduleName={moduleName} />
    </div>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <AuthProvider>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <ProtectedRoute>
            <AppLayout>
              <Routes>
                <Route path="/" element={<KnowledgeTwins />} />
                <Route path="/chat" element={<MiraChat />} />
                <Route
                  path="/query"
                  element={(
                    <BSMHQuery
                      endpoint="query"
                      isTemporarilyUnavailable
                      showPipelineBlurb
                    />
                  )}
                />
                <Route path="/gas-compatibility" element={<GasCompatibility />} />
                <Route path="/galvanic-compatibility" element={<GalvanicCompatibility />} />
                <Route path="/fracture-control" element={<FractureControl />} />
                <Route path="/oca" element={<Navigate to="/oca/workbench" replace />} />
                <Route path="/oca/workbench" element={<OCAWorkbench />} />
                <Route path="/oca/system-builder" element={<OCASystemBuilder />} />
                <Route
                  path="/test-classes"
                  element={<InactiveModulePage moduleName="MAPTIS Search" />}
                />
                <Route
                  path="/test-classes/:testType"
                  element={<InactiveModulePage moduleName="MAPTIS Search" />}
                />
                <Route
                  path="/miul"
                  element={(
                    <ProtectedRoute requireItar>
                      <MIULBuilderV4 />
                    </ProtectedRoute>
                  )}
                />
                <Route path="/mua" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua/v7" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua/v8" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua/v10" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua/matchmaker" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua/matchmaker/*" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/compliance" element={<Navigate to="/query" replace />} />
                <Route path="/mp-plan" element={<MPPlanGenerator />} />
                <Route
                  path="/dt-editor"
                  element={(
                    <ProtectedRoute requireItar>
                      <DTTreeEditor />
                    </ProtectedRoute>
                  )}
                />
                <Route path="/v4-query" element={<MiraV4Query />} />
                <Route path="/bsmh" element={<Navigate to="/query" replace />} />
                <Route path="/mua-v7" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua-v8" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/mua-v10" element={<InactiveModulePage moduleName="MUA Writer" />} />
                <Route path="/forge" element={<Navigate to="/" replace />} />
                <Route path="/forge-explorer" element={<Navigate to="/" replace />} />
                <Route path="/tocr" element={<TOCR />} />
                <Route path="/knowledge-twins" element={<Navigate to="/" replace />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </AppLayout>
          </ProtectedRoute>
        </BrowserRouter>
      </TooltipProvider>
    </AuthProvider>
  </QueryClientProvider>
);

export default App;
