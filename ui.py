#!/usr/bin/env python
"""
Cordelite Agent UI - Test the agent with a simple web interface.
Uses Gradio for the UI and Ollama as the backend.

The agent is built by main.build_application, the same factory as the CLI and
web SDK, so calibration, constrained decoding, and safety guards are identical.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from main import build_application

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL_CHOICES = ["gemma3:1b", "qwen2.5-coder:1.5b", "phi3:mini"]


def run_agent(user_input: str, model: str = "gemma3:1b", ollama_url: str = OLLAMA_URL) -> str:
    run_dir = Path(tempfile.mkdtemp(prefix="cordelite_run_"))
    reg = None
    try:
        workspace = run_dir / "workspace"
        workspace.mkdir()
        ctx, reg = build_application(workspace, model, ollama_url, run_dir / "ui.db", profile="lite")
        return str(ctx.plugins["agent_loop"].run(user_input))
    except Exception as e:
        return f"Error: {e}"
    finally:
        if reg is not None:
            reg.stop_all()
        shutil.rmtree(run_dir, ignore_errors=True)


def create_ui() -> Any:
    import gradio as gr

    return gr.Interface(
        fn=run_agent,
        inputs=[
            gr.Textbox(
                label="Task",
                placeholder="e.g., write hello to a.txt, read a.txt, list files",
                lines=2,
            ),
            gr.Dropdown(choices=MODEL_CHOICES, value=MODEL_CHOICES[0], label="Model"),
        ],
        outputs=gr.Textbox(label="Agent Result", lines=10),
        title="Cordelite Agent",
        description="Test the tool-using agent locally via Ollama. Each run uses a fresh temporary workspace.",
        examples=[
            ["write hello to a.txt"],
            ["read a.txt"],
            ["list files"],
            ["create a.txt and b.txt"],
        ],
    )


if __name__ == "__main__":
    create_ui().launch(server_name="127.0.0.1", server_port=7860, share=False)
