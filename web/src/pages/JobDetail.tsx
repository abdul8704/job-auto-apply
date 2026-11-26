import { useEffect, useState } from "react";
import { get, openPdf, poll, post } from "../api";
import { ErrorText, Status } from "../components/Status";
import type { Contact, Job, Kit, Message, Resume } from "../types";

export default function JobDetail({ jobId, onChanged }: { jobId: string; onChanged: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [kit, setKit] = useState<Kit | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function load() {
    try {
      const j = await poll<Job>(`/jobs/${jobId}`, (x) => !["queued", "parsing"].includes(x.status));
      setJob(j);
      onChanged();
      setContacts(await get<Contact[]>(`/jobs/${jobId}/contacts`));
      const kits = await get<Kit[]>(`/jobs/${jobId}/kits`);
      if (kits[0]) await showKit(kits[0]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function showKit(k: Kit) {
    setKit(k);
    if (k.resume_id) setResume(await poll<Resume>(`/resumes/${k.resume_id}`, (r) => r.status !== "queued"));
  }

  useEffect(() => {
    load();
  }, [jobId]);

  const act = (fn: () => Promise<void>) => async () => {
    setError("");
    setNote("");
    try {
      await fn();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  if (!job) return <ErrorText error={error} />;
  const p = job.parsed;
  const report = kit?.honesty_report;

  return (
    <div className="stack">
      <section className="card">
        <h2>
          {job.title || "Job"} {job.company && <span className="muted">at {job.company}</span>} <Status value={job.status} />
        </h2>
        {job.url && <a href={job.url} target="_blank" rel="noreferrer">{job.url}</a>}
        {job.error && <p className="error">{job.error}</p>}
        {p && (
          <>
            <p>{p.summary}</p>
            <p><strong>Must have:</strong> {p.required_skills.join(", ") || "—"}</p>
            <p><strong>Nice to have:</strong> {p.preferred_skills.join(", ") || "—"}</p>
            <details>
              <summary>Responsibilities ({p.responsibilities.length})</summary>
              <ul>{p.responsibilities.map((r) => <li key={r}>{r}</li>)}</ul>
            </details>
          </>
        )}
      </section>

      {job.status === "parsed" && (
        <section className="card">
          <h2>Tailored application kit</h2>
          <div className="row">
            <button
              className="primary"
              onClick={act(async () => {
                const k = await post<Kit>(`/jobs/${jobId}/kits`, {});
                await showKit(await poll<Kit>(`/kits/${k.id}`, (x) => ["done", "failed"].includes(x.status), 2000));
              })}
            >
              {kit ? "Regenerate kit" : "Tailor my resume"}
            </button>
            {kit && <Status value={kit.status} />}
          </div>
          {kit?.error && <p className="error">{kit.error}</p>}
          {kit?.status === "done" && (
            <>
              <div className="row">
                {resume?.status === "done" && <button onClick={act(() => openPdf(`/resumes/${resume.id}/pdf`))}>Open tailored resume</button>}
                {resume && resume.status !== "done" && <span>Resume <Status value={resume.status} /></span>}
                {kit.has_cover_letter_pdf && <button onClick={act(() => openPdf(`/kits/${kit.id}/cover-letter.pdf`))}>Open cover letter</button>}
                <button
                  onClick={act(async () => {
                    const r = await post<{ sent_to: string }>(`/kits/${kit.id}/email`);
                    setNote(`Emailed to ${r.sent_to}`);
                  })}
                >
                  Email it to me
                </button>
              </div>
              {note && <p className="good">{note}</p>}
              {report && (
                <div className="report">
                  <p><strong>Matched:</strong> {(report.matched_keywords ?? []).join(", ") || "—"}</p>
                  <p><strong>Not in your profile (left out, not invented):</strong> {(report.missing_keywords ?? []).join(", ") || "—"}</p>
                  {(report.reverted ?? []).length > 0 && (
                    <>
                      <p><strong>Honesty check reverted these rewrites:</strong></p>
                      <ul>{report.reverted!.map((r) => <li key={r.text}>{r.text} <span className="muted small">({r.reason})</span></li>)}</ul>
                    </>
                  )}
                </div>
              )}
              {kit.warnings?.map((w) => <p key={w} className="warn small">{w}</p>)}
            </>
          )}
        </section>
      )}

      {job.status === "parsed" && (
        <section className="card">
          <h2>People to contact</h2>
          <button
            onClick={act(async () => {
              await post(`/jobs/${jobId}/contacts/search`);
              await poll<Job>(`/jobs/${jobId}`, (x) => x.contacts_status !== "searching");
              setContacts(await get<Contact[]>(`/jobs/${jobId}/contacts`));
            })}
          >
            Find contacts
          </button>
          {job.contacts_warnings?.map((w) => <p key={w} className="warn small">{w}</p>)}
          <table>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id}>
                  <td>{c.full_name}<div className="muted small">{c.position}</div></td>
                  <td>{c.email ?? "—"} <span className="muted small">{c.email_status}</span></td>
                  <td>{c.category}</td>
                  <td>
                    {kit?.status === "done" && (
                      <button className="link" onClick={act(async () => setMessage(await get<Message>(`/kits/${kit.id}/messages/${c.id}`)))}>
                        Draft message
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {message && (
            <div className="report">
              <p><strong>To:</strong> {message.to_email ?? "(no email)"} · <strong>Subject:</strong> {message.subject}</p>
              <pre className="code">{message.body}</pre>
              <button onClick={() => navigator.clipboard?.writeText(`${message.subject}\n\n${message.body}`)}>Copy</button>
            </div>
          )}
        </section>
      )}
      <ErrorText error={error} />
    </div>
  );
}
