"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/client";
import type { components } from "@/lib/api.generated";

type Summary = components["schemas"]["CampaignSummary"];
type Detail = components["schemas"]["CampaignDetail"];

export default function CampaignResults({
  report,
}: {
  report: (e: unknown) => void;
}) {
  const [campaigns, setCampaigns] = useState<Summary[] | null>(null);
  const [selected, setSelected] = useState("legacy");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setRevision((v) => v + 1), 30000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    Promise.all([
      api<Summary[]>("/evaluations/campaigns", { signal: controller.signal }),
      api<Detail>(`/evaluations/campaigns/${selected}`, {
        signal: controller.signal,
      }),
    ])
      .then(([list, value]) => {
        setCampaigns(list);
        setDetail(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(true);
          if (e instanceof ApiError && e.status === 401) report(e);
        }
      });
    return () => controller.abort();
  }, [selected, revision, report]);
  const score = (value: number | undefined) =>
    value === undefined ? "Pending" : value.toFixed(4);
  const isolated = campaigns?.filter((c) => c.id !== "legacy") ?? [];
  return (
    <section
      className="panel evaluation-panel campaign-panel"
      aria-labelledby="campaign-heading"
    >
      <div className="section-bar">
        <h2 id="campaign-heading">Live answer-quality campaigns</h2>
        <button
          className="button secondary"
          onClick={() => setRevision((v) => v + 1)}
        >
          Refresh campaigns
        </button>
      </div>
      <p>
        Isolated comparisons: {isolated.reduce((n, c) => n + c.completed, 0)} /
        148 scored cases. The historical campaign is reported separately.
      </p>
      {error ? (
        <div role="alert">
          <p>
            Campaign results could not be loaded. Previously displayed values
            may be stale.
          </p>
          <button
            className="button secondary"
            onClick={() => setRevision((v) => v + 1)}
          >
            Retry campaign results
          </button>
        </div>
      ) : !campaigns ? (
        <p role="status">Loading live evaluation results…</p>
      ) : (
        <>
          <label htmlFor="campaign-select">Campaign</label>
          <select
            id="campaign-select"
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setDetail(null);
            }}
          >
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id === "legacy" ? "Historical campaign" : c.mode} ·{" "}
                {c.completed}/{c.requested} · {c.status}
              </option>
            ))}
          </select>
          {!detail ? (
            <p role="status">Loading selected campaign…</p>
          ) : (
            <>
              <p role="status">
                {detail.status} · {detail.completed}/{detail.requested} fully
                scored · {detail.provider} / {detail.model}
              </p>
              {detail.configuration && (
                <details>
                  <summary>Inspect frozen protocol</summary>
                  <pre className="campaign-passage">
                    {JSON.stringify(detail.configuration, null, 2)}
                  </pre>
                </details>
              )}
              {detail.next_retry_at && (
                <p>
                  Free quota wait. Next eligible retry:{" "}
                  <time dateTime={detail.next_retry_at}>
                    {new Date(detail.next_retry_at).toLocaleString()}
                  </time>
                  . No provider switch is made.
                </p>
              )}
              {detail.stopped_reason && (
                <p>Last stop: {detail.stopped_reason}</p>
              )}
              {(detail.limitations ?? []).map((text) => (
                <p key={text} className="muted small-text">
                  {text}
                </p>
              ))}
              {detail.provenance_gaps > 0 && (
                <p>
                  {detail.provenance_gaps} historical metric records lack
                  original judge RPC identifiers.
                </p>
              )}
              {detail.completed > 0 && (
                <p>
                  Completed-case means — context precision:{" "}
                  {score(detail.means?.context_precision)} · context recall:{" "}
                  {score(detail.means?.context_recall)} · faithfulness:{" "}
                  {score(detail.means?.faithfulness)}. Partial means are not a
                  complete benchmark.
                </p>
              )}
              {detail.rows.length === 0 ? (
                <p>
                  No scored answers yet. The free campaign preserves checkpoints
                  and resumes within its configured limits.
                </p>
              ) : (
                detail.rows.map((row) => (
                  <details key={row.case_id} className="campaign-case">
                    <summary>
                      {row.case_id} · precision{" "}
                      {score(row.metrics.context_precision)} · recall{" "}
                      {score(row.metrics.context_recall)} · faithfulness{" "}
                      {score(row.metrics.faithfulness)}
                    </summary>
                    {row.answer_kind && <p>Answer type: {row.answer_kind}</p>}
                    {row.question && <h3>{row.question}</h3>}
                    <h3>Recorded answer</h3>
                    <p className="campaign-passage">{row.response}</p>
                    <h3>Retrieved passages</h3>
                    {row.contexts.map((text, index) => (
                      <p className="campaign-passage" key={index}>
                        [{index + 1}] {text}
                      </p>
                    ))}
                    {row.response_sha256 && (
                      <p className="small-text campaign-hash">
                        Answer SHA-256: {row.response_sha256}
                      </p>
                    )}
                    <details>
                      <summary>Inspect metric provenance</summary>
                      <pre className="campaign-passage">
                        {JSON.stringify(
                          row.metric_configuration ?? {},
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </details>
                ))
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
