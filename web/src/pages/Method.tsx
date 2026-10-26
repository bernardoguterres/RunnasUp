import { api } from "../api/client";
import { ErrorState, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";
import { DataTable } from "../components/DataTable";

function MmrMethodSection() {
  const m = useApi((s) => api.mmrMethod(s), []);
  if (m.error) return <ErrorState error={m.error} onRetry={m.reload} title="Could not load the Running MMR method" />;
  if (!m.data) return <Loading />;
  const d = m.data;
  const calc = d.meaning.filter((x) => x.startsWith("Points:") || x.includes("Riegel"));
  const overview = d.meaning.filter((x) => !calc.includes(x));
  const scale = d.params.scale as { zero_t10_s: number; top_t10_s: number; top_points: number } | undefined;
  const ex = d.scale_examples.find((x) => x.t10_s === 3000) ?? d.scale_examples[Math.floor(d.scale_examples.length / 2)];
  return (
    <section className="section prose" aria-labelledby="mmr-m-h">
      <h2 id="mmr-m-h" className="visually-hidden">Running MMR method</h2>
      <h3 className="subhead">Overview</h3>
      <ul>
        {overview.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      <h3 className="subhead">Calculation</h3>
      <ul>
        {calc.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      {scale && ex ? (
        <>
          <h3 className="subhead">Worked example</h3>
          <p>
            A run whose 10 km-equivalent is <strong>{ex.t10_display}</strong> ({ex.t10_s} s) scores{" "}
            {scale.top_points} × ln({scale.zero_t10_s} / {ex.t10_s}) / ln({scale.zero_t10_s} / {scale.top_t10_s}) ={" "}
            <strong className="num">{ex.mmr.toFixed(0)}</strong> points (value from the app's method endpoint).
          </p>
        </>
      ) : null}
      <h3 className="subhead">Representative scores</h3>
      <DataTable
        caption="Representative Running MMR scores"
        captionHidden
        rows={d.scale_examples}
        rowKey={(x) => x.t10_s}
        columns={[
          { key: "t", header: "10 km-equivalent", align: "right", render: (x) => x.t10_display },
          { key: "m", header: "Running MMR", align: "right", render: (x) => x.mmr.toFixed(0) },
        ]}
      />
      <h3 className="subhead">Limitations</h3>
      <ul>
        {d.limitations.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      <details className="disclosure">
        <summary>Parameters and version ({d.version} · {d.scale_version})</summary>
        <dl className="kv">
          {Object.entries(d.params).map(([k, v]) => (
            <div key={k} className="kv__row">
              <dt className="mono">{k}</dt>
              <dd className="num">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}

export function MethodPage() {
  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">How Running MMR works</h1>
      </header>
      <MmrMethodSection />
    </div>
  );
}
