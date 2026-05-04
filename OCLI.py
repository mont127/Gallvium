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
import warnings
import datetime
try:
    from ddgs import DDGS
except ImportError:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        from duckduckgo_search import DDGS

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
{Colors.RESET}"""
    print(logo)
{Colors.RESET}{Colors.GRAY}
         >>> OllamaCode- Free Open Source AI Coding Assistant <<<{Colors.RESET}
"""
    print(logo)

MAX_OUTPUT_LENGTH = 5000
HISTORY_THRESHOLD = 40
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
    def __init__(self, model_name, auto_mode=False):
        self.model_name = model_name
        self.auto_mode = auto_mode
        cur_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.messages = [{'role': 'system', 'content': f"You are OCLI, an advanced AI agent. Current date: {cur_date}. Wrap internal reasoning in <thought> tags. End multi-step tasks with 'CONTINUE'. When the user asks for multiple searches, perform at least 5 search before summarizing. Prefer specific article pages over generic news index pages. Clearly separate confirmed facts from broader interpretation."}]

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
            while True:
                if interrupter.interrupted.is_set():
                    process.terminate()
                    print(f"\n  {Colors.RED}[INTERRUPTED]{Colors.RESET}")
                    interrupter.stop_listening()
                    return "Command interrupted."
                line = process.stdout.readline()
                if not line and process.poll() is not None: break
                if line:
                    print(line, end="")
                    output.append(line)
            interrupter.stop_listening()
            return f"Command Output:\n" + "".join(output)
        except Exception as e:
            interrupter.stop_listening()
            return f"Command Failed: {str(e)}"

    def web_search(self, query):
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
                    results = list(ddgs.text(search_query, region='wt-wt', safesearch='moderate', max_results=10))
                    for result in results:
                        href = result.get('href', '')
                        if not href or href in seen_urls or not domain_matches(href, requested_domains): continue
                        seen_urls.add(href)
                        collected.append(result)
                        if len(collected) >= 5: break
                    if len(collected) >= 5: break
            if not collected: return "No results found."
            formatted_results = "\n".join([f"- {r['title']}: {r['body']} ({r['href']})" for r in collected])
            print(f"\n  {Colors.MAGENTA}{Colors.BOLD}[SEARCH_RESULTS]{Colors.RESET}\n{render_text(formatted_results)}\n")
            return f"Search Results:\n{formatted_results}"
        except Exception as e: return f"Error: {str(e)}"

    def read_file(self, path):
        try:
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

    def display_metrics(self, response):
        duration = response.get('total_duration', 0) / 1e9
        p_tokens = response.get('prompt_eval_count', 0)
        e_tokens = response.get('eval_count', 0)
        if duration > 0: print(f"{Colors.GRAY}[STATS] {duration:.2f}s | IN: {p_tokens} | OUT: {e_tokens}{Colors.RESET}")

    def compact_history(self):
        if len(self.messages) > HISTORY_THRESHOLD:
            log_info("Compacting...")
            system_msg = self.messages[0]
            recent_context = self.messages[-10:]
            try:
                middle_messages = self.messages[1:-10]
                response = ollama.chat(model=self.model_name, messages=middle_messages + [{'role': 'user', 'content': "Summarize context concisely."}])
                self.messages = [system_msg, {'role': 'assistant', 'content': f"Summary: {response['message']['content']}"}] + recent_context
            except: self.messages = [system_msg] + recent_context

    def run(self):
        print_logo()
        status = f" | AUTO-MODE: {Colors.CYAN}ON{Colors.RESET}" if self.auto_mode else ""
        print(f"{Colors.GREEN}[SYS] OCLI ACTIVE | MODEL: {self.model_name}{status}{Colors.RESET}")
        print(f"{Colors.GRAY}[SYS] Type 'exit' to quit.{Colors.RESET}")
        while True:
            try:
                print("-" * 200)
                user_input = input(f"\n{Colors.YELLOW}{Colors.BOLD}[VibeCoder] > {Colors.RESET}").strip()
                print("")
                print("-" * 200)
                if user_input.lower() in ['exit', 'quit']: break
                if user_input.lower() in ['continue', 'c', '']:
                    if len(self.messages) > 1: user_input = "Please continue."
                    else: continue
                self.messages.append({'role': 'user', 'content': user_input})
                auto_count = 0
                while auto_count < 10:
                    self.compact_history()
                    self.process_chat()
                    last_msg = self.messages[-1].get('content', '') if self.messages else ""
                    if "CONTINUE" in last_msg.upper():
                        auto_count += 1
                        print(f"\n  {Colors.YELLOW}[AUTO] Continuing (Step {auto_count}/10){Colors.RESET}")
                        self.messages.append({'role': 'user', 'content': "Continue (Hidden)"})
                    else: break
            except KeyboardInterrupt: break

    def process_chat(self):
        available_tools = {'run_cmd': self.run_cmd, 'read_file': self.read_file, 'write_file': self.write_file, 'web_search': self.web_search}
        while True:
            try:
                interrupter.start_listening()
                stream = ollama.chat(
                    model=self.model_name,
                    messages=self.messages,
                    stream=True,
                    tools=[
                        {'type': 'function', 'function': {'name': 'run_cmd', 'description': 'Run shell command', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
                        {'type': 'function', 'function': {'name': 'web_search', 'description': 'Search web via DuckDuckGo. Use authoritative domains for official-source searches.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
                        {'type': 'function', 'function': {'name': 'read_file', 'description': 'Read file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}},
                        {'type': 'function', 'function': {'name': 'write_file', 'description': 'Write file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}}},
                    ]
                )
                content, tool_calls, response_metadata = "", [], {}
                print(f"\n{Colors.CYAN}{Colors.BOLD}OLAmma > {Colors.RESET}", end="", flush=True)
                in_thought, line_buffer = False, ""
                for chunk in stream:
                    if interrupter.interrupted.is_set():
                        print(f"\n  {Colors.RED}[INTERRUPTED]{Colors.RESET}")
                        break
                    msg = chunk.get('message', {})
                    if 'content' in msg:
                        token = msg['content']
                        content += token
                        if "<thought>" in token:
                            in_thought = True
                            print(f"{Colors.YELLOW}THINKING{Colors.RESET}", end="", flush=True)
                        elif "</thought>" in token:
                            in_thought = False
                            token = token.replace("</thought>", "")
                        if not in_thought:
                            line_buffer += token
                            if "\n" in line_buffer:
                                parts = line_buffer.split("\n")
                                for i in range(len(parts)-1):
                                    print(render_text(parts[i] + "\n"), end="", flush=True)
                                line_buffer = parts[-1]
                    if 'tool_calls' in msg: tool_calls.extend(msg['tool_calls'])
                    if 'total_duration' in chunk: response_metadata = chunk
                if line_buffer and not in_thought: print(render_text(line_buffer), end="", flush=True)
                print()
                interrupter.stop_listening()
                if interrupter.interrupted.is_set():
                    self.messages.append({'role': 'assistant', 'content': content + " [USER INTERRUPTED]"})
                    break
                self.messages.append({'role': 'assistant', 'content': content, 'tool_calls': tool_calls} if tool_calls else {'role': 'assistant', 'content': content})
                thoughts = re.findall(r'<thought>(.*?)</thought>', content, flags=re.DOTALL)
                if thoughts:
                    print(f"\n{Colors.YELLOW}{Colors.BOLD}THINKING{Colors.RESET}")
                    for t in thoughts: print(f"{Colors.GRAY}  > {render_text(t.strip())}{Colors.RESET}")
                self.display_metrics(response_metadata)
                if not tool_calls: break
                for tool in tool_calls:
                    name, args = tool['function']['name'], tool['function']['arguments']
                    if name in available_tools:
                        result = truncate_output(available_tools[name](**args))
                        self.messages.append({'role': 'tool', 'content': result, 'name': name})
                continue
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="qwen3.6:27b-coding-nvfp4")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()
    agent = OCLI(model_name=args.model, auto_mode=args.auto)
    agent.run()
