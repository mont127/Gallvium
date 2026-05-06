import ollama
import subprocess
import os
import json
import sys
import argparse
import difflib
import time
import re
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
warnings.simplefilter("ignore")
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    GRAY = "\033[90m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"

def render_text(text):
    text = re.sub(r'\*\*\*(.*?)\*\*\*', f"{Colors.BOLD}{Colors.MAGENTA}\\1{Colors.RESET}", text)
    text = re.sub(r'\*\*(.*?)\*\*', f"{Colors.BOLD}{Colors.CYAN}\\1{Colors.RESET}", text)
    text = re.sub(r'\*(.*?)\*', f"{Colors.BLUE}\\1{Colors.RESET}", text)
    text = re.sub(r'### (.*)', f"\n{Colors.BOLD}{Colors.YELLOW}■ \\1{Colors.RESET}", text)
    text = re.sub(r'## (.*)', f"\n{Colors.BOLD}{Colors.GREEN}# \\1{Colors.RESET}", text)
    text = re.sub(r'# (.*)', f"\n{Colors.BOLD}{Colors.BLUE}== \\1 =={Colors.RESET}", text)
    text = re.sub(r'^(\s*)[\*\-] ', f"\\1{Colors.CYAN}• {Colors.RESET}", text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*)(\d+)\. ', f"\\1{Colors.YELLOW}\\2. {Colors.RESET}", text, flags=re.MULTILINE)
    return text

def fake_loading(msg, duration=0.6):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        print(f"  {Colors.CYAN}{frames[i % len(frames)]} {msg}{Colors.RESET}", end="\r")
        time.sleep(0.06)
        i += 1
    print(f"  {Colors.GREEN}[OK] {msg}{Colors.RESET}")

def log_tool(msg):
    fake_loading(msg)

def log_info(msg):
    print(f"  {Colors.YELLOW}[INFO] {msg}{Colors.RESET}")

class Spinner:
    def __init__(self, msg="AI is thinking"):
        self.msg = msg
        self.running = False
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _spin(self):
        i = 0
        while self.running:
            print(f"  {Colors.CYAN}{self.frames[i % len(self.frames)]} {self.msg}{Colors.RESET}", end="\r")
            time.sleep(0.1)
            i += 1
        sys.stdout.write("\r" + " " * (len(self.msg) + 10) + "\r")
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
    print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[DIFF_REPORT]{Colors.RESET}")
    for line in diff_lines:
        if line.startswith('+') and not line.startswith('+++'): print(f"    {Colors.GREEN}{line.rstrip()}{Colors.RESET}")
        elif line.startswith('-') and not line.startswith('---'): print(f"    {Colors.RED}{line.rstrip()}{Colors.RESET}")
        elif line.startswith('@@'): print(f"    {Colors.CYAN}{line.rstrip()}{Colors.RESET}")
        else: print(f"    {Colors.GRAY}{line.rstrip()}{Colors.RESET}")
    print()

def print_logo():
    logo = rf"""{Colors.CYAN}{Colors.BOLD}
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
   ___  _      ____          _     
  / _ \| |    / ___|___   __| | __
 | | | | |   | |   / _ \ / _` |/ _ \ 
 | |_| | |___| |__| (_) | (_| |  __/
  \___/|_____|\____\___/ \__,_|\___/

{Colors.GRAY}      Free Open Source AI Coding Assistant
      Local models - Tools - Shell - Files - Web{Colors.CYAN}

                              7PP?.          .?PP7
                             P@PY@B:        :B@YP@P
                            !@#  5@5.!?JJ?!.5@5  #@!
                            J@P  7@@&BP55PB&@@7  P@J
                            7@&PP#@5^      ^5@#PP&@7
                           .J&#5?!!~          ~!!?5#&J.
                           .B@Y.                    .Y@B.
                           Y@P   .^.   ^~!!~^   .^.   P@Y
                           Y@5   G@G.JG5J??J5GJ.G@G   5@Y
                           :B@J. :~:BB: :YY. :BB:~: .J@B:
                            5@B:    GB^  ?7  ^BG    :B@5
                           ~@&.     .?PP5YY5PP?.     .&@~
                           ?@G         .::::.         G@?
                           ^@&^                      ^&@^
                            ?@&^                    ^&@?
                            Y@G.                    .G@Y
                           :&@^                      ^@&:
                           :&@^                      ^@&:
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
{Colors.RESET}{Colors.GRAY}
         >>> OllamaCode- Free Open Source AI Coding Assistant <<<
{Colors.RESET}"""
    print(logo)

MAX_OUTPUT_LENGTH = 10000
HISTORY_THRESHOLD = 20
DANGEROUS_PATTERNS = [r'\brm\b', r'\bmv\b', r'\bsudo\b', r'\bchmod\b', r'\bchown\b', r'\bdd\b', r'\bmkfs\b', r'\bformat\b', r'\bkill\b', r'>\s*/dev/', r'\bshred\b', r'\bwipe\b']
ALLOWED_SEARCH_DOMAINS = ["ollama.com", "googleblog.com", "ai.google.dev", "huggingface.co"]

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

def truncate_output(output):
    if len(str(output)) > MAX_OUTPUT_LENGTH: return str(output)[:MAX_OUTPUT_LENGTH] + f"\n\n[Output truncated due to size.]"
    return str(output)

class OCLI:
    def __init__(self, model_name, auto_mode=False, backend='ollama', url=None):
        self.model_name = model_name
        self.auto_mode = auto_mode
        self.backend = backend
        self.url = url or ("http://localhost:11434" if backend == 'ollama' else "http://localhost:8080")
        self.planning_enabled = False
        self.tasks = []
        self.active_process = None
        self.PLAN_PROMPT = "Before performing complex tasks, multiple file edits, or potentially destructive operations, you MUST create an implementation plan using the 'create_plan' tool. Break the plan down into discrete, numbered tasks. As you work, use the 'update_task' tool to mark tasks as 'doing' and 'done'. This provides the user with checkpoints."
        cur_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.messages = [{'role': 'system', 'content': f"You are OCLI, an advanced AUTONOMOUS AI agent. Current date: {cur_date}. Wrap internal reasoning in <thought> tags. To call a tool, use: <tools>{{\"name\": \"tool_name\", \"arguments\": {{...}}}}</tools>. End multi-step tasks with 'CONTINUE'. CRITICAL: Use the 'test_cmd' tool for ANY command that might be interactive (games, prompts, servers). DO NOT use 'run_cmd' for these. MANDATORY: Always use 'write_file' for all code modifications to ensure the user sees a diff report. When the user asks for multiple searches, perform at least 3-5 searches. IMPORTANT: You are an autonomous agent. NEVER ask the user to run a command. RUN IT YOURSELF. NEVER simulate tool results. ONLY use 'CONTINUE' if you have just called a tool and need to perform another step. ALWAYS prioritize answering the user's primary question directly after gathering data. If searching for software features, prioritize finding 'Release Notes' or 'What's New' pages."}]
        self.server_process = None
        if self.backend == 'mlx': self.ensure_mlx_server()
        atexit.register(self.cleanup)

    def cleanup(self):
        if self.server_process:
            log_info("Shutting down MLX server...")
            self.server_process.terminate()
            try: self.server_process.wait(timeout=5)
            except: self.server_process.kill()

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
            is_dangerous = any(re.search(p, command) for p in DANGEROUS_PATTERNS)
            if not self.auto_mode or is_dangerous:
                reason = "Dangerous Pattern" if is_dangerous else "Manual Confirmation"
                print(f"\n  {Colors.YELLOW}{Colors.BOLD}[WARN] {reason} | AI wants to execute:{Colors.RESET} {Colors.CYAN}{command}{Colors.RESET}")
                confirm = input(f"  {Colors.BOLD}Confirm execution? (y/n):{Colors.RESET} ").strip().lower()
                if confirm not in ['y', 'yes']: return "Command Aborted."
            else:
                fake_loading(f"Safety Audit: {command[:30]}...", duration=0.4)
                check_resp = ollama.chat(model=self.model_name, messages=[{'role': 'user', 'content': f"Is this command safe? '{command}'. Reply ONLY 'SAFE' or 'UNSAFE'."}])
                audit_result = check_resp['message']['content'].strip().upper()
                if "SAFE" not in audit_result or "UNSAFE" in audit_result:
                    print(f"\n  {Colors.YELLOW}{Colors.BOLD}[WARN] AI Audit UNSAFE | AI wants to execute:{Colors.RESET} {Colors.CYAN}{command}{Colors.RESET}")
                    confirm = input(f"  {Colors.BOLD}Confirm execution? (y/n):{Colors.RESET} ").strip().lower()
                    if confirm not in ['y', 'yes']: return "Command Aborted."
                else: print(f"\n  {Colors.GREEN}{Colors.BOLD}[AUTO-SAFE] AI Audit Passed | Executing:{Colors.RESET} {Colors.CYAN}{command}{Colors.RESET}")
            log_tool(f"SYSTEM_EXEC: {command}")
            interrupter.start_listening()
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            output = []
            print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[EXEC_OUTPUT]{Colors.RESET}")
            last_out = time.time()
            while True:
                if interrupter.interrupted.is_set():
                    process.terminate()
                    print(f"\n  {Colors.RED}[INTERRUPTED]{Colors.RESET}")
                    interrupter.stop_listening()
                    return "Command interrupted."
                
                rlist, _, _ = select.select([process.stdout], [], [], 1.0)
                if rlist:
                    line = process.stdout.readline()
                    if line:
                        print(line, end="")
                        output.append(line)
                        last_out = time.time()
                        continue
                
                
                if process.poll() is not None: break
                if time.time() - last_out > 60:
                    process.terminate()
                    interrupter.stop_listening()
                    return f"Command Timed Out (60s silence). If this was interactive, use 'test_cmd'. Output so far:\n" + "".join(output)

            process.stdout.close()
            process.wait()
            interrupter.stop_listening()
            return f"Command Output:\n" + "".join(output)
        except Exception as e:
            interrupter.stop_listening()
            return f"Command Failed: {str(e)}"

    def test_cmd(self, command):
        try:
            if self.active_process and self.active_process.poll() is None: self.active_process.terminate()
            log_tool(f"TEST_EXEC (PTY): {command}")
            interrupter.start_listening()
            master, slave = pty.openpty()
            self.active_process = subprocess.Popen(command, shell=True, stdout=slave, stderr=slave, stdin=slave, text=True, close_fds=True)
            os.close(slave)
            fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
            output = []
            print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[TEST_EXEC_OUTPUT]{Colors.RESET}")
            last_output_time = time.time()
            while True:
                if interrupter.interrupted.is_set():
                    self.active_process.terminate()
                    os.close(master)
                    print(f"\n  {Colors.RED}[INTERRUPTED]{Colors.RESET}")
                    interrupter.stop_listening()
                    return "Test interrupted."
                try:
                    data = os.read(master, 1024).decode(errors='ignore')
                    if data:
                        sys.stdout.write(data)
                        sys.stdout.flush()
                        output.append(data)
                        last_output_time = time.time()
                except (BlockingIOError, OSError): pass
                if self.active_process.poll() is not None: break
                if time.time() - last_output_time > 5:
                    print(f"\n  {Colors.YELLOW}[LIVE_FEEDBACK] Process waiting for input...{Colors.RESET}")
                    interrupter.stop_listening()
                    buffer = "".join(output[-1000:])
                    return f"LIVE_FEEDBACK (Process waiting for input):\n{buffer}\nUse 'send_input' to interact."
                time.sleep(0.1)
            os.close(master)
            interrupter.stop_listening()
            return f"Test Completed. Output:\n" + "".join(output)
        except Exception as e:
            interrupter.stop_listening()
            return f"Error: {str(e)}"

    def download_mlx_model(self, repo_id):
        try:
            log_tool(f"Downloading MLX Model: {repo_id}")
            cmd = f"hf download {repo_id}"
            return self.run_cmd(cmd)
        except Exception as e: return f"Error: {str(e)}"

    def send_input(self, text):
        try:
            if not self.active_process or self.active_process.poll() is not None:
                return "Error: No active process to send input to."
            
            log_info(f"Sending Input: {text}")
            self.active_process.stdin.write(text + "\n")
            self.active_process.stdin.flush()
            
            output = []
            last_output_time = time.time()
            interrupter.start_listening()
            while True:
                if interrupter.interrupted.is_set(): break
                rlist, _, _ = select.select([self.active_process.stdout], [], [], 0.5)
                if rlist:
                    line = self.active_process.stdout.readline()
                    if line:
                        print(line, end="")
                        output.append(line)
                        last_output_time = time.time()
                        continue
                if self.active_process.poll() is not None: break
                if time.time() - last_output_time > 5: break
                
            interrupter.stop_listening()
            return f"Input sent. New Output:\n" + "".join(output)
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
            print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[SEARCH_RESULTS]{Colors.RESET}\n{render_text(formatted_results)}\n")
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
            print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[URL_CONTENT: {url}]{Colors.RESET}\n{render_text(truncate_output(text))}\n")
            return truncate_output(text)
        except Exception as e: return f"Error fetching URL: {str(e)}"

    def read_file(self, path):
        try:
            if os.path.isdir(path): return f"Error: '{path}' is a directory. Use 'ls' to list its contents."
            log_tool(f"Reading: {path}")
            with open(path, 'r') as f:
                content = f.read()
                print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[FILE: {path}]{Colors.RESET}\n{render_text(truncate_output(content))}\n")
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
        print(f"\n  {Colors.CYAN}{Colors.BOLD}[PROGRESS_CHECKPOINTS]{Colors.RESET}")
        for i, task in enumerate(self.tasks):
            icon = f"{Colors.GRAY}[ ]"
            if task['status'] == 'done': icon = f"{Colors.GREEN}[x]"
            elif task['status'] == 'doing': icon = f"{Colors.YELLOW}[/]"
            print(f"    {icon} {Colors.RESET}{i+1}. {task['text']}")
        print()

    def create_plan(self, plan):
        try:
            self.tasks = []
            lines = plan.split('\n')
            for line in lines:
                match = re.match(r'^\s*[\*\-\d\.]+\s*(.*)', line)
                if match and match.group(1).strip():
                    self.tasks.append({'text': match.group(1).strip(), 'status': 'todo'})
            
            print(f"\n  {Colors.GREEN}{Colors.BOLD}[IMPLEMENTATION_PLAN]{Colors.RESET}")
            print(render_text(plan))
            self.print_tasks()
            print(f"  {Colors.YELLOW}{Colors.BOLD}Awaiting your approval or feedback to proceed...{Colors.RESET}")
            feedback = input(f"  {Colors.BOLD}Feedback (Enter to approve):{Colors.RESET} ").strip()
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
            print(f"  {Colors.RED}[ERR] Xcode Command Line Tools not found.{Colors.RESET}")
            print(f"  {Colors.YELLOW}[FIX] Run: xcode-select --install{Colors.RESET}")
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
        print(f"\n  {Colors.GREEN}{Colors.BOLD}>>> SUCCESS: llama.cpp is ready! <<<{Colors.RESET}")
        print(f"  {Colors.CYAN}To start the server:{Colors.RESET} cd llama.cpp && ./build/bin/llama-server -m models/qwen2.5-coder-1.5b.gguf")
        print(f"  {Colors.CYAN}To use with OCLI:{Colors.RESET} python3 OCLI.py --backend llama-cpp --model qwen2.5-coder-1.5b")
        return "llama.cpp setup successful."

    def setup_mlx(self):
        log_info("Starting MLX Automation Setup for macOS...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "mlx-lm", "huggingface_hub", "--break-system-packages"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"  {Colors.RED}[ERR] Failed to install mlx-lm: {e}{Colors.RESET}")
            return "Setup failed."

        log_info("Downloading recommended MLX model (Qwen2.5-Coder-7B-Instruct)...")
        model_name = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
        try:
            self.run_cmd(f"{sys.executable} -m huggingface_hub.commands.cli download {model_name}")
        except Exception as e:
            log_info(f"Model download check failed: {e}")

        log_info("MLX setup complete!")
        print(f"\n  {Colors.GREEN}{Colors.BOLD}>>> SUCCESS: MLX (mlx-lm) is ready! <<<{Colors.RESET}")
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
            if duration > 0: print(f"{Colors.GRAY}[STATS] {duration:.2f}s | IN: {p_tokens} | OUT: {e_tokens}{Colors.RESET}")
        else:
            print(f"{Colors.GRAY}[STATS] Request Completed.{Colors.RESET}")

    def compact_history(self):
        if len(self.messages) > HISTORY_THRESHOLD:
            log_info("History threshold reached. Compacting...")
            system_msg = self.messages[0]
            recent_context = self.messages[-8:]
            middle_messages = self.messages[1:-8]
            try:
                prompt = "Summarize the key progress and facts from this conversation in 3 sentences max. Focus on what was built and what bugs were fixed."
                if self.backend == 'ollama':
                    summary_resp = ollama.chat(model=self.model_name, messages=middle_messages + [{'role': 'user', 'content': prompt}])
                    summary = summary_resp['message']['content']
                else:
                    r = requests.post(f"{self.url}/v1/chat/completions", json={"model": self.model_name, "messages": middle_messages + [{'role': 'user', 'content': prompt}]})
                    summary = r.json()['choices'][0]['message']['content']
                self.messages = [system_msg, {'role': 'assistant', 'content': f"Summary of previous progress: {summary}"}] + recent_context
                log_info("Compaction successful.")
            except Exception as e:
                log_info(f"Compaction failed ({e}). Truncating history.")
                self.messages = [system_msg] + recent_context

    def run(self):
        print_logo()
        status = f" | AUTO-MODE: {Colors.CYAN}ON{Colors.RESET}" if self.auto_mode else ""
        print(f"{Colors.GREEN}[SYS] OCLI ACTIVE | MODEL: {self.model_name}{status}{Colors.RESET}")
        print(f"{Colors.GRAY}[SYS] Type 'exit' to quit.{Colors.RESET}")
        while True:
            try:
                print("-" * 60)
                user_input = input(f"\n{Colors.YELLOW}{Colors.BOLD}[VibeCoder] > {Colors.RESET}").strip()
                print("")
                print("-" * 60)
                if not user_input: continue
                if user_input.startswith('/'):
                    cmd_parts = user_input.split()
                    cmd = cmd_parts[0].lower()
                    if cmd == '/exit' or cmd == '/quit': break
                    elif cmd == '/auto':
                        self.auto_mode = not self.auto_mode
                        status = f"{Colors.GREEN}ON{Colors.RESET}" if self.auto_mode else f"{Colors.RED}OFF{Colors.RESET}"
                        log_info(f"Auto-mode is now {status}")
                        continue
                    elif cmd == '/plan':
                        self.planning_enabled = not self.planning_enabled
                        status = f"{Colors.GREEN}ENABLED{Colors.RESET}" if self.planning_enabled else f"{Colors.RED}DISABLED{Colors.RESET}"
                        log_info(f"Planning mode is now {status}")
                        if self.planning_enabled:
                            self.messages[0]['content'] = self.messages[0]['content'].replace("Planning is DISABLED. Do not use create_plan tool.", self.PLAN_PROMPT)
                        else:
                            self.messages[0]['content'] = self.messages[0]['content'].replace(self.PLAN_PROMPT, "Planning is DISABLED. Do not use create_plan tool.")
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
                        print(f"  {Colors.BOLD}Current Status:{Colors.RESET}")
                        print(f"  {Colors.CYAN}Model:{Colors.RESET} {self.model_name}")
                        print(f"  {Colors.CYAN}Backend:{Colors.RESET} {self.backend}")
                        print(f"  {Colors.CYAN}Auto-Mode:{Colors.RESET} {'ON' if self.auto_mode else 'OFF'}")
                        print(f"  {Colors.CYAN}Planning:{Colors.RESET} {'ENABLED' if self.planning_enabled else 'DISABLED'}")
                        print(f"  {Colors.CYAN}History:{Colors.RESET} {len(self.messages)} messages")
                        continue
                    elif cmd == '/tasks':
                        self.print_tasks()
                        continue
                    elif cmd == '/help':
                        print(f"  {Colors.BOLD}Available Commands:{Colors.RESET}")
                        print(f"  {Colors.CYAN}/status{Colors.RESET}    - Show model and backend status")
                        print(f"  {Colors.CYAN}/help{Colors.RESET}      - Show this help message")
                        print(f"  {Colors.CYAN}/auto{Colors.RESET}      - Toggle auto-execution mode")
                        print(f"  {Colors.CYAN}/plan{Colors.RESET}      - Toggle autonomous planning mode")
                        print(f"  {Colors.CYAN}/tasks{Colors.RESET}     - Show current progress checkpoints")
                        print(f"  {Colors.CYAN}/save [f]{Colors.RESET}  - Save current session to JSON")
                        print(f"  {Colors.CYAN}/load <f>{Colors.RESET}  - Load session from JSON")
                        print(f"  {Colors.CYAN}/setup_mlx{Colors.RESET} - Auto-install and download MLX models")
                        print(f"  {Colors.CYAN}/download <r>{Colors.RESET} - Download an MLX model from Hugging Face")
                        print(f"  {Colors.CYAN}/exit{Colors.RESET}      - Quit the application")
                        print(f"\n  {Colors.GRAY}Note: The AI automatically uses tools like 'read_url' and 'web_search' for exploration.{Colors.RESET}")
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
                    else:
                        log_info(f"Unknown command: {cmd}")
                        continue

                if user_input.lower() in ['exit', 'quit']: break
                if user_input.lower() in ['continue', 'c']:
                    if len(self.messages) > 1: user_input = "Please continue."
                    else: continue
                self.messages.append({'role': 'user', 'content': user_input})
                auto_count = 0
                while auto_count < 10:
                    self.compact_history()
                    had_tools = self.process_chat()
                    last_msg = self.messages[-1].get('content', '') if self.messages else ""
                    if "CONTINUE" in last_msg.upper() and had_tools:
                        auto_count += 1
                        print(f"\n  {Colors.YELLOW}[AUTO] Continuing (Step {auto_count}/10){Colors.RESET}")
                        self.messages.append({'role': 'user', 'content': "Continue (Hidden)"})
                    else: break
            except KeyboardInterrupt: break

    def process_chat(self):
        had_tool_calls = False
        available_tools = {'run_cmd': self.run_cmd, 'read_file': self.read_file, 'write_file': self.write_file, 'web_search': self.web_search, 'create_plan': self.create_plan, 'update_task': self.update_task, 'test_cmd': self.test_cmd, 'send_input': self.send_input, 'read_url': self.read_url, 'download_mlx_model': self.download_mlx_model}
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
                ]
                if self.planning_enabled:
                    tools.append({'type': 'function', 'function': {'name': 'create_plan', 'description': 'Create an implementation plan before performing complex tasks.', 'parameters': {'type': 'object', 'properties': {'plan': {'type': 'string'}}, 'required': ['plan']}}})
                    tools.append({'type': 'function', 'function': {'name': 'update_task', 'description': 'Update the status of a task in the current plan.', 'parameters': {'type': 'object', 'properties': {'index': {'type': 'string', 'description': 'The 1-based index of the task'}, 'status': {'type': 'string', 'enum': ['todo', 'doing', 'done']}}, 'required': ['index', 'status']}}})

                spinner = Spinner(f"{self.backend.capitalize()} is thinking...")
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
                        print(f"\n{Colors.CYAN}{Colors.BOLD}OLAmma > {Colors.RESET}", end="", flush=True)
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
                                        print(f"{Colors.YELLOW}THINKING{Colors.RESET}", end="", flush=True)
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
                        potential_json = re.findall(r'(\{+?\s*"name":\s*".*?",\s*"arguments":\s*\{.*?\}.*?\}+?)', content, re.DOTALL)
                        for pj in potential_json: 
                            tool_matches.append(pj.replace("{{", "{").replace("}}", "}"))
                    for match in tool_matches:
                        try:
                            data = json.loads(match.strip())
                            if isinstance(data, list):
                                for item in data: tool_calls.append({'function': {'name': item.get('name'), 'arguments': item.get('arguments', {})}})
                            else:
                                tool_calls.append({'function': {'name': data.get('name'), 'arguments': data.get('arguments', {})}})
                        except: pass

                interrupter.stop_listening()
                if interrupter.interrupted.is_set():
                    self.messages.append({'role': 'assistant', 'content': content + " [USER INTERRUPTED]"})
                    break
                if tool_calls:
                    formatted_calls = []
                    for tc in tool_calls:
                        args = tc['function']['arguments']
                        if not isinstance(args, str): args = json.dumps(args)
                        formatted_calls.append({'id': tc.get('id', 'call_' + str(int(time.time()))), 'type': 'function', 'function': {'name': tc['function']['name'], 'arguments': args}})
                    self.messages.append({'role': 'assistant', 'content': content or "", 'tool_calls': formatted_calls})
                else:
                    self.messages.append({'role': 'assistant', 'content': content or ""})
                thoughts = re.findall(r'<thought>(.*?)(?:</thought>|$)', content, flags=re.DOTALL)
                if thoughts and thoughts[0].strip():
                    print(f"\n{Colors.YELLOW}{Colors.BOLD}THINKING{Colors.RESET}")
                    for t in thoughts: 
                        if t.strip(): print(f"{Colors.GRAY}  > {render_text(t.strip())}{Colors.RESET}")
                self.display_metrics(response_metadata)
                if not tool_calls: break
                for tool in tool_calls:
                    name, args = tool['function']['name'], tool['function']['arguments']
                    call_id = tool.get('id', 'call_' + str(int(time.time())))
                    if name in available_tools:
                        if isinstance(args, str):
                            try: args = json.loads(args)
                            except: pass
                        result = truncate_output(available_tools[name](**args))
                        self.messages.append({'role': 'tool', 'content': result, 'tool_call_id': call_id, 'name': name})
                        had_tool_calls = True
                if not tool_calls: return had_tool_calls
                continue
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="qwen3.6:27b-coding-nvfp4")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--backend", type=str, choices=['ollama', 'llama-cpp', 'mlx'], default="ollama")
    parser.add_argument("--url", type=str, help="Server URL (e.g. http://localhost:8080)")
    args = parser.parse_args()
    agent = OCLI(model_name=args.model, auto_mode=args.auto, backend=args.backend, url=args.url)
    agent.run()
