"use client";
import { useEffect, useState } from "react";

type Event = { type: string; data: Record<string, unknown> };

export default function Page() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Event[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("qwen2.5-coder:1.5b");
  const [profile, setProfile] = useState("lite");
  const [enableSemanticRouter, setEnableSemanticRouter] = useState(false);

  useEffect(() => {
    if (sessionId) return;
    fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, profile, enableSemanticRouter }),
    })
      .then((r) => r.json())
      .then((data) => {
        setSessionId(data.id);
        const es = new EventSource(`/api/sessions/${data.id}/events`);
        es.onmessage = (e) => {
          const event = JSON.parse(e.data);
          setMessages((prev) => [...prev, event]);
        };
      });
  }, [sessionId, model, profile, enableSemanticRouter]);

  const send = () => {
    if (!sessionId || !input.trim()) return;
    fetch(`/api/sessions/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input }),
    });
    setInput("");
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <h1>Cordi v2 — 1.5B</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="qwen2.5-coder:1.5b">qwen2.5-coder:1.5b</option>
          <option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>
        </select>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option value="lite">lite</option>
          <option value="full">full</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={enableSemanticRouter}
            onChange={(e) => setEnableSemanticRouter(e.target.checked)}
          />{" "}
          Semantic Router
        </label>
      </div>
      <div
        style={{
          height: 400,
          overflow: "auto",
          border: "1px solid #ccc",
          padding: 8,
          marginBottom: 16,
        }}
      >
        {messages.map((m, i) => (
          <div key={i}>
            <strong>{m.type}:</strong> {JSON.stringify(m.data)}
          </div>
        ))}
      </div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
        style={{ width: "100%", padding: 8, marginBottom: 8 }}
      />
      <button onClick={send} style={{ padding: "8px 16px" }}>
        Send
      </button>
    </div>
  );
}
