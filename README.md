# OLCode
<img width="1123" height="521" alt="Screenshot 2026-05-09 at 19 54 10" src="https://github.com/user-attachments/assets/3dacf0b2-b3eb-4512-babb-cb2dc15a5ef4" />

An advanced agentic AI coding assistant designed for autonomous system-level operations.

## Features
- **Auto-Mode**: Intelligent autonomous execution with dual-layer safety auditing.
- **Web Search**: Domain-prioritized search for authoritative sources (Ollama, Google AI, etc.).
- **Visual Intelligence**: Real-time markdown-to-ANSI rendering and thinking stream visualization.
- **Global Interruption**: Instant `Esc` key support for stopping generation and commands.
- **Minimalist Core**: High-performance, comment-free codebase optimized for raw execution.

## Installation
Ensure you have Python 3.12+ and [Ollama](https://ollama.com/) installed.

```bash
pip install ollama ddgs
```

## Usage
Launch the agent with your preferred model (defaults to `qwen3.6:27b-coding-nvfp4`):

```bash
python3 OCLI.py --auto
```

## Shortcuts
- `Esc`: Stop AI generation or interrupt a running shell command.
- `exit`: Quit the application.
- '/help': list all the commands 
