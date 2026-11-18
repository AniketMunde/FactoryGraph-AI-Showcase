"use client";
import { useMemo, useState } from "react";
import {
  createColumnHelper,
  createPaginatedRowModel,
  createSortedRowModel,
  flexRender,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import {
  ArrowDownUp,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import type { Machine, CaseReport } from "@/lib/contracts";
import { latestEvent, percent, policy, utc } from "@/lib/presentation";
import { Badge, Button, Empty } from "./ui";
type Row = Machine & { report?: CaseReport };
const features = tableFeatures({
  rowSortingFeature,
  rowPaginationFeature,
  sortedRowModel: createSortedRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  sortFns: { basic: sortFn_basic, text: sortFn_text },
});
const helper = createColumnHelper<typeof features, Row>();
export function AssetTable({
  machines,
  reports,
  open,
}: {
  machines: Machine[];
  reports: CaseReport[];
  open: (id: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const [ids, setIds] = useState("");
  const data = useMemo(
    () =>
      machines
        .map((m) => ({ ...m, report: reports.find((r) => r.request.machine_id === m.machine_id) }))
        .filter(
          (m) =>
            `${m.machine_id} ${m.model}`.toLowerCase().includes(search.toLowerCase()) &&
            (state === "all" || policy(m.report).key === state) &&
            (!ids.trim() ||
              ids
                .split(",")
                .map((s) => s.trim())
                .includes(String(m.machine_id))),
        ),
    [machines, reports, search, state, ids],
  );
  const columns = useMemo(
    () =>
      helper.columns([
        helper.accessor("machine_id", {
          header: "Machine",
          sortFn: "basic",
          cell: (c) => (
            <button className="asset-link" onClick={() => open(c.row.original.machine_id)}>
              <span className="machine-glyph">M</span>
              <span>Machine {String(c.getValue()).padStart(2, "0")}</span>
            </button>
          ),
        }),
        helper.accessor("model", {
          header: "Recorded model",
          sortFn: "text",
          cell: (c) => <span className="model-code">{c.getValue()}</span>,
        }),
        helper.accessor((r) => r.report?.prediction.probability ?? -1, {
          id: "probability",
          header: "24h failure estimate",
          sortFn: "basic",
          cell: (c) => (
            <span
              className="tabular probability"
              title={String(c.row.original.report?.prediction.probability ?? "No replay result")}
            >
              {c.getValue() < 0 ? <span className="muted">—</span> : percent(c.getValue(), 4)}
            </span>
          ),
        }),
        helper.accessor((r) => policy(r.report).label, {
          id: "policy",
          header: "Frozen policy state",
          sortFn: "text",
          cell: (c) => <Badge tone={policy(c.row.original.report).tone}>{c.getValue()}</Badge>,
        }),
        helper.accessor((r) => r.report?.historical_evidence.status ?? "Not requested", {
          id: "evidence",
          header: "Historical evidence",
          sortFn: "text",
          cell: (c) => (
            <span className="evidence-label">
              <span className={c.getValue() === "verified" ? "verified-dot" : "unverified-dot"} />
              {c.getValue() === "verified" ? "Source verified" : c.getValue()}
            </span>
          ),
        }),
        helper.accessor((r) => latestEvent(r.report)?.event_timestamp ?? "", {
          id: "event",
          header: "Latest visible event",
          sortFn: "text",
          cell: (c) =>
            c.getValue() ? (
              <span className="small tabular">{utc(c.getValue(), true)}</span>
            ) : (
              <span className="muted">—</span>
            ),
        }),
        helper.display({
          id: "action",
          header: "",
          cell: (c) => (
            <Button
              variant="ghost"
              onClick={() => open(c.row.original.machine_id)}
              aria-label={`Investigate Machine ${c.row.original.machine_id}`}
            >
              <span>Investigate</span>
              <ArrowUpRight size={15} />
            </Button>
          ),
        }),
      ]),
    [open],
  );
  const table = useTable({
    features,
    columns,
    data,
    initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
  });
  return (
    <>
      <div className="table-toolbar">
        <div className="search-input">
          <Search size={16} />
          <input
            aria-label="Search machines"
            placeholder="Search machine ID or model…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              table.setPageIndex(0);
            }}
          />
        </div>
        <label className="filter-control">
          <SlidersHorizontal size={15} />
          <select
            aria-label="Filter policy state"
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              table.setPageIndex(0);
            }}
          >
            <option value="all">All policy states</option>
            <option value="alert">New policy alert</option>
            <option value="cooldown">Cooldown suppressed</option>
            <option value="below">Below threshold</option>
            <option value="evidence">Evidence only</option>
            <option value="unscored">Not replayed</option>
          </select>
        </label>
        <input
          className="id-filter"
          aria-label="Filter permitted machine IDs"
          placeholder="IDs, e.g. 1, 17"
          value={ids}
          onChange={(e) => {
            setIds(e.target.value);
            table.setPageIndex(0);
          }}
        />
      </div>
      <div className="table-scroll">
        <table className="asset-table">
          <caption className="sr-only">
            Authorized machines at the selected historical replay. Unscored machines have no
            inferred equipment status.
          </caption>
          <thead>
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                {g.headers.map((h) => (
                  <th
                    key={h.id}
                    scope="col"
                    aria-sort={
                      h.column.getIsSorted() === "asc"
                        ? "ascending"
                        : h.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    {h.column.getCanSort() ? (
                      <button onClick={() => h.column.toggleSorting()}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <ArrowDownUp size={12} />
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getAllCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data.length && (
        <Empty title="No machines match">Adjust the filters within your authorized scope.</Empty>
      )}
      <footer className="table-footer">
        <span>
          {data.length} authorized matches · {reports.length} replay reports available
        </span>
        <div>
          <span>
            Page {table.state.pagination.pageIndex + 1} of {Math.max(1, table.getPageCount())}
          </span>
          <Button
            aria-label="Previous asset page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronLeft size={15} />
          </Button>
          <Button
            aria-label="Next asset page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronRight size={15} />
          </Button>
        </div>
      </footer>
    </>
  );
}
