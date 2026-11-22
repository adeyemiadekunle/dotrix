import { Toaster } from "@dotrix/ui/components/sonner";
import { TooltipProvider } from "@dotrix/ui/components/tooltip";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { queryClient } from "@/lib/queryClient";
import { StoreBridge } from "./shell/StoreBridge";

export function Providers({ children }: { children: ReactNode }) {
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
