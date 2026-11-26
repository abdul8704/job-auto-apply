import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { setToken } from "./api";

function mockFetch(routes: Record<string, unknown>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const key = `${init?.method ?? "GET"} ${url}`;
      if (!(key in routes)) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 });
      const body = routes[key];
      if (body instanceof Response) return body;
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
});

test("logs in and shows the jobs page", async () => {
  const calls = mockFetch({
    "POST /api/auth/login": { access_token: "t0k" },
    "GET /api/auth/me": { id: "u1", email: "me@example.com", is_admin: true },
    "GET /api/jobs": [{ id: "j1", title: "Backend Engineer", company: "Acme", status: "parsed", url: null }],
  });
  render(<App />);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "me@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
  expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
  const me = calls.find((c) => c.url === "/api/auth/me")!;
  expect(new Headers(me.init?.headers).get("Authorization")).toBe("Bearer t0k");
});

test("shows the server's error on a failed login", async () => {
  mockFetch({ "POST /api/auth/login": new Response(JSON.stringify({ detail: "Wrong email or password" }), { status: 401 }) });
  render(<App />);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "me@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Wrong email or password"));
});

test("profile editor rejects invalid JSON before saving", async () => {
  setToken("t0k");
  const profile = { contact: { name: "", email: "", phone: "", location: "", links: [] }, summary: "", education: [], experience: [], projects: [], skills: [], certifications: [], achievements: [] };
  mockFetch({
    "GET /api/auth/me": { id: "u1", email: "me@example.com", is_admin: true },
    "GET /api/jobs": [],
    "GET /api/profile": profile,
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Profile" }));
  const editor = await screen.findByLabelText("Profile JSON");
  fireEvent.change(editor, { target: { value: "{not json" } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByText(/Invalid JSON/)).toBeInTheDocument();
});
