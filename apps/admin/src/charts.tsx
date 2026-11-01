// The Overview's charts: shadcn/ui charts (https://ui.shadcn.com/charts) on Recharts. Series colours
// are checked for colour-blind separation and contrast in both themes (--chart-ok, --chart-bad).
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@dotrix/ui/components/chart";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import type { Day } from "./api";
import { compact } from "./ui";

const day = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

const runsConfig = {
  finished: { label: "Finished or running", color: "var(--chart-ok)" },
  failed: { label: "Failed", color: "var(--chart-bad)" },
} satisfies ChartConfig;

/** Runs started each day, stacked: the ones that failed on top of the rest. */
export function RunsChart({ days }: { days: Day[] }) {
  const data = days.map((d) => ({
    day: d.day,
    finished: d.chat_runs + d.coding_runs - d.chat_failed - d.coding_failed,
    failed: d.chat_failed + d.coding_failed,
  }));
  return (
    <ChartContainer config={runsConfig} className="aspect-auto h-[220px] w-full">
      <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <defs>
          {(["finished", "failed"] as const).map((k) => (
            <linearGradient key={k} id={`fill-${k}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={`var(--color-${k})`} stopOpacity={0.32} />
              <stop offset="95%" stopColor={`var(--color-${k})`} stopOpacity={0.04} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} minTickGap={28} tickFormatter={day} />
        <YAxis tickLine={false} axisLine={false} width={36} allowDecimals={false} tickFormatter={compact} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="dot" labelFormatter={(_, p) => day(p?.[0]?.payload?.day ?? "")} />} />
        <Area
          isAnimationActive={false}
          dataKey="finished"
          type="monotone"
          stackId="runs"
          stroke="var(--color-finished)"
          strokeWidth={2}
          fill="url(#fill-finished)"
        />
        <Area isAnimationActive={false} dataKey="failed" type="monotone" stackId="runs" stroke="var(--color-failed)" strokeWidth={2} fill="url(#fill-failed)" />
        <ChartLegend content={<ChartLegendContent />} />
      </AreaChart>
    </ChartContainer>
  );
}

const tokensConfig = { tokens: { label: "Tokens", color: "var(--chart-ok)" } } satisfies ChartConfig;

/** Input and output tokens of the runs started each day. */
export function TokensChart({ days }: { days: Day[] }) {
  const data = days.map((d) => ({ day: d.day, tokens: d.input_tokens + d.output_tokens }));
  return (
    <ChartContainer config={tokensConfig} className="aspect-auto h-[220px] w-full">
      <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <defs>
          <linearGradient id="fill-tokens" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-tokens)" stopOpacity={0.32} />
            <stop offset="95%" stopColor="var(--color-tokens)" stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} minTickGap={28} tickFormatter={day} />
        <YAxis tickLine={false} axisLine={false} width={44} tickFormatter={compact} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="line" labelFormatter={(_, p) => day(p?.[0]?.payload?.day ?? "")} />} />
        <Area isAnimationActive={false} dataKey="tokens" type="monotone" stroke="var(--color-tokens)" strokeWidth={2} fill="url(#fill-tokens)" />
      </AreaChart>
    </ChartContainer>
  );
}

const signupsConfig = { signups: { label: "Sign-ups", color: "var(--chart-ok)" } } satisfies ChartConfig;

/** People who signed up each day: a count per day, so bars. */
export function SignupsChart({ days }: { days: Day[] }) {
  return (
    <ChartContainer config={signupsConfig} className="aspect-auto h-[160px] w-full">
      <BarChart data={days} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} minTickGap={28} tickFormatter={day} />
        <YAxis tickLine={false} axisLine={false} width={36} allowDecimals={false} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent hideIndicator labelFormatter={(_, p) => day(p?.[0]?.payload?.day ?? "")} />} />
        <Bar isAnimationActive={false} dataKey="signups" fill="var(--color-signups)" radius={[4, 4, 0, 0]} maxBarSize={24} />
      </BarChart>
    </ChartContainer>
  );
}
