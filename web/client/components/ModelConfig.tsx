"use client";
import { useState } from "react";

export default function ModelConfig({
  model,
  profile,
  enableSemanticRouter,
  onChange,
}: {
  model: string;
  profile: string;
  enableSemanticRouter: boolean;
  onChange: (patch: Partial<{ model: string; profile: string; enableSemanticRouter: boolean }>) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      <select
        value={model}
        onChange={(e) => onChange({ model: e.target.value })}
        style={{ padding: 6 }}
      >
        <option value="qwen2.5-coder:1.5b">qwen2.5-coder:1.5b</option>
        <option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>
      </select>
      <select
        value={profile}
        onChange={(e) => onChange({ profile: e.target.value })}
        style={{ padding: 6 }}
      >
        <option value="lite">lite</option>
        <option value="full">full</option>
      </select>
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={enableSemanticRouter}
          onChange={(e) => onChange({ enableSemanticRouter: e.target.checked })}
        />
        Semantic Router
      </label>
    </div>
  );
}
