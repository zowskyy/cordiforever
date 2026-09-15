import { EventMessage } from "./types";

export async function createSession(patch: {
  workspace?: string;
  model?: string;
  profile?: string;
  enableSemanticRouter?: boolean;
}) {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace: "workspace",
      model: "qwen2.5-coder:1.5b",
      profile: "lite",
      ...patch,
    }),
  });
  return res.json() as Promise<{ id: string }>;
}

export async function listSessions() {
  const res = await fetch("/api/sessions");
  return res.json() as Promise<{ sessions: string[] }>;
}

export function connectEvents(
  sessionId: string,
  onMessage: (event: EventMessage) => void
) {
  const es = new EventSource(`/api/sessions/${sessionId}/events`);
  es.onmessage = (e) => {
    const event = JSON.parse(e.data) as EventMessage;
    onMessage(event);
  };
  return es;
}

export async function sendMessage(sessionId: string, text: string) {
  await fetch(`/api/sessions/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
