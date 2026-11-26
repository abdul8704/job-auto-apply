import { FormEvent, useEffect, useState } from "react";
import { del, get, post } from "../api";
import { ErrorText, Status } from "../components/Status";
import type { Job } from "../types";
import JobDetail from "./JobDetail";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => get<Job[]>("/jobs").then(setJobs).catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const job = await post<Job>("/jobs", { url: url || null, text: text || null });
      setUrl("");
      setText("");
      await reload();
      setSelected(job.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="split">
      <aside className="stack">
        <form className="card" onSubmit={add}>
          <h2>Add a job</h2>
          <input placeholder="Job link (Workday, career page, …)" value={url} onChange={(e) => setUrl(e.target.value)} />
          <textarea placeholder="…or paste the job description" rows={4} value={text} onChange={(e) => setText(e.target.value)} />
          <button className="primary" disabled={busy || !(url || text)}>Add job</button>
          <ErrorText error={error} />
        </form>
        <ul className="joblist">
          {jobs.map((j) => (
            <li key={j.id} className={j.id === selected ? "active" : ""}>
              <button className="jobitem" onClick={() => setSelected(j.id)}>
                <strong>{j.title || j.url || "Untitled job"}</strong>
                <span className="muted small">{j.company}</span>
                <Status value={j.status} />
              </button>
              <button
                className="link small"
                aria-label="Delete job"
                onClick={async () => {
                  await del(`/jobs/${j.id}`);
                  if (selected === j.id) setSelected(null);
                  reload();
                }}
              >
                ✕
              </button>
            </li>
          ))}
          {jobs.length === 0 && <li className="muted">No jobs yet.</li>}
        </ul>
      </aside>
      <section>{selected ? <JobDetail key={selected} jobId={selected} onChanged={reload} /> : <p className="muted">Pick or add a job.</p>}</section>
    </div>
  );
}
