const TONE: Record<string, string> = {
  done: "good", parsed: "good", applied: "good",
  failed: "bad", rejected: "bad",
};

export function Status({ value }: { value: string }) {
  return <span className={`pill ${TONE[value] ?? "neutral"}`}>{value}</span>;
}

export function ErrorText({ error }: { error: string }) {
  return error ? <p className="error" role="alert">{error}</p> : null;
}
