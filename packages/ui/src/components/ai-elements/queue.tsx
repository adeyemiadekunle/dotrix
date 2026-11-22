"use client";

import * as React from "react";
import { CircleCheckIcon, CircleDashedIcon, CircleIcon, ListChecksIcon, ListIcon } from "lucide-react";

import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type QueueTodoStatus = "pending" | "in_progress" | "completed";

export type QueueTodo = {
  id?: string;
  content: string;
  status: QueueTodoStatus;
  description?: React.ReactNode;
};

function TodoIcon({ status }: { status: QueueTodoStatus }) {
  if (status === "completed") return <CircleCheckIcon />;
  if (status === "in_progress") return <CircleDashedIcon />;
  return <CircleIcon />;
}

function TodoRow({ todo, streaming }: { todo: QueueTodo; streaming: boolean }) {
  const line = (
    <TraceLine status={streaming && todo.status === "in_progress" ? "running" : undefined}>
      <TraceIcon>
        <TodoIcon status={todo.status} />
      </TraceIcon>
      <TraceTitle>{todo.content}</TraceTitle>
    </TraceLine>
  );

  if (!todo.description) return line;

  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>{todo.description}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

function TodoSection({
  title,
  icon,
  todos,
  streaming,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ReactNode;
  todos: QueueTodo[];
  streaming: boolean;
  defaultOpen?: boolean;
}) {
  if (todos.length === 0) return null;
  return (
    <TraceCollapsible defaultOpen={defaultOpen}>
      <TraceCollapsibleTrigger>
        <TraceLine>
          <TraceIcon>{icon}</TraceIcon>
          <TraceTitle>{title}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {todos.map((todo) => (
            <TodoRow key={todo.id ?? todo.content} todo={todo} streaming={streaming} />
          ))}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * The agent's todo list as two sections, "to do" and "completed", each todo with a status
 * icon (shadcn/ui AI Elements Queue, built on Trace).
 */
function Queue({ todos, streaming = false, className }: { todos: QueueTodo[]; streaming?: boolean; className?: string }) {
  const pending = todos.filter((todo) => todo.status !== "completed");
  const completed = todos.filter((todo) => todo.status === "completed");
  if (todos.length === 0) return null;
  return (
    <Trace className={cn("max-w-md", className)}>
      <TodoSection title={`${pending.length} to do`} icon={<ListIcon />} todos={pending} streaming={streaming} />
      <TodoSection title={`${completed.length} completed`} icon={<ListChecksIcon />} todos={completed} streaming={streaming} defaultOpen={false} />
    </Trace>
  );
}

export { Queue };
