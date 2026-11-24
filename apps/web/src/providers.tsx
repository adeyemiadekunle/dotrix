import { Toaster } from "@dotrix/ui/components/sonner";
import { TooltipProvider } from "@dotrix/ui/components/tooltip";
import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { initUiAgentBridge } from "@/src/core/uiAgent";
import { queryClient } from "@/lib/queryClient";
import { StoreBridge } from "./shell/StoreBridge";

export function Providers({ children }: { children: ReactNode }) {
  useEffect(() => initUiAgentBridge(), []);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        {children}
        <StoreBridge />
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
