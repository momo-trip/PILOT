import glob
import os
import re
import shlex

from utils_api import (
    read_file,
    write_file,
    copy_file,
    delete_file,
    append_file,
    create_directory,
    delete_directory,
    get_all_files,
    get_lined_code,
)

from llm_api import (
    ask_llm,
    # ask_agent,
)

from pilot_lib.utils import (
    run_script,
    append_list_to_file,
    get_pure_cmd,
)

def delete_first_line(brashed_path):

    with open(brashed_path, 'r') as f:
        lines = f.readlines()

    with open(brashed_path, 'w') as f:
        f.writelines(lines[1:])  
            

def remove_rm(run_test_path):
    modified_lines = []  # typo fixed
    
    # Read
    with open(run_test_path, 'r') as f:
        for line in f:
            line = line.replace('rm ', '')
            line = line.replace('> /dev/null', '')
            modified_lines.append(line)
    
    # Write
    with open(run_test_path, 'w') as f:
        for line in modified_lines:
            f.write(line)


def get_run_test_path(shell_dir):
    target_files = []

    if not os.path.exists(f"{shell_dir}"):
        print(f"Directory not found: {shell_dir}")
        return []
    
    target_files = glob.glob(os.path.join(f"{shell_dir}", "*.sh"))

    # Find all target JSON files
    target_files = [f for f in target_files if f.endswith(".sh")]

    return target_files


def extract_command_args(process_type, cmd, script_file_path, input_dir):

    unfind = False
    try:
        # Read the script file
        with open(script_file_path, 'r') as file:
            script_content = file.read()
        
        # Extract the arguments following the command using a regular expression
        # Fix the dots that need escaping, and correctly expand {cmd} as a variable
        pattern = r'\.\/' + re.escape(cmd) + r'\s+(.*?)($|\n)'
        matches = re.finditer(pattern, script_content)
        
        # Check existing file numbers in the input directory
        existing_files = [f for f in os.listdir(input_dir) if f.startswith('input') and f[5:].isdigit()]
        
        # Get the current maximum number
        max_num = 0
        for file in existing_files:
            try:
                num = int(file[5:])  # Extract the numeric part after 'input'
                max_num = max(max_num, num)
            except ValueError:
                continue
        
        # List to store the results
        extracted_args = []
        
        # Process every match found
        for i, match in enumerate(matches):
            arguments = match.group(1).strip()
            
            # Set the new file number
            file_num = max_num + i + 1
            output_path = os.path.join(input_dir, f"input{file_num}")
            
            print(output_path)
            with open(output_path, 'w') as out_file:
                out_file.write(arguments)
            
            print(f"Extracted arguments: {arguments}")
            print(f"Saved arguments to {output_path}")
            
            extracted_args.append(arguments)

        if extracted_args:
            print("Command found")
            #return extracted_args
        else:
            print(f"The ./{cmd} command was not found: at {script_file_path}")
            unfind = True
    
    except Exception as e:
        print(f"An error occurred: {e}")

    return unfind


def prepare_base_argv(
    target_cmd, order, base_argv_path, process_type, 
    target_dir, database_dir, database_json, shell_dir, directory_id
): 
    print("Function in car prepare_argv)")

    seed_dir = f"seed_tmp/{target_cmd}"
    if os.path.exists(seed_dir):
        delete_directory(seed_dir)
    create_directory(seed_dir)

    cmd = database_json[target_cmd]["cmd_exe"] 
    pure_cmd = get_pure_cmd(target_cmd)
    test_list = get_run_test_path(shell_dir)
    count = 0

    for run_test_path in test_list:
        print(f"Running {run_test_path}...")
        copy_file(run_test_path, target_dir)
        run_filename = os.path.basename(run_test_path)
        #run_script(f"{target_dir}/{run_filename}", 30, True, None, "both")
        count += 1
        print(f"{count} / {len(test_list)}")
        # if count > given_count:
        #     break

    count = 0
    need_check = []

    for run_test_path in test_list:
        print(f"Running {run_test_path}...")
        run_test_path = run_test_path.replace(shell_dir, target_dir)
        remove_rm(run_test_path)

        run_script(process_type, database_dir, run_test_path, 50, True, None, "both") #100, True, None, "both")
        unfind = extract_command_args(process_type, cmd, run_test_path, seed_dir) #f"{target_dir}/{input_dir}")
        if unfind is True:
            need_check.append(run_test_path)
            append_file(f"{database_dir}/{target_cmd}_{directory_id}/need_check.txt", f"{run_test_path}\n")

        count += 1
        print(f"{count} / {len(test_list)}")
        # if count > given_count:
        #     break
    
    if len(need_check) > 0:
        print("len(need_check) > 0")


    lines = []  # Temporarily store the content to be written
    line_count = 0
    
    for filename in os.listdir(seed_dir):
        file_path = os.path.join(seed_dir, filename)
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as input_file:
                    content = input_file.read().strip()
                    if content:  # Write only if not empty
                        lines.append(f'{pure_cmd} ' + content)  # Remove newlines
                        line_count += 1
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
    
    with open(base_argv_path, 'w') as output_file:
        for i, line in enumerate(lines):
            if i == len(lines) - 1:  # For the last line
                output_file.write(line)  # No newline
            else:
                output_file.write(line + '\n')  # With newline
            
    print(f"\nSaved arguments to: {base_argv_path} (total: {line_count} lines)")



def get_slices(base_argv_path, slice_num):
    slices = []
    print(base_argv_path)
    file_string = read_file(base_argv_path)
    print(file_string)
    slice_size = slice_num #100 #50
    skip_empty = True

    if not file_string.strip():  # File is empty or contains only spaces
        return slices
    
    # Split the file content into lines
    lines = file_string.splitlines()
    
    # Split into slices of 50 lines each
    for i in range(0, len(lines), slice_size):
        slice_lines = lines[i:i + slice_size]
        
        if skip_empty and not any(line.strip() for line in slice_lines):
            continue  # Skip slices consisting only of empty lines
            
        slice_content = '\n'.join(slice_lines)
        slices.append(slice_content)

    return slices 



autonomous_template = f"""
{{
    "answer" : "answer cotent",
    "input_option" : "input file option content",
    "ongoing" : true if the response will continue. false otherwise,
    "info" : explanatory text for the response,
    "info_match" : true or false
}}
"""

basic_template = f"""
{{
    "answer" : "answer cotent",
    "ongoing" : true if the response will continue. false otherwise,
    "info" : explanatory text for the response,
    "info_match" : true or false
}}
"""

input_template = f"""
{{
    "input_answer" "answer for input file paths",
    "ongoing" : true if the response will continue. false otherwise,
    "info" : explanatory text for the response,
    "info_match" : true or false
}}
"""

def change_command_string_llm(
    llm_interface, base_argv_path, raw_path, target_cmd, change_type, database_dir
):

    prompt = []
    sum_modified_list = []
    opt_sum_modified_list = []

    slice_num = 50 #100

    if change_type != "input":
        prompt.extend(["Regarding the contents of the txt file that lists candidate command-line arguments, please rewrite them by changing the format of the input files and output files so that fuzzing can be performed."])
        
        prompt.extend(["## Response rules:",
                    "- Please write the answer in JSON format following the format below.",
                    "",
                    "### Value of the \"answer\" key:",
                    "- Write the input file as @@. If there are two or more input files, make only the command's main input file @@, and leave the auxiliary input files as their path names.",
                    "- Write the output file as /tmp/foo. If there was originally no output file, do not write one (the \"> /tmp/foo\" that writes standard output is not needed).",
                    #"- If there is an input file to replace with @@, please move the option that uses that input file path and the chunk that is the file path argument to the very end, and tell me that option name.",
                    "- If there is an input file to replace with @@, please move the option part that uses that input file path and the path name argument to the very end, as long as it remains valid as a command.",
                    "- Please remove redirections (2>/dev/null, 2>&1, etc.) and shell control structures (|| true, && etc.), leaving only the pure command part.",
                    "- The content inside the answer key should be exactly what will be copy-pasted into the txt file.",
                    f"- Start from the first line of the txt file, and begin your answer with the first {slice_num} lines.", #Do not respond with something like 'The input file is too large to process in a single response. Please provide a smaller subset of the file or specify a range of lines to process.'; instead, refer to the file starting from line 1 and begin answering the commands.",
                    "- Since the answer will be copy-pasted directly into the txt file, never omit any of the original file's content.",
                    f"- Please write the number corresponding to the Line before the answer command. Example) For the command on Line 1, answer with Line 1. {target_cmd} <arguments>.",
                    "",
                    # "### Value of the \"input_option\" key:",
                    # "- In the input_option key of the JSON data, if moving @@ to the end of the command sequence is valid as a command sequence, place the word valid, then write only the single chunk of the option part that uses that input file path.",
                    # f"- More specifically, the answer inside the input_option key should, like the \"answer\" key answer, first write the Line number corresponding to the target command for each line, then write valid or invalid, and then write only the single chunk of the option part needed for the input file.",
                    # "    Example) For the command on Line 1, answer with \"Line 1. valid or invalid: -i @@\".",
                    # "",
                    "### Value of the \"ongoing\" key:",
                    "- If the answer continues, set the ongoing flag to True.",
                    "",
                    "### Values of the \"info\" key and \"info_match\" key:",
                    "- Count the commands in the answer. Also count the number of commands before modification. Write each count inside the \"info\" key.",
                    "- If the number of commands in the answer and the number of commands before modification do not match, set the info_match key to false."
                    ])
        
        prompt.extend([basic_template])  
    
    else:
        prompt.extend(["Regarding the contents of the txt file that lists candidate command-line arguments, please extract only the input file paths, extract them one file path at a time, and list them in the output txt file with a line break in the format Line X. <input file path>."])
        
        prompt.extend(["## Response rules:",
                    #"- Write the input file as @@.",
                    #"- Write the output file as /tmp/foo.",
                    #"- Please remove redirections (2>/dev/null, 2>&1, etc.) and shell control structures (|| true, && etc.), leaving only the pure command part.",
                    "- Please write the answer in JSON format following the format below.",
                    "- The content inside the answer key should be exactly what will be copy-pasted into the txt file.",
                    f"- Start from the first line of the txt file, and begin your answer with the first {slice_num} lines.", #Do not respond with something like 'The input file is too large to process in a single response. Please provide a smaller subset of the file or specify a range of lines to process.'; instead, refer to the file starting from line 1 and begin answering the commands.",
                    f"- If there are multiple input files, write the single most primary input file.",
                    "- If the answer continues, set the ongoing flag to True.",
                    "- Since the answer will be copy-pasted directly into the txt file, never omit any of the original file's content.",
                    f"- Please write the number corresponding to the Line before the answer file path name. Example) For the command on Line 1, answer with Line 1. <input file path>.",
                    "- Count the number of lines in the answer. Also count the number of lines before modification (the number of commands). Write each count inside the \"info\" key.",
                    "- If the counts before and after the answer do not match, set the info_match key to false."
                    ])
        
        prompt.extend([autonomous_template])

    slices = get_slices(base_argv_path, slice_num)
    print(slices)
    print(len(slices))

    rsp_json = None
    count = 0

    delete_file(raw_path)
 
    for file_string in slices:
        count += 1
        print(f"Counting: {count} / {len(slices)}...")
        if count == 1:
            prompt.extend(["## txt file:"])
            write_file(f"{database_dir}/lines.txt", file_string)
            file_string = get_lined_code(f"{database_dir}/lines.txt", database_dir)
            prompt.extend([f'{file_string}\n'])

        ongoing_flag = None
        rsp_json = {}
        while(1):
            if count == 1:
                rsp_json = ask_llm(prompt, "init", llm_interface)

            if 'answer' in rsp_json:
                modified_list = rsp_json['answer']
                if not isinstance(modified_list, list):
                    modified_list = [modified_list]
                sum_modified_list.extend(modified_list)
                append_list_to_file(raw_path, modified_list)

            if 'input_answer' in rsp_json:
                modified_list = rsp_json['input_answer']
                if not isinstance(modified_list, list):
                    modified_list = [modified_list]
                sum_modified_list.extend(modified_list)
                append_list_to_file(raw_path, modified_list)
            
            # if 'input_option' in rsp_json:
            #     opt_modified_list = rsp_json['input_option']
            #     if not isinstance(opt_modified_list, list):
            #         opt_modified_list = [opt_modified_list]
            #     opt_sum_modified_list.extend(opt_modified_list)
            #     append_list_to_file(opt_answer_path, opt_modified_list)
            
            #ongoing_flag = False
            if 'ongoing' in rsp_json:
                ongoing_flag = rsp_json['ongoing']
                ongoing_flag = False

            if ongoing_flag is False:
                break

            prompt = ["Please continue the JSON data answer.",
                        #f"The modified code content written in \"modified_data\" should not contain omitted sections. Also, since it will be copy-pasted directly between start_line and end_line, please write the indentation correctly.", #Make it compilable.",
                        #"If an error occurs when representing a backslash as a byte literal, you need to escape the backslash in the source code and also escape it within the byte literal, so use three backslashes (double backslash).",
                        #"If an error occurs when representing a backslash as a character literal, you need to escape the backslash in the source code and also escape it within the character literal, so use two backslashes.",
                        #f"To avoid hitting the output token limit, keep the JSON data included in a single response within {token_max} tokens", # If it is a long answer,
                        #"Since the modified code will be copy-pasted and executed directly, absolutely do not include omitted sections. If the JSON data to include in a single response is likely to exceed the token limit, please answer in multiple installments.",
                        "If that JSON data is the last one, write the boolean value False in the 'ongoing' key. Furthermore, if there is remaining continuation JSON data, write the boolean value True in the 'ongoing' key.",
                        ]

            if count > 1:
                if ongoing_flag is None:
                    prompt.extend(["## txt file:"])
                    write_file(f"{database_dir}/lines.txt", file_string)
                    file_string = get_lined_code(f"{database_dir}/lines.txt", database_dir)
                    prompt.extend([f'{file_string}\n'])
                
                rsp_json = ask_llm(prompt, "continue", llm_interface)
            
        prompt = []

    print("============= answer =============")
 


def change_command_string_agent(
    llm_interface, base_argv_path, raw_path, target_cmd, change_type, database_dir
):
    raise NotImplementedError(
        "Command-string rewriting is a batch preprocessing step and runs on the "
        "LLM path only. Agent mode is used for the exploration loop, not here."
    )


def change_command_string(
    change_type, llm_interface, 
    base_argv_path, raw_path, target_cmd, database_dir
):
    
    """
    if llm_interface.AGENT is False:
        change_command_string_llm(
            llm_interface, base_argv_path, raw_path, target_cmd, change_type, database_dir
        )
    else:
        change_command_string_agent(
            llm_interface, base_argv_path, raw_path, target_cmd, change_type, database_dir
        )
    """
    change_command_string_llm(
            llm_interface, base_argv_path, raw_path, target_cmd, change_type, database_dir
        )



def remove_blank_lines(file_path):
    """Remove the trailing newline character of the file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove the trailing newline character
    content = content.rstrip('\n')
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)




def remove_duplicate(file_path):
    """
    Function that removes duplicate lines in a file, keeping only the first-appearing line
    
    Args:
        file_path (str): Path of the target file (shared for input and output)
    """
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        seen_lines = set()  # Set to record lines already seen
        unique_lines = []   # List to store lines without duplicates
        
        for line in lines:
            stripped_line = line.strip()  # Remove leading/trailing whitespace and newlines
            
            # Skip empty lines
            if not stripped_line:
                continue
            
            # Add only if the line has not been seen before
            if stripped_line not in seen_lines:
                seen_lines.add(stripped_line)
                unique_lines.append(stripped_line)
        
        # Overwrite the original file with the deduplicated content
        with open(file_path, 'w', encoding='utf-8') as file:
            for line in unique_lines:
                file.write(line + '\n')
        
        print(f"Deduplication complete: {len(lines)} lines -> {len(unique_lines)} lines")
        
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
    except Exception as e:
        print(f"An error occurred: {e}")



def remove_without_at(file_path):
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        seen_lines = set()  # Set to record lines already seen
        unique_lines = []   # List to store lines without duplicates
        
        for line in lines:
            stripped_line = line.strip()  # Remove leading/trailing whitespace and newlines
            
            # Skip empty lines
            if not stripped_line:
                continue
            
            # Add only if the line has not been seen before
            if "@@" in stripped_line:
                unique_lines.append(stripped_line)
        
        # Overwrite the original file with the deduplicated content
        with open(file_path, 'w', encoding='utf-8') as file:
            for line in unique_lines:
                file.write(line + '\n')
        
        print(f"Deduplication complete: {len(lines)} lines -> {len(unique_lines)} lines")
        
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
    except Exception as e:
        print(f"An error occurred: {e}")



def insert_line_count(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Check whether the first line is a number
    if lines and lines[0].strip().isdigit():
        # If the line count has already been inserted, do nothing
        return

    line_count = len(lines)
    
    with open(file_path, 'w') as f:
        f.write(f"{line_count}\n")
        f.writelines(lines)


def brash_up(input_path, output_path, target_cmd, analysis_type):
    print("Brashing up...")
    try:
        with open(input_path, 'r', encoding='utf-8') as input_file:
            lines = input_file.readlines()
        
        processed_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Remove the "Line X. " pattern
            # Remove the pattern that starts with "Line ", followed by a number, and ends with ". "
            cleaned_line = re.sub(r'^Line\s+\d+[.:]?\s*', '', line)

            if analysis_type != "input":
                # Remove the part before target_cmd
                if target_cmd in cleaned_line:
                    # If target_cmd is included, keep only the part from target_cmd onward
                    target_index = cleaned_line.find(target_cmd)
                    cleaned_line = cleaned_line[target_index:]
                
            processed_lines.append(cleaned_line)
        
        # Write to the output file
        with open(output_path, 'w', encoding='utf-8') as output_file:
            for line in processed_lines:
                output_file.write(line + '\n')
                
        print(f"Processing complete: {input_path} -> {output_path}")
        
    except FileNotFoundError:
        print(f"Error: File '{input_path}' not found")
    except Exception as e:
        print(f"An error occurred: {e}")

    remove_blank_lines(output_path)

    if analysis_type != "input":
        insert_line_count(output_path)



def prepare_input_files(
    target_cmd, order, dst_path, input_brashed_path, 
    target_dir, database_json, directory_id
):
    print("Function in car prepare_input_files()")    

    cmd = database_json[target_cmd]["cmd_exe"] 
    pure_cmd = get_pure_cmd(target_cmd)
    test_list = get_run_test_path(directory_id)

    #print(test_list)
    for run_test_path in test_list:
        print(run_test_path)
    print(len(test_list))

    count = 0
    for run_test_path in test_list:
        copy_file(run_test_path, target_dir)
        print(target_dir)
        run_filename = os.path.basename(run_test_path)
        print("Running ...")
        run_script(f"{target_dir}/{run_filename}", 30, True, None, "both")

        count += 1
        print(f"{count} / {len(test_list)}")
        # if count > given_count:
        #     break

    unique_files = set() #[]
    with open(input_brashed_path, 'r') as f:
        for line in f:
            filename = line.strip()  # Remove newline characters
            print(filename)
            unique_files.add(f"{target_dir}/{filename}")

    delete_directory(dst_path)
    create_directory(dst_path)

    unique_files = list(unique_files)
    for unique_file in unique_files:
        copy_file(unique_file, dst_path)
    

def count_options(file_path):
    if not os.path.exists(file_path):
        return 0, []

    """Detect -option and --option from the file and return the option count and option list"""
    with open(file_path, 'r') as f:
        text = f.read()
    
    options = set(re.findall(r'--?\w+(?:-\w+)*', text))
    return len(options), sorted(options)


def get_empty_id(target_dir, target_cmd, width=3):
    """Return the smallest unused ID under seed_dir/target_cmd.

    Scans the target directory for subdirectories named like
    '{target_cmd}_000', '{target_cmd}_001', etc., and returns the
    smallest unused ID as a zero-padded string, e.g. '002'.
    If the directory does not exist or has no matching subdirectories,
    returns '000'.
    """
    # target_dir = os.path.join(seed_dir, target_cmd)
    if not os.path.exists(target_dir):
        return str(0).zfill(width)

    pattern = re.compile(rf'^{re.escape(target_cmd)}_(\d+)$')
    present_ids = set()
    for name in os.listdir(target_dir):
        if os.path.isdir(os.path.join(target_dir, name)):
            match = pattern.match(name)
            if match:
                present_ids.add(int(match.group(1)))

    if not present_ids:
        return str(0).zfill(width)

    # Find the smallest non-negative integer not in present_ids.
    i = 0
    while i in present_ids:
        i += 1
    return str(i).zfill(width)


def export_to_seed_dir(snap_dir, shell_dir, target_cmd):

    files = get_all_files(snap_dir)
    empty_id = get_empty_id(shell_dir, target_cmd)
    
    # print(files)
    for file_path in files:
        if not file_path.endswith('.sh'):
            continue

        if not os.path.exists(f"{shell_dir}/{target_cmd}_{empty_id}"):
            create_directory(f"{shell_dir}/{target_cmd}_{empty_id}")
            print(f"\nCreated: {shell_dir}/{target_cmd}_{empty_id}")

        copy_file(file_path, f"{shell_dir}/{target_cmd}_{empty_id}")
        print(f"Copied: {file_path}")

    return empty_id


def generate_base_argv(
    shell_dir, base_argv_path,
    process_type, target_dir, database_dir, database_json, target_cmd, directory_id
):

    print("Running c_build.sh ...")
    # run_script(process_type, database_dir, f"{home_dir}/{target_dir}/c_build.sh", 1000, True, None, "both")
    print("")

    prepare_base_argv(
        target_cmd, "all", base_argv_path, process_type, 
        target_dir, database_dir, database_json, shell_dir, directory_id
    )
    

def generate_input_files(
    base_argv_path, dst_path,
    target_cmd, directory_id, llm_interface,
    database_dir, target_dir, transit_dir, database_json, seed_dir
):
    random_string = ""
    input_raw_path = f"{transit_dir}/{target_cmd}_{directory_id}_raw_input.txt"
    input_brashed_path = f"{transit_dir}/{target_cmd}_{directory_id}_brashed_input.txt"

    # Regarding the contents of the txt file that lists candidate command-line arguments, please extract only the input file paths as a txt file, extract them one file path at a time, and list them with a line break in the format Line X. <input file path>.
    change_command_string(
        "input", llm_interface, 
        base_argv_path, input_raw_path, target_cmd, database_dir 
    )

    # Brash up
    brash_up(
        input_raw_path, input_brashed_path, 
        target_cmd, "input"
    )

    prepare_input_files(
        target_cmd, "all", dst_path, input_brashed_path, 
        target_dir, database_json, directory_id
    )
    

def generate_carpet_argv(
    base_argv_path, carpet_argv_path,
    llm_interface, chat_dir, transit_dir, database_dir, target_cmd, directory_id
):

    if os.path.exists(f"{chat_dir}/log_manager.json"):
        delete_file(f"{chat_dir}/log_manager.json")

    raw_path = f"{transit_dir}/{target_cmd}_{directory_id}_raw.txt"
    brashed_path = f"{transit_dir}/{target_cmd}_{directory_id}_brashed.txt"
    
    change_command_string(
        "carpet", llm_interface, 
        base_argv_path, raw_path, target_cmd, database_dir
    )
    
    # Brash up
    brash_up(
        raw_path, brashed_path, 
        target_cmd, "carpet"
    )
    remove_duplicate(brashed_path)
    remove_without_at(brashed_path)

    # output_dir = os.path.dirname(carpet_argv_path)
    # output_filename = os.path.basename(carpet_argv_path)

    os.makedirs(os.path.dirname(carpet_argv_path), exist_ok=True)
    copy_file(brashed_path, carpet_argv_path)


def generate_zigzag_argv(
    base_argv_path, zigzag_argv_path,
    target_cmd
):
    if not os.path.exists(base_argv_path):
        raise ValueError(f"Should prepare {base_argv_path}")
    # insert_line_count(base_argv_path)

    count, options = count_options(base_argv_path)

    os.makedirs(os.path.dirname(zigzag_argv_path), exist_ok=True)
    with open(zigzag_argv_path, 'w') as f:
        for item in options:
            f.write(f"{item}\n")
            

def gen_afl_argv_previous(directory_id, target_cmd, input_path, output_dir):
    print("Generate afl_argv...")
    print(input_path)

    os.makedirs(output_dir, exist_ok=True)
    target_cmd_parts = target_cmd.split()
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_path}")
        return 0
    
    seed_count = 0
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        
        if not line or line.startswith('#'):
            continue
        
        # Skip if the first token is a number (e.g. a line number like "239")
        parts = line.split(maxsplit=1)
        if parts[0].isdigit() and len(parts) > 1:
            command_line = parts[1]
        else:
            command_line = line
        
        # Split the whole command line by target_cmd to handle multiple commands
        commands = command_line.split(target_cmd)
        
        for cmd_idx, cmd in enumerate(commands):
            cmd = cmd.strip()
            if not cmd:
                continue
            
            try:
                args = shlex.split(cmd)
            except ValueError as e:
                print(f"Warning: Failed to parse command: {e}")
                args = cmd.split()
            
            if not args:
                continue
            
            # Create NULL-separated binary data
            argv_data = b''
            for arg in args:
                argv_data += arg.encode('utf-8', errors='replace') + b'\0'
            
            # Generate a file name with a sequential number
            seed_count += 1
            seed_filename = f"seed_{seed_count:04d}.bin"
            seed_path = os.path.join(output_dir, seed_filename)
            
            try:
                with open(seed_path, 'wb') as f:
                    f.write(argv_data)
                
                if seed_count <= 5:
                    print(f"  Created: {seed_filename} with args: {args}")
                    
            except IOError as e:
                print(f"Error: Failed to write seed file {seed_path}: {e}")
                continue
    
    print(f"Successfully generated {seed_count} seed files in {output_dir}")
    return seed_count


def generate_afl_argv(
    input_path, output_dir,
    chat_dir, transit_dir, target_cmd, directory_id
):

    # print(input_path)
    # print(output_dir)

    if os.path.exists(chat_dir):
        delete_directory(chat_dir)
    create_directory(chat_dir)

    if not os.path.exists(input_path):
        print(input_path)
        raise ValueError(f"Should prepare {input_path}")

    pure_cmd = get_pure_cmd(target_cmd)

    brashed_path = f"{transit_dir}/afl_{target_cmd}_{directory_id}_brashed.txt"
    brash_up(
        input_path, brashed_path, 
        target_cmd, "afl"
    )
    delete_first_line(brashed_path)
    
    if os.path.exists(output_dir):
        delete_directory(output_dir)
    create_directory(output_dir)

    gen_afl_argv_previous(directory_id, pure_cmd, brashed_path, output_dir)