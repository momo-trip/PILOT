import os
import re
import shlex
import shutil
import subprocess
from typing import Dict, Iterable, List, Optional, Tuple

APT_UPDATE_RE  = re.compile(r'^\s*(sudo\s+)?apt(-get)?\s+update\b')
APT_INSTALL_RE = re.compile(r'^\s*(sudo\s+)?apt(-get)?\s+install\b')

INSTALL_TIMEOUT = 600  # seconds, per command


from utils_api import (
    read_json,
    write_json,
    read_file,
    create_file,
)

from llm_api import (
    ask_llm,
    ask_agent,
)

from pilot_lib.utils import (
    append_list_to_file,
    get_pure_cmd,
)


def get_tool_string(tool_json_path, target_cmd, target):
    """Return "cmd1, cmd2, ..." and whether the target command itself is listed."""
    pure_cmd = get_pure_cmd(target_cmd)
    names = [t['command_name'] for t in load_tools(tool_json_path)
             if t.get('command_name')]
    return ", ".join(names), pure_cmd in names


tool_template = f"""
{{
    "tools" : [
        {{
            "program_name" : ,
            "install_command" : [
                "install_command1",
                "install_command2",
                ...
            ]
            "command_name" : "command1",
        }},
        {{
            "program_name" : ,
            "install_command" : [
                "install_command1",
                "install_command2",
                ...
            ]
            "command_name" : "command2",
        }},...
    ]
    "ongoing" : true if the answer response will continue in subsequent responses. false otherwise,
}}
"""

def find_tool_llm(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version):
    
    prompt = []
    sum_modified_list = []
    opt_sum_modified_list = []
    pure_cmd = get_pure_cmd(target_cmd)

    prompt.extend([f"Please tell me the standard command tools to create valid input files for {pure_cmd} commad of the {target} program.",
                   "Please answer the representative commands and its install commands."])
    
    prompt.extend(["## Response guidelines:",
                "- Please write your answer in JSON format following the format below",
                "- Return your response as raw JSON only. Do NOT wrap the JSON in markdown code blocks. Do NOT use ```json or ``` markers.",
                "",
                "### \"tools\" key value:",
                f"- List representative standard command-line tools that can create valid input files for the target command ({pure_cmd})",
                "- Include only tools that are fully scriptable and non-interactive",
                "- Exclude tools that require GUI, interactive mode, or manual editing"
                "- For each tool, provide:",
                "  - program_name: The name of the software package to install",
                f"  - install_command: List of commands needed to install the tool on {os_version} (can be multiple steps)",
                "  - command_name: The actual command name used to create input files",
                "- Include only tools that directly create compatible input file formats",
                #"- Each tool MUST produce a valid input file from command-line arguments alone, with no pre-existing input file. Reject format converters.",
                "",
                "",
                "### \"ongoing\" key value:",
                "- Set to true if the response will continue in subsequent messages, false otherwise",
                "",
                ])
    
    prompt.extend(["- In summary, please respond in the following JSON format:"]) 
    prompt.extend([tool_template])

    rsp_json = None
    count = 1
 
    modified_list = []

    # tool_json_path = f"{tool_dir}/tools.json"
    # create_file(tool_json_path)

    ongoing_flag = None
    rsp_json = {}
    while(1):
        if count == 1:
            rsp_json = ask_llm(prompt, "init", llm_interface)

        if 'tools' in rsp_json:
            modified_list = rsp_json['tools']
            if not isinstance(modified_list, list):
                modified_list = [modified_list]
            sum_modified_list.extend(modified_list)
            append_list_to_file(tool_json_path, modified_list)
        
        if 'ongoing' in rsp_json:
            ongoing_flag = rsp_json['ongoing']
            ongoing_flag = False

        if ongoing_flag is False:
            break

        prompt = []
        prompt = ["Please continue the JSON data response.",
                  "If this is the final JSON data, set the 'ongoing' key to the boolean value False. If there is more JSON data remaining to follow, set the 'ongoing' key value to the boolean value True.",
                ]

        rsp_json = ask_llm(prompt, "continue", llm_interface)
        count += 1

    write_json(tool_json_path, sum_modified_list)


# CHANGED: successor of tool_template. The "ongoing" key is removed because
# the agent writes the complete file in one run.
tool_agent_template = f"""
{{
    "tools" : [
        {{
            "program_name" : ,
            "install_command" : [
                "install_command1",
                "install_command2",
                ...
            ]
            "command_name" : "command1",
        }},
        {{
            "program_name" : ,
            "install_command" : [
                "install_command1",
                "install_command2",
                ...
            ]
            "command_name" : "command2",
        }},...
    ]
}}
"""

def find_tool_agent(target, target_cmd, target_dir, tool_dir, tool_json_path, agent_iface, os_version):
    """Agent-based successor of find_tool().

    Prompt wording is kept verbatim from find_tool(). Only the parts that
    presuppose JSON-mode responses (tool_template, ongoing flag, response
    accumulation loop) are modified, and every such spot is marked with a
    CHANGED/REMOVED comment.
    """

    prompt = []
    pure_cmd = get_pure_cmd(target_cmd)

    # tool_json_path = os.path.abspath(f"{tool_dir}/tools.json")
    # create_file(tool_json_path)

    prompt.extend([f"Please tell me the standard command tools to create valid input files for {pure_cmd} commad of the {target} program.",
                   "Please answer the representative commands and its install commands."])
    
    prompt.extend(["## Response guidelines:",
                # CHANGED: JSON is now written to a file by the agent, not returned as a chat response.
                #"- Please write your answer in JSON format following the format below",
                #"- Return your response as raw JSON only. Do NOT wrap the JSON in markdown code blocks. Do NOT use ```json or ``` markers.",
                f"- Please write your answer in JSON format following the format below, into the file {tool_json_path} using the Write tool.",
                "",
                "### \"tools\" key value:",
                f"- List representative standard command-line tools that can create valid input files for the target command ({pure_cmd})",
                "- Include only tools that are fully scriptable and non-interactive",
                "- Exclude tools that require GUI, interactive mode, or manual editing"
                "- For each tool, provide:",
                "  - program_name: The name of the software package to install",
                f"  - install_command: List of commands needed to install the tool on {os_version} (can be multiple steps)",
                "  - command_name: The actual command name used to create input files",
                "- Include only tools that directly create compatible input file formats",
                #"- Each tool MUST produce a valid input file from command-line arguments alone, with no pre-existing input file. Reject format converters.",
                "",
                "",
                # REMOVED: "ongoing" was an artifact of output-token-limited JSON
                # responses. The agent writes the complete file directly, so
                # multi-part continuation no longer applies.
                #"### \"ongoing\" key value:",
                #"- Set to true if the response will continue in subsequent messages, false otherwise",
                #"",
                ])
    
    prompt.extend(["- In summary, please write the JSON data in the following format:"]) # CHANGED: "respond in" -> "write ... in" (file output)
    prompt.extend([tool_agent_template])  # CHANGED: template without the "ongoing" key (see below)

    # CHANGED: tool-usage constraints, successor of "## Response format".
    prompt.extend(["",
        "## How to work:",
        f"- Write the JSON data to {tool_json_path} using the Write tool.",
        f"- Do NOT create, modify, or delete any files other than {tool_json_path}.",
        "- When finished, reply with a short summary only (number of tools listed). Do NOT paste the JSON itself into your reply.",
    ])

    # CHANGED: the whole while(1) loop (ongoing / continue dispatch /
    # sum_modified_list accumulation) is replaced by a single agent run.
    res = ask_agent(prompt, "init", agent_iface)
    if res.is_error:
        raise RuntimeError(f"find_tool agent failed (session={res.session_id})")

    # Deliverable validation: check the filesystem instead of parsing JSON.
    written = read_file(tool_json_path)
    if not written or not written.strip():
        res = ask_agent(
            f"You did not write any JSON data to {tool_json_path}. "
            f"Please write it now, following all the previous guidelines.",
            "continue", agent_iface)
        written = read_file(tool_json_path)
        if not written or not written.strip():
            raise RuntimeError("Agent produced no tools.json.")

    print("============= answer =============")

    

def find_tool(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version):

    if llm_interface.AGENT is False:    
        find_tool_llm(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version)
    else:
        find_tool_agent(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version)


def check_command_availability(tool_json_path, target_cmd, target) -> Dict[str, bool]:
    """
    Check if commands specified in the JSON are available on the system.
    Args:
        tools_json: List of tool dictionaries with 'command_name' field
        
    Returns:
        Dictionary mapping command_name to availability (True/False)
    """
    # tools_data = read_json(tool_json_path)
    availability = {}
    
    for tool in load_tools(tool_json_path):
        command_name = tool.get('command_name')
        if not command_name:
            continue
            
        try:
            # Use 'command -v' to check if command exists
            result = subprocess.run(
                f'command -v {shlex.quote(command_name)}',
                shell=True, 
                executable='/bin/bash',
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            availability[command_name] = (result.returncode == 0)
        except subprocess.TimeoutExpired:
            print(f"  [timeout] command -v {command_name}")
            availability[command_name] = False
    
    print("Command availability:")
    for cmd, avail in availability.items():
        status = "✓ Available" if avail else "✗ Missing"
        print(f"  {cmd}: {status}")
    
    """
    # Get lists
    available = [cmd for cmd, avail in availability.items() if avail]
    missing = [cmd for cmd, avail in availability.items() if not avail]
    print(f"\nAvailable: {available}")
    print(f"Missing: {missing}")
    if len(missing) > 0:
        raise ValueError("Missing exists")
    
    tool_string, cmd_self = get_tool_string(tool_json_path, target_cmd, target)
    if tool_string == "":
        raise ValueError("tool_string is empty")
    """

    return availability


def _sudo_prefix() -> str:
    """No sudo needed when running as root. If non-root and sudo is absent,
    return an empty prefix and let the command fail visibly."""
    if os.geteuid() == 0:
        return ""
    return "sudo env " if shutil.which("sudo") else ""


def _normalize(cmd: str, sudo: str) -> str:
    """Make an LLM-supplied install command non-interactive and sudo-agnostic."""
    cmd = cmd.strip()

    # Strip any sudo the LLM added; containers often run as root without sudo.
    cmd = re.sub(r'^\s*sudo\s+', '', cmd)

    if APT_UPDATE_RE.match(cmd) or APT_INSTALL_RE.match(cmd):
        if APT_INSTALL_RE.match(cmd) and not re.search(
                r'(^|\s)(-y|--yes|--assume-yes)(\s|$)', cmd):
            cmd = re.sub(r'(apt(-get)?\s+install)', r'\1 -y', cmd, count=1)
        # Avoid dying immediately on a contended dpkg lock.
        if 'Lock::Timeout' not in cmd:
            cmd = re.sub(r'(apt(-get)?)', r'\1 -o DPkg::Lock::Timeout=120',
                         cmd, count=1)
        prefix = f"{sudo}DEBIAN_FRONTEND=noninteractive " if sudo \
                 else "DEBIAN_FRONTEND=noninteractive "
        return prefix + cmd

    return f"{sudo}{cmd}" if sudo else cmd


def _run(cmd: str) -> bool:
    print(f"  $ {cmd}")
    try:
        r = subprocess.run(cmd, shell=True, executable='/bin/bash',
                           capture_output=True, text=True,
                           timeout=INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"    [timeout after {INSTALL_TIMEOUT}s]")
        return False
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-5:]
        print(f"    [exit {r.returncode}] " + " / ".join(tail))
        return False
    return True


def load_tools(tool_json_path: str) -> List[dict]:
    """Read tools.json and return a list of tool entries.

    Accepts both the bare-array form written by find_tool_llm and the
    {"tools": [...]} form the agent produces.
    """
    data = read_json(tool_json_path)
    if isinstance(data, dict):
        data = data.get("tools", [])
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"no tool entries in {tool_json_path}")
    return [t for t in data if isinstance(t, dict)]


def install_tools(tool_json_path: str,
                  only: Optional[Iterable[str]] = None) -> Dict[str, bool]:
    """Execute the install_command entries listed in tools.json.

    Args:
        tool_json_path: absolute path to tools.json
        only: restrict execution to entries whose command_name is in this
              set. None means all entries.

    Returns:
        Mapping of program_name to whether every step succeeded.
        No exception is raised on individual failures; the caller decides
        based on a subsequent command -v check.
    """
    tools = load_tools(tool_json_path)   # shared helper: normalizes dict/bare-array
    only_set = set(only) if only is not None else None
    sudo = _sudo_prefix()

    # Deduplicate by (program_name, install_command). The same package may
    # appear under several command_name values and must only be installed once.
    plans: List[Tuple[str, List[str]]] = []
    seen = set()
    for t in tools:
        cmd_name = t.get('command_name')
        if only_set is not None and cmd_name not in only_set:
            continue
        program = t.get('program_name') or cmd_name or "<unknown>"
        steps = t.get('install_command') or []
        if isinstance(steps, str):
            steps = [steps]
        key = (program, tuple(steps))
        if key in seen:
            continue
        seen.add(key)
        plans.append((program, list(steps)))

    if not plans:
        print("install_tools: nothing to install")
        return {}

    # Collapse every apt-get update into a single refresh up front.
    needs_update = any(APT_UPDATE_RE.match(s) for _, steps in plans for s in steps)
    if needs_update:
        print("install_tools: refreshing package index")
        _run(_normalize("apt-get update", sudo))

    results: Dict[str, bool] = {}
    for program, steps in plans:
        print(f"install_tools: {program}")
        ok = True
        for step in steps:
            if APT_UPDATE_RE.match(step):
                continue                 # already handled above
            if not _run(_normalize(step, sudo)):
                ok = False
                break                    # later steps depend on earlier ones
        results[program] = ok
        print(f"  -> {'ok' if ok else 'FAILED'}")

    return results


def native_tool_configuration(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version):
    
    tool_json_path = os.path.abspath(tool_json_path)

    find_tool(target, target_cmd, target_dir, tool_dir, tool_json_path, llm_interface, os_version)

    MAX_ATTEMPTS = 10
    prev_missing = None
    missing: List[str] = []

    for attempt in range(MAX_ATTEMPTS):

        avail = check_command_availability(tool_json_path, target_cmd, target)
        missing = [c for c, ok in avail.items() if not ok]
        if not missing:
            break
        # Bail out early when a round of installs changed nothing; a command
        # that never appears on PATH (e.g. a locally built target) will not
        # be fixed by retrying apt.
        if set(missing) == prev_missing:
            # raise RuntimeError(f"install made no progress: {missing}")
            raise RuntimeError(
                f"could not install {', '.join(sorted(missing))} on {os_version}. "
                f"No installation candidate is available. "
                f"Remove it from {tool_json_path} and rerun, "
                f"or install it manually."
            )

        prev_missing = set(missing)
        install_tools(tool_json_path, only=missing)

    else:
        raise RuntimeError(f"still missing after {MAX_ATTEMPTS}: {missing}")

    # Post-condition: the tool list must be usable downstream.
    tool_string, cmd_self = get_tool_string(tool_json_path, target_cmd, target)
    if not tool_string:
        raise RuntimeError(f"no usable tools in {tool_json_path}")
    print(f"native tools: {tool_string} (includes target itself: {cmd_self})")