import { agentTools, createAgent, registerTools } from "@ui-sdk/react/agent";

const uiAgent = createAgent({
  allow: (step) => {
    if (!step.confirm) return true;
    return typeof window !== "undefined" ? window.confirm(step.confirm) : false;
  },
});

declare global {
  interface Window {
    __dotrixAgent?: typeof uiAgent;
  }
}

function initUiAgentBridge(): () => void {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return () => {};
  }

  // uiAgent's own allow callback already prompts for step.confirm.
  const unregister = registerTools(uiAgent, { allow: () => true });

  if (import.meta.env.DEV) {
    window.__dotrixAgent = uiAgent;
  }

  return () => {
    unregister();
    if (import.meta.env.DEV && window.__dotrixAgent === uiAgent) {
      delete window.__dotrixAgent;
    }
  };
}

export { agentTools, initUiAgentBridge, uiAgent };
