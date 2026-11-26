import { ActionButton } from "@dotrix/ui/components/action-button";
import { ChatShowcase } from "@dotrix/ui/components/chat/chat-showcase";
import { Input } from "@dotrix/ui/components/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@dotrix/ui/components/tabs";
import { useState } from "react";

import { go } from "../core/nav";

const productExamples = [
  { route: "chat", label: "Chat", detail: "Sample conversations use Dotrix’s message renderer and shared model and action controls." },
  { route: "codes", label: "Code", detail: "Sample sessions show the shared action controls alongside Dotrix’s diff, files, and terminal views." },
  { route: "settings", label: "Settings", detail: "Workspace forms use shared inputs, selects, and buttons." },
] as const;

export default function DemoComponents() {
  const [filter, setFilter] = useState("");
  const matches = productExamples.filter(({ label, detail }) => `${label} ${detail}`.toLowerCase().includes(filter.trim().toLowerCase()));

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-5 px-4 py-6 sm:px-6">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold text-foreground">Components</h1>
        <p className="text-sm text-muted-foreground">Try the shared chat components and see where UI-SDK controls appear in Dotrix.</p>
      </header>
      <Tabs defaultValue="chat">
        <TabsList aria-label="Component examples">
          <TabsTrigger value="chat">Chat showcase</TabsTrigger>
          <TabsTrigger value="product">In Dotrix</TabsTrigger>
        </TabsList>
        <TabsContent value="chat" className="grid gap-3 py-2">
          <p className="text-sm text-muted-foreground">This sample uses the coss chat components ported to UI-SDK. Replies and reactions stay on this page.</p>
          <ChatShowcase />
        </TabsContent>
        <TabsContent value="product" className="grid gap-3 py-2">
          <p className="text-sm text-muted-foreground">These tabs, the filter input, and the navigation buttons use UI-SDK-backed components.</p>
          <Input
            className="max-w-sm"
            aria-label="Filter product examples"
            placeholder="Filter examples"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <ul className="grid gap-3 sm:grid-cols-3">
            {matches.map(({ route, label, detail }) => (
              <li key={route} className="grid content-between gap-4 rounded-xl border border-border bg-card p-4">
                <div>
                  <h2 className="font-medium">{label}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
                </div>
                <ActionButton className="btn btn-secondary w-fit" onClick={() => go(route)}>
                  Open {label}
                </ActionButton>
              </li>
            ))}
          </ul>
          {!matches.length && (
            <p className="text-sm text-muted-foreground" role="status">
              No matching examples.
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
