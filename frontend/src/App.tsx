import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import KnowledgeTwins from "./pages/KnowledgeTwins";
import TestClasses from "./pages/TestClasses";
import TestClassDetail from "./pages/TestClassDetail";
// import MIULBuilder from "./pages/MIULBuilder";  // Deprecated: replaced by V4 production builder
import MPPlanGenerator from "./pages/MPPlanGenerator";
import DTTreeEditor from "./pages/DTTreeEditor";
import MIULBuilderV4 from "./pages/MIULBuilderV4";
import MiraV4Query from "./pages/MiraV4Query";
import BSMHQuery from "./pages/BSMHQuery";
import MUAWizardV7 from "./pages/MUAWizardV7";
import MUAMatchmaker from "./pages/MUAMatchmaker";
import GasCompatibility from "./pages/GasCompatibility";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AppLayout>
          <Routes>
            <Route path="/" element={<KnowledgeTwins />} />
            <Route
              path="/query"
              element={
                <BSMHQuery
                  endpoint="query"
                  showPipelineBlurb
                />
              }
            />
            <Route path="/gas-compatibility" element={<GasCompatibility />} />
            <Route path="/test-classes" element={<TestClasses />} />
            <Route path="/test-classes/:testType" element={<TestClassDetail />} />
            <Route path="/miul" element={<MIULBuilderV4 />} />
            <Route path="/mua" element={<Navigate to="/mua-v8" replace />} />
            <Route path="/compliance" element={<Navigate to="/query" replace />} />
            <Route path="/mp-plan" element={<MPPlanGenerator />} />
            <Route path="/dt-editor" element={<DTTreeEditor />} />
            <Route path="/v4-query" element={<MiraV4Query />} />
            <Route path="/bsmh" element={<Navigate to="/query" replace />} />
            <Route path="/mua-v7" element={<MUAWizardV7 />} />
            <Route path="/mua-v8" element={<MUAMatchmaker />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppLayout>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
