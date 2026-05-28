# OLCode
<img width="618" height="164" alt="Screenshot 2026-05-28 at 18 15 37" src="https://github.com/user-attachments/assets/874ef8db-b475-47e9-a361-df5c6be82cf9" />

         ██████╗  █████╗ ██╗     ██╗     ██╗██╗   ██╗██╗██╗   ██╗███╗   ███╗
        ██╔════╝ ██╔══██╗██║     ██║     ██║██║   ██║██║██║   ██║████╗ ████║
        ██║  ███╗███████║██║     ██║     ██║██║   ██║██║██║   ██║██╔████╔██║
        ██║   ██║██╔══██║██║     ██║     ██║╚██╗ ██╔╝██║██║   ██║██║╚██╔╝██║
        ╚██████╔╝██║  ██║███████╗███████╗██║ ╚████╔╝ ██║╚██████╔╝██║ ╚═╝ ██║
         ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝
                                                        Code like a gallivan
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
