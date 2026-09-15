/* Cordi v2 Web Dashboard - Modern Chat UI */

const state = {
    sessionId: null,
    eventSource: null,
    settings: {
        autoscroll: true,
        timestamps: true,
        compact: false,
    },
};

const els = {
    connectionStatus: document.getElementById("connection-status"),
    activeSession: document.getElementById("active-session"),
    sessionList: document.getElementById("session-list"),
    refreshSessions: document.getElementById("refresh-sessions"),
    newSession: document.getElementById("new-session"),
    modelList: document.getElementById("model-list"),
    metrics: document.getElementById("metrics"),
    chatMessages: document.getElementById("chat-messages"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    typingIndicator: document.getElementById("typing-indicator"),
    settingsToggle: document.getElementById("settings-toggle"),
    settingsPanel: document.getElementById("settings-panel"),
    refreshMetrics: document.getElementById("refresh-metrics"),
    settingAutoscroll: document.getElementById("setting-autoscroll"),
    settingTimestamps: document.getElementById("setting-timestamps"),
    settingCompact: document.getElementById("setting-compact"),
    settingModel: document.getElementById("setting-model"),
};

/* ─── Utilities ─── */

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ─── Syntax Highlighting (vanilla, no dependencies) ─── */

const LANG_PATTERNS = {
    python: [
        { type: "comment", pattern: /(?:#.*$|"""[\s\S]*?"""|'''[\s\S]*?''')/m },
        { type: "string", pattern: /(?:f"(?:[^"\\]|\\.)*"|f'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/ },
        { type: "number", pattern: /\b(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\b/ },
        { type: "keyword", pattern: /\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b/ },
        { type: "builtin", pattern: /\b(?:abs|all|any|bin|bool|chr|dict|enumerate|filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|isinstance|issubclass|iter|len|list|locals|map|max|min|next|object|oct|open|ord|pow|print|property|range|repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|vars|zip)\b/ },
        { type: "function", pattern: /\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()/ },
    ],
    javascript: [
        { type: "comment", pattern: /\/\/.*$|\/\*[\s\S]*?\*\//m },
        { type: "string", pattern: /(?:`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/ },
        { type: "number", pattern: /\b(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\b/ },
        { type: "keyword", pattern: /\b(?:break|case|catch|class|const|continue|debugger|default|delete|do|else|export|extends|finally|for|function|if|import|in|instanceof|let|new|of|return|static|super|switch|this|throw|try|typeof|var|void|while|with|yield|async|await)\b/ },
        { type: "builtin", pattern: /\b(?:Array|Boolean|Date|Error|JSON|Math|Number|Object|Promise|RegExp|String|Symbol|console|document|window|globalThis)\b/ },
        { type: "boolean", pattern: /\b(?:true|false|null|undefined|NaN|Infinity)\b/ },
        { type: "function", pattern: /\b[A-Za-z_$][A-Za-z0-9_$]*(?=\s*\()/ },
    ],
    json: [
        { type: "string", pattern: /"(?:[^"\\]|\\.)*"/ },
        { type: "number", pattern: /-?\b(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\b/ },
        { type: "boolean", pattern: /\b(?:true|false|null)\b/ },
        { type: "property", pattern: /"(?:[^"\\]|\\.)*"(?=\s*:)/ },
    ],
};

function highlightCode(code, language) {
    const patterns = LANG_PATTERNS[language] || LANG_PATTERNS["python"];

    // Simple tokenizer: split by patterns and wrap in spans
    const tokens = [];
    let remaining = code;
    let pos = 0;

    while (remaining.length > 0) {
        let matched = false;
        for (const { type, pattern } of patterns) {
            const m = remaining.match(pattern);
            if (m && m.index === 0) {
                tokens.push(`<span class="hl-${type}">${escapeHtml(m[0])}</span>`);
                remaining = remaining.slice(m[0].length);
                matched = true;
                break;
            }
        }
        if (!matched) {
            // Take one char as plain text
            const ch = remaining[0];
            if (ch === "\n") {
                tokens.push("\n");
            } else {
                tokens.push(escapeHtml(ch));
            }
            remaining = remaining.slice(1);
        }
    }

    return tokens.join("");
}

function renderMarkdown(text) {
    let html = escapeHtml(text);

    // Code blocks with language
    html = html.replace(/```(\w+)?\n?([\s\S]*?)```/g, (_, lang, code) => {
        const language = (lang || "python").toLowerCase();
        const highlighted = highlightCode(code.trim(), language);
        return `<pre><code class="language-${language}">${highlighted}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, (_, code) => `<code>${escapeHtml(code)}</code>`);

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Line breaks
    html = html.replace(/\n/g, "<br>");

    return html;
}

/* ─── Status ─── */

function setStatus(text, kind = "") {
    els.connectionStatus.textContent = text;
    els.connectionStatus.className = "badge " + kind;
}

/* ─── Message Rendering ─── */

function appendMessage(role, content, timestamp) {
    // Remove empty state if present
    const emptyState = els.chatMessages.querySelector(".empty-state");
    if (emptyState) {
        emptyState.remove();
    }

    const node = document.createElement("div");
    node.className = "message " + role;

    const meta = document.createElement("div");
    meta.className = "meta";

    const roleLabel = document.createElement("span");
    roleLabel.className = "role";
    roleLabel.textContent = role;

    const timeLabel = document.createElement("span");
    timeLabel.className = "timestamp";
    timeLabel.textContent = state.settings.timestamps ? formatTime(timestamp) : "";

    meta.appendChild(roleLabel);
    meta.appendChild(timeLabel);

    const contentDiv = document.createElement("div");
    contentDiv.className = "content";

    if (role === "system" || role === "error") {
        contentDiv.textContent = String(content ?? "");
    } else {
        contentDiv.innerHTML = renderMarkdown(String(content ?? ""));
    }

    node.appendChild(meta);
    node.appendChild(contentDiv);
    els.chatMessages.appendChild(node);

    if (state.settings.autoscroll) {
        els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    }
}

function showError(message) {
    appendMessage("error", message);
}

function setTyping(visible) {
    els.typingIndicator.classList.toggle("hidden", !visible);
    if (visible && state.settings.autoscroll) {
        els.typingIndicator.scrollIntoView({ behavior: "smooth", block: "end" });
    }
}

/* ─── Sessions ─── */

async function loadSessions() {
    try {
        const res = await fetch("/api/sessions");
        if (!res.ok) throw new Error("Failed to load sessions");
        const data = await res.json();
        els.sessionList.innerHTML = "";
        if (data.length === 0) {
            els.sessionList.innerHTML = '<div class="empty">No sessions yet</div>';
            return;
        }
        for (const session of data) {
            const item = document.createElement("div");
            item.className = "session-item" + (session.session_id === state.sessionId ? " active" : "");

            const label = document.createElement("span");
            label.className = "session-name";
            label.textContent = session.session_id;
            label.title = session.session_id;

            const actions = document.createElement("div");
            actions.style.display = "flex";
            actions.style.gap = "4px";

            const selectBtn = document.createElement("button");
            selectBtn.textContent = "Open";
            selectBtn.onclick = () => selectSession(session.session_id);

            const deleteBtn = document.createElement("button");
            deleteBtn.textContent = "Delete";
            deleteBtn.onclick = async () => {
                try {
                    const r = await fetch(`/api/sessions/${encodeURIComponent(session.session_id)}`, { method: "DELETE" });
                    if (!r.ok) throw new Error("Delete failed");
                    if (state.sessionId === session.session_id) {
                        state.sessionId = null;
                        els.chatMessages.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg></div><p>Select or create a session to begin.</p></div>';
                        els.activeSession.textContent = "no session";
                    }
                    loadSessions();
                } catch (e) {
                    showError("Failed to delete session: " + e.message);
                }
            };

            actions.appendChild(selectBtn);
            actions.appendChild(deleteBtn);
            item.appendChild(label);
            item.appendChild(actions);
            els.sessionList.appendChild(item);
        }
    } catch (e) {
        showError("Failed to load sessions: " + e.message);
    }
}

async function createSession() {
    try {
        const input = prompt("Enter initial message for new session (optional):");
        const body = input !== null ? { input } : {};
        const res = await fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error("Failed to create session");
        const data = await res.json();
        if (data.session_id) {
            await selectSession(data.session_id);
            if (data.result) {
                appendMessage("assistant", data.result);
            }
        }
    } catch (e) {
        showError("Failed to create session: " + e.message);
    }
}

/* ─── Models ─── */

async function loadModels() {
    try {
        const res = await fetch("/api/models");
        if (!res.ok) throw new Error("Failed to load models");
        const data = await res.json();
        els.modelList.innerHTML = "";
        if (data.length === 0) {
            els.modelList.innerHTML = '<div class="empty">No models available</div>';
            return;
        }
        // Update model select in settings
        els.settingModel.innerHTML = "";
        for (const model of data) {
            const opt = document.createElement("option");
            opt.value = model.id;
            opt.textContent = model.id;
            els.settingModel.appendChild(opt);
        }

        for (const model of data) {
            const item = document.createElement("div");
            item.className = "model-item" + (model.active ? " active" : "");

            const label = document.createElement("span");
            label.textContent = model.id;

            const actions = document.createElement("div");

            const switchBtn = document.createElement("button");
            switchBtn.className = "switch-btn";
            switchBtn.textContent = model.active ? "Active" : "Switch";
            switchBtn.disabled = model.active;
            if (!model.active) {
                switchBtn.onclick = async () => {
                    try {
                        const r = await fetch(`/api/models/${encodeURIComponent(model.id)}/switch`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: "{}",
                        });
                        if (!r.ok) throw new Error("Switch failed");
                        loadModels();
                    } catch (e) {
                        showError("Failed to switch model: " + e.message);
                    }
                };
            }

            actions.appendChild(switchBtn);
            item.appendChild(label);
            item.appendChild(actions);
            els.modelList.appendChild(item);
        }
    } catch (e) {
        showError("Failed to load models: " + e.message);
    }
}

/* ─── Metrics ─── */

async function loadMetrics() {
    try {
        const res = await fetch("/api/metrics");
        if (!res.ok) throw new Error("Failed to load metrics");
        const data = await res.json();
        els.metrics.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        els.metrics.textContent = "Error: " + e.message;
    }
}

/* ─── Session Selection & SSE ─── */

async function selectSession(sessionId) {
    state.sessionId = sessionId;
    els.activeSession.textContent = sessionId;
    els.chatMessages.innerHTML = "";
    loadSessions();
    await streamSession(sessionId);
}

async function streamSession(sessionId) {
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }

    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/events`);
        if (!res.ok) throw new Error("Event stream failed");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || !trimmed.startsWith("data:")) continue;

                const payload = trimmed.slice(5).trim();
                if (!payload || payload === "[DONE]") continue;

                try {
                    const event = JSON.parse(payload);
                    renderEvent(event);
                } catch {
                    // ignore parse errors from keep-alive frames
                }
            }
        }
    } catch (e) {
        showError("Event stream disconnected: " + e.message);
        setStatus("disconnected", "danger");
    }
}

function renderEvent(event) {
    if (!event || !event.type) return;

    const payload = event.payload || {};
    const timestamp = event.timestamp;

    switch (event.type) {
        case "user.message":
            appendMessage("user", payload.content || payload, timestamp);
            break;
        case "assistant.message":
            appendMessage("assistant", payload.content || payload, timestamp);
            setTyping(false);
            break;
        case "system.message":
            appendMessage("system", payload.content || payload, timestamp);
            break;
        case "tool.invoked":
            appendMessage("system", `Tool invoked: ${payload.tool_name || "unknown"}`, timestamp);
            break;
        case "tool.result":
            appendMessage("assistant", `Tool result:\n${JSON.stringify(payload, null, 2)}`, timestamp);
            break;
        case "tool.error":
            appendMessage("error", `Tool error: ${payload.error || payload}`, timestamp);
            break;
        case "tool.call.start":
        case "tool.call.end":
            appendMessage("system", event.type, timestamp);
            break;
        case "tool.result.pruned":
        case "tool.result.spilled":
            appendMessage("system", `${event.type}: ${JSON.stringify(payload)}`, timestamp);
            break;
        case "turn.start":
            setTyping(true);
            break;
        case "turn.end":
            setTyping(false);
            break;
        case "session.start":
        case "session.end":
            appendMessage("system", event.type, timestamp);
            break;
        case "session.deleted":
            if (state.sessionId === payload.session_id) {
                state.sessionId = null;
                els.chatMessages.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg></div><p>Session deleted.</p></div>';
                els.activeSession.textContent = "no session";
            }
            loadSessions();
            break;
        default:
            if (event.type.startsWith("tool.")) {
                appendMessage("system", `${event.type}: ${JSON.stringify(payload).slice(0, 500)}`, timestamp);
            } else if (event.type === "model.requested" || event.type === "model.responded") {
                // Quietly handle model events
            } else {
                appendMessage("system", event.type, timestamp);
            }
    }
}

/* ─── Run Session ─── */

async function runCurrentSession(input) {
    if (!state.sessionId) return;

    setTyping(true);
    appendMessage("user", input);

    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(state.sessionId)}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input }),
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || `HTTP ${res.status}`);
        }

        if (data.error) {
            showError(data.error);
            setTyping(false);
        } else if (data.result) {
            appendMessage("assistant", data.result);
            setTyping(false);
        }
    } catch (e) {
        showError("Request failed: " + e.message);
        setTyping(false);
    }
}

/* ─── Settings ─── */

function toggleSettings() {
    els.settingsPanel.classList.toggle("open");
}

function applySettings() {
    state.settings.autoscroll = els.settingAutoscroll.checked;
    state.settings.timestamps = els.settingTimestamps.checked;
    state.settings.compact = els.settingCompact.checked;

    if (state.settings.compact) {
        document.body.classList.add("compact");
    } else {
        document.body.classList.remove("compact");
    }
}

/* ─── Init ─── */

async function init() {
    // Settings bindings
    els.settingsToggle.onclick = toggleSettings;
    els.settingAutoscroll.onchange = applySettings;
    els.settingTimestamps.onchange = applySettings;
    els.settingCompact.onchange = applySettings;

    // Buttons
    els.refreshSessions.onclick = loadSessions;
    els.newSession.onclick = createSession;
    els.refreshMetrics.onclick = loadMetrics;

    // Model switch from settings
    els.settingModel.onchange = async () => {
        const modelId = els.settingModel.value;
        if (!modelId) return;
        try {
            const r = await fetch(`/api/models/${encodeURIComponent(modelId)}/switch`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: "{}",
            });
            if (!r.ok) throw new Error("Switch failed");
            loadModels();
        } catch (e) {
            showError("Failed to switch model: " + e.message);
        }
    };

    // Chat form
    els.chatForm.onsubmit = async (ev) => {
        ev.preventDefault();
        const text = els.chatInput.value.trim();
        if (!text) return;

        els.chatInput.value = "";
        if (!state.sessionId) {
            try {
                const res = await fetch("/api/sessions", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ input: text }),
                });
                const data = await res.json();
                if (data.session_id) {
                    await selectSession(data.session_id);
                    if (data.result) {
                        appendMessage("assistant", data.result);
                    }
                    return;
                }
            } catch (e) {
                showError("Failed to create session: " + e.message);
                return;
            }
        }

        await runCurrentSession(text);
    };

    // Health check
    try {
        const res = await fetch("/api/health");
        const data = await res.json();
        setStatus(data.status === "ok" ? "online" : "degraded", data.status === "ok" ? "ok" : "warning");
    } catch {
        setStatus("offline", "danger");
    }

    loadSessions();
    loadModels();
    loadMetrics();
    setInterval(loadMetrics, 5000);
}

init();
