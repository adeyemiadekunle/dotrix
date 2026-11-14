import { Input as DesignInput } from "@dotrix/ui/components/input";
import { useState, type ReactNode } from "react";
import { Card, ComplexSelector, RadioList, RadioListItem } from "@dotrix/ui/astryx";

export interface Choice {
  id: string;
  label: string;
  icon: ReactNode;
  on: boolean;
  group?: string; // a heading in the full list: "This computer", "Cloud"
  note?: string; // shown faint on the right: "Not ready", "Off"
  tip?: string;
  disabled?: boolean;
  onPick: () => void;
}

export function ChoiceCard({ label, choices, extra }: { label: string; choices: Choice[]; extra?: (close: () => void) => ReactNode }) {
  const [query, setQuery] = useState("");
  const selected = choices.find((choice) => choice.on);
  const first = choices.slice(0, 3);
  const shown = selected && !first.includes(selected) ? [...first.slice(0, 2), selected] : first;
  const pick = (id: string) => choices.find((choice) => choice.id === id && !choice.disabled)?.onPick();
  const row = (choice: Choice) => (
    <RadioListItem
      key={choice.id}
      value={choice.id}
      label={choice.label}
      description={choice.tip}
      isDisabled={choice.disabled}
      endContent={choice.note ?? choice.icon}
    />
  );
  return (
    <Card padding={3} className="dotrix-choice-card">
      <RadioList label={label} isLabelHidden value={selected?.id ?? ""} onChange={pick}>
        {shown.map(row)}
      </RadioList>
      {(choices.length > shown.length || extra) && (
        <ComplexSelector
          label={label}
          isLabelHidden
          value={selected?.id ?? ""}
          triggerLabel={`More ${label.toLowerCase()}`}
          onChange={pick}
          onOpenChange={() => setQuery("")}
        >
          {(value, change, close) => (
            <div style={{ padding: 12, minWidth: 240 }}>
              {choices.length > 6 && (
                <DesignInput className="input" placeholder="Search…" aria-label={`Search: ${label}`} value={query} onChange={(e) => setQuery(e.target.value)} />
              )}
              <RadioList
                label={label}
                isLabelHidden
                value={value}
                onChange={(id) => {
                  change(id);
                  close();
                }}
              >
                {choices.filter((choice) => choice.label.toLowerCase().includes(query.toLowerCase())).map(row)}
              </RadioList>
              {extra?.(close)}
            </div>
          )}
        </ComplexSelector>
      )}
    </Card>
  );
}
