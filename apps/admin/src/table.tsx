// Tables with pages: TanStack Table on shadcn's table and pagination. Server-paged when given a
// `total` (runs, the audit log: the API returns one page and how many match), otherwise paged and
// sorted here (workspaces, failures).
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@dotrix/ui/components/table";
import {
  Pagination,
  PaginationButton,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@dotrix/ui/components/pagination";
import { CaretDownIcon, CaretUpDownIcon, CaretUpIcon } from "@phosphor-icons/react";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table";
import { Fragment, useState, type ReactNode } from "react";

export const PAGE_SIZES = [25, 50, 100];

type Align = { align?: "right" };

export type Column<T> = ColumnDef<T> & { meta?: Align };

export function DataTable<T>({
  columns,
  data,
  total,
  pagination,
  onPagination,
  loading,
  empty = "Nothing here.",
  rowKey,
  detail,
  initialSort,
}: {
  columns: Column<T>[];
  data: T[];
  /** The server's count of matching rows: pages come from the server. */
  total?: number;
  pagination?: PaginationState;
  onPagination?: (p: PaginationState) => void;
  loading?: boolean;
  empty?: ReactNode;
  rowKey: (row: T) => string;
  /** What a row shows when opened; rows without one don't open. */
  detail?: (row: T) => ReactNode | null;
  initialSort?: SortingState;
}) {
  const server = total !== undefined;
  const [local, setLocal] = useState<PaginationState>({ pageIndex: 0, pageSize: PAGE_SIZES[0] });
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [open, setOpen] = useState<string | null>(null);
  const page = server ? pagination! : local;

  const table = useReactTable({
    data,
    columns,
    getRowId: rowKey,
    state: { pagination: page, sorting },
    onSortingChange: setSorting,
    onPaginationChange: (u) => {
      const next = typeof u === "function" ? u(page) : u;
      setOpen(null);
      if (server) onPagination?.(next);
      else setLocal(next);
    },
    getCoreRowModel: getCoreRowModel(),
    ...(server
      ? { manualPagination: true, manualSorting: true, enableSorting: false, rowCount: total }
      : { getPaginationRowModel: getPaginationRowModel(), getSortedRowModel: getSortedRowModel() }),
  });

  const count = server ? total : data.length;
  const rows = table.getRowModel().rows;
  const from = count ? page.pageIndex * page.pageSize + 1 : 0;
  const to = Math.min(count, (page.pageIndex + 1) * page.pageSize);

  return (
    <div className={`dt${loading ? " loading" : ""}`}>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => {
                const right = (header.column.columnDef.meta as Align | undefined)?.align === "right";
                const sort = header.column.getCanSort() ? header.column.getIsSorted() : null;
                return (
                  <TableHead
                    key={header.id}
                    className={right ? "text-right" : undefined}
                    aria-sort={sort === "asc" ? "ascending" : sort === "desc" ? "descending" : undefined}
                  >
                    {header.isPlaceholder ? null : sort !== null ? (
                      <button type="button" className={`dt-sort${right ? " r" : ""}`} onClick={header.column.getToggleSortingHandler()}>
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sort === "asc" ? (
                          <CaretUpIcon size={12} />
                        ) : sort === "desc" ? (
                          <CaretDownIcon size={12} />
                        ) : (
                          <CaretUpDownIcon size={12} className="dt-idle" />
                        )}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {rows.length ? (
            rows.map((row) => {
              const more = detail?.(row.original);
              const isOpen = open === row.id && !!more;
              return (
                <Fragment key={row.id}>
                  <TableRow
                    data-state={isOpen ? "selected" : undefined}
                    className={more ? "cursor-pointer" : undefined}
                    onClick={more ? () => setOpen(isOpen ? null : row.id) : undefined}
                    aria-expanded={more ? isOpen : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        className={(cell.column.columnDef.meta as Align | undefined)?.align === "right" ? "text-right tabular-nums" : undefined}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                  {isOpen && (
                    <TableRow className="dt-detail hover:bg-transparent">
                      <TableCell colSpan={row.getVisibleCells().length}>{more}</TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })
          ) : (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="dt-empty">
                {loading ? "Loading…" : empty}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {count > PAGE_SIZES[0] || page.pageIndex > 0 ? (
        <div className="dt-foot">
          <span className="dt-count">
            {from.toLocaleString()}–{to.toLocaleString()} of {count.toLocaleString()}
          </span>
          <label className="dt-size">
            Rows
            <select className="input" value={page.pageSize} onChange={(e) => table.setPagination({ pageIndex: 0, pageSize: Number(e.target.value) })}>
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <Pages index={page.pageIndex} count={table.getPageCount()} go={(i) => table.setPageIndex(i)} />
        </div>
      ) : null}
    </div>
  );
}

/** Previous, the first and last pages, the pages around this one, and Next. */
function Pages({ index, count, go }: { index: number; count: number; go: (i: number) => void }) {
  const shown = new Set([0, count - 1, index - 1, index, index + 1].filter((i) => i >= 0 && i < count));
  const list = [...shown].sort((a, b) => a - b);
  return (
    <Pagination className="dt-pages">
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious disabled={index === 0} onClick={() => go(index - 1)} />
        </PaginationItem>
        {list.map((i, n) => (
          <Fragment key={i}>
            {n > 0 && i - list[n - 1] > 1 && (
              <PaginationItem>
                <PaginationEllipsis />
              </PaginationItem>
            )}
            <PaginationItem>
              <PaginationButton isActive={i === index} onClick={() => go(i)} aria-label={`Page ${i + 1}`}>
                {i + 1}
              </PaginationButton>
            </PaginationItem>
          </Fragment>
        ))}
        <PaginationItem>
          <PaginationNext disabled={index >= count - 1} onClick={() => go(index + 1)} />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
