"use client";
import { useEffect, useState } from "react";

type Session = { id: string; workspace: string; model: string; profile: string };

export default function SessionSidebar({
  onSelect,
}: {
  onSelect: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);

  const load = async () => {
    const res = await fetch("/api/sessions");
    const data = await res.json();
    setSessions(data.sessions || []);
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ width: 220, borderRight: "1px solid #334155", padding: 16 }}>
      <h3 style={{ marginTop: 0 }}>Sessions</h3>
      <ul style={{ padding: 0, listStyle: "none" }}>
        {sessions.map((s) => (
          <li
            key={s.id}
            onClick={() => onSelect(s.id)}
            style={{
              padding: 8,
              marginBottom: 4,
              background: "#1e293b",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            <div style={{ fontWeight: 600 }}>{s.id}</div>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>
              {s.profile} / {s.model}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
