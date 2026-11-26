import { ChangeEvent, useEffect, useState } from "react";
import { get, openPdf, poll, post, put, request } from "../api";
import { ErrorText, Status } from "../components/Status";
import type { DocumentOut, GitHubImport, Profile, Resume } from "../types";

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");

  const reload = () => get<Profile>("/profile").then(setProfile).catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  if (!profile) return <ErrorText error={error} />;
  return (
    <div className="stack">
      <ErrorText error={error} />
      <ResumeUpload onApplied={setProfile} />
      <GitHubImportCard onApplied={setProfile} />
      <FeaturedPicker profile={profile} onSaved={setProfile} />
      <ProfileEditor profile={profile} onSaved={setProfile} />
      <BaseResume />
    </div>
  );
}

function ResumeUpload({ onApplied }: { onApplied: (p: Profile) => void }) {
  const [doc, setDoc] = useState<DocumentOut | null>(null);
  const [error, setError] = useState("");

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const created = await request<DocumentOut>("/documents", { method: "POST", body: form });
      setDoc(created);
      setDoc(await poll<DocumentOut>(`/documents/${created.id}`, (d) => ["parsed", "failed"].includes(d.status)));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>1. Upload your resume</h2>
      <p className="muted">PDF, DOCX or .tex. It is parsed into your profile; review it before applying.</p>
      <input type="file" accept=".pdf,.docx,.tex" onChange={upload} />
      {doc && (
        <p>
          {doc.filename} <Status value={doc.status} /> {doc.error}
        </p>
      )}
      {doc?.status === "parsed" && (
        <button className="primary" onClick={async () => onApplied(await post<Profile>(`/documents/${doc.id}/apply`))}>
          Replace my profile with this draft
        </button>
      )}
      <ErrorText error={error} />
    </section>
  );
}

function GitHubImportCard({ onApplied }: { onApplied: (p: Profile) => void }) {
  const [username, setUsername] = useState("");
  const [featured, setFeatured] = useState("");
  const [imp, setImp] = useState<GitHubImport | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  async function start() {
    setError("");
    try {
      const names = featured.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 3);
      const created = await post<GitHubImport>("/github/imports", { username, featured: names });
      setImp(created);
      const done = await poll<GitHubImport>(`/github/imports/${created.id}`, (i) => ["done", "failed"].includes(i.status), 2000);
      setImp(done);
      setPicked(new Set(done.result?.repos.map((r) => r.name) ?? []));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>2. Import projects from GitHub</h2>
      <div className="row">
        <input placeholder="GitHub username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder="Top 3 repo names, comma separated" value={featured} onChange={(e) => setFeatured(e.target.value)} />
        <button className="primary" disabled={!username} onClick={start}>Import</button>
      </div>
      {imp && <p>Import <Status value={imp.status} /> {imp.error}</p>}
      {imp?.result && (
        <>
          <p className="muted small">Languages: {imp.result.languages.join(", ")} · Domains: {imp.result.domains.join(", ")}</p>
          {imp.result.warnings.map((w) => <p key={w} className="warn small">{w}</p>)}
          <ul className="plain">
            {imp.result.repos.map((r) => (
              <li key={r.name}>
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={picked.has(r.name)}
                    onChange={(e) => {
                      const next = new Set(picked);
                      if (e.target.checked) next.add(r.name);
                      else next.delete(r.name);
                      setPicked(next);
                    }}
                  />
                  <strong>{r.name}</strong> {r.featured && <span className="pill good">top 3</span>} — {r.project.description}
                  <span className="muted small"> ({r.project.tech.join(", ")})</span>
                </label>
              </li>
            ))}
          </ul>
          <button
            className="primary"
            onClick={async () => onApplied(await post<Profile>(`/github/imports/${imp.id}/apply`, { repos: [...picked] }))}
          >
            Add {picked.size} project(s) to my profile
          </button>
        </>
      )}
      <ErrorText error={error} />
    </section>
  );
}

function FeaturedPicker({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const [error, setError] = useState("");
  const featured = profile.projects.filter((p) => p.featured).map((p) => p.id);

  async function toggle(id: string, on: boolean) {
    const ids = on ? [...featured, id] : featured.filter((x) => x !== id);
    try {
      setError("");
      onSaved(await put<Profile>("/profile/featured", { project_ids: ids }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>3. Pick your top 3 projects</h2>
      {profile.projects.length === 0 && <p className="muted">No projects yet.</p>}
      <ul className="plain">
        {profile.projects.map((p) => (
          <li key={p.id}>
            <label className="inline">
              <input
                type="checkbox"
                checked={p.featured}
                disabled={!p.featured && featured.length >= 3}
                onChange={(e) => toggle(p.id, e.target.checked)}
              />
              {p.name}
            </label>
          </li>
        ))}
      </ul>
      <ErrorText error={error} />
    </section>
  );
}

function ProfileEditor({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const [text, setText] = useState(JSON.stringify(profile, null, 2));
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => setText(JSON.stringify(profile, null, 2)), [profile]);

  async function save() {
    setError("");
    setSaved(false);
    try {
      onSaved(await put<Profile>("/profile", JSON.parse(text)));
      setSaved(true);
    } catch (err) {
      setError(err instanceof SyntaxError ? `Invalid JSON: ${err.message}` : (err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>4. Review and edit your profile</h2>
      <p className="muted small">This is the single source of truth: tailoring may reword and reorder it, never add to it.</p>
      <textarea aria-label="Profile JSON" className="code" rows={22} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <button className="primary" onClick={save}>Save profile</button>
        {saved && <span className="good">Saved</span>}
      </div>
      <ErrorText error={error} />
    </section>
  );
}

function BaseResume() {
  const [resume, setResume] = useState<Resume | null>(null);
  const [error, setError] = useState("");
  async function render() {
    setError("");
    try {
      const r = await post<Resume>("/resumes", {});
      setResume(await poll<Resume>(`/resumes/${r.id}`, (x) => x.status !== "queued"));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <section className="card">
      <h2>5. Preview your base resume</h2>
      <div className="row">
        <button onClick={render}>Render PDF</button>
        {resume && <Status value={resume.status} />}
        {resume?.status === "done" && <button className="link" onClick={() => openPdf(`/resumes/${resume.id}/pdf`)}>Open PDF</button>}
      </div>
      {resume?.error && <pre className="code small">{resume.error}</pre>}
      <ErrorText error={error} />
    </section>
  );
}
