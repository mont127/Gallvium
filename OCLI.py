import ollama
import subprocess
import os
import json
import sys
import argparse
import difflib
import time
import re
import random
import threading
import select
import termios
import tty
import datetime
import requests
import warnings
import socket
import atexit
import signal
import pty
import array
import fcntl
import shlex
warnings.simplefilter("ignore")
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

class Colors:
    BLACK = "\033[30m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    GRAY = "\033[90m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    TEAL = "\033[38;5;44m"
    VIOLET = "\033[38;5;141m"
    PINK = "\033[38;5;213m"
    ORANGE = "\033[38;5;208m"
    LIME = "\033[38;5;118m"
    BG_DARK = "\033[48;5;236m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"

def clean_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", str(text))

def clean_len(text):
    return len(clean_ansi(text))

def term_width(default=92):
    try:
        return max(64, min(104, os.get_terminal_size().columns - 4))
    except OSError:
        return default

def frame_title(title, style=Colors.CYAN):
    width = term_width()
    label = f" {title} "
    line = "─" * max(2, width - clean_len(label) - 2)
    return f"{style}{Colors.BOLD}╭{label}{line}╮{Colors.RESET}"

def frame_bottom(style=Colors.CYAN):
    width = term_width()
    return f"{style}{Colors.BOLD}╰{'─' * (width - 2)}╯{Colors.RESET}"

def status_label(text, style=Colors.CYAN):
    return f"{style}{Colors.BOLD}▸ {text}{Colors.RESET}"

def mode_value(enabled, on="ON", off="OFF"):
    return f"{Colors.GREEN}{on}{Colors.RESET}" if enabled else f"{Colors.RED}{off}{Colors.RESET}"

def soft_rule(style=Colors.GRAY):
    return f"  {style}{Colors.DIM}{'─' * min(term_width(), 78)}{Colors.RESET}"

def print_panel(title, lines, style=Colors.CYAN):
    width = term_width()
    inner_width = width - 4
    print(f"  {frame_title(title, style)}")
    for line in lines:
        chunks = str(line).splitlines() or [""]
        for chunk in chunks:
            pad = " " * max(0, inner_width - clean_len(chunk))
            print(f"  {style}{Colors.BOLD}│{Colors.RESET} {chunk}{pad} {style}{Colors.BOLD}│{Colors.RESET}")
    print(f"  {frame_bottom(style)}")

def print_frame_line(text="", style=Colors.MAGENTA):
    inner_width = term_width() - 4
    safe = clean_ansi(str(text)).replace("\r", "\n").replace("\t", "    ")
    safe = "".join(char if char == "\n" or ord(char) >= 32 else " " for char in safe)
    lines = safe.split("\n")
    if not lines:
        lines = [""]
    for line in lines:
        if line == "":
            print(f"  {style}{Colors.BOLD}│{Colors.RESET} {' ' * inner_width} {style}{Colors.BOLD}│{Colors.RESET}")
            continue
        while line:
            chunk = line[:inner_width]
            line = line[inner_width:]
            pad = " " * max(0, inner_width - clean_len(chunk))
            print(f"  {style}{Colors.BOLD}│{Colors.RESET} {chunk}{pad} {style}{Colors.BOLD}│{Colors.RESET}")

def print_frame_text(text, style=Colors.MAGENTA):
    normalized = str(text).replace("\r", "\n")
    parts = normalized.split("\n")
    for index, part in enumerate(parts):
        if index == len(parts) - 1 and part == "":
            continue
        print_frame_line(part, style)

def can_use_terminal_keys():
    return sys.stdin.isatty() and sys.stdout.isatty()

def raw_text(text):
    return str(text).replace("\n", "\r\n")

INPUT_PUSHBACK = bytearray()

def input_ready(fd, timeout):
    return bool(INPUT_PUSHBACK) or bool(select.select([fd], [], [], timeout)[0])

def read_input_byte(fd):
    if INPUT_PUSHBACK:
        return bytes([INPUT_PUSHBACK.pop(0)]).decode(errors='ignore')
    return os.read(fd, 1).decode(errors='ignore')

def read_key():
    fd = sys.stdin.fileno()
    key = read_input_byte(fd)
    if key != "\x1b":
        return key
    if not input_ready(fd, 0.05):
        return key
    second = read_input_byte(fd)
    sequence = key + second
    if second != "[":
        return sequence
    if not input_ready(fd, 0.05):
        return sequence
    third = read_input_byte(fd)
    sequence += third
    if third in "ABCDHF":
        return sequence
    if third.isdigit():
        while input_ready(fd, 0.05) and len(sequence) < 6:
            char = read_input_byte(fd)
            sequence += char
            if char == "~":
                break
    return sequence

def read_bracketed_paste(fd):
    global INPUT_PUSHBACK
    marker = b"\x1b[201~"
    data = bytearray()
    while True:
        if not select.select([fd], [], [], 0.5)[0]:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        data.extend(chunk)
        index = data.find(marker)
        if index != -1:
            trailing = data[index + len(marker):]
            if trailing:
                INPUT_PUSHBACK[:0] = trailing
            return bytes(data[:index]).decode(errors='ignore')
    return bytes(data).decode(errors='ignore')

def styled_input(prompt, default=None):
    if not can_use_terminal_keys():
        return input(prompt)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    units = [{"display": ch, "actual": ch} for ch in (default or "")]
    cursor = len(units)
    last_prompt = prompt.split("\n")[-1]

    def display_text():
        return "".join(unit["display"] for unit in units)

    def actual_text():
        return "".join(unit["actual"] for unit in units)

    def display_len(slice_units):
        return clean_len("".join(unit["display"] for unit in slice_units))

    def redraw():
        rendered = display_text()
        sys.stdout.write("\r\033[K" + last_prompt + rendered)
        move_left = display_len(units[cursor:])
        if move_left > 0:
            sys.stdout.write(f"\033[{move_left}D")
        sys.stdout.flush()

    def insert_unit(display, actual):
        nonlocal cursor
        units.insert(cursor, {"display": display, "actual": actual})
        cursor += 1
        redraw()

    def insert_text(value):
        nonlocal cursor
        for char in value:
            if char in "\r\n":
                display = f"{Colors.GRAY}↵{Colors.RESET}"
                actual = "\n"
            elif char.isprintable() or char == "\t":
                display = "    " if char == "\t" else char
                actual = char
            else:
                continue
            units.insert(cursor, {"display": display, "actual": actual})
            cursor += 1
        redraw()

    def insert_paste(value):
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        lines = len(normalized.splitlines()) or 1
        if lines > 2:
            insert_unit(f"{Colors.ORANGE}[PASTED {lines} LINES]{Colors.RESET}", normalized)
        else:
            insert_text(normalized)

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?2004h")
        sys.stdout.write(raw_text(prompt) + display_text())
        sys.stdout.flush()
        while True:
            key = read_key()
            if key == "\x1b[200~":
                insert_paste(read_bracketed_paste(fd))
                continue
            if key in ["\r", "\n"]:
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return actual_text()
            if key == "\x03":
                raise KeyboardInterrupt
            if key == "\x04":
                if not units:
                    raise EOFError
                continue
            if key in ["\x7f", "\b"]:
                if cursor > 0:
                    del units[cursor - 1]
                    cursor -= 1
                    redraw()
                continue
            if key in ["\x1b[D", "\x02"]:
                if cursor > 0:
                    cursor -= 1
                    redraw()
                continue
            if key in ["\x1b[C", "\x06"]:
                if cursor < len(units):
                    cursor += 1
                    redraw()
                continue
            if key in ["\x1b[H", "\x1b[1~", "\x01"]:
                cursor = 0
                redraw()
                continue
            if key in ["\x1b[F", "\x1b[4~", "\x05"]:
                cursor = len(units)
                redraw()
                continue
            if key.startswith("\x1b[3") and cursor < len(units):
                del units[cursor]
                redraw()
                continue
            if len(key) == 1 and key.isprintable():
                insert_unit(key, key)
    finally:
        sys.stdout.write("\033[?2004l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def menu_lines(title, options, selected, style=Colors.VIOLET, offset=0, limit=None):
    width = term_width()
    inner_width = width - 4
    visible = options[offset:offset + limit] if limit else options
    lines = [f"  {frame_title(title, style)}"]
    for visible_index, option in enumerate(visible):
        actual_index = offset + visible_index
        marker = "▶" if actual_index == selected else " "
        if actual_index == selected:
            entry = f"{Colors.BG_DARK}{Colors.WHITE}{Colors.BOLD}{marker} {option}{Colors.RESET}"
        else:
            entry = f"{Colors.GRAY}{marker}{Colors.RESET} {option}"
        pad = " " * max(0, inner_width - clean_len(entry))
        lines.append(f"  {style}{Colors.BOLD}│{Colors.RESET} {entry}{pad} {style}{Colors.BOLD}│{Colors.RESET}")
    lines.append(f"  {frame_bottom(style)}")
    if limit and len(options) > limit:
        lines.append(f"  {Colors.GRAY}↑/↓ move · Enter select · 0/Esc cancel · {offset + 1}-{offset + len(visible)} of {len(options)}{Colors.RESET}")
    else:
        lines.append(f"  {Colors.GRAY}↑/↓ move · Enter select · 0/Esc cancel{Colors.RESET}")
    return lines

def interactive_menu(title, options, style=Colors.VIOLET):
    if not can_use_terminal_keys():
        print_panel(title, options + [f"{Colors.GRAY}0. Cancel{Colors.RESET}"], style)
        while True:
            choice = input(f"  {style}{Colors.BOLD}Select:{Colors.RESET} ").strip()
            if choice in ["", "0", "q", "quit", "cancel"]:
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return int(choice) - 1
            log_info("Pick a listed number or 0 to cancel.")
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    entries = options + [f"{Colors.GRAY}0. Cancel{Colors.RESET}"]
    selected = 0
    offset = 0
    height = 0

    def clear_menu():
        nonlocal height
        if not height:
            return
        sys.stdout.write(f"\033[{height}F")
        sys.stdout.write(f"\033[{height}M")
        sys.stdout.flush()
        height = 0

    def finish(value):
        clear_menu()
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        return value

    def draw():
        nonlocal height, offset
        if height:
            sys.stdout.write(f"\033[{height}F")
        try:
            visible_limit = max(6, min(16, os.get_terminal_size().lines - 8))
        except OSError:
            visible_limit = 12
        if selected < offset:
            offset = selected
        elif selected >= offset + visible_limit:
            offset = selected - visible_limit + 1
        lines = menu_lines(title, entries, selected, style, offset, visible_limit)
        for line in lines:
            sys.stdout.write("\033[K" + line + "\r\n")
        height = len(lines)
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?25l")
        draw()
        while True:
            key = read_key()
            if key in ["\x03", "\x04"]:
                raise KeyboardInterrupt
            if key in ["\r", "\n"]:
                return finish(None if selected == len(options) else selected)
            if key in ["\x1b", "q", "Q", "0"]:
                return finish(None)
            if key in ["\x1b[A", "k", "K"]:
                selected = (selected - 1) % len(entries)
                draw()
                continue
            if key in ["\x1b[B", "j", "J"]:
                selected = (selected + 1) % len(entries)
                draw()
                continue
            if key.isdigit() and 1 <= int(key) <= len(options):
                return finish(int(key) - 1)
    finally:
        clear_menu()
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def render_text(text):
    text = re.sub(r'`([^`]+)`', f"{Colors.BG_DARK}{Colors.WHITE} \\1 {Colors.RESET}", text)
    text = re.sub(r'\*\*\*(.*?)\*\*\*', f"{Colors.BOLD}{Colors.MAGENTA}\\1{Colors.RESET}", text)
    text = re.sub(r'\*\*(.*?)\*\*', f"{Colors.BOLD}{Colors.CYAN}\\1{Colors.RESET}", text)
    text = re.sub(r'\*(.*?)\*', f"{Colors.BLUE}\\1{Colors.RESET}", text)
    text = re.sub(r'### (.*)', f"\n{Colors.BOLD}{Colors.ORANGE}◆ \\1{Colors.RESET}", text)
    text = re.sub(r'## (.*)', f"\n{Colors.BOLD}{Colors.LIME}▰ \\1{Colors.RESET}", text)
    text = re.sub(r'# (.*)', f"\n{Colors.BOLD}{Colors.TEAL}━━ \\1 ━━{Colors.RESET}", text)
    text = re.sub(r'^(\s*)[\*\-] ', f"\\1{Colors.TEAL}• {Colors.RESET}", text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*)(\d+)\. ', f"\\1{Colors.ORANGE}\\2. {Colors.RESET}", text, flags=re.MULTILINE)
    return text

def fake_loading(msg, duration=0.6):
    frames = ["◜", "◠", "◝", "◞", "◡", "◟"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        print(f"  {Colors.TEAL}{frames[i % len(frames)]}{Colors.RESET} {Colors.GRAY}{msg}{Colors.RESET}", end="\r")
        time.sleep(0.06)
        i += 1
    print(f"  {Colors.GREEN}{Colors.BOLD}✓{Colors.RESET} {Colors.GRAY}{msg}{Colors.RESET}")

def log_tool(msg):
    fake_loading(msg)

def log_info(msg):
    print(f"  {status_label('INFO', Colors.ORANGE)} {msg}{Colors.RESET}")

class Spinner:
    def __init__(self, msg="AI is thinking"):
        self.msg = msg
        self.running = False
        self.thread = None
        self.frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        self.bars = [
            "▰▱▱▱▱▱▱▱",
            "▰▰▱▱▱▱▱▱",
            "▱▰▰▱▱▱▱▱",
            "▱▱▰▰▱▱▱▱",
            "▱▱▱▰▰▱▱▱",
            "▱▱▱▱▰▰▱▱",
            "▱▱▱▱▱▰▰▱",
            "▱▱▱▱▱▱▰▰",
            "▱▱▱▱▱▱▱▰",
            "▰▱▱▱▱▱▱▱",
        ]
        self.pulses = ["syncing context", "sampling tokens", "routing tools", "stream warming", "planning tool calls", "reading context", "loading model"]
        self.pulse_hold = 64
        self.current_pulse = random.choice(self.pulses)
        self.last_len = 0
        self.started_at = None

    def _spin(self):
        i = 0
        self.started_at = time.time()
        while self.running:
            elapsed = time.time() - self.started_at
            frame = self.frames[i % len(self.frames)]
            bar = self.bars[i % len(self.bars)]
            if i and i % self.pulse_hold == 0:
                choices = [pulse for pulse in self.pulses if pulse != self.current_pulse] or self.pulses
                self.current_pulse = random.choice(choices)
            pulse = self.current_pulse
            color = [Colors.TEAL, Colors.VIOLET, Colors.PINK, Colors.LIME][i % 4]
            line = f"  {color}{Colors.BOLD}{frame}{Colors.RESET} {color}{bar}{Colors.RESET} {Colors.WHITE}{self.msg}{Colors.RESET} {Colors.GRAY}{pulse} · {elapsed:04.1f}s{Colors.RESET}"
            pad = " " * max(0, self.last_len - clean_len(line))
            print(line + pad, end="\r")
            self.last_len = clean_len(line)
            time.sleep(0.08)
            i += 1
        sys.stdout.write("\r" + " " * (self.last_len + 2) + "\r")
        sys.stdout.flush()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join()

class InterruptionManager:
    def __init__(self):
        self.interrupted = threading.Event()
        self._old_settings = None
        self._active = False

    def start_listening(self):
        if self._active: return
        self.interrupted.clear()
        try:
            self._old_settings = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            self._active = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
        except Exception: pass

    def stop_listening(self):
        if not self._active: return
        try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)
        except Exception: pass
        self._active = False

    def _listen_loop(self):
        while self._active:
            try:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    key = sys.stdin.read(1)
                    if ord(key) == 27:
                        self.interrupted.set()
                        break
            except Exception: break
        self._active = False

interrupter = InterruptionManager()

def print_diff(diff_lines):
    if not diff_lines: return
    print(f"\n  {frame_title('DIFF REPORT', Colors.MAGENTA)}")
    for line in diff_lines:
        if line.startswith('+') and not line.startswith('+++'): print(f"    {Colors.GREEN}{Colors.BOLD}{line.rstrip()}{Colors.RESET}")
        elif line.startswith('-') and not line.startswith('---'): print(f"    {Colors.RED}{line.rstrip()}{Colors.RESET}")
        elif line.startswith('@@'): print(f"    {Colors.TEAL}{Colors.BOLD}{line.rstrip()}{Colors.RESET}")
        else: print(f"    {Colors.GRAY}{line.rstrip()}{Colors.RESET}")
    print(f"  {frame_bottom(Colors.MAGENTA)}\n")

def print_logo():
    logo = rf"""{Colors.TEAL}{Colors.BOLD}
╭────────────────────────────────────────────────────────────────────────────╮
│                                                                            │
│   ██████╗  ██████╗██╗     ██╗       ██████╗ ██████╗ ██████╗ ███████╗       │
│  ██╔═══██╗██╔════╝██║     ██║      ██╔════╝██╔═══██╗██╔══██╗██╔════╝       │
│  ██║   ██║██║     ██║     ██║█████╗██║     ██║   ██║██║  ██║█████╗         │
│  ██║   ██║██║     ██║     ██║╚════╝██║     ██║   ██║██║  ██║██╔══╝         │
│  ╚██████╔╝╚██████╗███████╗██║      ╚██████╗╚██████╔╝██████╔╝███████╗       │
│   ╚═════╝  ╚═════╝╚══════╝╚═╝       ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝       │
│                                                                            │
╰────────────────────────────────────────────────────────────────────────────╯
{Colors.RESET}{Colors.PINK}{Colors.BOLD}        local models  ✦  shell tools  ✦  files  ✦  web  ✦  autonomous coding{Colors.RESET}
{Colors.GRAY}        Free open-source AI coding assistant for the terminal{Colors.RESET}
"""
    print(logo)

MAX_OUTPUT_LENGTH = 10000
HISTORY_THRESHOLD = 36
COMPACT_RECENT_MESSAGES = 12
COMPACT_MAX_MESSAGE_CHARS = 2200
DANGEROUS_PATTERNS = [r'\brm\b', r'\bmv\b', r'\bsudo\b', r'\bchmod\b', r'\bchown\b', r'\bdd\b', r'\bmkfs\b', r'\bformat\b', r'\bkill\b', r'>\s*/dev/', r'\bshred\b', r'\bwipe\b']
ALLOWED_SEARCH_DOMAINS = ["ollama.com", "googleblog.com", "ai.google.dev", "huggingface.co"]
BACKEND_DEFAULT_URLS = {
    "ollama": "http://localhost:11434",
    "llama-cpp": "http://localhost:8080",
    "mlx": "http://localhost:8080",
}
BACKEND_DEFAULT_MODELS = {
    "ollama": "qwen3.6:27b-coding-nvfp4",
    "llama-cpp": "qwen2.5-coder-1.5b",
    "mlx": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
}
OLLAMA_MODELS = [
    "qwen3.6:27b-coding-nvfp4",
    "llama3.2",
    "llama3.1",
    "llama3.3",
    "qwen3",
    "qwen2.5",
    "qwen2.5vl",
    "qwen3-vl",
    "mistral",
    "mistral-nemo",
    "mistral-small",
    "mistral-small3.2",
    "gemma3",
    "gemma2",
    "phi4",
    "phi3",
    "deepseek-r1",
    "deepseek-v3",
    "olmo2",
    "olmo-3",
    "aya",
    "dolphin3",
    "dolphin-llama3",
    "neural-chat",
    "nous-hermes2",
    "orca-mini",
    "mixtral",
    "falcon3",
    "smollm",
    "smollm2",
    "cogito",
    "lfm2.5-thinking",
    "rnj-1",
    "nemotron-3-nano",
    "granite3.1-moe",
    "granite3.2",
    "granite3.3",
    "qwen2.5-coder",
    "qwen3-coder",
    "deepseek-coder",
    "codellama",
    "codegemma",
    "starcoder2",
    "stable-code",
    "sqlcoder",
    "wizardcoder",
    "yi-coder",
    "granite-code",
    "nomic-embed-text",
    "mxbai-embed-large",
    "bge-m3",
    "all-minilm",
    "snowflake-arctic-embed",
    "qwen3-embedding",
    "llava",
    "bakllava",
    "moondream",
    "minicpm-v",
    "llama3.2-vision",
]
MLX_MODELS = [
    "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "mlx-community/Qwen3-8B-4bit",
    "mlx-community/gemma-3-4b-it-4bit",
    "mlx-community/Qwen3.5-0.8B-OptiQ-4bit",
    "mlx-community/Qwen3.5-2B-OptiQ-4bit",
    "mlx-community/Qwen3.5-4B-OptiQ-4bit",
    "mlx-community/Qwen3.5-9B-MLX-4bit",
    "mlx-community/Qwen3.6-35B-A3B-4bit",
    "mlx-community/Qwen3.6-40B-Claude-4.6-Opus-Deckard-Heretic-Uncensored-Thinking-8bit",
    "mlx-community/Qwen3-Coder-Next-nvfp4",
    "mlx-community/Qwen3-Coder-Next-mxfp8",
    "mlx-community/Qwen3-Coder-Next-mxfp4",
    "mlx-community/gemma-4-e2b-it-OptiQ-4bit",
    "mlx-community/gemma-4-e4b-it-OptiQ-4bit",
    "mlx-community/gemma-4-26B-A4B-it-assistant-bf16",
    "mlx-community/gemma-4-31B-it-assistant-bf16",
    "mlx-community/Nemotron-Mini-4B-Instruct-4bit-mlx",
    "mlx-community/Nemotron-Mini-4B-Instruct-bf16-mlx",
    "mlx-community/granite-4.1-8b-4bit",
    "mlx-community/granite-4.1-8b-5bit",
    "mlx-community/granite-4.1-8b-6bit",
    "mlx-community/granite-4.1-8b-8bit",
    "mlx-community/granite-4.1-8b-nvfp4",
    "mlx-community/granite-4.1-8b-mxfp8",
    "mlx-community/GLM-4.5-Air-mxfp8",
    "mlx-community/GLM-4.5-Air-nvfp4",
    "mlx-community/DeepSeek-V4-Flash-4bit",
    "mlx-community/DeepSeek-V4-Flash-2bit-DQ",
]
GGUF_MODELS = [
    "Qwen2.5-Coder-1.5B-Instruct-GGUF",
    "Llama-3.1-8B-Instruct-GGUF",
    "Llama-3.2-3B-Instruct-GGUF",
    "Llama-3.3-70B-Instruct-GGUF",
    "Qwen2.5-Coder-7B-Instruct-GGUF",
    "Qwen2.5-Coder-14B-Instruct-GGUF",
    "Qwen2.5-Coder-32B-Instruct-GGUF",
    "Qwen3-8B-GGUF",
    "Qwen3-14B-GGUF",
    "Qwen3-32B-GGUF",
    "Qwen3-Coder-GGUF",
    "Mistral-7B-Instruct-GGUF",
    "Mistral-Nemo-12B-Instruct-GGUF",
    "Mixtral-8x7B-Instruct-GGUF",
    "Gemma-2-9B-Instruct-GGUF",
    "Gemma-3-GGUF",
    "Phi-3-mini-GGUF",
    "Phi-4-GGUF",
    "DeepSeek-R1-Distill-Qwen-7B-GGUF",
    "DeepSeek-R1-Distill-Qwen-14B-GGUF",
    "DeepSeek-R1-Distill-Qwen-32B-GGUF",
    "DeepSeek-Coder-V2-Lite-GGUF",
    "CodeLlama-7B-Instruct-GGUF",
    "CodeLlama-13B-Instruct-GGUF",
    "StarCoder2-7B-GGUF",
    "Yi-Coder-9B-GGUF",
    "Nous-Hermes-2-Mistral-7B-GGUF",
    "OpenHermes-2.5-Mistral-7B-GGUF",
    "Dolphin-Llama3-GGUF",
    "Dolphin-Mistral-GGUF",
    "froggeric/Qwen3.6-27B-MTP-GGUF",
    "Jiunsong/supergemma4-26b-uncensored-gguf-v2",
    "hesamation/Qwen3.6-35B-A3B-Claude-4.6-Opus-Reasoning-Distilled-GGUF",
    "kai-os/Carnice-V2-27b-GGUF",
    "AtomicChat/gemma-4-26B-A4B-it-assistant-GGUF",
    "LiquidAI/LFM2.5-1.2B-Thinking-GGUF",
    "LiquidAI/LFM2-24B-A2B-GGUF",
    "prism-ml/Bonsai-8B-gguf",
    "jgebbeken/gemma-4-coder-gguf",
    "qvac/MedPsy-4B-GGUF",
]
LLAMA_CPP_URLS = {
    "Qwen2.5-Coder-1.5B-Instruct-GGUF": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
}
MODEL_SUGGESTIONS = {
    "ollama": OLLAMA_MODELS,
    "llama-cpp": GGUF_MODELS,
    "mlx": MLX_MODELS,
}
DOWNLOAD_MODEL_OPTIONS = {
    "ollama": [(model, model, None) for model in OLLAMA_MODELS],
    "mlx": [(model.split("/")[-1], model, None) for model in MLX_MODELS],
    "llama-cpp": [(model.split("/")[-1], model, LLAMA_CPP_URLS.get(model)) for model in GGUF_MODELS],
}

def extract_allowed_domains(text):
    found = []
    lowered = text.lower()
    for domain in ALLOWED_SEARCH_DOMAINS:
        if domain in lowered: found.append(domain)
    return found

def should_search_official_domains(query):
    lowered = query.lower()
    official_words = ["official", "source", "vendor", "docs", "documentation"]
    known_products = ["ollama", "gemma", "google", "huggingface", "hugging face"]
    return any(word in lowered for word in official_words) and any(product in lowered for product in known_products)

def domain_matches(url, allowed_domains):
    if not allowed_domains: return True
    lowered = url.lower()
    return any(domain in lowered for domain in allowed_domains)

def model_matches_backend(model, backend):
    if not model:
        return False
    lowered = model.lower()
    if backend == "mlx":
        return model.startswith("mlx-community/") or model.startswith(("/", ".", "~"))
    if backend == "llama-cpp":
        return lowered.endswith(".gguf") or "gguf" in lowered or model.startswith(("/", ".", "~"))
    return not model.startswith("mlx-community/") and "gguf" not in lowered and not lowered.endswith(".gguf")

def truncate_output(output):
    if len(str(output)) > MAX_OUTPUT_LENGTH: return str(output)[:MAX_OUTPUT_LENGTH] + f"\n\n[Output truncated due to size.]"
    return str(output)


def extract_json_objects(text):
    objects = []
    start = None
    depth = 0
    in_string = False
    escape = False
    for i, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            if depth == 0:
                start = i
            depth += 1
        elif char == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:i + 1])
                    start = None
    return objects

def recover_tool_call_from_text(text):
    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
    if not name_match:
        return None
    name = name_match.group(1)

    args = {}
    arg_keys = ['command', 'path', 'content', 'plan', 'query', 'text', 'url', 'pattern', 'repo_id', 'index', 'status', 'key', 'value']
    for key in arg_keys:
        match = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if match:
            try:
                args[key] = bytes(match.group(1), "utf-8").decode("unicode_escape")
            except Exception:
                args[key] = match.group(1)
    num_match = re.search(r'"num_results"\s*:\s*(\d+)', text)
    if num_match:
        args["num_results"] = int(num_match.group(1))

    if not args: return None
    return {'function': {'name': name, 'arguments': args}}

class OCLI:
    def __init__(self, model_name, auto_mode=False, backend='ollama', url=None):
        self.model_name = model_name
        self.auto_mode = auto_mode
        self.backend = backend
        self.url = url or BACKEND_DEFAULT_URLS.get(backend, "http://localhost:8080")
        self.planning_enabled = False
        self.tasks = []
        self.active_process = None
        self.active_master = None
        self.last_tool_signature = None
        self.repeated_tool_count = 0
        self.last_user_goal = ""
        self.last_failure_signature = None
        self.repeated_failure_count = 0
        self.tool_steps_this_turn = 0
        self.compaction_count = 0
        self.PLAN_PROMPT = "Planning is ENABLED. Before performing complex tasks, multiple file edits, or potentially destructive operations, you MUST create an implementation plan using the 'create_plan' tool. Break the plan down into discrete, numbered tasks that cover every explicit user requirement. As you work, use the 'update_task' tool to mark tasks as 'doing' and 'done'. After the plan is approved, continue by making real tool calls."
        cur_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.messages = [{
            'role': 'system',
            'content': (
                f"You are OCLI, an advanced AUTONOMOUS AI coding agent. Current date: {cur_date}. "
                "CONVERSATION RULES: For greetings, questions, explanations, or any non-task message, respond in plain natural language. Do NOT call tools or output JSON for simple conversation. Only use tools when the user explicitly asks you to perform an action (run code, edit files, search, etc.). "
                "Wrap internal reasoning in <thought> tags. "
                "To call a tool, output exactly one tool call and nothing else: <tools>{{\"name\": \"tool_name\", \"arguments\": {{...}}}}</tools>. For coding tasks, write the complete requested implementation first, then write tests, then run pytest, then fix failures, then summarize final files. "
                "Do not write markdown code blocks when creating or editing files; use the write_file tool. Do not describe running commands; use run_cmd or test_cmd. Do not fabricate tool results, diffs, test output, file contents, or <tool_response> blocks. If a user asks you to create code, modify code, inspect files, run tests, install packages, or execute a program, you MUST call a real tool. "
                "For multi-step tasks, after each successful real tool call, immediately make the next required real tool call only if it advances the original user request; do not output bare CONTINUE as a standalone response, and do not repeatedly run the same command or read/write the same file without changing strategy. If a test fails twice with the same error, inspect the file tree and relevant files before editing again. "
                "CRITICAL: Use the 'test_cmd' tool for ANY command that might be interactive (games, prompts, servers). DO NOT use 'run_cmd' for these. MANDATORY: Always use 'write_file' for all code modifications to ensure the user sees a diff report. When the user asks for multiple searches, perform at least 3-5 searches. "
                "IMPORTANT: You are an autonomous agent. NEVER ask the user to run a command. RUN IT YOURSELF. NEVER simulate tool results. ONLY use 'CONTINUE' if you have just called a tool and need to perform another step. ALWAYS prioritize answering the user's primary question directly after gathering data. If searching for software features, prioritize finding 'Release Notes' or 'What's New' pages. Planning is DISABLED. Do not use create_plan tool unless planning is explicitly enabled."
            )
        }]
        self.server_process = None
        if self.backend == 'mlx': self.ensure_mlx_server()
        atexit.register(self.cleanup)

    def cleanup(self):
        if self.server_process:
            log_info("Shutting down MLX server...")
            self.server_process.terminate()
            try: self.server_process.wait(timeout=5)
            except: self.server_process.kill()
            self.server_process = None

    def menu_choice(self, title, options):
        return interactive_menu(title, options, Colors.VIOLET)

    def prompt_value(self, label, current=None):
        suffix = f" {Colors.GRAY}[{current}]{Colors.RESET}" if current else ""
        value = styled_input(f"  {Colors.TEAL}{label}{Colors.RESET}{suffix}: ").strip()
        return value or current

    def set_backend(self, backend, url=None, keep_model=False):
        previous_backend = self.backend
        if previous_backend == 'mlx' and backend != 'mlx':
            self.cleanup()
        self.backend = backend
        self.url = url or BACKEND_DEFAULT_URLS.get(backend, "http://localhost:8080")
        if keep_model and not model_matches_backend(self.model_name, backend):
            log_info(f"Current model {Colors.TEAL}{self.model_name}{Colors.RESET} is not compatible with {Colors.TEAL}{backend}{Colors.RESET}; using the backend default.")
            keep_model = False
        if not keep_model:
            self.model_name = BACKEND_DEFAULT_MODELS.get(backend, self.model_name)
        if self.backend == 'mlx':
            self.ensure_mlx_server()
        log_info(f"Backend switched to {Colors.TEAL}{self.backend}{Colors.RESET} using {Colors.TEAL}{self.url}{Colors.RESET}")
        log_info(f"Model is now {Colors.TEAL}{self.model_name}{Colors.RESET}")

    def backend_menu(self):
        options = [
            f"1. {Colors.CYAN}ollama{Colors.RESET}     {Colors.GRAY}Local Ollama API on port 11434{Colors.RESET}",
            f"2. {Colors.CYAN}llama-cpp{Colors.RESET}  {Colors.GRAY}OpenAI-compatible llama.cpp server{Colors.RESET}",
            f"3. {Colors.CYAN}mlx{Colors.RESET}        {Colors.GRAY}MLX server for Apple Silicon{Colors.RESET}",
        ]
        choice = self.menu_choice("BACKEND", options)
        if choice is None:
            return
        backend = ["ollama", "llama-cpp", "mlx"][choice]
        current_url = self.url if self.backend == backend else BACKEND_DEFAULT_URLS[backend]
        url = self.prompt_value("Server URL", current_url)
        keep_model = False
        if model_matches_backend(self.model_name, backend):
            keep = styled_input(f"  {Colors.TEAL}Keep current model '{self.model_name}'?{Colors.RESET} {Colors.GRAY}(y/N){Colors.RESET}: ").strip().lower()
            keep_model = keep in ["y", "yes"]
        else:
            log_info(f"Current model {Colors.TEAL}{self.model_name}{Colors.RESET} does not match {Colors.TEAL}{backend}{Colors.RESET}; switching to {Colors.TEAL}{BACKEND_DEFAULT_MODELS[backend]}{Colors.RESET}.")
        self.set_backend(backend, url, keep_model)

    def list_ollama_models(self):
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return []
            models = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
        except Exception:
            return []

    def model_menu(self):
        suggestions = MODEL_SUGGESTIONS.get(self.backend, []).copy()
        if self.backend == "ollama":
            suggestions = list(dict.fromkeys(self.list_ollama_models() + suggestions))
        options = [f"{i + 1}. {Colors.CYAN}{model}{Colors.RESET}" for i, model in enumerate(suggestions)]
        options.append(f"{len(options) + 1}. {Colors.ORANGE}Type a custom model name{Colors.RESET}")
        choice = self.menu_choice("MODEL", options)
        if choice is None:
            return
        if choice < len(suggestions):
            self.model_name = suggestions[choice]
        else:
            model = self.prompt_value("Model name", self.model_name)
            if not model:
                return
            self.model_name = model
        if self.backend == 'mlx':
            self.cleanup()
            self.ensure_mlx_server()
        log_info(f"Model switched to {Colors.TEAL}{self.model_name}{Colors.RESET}")

    def run_model_download(self, model_name, url=None):
        if not model_name:
            return
        log_info(f"Download target: {Colors.TEAL}{model_name}{Colors.RESET}")
        if self.backend == "ollama":
            self.run_cmd(f"ollama pull {shlex.quote(model_name)}")
        elif self.backend == "mlx":
            self.download_mlx_model(model_name)
        else:
            if not url and "/" in model_name:
                target = os.path.join("llama.cpp/models", model_name.split("/")[-1])
                os.makedirs(target, exist_ok=True)
                self.run_cmd(f"hf download {shlex.quote(model_name)} --include '*.gguf' --local-dir {shlex.quote(target)}")
                return
            url = url or self.prompt_value("GGUF download URL")
            if not url:
                log_info("Download canceled.")
                return
            os.makedirs("llama.cpp/models", exist_ok=True)
            filename = model_name if model_name.endswith(".gguf") else os.path.basename(url.split("?")[0]) or f"{model_name}.gguf"
            self.run_cmd(f"curl -L -o {shlex.quote(os.path.join('llama.cpp/models', filename))} {shlex.quote(url)}")

    def download_model_menu(self, model_name=None):
        if model_name:
            self.run_model_download(model_name)
            return
        choices = DOWNLOAD_MODEL_OPTIONS.get(self.backend, [])
        options = [
            f"{i + 1}. {Colors.CYAN}{label}{Colors.RESET} {Colors.GRAY}{value}{Colors.RESET}"
            for i, (label, value, _) in enumerate(choices)
        ]
        options.append(f"{len(options) + 1}. {Colors.ORANGE}Type a custom model or URL{Colors.RESET}")
        choice = self.menu_choice("DOWNLOAD MODEL", options)
        if choice is None:
            return
        if choice < len(choices):
            _, value, url = choices[choice]
            self.run_model_download(value, url)
            return
        if self.backend == "llama-cpp":
            url = self.prompt_value("GGUF download URL")
            if not url:
                log_info("Download canceled.")
                return
            model_name = self.prompt_value("Save as", os.path.basename(url.split("?")[0]) or "model.gguf")
            self.run_model_download(model_name, url)
            return
        model_name = self.prompt_value("Model to download", self.model_name)
        self.run_model_download(model_name)

    def is_port_open(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def ensure_mlx_server(self):
        host = self.url.split("//")[-1].split(":")[0]
        try: port = int(self.url.split(":")[-1])
        except: port = 8080
        
        if self.is_port_open(host, port):
            log_info(f"MLX Server already running on {host}:{port}")
            return

        log_info(f"Auto-starting MLX Server with model: {self.model_name}")
        cmd = [sys.executable, "-m", "mlx_lm.server", "--model", self.model_name]
        try:
            self.server_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_info("Waiting for MLX server to initialize...")
            for _ in range(30):
                if self.is_port_open(host, port):
                    log_info("MLX Server is ready!")
                    return
                time.sleep(1)
            log_info("Warning: MLX Server is taking a long time to start. It might still be loading.")
        except Exception as e:
            log_info(f"Failed to start MLX server: {e}")

    def run_cmd(self, command):
        try:
            def close_panel():
                print(f"  {frame_bottom(Colors.MAGENTA)}")

            is_dangerous = any(re.search(p, command) for p in DANGEROUS_PATTERNS)
            if not self.auto_mode or is_dangerous:
                reason = "Dangerous Pattern" if is_dangerous else "Manual Confirmation"
                print(f"\n  {status_label('WARN', Colors.ORANGE)} {reason} {Colors.GRAY}│{Colors.RESET} {Colors.TEAL}{command}{Colors.RESET}")
                confirm = styled_input(f"  {Colors.BOLD}Confirm execution? (y/n):{Colors.RESET} ").strip().lower()
                if confirm not in ['y', 'yes']: return "Command Aborted."
            else:
                fake_loading(f"Safety Audit: {command[:30]}...", duration=0.4)
                check_resp = ollama.chat(model=self.model_name, messages=[{'role': 'user', 'content': f"Is this command safe? '{command}'. Reply ONLY 'SAFE' or 'UNSAFE'."}])
                audit_result = check_resp['message']['content'].strip().upper()
                if "SAFE" not in audit_result or "UNSAFE" in audit_result:
                    print(f"\n  {status_label('WARN', Colors.ORANGE)} AI Audit UNSAFE {Colors.GRAY}│{Colors.RESET} {Colors.TEAL}{command}{Colors.RESET}")
                    confirm = styled_input(f"  {Colors.BOLD}Confirm execution? (y/n):{Colors.RESET} ").strip().lower()
                    if confirm not in ['y', 'yes']: return "Command Aborted."
                else: print(f"\n  {status_label('AUTO SAFE', Colors.GREEN)} AI Audit Passed {Colors.GRAY}│{Colors.RESET} {Colors.TEAL}{command}{Colors.RESET}")
            log_tool(f"SYSTEM_EXEC: {command}")
            interrupter.start_listening()
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            output = []
            print(f"\n  {frame_title('EXEC OUTPUT', Colors.MAGENTA)}")
            panel_open = True
            last_out = time.time()
            while True:
                if interrupter.interrupted.is_set():
                    process.terminate()
                    print_frame_line(status_label('INTERRUPTED', Colors.RED))
                    if panel_open:
                        close_panel()
                        panel_open = False
                    interrupter.stop_listening()
                    return "Command interrupted."
                
                rlist, _, _ = select.select([process.stdout], [], [], 1.0)
                if rlist:
                    line = process.stdout.readline()
                    if line:
                        print_frame_text(line)
                        output.append(line)
                        last_out = time.time()
                        continue
                
                
                if process.poll() is not None: break
                if time.time() - last_out > 60:
                    process.terminate()
                    if panel_open:
                        close_panel()
                        panel_open = False
                    interrupter.stop_listening()
                    return f"Command Timed Out (60s silence). If this was interactive, use 'test_cmd'. Output so far:\n" + "".join(output)

            process.stdout.close()
            process.wait()
            if panel_open:
                close_panel()
            interrupter.stop_listening()
            return f"Command Output:\n" + "".join(output)
        except Exception as e:
            interrupter.stop_listening()
            return f"Command Failed: {str(e)}"

    def test_cmd(self, command):
        try:
            def close_panel():
                print(f"  {frame_bottom(Colors.MAGENTA)}")

            if self.active_process and self.active_process.poll() is None: self.active_process.terminate()
            log_tool(f"TEST_EXEC (PTY): {command}")
            interrupter.start_listening()
            self.active_master, slave = pty.openpty()
            self.active_process = subprocess.Popen(command, shell=True, stdout=slave, stderr=slave, stdin=slave, text=True, close_fds=True)
            os.close(slave)
            fcntl.fcntl(self.active_master, fcntl.F_SETFL, os.O_NONBLOCK)
            output = []
            print(f"\n  {frame_title('TEST EXEC OUTPUT', Colors.MAGENTA)}")
            panel_open = True
            last_output_time = time.time()
            while True:
                if interrupter.interrupted.is_set():
                    self.active_process.terminate()
                    os.close(self.active_master)
                    self.active_master = None
                    print_frame_line(status_label('INTERRUPTED', Colors.RED))
                    if panel_open:
                        close_panel()
                        panel_open = False
                    interrupter.stop_listening()
                    return "Test interrupted."
                try:
                    data = os.read(self.active_master, 1024).decode(errors='ignore')
                    if data:
                        print_frame_text(data)
                        output.append(data)
                        last_output_time = time.time()
                except (BlockingIOError, OSError): pass
                if self.active_process.poll() is not None: break
                if time.time() - last_output_time > 5:
                    print_frame_line(f"{status_label('LIVE FEEDBACK', Colors.ORANGE)} Process waiting for input...")
                    if panel_open:
                        close_panel()
                        panel_open = False
                    interrupter.stop_listening()
                    buffer = "".join(output[-1000:])
                    return f"LIVE_FEEDBACK (Process waiting for input):\n{buffer}\nUse 'send_input' to interact."
                time.sleep(0.1)
            os.close(self.active_master)
            self.active_master = None
            if panel_open:
                close_panel()
            interrupter.stop_listening()
            return f"Test Completed. Output:\n" + "".join(output)
        except Exception as e:
            interrupter.stop_listening()
            return f"Error: {str(e)}"

    def download_mlx_model(self, repo_id):
        try:
            log_tool(f"Downloading MLX Model: {repo_id}")
            cmd = f"hf download {shlex.quote(repo_id)}"
            return self.run_cmd(cmd)
        except Exception as e: return f"Error: {str(e)}"

    def send_input(self, text):
        try:
            if not self.active_process or self.active_process.poll() is not None or self.active_master is None:
                return "Error: No active PTY process to send input to."
            log_info(f"Sending Input: {text}")
            os.write(self.active_master, (text + "\n").encode())
            time.sleep(0.5)
            output = []
            try:
                while True:
                    data = os.read(self.active_master, 4096).decode(errors='ignore')
                    if data:
                        sys.stdout.write(data)
                        sys.stdout.flush()
                        output.append(data)
                    else: break
            except (BlockingIOError, OSError): pass
            return f"Input sent. New Output:\n" + "".join(output) if output else "Input sent."
        except Exception as e: return f"Error: {str(e)}"

    def list_files(self, path="."):
        try:
            log_tool(f"Listing Files: {path}")
            res = []
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.venv', 'venv']]
                level = root.replace(path, '').count(os.sep)
                if level > 3: continue
                indent = '  ' * level
                res.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = '  ' * (level + 1)
                for f in files: res.append(f"{sub_indent}{f}")
            result = "\n".join(res)
            print(f"\n  {frame_title('FILE TREE', Colors.MAGENTA)}\n{result}\n  {frame_bottom(Colors.MAGENTA)}\n")
            return result
        except Exception as e: return f"Error: {str(e)}"

    def search_files(self, query, path="."):
        try:
            log_tool(f"Searching Files: {query}")
            return self.run_cmd(f"find {path} -maxdepth 4 -name '*{query}*' ! -path '*/.git/*' ! -path '*/__pycache__/*'")
        except Exception as e: return f"Error: {str(e)}"

    def grep(self, pattern, path="."):
        try:
            log_tool(f"Grep: {pattern}")
            return self.run_cmd(f"grep -rIn '{pattern}' {path} --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=node_modules | head -n 50")
        except Exception as e: return f"Error: {str(e)}"

    def git_status(self):
        try:
            log_tool("Git Status")
            return self.run_cmd("git status --short")
        except Exception as e: return f"Error: {str(e)}"

    def git_diff(self, path=""):
        try:
            log_tool(f"Git Diff{': ' + path if path else ''}")
            cmd = f"git diff {path}" if path else "git diff"
            return self.run_cmd(cmd)
        except Exception as e: return f"Error: {str(e)}"

    def web_search(self, query, num_results=20):
        try:
            requested_domains = extract_allowed_domains(query)
            if not requested_domains and should_search_official_domains(query): requested_domains = ALLOWED_SEARCH_DOMAINS.copy()
            search_queries = [query]
            if requested_domains:
                clean_query = query
                for domain in requested_domains: clean_query = re.sub(rf"\b{re.escape(domain)}\b", "", clean_query, flags=re.IGNORECASE)
                clean_query = re.sub(r"\s+", " ", clean_query).strip()
                search_queries = [f"{clean_query} site:{domain}" for domain in requested_domains]
            log_tool(f"Searching Web: {query}")
            collected, seen_urls = [], set()
            with DDGS() as ddgs:
                for search_query in search_queries:
                    try:
                        results = list(ddgs.text(search_query, region='wt-wt', safesearch='moderate', max_results=num_results))
                        for result in results:
                            href = result.get('href', '')
                            if not href or href in seen_urls or not domain_matches(href, requested_domains): continue
                            seen_urls.add(href)
                            collected.append(result)
                            if len(collected) >= num_results: break
                    except: continue
                    if len(collected) >= num_results: break
            if not collected and requested_domains:
                log_info("No results found with site filter. Trying broad search...")
                with DDGS() as ddgs:
                    try:
                        results = list(ddgs.text(query, region='wt-wt', safesearch='moderate', max_results=num_results))
                        for result in results:
                            href = result.get('href', '')
                            if not href or href in seen_urls: continue
                            seen_urls.add(href)
                            collected.append(result)
                            if len(collected) >= num_results: break
                    except: pass
            if not collected: return "No results found."
            formatted_results = "\n".join([f"- {r['title']}: {r['body']} ({r['href']})" for r in collected])
            print(f"\n  {frame_title('SEARCH RESULTS', Colors.MAGENTA)}\n{render_text(formatted_results)}\n  {frame_bottom(Colors.MAGENTA)}\n")
            return f"Search Results:\n{formatted_results}"
        except Exception as e: return f"Error: {str(e)}"

    def read_url(self, url):
        try:
            log_tool(f"Fetching URL: {url}")
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            text = r.text
            text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            print(f"\n  {frame_title('URL CONTENT', Colors.MAGENTA)}\n  {Colors.GRAY}{url}{Colors.RESET}\n\n{render_text(truncate_output(text))}\n  {frame_bottom(Colors.MAGENTA)}\n")
            return truncate_output(text)
        except Exception as e: return f"Error fetching URL: {str(e)}"

    def read_file(self, path):
        try:
            if os.path.isdir(path): return f"Error: '{path}' is a directory. Use 'ls' to list its contents."
            log_tool(f"Reading: {path}")
            with open(path, 'r') as f:
                content = f.read()
                print(f"\n  {frame_title(f'FILE: {path}', Colors.MAGENTA)}\n{render_text(truncate_output(content))}\n  {frame_bottom(Colors.MAGENTA)}\n")
                return content
        except Exception as e: return f"Error: {str(e)}"

    def write_file(self, path, content):
        try:
            log_tool(f"Writing: {path}")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            old_content = ""
            if os.path.exists(path):
                with open(path, 'r') as f: old_content = f.read()
            with open(path, 'w') as f: f.write(content)
            if old_content:
                diff = list(difflib.unified_diff(old_content.splitlines(keepends=True), content.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))
                if diff: print_diff(diff)
                return f"File updated. Diff shown."
            return f"File created."
        except Exception as e: return f"Error: {str(e)}"

    def print_tasks(self):
        if not self.tasks: return
        print(f"\n  {frame_title('PROGRESS CHECKPOINTS', Colors.TEAL)}")
        for i, task in enumerate(self.tasks):
            icon = f"{Colors.GRAY}○"
            if task['status'] == 'done': icon = f"{Colors.GREEN}✓"
            elif task['status'] == 'doing': icon = f"{Colors.ORANGE}◆"
            print(f"    {icon} {Colors.RESET}{i+1}. {task['text']}")
        print(f"  {frame_bottom(Colors.TEAL)}\n")

    def create_plan(self, plan):
        try:
            self.tasks = []
            lines = plan.split('\n')
            for line in lines:
                match = re.match(r'^\s*[\*\-\d\.]+\s*(.*)', line)
                if match and match.group(1).strip():
                    self.tasks.append({'text': match.group(1).strip(), 'status': 'todo'})
            
            print(f"\n  {frame_title('IMPLEMENTATION PLAN', Colors.GREEN)}")
            print(render_text(plan))
            print(f"  {frame_bottom(Colors.GREEN)}")
            self.print_tasks()
            print(f"  {Colors.YELLOW}{Colors.BOLD}Awaiting your approval or feedback to proceed...{Colors.RESET}")
            feedback = styled_input(f"  {Colors.BOLD}Feedback (Enter to approve):{Colors.RESET} ").strip()
            if not feedback:
                return "Plan approved. Start by marking the first task as 'doing' using update_task."
            return f"User feedback: {feedback}. Adjust the plan or address it."
        except Exception as e: return f"Error: {str(e)}"

    def update_task(self, index, status):
        try:
            idx = int(index) - 1
            if 0 <= idx < len(self.tasks):
                self.tasks[idx]['status'] = status
                self.print_tasks()
                return f"Task {index} updated to {status}."
            return f"Invalid task index: {index}"
        except Exception as e: return f"Error: {str(e)}"

    def setup_llama_cpp(self):
        log_info("Starting llama.cpp Automation Setup for macOS...")
        
        try:
            subprocess.check_call(["clang", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            print(f"  {status_label('ERROR', Colors.RED)} Xcode Command Line Tools not found.")
            print(f"  {status_label('FIX', Colors.ORANGE)} Run: {Colors.WHITE}xcode-select --install{Colors.RESET}")
            return "Setup aborted: Xcode tools missing."

        brew_check = subprocess.run(["which", "brew"], capture_output=True, text=True)
        if brew_check.returncode != 0:
            log_info("Installing Homebrew...")
            self.run_cmd('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
        
        log_info("Installing dependencies (git, cmake)...")
        self.run_cmd("brew install git cmake")

        if not os.path.exists("llama.cpp"):
            log_info("Cloning llama.cpp repository...")
            self.run_cmd("git clone https://github.com/ggerganov/llama.cpp")
        
        log_info("Building llama.cpp with Metal acceleration...")
        build_cmd = "cd llama.cpp && cmake -B build -DGGML_METAL=ON && cmake --build build --config Release"
        self.run_cmd(build_cmd)

        log_info("Setting up models directory and downloading a starter model...")
        model_setup = "mkdir -p llama.cpp/models && curl -L -o llama.cpp/models/qwen2.5-coder-1.5b.gguf 'https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf'"
        self.run_cmd(model_setup)

        log_info("llama.cpp setup complete!")
        print(f"\n  {status_label('SUCCESS', Colors.GREEN)} llama.cpp is ready!")
        print(f"  {Colors.CYAN}To start the server:{Colors.RESET} cd llama.cpp && ./build/bin/llama-server -m models/qwen2.5-coder-1.5b.gguf")
        print(f"  {Colors.CYAN}To use with OCLI:{Colors.RESET} python3 OCLI.py --backend llama-cpp --model qwen2.5-coder-1.5b")
        return "llama.cpp setup successful."

    def setup_mlx(self):
        log_info("Starting MLX Automation Setup for macOS...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "mlx-lm", "huggingface_hub", "--break-system-packages"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"  {status_label('ERROR', Colors.RED)} Failed to install mlx-lm: {e}")
            return "Setup failed."

        log_info("Downloading recommended MLX model (Qwen2.5-Coder-7B-Instruct)...")
        model_name = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
        try:
            self.run_cmd(f"{sys.executable} -m huggingface_hub.commands.cli download {model_name}")
        except Exception as e:
            log_info(f"Model download check failed: {e}")

        log_info("MLX setup complete!")
        print(f"\n  {status_label('SUCCESS', Colors.GREEN)} MLX (mlx-lm) is ready!")
        print(f"  {Colors.CYAN}To start the server:{Colors.RESET} python3 -m mlx_lm.server --model {model_name}")
        print(f"  {Colors.CYAN}To use with OCLI:{Colors.RESET} python3 OCLI.py --backend mlx --model {model_name}")
        return "MLX setup successful."

    def save_session(self, path=None):
        try:
            if not path:
                path = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(path, 'w') as f:
                json.dump(self.messages, f, indent=2)
            log_info(f"Session saved to {path}")
            return f"Session saved to {path}"
        except Exception as e: return f"Error saving session: {str(e)}"

    def load_session(self, path):
        try:
            if not os.path.exists(path):
                return f"File not found: {path}"
            with open(path, 'r') as f:
                self.messages = json.load(f)
            log_info(f"Session loaded from {path}")
            return f"Session loaded from {path}"
        except Exception as e: return f"Error loading session: {str(e)}"

    def display_metrics(self, response):
        if self.backend == 'ollama':
            duration = response.get('total_duration', 0) / 1e9
            p_tokens = response.get('prompt_eval_count', 0)
            e_tokens = response.get('eval_count', 0)
            if duration > 0: print(f"  {status_label('STATS', Colors.GRAY)} {duration:.2f}s {Colors.GRAY}│{Colors.RESET} IN {p_tokens} {Colors.GRAY}│{Colors.RESET} OUT {e_tokens}{Colors.RESET}")
        else:
            print(f"  {status_label('STATS', Colors.GRAY)} Request completed.{Colors.RESET}")

    def compact_message_text(self, message):
        role = message.get('role', 'unknown')
        name = message.get('name') or message.get('tool_call_id') or ""
        content = str(message.get('content', '') or "")
        tool_calls = message.get('tool_calls') or []
        header = f"{role.upper()}{' ' + name if name else ''}"
        if tool_calls:
            calls = []
            for call in tool_calls:
                fn = call.get('function', {}) if isinstance(call, dict) else {}
                calls.append(f"{fn.get('name', 'unknown')}({fn.get('arguments', {})})")
            content = (content + "\nTool calls: " + "; ".join(calls)).strip()
        content = re.sub(r"\s+", " ", content).strip()
        if len(content) > COMPACT_MAX_MESSAGE_CHARS:
            content = content[:COMPACT_MAX_MESSAGE_CHARS] + " ... [trimmed]"
        return f"{header}: {content}" if content else f"{header}: [empty]"

    def compact_source_text(self, messages):
        return "\n".join(self.compact_message_text(message) for message in messages)

    def recent_context_slice(self):
        recent = self.messages[-COMPACT_RECENT_MESSAGES:]
        while recent and recent[0].get('role') == 'tool':
            recent = recent[1:]
        return recent

    def fallback_compaction_summary(self, messages):
        users = [m.get('content', '') for m in messages if m.get('role') == 'user']
        tools = [m.get('name', '') for m in messages if m.get('role') == 'tool' and m.get('name')]
        last_goal = users[-1] if users else self.last_user_goal
        tool_list = ", ".join(dict.fromkeys(tools[-12:])) if tools else "none"
        return (
            f"Goal: {last_goal or 'Continue the current task.'}\n"
            f"State: Conversation was compacted after {len(messages)} older messages.\n"
            f"Files: Preserve details from the recent context below.\n"
            f"Commands: Recent tool usage included {tool_list}.\n"
            f"Decisions: Continue from the preserved recent messages and avoid repeating blocked calls.\n"
            f"Next Steps: Inspect current context, continue the user's latest request, and verify changes."
        )

    def request_compaction_summary(self, messages):
        source = self.compact_source_text(messages)
        prompt = (
            "Create a compact working-memory summary for an autonomous coding CLI. "
            "Preserve only durable facts needed to continue accurately. "
            "Include these labels exactly: Goal, State, Files, Commands, Decisions, Failures, Next Steps. "
            "Mention concrete filenames, commands, test results, backend/model changes, and unresolved risks when present. "
            "Do not include hidden reasoning or generic narration.\n\n"
            f"Conversation to compact:\n{source}"
        )
        if self.backend == 'ollama':
            response = ollama.chat(model=self.model_name, messages=[{'role': 'user', 'content': prompt}])
            return response['message']['content'].strip()
        response = requests.post(
            f"{self.url}/v1/chat/completions",
            json={"model": self.model_name, "messages": [{'role': 'user', 'content': prompt}], "temperature": 0.1},
            timeout=60
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()

    def compact_history(self):
        if len(self.messages) > HISTORY_THRESHOLD:
            log_info("History threshold reached. Compacting...")
            system_msg = self.messages[0]
            recent_context = self.recent_context_slice()
            middle_end = len(self.messages) - len(recent_context)
            middle_messages = self.messages[1:middle_end]
            try:
                summary = self.request_compaction_summary(middle_messages)
            except Exception as e:
                log_info(f"Compaction model failed ({e}). Using local summary.")
                summary = self.fallback_compaction_summary(middle_messages)
            self.compaction_count += 1
            memory = (
                f"Working memory summary #{self.compaction_count}:\n{summary}\n\n"
                f"Current backend: {self.backend}\n"
                f"Current model: {self.model_name}\n"
                f"Auto mode: {'ON' if self.auto_mode else 'OFF'}\n"
                f"Planning: {'ENABLED' if self.planning_enabled else 'DISABLED'}"
            )
            self.messages = [system_msg, {'role': 'assistant', 'content': memory}] + recent_context
            log_info(f"Compaction successful. Preserved {len(recent_context)} recent messages.")

    def run(self):
        print_logo()
        print_panel("SESSION", [
            f"{Colors.TEAL}Model{Colors.RESET}      {self.model_name}",
            f"{Colors.TEAL}Backend{Colors.RESET}    {self.backend}",
            f"{Colors.TEAL}Auto Mode{Colors.RESET}  {mode_value(self.auto_mode)}",
            f"{Colors.GRAY}Type {Colors.WHITE}exit{Colors.GRAY} to quit or {Colors.WHITE}/help{Colors.GRAY} for commands.{Colors.RESET}"
        ], Colors.TEAL)
        while True:
            try:
                print(soft_rule(Colors.VIOLET))
                user_input = styled_input(f"\n  {Colors.VIOLET}{Colors.BOLD}╭─ OCLI{Colors.RESET} {Colors.GRAY}{self.backend}:{Colors.RESET}{Colors.TEAL}{self.model_name}{Colors.RESET}\n  {Colors.VIOLET}{Colors.BOLD}╰─>{Colors.RESET} ").strip()
                print("")
                print(soft_rule(Colors.VIOLET))
                if not user_input: continue
                if user_input.startswith('/'):
                    cmd_parts = user_input.split()
                    cmd = cmd_parts[0].lower()
                    if cmd == '/exit' or cmd == '/quit': break
                    elif cmd == '/auto':
                        self.auto_mode = not self.auto_mode
                        log_info(f"Auto-mode is now {mode_value(self.auto_mode)}")
                        continue
                    elif cmd == '/plan':
                        self.planning_enabled = not self.planning_enabled
                        log_info(f"Planning mode is now {mode_value(self.planning_enabled, 'ENABLED', 'DISABLED')}")
                        if self.planning_enabled:
                            if "Planning is DISABLED. Do not use create_plan tool unless planning is explicitly enabled." in self.messages[0]['content']:
                                self.messages[0]['content'] = self.messages[0]['content'].replace("Planning is DISABLED. Do not use create_plan tool unless planning is explicitly enabled.", self.PLAN_PROMPT)
                            elif self.PLAN_PROMPT not in self.messages[0]['content']:
                                self.messages[0]['content'] += " " + self.PLAN_PROMPT
                        else:
                            self.messages[0]['content'] = self.messages[0]['content'].replace(self.PLAN_PROMPT, "Planning is DISABLED. Do not use create_plan tool unless planning is explicitly enabled.")
                        continue
                    elif cmd == '/save':
                        path = cmd_parts[1] if len(cmd_parts) > 1 else None
                        self.save_session(path)
                        continue
                    elif cmd == '/load':
                        if len(cmd_parts) < 2:
                            log_info("Usage: /load <filename>")
                            continue
                        self.load_session(cmd_parts[1])
                        continue
                    elif cmd == '/status':
                        print_panel("STATUS", [
                            f"{Colors.TEAL}Model{Colors.RESET}      {self.model_name}",
                            f"{Colors.TEAL}Backend{Colors.RESET}    {self.backend}",
                            f"{Colors.TEAL}Auto Mode{Colors.RESET}  {mode_value(self.auto_mode)}",
                            f"{Colors.TEAL}Planning{Colors.RESET}   {mode_value(self.planning_enabled, 'ENABLED', 'DISABLED')}",
                            f"{Colors.TEAL}History{Colors.RESET}    {len(self.messages)} messages",
                            f"{Colors.TEAL}Compacted{Colors.RESET}  {self.compaction_count} times"
                        ], Colors.TEAL)
                        continue
                    elif cmd == '/backend':
                        if len(cmd_parts) > 1 and cmd_parts[1] in BACKEND_DEFAULT_URLS:
                            url = cmd_parts[2] if len(cmd_parts) > 2 else None
                            self.set_backend(cmd_parts[1], url, keep_model=False)
                        else:
                            self.backend_menu()
                        continue
                    elif cmd == '/model':
                        if len(cmd_parts) > 1:
                            self.model_name = " ".join(cmd_parts[1:])
                            if self.backend == 'mlx':
                                self.cleanup()
                                self.ensure_mlx_server()
                            log_info(f"Model switched to {Colors.TEAL}{self.model_name}{Colors.RESET}")
                        else:
                            self.model_menu()
                        continue
                    elif cmd == '/tasks':
                        self.print_tasks()
                        continue
                    elif cmd == '/help':
                        print_panel("COMMANDS", [
                            f"{Colors.CYAN}/status{Colors.RESET}       {Colors.GRAY}Show model and backend status{Colors.RESET}",
                            f"{Colors.CYAN}/help{Colors.RESET}         {Colors.GRAY}Show this command deck{Colors.RESET}",
                            f"{Colors.CYAN}/backend{Colors.RESET}      {Colors.GRAY}Open the backend switcher{Colors.RESET}",
                            f"{Colors.CYAN}/model{Colors.RESET}        {Colors.GRAY}Open the model switcher{Colors.RESET}",
                            f"{Colors.CYAN}/download_model{Colors.RESET} {Colors.GRAY}Download a model for the active backend{Colors.RESET}",
                            f"{Colors.CYAN}/auto{Colors.RESET}         {Colors.GRAY}Toggle auto-execution mode{Colors.RESET}",
                            f"{Colors.CYAN}/plan{Colors.RESET}         {Colors.GRAY}Toggle autonomous planning mode{Colors.RESET}",
                            f"{Colors.CYAN}/tasks{Colors.RESET}        {Colors.GRAY}Show progress checkpoints{Colors.RESET}",
                            f"{Colors.CYAN}/save [file]{Colors.RESET}  {Colors.GRAY}Save current session to JSON{Colors.RESET}",
                            f"{Colors.CYAN}/load <file>{Colors.RESET}  {Colors.GRAY}Load a session from JSON{Colors.RESET}",
                            f"{Colors.CYAN}/setup_mlx{Colors.RESET}    {Colors.GRAY}Install and download MLX models{Colors.RESET}",
                            f"{Colors.CYAN}/download <r>{Colors.RESET} {Colors.GRAY}Download an MLX model from Hugging Face{Colors.RESET}",
                            f"{Colors.CYAN}/exit{Colors.RESET}         {Colors.GRAY}Quit OCLI{Colors.RESET}",
                            "",
                            f"{Colors.GRAY}Tools like read_url and web_search are used automatically during exploration.{Colors.RESET}"
                        ], Colors.VIOLET)
                        continue
                    elif cmd == '/setup':
                        self.setup_llama_cpp()
                        continue
                    elif cmd == '/setup_mlx':
                        self.setup_mlx()
                        continue
                    elif cmd == '/download':
                        if len(cmd_parts) < 2:
                            log_info("Usage: /download <repo_id>")
                            continue
                        self.download_mlx_model(cmd_parts[1])
                        continue
                    elif cmd == '/download_model':
                        self.download_model_menu(" ".join(cmd_parts[1:]) if len(cmd_parts) > 1 else None)
                        continue
                    else:
                        log_info(f"Unknown command: {cmd}")
                        continue

                if user_input.lower() in ['exit', 'quit']: break
                if user_input.lower() in ['continue', 'c']:
                    if len(self.messages) > 1: user_input = "Please continue."
                    else: continue
                self.last_user_goal = user_input
                self.last_tool_signature = None
                self.repeated_tool_count = 0
                self.last_failure_signature = None
                self.repeated_failure_count = 0
                self.tool_steps_this_turn = 0
                self.messages.append({'role': 'user', 'content': user_input})
                auto_count = 0
                while auto_count < 10:
                    self.compact_history()
                    had_tools = self.process_chat()
                    last_msg = self.messages[-1].get('content', '') if self.messages else ""
                    should_continue = (
                        (had_tools and self.auto_mode)
                        or ("CONTINUE" in last_msg.upper() and auto_count < 3)
                        or (self.messages[-1].get('role') == 'tool' and auto_count < 3)
                    )
                    if should_continue:
                        auto_count += 1
                        print(f"\n  {status_label('AUTO', Colors.ORANGE)} Continuing step {auto_count}/10")
                        self.messages.append({'role': 'user', 'content': f"Continue the original task and make concrete progress toward completion. Original request:\n{self.last_user_goal}\nDo not repeat the same command/read cycle. If implementation is incomplete, write the full files now. If files are written, run pytest. If tests pass, summarize final files and usage."})
                    else:
                        break
            except KeyboardInterrupt: break

    def process_chat(self):
        had_tool_calls = False
        available_tools = {'run_cmd': self.run_cmd, 'read_file': self.read_file, 'write_file': self.write_file, 'web_search': self.web_search, 'create_plan': self.create_plan, 'update_task': self.update_task, 'test_cmd': self.test_cmd, 'send_input': self.send_input, 'read_url': self.read_url, 'download_mlx_model': self.download_mlx_model, 'list_files': self.list_files, 'search_files': self.search_files, 'grep': self.grep, 'git_status': self.git_status, 'git_diff': self.git_diff}
        while True:
            try:
                interrupter.start_listening()
                tools = [
                    {'type': 'function', 'function': {'name': 'run_cmd', 'description': 'Run shell command', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
                    {'type': 'function', 'function': {'name': 'web_search', 'description': 'Search web via DuckDuckGo. Use authoritative domains for official-source searches.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'num_results': {'type': 'integer', 'default': 10}}, 'required': ['query']}}},
                    {'type': 'function', 'function': {'name': 'read_url', 'description': 'Fetch and read the text content of a URL.', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
                    {'type': 'function', 'function': {'name': 'download_mlx_model', 'description': 'Download an MLX model from Hugging Face.', 'parameters': {'type': 'object', 'properties': {'repo_id': {'type': 'string'}}, 'required': ['repo_id']}}},
                    {'type': 'function', 'function': {'name': 'read_file', 'description': 'Read file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}},
                    {'type': 'function', 'function': {'name': 'write_file', 'description': 'Write file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}}},
                    {'type': 'function', 'function': {'name': 'test_cmd', 'description': 'Run command with live feedback (use for interactive tests or long processes).', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
                    {'type': 'function', 'function': {'name': 'send_input', 'description': 'Send text input to the active test process.', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}},
                    {'type': 'function', 'function': {'name': 'list_files', 'description': 'List files and directories in a path (tree view, max depth 3).', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string', 'default': '.'}}, 'required': []}}},
                    {'type': 'function', 'function': {'name': 'search_files', 'description': 'Find files by name pattern.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'path': {'type': 'string', 'default': '.'}}, 'required': ['query']}}},
                    {'type': 'function', 'function': {'name': 'grep', 'description': 'Search file contents for a pattern (like grep -rIn).', 'parameters': {'type': 'object', 'properties': {'pattern': {'type': 'string'}, 'path': {'type': 'string', 'default': '.'}}, 'required': ['pattern']}}},
                    {'type': 'function', 'function': {'name': 'git_status', 'description': 'Show git status of the current repo.', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
                    {'type': 'function', 'function': {'name': 'git_diff', 'description': 'Show git diff of changes. Optionally for a specific file.', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string', 'default': ''}}, 'required': []}}},
                ]
                if self.planning_enabled:
                    tools.append({'type': 'function', 'function': {'name': 'create_plan', 'description': 'Create an implementation plan before performing complex tasks.', 'parameters': {'type': 'object', 'properties': {'plan': {'type': 'string'}}, 'required': ['plan']}}})
                    tools.append({'type': 'function', 'function': {'name': 'update_task', 'description': 'Update the status of a task in the current plan.', 'parameters': {'type': 'object', 'properties': {'index': {'type': 'string', 'description': 'The 1-based index of the task'}, 'status': {'type': 'string', 'enum': ['todo', 'doing', 'done']}}, 'required': ['index', 'status']}}})

                spinner = Spinner(f"{self.backend.capitalize()} generating")
                spinner.start()
                
                content, tool_calls, response_metadata = "", [], {}
                first_chunk = True
                in_thought, in_tool, thought_labeled, line_buffer = False, False, False, ""
                tags_to_hide = ["<thought>", "</thought>", "<tools>", "</tools>", "<tool_call>", "</tool_call>", "<response>", "</response>", "<result>", "</result>", "```json", "```", "Thought:", "THINKING:", "<|im_end|>", "<|im_start|>", "<|endoftext|>"]

                def process_token(token):
                    nonlocal first_chunk, in_thought, in_tool, thought_labeled, line_buffer, content
                    content += token
                    
                    if first_chunk and token.strip():
                        spinner.stop()
                        print(f"\n{Colors.TEAL}{Colors.BOLD}◆ OCLI{Colors.RESET} {Colors.GRAY}›{Colors.RESET} ", end="", flush=True)
                        first_chunk = False

                    for tag in tags_to_hide:
                        if tag in content and tag not in content[:-len(token)]:
                            if tag.startswith("</") or tag == "```":
                                if in_thought and tag == "</thought>": in_thought = False
                                if in_tool: in_tool = False
                            else:
                                if tag in ["<thought>", "Thought:", "THINKING:"]:
                                    in_thought = True
                                    if not thought_labeled:
                                        print(f"{Colors.ORANGE}{Colors.BOLD}thinking{Colors.RESET}", end="", flush=True)
                                        thought_labeled = True
                                else: in_tool = True
                    
                    if not in_thought and not in_tool:
                        line_buffer += token
                        for tag in tags_to_hide: line_buffer = line_buffer.replace(tag, "")
                        
                        is_potential_tag = any(line_buffer.endswith(tag[:i]) for tag in tags_to_hide for i in range(1, len(tag)))
                        if not is_potential_tag and "\n" in line_buffer:
                            parts = line_buffer.split("\n")
                            for i in range(len(parts)-1): print(render_text(parts[i] + "\n"), end="", flush=True)
                            line_buffer = parts[-1]

                if self.backend == 'ollama':
                    stream = ollama.chat(model=self.model_name, messages=self.messages, stream=True, tools=tools)
                    for chunk in stream:
                        if interrupter.interrupted.is_set(): break
                        msg = chunk.get('message', {})
                        if 'content' in msg: process_token(msg['content'])
                        if 'tool_calls' in msg: tool_calls.extend(msg['tool_calls'])
                        if 'total_duration' in chunk: response_metadata = chunk
                else:
                    payload = {"model": self.model_name, "messages": self.messages, "stream": True, "tools": tools}
                    r = requests.post(f"{self.url}/v1/chat/completions", json=payload, stream=True)
                    if r.status_code != 200:
                        log_info(f"Server Error ({r.status_code}): {r.text}")
                        break
                    log_info(f"Connected to {self.backend} server. Awaiting response...")
                    for line in r.iter_lines():
                        if interrupter.interrupted.is_set(): break
                        if not line: continue
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            if line.strip() == 'data: [DONE]': break
                            data = json.loads(line[6:])
                            delta = data['choices'][0].get('delta', {})
                            if 'content' in delta and delta['content']: process_token(delta['content'])
                            if 'tool_calls' in delta:
                                for tc in delta['tool_calls']:
                                    idx = tc.get('index', 0)
                                    while len(tool_calls) <= idx: tool_calls.append({'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                                    if 'id' in tc: tool_calls[idx]['id'] += tc['id']
                                    if 'function' in tc:
                                        if 'name' in tc['function']: tool_calls[idx]['function']['name'] += tc['function']['name']
                                        if 'arguments' in tc['function']: tool_calls[idx]['function']['arguments'] += tc['function']['arguments']
                
                spinner.stop()
                if line_buffer and not in_thought: print(render_text(line_buffer), end="", flush=True)
                print()
                
                if not tool_calls:
                    tool_matches = re.findall(r'<(?:tools|tool_call|response)>(.*?)(?:</(?:tools|tool_call|response)>|$)', content, re.DOTALL)
                    if not tool_matches:
                        tool_matches = re.findall(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if not tool_matches:
                        for obj in extract_json_objects(content):
                            if '"name"' in obj and '"arguments"' in obj:
                                tool_matches.append(obj.replace("{{", "{").replace("}}", "}"))
                    for match in tool_matches:
                        try:
                            data = json.loads(match.strip())
                            if isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict) and item.get('name'):
                                        tool_calls.append({'function': {'name': item.get('name'), 'arguments': item.get('arguments', {})}})
                            elif isinstance(data, dict) and data.get('name'):
                                tool_calls.append({'function': {'name': data.get('name'), 'arguments': data.get('arguments', {})}})
                        except Exception as e:
                            recovered = recover_tool_call_from_text(match.strip())
                            if recovered:
                                log_info("Recovered malformed tool JSON from model output")
                                tool_calls.append(recovered)
                            else:
                                log_info(f"Failed to parse tool JSON: {e}")

                    if not tool_calls:
                        recovered = recover_tool_call_from_text(content)
                        if recovered:
                            log_info("Recovered malformed tool JSON from full model output")
                            tool_calls.append(recovered)

                lower_content = content.lower()
                user_context = "\n".join(m.get('content', '') for m in self.messages[-3:] if m.get('role') == 'user').lower()
                fake_tool_markers = ['<tool_response>', '</tool_response>', 'running tasklite.py...', 'diff --git']
                tool_required_phrases = ['create ', 'write ', 'edit ', 'modify ', 'fix ', 'test ', 'run ', 'execute ', 'pytest', 'tasklite.py', 'devlog.py', 'test_devlog.py', 'readme.md']
                needs_real_tool = any(phrase in user_context for phrase in tool_required_phrases)
                appears_fake_tool_result = any(marker in lower_content for marker in fake_tool_markers)
                bare_continue = content.strip().upper() == "CONTINUE"
                hardware_queries = ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']
                if not tool_calls and any(term in user_context for term in hardware_queries):
                    log_info("Using deterministic hardware inspection command")
                    tool_calls.append({
                        'function': {
                            'name': 'run_cmd',
                            'arguments': {
                                'command': "system_profiler SPDisplaysDataType SPHardwareDataType | sed -n '/Chipset Model/p;/VRAM/p;/Total Number of Cores/p;/Memory:/p;/Model Name/p;/Chip/p'"
                            }
                        }
                    })
                elif not tool_calls and (needs_real_tool or appears_fake_tool_result or bare_continue):
                    self.messages.append({'role': 'assistant', 'content': content or ""})
                    self.messages.append({'role': 'user', 'content': "Continue the user's original task with the next required real tool call. Do not output bare CONTINUE. Do not describe or simulate tool output. Emit exactly one <tools>{...}</tools> call with complete JSON arguments."})
                    continue

                interrupter.stop_listening()
                if interrupter.interrupted.is_set():
                    self.messages.append({'role': 'assistant', 'content': content + " [USER INTERRUPTED]"})
                    break
                if tool_calls:
                    formatted_calls = []
                    for tc in tool_calls:
                        function_info = tc.get('function', {}) if isinstance(tc, dict) else {}
                        name = function_info.get('name')
                        args = function_info.get('arguments', {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args) if args.strip() else {}
                            except json.JSONDecodeError:
                                args = {}
                        if not isinstance(args, dict):
                            args = {}
                        if name:
                            formatted_calls.append({'id': tc.get('id', 'call_' + str(int(time.time()))), 'type': 'function', 'function': {'name': name, 'arguments': args}})
                    if formatted_calls:
                        self.messages.append({'role': 'assistant', 'content': content or "", 'tool_calls': formatted_calls})
                    else:
                        self.messages.append({'role': 'assistant', 'content': content or ""})
                else:
                    self.messages.append({'role': 'assistant', 'content': content or ""})
                thoughts = re.findall(r'<thought>(.*?)(?:</thought>|$)', content, flags=re.DOTALL)
                if thoughts and thoughts[0].strip():
                    print(f"\n{status_label('THINKING', Colors.ORANGE)}")
                    for t in thoughts: 
                        if t.strip(): print(f"{Colors.GRAY}  > {render_text(t.strip())}{Colors.RESET}")
                self.display_metrics(response_metadata)
                if not tool_calls: break
                valid_tool_calls = 0
                for tool in tool_calls:
                    try:
                        function_info = tool.get('function', {}) if isinstance(tool, dict) else {}
                        name = function_info.get('name')
                        args = function_info.get('arguments', {})
                        call_id = tool.get('id', 'call_' + str(int(time.time()))) if isinstance(tool, dict) else 'call_' + str(int(time.time()))

                        if name == 'create_plan' and not self.planning_enabled:
                            log_info("Ignoring create_plan because planning mode is disabled")
                            self.messages.append({'role': 'tool', 'content': "Planning mode is disabled. Continue the original task with write_file, test_cmd, or run_cmd instead of create_plan.", 'tool_call_id': call_id, 'name': name})
                            continue

                        if not name or name not in available_tools:
                            log_info(f"Ignoring invalid tool call: {name or 'missing tool name'}")
                            if any(term in self.last_user_goal.lower() for term in ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']):
                                log_info("Replacing invalid hardware tool call with deterministic run_cmd")
                                name = 'run_cmd'
                                args = {'command': "system_profiler SPDisplaysDataType SPHardwareDataType | sed -n '/Chipset Model/p;/VRAM/p;/Total Number of Cores/p;/Memory:/p;/Model Name/p;/Chip/p'"}
                            else:
                                continue

                        if isinstance(args, str):
                            try:
                                args = json.loads(args) if args.strip() else {}
                            except json.JSONDecodeError as e:
                                log_info(f"Ignoring malformed arguments for tool '{name}': {e}")
                                if name == 'run_cmd' and any(term in self.last_user_goal.lower() for term in ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']):
                                    log_info("Replacing malformed hardware run_cmd with deterministic command")
                                    args = {'command': "system_profiler SPDisplaysDataType SPHardwareDataType | sed -n '/Chipset Model/p;/VRAM/p;/Total Number of Cores/p;/Memory:/p;/Model Name/p;/Chip/p'"}
                                else:
                                    self.messages.append({'role': 'tool', 'content': f"Malformed tool arguments: {e}", 'tool_call_id': call_id, 'name': name})
                                    continue

                        if not isinstance(args, dict):
                            log_info(f"Ignoring invalid arguments for tool '{name}': expected object")
                            if name == 'run_cmd' and any(term in self.last_user_goal.lower() for term in ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']):
                                log_info("Replacing invalid hardware run_cmd arguments with deterministic command")
                                args = {'command': "system_profiler SPDisplaysDataType SPHardwareDataType | sed -n '/Chipset Model/p;/VRAM/p;/Total Number of Cores/p;/Memory:/p;/Model Name/p;/Chip/p'"}
                            else:
                                self.messages.append({'role': 'tool', 'content': "Invalid tool arguments: expected object", 'tool_call_id': call_id, 'name': name})
                                continue

                        tool_signature = json.dumps({'name': name, 'arguments': args}, sort_keys=True)
                        if tool_signature == self.last_tool_signature:
                            self.repeated_tool_count += 1
                        else:
                            self.last_tool_signature = tool_signature
                            self.repeated_tool_count = 0

                        if self.repeated_tool_count >= 2:
                            log_info(f"Blocking repeated tool call: {name}")
                            self.messages.append({'role': 'tool', 'content': "Repeated tool call blocked. Change strategy now: inspect the project tree with `find . -maxdepth 3 -type f`, read the relevant files, then fix the actual root cause. Do not repeat the same write/test cycle.", 'tool_call_id': call_id, 'name': name})
                            continue

                        if self.tool_steps_this_turn >= 50:
                            log_info("Stopping tool loop after 12 tool steps in one user turn")
                            self.messages.append({'role': 'tool', 'content': "Tool step limit reached for this turn. Stop looping and give the user a concise status report with the exact remaining failure and next manual fix.", 'tool_call_id': call_id, 'name': name})
                            break

                        result = truncate_output(available_tools[name](**args))
                        self.tool_steps_this_turn += 1

                        if name in ['test_cmd', 'run_cmd']:
                            failure_patterns = [
                                r'ModuleNotFoundError: No module named .+',
                                r'ImportError while importing test module .+',
                                r'collected 0 items / 1 error',
                                r'FAILED .+',
                                r'ERROR .+',
                            ]
                            matched_failure = None
                            for pattern in failure_patterns:
                                match = re.search(pattern, result)
                                if match:
                                    matched_failure = match.group(0)
                                    break
                            if matched_failure:
                                if matched_failure == self.last_failure_signature:
                                    self.repeated_failure_count += 1
                                else:
                                    self.last_failure_signature = matched_failure
                                    self.repeated_failure_count = 0

                                if self.repeated_failure_count >= 2:
                                    result += "\n\n[OCLI LOOP GUARD] The same failure has repeated. Do not rewrite the same test file or rerun the same command. First inspect the project tree with `find . -maxdepth 3 -type f`, then fix the actual package/import structure, such as missing __init__.py or wrong file placement."
                                    self.messages.append({'role': 'tool', 'content': result, 'tool_call_id': call_id, 'name': name})
                                    valid_tool_calls += 1
                                    had_tool_calls = True
                                    continue

                        self.messages.append({'role': 'tool', 'content': result, 'tool_call_id': call_id, 'name': name})
                        valid_tool_calls += 1
                        had_tool_calls = True
                    except TypeError as e:
                        tool_name = tool.get('function', {}).get('name', 'unknown') if isinstance(tool, dict) else 'unknown'
                        call_id = tool.get('id', 'call_' + str(int(time.time()))) if isinstance(tool, dict) else 'call_' + str(int(time.time()))
                        log_info(f"Tool '{tool_name}' was called with invalid arguments: {e}")
                        self.messages.append({'role': 'tool', 'content': f"Invalid tool arguments: {e}", 'tool_call_id': call_id, 'name': tool_name})
                    except Exception as e:
                        tool_name = tool.get('function', {}).get('name', 'unknown') if isinstance(tool, dict) else 'unknown'
                        call_id = tool.get('id', 'call_' + str(int(time.time()))) if isinstance(tool, dict) else 'call_' + str(int(time.time()))
                        log_info(f"Tool '{tool_name}' failed: {e}")
                        self.messages.append({'role': 'tool', 'content': f"Tool failed: {e}", 'tool_call_id': call_id, 'name': tool_name})

                if valid_tool_calls == 0:
                    if any(term in self.last_user_goal.lower() for term in ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']):
                        log_info("No valid hardware tool call was produced; running deterministic hardware command")
                        result = truncate_output(self.run_cmd("system_profiler SPDisplaysDataType SPHardwareDataType | sed -n '/Chipset Model/p;/VRAM/p;/Total Number of Cores/p;/Memory:/p;/Model Name/p;/Chip/p'"))
                        self.messages.append({'role': 'tool', 'content': result, 'tool_call_id': 'hardware_fallback_' + str(int(time.time())), 'name': 'run_cmd'})
                        return True
                    self.messages.append({'role': 'user', 'content': f"Your previous tool call was invalid, incomplete, or repetitive. Original request:\n{self.last_user_goal}\nRespond with one complete JSON tool call that advances the task, or give the final summary only if the task is actually complete."})
                    continue
                continue
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=BACKEND_DEFAULT_MODELS["ollama"])
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--backend", type=str, choices=['ollama', 'llama-cpp', 'mlx'], default="ollama")
    parser.add_argument("--url", type=str, help="Server URL (e.g. http://localhost:8080)")
    args = parser.parse_args()
    agent = OCLI(model_name=args.model, auto_mode=args.auto, backend=args.backend, url=args.url)
    agent.run()
