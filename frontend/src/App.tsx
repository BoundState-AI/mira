import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import KnowledgeTwins from "./pages/KnowledgeTwins";
import TestClasses from "./pages/TestClasses";
import TestClassDetail from "./pages/TestClassDetail";
// import MIULBuilder from "./pages/MIULBuilder";  // Deprecated: replaced by V4 production builder
import MPPlanGenerator from "./pages/MPPlanGenerator";
import DTTreeEditor from "./pages/DTTreeEditor";
import MIULBuilderV4 from "./pages/MIULBuilderV4";
import MiraV4Query from "./pages/MiraV4Query";
import BSMHQuery from "./pages/BSMHQuery";
import MUAV10 from "./pages/MUAV10";
import GasCompatibility from "./pages/GasCompatibility";
import OCAWorkbench from "./pages/OCAWorkbench";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

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
                <Route
                  path="/query"
                  element={(
                    <BSMHQuery
                      endpoint="query"
                      showPipelineBlurb
                    />
                  )}
                />
                <Route path="/gas-compatibility" element={<GasCompatibility />} />
                <Route path="/oca" element={<OCAWorkbench />} />
                <Route path="/test-classes" element={<TestClasses />} />
                <Route path="/test-classes/:testType" element={<TestClassDetail />} />
                <Route
                  path="/miul"
                  element={(
                    <ProtectedRoute requireItar>
                      <MIULBuilderV4 />
                    </ProtectedRoute>
                  )}
                />
                <Route path="/mua" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua/v7" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua/v8" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua/v10" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua/matchmaker" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua/matchmaker/*" element={<Navigate to="/mua-v10" replace />} />
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
                <Route path="/mua-v7" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua-v8" element={<Navigate to="/mua-v10" replace />} />
                <Route path="/mua-v10" element={<MUAV10 />} />
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
