"use client";
import { useEffect, useState } from "react";

type FileEntry = { name: string; path: string; kind: "file" | "dir" };

export default function FileExplorer() {
  const [files, setFiles] = useState<FileEntry[]>([]);

  useEffect(() => {
    fetch("/api/files?path=workspace")
      .then((r) => r.json())
      .then((data) => setFiles(data.files || []))
      .catch(() => {});
  }, []);

  return (
    <div style={{ width: 220, borderLeft: "1px solid #334155", padding: 16 }}>
      <h3 style={{ marginTop: 0 }}>Workspace</h3>
      <ul style={{ padding: 0, listStyle: "none" }}>
        {files.map((f) => (
          <li key={f.path} style={{ fontSize: 14, color: "#e2e8f0" }}>
            {f.kind === "dir" ? "📁" : "📄"} {f.name}
          </li>
        ))}
      </ul>
    </div>
  );
}
