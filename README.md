# OLCode
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
   ___  _      ____          _     
  / _ \| |    / ___|___   __| | __
 | | | | |   | |   / _ \ / _` |/ _ \ 
 | |_| | |___| |__| (_) | (_| |  __/
  \___/|_____|\____\___/ \__,_|\___/

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
