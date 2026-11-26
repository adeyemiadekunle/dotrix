import { ChatShowcase } from "@dotrix/ui/components/chat/chat-showcase";
import { SelectField } from "@dotrix/ui/components/select";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { call, type Day } from "./api";
import { RunsChart } from "./charts";
import { Card, Failed, Loading, PageHead } from "./ui";

const windows = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
];

export default function DemoComponents() {
  const [days, setDays] = useState("7");
  const trends = useQuery({ queryKey: ["trends", Number(days)], queryFn: () => call<Day[]>(`/admin/observe/trends?days=${days}`) });

  return (
    <>
      <PageHead title="Components" sub="Explore the admin dashboard controls and try the shared chat components with sample data." />
      <Card title="In the admin console">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <p className="max-w-prose text-sm text-muted-foreground">
            The shared UI-SDK select changes the range of the same chart used in{" "}
            <a className="link" href="#/overview">
              Overview
            </a>
            . Open{" "}
            <a className="link" href="#/runs">
              Runs
            </a>{" "}
            to try the shared table and pagination.
          </p>
          <SelectField aria-label="Sample chart range" value={days} options={windows} onValueChange={setDays} />
        </div>
        {trends.isError ? <Failed error={trends.error} /> : trends.data ? <RunsChart days={trends.data} /> : <Loading />}
      </Card>
      <section aria-label="Chat showcase" className="grid gap-3">
        <div>
          <h2 className="text-lg font-semibold">Chat showcase</h2>
          <p className="text-sm text-muted-foreground">
            The admin console includes this interactive gallery to preview Dotrix’s shared chat components. Replies and reactions stay on this page.
          </p>
        </div>
        <ChatShowcase />
      </section>
    </>
  );
}
