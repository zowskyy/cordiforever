"use client";
import { useEffect, useRef } from "react";

type Event = { type: string; data: Record<string, unknown> };

export default function Chat({
  messages,
  onSend,
}: {
  messages: Event[];
  onSend: (text: string) => void;
}) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = () => {
    if (!input.trim()) return;
    onSend(input);
    setInput("");
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      <div
        style={{
          flex: 1,
          overflow: "auto",
          border: "1px solid #334155",
          borderRadius: 8,
          padding: 16,
          marginBottom: 16,
          background: "#0f172a",
        }}
      >
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <strong style={{ color: "#38bdf8" }}>{m.type}:</strong>{" "}
            <span style={{ color: "#e2e8f0" }}>{JSON.stringify(m.data)}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          style={{
            flex: 1,
            padding: 10,
            borderRadius: 6,
            border: "1px solid #334155",
            background: "#0f172a",
            color: "#e2e8f0",
          }}
        />
        <button
          onClick={send}
          style={{
            padding: "10px 16px",
            borderRadius: 6,
            border: "none",
            background: "#2563eb",
            color: "#fff",
            cursor: "pointer",
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
