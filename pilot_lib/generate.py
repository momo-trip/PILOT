import os
import random
import shlex
import subprocess
import sys
import threading
import time
import glob
import signal

from datetime import datetime
from pathlib import Path
from typing import Dict, NamedTuple

from utils_api import (
    read_json,
    write_json,
    read_file,
    write_file,
    delete_file,
    create_permissioned_file,
    append_file,
    get_timestamp,
    get_coverage,
    get_lined_specific_code,
    get_lined_code,
    find_matching_path,
    run_script,
)

from llm_api import (
    save_coverage_report,
    get_dir_struct,
    ask_llm,
    reflect_line_modification,
    adjust_prompt,
    trim_data,
    trim_code,
    ask_agent,
)

from pilot_lib.utils import (
    get_metadata,
    get_related_data,
    get_coverage,
    run_cov_script,
    run_branch_cov_script,
    write_testcase,
    parse_function_id,
    get_metrics,
    get_pure_cmd,
    append_list_to_file,
    RepairContext,
)

from pilot_lib.tool import get_tool_string


def clear_gcda_files(target_dir):
    print("Deleting coverage files")
    target_path = Path(target_dir)
    
    # Extensions targeted for deletion
    coverage_extensions = ['*.gcda', '*.gcov'] # , '*.gcno', '*.gcov'  #coverage_extensions = ['*.gcda', '*.gcno', '*.gcov']
    
    deleted_files = 0
    for ext in coverage_extensions:
        # Search the directory recursively
        pattern = str(target_path / '**' / ext)
        files = glob.glob(pattern, recursive=True)
        
        for file in files:
            try:
                os.remove(file)
                deleted_files += 1
                print(f"Deleted: {file}")
            except OSError as e:
                print(f"Error deleting {file}: {e}")
    
    print(f"Total {deleted_files} coverage files deleted")


def get_func_sum(callee_main_path):

    related_data = read_json(callee_main_path)
    if related_data is None:
        return 0
    return len(related_data)


def check_command_availability(tool_json_path, target_cmd, target) -> Dict[str, bool]:
    """
    Check if commands specified in the JSON are available on the system.
    Args:
        tools_json: List of tool dictionaries with 'command_name' field
        
    Returns:
        Dictionary mapping command_name to availability (True/False)
    """
    tools_data = read_json(tool_json_path)
    availability = {}
    
    for tool in tools_data:
        command_name = tool.get('command_name')
        if not command_name:
            continue
            
        try:
            # Use 'command -v' to check if command exists
            result = subprocess.run(
                ['command', '-v', command_name],
                shell=True,
                executable='/bin/bash',
                capture_output=True,
                text=True,
                timeout=5
            )
            availability[command_name] = (result.returncode == 0)
        except (subprocess.TimeoutExpired, Exception):
            availability[command_name] = False
    
    print("Command availability:")
    for cmd, avail in availability.items():
        status = "✓ Available" if avail else "✗ Missing"
        print(f"  {cmd}: {status}")
    
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
        
    return availability


def set_timeout(
    seconds, start_time, process_type, target_cmd, target, 
    target_dir, original_target_dir, archive_dir, meta_dir, 
    result_path, dep_json_path, logging_path,
    fixed_explore_time, temperature, total_time, interval, 
    fixed_metric, llm_choice, llm_model, strategy,
    chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
    cov_report_path, select_path, database_dir, token_path
):
    def timeout_handler(signum, frame):
        sys.stderr.write(f"Timeout ({seconds} seconds) occurred\n")
        stop_periodic_server()  # Stop the periodic thread

        get_final_report(
            process_type, start_time, 
            target_dir, original_target_dir, archive_dir, 
            result_path, dep_json_path, meta_dir, logging_path, target_cmd, target,
            fixed_explore_time, temperature, total_time, interval, 
            fixed_metric, llm_choice, llm_model, strategy,
            chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
            cov_report_path, select_path, database_dir, token_path,
            config_data
        )
        os._exit(1)  # Terminate the entire process

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)


periodic_running = True
periodic_start_time = None  # Variable to record the start time

def run_periodic(
    interval, target_dir, azure_endpoint, target_function_count, 
    tmp_branch_path, tmp_line_path, tmp_function_path
):
    """Keep running the function against the directory at the specified interval"""

    global periodic_running, periodic_start_time
    periodic_start_time = time.time()  # Record the start time

    while periodic_running:
        elapsed_time = time.time() - periodic_start_time
        minutes = int(elapsed_time // 60)  # Compute the minutes
        if azure_endpoint is None:
            print(f"Elapsed time: {elapsed_time:.2f} seconds ({minutes} min)")
        else:
            print(f"Elapsed time: {elapsed_time:.2f} seconds ({minutes} min), region: {azure_endpoint}")

        print(f"Target function count: {target_function_count}")

        branch_path = tmp_branch_path
        line_path = tmp_line_path
        function_path = tmp_function_path

        time.sleep(interval)  # Wait for the specified number of seconds
        

def start_periodic_server(
    process_type, strategy, interval, target_dir, azure_endpoint, target_function_count, 
    tmp_branch_path, tmp_line_path, tmp_function_path
):
    if process_type != "prepare" and process_type != "preset" and process_type != "gcno":
        periodic_thread = threading.Thread(target=run_periodic, args=(interval, target_dir, azure_endpoint, target_function_count, tmp_branch_path, tmp_line_path, tmp_function_path))
        periodic_thread.daemon = True  # Terminate together when the main thread ends
        periodic_thread.start()


def get_tool_cmd(strategy, tool_string):
    tool_cmd = f"- Please include commands to create valid input files using appropriate standard tools: {tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage."
        
    if strategy == "wo_tool":
        tool_cmd = f"- Please also include commands to create input files within the shell script."
                        
    return tool_cmd


def check_excluded(see_path, target_dir):
    excluded_dirs = ['build', '.github', '.gitlab', '.tx', '.git', 'fuzz', 'test'] 

    abs_path = os.path.abspath(see_path)

    abs_excluded_dirs = []
    for excluded_dir in excluded_dirs:
        excluded_dir = f"{target_dir}/{excluded_dir}"
        abs_excluded_dir = os.path.abspath(excluded_dir)
        abs_excluded_dirs.append(abs_excluded_dir)
    
    print(f"abs_excluded_dirs: {abs_excluded_dirs}")

    for excluded_dir in abs_excluded_dirs:
        if abs_path.startswith(excluded_dir):
            return True
    return False


def is_empty_string(file_code):
    if file_code is None:
        return True
    
    if file_code.strip() == "":
        return True
        
    return False

    

basic_template = f"""
{{
    "answer" : "answer cotent",
    "max_counter" : highest file counter number used in your response. If input files are not used, use null.",
    "ongoing" : true if the response will continue. false otherwise,
    "reason" : (reason, if needed)
}}
"""

basic_repair_template = f"""
# In "read_data" mode
{{
    "mode" : "read_data",
    "target_files" : [path/to/file1, path/to/file2, ..., path/to/fileN], 
    "file_slices" : (if necessary, otherwise None) [
        {{
            "file_path" : (file path),
            "start_line" : (start_line of the scope),
            "end_line" : (end_line of the scope),
        }},...
    ]
    "ongoing_in_mode" : true if the "answer" response in "read_data" mode is long and will continue in subsequent responses. false otherwise,
    "reason" : explanatory text for the response (insert here if needed)
}}

# In "modify_data" mode
{{
    "mode" : "modify_data",
    "answer" : [
        {{
            "file_path" : (file path),
            "start_line" : (start line of the original code to be deleted; must reflect the original range to be replaced),
            "end_line" : (end line of the original code to be deleted; must reflect the original range to be replaced),
            "modified_data" : (Content of the corrected code without any omission. Content of the corrected code as a string if is_JSON is false, or as a direct JSON object if is_JSON is true.),
        }},
        {{
            "file_path" : (file path),
            "start_line" : (start line of the original code to be deleted; must reflect the original range to be replaced),
            "end_line" : (end line of the original code to be deleted; must reflect the original range to be replaced),
            "modified_data" : (Content of the corrected code without any omission. Content of the corrected code as a string if is_JSON is false, or as a direct JSON object if is_JSON is true.),
        }},...
    ],
    "ongoing_in_mode" : true if the "answer" response in "modify_data" mode is long and will continue in subsequent responses. false otherwise,
    "reason" : explanatory text for the response (insert here if needed)
}}
"""

def ask_basic_command_llm(ctx):
    
    print("Asking basic commands...")
    output_max = ctx.llm_interface.output_max
    prompt = []
    sum_modified_list = []
    opt_sum_modified_list = []

    initial_std_out = None

    cmd_exe = database_json[ctx.target_cmd]["cmd_exe"]
    pure_cmd = get_pure_cmd(ctx.target_cmd)
    
    prompt.extend([f"Please write a shell script that demonstrates the most basic usage of {pure_cmd} command to process an input file.",
                   "I want to see the simplest command invocation with minimal options, just specifying an input file and executing it."
                   ])
    
    tool_cmd = get_tool_cmd(ctx.strategy, ctx.tool_string)
    prompt.extend(["", "## Response rules:",
                         f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                         f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                         f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                         f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                         f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                         "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                         #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                         f"- Please do not include build execution (./{build_path}) in the shell code in {ctx.paths.run_test_path}.",
                         #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                         f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute commands using only existing binaries.",
                         #f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                         #f"- Please set as many options as possible in a single command to explore more execution paths.",
                         f"- Please make input files that commands use have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                         #f"- Please also include commands to create input files within the shell script.",
                         #f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                         f"{tool_cmd}",
                         f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                         f"- Please do not include commands that delete input files in the shell script.",
                         f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                         "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                         #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                         f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                         #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                         "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                         "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                         ])

    prompt.extend(["- In summary, please respond in the following JSON format:"]) 
    prompt.extend([basic_template]) 

    rsp_json = None
    count = 0

    delete_file(ctx.paths.run_test_path)

    prompt.extend([f"\n## Current content of the {ctx.paths.run_test_path} file:"])
    file_string = get_lined_code(ctx.paths.run_test_path, ctx.paths.work_dir)
    prompt.extend([f'{file_string}\n'])

    prompt.extend(["", "## Directory Structure of the Target Program:"]) 
    directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir) # , test_id
    write_file(f"{database_dir}/directry_structure.txt", directory_structure)
    directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 6000) #, 10000)
    prompt.extend([directory_structure, ""])
    

    ongoing_flag = None
    error = None
    std_out = None
    rsp_json = {}

    while(1):
        if count == 0:
            rsp_json = ask_llm(prompt, "init", ctx.llm_interface)

        if 'answer' in rsp_json:
            modified_list = rsp_json['answer']
            if not isinstance(modified_list, list):
                modified_list = [modified_list]
            sum_modified_list.extend(modified_list)
            append_list_to_file(ctx.paths.run_test_path, modified_list)

        if 'ongoing' in rsp_json:
            ongoing_flag = rsp_json['ongoing']
            ongoing_flag = False

        if ongoing_flag is False:
            break

        prompt = [f"Please continue your answer for the code that performs basic usage of {pure_cmd}."]
        
        prompt.extend(["", "## Response rules:",
                        #"If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                        #"If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {ctx.llm_interface.output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                        "- The modified code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])
                    
        rsp_json = ask_llm(prompt, "continue", ctx.llm_interface)
    
        prompt = []
        count += 1

    print("============= answer =============")

    error = None
    std_out = None
    ongoing_in_mode_flag = None

    sum_target_list = []
    sum_modified_list = []
    sum_deleted_list = []

    sum_slice_list = []
    repair_count = 0
    count = 0
    mode = None

    while(1):
        error, std_out, repair_count = run_script(
            run_test_path, 100, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, mode
        )
        if WO_VALIDATION is True:
            break

        if error is None and (ongoing_in_mode_flag is False or ongoing_in_mode_flag is None):
            break

        if target_cmd == "editcap_old":
            break

        prompt = []
        prompt.extend(["When I ran the test case shell code you provided, I encountered the following error.",
                   f"Please write a shell script that demonstrates the most basic usage of {pure_cmd} command to process an input file.",
                   f"I want to see the simplest command invocation with minimal options, just specifying an input file and executing it."
                   ])

        if count == 0:
            tool_cmd = get_tool_cmd(strategy, tool_string)
            prompt.extend(["", "## Response rules:",
                         f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                         f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                         f"- Even if the program implements other commands, please write test cases only for the {ctx.target_cmd} command for now.",
                         f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                         f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                         "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                         #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                         f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                         #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                         f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute commands using only existing binaries.",
                         #f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                         #f"- Please set as many options as possible in a single command to explore more execution paths.",
                         f"- Please make input files that commands use have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                         #f"- Please also include commands to create input files within the shell script.",
                         # f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                         f"{tool_cmd}",
                         f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                         f"- Please do not include commands that delete input files in the shell script.",
                         f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                         "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                         #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                         f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                         #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                         "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                         #"- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                         ])

            prompt.extend(["- In summary, please respond in the following JSON format:"]) 
            prompt.extend([basic_repair_template])

        elif count > 1:
            if mode == 'read_data':
                print(f"In mode: {mode}")
                read_prompt = ["- The content obtained in read_data mode is as follows.", ""] 

                slice_set = set()
                for slice_item in sum_slice_list:
                    slice_set.add(slice_item['file_path'])

                new_sum_target_list = []
                print(f"sum_target_list: {sum_target_list}")
                for see_path in sum_target_list:
                    if see_path not in slice_set:
                        new_sum_target_list.append(see_path)
                sum_target_list = new_sum_target_list

                sum_target_list = list(set(sum_target_list))
                for see_path in sum_target_list:
                    is_excluded = check_excluded(see_path, ctx.paths.work_dir)
                    if is_excluded:
                        continue

                    file_code = get_lined_code(see_path, ctx.paths.work_dir)
                    file_code = trim_code(see_path, file_code, 10000)

                    read_prompt.extend([f"## Content of the file {see_path}:"])
                    if not is_empty_string(file_code):
                        read_prompt.extend([f'{file_code}\n'])
                    else:
                        read_prompt.extend([f'None\n'])
                
                for see_item in sum_slice_list:
                    is_excluded = check_excluded(see_item['file_path'], work_dir)
                    if is_excluded:
                        continue

                    file_code = get_lined_specific_code(ctx.paths.database_dir, see_item['file_path'], see_item['start_line'], see_item['end_line'])
                    file_code = trim_code(see_item['file_path'], file_code, 10000)

                    read_prompt.extend([f"## Content of {see_item['start_line']} - {see_item['end_line']} lines in the file {see_item['file_path']}:"]) 
                    read_prompt.extend([f'{file_code}\n'])


        prompt.extend([f"\n## Current content of the {ctx.paths.run_test_path} file:"])
        file_string = get_lined_code(ctx.paths.run_test_path, ctx.paths.work_dir)
        prompt.extend([f'{file_string}\n'])

        if error is not None:
            prompt.extend(["", "## Error when executing the testcase shell code:"])
            prompt.extend([f"{error}"])
            initial_error = None 

        if std_out is not None:
            prompt.extend(["", "## Standard output when executing the testcase shell code:"])
            prompt.extend([f"{initial_std_out}"])
            std_out = None 
        
        if count > 1:
            prompt.extend(["", "## Directory Structure of the Target Program:"]) 
            directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir) # , test_id
            write_file(f"{database_dir}/directry_structure.txt", directory_structure)
            directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 10000)
            prompt.extend([directory_structure, ""])

        rsp_json = ask_llm(prompt, "continue", ctx.llm_interface)

        if 'mode' in rsp_json:
            mode = rsp_json['mode']

            if mode == 'read_data':
                if 'target_files' in rsp_json:
                    target_list = rsp_json['target_files']
                    if not isinstance(target_list, list):
                        target_list = [target_list]
                    sum_target_list.extend(target_list)
                
                if 'file_slices' in rsp_json and rsp_json['file_slices'] is not None:
                    slice_list = rsp_json['file_slices']
                    if not isinstance(slice_list, list):
                        slice_list = [slice_list]
                    sum_slice_list.extend(slice_list)

            if mode == 'modify_data':
                if 'answer' in rsp_json:
                    modified_list = rsp_json['answer']
                    if not isinstance(modified_list, list):
                        modified_list = [modified_list]
                    sum_modified_list.extend(modified_list)
                    reflect_line_modification(modified_list, ctx.paths.work_dir, ctx.paths.database_dir)

        if 'ongoing_in_mode' in rsp_json:
            ongoing_in_mode_flag = rsp_json['ongoing_in_mode']
                            
        count += 1

    timestamp = get_timestamp()
    write_testcase(ctx.paths.run_test_path, ctx.paths.snap_dir, timestamp)
    print("============= answer =============")


def ask_basic_command_agent(ctx):
    """ask_agent version of ask_basic_command.
    
    The agent writes run_test_path (a shell script) directly via its file tools;
    the orchestrator still runs it with run_script. The old ongoing / mode
    dispatch (read_data / modify_data) and the two staged while-loops are
    removed, since the Agent SDK absorbs them. Prompt text is kept as in the
    original; only the mode descriptions, the JSON response template, and the
    ongoing / output_max lines are dropped.
    """

    print("Asking basic commands...")

    cmd_exe = database_json[ctx.target_cmd]["cmd_exe"]
    pure_cmd = get_pure_cmd(ctx.target_cmd)

    # --- Agent execution environment: inspect source + author the shell script.
    #     No build / recompile; the script is run externally by run_script. ---
    agent = agent_interface
    agent.allowed_tools = ["Read", "Grep", "Glob", "Write", "Edit"]
    agent.add_dirs = list({
        os.path.dirname(os.path.normpath(ctx.paths.run_test_path)),
        ctx.paths.target_dir, ctx.original_target_dir, ctx.paths.database_dir, ctx.paths.work_dir,
    })
    if agent.session_path:
        delete_file(agent.session_path)

    delete_file(ctx.paths.run_test_path)

    error = None
    std_out = None
    repair_count = 0
    count = 0
    mode = None

    while (1):
        prompt = []

        if count == 0:
            # --- first request (from the original first prompt block) ---
            prompt.extend([f"Please write a shell script that demonstrates the most basic usage of {pure_cmd} command to process an input file.",
                           "I want to see the simplest command invocation with minimal options, just specifying an input file and executing it."
                           ])
        else:
            # --- retry after an execution error (from the original second loop) ---
            prompt.extend(["When I ran the test case shell code you provided, I encountered the following error.",
                           f"Please write a shell script that demonstrates the most basic usage of {pure_cmd} command to process an input file.",
                           f"I want to see the simplest command invocation with minimal options, just specifying an input file and executing it."
                           ])

        tool_cmd = get_tool_cmd(strategy, tool_string)
        prompt.extend(["", "## Response rules:",
                             f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                             f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                             f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                             f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                             f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                             f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                             "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                             f"- Please do not include build execution (./{build_path}) in the shell code in {ctx.paths.run_test_path}.",
                             f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute commands using only existing binaries.",
                             f"- Please make input files that commands use have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                             f"{tool_cmd}",
                             f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                             f"- Please do not include commands that delete input files in the shell script.",
                             f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                             "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                             "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections.",
                             ])

        # --- agent-facing closing (replaces the old JSON format / mode blocks) ---
        prompt.extend(["",
            "## How to work:",
            "- You have file tools available (Read/Grep/Glob to inspect the target source, Write/Edit to author files).",
            f"- Read the relevant source if needed, then write the finished shell script directly to {ctx.paths.run_test_path}.",
            "- Do not build, recompile, or run the script yourself; it is executed externally after you finish.",
            "- End your turn once the shell script is fully written (no abbreviations)."])

        # --- current content of run_test_path ---
        prompt.extend([f"\n## Current content of the {ctx.paths.run_test_path} file:"])
        file_string = get_lined_code(rctx.paths.un_test_path, ctx.paths.work_dir)
        prompt.extend([f'{file_string}\n'])

        # --- previous execution feedback (from the original error / std_out injection) ---
        if error is not None:
            prompt.extend(["", "## Error when executing the testcase shell code:"])
            prompt.extend([f"{error}"])
            error = None

        if std_out is not None:
            prompt.extend(["", "## Standard output when executing the testcase shell code:"])
            prompt.extend([f"{std_out}"])
            std_out = None

        # --- directory structure ---
        prompt.extend(["", "## Directory Structure of the Target Program:"])
        directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir)
        write_file(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure)
        directory_structure = trim_code(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure, 6000)
        prompt.extend([directory_structure, ""])

        prompt = adjust_prompt(prompt)

        # agent run (replaces the ask_llm receive-loop + append_list_to_file / reflect_line_modification)
        if count == 0:
            memory_type = "init" 
        else:
            memory_type = "continue"

        result = ask_agent(prompt, memory_type, agent)
        if result.is_error:
            print(f"[agent] run reported error (turns={result.num_turns})")

        # --- run the script the agent just wrote ---
        error, std_out, repair_count = run_script(
            ctx.paths.run_test_path, 100, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, mode
        )

        if WO_VALIDATION is True:
            break

        if error is None:
            break

        if target_cmd == "editcap_old":
            break

        count += 1

    timestamp = get_timestamp()
    write_testcase(ctx.paths.run_test_path, ctx.paths.snap_dir, timestamp)
    print("============= answer =============")


def ask_basic_command(
    paths, llm_interface, target_cmd, 
    database_json, max_iterations, tool_string, strategy, testfile_counter, WO_VALIDATION
):
    ctx = RepairContext(
        paths=paths,
        llm_interface=llm_interface,
        select=False,
        cov_target=cov_target,
        strategy=strategy,
        max_num_test=max_num_test,
        entry=entry,
        original_run_test_path=target_entry['original_run_test_path'],
        repair_count=repair_count,
        target_path=target_path,
        target_function=target_function,
        target_uncovered_ratio=target_uncovered_ratio,
        target_branch=target_branch,
        target_line=target_line,
        target_end_line=target_end_line,
        target_cmd=target_cmd,
        execute_path=execute_path,
        cmd_list=cmd_list,
        test_path=None,
        file_path=None,
        test_id=None,
        function_name=None,
        main_flag=None,
        explore_time=explore_time,
        cmd_exe=cmd_exe,
        notes=notes,
    )

    if llm_interface.AGENT is False:
        ask_basic_command_llm(ctx)
    else:
        ask_basic_command_agent(ctx)


def write_time(time_path, activity, action, repair_target, timestamp=None):
    formatted_time = None

    if timestamp is not None:
        # When timestamp is a float (UNIX timestamp)
        if isinstance(timestamp, float):
            datetime_obj = datetime.fromtimestamp(timestamp)
            # When unifying the timestamp into string format as well
            timestamp = datetime_obj.strftime('%Y-%m-%d-%H-%M-%S')
        # When timestamp is a string
        else:
            datetime_obj = datetime.strptime(timestamp, '%Y-%m-%d-%H-%M-%S')

        formatted_time = datetime_obj.strftime("%Y%m%d_%H%M%S")
    

    with open(time_path, 'a') as f:
        f.write(f"{activity},{repair_target},{action},{timestamp},{formatted_time}\n")



def get_path_info_wide(callee_main_path, target_entry, function_branch_path):
    
    prompt = []
    candidates = []
    count = 1
    callee_data = read_json(callee_main_path)
    
    # Add a list to track the length of paths
    path_lengths = []
    
    all_paths = []
    for item in callee_data:
        if item['name'] == target_entry['target_function'] and item['file_path'] == target_entry['target_path']:
            if 'all_paths' not in item:
                path_list = []
            else:
                path_list = item['all_paths']
            
            for path_item in path_list:
                candidates.append(f"Path candidate {count}")
                i = 1
                for tiny_path in path_item['path']:
                    if i == 1:
                        candidates.append(f"{tiny_path}")
                    else:
                        candidates.append(f"-> {tiny_path}")
                    i += 1
                #candidates.extend(path_item['path'])
                length = len(path_item['path'])
                # Record the path length
                path_lengths.append(length)
                candidates.append("")
                count += 1

                all_paths.extend(path_item['path'])            
            break

    # Compute the minimum and maximum path lengths
    min_length = min(path_lengths) if path_lengths else 0
    max_length = max(path_lengths) if path_lengths else 0
    
    prompt.extend(["## Fucntion call relationship from main():", "Please select one path from the possible paths below and write a test case that reaches that target function."])
    prompt.extend(candidates)
    
    all_paths = list(set(all_paths))
    result = {}
    for item in all_paths:
        result[item] = False

    cov_data = read_json(function_branch_path)
    if cov_data is not None:
        for target_item in result:
            target_name, target_path, target_line = parse_function_id(target_item)
            found = False

            for file_path, item in cov_data['files'].items():
                for func_item in item['functions']:
                    if file_path == target_path and func_item['name'] == target_name:
                        if func_item['called'] is True:
                            result[target_item] = True
                            found = True
                    if found:
                        break
                if found:
                        break
        
    covered_prompt = []
    covered_prompt.append(f"## Alreadly covered functions when the previously generated testcase ({ctx.paths.run_test_path}) was executed")
    covered_prompt.append("### Covered functions")
    count = 0
    for key, value in result.items():
        if value == True:
            covered_prompt.append(key)
            count += 1

    if count == 0:
        covered_prompt.append("None")

    return prompt, count, min_length, max_length, covered_prompt



autonomous_template = f"""
# In "read_data" mode
{{
    "mode" : "read_data",
    "target_files" : [path/to/file1, path/to/file2, ..., path/to/fileN], 
    "file_slices" : (if necessary, otherwise None) [
        {{
            "file_path" : (file path),
            "start_line" : (start_line of the scope),
            "end_line" : (end_line of the scope),
        }},...
    ]
    "ongoing_in_mode" : true if the "answer" response in "read_data" mode is long and will continue in subsequent responses. false otherwise,
    "ongoing" : true if the response will continue in a different mode. false otherwise,
    "reason" : explanatory text for the response (insert here if needed)
}}

# In "modify_data" mode
{{
    "mode" : "modify_data",
    "answer" : [
        {{
            "file_path" : (file path),
            "start_line" : (start line of the original code to be deleted; must reflect the original range to be replaced),
            "end_line" : (end line of the original code to be deleted; must reflect the original range to be replaced),
            "is_deletion" : True for deletion only, False for modification,
            "overwrite_all" : Flag for full file modification. If true, overwrites the whole file; if false, modifies only the specified lines
            "modified_data" : (Content of the corrected code without any omission. Content of the corrected code as a string if is_JSON is false, or as a direct JSON object if is_JSON is true.),
        }},
        {{
            "file_path" : (file path),
            "start_line" : (start line of the original code to be deleted; must reflect the original range to be replaced),
            "end_line" : (end line of the original code to be deleted; must reflect the original range to be replaced),
            "is_deletion" : True for deletion only, False for modification,
            "overwrite_all" : Flag for full file modification. If true, overwrites the whole file; if false, modifies only the specified lines
            "modified_data" : (Content of the corrected code without any omission. Content of the corrected code as a string if is_JSON is false, or as a direct JSON object if is_JSON is true.),
        }},...
    ],
    "ongoing_in_mode" : true if the "answer" response in "modify_data" mode is long and will continue in subsequent responses. false otherwise,
    "ongoing" : true if the response will continue in a different mode. false otherwise,
    "ready_to_execute" : true if this response marks the end of a coherent modification set and it's ready to be tested; false otherwise,
    "max_counter":  highest file counter number used in your response. If input files are not used, use null."
    "reason" : explanatory text for the response (insert here if needed)
}}

# In "execute_command" mode
{{
    "mode" : "execute_command",
    "answer" : shell script content to be executed,
    "ongoing_in_mode" : true if the "answer" response in "execute_command" mode is long and will continue in subsequent responses. false otherwise,
    "ongoing" : true if the response will continue in a different mode. false otherwise,
    "reason" : explanatory text for the response (insert here if needed)
}}
"""

def repair_test_llm(repair_target, ctx): 

    process_type = repair_target 
    output_max = ctx.llm_interface.output_max
    function_branch_path = f"{ctx.paths.database_dir}/cov_candidate.json"
    execute_path = f"{ctx.paths.work_dir}/execute.sh"
    def_start_line = ctx.entry.target_line         
    pure_cmd = get_pure_cmd(ctx.target_cmd)

    initial_error = None
    initial_std_out = None
    select_flag = None
    is_covered = None
    diff = None
    is_increased = None
    current_coverage = None
    path_count = None
    min_length = None
    max_length = None
    original_run_test_path = None
    explore_count = 0 

    delete_file(ctx.paths.run_test_path)
    create_permissioned_file(ctx.paths.run_test_path)

    execute_dir = os.path.dirname(os.path.normpath(execute_path))
    create_permissioned_file(execute_path)


    if not (ctx.WO_READ):
        mode_statement = "Only one mode out of three" #"Only one mode from three modes" # "Only one mode out of three"
    elif ctx.WO_READ:
        mode_statement = "modify_data mode"


    ref_files = []
    dep_data = read_json(ctx.paths.dep_json_path)

    if repair_count is None:
        repair_count = 1 # one round for convert_llm

    modified_file_list = []

    mode = None
    execute_error = None
    execute_out = None
    read_prompt = None
    version_count = 0
    error = True
    std_out = ""
    ongoing_flag = None # False
    mode = None
    elapsed_time = None
    testcase_num = max_num_test
    timestamp = None

    llm_start_time = time.time()
    write_time(ctx.paths.time_path, "llm", "start", repair_target, llm_start_time)

    #global previous_coverage
    branch_coverage, line_coverage, function_coverage = get_coverage(
        ctx.cov_target, ctx.paths.target_dir, ctx.paths.database_dir, 
        ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, 
        ctx.paths.is_program_path, ctx.paths.current_cov_path
    )
    
    if cov_target == "function":
        initial_coverage = function_coverage
        target_statement = "target function"
    
    elif cov_target == "branch":
        initial_coverage = branch_coverage
        target_statement = "target line"

    current_coverage = initial_coverage

    while (1):
        llm_end_time = time.time()
        elapsed_time = llm_end_time - llm_start_time

        if version_count > fixed_version_count:
            break

        if mode != "read_data":
            if (repair_count != 1 and repair_target == "explore_path"):
                # Update current_coverage
                error, std_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp, original_run_test_path = run_cov_script(
                    process_type, cov_target, ctx.paths.run_test_path, entry, branch_path, line_path, function_path, 
                    ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir, 
                    current_coverage, function_branch_path, is_program_path, current_cov_path
                )
                
                if ctx.WO_VALIDATION is True:
                    break

                version_count += 1
                print(f"\nJudge at {entry}: {is_increased}")

                save_coverage_report(
                    ctx.cov_target, ctx.paths.cov_report_path, ctx.paths.token_path, current_coverage, line_coverage, function_coverage, "llm"
                )

                if is_covered is True:
                    break

        if repair_target == "explore_path":
            if error is None and mode != "read_data" and ongoing_flag is False:
                if is_covered is True: 
                    break 

        elif repair_target == "no_target":
            if repair_count > 1:
                break
            
        elif error is None and mode != "read_data" and ongoing_flag is False:
            if repair_target == "explore_path":
                if is_covered is True: 
                    break           
            else:
                break

        if repair_target == "explore_path":
            target_path = entry['target_path']

            if repair_count == 1:
                prompt = []
                if cov_target == "branch":
                    prompt.extend([f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute test cases for the {pure_cmd} command that will cover the specified branch '{ctx.entry.target_branch}' on line {ctx.entry.target_line} in the {ctx.entry.target_function} function of the {ctx.entry.target_path} file.",
                                f"When answering, please follow the answering rules and choose {mode_statement} to generate your response.",
                                ])
                elif cov_target == "function":
                    prompt.extend([f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute test cases for the {pure_cmd} command that will reach the {ctx.entry.target_function} function of the {ctx.entry.target_path} file (Line {ctx.entry.target_line}).",
                                f"Also, write multiple command invocations to execute as many lines as possible within the target function. For conditional branches, try to explore as many different paths as possible.",
                                f"When answering, please follow the answering rules and choose {mode_statement} to generate your response.",
                                ])

                
                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                if not ctx.WO_PATH:
                    prompt.extend(["", "## Response rules:",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                        f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                        f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        f"- Please set as many options as possible in a single command to explore more execution paths.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        #f"- Please also include commands to create input files within the shell script.",
                        #f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                        #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                        "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])
                
                else:
                    prompt.extend(["", "## Response rules:",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                        f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                        f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        #f"- Please set as many options as possible in a single command to explore more execution paths.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        #f"- Please also include commands to create input files within the shell script.",
                        #f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                        #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                        "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])

                prompt.extend(ctx.notes)
                
            else:
                if not (ctx.GDB_OPTION and explore_count > 3):
                    if cov_target == "branch":
                        prompt = [f"With the current code, we have not yet been able to pass through the specified branch. ",
                                f"Please write a shell script code in modify_data mode to {ctx.paths.run_test_path} that will execute a program to pass through the specified branch {ctx.entry.target_path} file's {ctx.entry.target_function} function's line {ctx.entry.target_line} branch {ctx.entry.target_branch}",
                                f"Please follow the instructions below and select {mode_statement} to generate your response."
                                ]
                        prompt.extend(["", "## Response rules:", #"- Test cases refer to the inputs of the entry point function.",
                                    f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                                    f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                                    f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                                    f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                                    f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                                    "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                                    "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                                    #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                                    f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                                    ])
                        prompt.extend(ctx.notes)

                    elif cov_target == "function":
                        prompt = [f"With the current code, we have not yet been able to reach the target function. ",
                                f"Please write a shell script code in modify_data mode to {ctx.paths.run_test_path} that will execute a program to reach the {ctx.entry.target_path} file's {ctx.entry.target_function} function (Line {def_start_line}).",
                                f"Also, write multiple command invocations to execute as many lines as possible within the target function. For conditional branches, try to explore as many different paths as possible.",
                                f"Please follow the instructions below and select {mode_statement} to generate your response."
                                ]
                        prompt.extend(["", "## Response rules:", #"- Test cases refer to the inputs of the entry point function.",
                                    f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                                    f"- Consider methods to execute the specified function by manipulating the arguments of the main function (command line arguments).",
                                    f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                                    f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                                    f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                                    f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                                    "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                                    "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                                    #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                                    f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                                    ])
                        prompt.extend(ctx.notes)
                    
                else:
                    if cov_target == "branch":
                        prompt = [f"With the current code, we still haven't been able to pass through the specified branch.", #"Please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute the program that will pass through the specified branch (line number {ctx.entry.target_line} in {ctx.entry.target_function} of {ctx.entry.target_path} file).",
                                f"To generate code that passes through the specified branch '{ctx.entry.target_branch}' on line {ctx.entry.target_line} in the {ctx.entry.target_function} function of the {ctx.entry.target_path} file, first select the \"gdb_execute\" mode from the following four modes to check which path the most recently generated testcase is passing through.",
                                #"Please follow the response rules below and answer."
                                ]
                    elif cov_target == "function":
                        prompt = [f"With the current code, we still haven't been able to reach the target function.", #"Please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute the program that will pass through the specified branch (line number {ctx.entry.target_line} in {ctx.entry.target_function} of {ctx.entry.target_path} file).",
                                f"To generate code that reaches the {ctx.entry.target_function} function of the {ctx.entry.target_path} file, first select the \"gdb_execute\" mode from the following four modes to check which path the most recently generated testcase is passing through.",
                                #"Please follow the response rules below and answer."
                                ]

                    explore_count = 0


        if execute_error is not None or execute_out is not None:
            prompt.extend(["", "- The results of execution in execute_command mode are as follows."])

            if execute_out is not None:
                execute_out = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/execute_out.txt", execute_out, 10000)
                prompt.extend(["## Execution Result:", f"{execute_out}"]) 

            if execute_error is not None:
                prompt.extend(["", "## Execution Result Error: ", f"{execute_error}"])

            execute_error = None 
            execute_out = None
        
        if read_prompt is not None:
            prompt.extend(["", "## Response to the previous request:"]) 
            prompt.extend(read_prompt)
            read_prompt = None 

        if initial_error is not None:
            prompt.extend(["", "## Error when executing the current (pre-modification) testcase shell code:"])
            prompt.extend([f"{initial_error}"])
            initial_error = None 

        if initial_std_out is not None:
            prompt.extend(["", "## Standard output when executing the current (pre-modification) testcase shell code:"])
            prompt.extend([f"{initial_std_out}"])
            initial_std_out = None 

        print(f"ongoing_flag is {ongoing_flag}")
        if ongoing_flag is False or ongoing_flag is None:
            if repair_target == "explore_path":
                if not (ctx.GDB_OPTION or ctx.WO_READ):
                    prompt.extend(["",
                                "## Response Modes:",
                                "1. In 'read_data' mode:",
                                "## Purpose:",
                                "- Returns the contents of the specified filename as is.",
                                "## How to Answer:",
                                "- Please put the file path you want to know about in the \"target_files\" field of the JSON format data.",
                                "- If the file you want to know about has many lines and cannot be viewed due to context window limitations, you can specify \"start_line\" and \"end_line\" in addition to file_path in the \"file_slices\" to see between those specific line numbers.",
                                #f"- The shell script code you answer will be saved to the shell script file at {execute_path} and is assumed to be executed in the directory containing {execute_path}.",
                                #"- If you want to know about multiple files, please include multiple commands in a single shell script code in your answer.",
                                #f"- The shell script can contain multiple commands.",
                                #"- For example, if your code includes cat /path/to/test.c, you will be able to know the information of /path/to/test.c as it will be sent back to you in the next request prompt.",
                                "",
                                "2. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                                "3. In 'execute_command' mode:",
                                "## Purpose:",
                                "- You can execute the shell script code you answered.",
                                "## How to Answer:",
                                #f"- This executes separately from {ctx.paths.run_test_path}. If you don't need anything other than {ctx.paths.run_test_path}, you don't have to answer.", # {ctx.paths.run_test_path} or
                                "- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                f"- The shell script code you answer will be saved to the shell script file at {execute_path} and executed in the {execute_dir} directory.",
                                f"- Please design ./execute.sh to not take any arguments when executed.",
                                f"- The shell script can contain multiple commands.",
                    ])

                elif ctx.WO_READ:

                    prompt.extend(["",
                                    "## Response Modes:",
                                    "1. In 'modify_data' mode:",
                                    "## Purpose:",
                                    "- You can modify the specified file path.",
                                    "## How to Answer:",
                                    f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                    "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                    "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                    "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                    "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                    "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                    "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                    "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                        ])

            else:
                if not ctx.WO_READ:
                    prompt.extend([#"Please choose only one of the following three modes to generate your response.", #Your answer should choose only one mode.",
                                "",
                                "## Response Modes:",
                                "1. In 'read_data' mode:",
                                "## Purpose:",
                                #"- The execution results of the shell script code you answer will be sent back to you, so you can know them.", #(cat, less, tree etc...)
                                "- Returns the contents of the specified filename as is.",
                                "## How to Answer:",
                                #"- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                "- Please put the file path you want to know about in the \"target_files\" field of the JSON format data.",
                                "- If the file you want to know about has many lines and cannot be viewed due to context window limitations, you can specify \"start_line\" and \"end_line\" in addition to file_path in the \"file_slices\" to see between those specific line numbers.",
                                #f"- The shell script code you answer will be saved to the shell script file at {execute_path} and is assumed to be executed in the directory containing {execute_path}.",
                                #"- If you want to know about multiple files, please include multiple commands in a single shell script code in your answer.",
                                #f"- The shell script can contain multiple commands.",
                                #"- For example, if your code includes cat /path/to/test.c, you will be able to know the information of /path/to/test.c as it will be sent back to you in the next request prompt.",
                                "",
                                "2. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                                "3. In 'execute_command' mode:",
                                "## Purpose:",
                                "- You can execute the shell script code you answered.",
                                "## How to Answer:",
                                #f"- This executes separately from {ctx.paths.run_test_path} and {ctx.paths.run_test_path}. If you don't need anything other than {ctx.paths.run_test_path} or {ctx.paths.run_test_path}, you don't have to answer.",
                                "- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                f"- The shell script code you answer will be saved to the shell script file at {execute_path} and executed in the {execute_dir} directory.",
                                f"- Please design ./execute.sh to not take any arguments when executed.",
                                f"- The shell script can contain multiple commands.",
                     ])
                

                    prompt.extend(["",
                                    "",
                                    "## Other Notes:", #f"Please choose only one mode for your answer.",
                                    #"- If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                                    #"- If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                                    "- For the same error, please do not propose solution methods that have already been tried once, but suggest other solution methods.",
                                    #f"{platform_instruction}",
                                    #"- Writing to newly created files is done with 'execute_command', but in that case, please do not abbreviate the code to be written.",
                                    f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                                    #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing_in_mode' key.",
                                      "- If the JSON data to be included in a single mode response is likely to exceed the token limit, please answer in multiple parts.",
                                    "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing_in_mode' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key.",
                                    "- Always create your response in a single mode ('read_data', 'modify_data', 'execute_command') and only use 'ongoing_in_mode' when further exchanges are needed within that one mode.",
                                    "- When switching modes, please end your response by requesting a new request.",
                                    "- The content of modified_data you answer in 'modify_data' mode will be copied and pasted as is, so please absolutely do not include any abbreviated sections.",
                    ])
                
                elif ctx.WO_READ:
                    prompt.extend([#"Please choose only one of the following three modes to generate your response.", #Your answer should choose only one mode.",
                                "",
                                "## Response Modes:",
                                "1. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                    ])
                
                    prompt.extend(["",
                                    "",
                                    "## Other Notes:", #f"Please choose only one mode for your answer.",
                                    #"- If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                                    #"- If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                                    "- For the same error, please do not propose solution methods that have already been tried once, but suggest other solution methods.",
                                    #f"{platform_instruction}",
                                    #"- Writing to newly created files is done with 'execute_command', but in that case, please do not abbreviate the code to be written.",
                                    f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                                    #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing_in_mode' key.",
                                      "- If the JSON data to be included in a single mode response is likely to exceed the token limit, please answer in multiple parts.",
                                    "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing_in_mode' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key.",
                                    "- Always create your response in a single mode ('modify_data') and only use 'ongoing_in_mode' when further exchanges are needed within that one mode.",
                                    #"- When switching modes, please end your response by requesting a new request.",
                                    "- The content of modified_data you answer in 'modify_data' mode will be copied and pasted as is, so please absolutely do not include any abbreviated sections.",
                    ])
    
            prompt.extend(["- In summary, please respond in the following JSON format:"]) 
            
            if repair_target == "explore_path":
                if not (ctx.GDB_OPTION or ctx.WO_READ):
                    prompt.extend([autonomous_template])
                elif ctx.WO_READ:
                    prompt.extend([read_template])

                
                if not ctx.WO_PATH and strategy != "wo_tool":
                    if MIN_LENGTH:
                        path_info, path_count, min_length, max_length = get_path_info(
                            ctx.paths.callee_main_path, entry, ctx.paths.function_branch_path
                        )
                    else:
                        path_info, path_count, min_length, max_length, covered_info = get_path_info_wide(
                            ctx.paths.callee_main_path, entry, ctx.paths.function_branch_path
                        )

                    path_info = "\n".join(path_info)
                    path_info = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/path_info.txt", path_info, 5000)
                    prompt.extend([""])  
                    prompt.extend([path_info])

                    covered_info = "\n".join(covered_info)
                    covered_info = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/covered_info.txt", covered_info, 6000)
                    prompt.extend([""])  
                    prompt.extend([covered_info])

            else:
                prompt.extend([autonomous_template])

            if repair_count != 1 and repair_target == "testcase":
                test_code = get_lined_code(test_path, ctx.paths.work_dir)

                ref_text = []
                for ref in ref_files: # ref_test_path
                    ref_text.append(f" - {test_path}") #ref_text.append(f" - {ref_base_path}")

                ref_text.append(f" - {test_path}")

                execute_code = get_lined_code(run_test_path, work_dir)

                prompt.extend([f"## {test_path} code:", test_code]) 
                prompt.extend([f"## Shell script for compiling and executing {test_path} (stored in the path {ctx.paths.run_test_path}):", execute_code])


            if error is not None and error is not True:
                prompt.extend(["", f"## Execution result error of {ctx.paths.run_test_path}:", f"{error}"]) # error])
                error = None

            if std_out is not None and std_out is not True:
                std_out = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/std_out.txt", std_out, 10000)
                prompt.extend(["", f"## Execution Result of {ctx.paths.run_test_path}:", f"{std_out}"]) #, std_out]) #, std_out]) # std_out])
                std_out = None #std_out = ""

            prompt.extend(["", "## Directory Structure of the Target Program:"]) 
            directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir) # , test_id
            write_file(f"{database_dir}/directry_structure.txt", directory_structure)
            directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 6000) #10000)
            prompt.extend([directory_structure, ""])

        else:
            prompt.extend(["- In summary, please respond in the following JSON format:"]) 
            prompt.extend([autonomous_template])

            prompt.extend(["", "## Directory Structure of the Target Program:"]) 
            directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir) # , test_id
            write_file(f"{database_dir}/directry_structure.txt", directory_structure)
            directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 6000) #, 10000)

            prompt.extend([directory_structure, ""])
        

        if repair_target == "explore_path":
            target_code = get_lined_specific_code(ctx.paths.database_dir, target_path, ctx.entry.target_line, target_end_line)
            target_code = trim_code(target_path, target_code, 8000) #10000)
    
            if cov_target == "branch":
                prompt.extend(["", f"## Branch to be covered (branch {ctx.entry.target_branch} on line {ctx.entry.target_line} in {ctx.entry.target_function} of {ctx.entry.target_path} file):"])
            elif cov_target == "function":
                prompt.extend(["", f"## Target function ({ctx.entry.target_function} of {ctx.entry.target_path} file (Line {ctx.entry.target_line})):"])

            prompt.extend([target_code])


        prompt = adjust_prompt(prompt)
        delete_file(execute_path)
        create_permissioned_file(execute_path)
        rsp_json = ask_llm(prompt, "continue", ctx.llm_interface)

        ongoing_in_mode_flag = False

        sum_target_list = []
        sum_modified_list = []
        sum_deleted_list = []

        sum_slice_list = []
        mode = None

        while (1):
            prompt = []
            execute_error = None

            if 'ongoing' in rsp_json:
                ongoing_flag = rsp_json['ongoing']

            if 'ongoing_in_mode' in rsp_json:
                ongoing_in_mode_flag = rsp_json['ongoing_in_mode']

            print(f"ongoing_flag at location 1 is {ongoing_flag}")
            print(f"ongoing_in_mode_flag at location 1 is {ongoing_in_mode_flag}")

            if 'mode' in rsp_json:
                mode = rsp_json['mode']

                if mode == 'read_data':
                    if 'answer' in rsp_json:
                        code = rsp_json['answer']
                        append_file(execute_path, code)

                    if 'target_files' in rsp_json:
                        target_list = rsp_json['target_files']
                        if not isinstance(target_list, list):
                            target_list = [target_list]
                        sum_target_list.extend(target_list)
                    
                    if 'file_slices' in rsp_json and rsp_json['file_slices'] is not None:
                        slice_list = rsp_json['file_slices']
                        if not isinstance(slice_list, list):
                            slice_list = [slice_list]
                        sum_slice_list.extend(slice_list)


                if mode == 'modify_data':
                    if 'answer' in rsp_json:
                        modified_list = rsp_json['answer'] 
                        if not isinstance(modified_list, list):
                            modified_list = [modified_list]
                        sum_modified_list.extend(modified_list)
                
                if mode == 'delete_data':
                    if 'answer' in rsp_json:
                        deleted_list = rsp_json['answer'] 
                        if not isinstance(deleted_list, list):
                            deleted_list = [deleted_list]
                        sum_deleted_list.extend(deleted_list)

                if mode == 'execute_command':
                    if 'answer' in rsp_json:
                        code = rsp_json['answer']
                        append_file(execute_path, code)

            if ongoing_in_mode_flag is False:
                break

            if 'testcase_num' in rsp_json:
                testcase_num = rsp_json['testcase_num']

            print("Keep going to receive Rust code in modifying.")
            if repair_target == "explore_path":
                if cov_target == "branch":
                    prompt = [f"Please continue your answer for the code that passes through the specified branch."]
                elif cov_target == "function":
                    prompt = [f"Please continue your answer for the code that passes through the specified function."]

            prompt.extend(["", "## Response rules:",
                        #"If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                        #"If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                          "- The modified code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])
                
            rsp_json = ask_llm(prompt, "continue", llm_interface)

        print(f"Running program for the mode: {mode}")
        if mode == 'modify_data':
            print(f"In mode: {mode}")
            reflect_line_modification(sum_modified_list, work_dir, database_dir)
        
        elif mode == 'delete_data':
            print(f"In mode: {mode}")
            reflect_line_deletion(sum_deleted_list, work_dir, database_dir)


        elif mode == 'read_data':
            print(f"In mode: {mode}")
            #output = run_read_script(execute_path, 10, True, None, "both")
            read_prompt = ["- The content obtained in read_data mode is as follows.", ""] 

            slice_set = set()
            for slice_item in sum_slice_list:
                slice_set.add(slice_item['file_path'])

            new_sum_target_list = []
            print(f"sum_target_list: {sum_target_list}")
            for see_path in sum_target_list:
                if see_path not in slice_set:
                    new_sum_target_list.append(see_path)
            sum_target_list = new_sum_target_list

            sum_target_list = list(set(sum_target_list))

            tmp_sum_target_list = []
            for see_path in sum_target_list:
                if not os.path.exists(see_path):
                    see_path = find_matching_path(ctx.paths.work_dir, see_path)
                tmp_sum_target_list.append(see_path)
            sum_target_list = tmp_sum_target_list

            for see_path in sum_target_list:
                is_excluded = check_excluded(see_path, ctx.paths.work_dir)
                if is_excluded:
                    continue

                file_code = get_lined_code(see_path, ctx.paths.work_dir)
                file_code = trim_code(see_path, file_code, 10000)

                read_prompt.extend([f"Content of the file {see_path}:"]) 
                if not is_empty_string(file_code):
                    read_prompt.extend([f'{file_code}\n'])
                else:
                    read_prompt.extend([f'None\n'])
            
            for see_item in sum_slice_list:
                is_excluded = check_excluded(see_item['file_path'], ctx.paths.work_dir)
                if is_excluded:
                    continue

                file_code = get_lined_specific_code(ctx.paths.database_dir, see_item['file_path'], see_item['start_line'], see_item['end_line'])
                file_code = trim_code(see_item['file_path'], file_code, 10000)

                read_prompt.extend([f"Content of {see_item['start_line']} - {see_item['end_line']} lines in the file {see_item['file_path']}:"])
                read_prompt.extend([f'{file_code}\n'])

        
        elif mode == 'execute_command':
            print(f"In mode: {mode}")
            if repair_target == "explore_path":
                execute_error, execute_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp, original_run_test_path = run_cov_script(
                    process_type, ctx.cov_target, ctx.paths.run_test_path, ctx.entry, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, 
                    ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir, 
                    initial_coverage, ctx.paths.function_branch_path, ctx.paths.is_program_path, ctx.paths.current_cov_path
                )
            
            else:
                execute_error, execute_out, repair_count = run_script(
                    execute_path, 10, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, mode
                )
                execute_out = run_script_pty(ctx.paths.run_test_path)

        repair_count += 1

    llm_end_time = time.time()
    write_time(ctx.paths.time_path, "llm", "end", repair_target, llm_end_time)

    is_full_branch_covered = False
    ans_entry = {
        "repair_count" : repair_count,
        "version_count" : version_count, 
        "is_covered" : is_covered,
        "is_full_branch_covered" : is_full_branch_covered,
        "elapsed_time" : elapsed_time,
        "diff" : diff,
        "timestamp" : timestamp,
        "path_count" : path_count,
        "min_length" : min_length,
        "max_length" : max_length,
        "original_run_test_path" : original_run_test_path,
    }

    if repair_target == "explore_path": # is True:  #if select_flag is True:
        if original_run_test_path is None:
            timestamp = get_timestamp()
            original_run_test_path = write_testcase(ctx.paths.run_test_path, ctx.paths.snap_dir, timestamp)
            
        if is_covered is True:
            is_full_branch_covered = get_branch_covered(
                ctx.entry.target_path, ctx.entry.target_function, ctx.entry.target_line, ctx.entry.target_end_line
            )
            ans_entry['is_full_branch_covered'] = is_full_branch_covered

        return ans_entry 

    elif repair_target == "no_target":
        return ans_entry
    

def repair_test_agent(repair_target, interface):
    """ask_agent version of repair_test.

    The agent writes run_test_path (a shell script); coverage measurement
    (run_cov_script) is still done by the orchestrator, as before. The old
    read_data/modify_data/execute_command mode dispatch and the
    ongoing / ongoing_in_mode control flow are removed, since the Agent SDK
    absorbs them internally. Prompt text is kept as in the original; only the
    mode descriptions, the JSON response template, and the ongoing/output_max
    lines are dropped.
    """

    process_type         = repair_target

    function_branch_path = f"{ctx.paths.database_dir}/cov_candidate.json"
    is_covered = None
    diff = None
    is_increased = None
    current_coverage = None
    path_count = None
    min_length = None
    max_length = None
    original_run_test_path = None
    timestamp = None
    elapsed_time = None

    execute_path = interface['execute_path']
    execute_dir = os.path.dirname(os.path.normpath(execute_path))
    create_permissioned_file(execute_path)

    dep_data = read_json(dep_json_path)
    if repair_count is None:
        repair_count = 1

    version_count = 0
    error = None
    std_out = None

    # --- Agent execution environment: inspect target source + author the shell
    #     script only. Building / recompiling / coverage measurement are not done
    #     by the agent; measurement is done by the orchestrator. ---
    agent.allowed_tools = ["Read", "Grep", "Glob", "Write", "Edit"]
    agent.add_dirs = list({
        os.path.dirname(os.path.normpath(ctx.paths.run_test_path)),
        ctx.paths.target_dir, ctx.original_target_dir, ctx.paths.database_dir, ctx.paths.work_dir,
    })
    if agent.session_path:
        delete_file(agent.session_path)

    llm_start_time = time.time()
    write_time(ctx.paths.time_path, "llm", "start", repair_target, llm_start_time)

    branch_coverage, line_coverage, function_coverage = get_coverage(
        ctx.cov_target, ctx.paths.target_dir, ctx.paths.database_dir, 
        ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path,
        ctx.paths.is_program_path, ctx.paths.current_cov_path
    )

    if cov_target == "function":
        initial_coverage = function_coverage
        target_statement = "target function"
    elif cov_target == "branch":
        initial_coverage = branch_coverage
        target_statement = "target line"

    current_coverage = initial_coverage

    while (1):
        llm_end_time = time.time()
        elapsed_time = llm_end_time - llm_start_time

        if version_count > fixed_version_count:
            break

        # measure the coverage of the run_test_path the agent wrote last iteration
        if (repair_count != 1 and repair_target == "explore_path"):
            error, std_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp, original_run_test_path = run_cov_script(
                process_type, cov_target, ctx.paths.run_test_path, ctx.entry, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path,
                ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir,
                current_coverage, function_branch_path, is_program_path, current_cov_path
            )

            if ctx.WO_VALIDATION is True:
                break

            version_count += 1
            print(f"\nJudge at {ctx.entry}: {is_increased}")

            save_coverage_report(
                ctx.cov_target, ctx.paths.cov_report_path, ctx.paths.token_path, current_coverage, line_coverage, function_coverage, "llm"
            )

            if is_covered is True:
                break

        if repair_target == "no_target":
            if repair_count > 1:
                break

        if repair_target == "explore_path":
            if repair_count == 1:
                prompt = []
                if cov_target == "branch":
                    prompt.extend([f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} to execute test cases for the {pure_cmd} command that will cover the specified branch '{ctx.entry.target_branch}' on line {ctx.entry.target_line} in the {ctx.entry.target_function} function of the {ctx.entry.target_path} file.",
                                ])
                elif cov_target == "function":
                    prompt.extend([f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} to execute test cases for the {pure_cmd} command that will reach the {ctx.entry.target_function} function of the {ctx.entry.target_path} file (Line {ctx.entry.target_line}).",
                                f"Also, write multiple command invocations to execute as many lines as possible within the target function. For conditional branches, try to explore as many different paths as possible.",
                                ])

                tool_cmd = get_tool_cmd(strategy, tool_string)
                if not ctx.WO_PATH:
                    prompt.extend(["", "## Response rules:",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                        f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        f"- Please set as many options as possible in a single command to explore more execution paths.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                        "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections.",
                        ])

                else:
                    prompt.extend(["", "## Response rules:",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                        f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                        "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections.",
                        ])

                prompt.extend(ctx.notes)

            else:
                if cov_target == "branch":
                    prompt = [f"With the current code, we have not yet been able to pass through the specified branch. ",
                            f"Please write a shell script code to {ctx.paths.run_test_path} that will execute a program to pass through the specified branch {ctx.entry.target_path} file's {ctx.entry.target_function} function's line {ctx.entry.target_line} branch {ctx.entry.target_branch}",
                            ]
                    prompt.extend(["", "## Response rules:",
                                f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                                f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                                f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                                f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                                f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                                "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                                "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                                f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                                ])
                    prompt.extend(ctx.notes)

                elif cov_target == "function":
                    prompt = [f"With the current code, we have not yet been able to reach the target function. ",
                            f"Please write a shell script code to {ctx.paths.run_test_path} that will execute a program to reach the {ctx.entry.target_path} file's {ctx.entry.target_function} function (Line {def_start_line}).",
                            f"Also, write multiple command invocations to execute as many lines as possible within the target function. For conditional branches, try to explore as many different paths as possible.",
                            ]
                    prompt.extend(["", "## Response rules:",
                                f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                                f"- Consider methods to execute the specified function by manipulating the arguments of the main function (command line arguments).",
                                f"- The {pure_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                                f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                                f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                                f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                                "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                                "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                                f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                                ])
                    prompt.extend(ctx.notes)

        # feedback of the previous execution result (mirrors the original error / std_out injection)
        if error is not None and error is not True:
            prompt.extend(["", f"## Execution result error of {ctx.paths.run_test_path}:", f"{error}"])
            error = None

        if std_out is not None and std_out is not True:
            std_out = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/std_out.txt", std_out, 10000)
            prompt.extend(["", f"## Execution Result of {ctx.paths.run_test_path}:", f"{std_out}"])
            std_out = None

        # path_info / covered_info (from the original)
        if repair_target == "explore_path":
            if not ctx.WO_PATH and strategy != "wo_tool":
                if MIN_LENGTH:
                    path_info, path_count, min_length, max_length = get_path_info(
                        ctx.paths.callee_main_path, ctx.entry, function_branch_path
                    )
                else:
                    path_info, path_count, min_length, max_length, covered_info = get_path_info_wide(
                        ctx.paths.callee_main_path, ctx.entry, function_branch_path
                    )

                path_info = "\n".join(path_info)
                path_info = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/path_info.txt", path_info, 5000)
                prompt.extend([""])
                prompt.extend([path_info])

                if not MIN_LENGTH:
                    covered_info = "\n".join(covered_info)
                    covered_info = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/covered_info.txt", covered_info, 6000)
                    prompt.extend([""])
                    prompt.extend([covered_info])

        prompt.extend(["", "## Directory Structure of the Target Program:"])
        directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir)
        write_file(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure)
        directory_structure = trim_code(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure, 6000)
        prompt.extend([directory_structure, ""])

        if repair_target == "explore_path":
            target_code = get_lined_specific_code(ctx.paths.database_dir, ctx.entry.target_path, ctx.entry.target_line, ctx.entry.target_end_line)
            target_code = trim_code(ctx.entry.target_path, target_code, 8000)

            if cov_target == "branch":
                prompt.extend(["", f"## Branch to be covered (branch {ctx.entry.target_branch} on line {ctx.entry.target_line} in {ctx.entry.target_function} of {ctx.entry.target_path} file):"])
            elif cov_target == "function":
                prompt.extend(["", f"## Target function ({ctx.entry.target_function} of {ctx.entry.target_path} file (Line {ctx.entry.target_line})):"])

            prompt.extend([target_code])

        prompt = adjust_prompt(prompt)

        # agent run (replaces ask_llm(prompt, "continue", llm_interface))
        result = ask_agent(prompt, "continue", ctx.agent)
        if result.is_error:
            print(f"[agent] run reported error (turns={result.num_turns})")

        repair_count += 1

    llm_end_time = time.time()
    write_time(ctx.paths.time_path, "llm", "end", repair_target, llm_end_time)

    is_full_branch_covered = False
    ans_entry = {
        "repair_count" : repair_count,
        "version_count" : version_count,
        "is_covered" : is_covered,
        "is_full_branch_covered" : is_full_branch_covered,
        "elapsed_time" : elapsed_time,
        "diff" : diff,
        "timestamp" : timestamp,
        "path_count" : path_count,
        "min_length" : min_length,
        "max_length" : max_length,
        "original_run_test_path" : original_run_test_path,
    }

    if repair_target == "explore_path":
        if original_run_test_path is None:
            timestamp = get_timestamp()
            original_run_test_path = write_testcase(run_test_path, snap_dir, timestamp)
            ans_entry['original_run_test_path'] = original_run_test_path

        if is_covered is True:
            is_full_branch_covered = get_branch_covered(
                ctx.entry.target_path, ctx.entry.target_function, ctx.entry.target_line, ctx.entry.target_end_line
            )
            ans_entry['is_full_branch_covered'] = is_full_branch_covered

        return ans_entry

    elif repair_target == "no_target":
        return ans_entry


def sort_by_centrality(data, graph_metrics, fixed_metric):
    for key, item in data.items():
        item["metrics"] = get_metrics(item, graph_metrics)

    # Sort by the specified centrality metric
    sort_by = "closeness_centrality"

    if fixed_metric is not None:
        sort_by = fixed_metric
    
    # Create a list of keys and sort by the corresponding value's metric
    if sort_by == "pagerank":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["pagerank"], reverse=True)
    elif sort_by == "degree_centrality":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["degree_centrality"], reverse=True)
    elif sort_by == "betweenness_centrality":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["betweenness_centrality"], reverse=True)
    elif sort_by == "closeness_centrality":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["closeness_centrality"], reverse=True)
    elif sort_by == "eigenvector_centrality":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["eigenvector_centrality"], reverse=True)
    elif sort_by == "katz_centrality":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["katz_centrality"], reverse=True)
    elif sort_by == "combined_score":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["combined_score"], reverse=True)
    elif sort_by == "in_degree":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["in_degree"], reverse=True)
    elif sort_by == "out_degree":
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["out_degree"], reverse=True)
    else:
        # Default to sorting by pagerank
        sorted_keys = sorted(data.keys(), key=lambda k: data[k]["metrics"]["pagerank"], reverse=True)
    
    # Create a new ordered dictionary using the sorted keys
    sorted_data = {k: data[k] for k in sorted_keys}
    
    return sorted_data


def get_pure_target(
    strategy, target_cmd, target_dir, meta_dir, database_dir, work_dir, targeted_set,
    is_program_path, callee_path, callee_main_path, graph_metrics, fixed_metric, WO_PATH
):

    ####################################################
    ### Prepare priority data
    ####################################################
    
    data = read_json(callee_path)
    related_ids = get_related_data(callee_main_path)
    # data is in dictionary form, so treat the key-value pairs as items
    # then filter out items whose key is not in targeted_set
    #available_items = [(key, value) for key, value in data.items() if key not in targeted_set]

    new_data = {} 
    meta_paths = []
    explored = set()

    select_data = read_json(f"rq1/cov_select_{target_cmd}.json")
    if select_data is not None:
        for item in select_data:
            #if item['is_covered'] is True:
            key = f"{item['name']}@{item['file_path']}:{item['line_number']}"
            explored.add(key)

    for key, item in data.items():
        if key not in related_ids:
            continue
        
        if item['name'].startswith('__builtin_va'):
            continue
        item['def_file_path'] = item['file_path']
        meta_path = get_metadata(item['file_path'], meta_dir, True)
        if strategy == "random_t" or strategy == "wo_tool" or WO_PATH is True:  # METRIC is True
            if (os.path.exists(meta_path)):
                new_data[key] = item

        else:
            if (os.path.exists(meta_path) and key not in explored):
                new_data[key] = item

    data = new_data
    # print("++++++++++++++++")
    # print(len(data))
    # print("++++++++++++++++")

    data = sort_by_centrality(data, graph_metrics, fixed_metric)
    write_json(f"{database_dir}/sorted.json", data)

    PURE_SORTED = True
    satisfied = True
    i = 0

    available_items = []
    for key, value in data.items():
        if key not in targeted_set:
            available_items.append((key, value))
    
    if not available_items:
        targeted_set = set()

    while(1):
        available_items = []
        for key, value in data.items():
            if key not in targeted_set:
                available_items.append((key, value))
                
        if not available_items:
            print("All items are already in targeted_set")
            sys.exit(1)
            return None
        
        # Randomly select one item (a key-value tuple)
        if PURE_SORTED:
            if i >= len(available_items):
                print("All items are already tested: i >= len(available_items)")
                sys.exit(1)
                return None

            key, item = available_items[i]
            i += 1

        else:
            key, item = random.choice(available_items)

        meta_path = get_metadata(item['file_path'], meta_dir, True)
        if not os.path.exists(meta_path):
            print(meta_path)
            print("------------")
            print(meta_paths)
            satisfied = False
            sys.exit(0)
        
        if satisfied and item['name'] != "main":
            break
            
    targeted_set.add(key)

    target_entry = {
        'target_path': item['file_path'],
        'target_line': item['def_start_line'],
        'target_end_line': item['def_end_line'],
        'target_function': item['name'],
        'target_uncovered_ratio': None,
        'target_branch': None,
        'flow_log_path': None,
        'explore_time': None,
    }
    
    return target_entry


def update_select(select_path, target_data):
    data = []
    if os.path.exists(select_path):
        data = read_json(select_path)
    
    data.append(target_data)
    write_json(select_path, data)



def explore_path(
    paths, llm_interface, strategy, tool_string, max_num_test, cov_target, current_coverage, targeted_set, target_cmd, 
    original_target_dir, fixed_metric, fixed_version_count, fixed_explore_time, explore_fix,
    database_json, error, std_out, graph_metrics, G,
    WO_READ, WO_PATH, WO_VALIDATION, MIN_LENGTH, GDB_OPTION, testfile_counter
): 
    
    entry = {}
    if strategy != "wo_tool":
        if current_coverage == 0 or current_coverage is None:
            target_entry = get_pure_target(
                strategy, target_cmd, paths.target_dir, paths.meta_dir, paths.database_dir, paths.work_dir, targeted_set, 
                paths.is_program_path, paths.callee_path, paths.callee_main_path, graph_metrics, fixed_metric, WO_PATH
            ) 

        else:
            if cov_target == "function":
                target_entry = get_target_entry(
                    paths.target_dir, paths.is_program_path, paths.function_path, paths.priority_path, paths.callee_main_path
                ) 

            elif cov_target == "branch":
                target_entry = get_target_entry_branch(
                    paths.target_dir, paths.is_program_path, paths.branch_path, paths.priority_path
                )

        print(f"\nTarget is {target_entry}")

    else:
        target_entry = {
            'target_path' : None,
            'target_line' : None,
            'target_end_line' : None,
            'target_function' : None,
            'target_uncovered_ratio' : None,
            'target_branch' : None,
            'flow_log_path' : None,
            'explore_time' : None,
        }

    entry['target_path'] = target_entry['target_path']
    entry['target_line'] = target_entry['target_line']
    entry['target_end_line'] = target_entry['target_end_line']
    entry['target_function'] = target_entry['target_function']
    entry['target_uncovered_ratio'] = target_entry['target_uncovered_ratio']
    entry['target_branch'] = target_entry['target_branch']
    entry['flow_log_path'] = paths.flow_log_path

    target_path = target_entry['target_path']
    target_line = target_entry['target_line'] 
    target_end_line = target_entry['target_end_line']  
    target_function = target_entry['target_function'] 
    target_uncovered_ratio = target_entry['target_uncovered_ratio']
    target_branch = target_entry['target_branch']

    # setup for asking llm
    cmd_list = []
    cmd_exe = database_json[target_cmd]["cmd_exe"]
    notes = database_json[target_cmd]["notes"]

    if explore_fix == "t":
        explore_time = fixed_explore_time
    else:
        explore_time = target_entry['explore_time']

    repair_count = 1

    ctx = RepairContext(
        paths=paths,
        llm_interface=llm_interface,
        select=False,
        cov_target=cov_target,
        strategy=strategy,
        tool_string=tool_string,
        fixed_version_count=fixed_version_count,
        entry=entry,
        max_num_test=max_num_test,
        fixed_metric=fixed_metric,
        repair_count=repair_count,
        target_path=target_path,
        target_function=target_function,
        target_uncovered_ratio=target_uncovered_ratio,
        target_branch=target_branch,
        target_line=target_line,
        target_end_line=target_end_line,
        target_cmd=target_cmd,
        cmd_list=cmd_list,
        test_path=None,
        file_path=None,
        test_id=None,
        function_name=None,
        main_flag=None,
        explore_time=explore_time,
        cmd_exe=cmd_exe,
        notes=notes,
        testfile_counter=testfile_counter,
        WO_READ=WO_READ,
        WO_PATH=WO_PATH,
        WO_VALIDATION=WO_VALIDATION,
        MIN_LENGTH=MIN_LENGTH,
        GDB_OPTION=GDB_OPTION,
        # COUNT_PERIODIC=COUNT_PERIODIC,
    )

    if strategy != "wo_tool":
        if llm_interface.AGENT is False:
            ans_entry = repair_test_llm('explore_path', ctx)
        else:
            ans_entry = repair_test_agent('explore_path', ctx)

        repair_count = ans_entry['repair_count']
        version_count = ans_entry['version_count']
        is_covered = ans_entry['is_covered']
        elapsed_time = ans_entry['elapsed_time']
        diff = ans_entry['diff']
        timestamp = ans_entry['timestamp']
        path_count = ans_entry['path_count']
        min_length = ans_entry["min_length"]
        max_length = ans_entry["max_length"]

        is_increased = False
        if diff is not None and diff > 0:
            is_increased = True
        if diff is None:
            diff = 0

        target_data = {
            "file_path" : target_path,
            "line_number" : target_line,
            "name" : target_function,
            "repair_count" : repair_count,
            "version_count" : version_count,
            "elapsed_time" : elapsed_time, 
            "explore_time" : explore_time,
            "timestamp" : timestamp, 
            "path_count" : path_count,
            "min_length" : min_length,
            "max_length" : max_length,
            "is_covered" : is_covered,
            "is_increased" : is_increased,
            "diff" : diff,
        }

        update_select(paths.select_path, target_data)
        
    elif strategy == "wo_tool":
        if llm_interface.AGENT is False:
            ans_entry = repair_test('no_target', ctx)
        else:
            ans_entry = repair_test_agent('no_target', ctx)

        ans_entry['is_covered'] = None

    print(f"Current coverage: {current_coverage}")
    target_entry['is_covered'] = None
    target_entry['is_covered'] = ans_entry['is_covered']
    target_entry['is_full_branch_covered'] = ans_entry['is_full_branch_covered']
    target_entry['original_run_test_path'] = ans_entry['original_run_test_path']

    return current_coverage, target_entry


def get_annotated_source_code_range(target_file_path, start_line=None, end_line=None):
    """
    Generate annotated code from an lcov .info file
    """
    try:
        if not os.path.exists(target_file_path):
            return f"Error: File not found: {target_file_path}"
        
        # Run lcov to generate the .info file
        target_dir = os.path.dirname(target_file_path)
        
        cmd = ['lcov', '--capture', '--directory', target_dir, '--output-file', '-']
        
        result = subprocess.run(
            cmd,
            #capture_output=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=None #600
        )
        
        if result.returncode != 0:
            return f"lcov error: {result.stderr}"
        
        # Parse the .info file
        lines = result.stdout.split('\n')
        line_data = {}
        branch_data = {}
        function_data = {}
        current_file = None
        
        for line in lines:
            line = line.strip()
            
            # File information
            if line.startswith('SF:'):
                current_file = line[3:]
                
            elif current_file == target_file_path:
                # Line coverage: DA:line_number,execution_count
                if line.startswith('DA:'):
                    parts = line[3:].split(',')
                    line_num = int(parts[0])
                    count = int(parts[1])
                    line_data[line_num] = count
                
                # Function coverage: FN:line_number,function_name
                elif line.startswith('FN:'):
                    parts = line[3:].split(',', 1)
                    line_num = int(parts[0])
                    func_name = parts[1]
                    function_data[line_num] = func_name
                
                # Branch coverage: BRDA:line_number,block,branch,execution_count
                elif line.startswith('BRDA:'):
                    parts = line[5:].split(',')
                    line_num = int(parts[0])
                    count = 0 if parts[3] == '-' else int(parts[3])
                    if line_num not in branch_data:
                        branch_data[line_num] = []
                    branch_data[line_num].append(count)
        
        # Read the original source file
        with open(target_file_path, 'r', encoding='utf-8') as f:
            source_lines = f.readlines()
        
        # Generate annotated code
        annotated_lines = []
        
        # Add metadata header
        annotated_lines.append(f"        -:    0:Source:{os.path.basename(target_file_path)}")
        annotated_lines.append(f"        -:    0:Data:lcov-generated")
        
        for i, source_line in enumerate(source_lines, 1):
            # Line range check
            if start_line is not None and i < start_line:
                continue
            if end_line is not None and i > end_line:
                continue
                
            # Generate prefix based on coverage information
            if i in line_data:
                count = line_data[i]
                if count == 0:
                    prefix = f"    #####:{i:5}:"
                else:
                    prefix = f"{count:9}:{i:5}:"
            else:
                prefix = f"        -:{i:5}:"
            
            annotated_lines.append(f"{prefix}{source_line.rstrip()}")
            
            # Add function information
            if i in function_data:
                func_name = function_data[i]
                func_count = line_data.get(i, 0)
                annotated_lines.append(f"function {func_name} called {func_count} returned 100% blocks executed 100%")
            
            # Add branch information
            if i in branch_data:
                for j, branch_count in enumerate(branch_data[i]):
                    if branch_count > 0:
                        annotated_lines.append(f"branch  {j} taken 100%")
                    else:
                        annotated_lines.append(f"branch  {j} never executed")
        
        return '\n'.join(annotated_lines)
        
    except Exception as e:
        return f"Error: {str(e)}"


def repair_branch_llm(repair_target, interface):

    process_type = repair_target 
    function_branch_path = f"{database_dir}/cov_candidate.json"

    explore_time = None
    initial_error = None
    initial_std_out = None

    select_flag = None
    is_covered = None
    diff = None
    is_increased = None
    path_count = None
    min_length = None
    max_length = None

    def_start_line = ctx.entry.target_line 

    if not (ctx.WO_READ):
        mode_statement = "Only one mode out of three" #"Only one mode from three modes" # "Only one mode out of three"
    elif ctx.WO_READ:
        mode_statement = "modify_data mode"


    explore_count = 0
    execute_dir = os.path.dirname(os.path.normpath(execute_path))
    create_permissioned_file(execute_path)

    ref_files = []
    dep_data = read_json(ctx.paths.dep_json_path)

    if repair_count is None:
        repair_count = 1 

    modified_file_list = []
    mode = None
    execute_error = None
    execute_out = None
    read_prompt = None
    version_count = 0
    error = True
    std_out = ""
    ongoing_flag = None # False
    mode = None
    elapsed_time = None
    testcase_num = ctx.max_num_test
    timestamp = None

    llm_start_time = time.time()
    write_time(ctx.paths.time_path, "llm", "start", repair_target, llm_start_time)

    branch_coverage, line_coverage, function_coverage = get_coverage(
        ctx.cov_target, ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, 
        ctx.paths.is_program_path, ctx.paths.current_cov_path
    )
    
    global current_branch_coverage
    current_branch_coverage = branch_coverage
    initial_coverage = branch_coverage

    target_statement = "target line"

    while(1):
        llm_end_time = time.time()
        elapsed_time = llm_end_time - llm_start_time

        if version_count > fixed_version_count:
            break

        if mode != "read_data":
            if (ctx.repair_count != 1 and repair_target == "explore_path"):
                error, std_out, is_covered, is_increased, diff, current_branch_coverage, branch_coverage, line_coverage, function_coverage, timestamp = run_branch_cov_script(
                    process_type, ctx.paths.run_test_path, ctx.entry, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, ctx.paths.is_program_path,
                    ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir, 
                    current_branch_coverage, function_branch_path
                )
                version_count += 1

                print(f"\nJudge at {entry}: {is_increased}")
                save_coverage_report(
                    ctx.cov_target, ctx.paths.cov_report_path, ctx.paths.token_path, 
                    current_branch_coverage, line_coverage, function_coverage, "llm"
                ) 

                if is_increased is True:
                    break
            
            elif (ctx.repair_count != 1 and repair_target == "no_target"):
                error, std_out, ctx.repair_count = run_script(
                    ctx.paths.run_test_path, 10, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, mode
                )

        if repair_target == "explore_path":
            if error is None and mode != "read_data" and ongoing_flag is False:
                if is_covered is True: 
                    break 

        elif repair_target == "no_target":
            if repair_count > 1:
                break
            
        elif error is None and mode != "read_data" and ongoing_flag is False:
            if repair_target == "explore_path":
                if is_covered is True: 
                    break            
            else:
                break

        if ctx.WO_VALIDATION is True:
            break

        if repair_target == "explore_path":
            if repair_count == 1:
                prompt = []
                add_prompt = []

                prompt.extend([
                    f"The following commands in {original_run_test_path} are commands that reach the target {ctx.entry.target_function} function below. Please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute diverse commands using the {target_cmd} command that would improve branch coverage within that target function.",
                    f"When answering, please follow the answering rules and choose {mode_statement} to generate your response.",
                ]) 
                                
                tool_cmd = get_tool_cmd(strategy, tool_string)
                prompt.extend(["", "## Response rules:",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- Even if the program implements other commands, please write test cases only for the {target_cmd} command for now.",
                        f"- The {target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                        f"- Please do not include build execution (./{build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        f"- Please set as many options as possible in a single command to explore more execution paths.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        #f"- Please also include commands to create input files within the shell script. In that time, please always generate valid input files using standard tools appropriate for the file type because invalid files cause early rejection and prevent deep code coverage.",
                        # f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                        #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                        "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])

                prompt.extend(notes)

            else:
                #if explore_count > 3:
                #if cov_target == "branch":
                prompt = [f"With the current code, we have not yet been able to improve branch coverage of the target function.",
                        f"Please write a shell script code in modify_data mode to {ctx.paths.run_test_path} that will improve branch coverage of the target {ctx.entry.target_function} function.",
                        f"Please follow the instructions below and select {mode_statement} to generate your response."
                        ]
                prompt.extend(["", "## Response rules:", #"- Test cases refer to the inputs of the entry point function.",
                            f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                            f"- Even if the program implements other commands, please write test cases only for the {target_cmd} command for now.",
                            f"- The {ctx.target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                            f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                            f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                            "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                            "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                            #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                            f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                            ])
                prompt.extend(notes)                    
        
        elif repair_target == "no_target":
            if repair_count == 1:
                prompt = []
                prompt.extend([f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute test cases for the {pure_cmd} command in a way that maximizes code coverage.", #coverage.",
                               f"When answering, please follow the answering rules below and choose {mode_statement} to generate your response.",
                               ])
                
                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                prompt.extend(["", "## Response rules",
                        f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                        f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                        f"- The {ctx.target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                        f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                        f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                        #f"- To increase coverage more quickly, please include at least {max_num_test} calls to {target_cmd}.",
                        #f"- The current total number of covered functions is {current_coverage}.",
                        "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                        #"- --run_fuzz is used for fuzzing, but now it's for executing commands, so please don't include the --run_fuzz option when executing the program in the shell code.",
                        f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                        #f"- If modifying {ctx.paths.run_test_path} still cannot generate test cases that pass through the specified branch, please use gdb_execute mode once to confirm which functions the current test case is passing through, and generate shell code that accurately passes through the specified line.",
                        f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                        f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                        #f"- Please set as many options as possible in a single command to explore more execution paths.",
                        f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                        #f"- Please also include commands to create input files within the shell script.",
                        # f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                        f"{tool_cmd}",
                        f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                        f"- Please do not include commands that delete input files in the shell script.",
                        f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                        "- Since coverage information is being accumulated, please absolutely do not recompile the source code in the code generated in modify_data mode or in the shell code executed in execute_command mode.",
                        #"- Please do not include sudo commands that use root privileges. It is assumed that settings requiring sudo have already been made.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                          "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])      
                prompt.extend(notes) 

            else:
                print("Should not proceed this step")
                prompt = []
                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                prompt = [f"Please modify the test case {ctx.paths.run_test_path} to increase coverage for the program.",
                          f"- Please set as many options as possible in a single command to explore more execution paths.",
                          f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater. Also, please include the maximum counter value of the filenames used in your response in the \"max_counter\" root-level JSON key of a JSON file.",
                          #f"- Please also include commands to create input files within the shell script.",
                          # f"- Please include commands to create valid input files using appropriate standard tools: {ctx.tool_string}. Do not manually construct file headers or use placeholder data. Invalid files cause early rejection and low coverage.",
                          f"{tool_cmd}",
                          f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                          f"- Please do not include commands that delete input files in the shell script.",
                          f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                          #"Please write shell script code in {ctx.paths.run_test_path} using modify_data mode to execute the program that will pass through the specified branch (line number {ctx.entry.target_line} in {ctx.entry.target_function} of {ctx.entry.target_path} file).",
                        ]
                
        
        if execute_error is not None or execute_out is not None:
            prompt.extend(["", "- The results of execution in execute_command mode are as follows."])

            if execute_out is not None: 
                execute_out = trim_data(ctx.paths.work_dir, f"{ctx.paths.work_dir}/execute_out.txt", execute_out, 10000)
                prompt.extend(["## Execution Result:", f"{execute_out}"]) 

            if execute_error is not None:
                prompt.extend(["", "## Execution Result Error: ", f"{execute_error}"])

            execute_error = None 
            execute_out = None
        
        if read_prompt is not None:
            prompt.extend(["", "## Response to the previous request:"])
            prompt.extend(read_prompt)
            read_prompt = None 

        if initial_error is not None:
            prompt.extend(["", "## Error when executing the current (pre-modification) testcase shell code:"])
            prompt.extend([f"{initial_error}"])
            initial_error = None 

        if initial_std_out is not None:
            prompt.extend(["", "## Standard output when executing the current (pre-modification) testcase shell code:"])
            prompt.extend([f"{initial_std_out}"])
            initial_std_out = None 

        print(f"ongoing_flag is {ongoing_flag}")

        if ongoing_flag is False or ongoing_flag is None:
            if repair_target == "explore_path":
                if not (ctx.GDB_OPTION or ctx.WO_READ):
                    prompt.extend(["",
                                "## Response Modes:",
                                "1. In 'read_data' mode:",
                                "## Purpose:",
                                "- Returns the contents of the specified filename as is.",
                                "## How to Answer:",
                                "- Please put the file path you want to know about in the \"target_files\" field of the JSON format data.",
                                "- If the file you want to know about has many lines and cannot be viewed due to context window limitations, you can specify \"start_line\" and \"end_line\" in addition to file_path in the \"file_slices\" to see between those specific line numbers.",
                                #f"- The shell script code you answer will be saved to the shell script file at {execute_path} and is assumed to be executed in the directory containing {execute_path}.",
                                #"- If you want to know about multiple files, please include multiple commands in a single shell script code in your answer.",
                                #f"- The shell script can contain multiple commands.",
                                #"- For example, if your code includes cat /path/to/test.c, you will be able to know the information of /path/to/test.c as it will be sent back to you in the next request prompt.",
                                "",
                                "2. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                                "3. In 'execute_command' mode:",
                                "## Purpose:",
                                "- You can execute the shell script code you answered.",
                                "## How to Answer:",
                                #f"- This executes separately from {ctx.paths.run_test_path}. If you don't need anything other than {ctx.paths.run_test_path}, you don't have to answer.", # {ctx.paths.run_test_path} or
                                "- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                f"- The shell script code you answer will be saved to the shell script file at {execute_path} and executed in the {execute_dir} directory.",
                                f"- Please design ./execute.sh to not take any arguments when executed.",
                                f"- The shell script can contain multiple commands.",
                    ])


            else:
                if not ctx.WO_READ:
                    prompt.extend([#"Please choose only one of the following three modes to generate your response.", #Your answer should choose only one mode.",
                                "",
                                "## Response Modes:",
                                "1. In 'read_data' mode:",
                                "## Purpose:",
                                #"- The execution results of the shell script code you answer will be sent back to you, so you can know them.", #(cat, less, tree etc...)
                                "- Returns the contents of the specified filename as is.",
                                "## How to Answer:",
                                #"- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                "- Please put the file path you want to know about in the \"target_files\" field of the JSON format data.",
                                "- If the file you want to know about has many lines and cannot be viewed due to context window limitations, you can specify \"start_line\" and \"end_line\" in addition to file_path in the \"file_slices\" to see between those specific line numbers.",
                                #f"- The shell script code you answer will be saved to the shell script file at {execute_path} and is assumed to be executed in the directory containing {execute_path}.",
                                #"- If you want to know about multiple files, please include multiple commands in a single shell script code in your answer.",
                                #f"- The shell script can contain multiple commands.",
                                #"- For example, if your code includes cat /path/to/test.c, you will be able to know the information of /path/to/test.c as it will be sent back to you in the next request prompt.",
                                "",
                                "2. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                                "3. In 'execute_command' mode:",
                                "## Purpose:",
                                "- You can execute the shell script code you answered.",
                                "## How to Answer:",
                                #f"- This executes separately from {ctx.paths.run_test_path} and {ctx.paths.run_test_path}. If you don't need anything other than {ctx.paths.run_test_path} or {ctx.paths.run_test_path}, you don't have to answer.",
                                "- Put the shell script code to be executed in the \"answer\" field of the JSON format data.",
                                f"- The shell script code you answer will be saved to the shell script file at {execute_path} and executed in the {execute_dir} directory.",
                                f"- Please design ./execute.sh to not take any arguments when executed.",
                                f"- The shell script can contain multiple commands.",
                     ])
                

                    prompt.extend(["",
                                    "",
                                    "## Other Notes:", #f"Please choose only one mode for your answer.",
                                    #"- If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                                    #"- If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                                    "- For the same error, please do not propose solution methods that have already been tried once, but suggest other solution methods.",
                                    #f"{platform_instruction}",
                                    #"- Writing to newly created files is done with 'execute_command', but in that case, please do not abbreviate the code to be written.",
                                    f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                                    #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing_in_mode' key.",
                                      "- If the JSON data to be included in a single mode response is likely to exceed the token limit, please answer in multiple parts.",
                                    "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing_in_mode' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key.",
                                    "- Always create your response in a single mode ('read_data', 'modify_data', 'execute_command') and only use 'ongoing_in_mode' when further exchanges are needed within that one mode.",
                                    "- When switching modes, please end your response by requesting a new request.",
                                    "- The content of modified_data you answer in 'modify_data' mode will be copied and pasted as is, so please absolutely do not include any abbreviated sections.",
                    ])
                
                elif ctx.WO_READ:
                    prompt.extend([#"Please choose only one of the following three modes to generate your response.", #Your answer should choose only one mode.",
                                "",
                                "## Response Modes:",
                                "1. In 'modify_data' mode:",
                                "## Purpose:",
                                "- You can modify the specified file path.",
                                "## How to Answer:",
                                f"- Delete the original code and insert the filename, start line, and end line of the section to be changed in the values of the \"file_path\", \"start_line\", and \"end_line\" keys in JSON format data.",
                                "- Then, put the new content to be inserted in that modified section in the value of the \"modified_data\" key.",
                                "- modified_data will be copied and pasted directly into the original code from start_line to end_line, so please insert appropriate indentation so that it can be copied and pasted and executed correctly.",
                                "- modified_data will be copied and pasted directly into the original code, so please absolutely do not include any abbreviated sections.",
                                "- If you want to delete but not insert into a specific section of the specified file path, set the value of \"is_deletion\" to True.",
                                "- If you want to overwrite the entire file rather than just modifying the specified line range, set the value of \"overwrite_all\" to True.",
                                "- If you don't know the exact start_line and end_line, you can run 'read_data' mode first, which will show the content of the code in that file with line numbers.",
                                "- If the file to be edited is a JSON file, set the is_JSON flag to True and put the JSON data to be inserted into modified_data.",
                                "",
                    ])
                
                    prompt.extend(["",
                                    "",
                                    "## Other Notes:", #f"Please choose only one mode for your answer.",
                                    #"- If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                                    #"- If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                                    "- For the same error, please do not propose solution methods that have already been tried once, but suggest other solution methods.",
                                    #f"{platform_instruction}",
                                    #"- Writing to newly created files is done with 'execute_command', but in that case, please do not abbreviate the code to be written.",
                                    f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                                    #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing_in_mode' key.",
                                      "- If the JSON data to be included in a single mode response is likely to exceed the token limit, please answer in multiple parts.",
                                    "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing_in_mode' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing_in_mode' key.",
                                    "- Always create your response in a single mode ('modify_data') and only use 'ongoing_in_mode' when further exchanges are needed within that one mode.",
                                    #"- When switching modes, please end your response by requesting a new request.",
                                    "- The content of modified_data you answer in 'modify_data' mode will be copied and pasted as is, so please absolutely do not include any abbreviated sections.",
                    ])

                
            prompt.extend(["- In summary, please respond in the following JSON format:"])
            if repair_target == "explore_path":
                if not (ctx.GDB_OPTION or ctx.WO_READ):
                    prompt.extend([autonomous_template])
                elif ctx.WO_READ:
                    prompt.extend([read_template])

                
                if not ctx.WO_PATH and ctx.strategy != "wo_tool":
                    print("Printing covered branch?")

            else:
                prompt.extend([autonomous_template])
    
            if error is not None and error is not True:
                prompt.extend(["", f"## Execution result error of {ctx.paths.run_test_path}:", f"{error}"])
                error = None

            if std_out is not None and std_out is not True:
                std_out = trim_data(work_dir, f"{work_dir}/std_out.txt", std_out, 10000)
                prompt.extend(["", f"## Execution Result of {ctx.paths.run_test_path}:", f"{std_out}"])
                std_out = None 

            prompt.extend(["", "## Directory Structure of the Target Program:"])
            directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir) 
            write_file(f"{database_dir}/directry_structure.txt", directory_structure)
            directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 6000) #, 10000)
            prompt.extend([directory_structure, ""])

        else:
            prompt.extend(["- In summary, please respond in the following JSON format:"]) 
            prompt.extend([autonomous_template])

            prompt.extend(["", "## Directory Structure of the Target Program:"])
            directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir)
            write_file(f"{database_dir}/directry_structure.txt", directory_structure)
            directory_structure = trim_code(f"{database_dir}/directry_structure.txt", directory_structure, 6000) #, 10000)

            prompt.extend([directory_structure, ""])

        if repair_target == "explore_path":
            target_code = get_lined_specific_code(database_dir, ctx.entry.target_path, ctx.entry.target_line, ctx.entry.target_end_line)
            target_code = trim_code(ctx.entry.target_path, target_code, 8000) #10000)

            # covered_code = get_covered_code()
            annotated_code = get_annotated_source_code_range(ctx.entry.target_path, ctx.entry.target_line, ctx.entry.target_end_line)
            print("=== Annotated source code ===")
            print(annotated_code)

            test_code = read_file(original_run_test_path)
            prompt.extend(["", f"## Original test shell that reaches the target function (in {original_run_test_path}):"])
            prompt.extend([test_code])


            prompt.extend(["", f"## Target function ({ctx.entry.target_function} of {ctx.entry.target_path} file (Line {ctx.entry.target_line})):"])
            prompt.extend([target_code])

            prompt.extend(["", f"## Target function with coverage information:"])
            prompt.extend([annotated_code])


        prompt = adjust_prompt(prompt)
        delete_file(execute_path)
        create_permissioned_file(execute_path)
        rsp_json = ask_llm(prompt, "continue", ctx.llm_interface)
        
        ongoing_in_mode_flag = False

        sum_target_list = []
        sum_modified_list = []
        sum_deleted_list = []

        sum_slice_list = []

        while (1):
            prompt = []
            execute_error = None

            if 'ongoing' in rsp_json:
                ongoing_flag = rsp_json['ongoing']

            if 'ongoing_in_mode' in rsp_json:
                ongoing_in_mode_flag = rsp_json['ongoing_in_mode']

            print(f"ongoing_flag at location 1 is {ongoing_flag}")
            print(f"ongoing_in_mode_flag at location 1 is {ongoing_in_mode_flag}")


            if 'mode' in rsp_json:
                mode = rsp_json['mode']

                if mode == 'read_data':
                    if 'answer' in rsp_json:
                        code = rsp_json['answer']
                        append_file(execute_path, code)

                    if 'target_files' in rsp_json:
                        target_list = rsp_json['target_files']
                        if not isinstance(target_list, list):
                            target_list = [target_list]
                        sum_target_list.extend(target_list)
                    
                    if 'file_slices' in rsp_json and rsp_json['file_slices'] is not None:
                        slice_list = rsp_json['file_slices']
                        if not isinstance(slice_list, list):
                            slice_list = [slice_list]
                        sum_slice_list.extend(slice_list)


                if mode == 'modify_data':
                    if 'answer' in rsp_json:
                        modified_list = rsp_json['answer'] 
                        if not isinstance(modified_list, list):
                            modified_list = [modified_list]
                        sum_modified_list.extend(modified_list)
                
                if mode == 'delete_data':
                    if 'answer' in rsp_json:
                        deleted_list = rsp_json['answer'] 
                        if not isinstance(deleted_list, list):
                            deleted_list = [deleted_list]
                        sum_deleted_list.extend(deleted_list)

                if mode == 'execute_command':
                    if 'answer' in rsp_json:
                        code = rsp_json['answer']
                        append_file(execute_path, code)

            if ongoing_in_mode_flag is False:
                break

            if 'testcase_num' in rsp_json:
                testcase_num = rsp_json['testcase_num']

            print("Keep going to receive Rust code in modifying.")

            if repair_target == "explore_path":
                prompt = [f"Please continue your answer for the code that passes through the specified function."]


            prompt.extend(["", "## Response rules:",
                        #"If you are encountering errors when expressing backslashes as byte literals, you need to escape backslashes in the source code and also escape them in the byte literals, so use three backslashes (double backslashes).",
                        #"If you are encountering errors when expressing backslashes as character literals, you need to escape backslashes in the source code and also escape them in the character literals, so use two backslashes.",
                        f"- To avoid hitting the output token limit, please keep the JSON data included in a single response within {output_max} tokens.", # For long answers,
                        #f"When answering in multiple parts, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key. If that JSON data is the last part, please enter the boolean value False in the 'ongoing' key.",
                          "- The modified code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections. If the JSON data to be included in a single response is likely to exceed the token limit, please answer in multiple parts.",
                        "- If that JSON data is the last one, please enter the boolean value False in the 'ongoing' key. Furthermore, if there is more JSON data remaining, please enter the boolean value True in the value of the 'ongoing' key.",
                        ])
                
            rsp_json = ask_llm(prompt, "continue", ctx.llm_interface) 

        print(f"Running program for the mode: {mode}")
        if mode == 'modify_data':
            print(f"In mode: {mode}")
            reflect_line_modification(sum_modified_list, ctx.paths.work_dir, ctx.paths.database_dir) 

        elif mode == 'delete_data':
            print(f"In mode: {mode}")
            reflect_line_deletion(sum_deleted_list, ctx.paths.work_dir, ctx.paths.database_dir) 

        elif mode == 'read_data':
            print(f"In mode: {mode}")
            read_prompt = ["- The content obtained in read_data mode is as follows.", ""] 

            slice_set = set()
            for slice_item in sum_slice_list:
                slice_set.add(slice_item['file_path'])

            new_sum_target_list = []
            print(f"sum_target_list: {sum_target_list}")
            for see_path in sum_target_list:
                if see_path not in slice_set:
                    new_sum_target_list.append(see_path)
            sum_target_list = new_sum_target_list

            sum_target_list = list(set(sum_target_list))

            ## checked
            tmp_sum_target_list = []
            for see_path in sum_target_list:
                if not os.path.exists(see_path):
                    see_path = find_matching_path(ctx.paths.work_dir, see_path)
                tmp_sum_target_list.append(see_path)
            sum_target_list = tmp_sum_target_list

            for see_path in sum_target_list:
                is_excluded = check_excluded(see_path, ctx.paths.work_dir)
                if is_excluded:
                    continue

                file_code = get_lined_code(see_path, ctx.paths.work_dir)
                file_code = trim_code(see_path, file_code, 10000)

                read_prompt.extend([f"Content of the file {see_path}:"]) 
                if not is_empty_string(file_code):
                    read_prompt.extend([f'{file_code}\n'])
                else:
                    read_prompt.extend([f'None\n'])
            
            for see_item in sum_slice_list:
                is_excluded = check_excluded(see_item['file_path'], ctx.paths.work_dir)
                if is_excluded:
                    continue

                file_code = get_lined_specific_code(ctx.paths.database_dir, see_item['file_path'], see_item['start_line'], see_item['end_line'])
                file_code = trim_code(see_item['file_path'], file_code, 10000)

                read_prompt.extend([f"Content of {see_item['start_line']} - {see_item['end_line']} lines in the file {see_item['file_path']}:"])
                read_prompt.extend([f'{file_code}\n'])

        
        elif mode == 'execute_command':
            print(f"In mode: {mode}")
            if repair_target == "explore_path":
                execute_error, execute_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp, original_run_test_path = run_cov_script(
                    process_type, ctx.cov_target, ctx.paths.run_test_path, entry, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, 
                    ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir, 
                    initial_coverage, ctx.paths.function_branch_path, ctx.paths.is_program_path, ctx.paths.current_cov_path
                ) 
            
            else:
                execute_error, execute_out, ctx.repair_count = run_script(
                    execute_path, 10, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, mode
                )
                execute_out = run_script_pty(ctx.paths.run_test_path)
            
        ctx.repair_count += 1 

    llm_end_time = time.time()
    write_time(time_path, "llm", "end", repair_target, llm_end_time)

    if repair_target == "explore_path": # is True:  #if select_flag is True:
        ans_entry = {
            "repair_count" : ctx.repair_count,
            "version_count" : version_count, 
            "is_covered" : is_covered,
            "elapsed_time" : elapsed_time,
            "diff" : diff,
            "timestamp" : timestamp,
            "path_count" : path_count,
            "min_length" : min_length,
            "max_length" : max_length
        }
        return ans_entry #ctx.repair_count, is_covered, elapsed_time, diff
    

def repair_branch_agent(repair_target, ctx):
    """ask_agent version of repair_branch.

    The agent writes run_test_path (a shell script) directly; branch-coverage
    measurement (run_branch_cov_script) is done by the orchestrator, right after
    the agent finishes, as in repair_test_agent. The old read_data/modify_data/
    execute_command dispatch and ongoing / ongoing_in_mode loops are removed,
    since the Agent SDK absorbs them. Prompt text is kept as in the original;
    only the mode descriptions, the JSON response template, and the
    ongoing / output_max / max_counter lines are dropped.
    """

    process_type = repair_target 
    function_branch_path = f"{ctx.paths.database_dir}/cov_candidate.json"

    explore_time = None
    is_covered = None
    diff = None
    is_increased = None
    path_count = None
    min_length = None
    max_length = None
    timestamp = None
    elapsed_time = None

    test_path     = interface['test_path']
    file_path     = interface['file_path']
    test_id       = interface['test_id']
    function_name = interface['function_name']
    main_flag     = interface['main_flag']

    dep_data = read_json(dep_json_path)

    if ctx.repair_count is None:
        ctx.repair_count = 1

    version_count = 0
    error = None
    std_out = None

    # --- Agent execution environment: author the shell script only.
    #     Measurement (run_branch_cov_script) is done by the orchestrator, so the
    #     agent gets no Bash (avoids gcda contamination before measurement). ---
    agent.allowed_tools = ["Read", "Grep", "Glob", "Write", "Edit"]
    agent.add_dirs = list({
        os.path.dirname(os.path.normpath(ctx.paths.run_test_path)),
        ctx.paths.target_dir, original_target_dir, ctx.paths.database_dir, ctx.paths.work_dir,
    })
    if agent.session_path:
        delete_file(agent.session_path)

    llm_start_time = time.time()
    write_time(time_path, "llm", "start", repair_target, llm_start_time)

    branch_coverage, line_coverage, function_coverage = get_coverage(
        ctx.cov_target, ctx.paths.target_dir, ctx.paths.database_dir, 
        ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path,
        ctx.paths.is_program_path, ctx.paths.current_cov_path
    )

    global current_branch_coverage
    current_branch_coverage = branch_coverage
    initial_coverage = branch_coverage
    target_statement = "target line"

    while (1):
        llm_end_time = time.time()
        elapsed_time = llm_end_time - llm_start_time

        if version_count > fixed_version_count:
            break

        if repair_target == "no_target" and ctx.repair_count > 1:
            break

        # ---------------- prompt construction ----------------
        if repair_target == "explore_path":
            if ctx.repair_count == 1:
                prompt = []
                prompt.extend([
                    f"The following commands in {original_run_test_path} are commands that reach the target {ctx.entry.target_function} function below. Please write shell script code in {ctx.paths.run_test_path} to execute diverse commands using the {target_cmd} command that would improve branch coverage within that target function.",
                ])

                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                prompt.extend(["", "## Response rules:",
                    f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                    f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                    f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                    f"- Even if the program implements other commands, please write test cases only for the {ctx.target_cmd} command for now.",
                    f"- The {ctx.target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                    f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                    "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                    f"- Please do not include build execution (./{ctx.paths.build_path}) in the shell code in {ctx.paths.run_test_path}.",
                    f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                    f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                    f"- Please set as many options as possible in a single command to explore more execution paths.",
                    f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater.",
                    f"{tool_cmd}",
                    f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                    f"- Please do not include commands that delete input files in the shell script.",
                    f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                    "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                    "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections.",
                    ])
                prompt.extend(notes)

            else:
                prompt = [
                    f"With the current code, we have not yet been able to improve branch coverage of the target function.",
                    f"Please write a shell script code to {ctx.paths.run_test_path} that will improve branch coverage of the target {ctx.entry.target_function} function.",
                ]
                prompt.extend(["", "## Response rules:",
                    f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                    f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                    f"- Even if the program implements other commands, please write test cases only for the {target_cmd} command for now.",
                    f"- The {target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                    f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                    f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                    "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                    "- Please do not make any changes to the source code of the test target, and write shell code that changes the arguments of the execution program, etc.",
                    f"- Please do not include build execution (./{build_path}) in the shell code in {ctx.paths.run_test_path}.",
                    ])
                prompt.extend(notes)

        elif repair_target == "no_target":
            if ctx.repair_count == 1:
                prompt = []
                prompt.extend([
                    f"For the program with the following directory structure, please write shell script code in {ctx.paths.run_test_path} to execute test cases for the {pure_cmd} command in a way that maximizes code coverage.",
                ])
                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                prompt.extend(["", "## Response rules",
                    f"- Please write the response shell script to the path {ctx.paths.run_test_path}.",
                    f"- Your task is only to generate {ctx.paths.run_test_path}. Do NOT execute or verify the generated script under any circumstances. Verifying whether the script actually reaches the target is out of scope for this task and will be handled by a separate process.",
                    f"- Consider methods to execute the specified line by manipulating the arguments of the main function (command line arguments).",
                    f"- The {target_cmd} command can be executed in the code with ./{ctx.cmd_exe}.",
                    f"- Please ensure all commands are written in complete form beginning with `./{ctx.cmd_exe}`. Do not use variables or aliases - write directly executable command lines.",
                    f"- Even if the program implements other commands, please write test cases only for the {pure_cmd} command for now.",
                    "- The shell script will be executed in the directory where the file is located, so please write the code considering this point.",
                    f"- Please do not include build execution (./{build_path}) in the shell code in {ctx.paths.run_test_path}.",
                    f"- Please do not use compilation-related commands (gcc, cc, make, etc.) in the shell code in {ctx.paths.run_test_path}, and execute the {target_statement} using only existing binaries.",
                    f"- Since we plan to iteratively modify to increase coverage, please write {ctx.paths.run_test_path} to complete execution within approximately 30 seconds.",
                    f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater.",
                    f"{tool_cmd}",
                    f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                    f"- Please do not include commands that delete input files in the shell script.",
                    f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                    "- Since coverage information is being accumulated, please absolutely do not recompile the source code.",
                    "- The answer code will be executed by direct copy and paste, so please absolutely do not include any abbreviated sections.",
                    ])
                prompt.extend(notes)
            else:
                print("Should not proceed this step")
                tool_cmd = get_tool_cmd(ctx.strategy, tool_string)
                prompt = [
                    f"Please modify the test case {ctx.paths.run_test_path} to increase coverage for the program.",
                    f"- Please set as many options as possible in a single command to explore more execution paths.",
                    f"- Please make each input file that each command uses have a different name to ensure uniqueness, using the format \"input{{counter}}.{{suffix}}\" (like input0.txt, input1.txt ...), where {{counter}} is a number {ctx.testfile_counter} or greater.",
                    f"{tool_cmd}",
                    f"- Please avoid placing input files in any directory, like test_data/inputfile.",
                    f"- Please do not include commands that delete input files in the shell script.",
                    f"- Please do not use shell variables ($variable or ${{variable}}) in commands, since each command sequence will be extracted individually later.",
                    ]

        # --- previous execution feedback (mirrors the original error / std_out injection) ---
        if error is not None and error is not True:
            prompt.extend(["", f"## Execution result error of {ctx.paths.run_test_path}:", f"{error}"])
            error = None

        if std_out is not None and std_out is not True:
            std_out = trim_data(work_dir, f"{work_dir}/std_out.txt", std_out, 10000)
            prompt.extend(["", f"## Execution Result of {ctx.paths.run_test_path}:", f"{std_out}"])
            std_out = None

        # --- directory structure ---
        prompt.extend(["", "## Directory Structure of the Target Program:"])
        directory_structure = get_dir_struct("testcase", ctx.paths.work_dir, ctx.original_target_dir)
        write_file(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure)
        directory_structure = trim_code(f"{ctx.paths.database_dir}/directry_structure.txt", directory_structure, 6000)
        prompt.extend([directory_structure, ""])

        # --- target function + coverage annotation + original reaching test (from the original) ---
        if repair_target == "explore_path":
            target_code = get_lined_specific_code(ctx.paths.database_dir, ctx.entry.target_path, ctx.entry.target_line, ctx.entry.target_end_line)
            target_code = trim_code(ctx.entry.target_path, target_code, 8000)

            # covered_code = get_covered_code()
            annotated_code = get_annotated_source_code_range(ctx.entry.target_path, ctx.entry.target_line, ctx.entry.target_end_line)

            test_code = read_file(original_run_test_path)
            prompt.extend(["", f"## Original test shell that reaches the target function (in {original_run_test_path}):"])
            prompt.extend([test_code])

            prompt.extend(["", f"## Target function ({ctx.entry.target_function} of {ctx.entry.target_path} file (Line {ctx.entry.target_line})):"])
            prompt.extend([target_code])

            prompt.extend(["", f"## Target function with coverage information:"])
            prompt.extend([annotated_code])

        prompt = adjust_prompt(prompt)

        # --- agent run (replaces ask_llm + the ongoing/mode receive loops) ---
        result = ask_agent(prompt, "continue", agent)
        if result.is_error:
            print(f"[agent] run reported error (turns={result.num_turns})")

        # --- measure branch coverage of the run_test_path the agent just wrote ---
        if repair_target == "explore_path":
            error, std_out, is_covered, is_increased, diff, current_branch_coverage, branch_coverage, line_coverage, function_coverage, timestamp = run_branch_cov_script(
                process_type, ctx.paths.run_test_path, entry, ctx.paths.branch_path, ctx.paths.line_path, ctx.paths.function_path, ctx.paths.is_program_path,
                ctx.paths.target_dir, ctx.paths.database_dir, ctx.paths.snap_dir, ctx.paths.tmp_dir, 
                current_branch_coverage, function_branch_path
            )

            version_count += 1
            print(f"\nJudge at {entry}: {is_increased}")
            save_coverage_report(
                ctx.cov_target, ctx.paths.cov_report_path, ctx.paths.token_path, 
                current_branch_coverage, line_coverage, function_coverage, "llm"
            )

            if ctx.WO_VALIDATION is True:
                break
            if is_increased is True:
                break

        elif repair_target == "no_target":
            error, std_out, ctx.repair_count = run_script(
                ctx.paths.run_test_path, 10, True, None, "both", None, ctx.repair_count, ctx.max_iterations, ctx.paths.log_dir, None
            )

        ctx.repair_count += 1

    llm_end_time = time.time()
    write_time(ctx.paths.time_path, "llm", "end", repair_target, llm_end_time)

    if repair_target == "explore_path":
        ans_entry = {
            "repair_count" : ctx.repair_count,
            "version_count" : version_count,
            "is_covered" : is_covered,
            "elapsed_time" : elapsed_time,
            "diff" : diff,
            "timestamp" : timestamp,
            "path_count" : path_count,
            "min_length" : min_length,
            "max_length" : max_length,
        }
        return ans_entry


def explore_branch(
    paths, llm_interface, strategy, cov_target, target_cmd, target_entry,
    original_target_dir, max_num_test, fixed_explore_time,
    database_json, error, std_out, graph_metrics, G
):
    entry = {}
    print("=====================================")
    print(f"target_entry is {target_entry}")
    print("=====================================")

    entry['target_path'] = target_entry['target_path']
    entry['target_line'] = target_entry['target_line'] 
    entry['target_function'] = target_entry['target_function']
    entry['target_uncovered_ratio'] = target_entry['target_uncovered_ratio']
    entry['target_branch'] = target_entry['target_branch']
    entry['flow_log_path'] = flow_log_path


    target_path = target_entry['target_path']
    target_line = target_entry['target_line'] 
    target_end_line = target_entry['target_end_line']

    target_function = target_entry['target_function'] 
    target_uncovered_ratio = target_entry['target_uncovered_ratio']
    target_branch = target_entry['target_branch']

    # setup for asking llm
    execute_path = f"{ctx.paths.work_dir}/execute.sh"

    cmd_list = []
    cmd_exe = database_json[target_cmd]["cmd_exe"]
    notes = database_json[target_cmd]["notes"]

    if explore_fix == "t":
        explore_time = fixed_explore_time
    else:
        explore_time = target_entry['explore_time']

    repair_count = 1
    ctx = RepairContext(
        paths=paths,
        llm_interface=llm_interface,
        select=False,
        cov_target=cov_target,
        strategy=strategy,
        max_num_test=max_num_test,
        entry=entry,
        original_run_test_path=target_entry['original_run_test_path'],
        repair_count=repair_count,
        target_path=target_path,
        target_function=target_function,
        target_uncovered_ratio=target_uncovered_ratio,
        target_branch=target_branch,
        target_line=target_line,
        target_end_line=target_end_line,
        target_cmd=target_cmd,
        execute_path=execute_path,
        cmd_list=cmd_list,
        test_path=None,
        file_path=None,
        test_id=None,
        function_name=None,
        main_flag=None,
        explore_time=explore_time,
        cmd_exe=cmd_exe,
        notes=notes,
    )

    if strategy != "wo_tool":
        if llm_interface.AGENT is False:
            ans_entry = repair_branch_llm('explore_path', ctx)
        else:
            ans_entry = repair_branch_agent('explore_path', ctx)

        repair_count = ans_entry['repair_count']
        version_count = ans_entry['version_count']
        is_covered = ans_entry['is_covered']
        elapsed_time = ans_entry['elapsed_time']
        diff = ans_entry['diff']
        timestamp = ans_entry['timestamp']
        path_count = ans_entry['path_count']
        min_length = ans_entry["min_length"]
        max_length = ans_entry["max_length"]

        is_increased = False
        if diff is not None and diff > 0:
            is_increased = True
        if diff is None:
            diff = 0

        target_data = {
            "file_path" : target_path,
            "line_number" : target_line,
            "name" : target_function,
            "repair_count" : repair_count,
            "version_count" : version_count,
            "elapsed_time" : elapsed_time, 
            "explore_time" : explore_time,
            "timestamp" : timestamp, 
            "path_count" : path_count,
            "min_length" : min_length,
            "max_length" : max_length,
            "is_covered" : is_covered,
            "is_increased" : is_increased,
            "diff" : diff,
        }

        update_select(select_path, target_data)
    
    elif strategy == "wo_tool":
        if llm_interface.AGENT is False:
            ans_entry = repair_branch_llm('no_target', ctx)
        else:
            ans_entry = repair_branch_agent('no_target', ctx)

    # print(f"Current coverage: {current_coverage}")
    # return current_coverage 

