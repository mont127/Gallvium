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
import concurrent.futures
import contextlib
import io
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
    SKY = "\033[38;5;117m"
    EMERALD = "\033[38;5;78m"
    AMBER = "\033[38;5;220m"
    ROSE = "\033[38;5;204m"
    SLATE = "\033[38;5;245m"
    INDIGO = "\033[38;5;105m"
    MINT = "\033[38;5;121m"
    BG_DARK = "\033[48;5;236m"
    BG_PANEL = "\033[48;5;234m"
    BG_BADGE = "\033[48;5;238m"
    BG_ACCENT = "\033[48;5;54m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"

ACCENT = Colors.TEAL
MUTED = Colors.SLATE

def badge(text, fg=Colors.WHITE, bg=Colors.BG_BADGE):
    return f"{bg}{fg}{Colors.BOLD} {text} {Colors.RESET}"

def clean_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", str(text))

def clean_len(text):
    return len(clean_ansi(text))

def term_cols(default=100):
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default

LEFT_MARGIN = 2

def term_width(default=92):
    cols = term_cols(default + LEFT_MARGIN * 2)
    return max(60, cols - LEFT_MARGIN * 2)

def left_indent():
    return " " * LEFT_MARGIN

def center_pad(content_len):
    cols = term_cols()
    return " " * max(LEFT_MARGIN, (cols - content_len) // 2)

def frame_title(title, style=None, subtitle=None):
    style = style or MUTED
    width = term_width()
    label = f" {Colors.RESET}{Colors.BOLD}{Colors.WHITE}{title}{Colors.RESET}{style} "
    label_len = clean_len(f" {title} ")
    sub_len = 0
    sub = ""
    if subtitle:
        sub = f"{Colors.RESET}{Colors.DIM}{Colors.GRAY}{subtitle}{Colors.RESET}{style} "
        sub_len = clean_len(f"{subtitle} ")
    line = "─" * max(2, width - label_len - sub_len - 4)
    return f"{style}╭─{label}{sub}{line}─╮{Colors.RESET}"

def frame_bottom(style=None, hint=None):
    style = style or MUTED
    width = term_width()
    if hint:
        hint_text = f" {Colors.RESET}{Colors.DIM}{Colors.GRAY}{hint}{Colors.RESET}{style} "
        hint_len = clean_len(f" {hint} ")
        line = "─" * max(2, width - hint_len - 4)
        return f"{style}╰─{line}{hint_text}─╯{Colors.RESET}"
    return f"{style}╰{'─' * (width - 2)}╯{Colors.RESET}"

def status_label(text, style=None):
    style = style or ACCENT
    return f"{style}{Colors.BOLD}▎{Colors.RESET}{Colors.BOLD}{Colors.WHITE} {text} {Colors.RESET}"

def mode_value(enabled, on="on", off="off"):
    if enabled:
        return f"{ACCENT}●{Colors.RESET} {Colors.WHITE}{on}{Colors.RESET}"
    return f"{Colors.DIM}{Colors.GRAY}○ {off}{Colors.RESET}"

def soft_rule(style=None):
    style = style or Colors.GRAY
    return f"{left_indent()}{style}{Colors.DIM}{'─' * term_width()}{Colors.RESET}"

def kv_row(label, value, label_width=11):
    pad = max(0, label_width - clean_len(label))
    return f"{Colors.DIM}{Colors.GRAY}{label}{Colors.RESET}{' ' * pad}  {value}"

def print_panel(title, lines, style=Colors.CYAN):
    width = term_width()
    inner_width = width - 4
    indent = left_indent()
    print(f"{indent}{frame_title(title, style)}")
    for line in lines:
        chunks = str(line).splitlines() or [""]
        for chunk in chunks:
            pad = " " * max(0, inner_width - clean_len(chunk))
            print(f"{indent}{style}{Colors.BOLD}│{Colors.RESET} {chunk}{pad} {style}{Colors.BOLD}│{Colors.RESET}")
    print(f"{indent}{frame_bottom(style)}")

def print_frame_line(text="", style=Colors.MAGENTA):
    inner_width = term_width() - 4
    indent = left_indent()
    safe = clean_ansi(str(text)).replace("\r", "\n").replace("\t", "    ")
    safe = "".join(char if char == "\n" or ord(char) >= 32 else " " for char in safe)
    lines = safe.split("\n")
    if not lines:
        lines = [""]
    for line in lines:
        if line == "":
            print(f"{indent}{style}{Colors.BOLD}│{Colors.RESET} {' ' * inner_width} {style}{Colors.BOLD}│{Colors.RESET}")
            continue
        while line:
            chunk = line[:inner_width]
            line = line[inner_width:]
            pad = " " * max(0, inner_width - clean_len(chunk))
            print(f"{indent}{style}{Colors.BOLD}│{Colors.RESET} {chunk}{pad} {style}{Colors.BOLD}│{Colors.RESET}")

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
    indent = left_indent()
    lines = [f"{indent}{frame_title(title, style)}"]
    for visible_index, option in enumerate(visible):
        actual_index = offset + visible_index
        if actual_index == selected:
            entry = f"{ACCENT}{Colors.BOLD}❯{Colors.RESET} {Colors.WHITE}{Colors.BOLD}{option}{Colors.RESET}"
        else:
            entry = f"{Colors.DIM}{Colors.GRAY}  {option}{Colors.RESET}"
        pad = " " * max(0, inner_width - clean_len(entry))
        lines.append(f"{indent}{style}{Colors.BOLD}│{Colors.RESET} {entry}{pad} {style}{Colors.BOLD}│{Colors.RESET}")
    lines.append(f"{indent}{frame_bottom(style)}")
    hint_base = f"{Colors.DIM}{Colors.GRAY}↑↓ move · ⏎ select · 0/Esc cancel{Colors.RESET}"
    if limit and len(options) > limit:
        lines.append(f"{indent}{hint_base}  {Colors.DIM}{Colors.GRAY}· {offset + 1}-{offset + len(visible)}/{len(options)}{Colors.RESET}")
    else:
        lines.append(f"{indent}{hint_base}")
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
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + duration
    i = 0
    indent = left_indent()
    while time.time() < end_time:
        print(f"{indent}{ACCENT}{frames[i % len(frames)]}{Colors.RESET} {Colors.DIM}{Colors.GRAY}{msg}{Colors.RESET}", end="\r")
        time.sleep(0.06)
        i += 1
    print(f"{indent}{ACCENT}{Colors.BOLD}✓{Colors.RESET} {Colors.DIM}{Colors.GRAY}{msg}{Colors.RESET}\033[K")

def log_tool(msg):
    fake_loading(msg)

def log_info(msg):
    print(f"{left_indent()}{ACCENT}{Colors.BOLD}·{Colors.RESET} {Colors.DIM}{Colors.GRAY}info{Colors.RESET}  {msg}{Colors.RESET}")

def log_ok(msg):
    print(f"{left_indent()}{ACCENT}{Colors.BOLD}✓{Colors.RESET} {Colors.DIM}{Colors.GRAY}done{Colors.RESET}  {msg}{Colors.RESET}")

def log_warn(msg):
    print(f"{left_indent()}{Colors.YELLOW}{Colors.BOLD}!{Colors.RESET} {Colors.DIM}{Colors.GRAY}warn{Colors.RESET}  {msg}{Colors.RESET}")

def summarize_tool_args(args):
    if not isinstance(args, dict) or not args:
        return ""
    preview_keys = ["command", "path", "query", "pattern", "url", "repo_id", "text", "index", "status"]
    parts = []
    for key in preview_keys:
        if key in args and args[key] not in (None, ""):
            value = str(args[key]).replace("\n", " ")
            if len(value) > 60:
                value = value[:57] + "…"
            parts.append(f"{Colors.DIM}{Colors.GRAY}{key}={Colors.RESET}{Colors.WHITE}{value}{Colors.RESET}")
    leftover = [k for k in args if k not in preview_keys and args[k] not in (None, "")]
    if leftover:
        parts.append(f"{Colors.DIM}{Colors.GRAY}+{len(leftover)} more{Colors.RESET}")
    return "  ".join(parts)

def print_tool_call(name, args):
    detail = summarize_tool_args(args)
    line = f"{left_indent()}{ACCENT}{Colors.BOLD}⚙ {name}{Colors.RESET}"
    if detail:
        line += f"  {detail}"
    print(line)

TOOL_MARKUP_RE = re.compile(
    r'<tool_call>.*?</tool_call>'
    r'|<function\s*=.*?</function>'
    r'|<tools>.*?</tools>'
    r'|<tool_call>.*$'
    r'|<function\s*=.*$',
    re.DOTALL,
)

def strip_tool_markup(text):
    if not text:
        return text
    cleaned = TOOL_MARKUP_RE.sub('', text)
    cleaned = re.sub(r'```json\s*\{.*?\}\s*```', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()

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
            line = (
                f"{left_indent()}{ACCENT}{Colors.BOLD}{frame}{Colors.RESET} "
                f"{ACCENT}{bar}{Colors.RESET}  "
                f"{Colors.WHITE}{self.msg}{Colors.RESET}  "
                f"{Colors.DIM}{Colors.GRAY}{pulse} · {elapsed:04.1f}s{Colors.RESET}"
            )
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
    indent = left_indent()
    added = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))
    header_file = ""
    for line in diff_lines:
        if line.startswith('+++ '):
            header_file = line[6:].strip() if line.startswith('+++ b/') else line[4:].strip()
            break
    subtitle = f"+{added} -{removed}" + (f" · {header_file}" if header_file else "")
    print(f"\n{indent}{frame_title('DIFF', Colors.MAGENTA, subtitle=subtitle)}")
    for line in diff_lines:
        stripped = line.rstrip()
        if line.startswith('+++') or line.startswith('---'):
            print(f"{indent}  {Colors.DIM}{Colors.GRAY}{stripped}{Colors.RESET}")
        elif line.startswith('+'):
            print(f"{indent}  {Colors.GREEN}{Colors.BOLD}{stripped}{Colors.RESET}")
        elif line.startswith('-'):
            print(f"{indent}  {Colors.RED}{stripped}{Colors.RESET}")
        elif line.startswith('@@'):
            print(f"{indent}  {Colors.TEAL}{Colors.BOLD}{stripped}{Colors.RESET}")
        else:
            print(f"{indent}  {Colors.GRAY}{stripped}{Colors.RESET}")
    print(f"{indent}{frame_bottom(Colors.MAGENTA)}\n")

def print_logo():
    art_lines = [
        " ██████╗  █████╗ ██╗     ██╗     ██╗██╗   ██╗██╗██╗   ██╗███╗   ███╗",
        "██╔════╝ ██╔══██╗██║     ██║     ██║██║   ██║██║██║   ██║████╗ ████║",
        "██║  ███╗███████║██║     ██║     ██║██║   ██║██║██║   ██║██╔████╔██║",
        "██║   ██║██╔══██║██║     ██║     ██║╚██╗ ██╔╝██║██║   ██║██║╚██╔╝██║",
        "╚██████╔╝██║  ██║███████╗███████╗██║ ╚████╔╝ ██║╚██████╔╝██║ ╚═╝ ██║",
        " ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝",
    ]
    cols = term_cols()
    art_width = max(len(line) for line in art_lines)
    art_pad = " " * max(0, (cols - art_width) // 2)
    tagline = "Gallivium · AI coding assistant for the terminal"
    sub = "local models  ·  shell  ·  files  ·  web  ·  autonomous coding"
    print()
    for line in art_lines:
        print(f"{art_pad}{Colors.WHITE}{Colors.BOLD}{line}{Colors.RESET}")
    print()
    print(f"{' ' * max(0, (cols - len(tagline)) // 2)}{Colors.DIM}{Colors.GRAY}{tagline}{Colors.RESET}")
    print(f"{' ' * max(0, (cols - len(sub)) // 2)}{Colors.DIM}{Colors.GRAY}{sub}{Colors.RESET}")
    print()

MAX_OUTPUT_LENGTH = 10000
MAX_URL_OUTPUT_LENGTH = 1500000
HISTORY_THRESHOLD = 36
COMPACT_RECENT_MESSAGES = 12
COMPACT_MAX_MESSAGE_CHARS = 2200
DANGEROUS_PATTERNS = [r'\brm\b', r'\bmv\b', r'\bsudo\b', r'\bchmod\b', r'\bchown\b', r'\bdd\b', r'\bmkfs\b', r'\bformat\b', r'\bkill\b', r'>\s*/dev/', r'\bshred\b', r'\bwipe\b']
ALLOWED_SEARCH_DOMAINS = ["ollama.com", "googleblog.com", "ai.google.dev", "huggingface.co"]
CLI_COMMAND_NAME = "OCLI"
CLI_INSTALL_PATHS = [
    "/usr/local/bin/OCLI",
    os.path.expanduser("~/.local/bin/OCLI"),
    "/bin/OCLI",
]
BACKEND_DEFAULT_URLS = {
    "ollama": "http://localhost:11434",
    "llama-cpp": "http://localhost:8080",
    "mlx": "http://localhost:8080",
    "airllm": None,
}
BACKEND_DEFAULT_MODELS = {
    "ollama": "qwen3.6:27b-coding-nvfp4",
    "llama-cpp": "qwen2.5-coder-1.5b",
    "mlx": "mlx-community/Qwen3.5-0.8B-OptiQ-4bit",
    "airllm": "Qwen/Qwen2.5-72B-Instruct",
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
    "mlx-community/Qwen3.5-0.8B-OptiQ-4bit",
    "mlx-community/Qwen3.5-2B-OptiQ-4bit",
    "mlx-community/Qwen3.5-4B-OptiQ-4bit",
    "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "mlx-community/Qwen3-8B-4bit",
    "mlx-community/gemma-3-4b-it-4bit",
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
AIRLLM_MODELS = [
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.1-70B-Instruct",
    "meta-llama/Llama-3.1-405B-Instruct",
    "meta-llama/Llama-3-70B-Instruct",
    "meta-llama/Llama-2-70b-chat-hf",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "garage-bAInd/Platypus2-70B-instruct",
    "codellama/CodeLlama-70b-Instruct-hf",
    "google/gemma-2-27b-it",
    "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
]
MODEL_SUGGESTIONS = {
    "ollama": OLLAMA_MODELS,
    "llama-cpp": GGUF_MODELS,
    "mlx": MLX_MODELS,
    "airllm": AIRLLM_MODELS,
}
DOWNLOAD_MODEL_OPTIONS = {
    "ollama": [(model, model, None) for model in OLLAMA_MODELS],
    "mlx": [(model.split("/")[-1], model, None) for model in MLX_MODELS],
    "llama-cpp": [(model.split("/")[-1], model, LLAMA_CPP_URLS.get(model)) for model in GGUF_MODELS],
    "airllm": [(model.split("/")[-1], model, None) for model in AIRLLM_MODELS],
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

def launcher_matches_source(path, source):
    try:
        with open(path, "r") as f:
            return source in f.read()
    except Exception:
        return False

def command_on_path(name):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None

def install_cli_launcher():
    if os.environ.get("OCLI_SKIP_INSTALL") == "1":
        return
    source = os.path.abspath(__file__)
    existing = command_on_path(CLI_COMMAND_NAME)
    if existing and launcher_matches_source(existing, source):
        return
    wrapper = f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(source)} \"$@\"\n"
    errors = []
    for path in CLI_INSTALL_PATHS:
        if os.path.exists(path):
            if launcher_matches_source(path, source):
                return
            errors.append(f"{path} already exists")
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(wrapper)
            os.chmod(path, 0o755)
            log_info(f"Installed launcher: {Colors.TEAL}{path}{Colors.RESET}")
            if os.path.dirname(path) not in os.environ.get("PATH", "").split(os.pathsep):
                log_info(f"Add {Colors.TEAL}{os.path.dirname(path)}{Colors.RESET} to PATH to run {Colors.TEAL}OCLI{Colors.RESET} directly.")
            return
        except Exception as e:
            errors.append(f"{path}: {e}")
    if can_use_terminal_keys():
        log_info("Could not install OCLI launcher automatically. Try running with permissions for /usr/local/bin or create a launcher manually.")

def model_matches_backend(model, backend):
    if not model:
        return False
    lowered = model.lower()
    if backend == "airllm":
        return "/" in model and not model.startswith("mlx-community/") and "gguf" not in lowered
    if backend == "mlx":
        return model.startswith("mlx-community/") or model.startswith(("/", ".", "~"))
    if backend == "llama-cpp":
        return lowered.endswith(".gguf") or "gguf" in lowered or model.startswith(("/", ".", "~"))
    return not model.startswith("mlx-community/") and "gguf" not in lowered and not lowered.endswith(".gguf")

def is_large_mlx_model(model):
    lowered = str(model).lower()
    return any(size in lowered for size in ["24b", "26b", "27b", "31b", "32b", "35b", "40b", "70b"])

def truncate_output(output, limit=MAX_OUTPUT_LENGTH):
    if len(str(output)) > limit: return str(output)[:limit] + f"\n\n[Output truncated due to size.]"
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

NUMERIC_TOOL_ARGS = {"num_results", "index"}

def _coerce_arg(key, value):
    if key in NUMERIC_TOOL_ARGS:
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return value
    return value

def parse_xml_tool_calls(text):
    """Parse Qwen/Hermes-style XML tool calls.

    Handles blocks like:
        <function=run_cmd>
        <parameter=command>ls -la</parameter>
        </function>
    with or without an enclosing <tool_call>...</tool_call> wrapper.
    """
    calls = []
    for fn_match in re.finditer(r'<function\s*=\s*([A-Za-z_][\w-]*)\s*>(.*?)</function>', text, re.DOTALL):
        name = fn_match.group(1).strip()
        body = fn_match.group(2)
        args = {}
        for param in re.finditer(r'<parameter\s*=\s*([A-Za-z_][\w-]*)\s*>(.*?)</parameter>', body, re.DOTALL):
            key = param.group(1).strip()
            value = param.group(2)
            # trim a single leading/trailing newline that the format adds, keep inner content intact
            if value.startswith("\n"):
                value = value[1:]
            if value.endswith("\n"):
                value = value[:-1]
            args[key] = _coerce_arg(key, value)
        if name:
            calls.append({'function': {'name': name, 'arguments': args}})
    return calls

def recover_tool_call_from_text(text):
    name_match = re.search(r'["\']?name["\']?\s*:\s*["\']?([A-Za-z_][\w-]*)["\']?', text)
    args = {}
    arg_keys = ['command', 'path', 'content', 'plan', 'query', 'text', 'url', 'pattern', 'repo_id', 'index', 'status', 'key', 'value']
    for key in arg_keys:
        match = re.search(rf'["\']?{key}["\']?\s*:\s*("((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|([^,}}\n]+))', text)
        if match:
            raw_value = next((group for group in match.groups()[1:] if group is not None), "")
            raw_value = raw_value.strip()
            try:
                args[key] = bytes(raw_value, "utf-8").decode("unicode_escape")
            except Exception:
                args[key] = raw_value
    num_match = re.search(r'["\']?num_results["\']?\s*:\s*(\d+)', text)
    if num_match:
        args["num_results"] = int(num_match.group(1))
    if not args: return None
    if name_match:
        name = name_match.group(1)
    elif re.search(r'\brun_cmd\b', text) or 'command' in args:
        name = 'run_cmd'
    else:
        return None
    return {'function': {'name': name, 'arguments': args}}

def normalize_tool_call(tc):
    if isinstance(tc, dict):
        return tc
    try:
        d = tc.model_dump()
        if isinstance(d, dict) and 'function' in d:
            return d
    except (AttributeError, Exception):
        pass
    try:
        func = tc.function
        return {
            'function': {
                'name': getattr(func, 'name', None),
                'arguments': getattr(func, 'arguments', {}) or {}
            }
        }
    except (AttributeError, Exception):
        pass
    return {'function': {'name': None, 'arguments': {}}}

def direct_command_from_user(text):
    cleaned = str(text).strip()
    match = re.match(r'^(?:(?:please|can you|could you|would you)\s+)?(?:run|execute)\s+(?:the\s+)?(?:command\s+)?(.+?)[?.!]*$', cleaned, flags=re.IGNORECASE)
    if not match:
        match = re.match(r'^(?:(?:please|can you|could you|would you)\s+)?use\s+(?:the\s+)?command\s+(.+?)[?.!]*$', cleaned, flags=re.IGNORECASE)
    if not match:
        match = re.match(r'^(?:(?:please|can you|could you|would you)\s+)?command\s+(.+?)[?.!]*$', cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    command = match.group(1).strip()
    if not command:
        return None
    command = re.sub(r'[?.!]+$', '', command).strip()
    command = command.strip("`'\" ")
    try:
        first = shlex.split(command)[0]
    except Exception:
        return None
    allowed = {
        'pwd', 'ls', 'find', 'rg', 'grep', 'cat', 'sed', 'awk', 'head', 'tail', 'wc',
        'git', 'python', 'python3', 'pytest', 'pip', 'pip3', 'uv', 'npm', 'node',
        'pnpm', 'yarn', 'bun', 'make', 'cargo', 'go', 'java', 'javac', 'curl',
        'wget', 'hf', 'ollama', 'which', 'whoami', 'date', 'uname', 'df', 'du',
        'ps', 'env', 'printenv'
    }
    return command if first in allowed else None

def spawn_agents_tool_schema():
    return {
        'type': 'function',
        'function': {
            'name': 'spawn_agents',
            'description': 'Spawn up to 4 independent autonomous OCLI worker agents in parallel. Each child gets its own tool loop and memory. Use read_only for investigation; use full only when agents have clear ownership and may run commands or edit files.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'agents': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'task': {'type': 'string'},
                                'context': {'type': 'string'},
                            },
                            'required': ['task'],
                        },
                    },
                    'shared_context': {'type': 'string', 'default': ''},
                    'timeout_seconds': {'type': 'integer', 'default': 120},
                    'max_steps': {'type': 'integer', 'default': 3},
                    'tool_access': {'type': 'string', 'enum': ['read_only', 'full'], 'default': 'read_only'},
                },
                'required': ['agents'],
            },
        },
    }

class OCLI:
    def __init__(self, model_name, auto_mode=False, backend='ollama', url=None):
        self.model_name = model_name or BACKEND_DEFAULT_MODELS.get(backend, BACKEND_DEFAULT_MODELS["ollama"])
        self.auto_mode = auto_mode
        self.backend = backend
        self.url = url or BACKEND_DEFAULT_URLS.get(backend, "http://localhost:8080")
        if not model_matches_backend(self.model_name, self.backend):
            self.model_name = BACKEND_DEFAULT_MODELS.get(self.backend, self.model_name)
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
        self.server_model = None
        self.tool_access = "full"
        self.allow_spawn_agents = True
        self.non_interactive = False
        self.PLAN_PROMPT = "Planning is ENABLED. Before performing complex tasks, multiple file edits, or potentially destructive operations, you MUST create an implementation plan using the 'create_plan' tool. Break the plan down into discrete, numbered tasks that cover every explicit user requirement. As you work, use the 'update_task' tool to mark tasks as 'doing' and 'done'. After the plan is approved, continue by making real tool calls."
        cur_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.messages = [{
            'role': 'system',
            'content': (
                f"You are OCLI, an advanced AUTONOMOUS AI coding agent. Current date: {cur_date}. "
                "CONVERSATION RULES: For greetings, questions, explanations, or any non-task message, respond in plain natural language. Do NOT call tools or output JSON for simple conversation. Only use tools when the user explicitly asks you to perform an action (run code, edit files, search, etc.). "
                "Wrap internal reasoning in <thought> tags. "
                "To call a tool, emit a single tool call. Preferred format: <tools>{{\"name\": \"tool_name\", \"arguments\": {{...}}}}</tools>. For shell commands, use <tools>{{\"name\":\"run_cmd\",\"arguments\":{{\"command\":\"pwd\"}}}}</tools>. The native function-call format (<tool_call><function=run_cmd><parameter=command>pwd</parameter></function></tool_call>) is also accepted. Use exactly one format per call and provide every required argument. Available tools include run_cmd, read_file, write_file, test_cmd, list_files, search_files, find_files, grep, web_search, read_url, git_status, git_diff, and spawn_agents. For coding tasks, write the complete requested implementation first, then write tests, then run pytest, then fix failures, then summarize final files. "
                "Do not write markdown code blocks when creating or editing files; use the write_file tool. Do not describe running commands; use run_cmd or test_cmd. Do not fabricate tool results, diffs, test output, file contents, or <tool_response> blocks. If a user asks you to create code, modify code, inspect files, run tests, install packages, or execute a program, you MUST call a real tool. "
                "For multi-step tasks, after each successful real tool call, immediately make the next required real tool call only if it advances the original user request; do not output bare CONTINUE as a standalone response, and do not repeatedly run the same command or read/write the same file without changing strategy. If list_files has already shown the tree, do not call it again; use search_files/find_files, grep, read_file, git_diff, or provide the final answer. If a test fails twice with the same error, inspect the file tree and relevant files before editing again. "
                "CRITICAL: Use the 'test_cmd' tool for ANY command that might be interactive (games, prompts, servers). DO NOT use 'run_cmd' for these. MANDATORY: Always use 'write_file' for all code modifications to ensure the user sees a diff report. When the user asks for multiple searches, perform at least 3-5 searches. "
                "IMPORTANT: You are an autonomous agent. NEVER ask the user to run a command. RUN IT YOURSELF. NEVER simulate tool results. ONLY use 'CONTINUE' if you have just called a tool and need to perform another step. ALWAYS prioritize answering the user's primary question directly after gathering data. If searching for software features, prioritize finding 'Release Notes' or 'What's New' pages. Planning is DISABLED. Do not use create_plan tool unless planning is explicitly enabled."
            )
        }]
        self.server_process = None
        self.airllm_model = None
        self.airllm_compression = None
        self.airllm_max_length = 4096
        self.airllm_max_new_tokens = 2048
        if self.backend == 'mlx': log_info("MLX backend selected. The model will load on the first prompt.")
        if self.backend == 'airllm': log_info("AirLLM backend selected. The model will load on the first prompt (layer-by-layer, may take a while).")
        atexit.register(self.cleanup)

    def cleanup(self):
        if self.server_process:
            log_info("Shutting down MLX server...")
            self.server_process.terminate()
            try: self.server_process.wait(timeout=5)
            except: self.server_process.kill()
            self.server_process = None
        if self.airllm_model:
            log_info("Unloading AirLLM model...")
            del self.airllm_model
            self.airllm_model = None
        self.server_model = None

    def menu_choice(self, title, options):
        return interactive_menu(title, options, Colors.VIOLET)

    def prompt_value(self, label, current=None):
        suffix = f" {Colors.GRAY}[{current}]{Colors.RESET}" if current else ""
        value = styled_input(f"  {Colors.TEAL}{label}{Colors.RESET}{suffix}: ").strip()
        return value or current

    def set_backend(self, backend, url=None, keep_model=False):
        previous_backend = self.backend
        previous_url = self.url
        next_url = url or BACKEND_DEFAULT_URLS.get(backend) or BACKEND_DEFAULT_URLS.get("ollama")
        if previous_backend == 'mlx' and (backend != 'mlx' or next_url != previous_url):
            self.cleanup()
        if previous_backend == 'airllm' and backend != 'airllm':
            if self.airllm_model:
                log_info("Unloading AirLLM model...")
                del self.airllm_model
                self.airllm_model = None
        self.backend = backend
        self.url = next_url if backend != 'airllm' else None
        if keep_model and not model_matches_backend(self.model_name, backend):
            log_info(f"Current model {Colors.TEAL}{self.model_name}{Colors.RESET} is not compatible with {Colors.TEAL}{backend}{Colors.RESET}; using the backend default.")
            keep_model = False
        if not keep_model:
            self.model_name = BACKEND_DEFAULT_MODELS.get(backend, self.model_name)
        if self.backend == 'mlx':
            log_info("MLX model will load on the first prompt.")
            if is_large_mlx_model(self.model_name):
                log_info("Large MLX model selected; the first prompt can take several minutes while weights load into memory.")
        if self.backend == 'airllm':
            self.airllm_model = None
            self.server_model = None
            log_info("AirLLM model will load on the first prompt (layer-by-layer streaming).")
        log_info(f"Backend switched to {Colors.TEAL}{self.backend}{Colors.RESET}" + (f" using {Colors.TEAL}{self.url}{Colors.RESET}" if self.url else ""))
        log_info(f"Model is now {Colors.TEAL}{self.model_name}{Colors.RESET}")

    def backend_menu(self):
        options = [
            f"1. {Colors.CYAN}ollama{Colors.RESET}     {Colors.GRAY}Local Ollama API on port 11434{Colors.RESET}",
            f"2. {Colors.CYAN}llama-cpp{Colors.RESET}  {Colors.GRAY}OpenAI-compatible llama.cpp server{Colors.RESET}",
            f"3. {Colors.CYAN}mlx{Colors.RESET}        {Colors.GRAY}MLX server for Apple Silicon{Colors.RESET}",
            f"4. {Colors.CYAN}airllm{Colors.RESET}     {Colors.GRAY}AirLLM in-process inference (run 70B+ on 4GB VRAM){Colors.RESET}",
        ]
        choice = self.menu_choice("BACKEND", options)
        if choice is None:
            return
        backend = ["ollama", "llama-cpp", "mlx", "airllm"][choice]
        if backend == 'airllm':
            url = None
        else:
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
            if self.server_process and self.server_model != self.model_name:
                self.cleanup()
            elif self.server_model != self.model_name:
                self.server_model = None
            log_info("MLX model will load on the next prompt.")
            if is_large_mlx_model(self.model_name):
                log_info("Large MLX model selected; the first prompt can take several minutes while weights load into memory.")
        log_info(f"Model switched to {Colors.TEAL}{self.model_name}{Colors.RESET}")

    def parse_download_args(self, arg_text):
        if not arg_text:
            return None, None
        try:
            parts = shlex.split(arg_text)
        except ValueError as e:
            log_info(f"Could not parse download arguments: {e}")
            return arg_text.strip(), None

        path = None
        model_parts = []
        i = 0
        while i < len(parts):
            part = parts[i]
            if part in ["--path", "--dir", "--local-dir", "-p"]:
                if i + 1 >= len(parts):
                    log_info(f"Missing path after {part}.")
                    break
                path = parts[i + 1]
                i += 2
                continue
            if part.startswith("--path=") or part.startswith("--dir=") or part.startswith("--local-dir="):
                path = part.split("=", 1)[1]
                i += 1
                continue
            model_parts.append(part)
            i += 1
        return " ".join(model_parts).strip() or None, path

    def model_download_default_dir(self, model_name=None, url=None):
        if self.backend == "mlx":
            name = (model_name or "model").rstrip("/").split("/")[-1] or "model"
            return os.path.join("models", "mlx", name)
        if self.backend == "airllm":
            name = (model_name or "model").rstrip("/").split("/")[-1] or "model"
            return os.path.join("models", "airllm", name)
        if self.backend == "llama-cpp":
            if model_name and "/" in model_name and not url:
                name = model_name.rstrip("/").split("/")[-1] or "model"
                return os.path.join("llama.cpp", "models", name)
            return os.path.join("llama.cpp", "models")
        return ""

    def normalize_download_dir(self, path):
        return os.path.abspath(os.path.expanduser(path)) if path else None

    def prompt_download_dir(self, model_name=None, url=None):
        if self.backend == "ollama":
            log_info("Ollama stores models in its configured model directory; set OLLAMA_MODELS before starting Ollama to change it.")
            return None
        default = self.model_download_default_dir(model_name, url)
        path = self.prompt_value("Download path", default)
        return self.normalize_download_dir(path)

    def run_model_download(self, model_name, url=None, download_dir=None, ask_for_path=True):
        if not model_name:
            return
        log_info(f"Download target: {Colors.TEAL}{model_name}{Colors.RESET}")
        if self.backend == "ollama":
            if download_dir:
                log_info("Ollama does not support a per-download path; using the active Ollama model store.")
            self.run_cmd(f"ollama pull {shlex.quote(model_name)}")
        elif self.backend == "mlx":
            if ask_for_path and not download_dir:
                download_dir = self.prompt_download_dir(model_name, url)
            result = self.download_mlx_model(model_name, download_dir)
            if download_dir:
                log_info(f"To use this local MLX model, run {Colors.TEAL}/model {self.normalize_download_dir(download_dir)}{Colors.RESET}")
            return result
        elif self.backend == "airllm":
            if ask_for_path and not download_dir:
                download_dir = self.prompt_download_dir(model_name, url)
            download_dir = self.normalize_download_dir(download_dir)
            if download_dir:
                os.makedirs(download_dir, exist_ok=True)
                result = self.run_cmd(f"hf download {shlex.quote(model_name)} --local-dir {shlex.quote(download_dir)}")
                log_info(f"To use this local AirLLM model, run {Colors.TEAL}/model {download_dir}{Colors.RESET}")
                return result
            return self.run_cmd(f"hf download {shlex.quote(model_name)}")
        elif self.backend == "llama-cpp":
            if ask_for_path and not download_dir:
                download_dir = self.prompt_download_dir(model_name, url)
            download_dir = self.normalize_download_dir(download_dir or self.model_download_default_dir(model_name, url))
            if not url and "/" in model_name:
                os.makedirs(download_dir, exist_ok=True)
                self.run_cmd(f"hf download {shlex.quote(model_name)} --include '*.gguf' --local-dir {shlex.quote(download_dir)}")
                return
            url = url or self.prompt_value("GGUF download URL")
            if not url:
                log_info("Download canceled.")
                return
            os.makedirs(download_dir, exist_ok=True)
            filename = model_name if model_name.endswith(".gguf") else os.path.basename(url.split("?")[0]) or f"{model_name}.gguf"
            self.run_cmd(f"curl -L -o {shlex.quote(os.path.join(download_dir, filename))} {shlex.quote(url)}")
        else:
            log_info(f"Model download is not configured for backend {Colors.TEAL}{self.backend}{Colors.RESET}.")

    def download_model_menu(self, model_name=None, download_dir=None):
        if model_name:
            self.run_model_download(model_name, download_dir=download_dir)
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
            self.run_model_download(value, url, download_dir=download_dir)
            return
        if self.backend == "llama-cpp":
            url = self.prompt_value("GGUF download URL")
            if not url:
                log_info("Download canceled.")
                return
            model_name = self.prompt_value("Save as", os.path.basename(url.split("?")[0]) or "model.gguf")
            self.run_model_download(model_name, url, download_dir=download_dir)
            return
        model_name = self.prompt_value("Model to download", self.model_name)
        self.run_model_download(model_name, download_dir=download_dir)

    def is_port_open(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def ensure_mlx_server(self):
        host = self.url.split("//")[-1].split(":")[0]
        try: port = int(self.url.split(":")[-1])
        except: port = 8080

        if self.server_process and self.server_process.poll() is not None:
            self.server_process = None
            self.server_model = None
        if self.server_process and self.server_model != self.model_name:
            self.cleanup()
        if self.server_process and self.server_model == self.model_name and self.is_port_open(host, port):
            return
        if self.is_port_open(host, port):
            log_info(f"MLX Server already running on {host}:{port}")
            self.server_model = self.model_name
            return

        log_info(f"Auto-starting MLX Server with model: {self.model_name}")
        cmd = [sys.executable, "-m", "mlx_lm.server", "--model", self.model_name]
        try:
            self.server_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_info("Waiting for MLX server to initialize...")
            for _ in range(30):
                if self.is_port_open(host, port):
                    self.server_model = self.model_name
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
                if self.non_interactive:
                    return f"Command blocked: non-interactive agent cannot confirm {reason.lower()} for `{command}`."
                confirm = styled_input(f"  {Colors.BOLD}Confirm execution? (y/n):{Colors.RESET} ").strip().lower()
                if confirm not in ['y', 'yes']: return "Command Aborted."
            else:
                fake_loading(f"Safety Audit: {command[:30]}...", duration=0.4)
                check_resp = ollama.chat(model=self.model_name, messages=[{'role': 'user', 'content': f"Is this command safe? '{command}'. Reply ONLY 'SAFE' or 'UNSAFE'."}])
                audit_result = check_resp['message']['content'].strip().upper()
                if "SAFE" not in audit_result or "UNSAFE" in audit_result:
                    print(f"\n  {status_label('WARN', Colors.ORANGE)} AI Audit UNSAFE {Colors.GRAY}│{Colors.RESET} {Colors.TEAL}{command}{Colors.RESET}")
                    if self.non_interactive:
                        return f"Command blocked: non-interactive agent cannot confirm unsafe command `{command}`."
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

    def download_mlx_model(self, repo_id, download_dir=None):
        try:
            log_tool(f"Downloading MLX Model: {repo_id}")
            download_dir = self.normalize_download_dir(download_dir)
            if download_dir:
                os.makedirs(download_dir, exist_ok=True)
                cmd = f"hf download {shlex.quote(repo_id)} --local-dir {shlex.quote(download_dir)}"
            else:
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
            max_entries = 350
            truncated = False
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.venv', 'venv']]
                level = root.replace(path, '').count(os.sep)
                if level > 3: continue
                indent = '  ' * level
                res.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = '  ' * (level + 1)
                for f in files: res.append(f"{sub_indent}{f}")
                if len(res) >= max_entries:
                    truncated = True
                    break
            if truncated:
                res = res[:max_entries]
                res.append("[truncated: use search_files/find_files, grep, or read_file for a narrower view]")
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
            print(f"\n  {frame_title('URL CONTENT', Colors.MAGENTA)}\n  {Colors.GRAY}{url}{Colors.RESET}\n\n{render_text(truncate_output(text, MAX_URL_OUTPUT_LENGTH))}\n  {frame_bottom(Colors.MAGENTA)}\n")
            return truncate_output(text, MAX_URL_OUTPUT_LENGTH)
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
            existed = os.path.exists(path)
            old_content = ""
            if existed:
                with open(path, 'r') as f: old_content = f.read()
            with open(path, 'w') as f: f.write(content)
            from_label = f"a/{path}" if existed else "/dev/null"
            to_label = f"b/{path}"
            diff = list(difflib.unified_diff(
                old_content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=from_label,
                tofile=to_label,
            ))
            if diff:
                print_diff(diff)
            else:
                print(f"\n{left_indent()}{frame_title('DIFF REPORT', Colors.MAGENTA, subtitle=path)}")
                print(f"{left_indent()}  {Colors.DIM}{Colors.GRAY}(no changes — content identical){Colors.RESET}")
                print(f"{left_indent()}{frame_bottom(Colors.MAGENTA)}\n")
            added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
            removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
            if existed:
                return f"File updated. Diff shown (+{added}/-{removed})."
            return f"File created. Diff shown (+{added} lines)."
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

    def _spawn_agent_chat(self, agent, shared_context="", timeout_seconds=120, max_steps=3, tool_access="read_only"):
        name = str(agent.get("name") or "agent").strip()[:80] or "agent"
        task = str(agent.get("task") or agent.get("prompt") or "").strip()
        agent_context = str(agent.get("context") or "").strip()
        if not task:
            return {"name": name, "status": "error", "response": "Missing agent task."}
        payload = {
            "name": name,
            "task": task,
            "context": agent_context,
            "shared_context": shared_context,
            "model_name": self.model_name,
            "backend": self.backend,
            "url": self.url,
            "tool_access": tool_access,
            "max_steps": max_steps,
        }
        cmd = [sys.executable, os.path.abspath(__file__), "--spawn-agent-worker", "--skip-install"]
        try:
            completed = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, timeout=timeout_seconds + 30)
            try:
                data = json.loads(completed.stdout)
                data["name"] = name
                return data
            except json.JSONDecodeError:
                pass
            if completed.returncode != 0:
                return {
                    "name": name,
                    "status": "error",
                    "response": truncate_output(completed.stderr or completed.stdout or f"Worker exited with code {completed.returncode}", 4000),
                }
            return {"name": name, "status": "error", "response": "Worker completed without JSON output."}
        except subprocess.TimeoutExpired:
            return {"name": name, "status": "timeout", "response": f"Timed out after {timeout_seconds}s."}
        except json.JSONDecodeError as e:
            return {"name": name, "status": "error", "response": f"Worker returned invalid JSON: {e}"}
        except Exception as e:
            return {"name": name, "status": "error", "response": str(e)}

    def spawn_agents(self, agents, shared_context="", timeout_seconds=120, max_steps=3, tool_access="read_only"):
        try:
            if isinstance(agents, str):
                agents = [{"name": "agent_1", "task": agents}]
            elif isinstance(agents, dict):
                agents = agents.get("agents", [agents])
            if not isinstance(agents, list) or not agents:
                return "Error: agents must be a non-empty list of task objects."

            normalized = []
            for index, agent in enumerate(agents[:4], 1):
                if isinstance(agent, str):
                    normalized.append({"name": f"agent_{index}", "task": agent})
                elif isinstance(agent, dict):
                    normalized.append({
                        "name": str(agent.get("name") or f"agent_{index}"),
                        "task": str(agent.get("task") or agent.get("prompt") or ""),
                        "context": str(agent.get("context") or ""),
                    })
            if not normalized:
                return "Error: no valid agent tasks were provided."

            timeout_seconds = max(10, min(int(timeout_seconds or 120), 600))
            max_steps = max(1, min(int(max_steps or 3), 8))
            tool_access = tool_access if tool_access in ["read_only", "full"] else "read_only"
            if self.backend == "mlx":
                self.ensure_mlx_server()
            log_tool(f"SPAWN_AGENTS: {len(normalized)} agents · {tool_access}")

            results = [None] * len(normalized)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(normalized))
            futures = {
                executor.submit(self._spawn_agent_chat, agent, shared_context, timeout_seconds, max_steps, tool_access): index
                for index, agent in enumerate(normalized)
            }
            try:
                for future in concurrent.futures.as_completed(futures, timeout=timeout_seconds + 5):
                    index = futures[future]
                    try:
                        results[index] = future.result()
                    except Exception as e:
                        results[index] = {"name": normalized[index]["name"], "status": "error", "response": str(e)}
            except concurrent.futures.TimeoutError:
                pass
            finally:
                for future, index in futures.items():
                    if results[index] is None:
                        future.cancel()
                        results[index] = {"name": normalized[index]["name"], "status": "timeout", "response": f"Timed out after {timeout_seconds}s."}
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    executor.shutdown(wait=False)

            summary_lines = [
                f"{Colors.CYAN}{result['name']}{Colors.RESET} {Colors.GRAY}({result['status']}){Colors.RESET}: {truncate_output(result['response'], 500)}"
                for result in results
            ]
            print_panel("SPAWNED AGENTS", summary_lines, Colors.CYAN)
            return "Spawned agent results:\n" + json.dumps(results, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

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
        starter_filename = "qwen2.5-coder-1.5b.gguf"
        starter_dir = self.normalize_download_dir(self.prompt_value("Starter model download path", os.path.join("llama.cpp", "models")))
        starter_path = os.path.join(starter_dir, starter_filename)
        starter_url = "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
        model_setup = f"mkdir -p {shlex.quote(starter_dir)} && curl -L -o {shlex.quote(starter_path)} {shlex.quote(starter_url)}"
        self.run_cmd(model_setup)

        log_info("llama.cpp setup complete!")
        print(f"\n  {status_label('SUCCESS', Colors.GREEN)} llama.cpp is ready!")
        print(f"  {Colors.CYAN}To start the server:{Colors.RESET} cd llama.cpp && ./build/bin/llama-server -m {starter_path}")
        print(f"  {Colors.CYAN}To use with OCLI:{Colors.RESET} python3 OCLI.py --backend llama-cpp --model {starter_path}")
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
        model_dir = self.normalize_download_dir(self.prompt_value("Recommended model download path", os.path.join("models", "mlx", model_name.split("/")[-1])))
        try:
            os.makedirs(model_dir, exist_ok=True)
            self.run_cmd(f"{shlex.quote(sys.executable)} -m huggingface_hub.commands.cli download {shlex.quote(model_name)} --local-dir {shlex.quote(model_dir)}")
        except Exception as e:
            log_info(f"Model download check failed: {e}")

        log_info("MLX setup complete!")
        print(f"\n  {status_label('SUCCESS', Colors.GREEN)} MLX (mlx-lm) is ready!")
        print(f"  {Colors.CYAN}To start the server:{Colors.RESET} python3 -m mlx_lm.server --model {model_dir}")
        print(f"  {Colors.CYAN}To use with OCLI:{Colors.RESET} python3 OCLI.py --backend mlx --model {model_dir}")
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
        elif self.backend == 'airllm':
            if not self.airllm_model:
                return self.fallback_compaction_summary(messages)
            try:
                import torch
                prompt_text = self.airllm_model.tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}], tokenize=False, add_generation_prompt=True)
                if not prompt_text:
                    prompt_text = f"user: {prompt}\nassistant: "
                input_tokens = self.airllm_model.tokenizer(
                    [prompt_text], return_tensors="pt", return_attention_mask=False, 
                    truncation=True, max_length=self.airllm_max_length, padding=False
                )
                input_ids = input_tokens['input_ids']
                if torch.cuda.is_available():
                    input_ids = input_ids.cuda()
                generation_output = self.airllm_model.generate(
                    input_ids, max_new_tokens=1024, use_cache=True, return_dict_in_generate=True
                )
                output_ids = generation_output.sequences[0][len(input_ids[0]):]
                return self.airllm_model.tokenizer.decode(output_ids, skip_special_tokens=True).strip()
            except Exception as e:
                log_info(f"AirLLM compaction failed: {e}")
                return self.fallback_compaction_summary(messages)
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

    def server_messages(self):
        prepared = []
        for message in self.messages:
            role = message.get('role', 'user')
            content = message.get('content', '') or ''
            if role == 'tool':
                name = message.get('name') or 'tool'
                prepared.append({'role': 'user', 'content': f"Tool result from {name}:\n{content}"})
            elif role in ['system', 'user', 'assistant']:
                prepared.append({'role': role, 'content': content})
            else:
                prepared.append({'role': 'user', 'content': content})
        return prepared

    def run(self):
        print_logo()
        print_panel("session", [
            kv_row("model",   f"{Colors.WHITE}{self.model_name}{Colors.RESET}"),
            kv_row("backend", f"{Colors.WHITE}{self.backend}{Colors.RESET}"),
            kv_row("auto",    mode_value(self.auto_mode)),
            "",
            f"{Colors.DIM}{Colors.GRAY}/help for commands · exit to quit{Colors.RESET}",
        ], MUTED)
        while True:
            try:
                width = term_width()
                inner = width - 2
                indent = left_indent()
                meta_left = f" OCLI "
                meta_right = f" {self.backend}:{self.model_name} · auto {'on' if self.auto_mode else 'off'} · plan {'on' if self.planning_enabled else 'off'} "
                fill = max(2, inner - len(meta_left) - len(meta_right))
                top = (
                    f"{indent}{MUTED}╭─{Colors.RESET}"
                    f"{ACCENT}{Colors.BOLD}{meta_left}{Colors.RESET}"
                    f"{MUTED}{'─' * fill}{Colors.RESET}"
                    f"{Colors.DIM}{Colors.GRAY}{meta_right}{Colors.RESET}"
                    f"{MUTED}─╮{Colors.RESET}"
                )
                bottom = f"{indent}{MUTED}╰{'─' * (width - 2)}╯{Colors.RESET}"
                print()
                print(top)
                prompt_inline = f"{indent}{MUTED}│{Colors.RESET} {ACCENT}{Colors.BOLD}❯{Colors.RESET} "
                user_input = styled_input(prompt_inline).strip()
                print(bottom)
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
                        print_panel("status", [
                            kv_row("model",     f"{Colors.WHITE}{self.model_name}{Colors.RESET}"),
                            kv_row("backend",   f"{Colors.WHITE}{self.backend}{Colors.RESET}"),
                            kv_row("auto",      mode_value(self.auto_mode)),
                            kv_row("planning",  mode_value(self.planning_enabled)),
                            kv_row("history",   f"{Colors.WHITE}{len(self.messages)}{Colors.RESET} {Colors.DIM}{Colors.GRAY}messages{Colors.RESET}"),
                            kv_row("compacted", f"{Colors.WHITE}{self.compaction_count}{Colors.RESET} {Colors.DIM}{Colors.GRAY}times{Colors.RESET}"),
                        ], MUTED)
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
                                if self.server_process and self.server_model != self.model_name:
                                    self.cleanup()
                                elif self.server_model != self.model_name:
                                    self.server_model = None
                                log_info("MLX model will load on the next prompt.")
                                if is_large_mlx_model(self.model_name):
                                    log_info("Large MLX model selected; the first prompt can take several minutes while weights load into memory.")
                            log_info(f"Model switched to {Colors.TEAL}{self.model_name}{Colors.RESET}")
                        else:
                            self.model_menu()
                        continue
                    elif cmd == '/tasks':
                        self.print_tasks()
                        continue
                    elif cmd == '/help':
                        def help_row(cmd_text, desc):
                            pad = max(0, 34 - clean_len(cmd_text))
                            return f"  {Colors.WHITE}{cmd_text}{Colors.RESET}{' ' * pad}{Colors.DIM}{Colors.GRAY}{desc}{Colors.RESET}"
                        def help_header(text):
                            return f"  {Colors.DIM}{Colors.GRAY}── {text} ──{Colors.RESET}"
                        print_panel("commands", [
                            help_header("session"),
                            help_row("/status",                          "show model and backend status"),
                            help_row("/tasks",                           "show progress checkpoints"),
                            help_row("/save [file]",                     "save current session to JSON"),
                            help_row("/load <file>",                     "load a session from JSON"),
                            help_row("/exit",                            "quit OCLI"),
                            "",
                            help_header("models & backends"),
                            help_row("/backend",                         "open the backend switcher"),
                            help_row("/model",                           "open the model switcher"),
                            help_row("/download_model [m] [--path dir]", "download a model for the active backend"),
                            help_row("/download <repo> [--path dir]",    "download an MLX model from Hugging Face"),
                            help_row("/setup_mlx",                       "install and download MLX models"),
                            "",
                            help_header("behavior"),
                            help_row("/auto",                            "toggle auto-execution mode"),
                            help_row("/plan",                            "toggle autonomous planning mode"),
                            help_row("/help",                            "show this command list"),
                        ], MUTED)
                        continue
                    elif cmd == '/setup':
                        self.setup_llama_cpp()
                        continue
                    elif cmd == '/setup_mlx':
                        self.setup_mlx()
                        continue
                    elif cmd == '/download':
                        repo_id, download_dir = self.parse_download_args(user_input[len(cmd_parts[0]):].strip())
                        if not repo_id:
                            log_info("Usage: /download <repo_id> [--path <download_dir>]")
                            continue
                        if download_dir is None:
                            download_dir = self.prompt_download_dir(repo_id)
                        self.download_mlx_model(repo_id, download_dir)
                        continue
                    elif cmd == '/download_model':
                        model_arg, download_dir = self.parse_download_args(user_input[len(cmd_parts[0]):].strip())
                        self.download_model_menu(model_arg, download_dir)
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
                        or (had_tools and self.auto_mode and self.messages[-1].get('role') == 'tool' and auto_count < 3)
                    )
                    if should_continue:
                        auto_count += 1
                        print(f"\n{left_indent()}{ACCENT}↻{Colors.RESET} {Colors.DIM}{Colors.GRAY}auto{Colors.RESET}  continuing step {Colors.WHITE}{auto_count}{Colors.DIM}/10{Colors.RESET}")
                        self.messages.append({'role': 'user', 'content': f"Continue the original task and make concrete progress toward completion. Original request:\n{self.last_user_goal}\nDo not repeat the same command/read cycle. If implementation is incomplete, write the full files now. If files are written, run pytest. If tests pass, summarize final files and usage."})
                    else:
                        break
            except KeyboardInterrupt: break

    def process_chat(self):
        had_tool_calls = False
        available_tools = {'run_cmd': self.run_cmd, 'read_file': self.read_file, 'write_file': self.write_file, 'web_search': self.web_search, 'create_plan': self.create_plan, 'update_task': self.update_task, 'test_cmd': self.test_cmd, 'send_input': self.send_input, 'read_url': self.read_url, 'download_mlx_model': self.download_mlx_model, 'list_files': self.list_files, 'search_files': self.search_files, 'find_files': self.search_files, 'grep': self.grep, 'git_status': self.git_status, 'git_diff': self.git_diff, 'spawn_agents': self.spawn_agents}
        read_only_tool_names = {'read_file', 'web_search', 'read_url', 'list_files', 'search_files', 'find_files', 'grep', 'git_status', 'git_diff'}
        if self.tool_access == "read_only":
            available_tools = {name: tool for name, tool in available_tools.items() if name in read_only_tool_names}
        if not self.allow_spawn_agents:
            available_tools.pop('spawn_agents', None)
        tool_reprompt_count = 0
        invalid_tool_reprompt_count = 0
        while True:
            try:
                spinner = None
                interrupter.start_listening()
                tools = [
                    {'type': 'function', 'function': {'name': 'run_cmd', 'description': 'Run shell command', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
                    {'type': 'function', 'function': {'name': 'web_search', 'description': 'Search web via DuckDuckGo. Use authoritative domains for official-source searches.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'num_results': {'type': 'integer', 'default': 10}}, 'required': ['query']}}},
                    {'type': 'function', 'function': {'name': 'read_url', 'description': 'Fetch and read the text content of a URL.', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
                    {'type': 'function', 'function': {'name': 'download_mlx_model', 'description': 'Download an MLX model from Hugging Face.', 'parameters': {'type': 'object', 'properties': {'repo_id': {'type': 'string'}, 'download_dir': {'type': 'string', 'description': 'Optional local directory for the downloaded model files.'}}, 'required': ['repo_id']}}},
                    {'type': 'function', 'function': {'name': 'read_file', 'description': 'Read file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}},
                    {'type': 'function', 'function': {'name': 'write_file', 'description': 'Write file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}}},
                    {'type': 'function', 'function': {'name': 'test_cmd', 'description': 'Run command with live feedback (use for interactive tests or long processes).', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
                    {'type': 'function', 'function': {'name': 'send_input', 'description': 'Send text input to the active test process.', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}},
                    {'type': 'function', 'function': {'name': 'list_files', 'description': 'List files and directories in a path (tree view, max depth 3).', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string', 'default': '.'}}, 'required': []}}},
                    {'type': 'function', 'function': {'name': 'search_files', 'description': 'Find files by name pattern.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'path': {'type': 'string', 'default': '.'}}, 'required': ['query']}}},
                    {'type': 'function', 'function': {'name': 'find_files', 'description': 'Alias for search_files. Find files by name pattern.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'path': {'type': 'string', 'default': '.'}}, 'required': ['query']}}},
                    {'type': 'function', 'function': {'name': 'grep', 'description': 'Search file contents for a pattern (like grep -rIn).', 'parameters': {'type': 'object', 'properties': {'pattern': {'type': 'string'}, 'path': {'type': 'string', 'default': '.'}}, 'required': ['pattern']}}},
                    {'type': 'function', 'function': {'name': 'git_status', 'description': 'Show git status of the current repo.', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
                    {'type': 'function', 'function': {'name': 'git_diff', 'description': 'Show git diff of changes. Optionally for a specific file.', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string', 'default': ''}}, 'required': []}}},
                    spawn_agents_tool_schema(),
                ]
                if self.planning_enabled:
                    tools.append({'type': 'function', 'function': {'name': 'create_plan', 'description': 'Create an implementation plan before performing complex tasks.', 'parameters': {'type': 'object', 'properties': {'plan': {'type': 'string'}}, 'required': ['plan']}}})
                    tools.append({'type': 'function', 'function': {'name': 'update_task', 'description': 'Update the status of a task in the current plan.', 'parameters': {'type': 'object', 'properties': {'index': {'type': 'string', 'description': 'The 1-based index of the task'}, 'status': {'type': 'string', 'enum': ['todo', 'doing', 'done']}}, 'required': ['index', 'status']}}})
                if self.tool_access == "read_only" or not self.allow_spawn_agents:
                    tools = [tool for tool in tools if tool.get('function', {}).get('name') in available_tools]

                if self.backend == 'mlx':
                    self.ensure_mlx_server()

                spinner = Spinner(f"{self.backend.capitalize()} generating")
                spinner.start()
                
                content, tool_calls, response_metadata = "", [], {}
                first_chunk = True
                in_thought, in_tool, thought_labeled, line_buffer = False, False, False, ""
                tags_to_hide = ["<thought>", "</thought>", "<tools>", "</tools>", "<tool_call>", "</tool_call>", "</function>", "</parameter>", "<response>", "</response>", "<result>", "</result>", "<tool_response>", "</tool_response>", "```json", "```", "Thought:", "THINKING:", "<|im_end|>", "<|im_start|>", "<|endoftext|>"]
                tool_start_re = re.compile(r'<(?:function|parameter)\s*=')

                def process_token(token):
                    nonlocal first_chunk, in_thought, in_tool, thought_labeled, line_buffer, content
                    content += token

                    if first_chunk and token.strip():
                        spinner.stop()
                        print(f"\n{left_indent()}{ACCENT}{Colors.BOLD}❯ OCLI{Colors.RESET} {Colors.DIM}{Colors.GRAY}·{Colors.RESET} ", end="", flush=True)
                        first_chunk = False

                    # Qwen/Hermes XML tool calls use variable-length tags (<function=...>),
                    # so detect them with a regex over the recently-added region.
                    if not in_tool and tool_start_re.search(content[-(len(token) + 12):]):
                        in_tool = True

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
                        is_potential_tag = is_potential_tag or line_buffer.rstrip().endswith("<")
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
                        if 'tool_calls' in msg and msg['tool_calls']: tool_calls.extend(normalize_tool_call(tc) for tc in msg['tool_calls'])
                        if 'total_duration' in chunk: response_metadata = chunk
                elif self.backend == 'airllm':
                    try:
                        from airllm import AutoModel
                        import torch
                    except ImportError:
                        spinner.stop()
                        interrupter.stop_listening()
                        log_info(f"AirLLM or PyTorch is not installed. Please run: {Colors.TEAL}pip install airllm torch{Colors.RESET}")
                        self.messages.append({'role': 'assistant', 'content': "[AirLLM NOT INSTALLED]"})
                        return False
                    
                    if not self.airllm_model:
                        log_info(f"Loading AirLLM model {self.model_name}...")
                        try:
                            self.airllm_model = AutoModel.from_pretrained(self.model_name, compression=self.airllm_compression)
                            self.server_model = self.model_name
                        except Exception as e:
                            spinner.stop()
                            interrupter.stop_listening()
                            log_info(f"Failed to load AirLLM model: {e}")
                            self.messages.append({'role': 'assistant', 'content': f"[MODEL LOAD ERROR] {e}"})
                            return False
                    
                    try:
                        prompt_text = self.airllm_model.tokenizer.apply_chat_template(self.server_messages(), tokenize=False, add_generation_prompt=True)
                        if not prompt_text:
                            prompt_text = "\n".join([f"{m['role']}: {m['content']}" for m in self.server_messages()]) + "\nassistant: "
                        
                        input_tokens = self.airllm_model.tokenizer(
                            [prompt_text],
                            return_tensors="pt",
                            return_attention_mask=False,
                            truncation=True,
                            max_length=self.airllm_max_length,
                            padding=False
                        )
                        
                        input_ids = input_tokens['input_ids']
                        if torch.cuda.is_available():
                            input_ids = input_ids.cuda()
                            
                        generation_output = self.airllm_model.generate(
                            input_ids,
                            max_new_tokens=self.airllm_max_new_tokens,
                            use_cache=True,
                            return_dict_in_generate=True
                        )
                        
                        output_ids = generation_output.sequences[0][len(input_ids[0]):]
                        output_text = self.airllm_model.tokenizer.decode(output_ids, skip_special_tokens=True)
                        process_token(output_text)
                    except Exception as e:
                        spinner.stop()
                        interrupter.stop_listening()
                        log_info(f"AirLLM generation failed: {e}")
                        self.messages.append({'role': 'assistant', 'content': f"[AIRLLM ERROR] {e}"})
                        return False
                else:
                    payload = {"model": self.model_name, "messages": self.server_messages(), "stream": True}
                    try:
                        r = requests.post(f"{self.url}/v1/chat/completions", json=payload, stream=True)
                    except requests.RequestException as e:
                        spinner.stop()
                        interrupter.stop_listening()
                        log_info(f"Server request failed: {e}")
                        self.messages.append({'role': 'assistant', 'content': f"[SERVER ERROR] {e}"})
                        return False
                    if r.status_code != 200:
                        spinner.stop()
                        interrupter.stop_listening()
                        log_info(f"Server Error ({r.status_code}): {r.text}")
                        self.messages.append({'role': 'assistant', 'content': f"[SERVER ERROR {r.status_code}] {r.text}"})
                        return False
                    spinner.stop()
                    log_info(f"Connected to {self.backend} server. Awaiting response...")
                    spinner.start()
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
                    # 1) Qwen/Hermes XML function-call format: <function=name><parameter=k>v</parameter></function>
                    xml_calls = parse_xml_tool_calls(content)
                    if xml_calls:
                        tool_calls.extend(xml_calls)

                if not tool_calls:
                    # 2) JSON wrapped in <tools>/<tool_call>/<response>, fenced ```json, or bare objects
                    tool_matches = re.findall(r'<(?:tools|tool_call|response)>(.*?)(?:</(?:tools|tool_call|response)>|$)', content, re.DOTALL)
                    if not tool_matches:
                        tool_matches = re.findall(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if not tool_matches:
                        for obj in extract_json_objects(content):
                            if '"name"' in obj and '"arguments"' in obj:
                                tool_matches.append(obj.replace("{{", "{").replace("}}", "}"))
                    for match in tool_matches:
                        snippet = match.strip()
                        if not snippet:
                            continue
                        try:
                            data = json.loads(snippet)
                            if isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict) and item.get('name'):
                                        tool_calls.append({'function': {'name': item.get('name'), 'arguments': item.get('arguments', {})}})
                            elif isinstance(data, dict) and data.get('name'):
                                tool_calls.append({'function': {'name': data.get('name'), 'arguments': data.get('arguments', {})}})
                        except Exception as e:
                            recovered = parse_xml_tool_calls(snippet) or recover_tool_call_from_text(snippet)
                            if recovered:
                                log_info("Recovered tool call from non-JSON model output")
                                tool_calls.extend(recovered if isinstance(recovered, list) else [recovered])
                            else:
                                log_info(f"Failed to parse tool call: {e}")

                    if not tool_calls:
                        recovered = recover_tool_call_from_text(content)
                        if recovered:
                            log_info("Recovered malformed tool call from full model output")
                            tool_calls.append(recovered)

                lower_content = content.lower()
                user_context = "\n".join(m.get('content', '') for m in self.messages[-3:] if m.get('role') == 'user').lower()
                fake_tool_markers = ['<tool_response>', '</tool_response>', 'running tasklite.py...', 'diff --git']
                tool_required_phrases = ['create ', 'write ', 'edit ', 'modify ', 'fix ', 'test ', 'run ', 'execute ', 'pytest', 'tasklite.py', 'devlog.py', 'test_devlog.py', 'readme.md']
                needs_real_tool = not had_tool_calls and any(phrase in user_context for phrase in tool_required_phrases)
                appears_fake_tool_result = not had_tool_calls and any(marker in lower_content for marker in fake_tool_markers)
                bare_continue = content.strip().upper() == "CONTINUE"
                hardware_queries = ['vram', 'gpu memory', 'video memory', 'unified memory', 'how much memory']
                direct_command = direct_command_from_user(self.last_user_goal)
                if not tool_calls and not had_tool_calls and direct_command:
                    log_info(f"Model did not emit a valid tool call; using recovered command: {Colors.TEAL}{direct_command}{Colors.RESET}")
                    tool_calls.append({
                        'function': {
                            'name': 'run_cmd',
                            'arguments': {'command': direct_command}
                        }
                    })
                elif not tool_calls and not had_tool_calls and any(term in user_context for term in hardware_queries):
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
                    tool_reprompt_count += 1
                    if tool_reprompt_count > 2:
                        log_info("No valid tool call produced after retries.")
                        self.messages.append({'role': 'assistant', 'content': content or "[No valid tool call produced.]"})
                        return False
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
                        self.messages.append({'role': 'assistant', 'content': strip_tool_markup(content), 'tool_calls': formatted_calls})
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
                            repeated_hint = (
                                f"Repeated `{name}` call skipped. You already have that tool output in the conversation. "
                                "Do not call the same tool with the same arguments again. Use search_files/find_files, grep, read_file, git_diff, or provide the final answer now."
                            )
                            self.messages.append({'role': 'tool', 'content': repeated_hint, 'tool_call_id': call_id, 'name': name})
                            valid_tool_calls += 1
                            had_tool_calls = True
                            continue

                        if self.tool_steps_this_turn >= 50:
                            log_info("Stopping tool loop after 50 tool steps in one user turn")
                            self.messages.append({'role': 'tool', 'content': "Tool step limit reached for this turn. Stop looping and give the user a concise status report with the exact remaining failure and next manual fix.", 'tool_call_id': call_id, 'name': name})
                            break

                        print_tool_call(name, args)
                        tool_limit = MAX_URL_OUTPUT_LENGTH if name == 'read_url' else MAX_OUTPUT_LENGTH
                        result = truncate_output(available_tools[name](**args), tool_limit)
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
                    invalid_tool_reprompt_count += 1
                    if invalid_tool_reprompt_count > 2:
                        log_info("No valid tool call produced after retries.")
                        self.messages.append({'role': 'assistant', 'content': "[No valid tool call produced after retries.]"})
                        return False
                    self.messages.append({'role': 'user', 'content': f"Your previous tool call was invalid, incomplete, or repetitive. Original request:\n{self.last_user_goal}\nRespond with one complete JSON tool call that advances the task, or give the final summary only if the task is actually complete."})
                    continue
                continue
            except Exception as e:
                if spinner:
                    spinner.stop()
                interrupter.stop_listening()
                self.messages.append({'role': 'assistant', 'content': f"[OCLI ERROR] {e}"})
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                return False

def run_spawn_agent_worker():
    try:
        request = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"status": "error", "response": f"Invalid worker payload: {e}", "log": ""}))
        return 1

    name = str(request.get("name") or "agent").strip()[:80] or "agent"
    task = str(request.get("task") or "").strip()
    context = str(request.get("context") or "").strip()
    shared_context = str(request.get("shared_context") or "").strip()
    backend = request.get("backend") or "ollama"
    model_name = request.get("model_name") or BACKEND_DEFAULT_MODELS.get(backend, BACKEND_DEFAULT_MODELS["ollama"])
    url = request.get("url")
    tool_access = request.get("tool_access") if request.get("tool_access") in ["read_only", "full"] else "read_only"
    try:
        max_steps = max(1, min(int(request.get("max_steps") or 3), 8))
    except Exception:
        max_steps = 3

    log_buffer = io.StringIO()
    status = "ok"
    response_text = ""
    try:
        with contextlib.redirect_stdout(log_buffer):
            agent = OCLI(model_name=model_name, auto_mode=True, backend=backend, url=url)
            agent.tool_access = tool_access
            agent.allow_spawn_agents = False
            agent.non_interactive = True
            agent.messages[0]["content"] += (
                f" You are spawned worker agent `{name}`. You have your own tool loop and memory. "
                "You are not alone in the workspace; avoid broad edits and do not overwrite unrelated changes. "
                "If tool_access is read_only, inspect and report only. If tool_access is full, edit or run commands only when the task clearly requires it. "
                "Before making claims about the current workspace, inspect it with an available tool. "
                "Do not spawn more agents. Finish with concise findings, exact files touched if any, and remaining risks."
            )
            user_parts = []
            if shared_context:
                user_parts.append(f"Shared context:\n{shared_context}")
            if context:
                user_parts.append(f"Agent-specific context:\n{context}")
            user_parts.append(f"Task:\n{task}")
            user_parts.append(f"Tool access: {tool_access}")
            agent.last_user_goal = task
            agent.messages.append({"role": "user", "content": "\n\n".join(user_parts)})
            for step in range(max_steps):
                agent.compact_history()
                agent.process_chat()
                last_content = next((m.get("content", "") for m in reversed(agent.messages) if m.get("role") == "assistant" and m.get("content")), "")
                if "CONTINUE" not in str(last_content).upper() or step == max_steps - 1:
                    break
                agent.messages.append({"role": "user", "content": "Continue the assigned worker task. Use tools only if they materially advance the task; otherwise provide the final worker summary."})
            agent.cleanup()

        response_text = next(
            (
                str(m.get("content", "")).strip()
                for m in reversed(agent.messages)
                if m.get("role") == "assistant" and str(m.get("content", "")).strip() and not m.get("tool_calls")
            ),
            "",
        )
        if not response_text:
            status = "no_final"
            response_text = "Worker completed without a final assistant summary."
    except Exception as e:
        status = "error"
        response_text = str(e)

    print(json.dumps({
        "name": name,
        "status": status,
        "tool_access": tool_access,
        "response": truncate_output(response_text, 5000),
        "log": truncate_output(clean_ansi(log_buffer.getvalue()), 5000),
    }))
    return 0 if status != "error" else 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--backend", type=str, choices=['ollama', 'llama-cpp', 'mlx', 'airllm'], default="ollama")
    parser.add_argument("--url", type=str, help="Server URL (e.g. http://localhost:8080)")
    parser.add_argument("--skip-install", action="store_true", help="Skip automatic OCLI launcher installation")
    parser.add_argument("--spawn-agent-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.skip_install:
        os.environ["OCLI_SKIP_INSTALL"] = "1"
    if args.spawn_agent_worker:
        sys.exit(run_spawn_agent_worker())
    install_cli_launcher()
    agent = OCLI(model_name=args.model or BACKEND_DEFAULT_MODELS[args.backend], auto_mode=args.auto, backend=args.backend, url=args.url)
    agent.run()
