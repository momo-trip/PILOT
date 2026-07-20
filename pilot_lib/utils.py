import json
import os
import random
import subprocess

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from utils_api import (
    read_json,
    write_json,
    copy_file,
    delete_file,
    create_file,
    get_timestamp,
)


TARGET = "function"

@dataclass
class LineCoverage:
    line_number: int
    is_covered: bool
    execution_count: int

class CoverageData:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lines: Dict[int, LineCoverage] = {}
    
    def add_line(self, line_number: int, execution_count: int):
        self.lines[line_number] = LineCoverage(
            line_number=line_number,
            is_covered=execution_count > 0,
            execution_count=execution_count
        )
    
    def to_dict(self):
        return {
            'file_path': self.file_path,
            'lines': {
                str(line_num): {
                    'line_number': line.line_number,
                    'is_covered': line.is_covered,
                    'execution_count': line.execution_count
                }
                for line_num, line in self.lines.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        coverage = cls(data['file_path'])
        for line_num, line_data in data['lines'].items():
            coverage.add_line(
                int(line_data['line_number']),
                line_data['execution_count']
            )
        return coverage


def separate_output_files(content, moment_flow_path):
    if content is None:  # Added handling for the case where content is None
        return None
        
    moment_flows = []
    main_content = []
    
    # Split the string into lines
    lines = content.split('\n')
    for line in lines:
        if line.startswith('cloned_target'):
            moment_flows.append(line + '\n')
        else:
            main_content.append(line + '\n')
            
    with open(moment_flow_path, 'w') as f:
        f.writelines(moment_flows)
        
    # Join as a string and return
    return ''.join(main_content)


def run_script(
    process_type, database_dir, script_path, timeout, dir_move_flag, execute_log_path, option
):
    
    error_output = None
    std_output = None
    try:
        # Check if file exists
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")
            
        # Check if file is executable
        if not os.access(script_path, os.X_OK):
            # Try to make it executable
            try:
                os.chmod(script_path, 0o755)
            except Exception as e:
                raise PermissionError(f"Cannot make script executable: {e}")
        
        if dir_move_flag is True:
            execute_dir = os.path.dirname(os.path.normpath(script_path))
            script_path = os.path.basename(os.path.normpath(script_path))
        else:
            execute_dir = None

        cmd = ["bash"]
        
        if script_path.startswith("./"):
            cmd.append(script_path)
        else:
            cmd.append(f"./{script_path}")

        if option == "compile":
            cmd.append("--build")
        elif option == "run":
            cmd.append("--run")
        
        print(f"Execute run_script: {script_path} at {execute_dir}")

        # Copy the current environment variables
        env = os.environ.copy()
        env["GCOV_CHECK_STAMP"] = "0" # Add GCOV_CHECK_STAMP=0

        # Execute the script
        if execute_dir is None:
            print("Run with None execute_dir")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False, #shell=True  # Required for shell scripts
                env=env
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                cwd=execute_dir,
                text=True,
                timeout=timeout,
                shell=False, #shell=True  # Required for shell scripts
                env=env
            )

        # Write the execution result to the log
        if execute_log_path is not None:
            print(f"before ({execute_log_path})")
            create_file(execute_log_path)
            with open(execute_log_path, 'w', encoding='utf-8') as f:
                if result.stdout:
                    f.write(result.stdout)
                if result.stderr:
                    f.write(result.stderr)
            print(f"Wrote log file ({execute_log_path})")

        # Check for errors
        std_output = result.stdout if result.stdout is not None and result.stdout != "" else None
        error_output = result.stderr if result.stderr is not None and result.stderr != "" else None
        return_code = result.returncode  # Get return_code here

        print(f"type(result.stdout): {type(result.stdout)}") 
        print(f"type(result.stderr): {type(result.stderr)}") 
        
        if process_type == "explore_path":
            moment_flow_path = f'{database_dir}/flow_moment.txt'
            std_output = separate_output_files(std_output, moment_flow_path)
        
        if error_output and return_code == 0:
            if std_output is None:
                std_output = error_output
            else:
                std_output += "\n" + error_output  # Add with a newline
            error_output = None
        
        if error_output is None and return_code == 1: # Mainly for "initial_testcase"
            error_output = "Return code 1: abnormal termination."
        
        return error_output, std_output

    except subprocess.TimeoutExpired:
        return f"Script execution timed out after {timeout} seconds", std_output
        
    except subprocess.SubprocessError as e:
        return f"Failed to execute script: {str(e)}", std_output
        
    except Exception as e:
        return f"Unexpected error: {str(e)}", std_output



def save_function_coverage_data(function_data, function_path):
    """
    Save the function coverage data in JSON format and display a summary
    
    Args:
        function_data (dict): A dictionary containing the function coverage information
        function_path (str): The destination path for saving the JSON file
        
    Returns:
        float: The average coverage percentage
    """
    # Create the directory if it does not exist
    os.makedirs(os.path.dirname(function_path), exist_ok=True)
    
    # Save the function coverage data as a JSON file
    with open(function_path, 'w') as f:
        json.dump(function_data, f, indent=4)
    
    # Display the coverage summary
    total_functions = function_data["total_functions"]
    covered_functions = function_data["covered_functions"]
    coverage_percent = function_data["coverage_percent"]
    
    print(f"Function Coverage Summary:")
    print(f"  Total Functions: {total_functions}")
    print(f"  Covered Functions: {covered_functions}")
    print(f"  Coverage: {coverage_percent}%")
    
    return coverage_percent


# related_main has not been added
def get_function_coverage(coverage_info_path, target_dir, function_path, is_program_path):
    program_files = set(read_json(is_program_path))

    function_data = {
        "total_functions": 0,
        "covered_functions": 0,
        "coverage_percent": None,
        "files": {}
    }
    
    current_file = None
    
    with open(coverage_info_path, 'r') as f:
        for line in f:
            line = line.strip()
            
            # Get the file name
            if line.startswith('SF:'):
                current_file = line[3:]
                function_data["files"][current_file] = {
                    "file_path": current_file,
                    "total_functions": 0,
                    "covered_functions": 0,
                    "coverage_percent": None,
                    "functions": []
                }
            
            # Parse the function definition (FN:line_number,function_name)
            elif line.startswith('FN:'):
                parts = line[3:].split(',')
                if len(parts) >= 2:
                    try:
                        line_number = int(parts[0])
                        function_name = parts[1]
                        
                        if current_file:
                            function_data["files"][current_file]["functions"].append({
                                "name": function_name,
                                "line_number": line_number,
                                "called": False,
                                "count": 0
                            })
                    except (ValueError, IndexError) as e:
                        print(f"Error: While processing an FN line: {line}, error details: {e}")
                        continue
            
            # Parse the function execution (FNDA:execution_count,function_name)
            elif line.startswith('FNDA:'):
                parts = line[5:].split(',')
                if len(parts) >= 2:
                    try:
                        execution_count = int(parts[0])
                        function_name = parts[1]
                        
                        if current_file:
                            for func in function_data["files"][current_file]["functions"]:
                                if func["name"] == function_name:
                                    func["called"] = execution_count > 0
                                    func["count"] = execution_count
                                    break
                    except (ValueError, IndexError) as e:
                        print(f"Error: While processing an FNDA line: {line}, error details: {e}")
                        continue
    
    # Recalculate the number of functions and the number of called functions for each file from the functions list
    function_total = 0
    covered_total = 0

    for file_path, file_data in function_data["files"].items():
        def_file_path = file_path
            
        for func_item in file_data['functions']:
            file_data["total_functions"] += 1

            if func_item['called'] is True:
                file_data["covered_functions"] += 1


        function_total += file_data["total_functions"]
        covered_total += file_data["covered_functions"]
    
    # Calculate the overall coverage percentage
    function_data["total_functions"] = function_total
    function_data["covered_functions"] = covered_total

    if function_data["total_functions"] > 0:
        function_data["coverage_percent"] = round(
            (function_data["covered_functions"] / function_data["total_functions"]) * 100, 2
        )
    else:
        function_data["coverage_percent"] = 0
    
    # Save to JSON file and Print summary
    average_coverage = save_function_coverage_data(function_data, function_path)
    
    coverage_percent = function_data["coverage_percent"]
    return covered_total, coverage_percent



def save_branch_coverage_data(branch_data, branch_path):

    with open(branch_path, "w") as f:
        json.dump(branch_data, f, indent=4)
    
    # Display the results
    print(f"Branch Coverage: {branch_data['coverage_percent']}%")
    print(f"Total Branches: {branch_data['total_branches']}")
    print(f"Covered Branches: {branch_data['covered_branches']}")
    #print(f"Uncovered Branches: {len(branch_data['uncovered_branches'])}")

    return branch_data['coverage_percent'] / 100


def get_branch_coverage(coverage_info_path, target_dir, branch_path, is_program_path):
    program_files = set(read_json(is_program_path))

    branch_data: Dict[str, Any] = {
        "total_branches": 0,
        "covered_branches": 0,
        "coverage_percent": None,
        "files": {}
    }
    
    current_file = None
    with open(coverage_info_path, 'r') as f:
        for line in f:
            line = line.strip()
            
            # Get the file name
            if line.startswith('SF:'):
                current_file = line[3:]
                branch_data["files"][current_file] = {
                    "file_path" : current_file,
                    "total_branches": 0,
                    "covered_branches": 0,
                    "coverage_percent": None,
                    "branches": []
                }
            
            # Parse the branch coverage information
            # BRDA:line_number,block_number,branch_number,execution_count or -
            # Parse the branch coverage information
            elif line.startswith('BRDA:'):
                branch_data["total_branches"] += 1  # branch_total will be re-obtained later
                
                parts = line[5:].split(',')
                
                # Check whether parts has enough elements
                if len(parts) < 4:
                    print(f"Warning: Invalid BRDA line format: {line}")
                    continue  # Skip this line and move to the next
                
                try:
                    line_number = int(parts[0])
                    block_number = int(parts[1])
                    branch_number = int(parts[2])
                    
                    if parts[3] == '-':
                        execution_count = 0
                        taken = False
                    else:
                        try:
                            execution_count = int(parts[3])
                            taken = execution_count > 0
                        except ValueError:
                            # In the case of a special value (e.g. '1TN:')
                            print(f"Warning: A special branch value was found: {parts[3]} (line: {line})")
                            # If TN: is included, treat it as executed (adjust as needed)
                            if 'TN:' in parts[3]:
                                execution_count = 1  # Provisional value
                                taken = True
                            else:
                                execution_count = 0
                                taken = False
                                
                    if taken:
                        branch_data["covered_branches"] += 1
                            
                    if current_file:
                        branch_data["files"][current_file]["total_branches"] += 1
                        if taken:
                            branch_data["files"][current_file]["covered_branches"] += 1
                                
                        branch_info = {
                            "line_number": line_number,
                            "block": block_number,
                            "branch": branch_number,
                            "taken": taken,
                            "count": execution_count
                        }
                                
                        branch_data["files"][current_file]["branches"].append(branch_info)
                except (ValueError, IndexError) as e:
                    print(f"Error: While processing a BRDA line: {line}, error details: {e}")
                    # Increment an error counter as needed, or log the error for analysis
                    continue  # Skip this line and proceed to the next

    # Calculate the coverage percentage for each file
    branch_total = 0
    covered_total = 0
    for file_path, file_data in branch_data["files"].items():
        if file_path in program_files:
            branch_total += file_data["total_branches"]
            covered_total += file_data["covered_branches"]

        total = file_data["total_branches"]
        covered = file_data["covered_branches"]
        if total > 0:
            file_data["coverage_percent"] = round((covered / total) * 100, 2)
        else:
            file_data["coverage_percent"] = 0
    
    # Calculate the overall coverage percentage
    branch_data["total_branches"] = branch_total
    branch_data["covered_branches"] = covered_total

    if branch_data["total_branches"] > 0:
        branch_data["coverage_percent"] = round(
            (branch_data["covered_branches"] / branch_data["total_branches"]) * 100, 2
        )
    else:
        branch_data["coverage_percent"] = 0
        
    # Save to JSON file and Print summary
    average_coverage = save_branch_coverage_data(branch_data, branch_path)

    return covered_total, branch_data["coverage_percent"]  #average_coverage #branch_data



def parse_function_data(input_string):
    # Input validation
    if not input_string or ':::' not in input_string:
        raise ValueError("Invalid input format. Expected 'function_name:::file_path:::start_line'")
    
    # Split the string at ':::'
    parts = input_string.split(':::')
    if len(parts) != 3:  # Changed from 2 to 3
        raise ValueError("Invalid number of parts. Expected exactly two ':::'")
    
    function_name = parts[0].strip()
    file_path = parts[1].strip()
    start_line = parts[2].strip()
    
    # Validate non-empty parts
    if not function_name or not file_path or not start_line:
        raise ValueError("Function name, file path, and start line must be non-empty")
    
    # Validate start_line is a number
    try:
        start_line = int(start_line)
    except ValueError:
        raise ValueError("Start line must be a number")
    
    return function_name, file_path, start_line



def parse_func_data(input_string):
    # Input validation
    if not input_string or ':::' not in input_string:
        raise ValueError("Invalid input format. Expected 'function_name:::file_path'")
    
    # Split the string at ':::'
    parts = input_string.split(':::')
    if len(parts) != 2:
        raise ValueError("Invalid number of parts. Expected exactly one ':::'")
        
    function_name = parts[0].strip()
    file_path = parts[1].strip()
    
    # Validate non-empty parts
    if not function_name or not file_path:
        raise ValueError("Both function name and file path must be non-empty")
        
    return function_name, file_path


def get_metadata(c_path, meta_dir, path_flag): # , signal
    is_abs_os_path = os.path.isabs(c_path)
    c_path = os.path.abspath(c_path)

    if c_path.endswith(".c"):
        suffix = "_c"
    elif c_path.endswith(".h"):
        suffix = "_h"
    elif c_path.endswith(".sh"):
        suffix = "_sh"
    else:
        suffix = ""
    
    meta_path = meta_dir + "/" + c_path[:-2] + suffix + ".json"

    print(f"Getting metadata from {meta_path}")
    if path_flag is False:
        meta_data = read_json(meta_path)
        return meta_data
    
    elif path_flag is True:
        return meta_path
    
    else:
        meta_data = read_json(meta_path)
        return meta_data, meta_path


def append_list_to_file(filename, data_list):
    """
    Function to save the contents of a list to a text file
    
    Args:
        data_list: The list you want to save
        filename: The output file name
    """
    try:
        with open(filename, 'a', encoding='utf-8') as f:
            for item in data_list:
                # Write each item as a string and add a newline
                f.write(str(item) + '\n')
        print(f"Successfully saved {len(data_list)} items to {filename}")
    except Exception as e:
        print(f"Error saving to file: {e}")


def get_related_data(callee_main_path):
    related_data = read_json(callee_main_path)

    related_ids = []
    for item in related_data:
        related_ids.append(item['function_id'])

    return related_ids


def get_random_void():
    return random.random()


def get_line_coverage(coverage_info_path, directory, line_path, is_program_path) -> Dict[str, CoverageData]:

    line_percent = 0
    coverage_data: Dict[str, CoverageData] = {}

    if not os.path.exists(coverage_info_path):
        return 

    with open(f"{coverage_info_path}", 'r') as f:
        current_file = None
        for line in f:
            line = line.strip()
            if line.startswith('SF:'):
                current_file = line[3:]
                coverage_data[current_file] = CoverageData(current_file)
            elif line.startswith('DA:'):
                try:
                    # Handle special format cases such as "DA:6TN:"
                    da_part = line[3:]
                    if ',' in da_part:
                        line_num_str, count_str = da_part.split(',')
                        line_num = int(line_num_str)
                        count = int(count_str)
                        if coverage_data is not None and current_file is not None:
                            coverage_data[current_file].add_line(line_num, count)
                    else:
                        # Log and skip if there is no comma
                        print(f"WARNING: Skipping malformed line data: {line}")
                except ValueError as e:
                    # Log and skip if a conversion error occurs
                    print(f"WARNING: Could not parse line data: {line}, Error: {e}")
                    continue
        
    # Save to JSON file and Print summary
    line_coverage, line_percent = save_line_coverage_data(coverage_data, line_path, is_program_path)

    return line_coverage, line_percent #average_coverage #coverage_data


def save_line_coverage_data(coverage_data, output_file, is_program_path): #coverage_data: Dict[str, CoverageData], output_file: str):
    
    print("Save coverage data to JSON file")

    existing_data = {
        "total_lines" : None,
        "covered_lines" : None,
        "files" : {}
    }

    for file_path, coverage in coverage_data.items():
        if file_path not in existing_data:
            existing_data["files"][file_path] = {
                "file_path": file_path,
                "total_lines" : None,
                "covered_lines" : None,
                "coverage_percent" : None,
                "lines": {}
            }

        for line_num, line_coverage in coverage.lines.items():
            line_info = {
                'line_number': line_coverage.line_number,
                'is_covered': line_coverage.is_covered,
                'execution_count': line_coverage.execution_count
            }
            
            if str(line_num) not in existing_data["files"][file_path]["lines"]:
                existing_data["files"][file_path]["lines"][str(line_num)] = []
            #existing_data["files"][file_path]["lines"][str(line_num)].append(line_info)
            existing_data["files"][file_path]["lines"][str(line_num)] = line_info

    """Print coverage information for all files and average coverage"""
    total_lines = 0
    total_covered_lines = 0
    
    program_files = set(read_json(is_program_path))
    for file_path, coverage in coverage_data.items():
        print(f"\nFile: {file_path}")
        
        file_total_lines = 0
        file_covered_lines = 0
        
        for line_num in sorted(coverage.lines.keys()):
            line = coverage.lines[line_num]
            status = "covered" if line.is_covered else "uncovered"

            file_total_lines += 1
            if line.is_covered:
                file_covered_lines += 1
        
        # Calculate the coverage percentage for each file
        if file_total_lines > 0:
            file_coverage_percent = (file_covered_lines / file_total_lines) * 100
            print(f"Coverage of {file_path}: {file_coverage_percent:.2f}%")
        
        existing_data["files"][file_path]["total_lines"] = file_total_lines
        existing_data["files"][file_path]["covered_lines"] = file_covered_lines
        existing_data["files"][file_path]["coverage_percent"] = file_coverage_percent

        # Add to the overall statistics
        if file_path in program_files: 
            total_lines += file_total_lines
            total_covered_lines += file_covered_lines
        
    # Calculate the overall coverage percentage
    average_coverage = 0
    if total_lines > 0:
        average_coverage = (total_covered_lines / total_lines) * 100
        print(f"\nAverage coverage of all files: {average_coverage:.2f}%")
        print(f"Total lines: {total_lines}, covered lines: {total_covered_lines}")

    existing_data["total_lines"] = total_lines
    existing_data["covered_lines"] = total_covered_lines

    with open(output_file, 'w') as f:
        json.dump(existing_data, f, indent=4)

    return total_covered_lines, average_coverage  #average_coverage / 100


def get_coverage(target_dir, database_dir, branch_path, line_path, function_path, is_program_path, current_cov_path):
    
    delete_file(line_path)
    delete_file(branch_path)

    random = get_random_void()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    timestamp = f"{timestamp}_{random}"

    # Generate coverage information including branch coverage with lcov
    coverage_info_path = f"{database_dir}/coverage_{timestamp}.info" 

    try:
        subprocess.run(
            [
                "lcov", "--capture", "--directory", target_dir,
                "--output-file", coverage_info_path,
                "--rc", "lcov_branch_coverage=1"  # Enable branch coverage
            ],
            check=True,
            #stderr=subprocess.PIPE,
            stderr=subprocess.DEVNULL,    # Added
            stdout=subprocess.DEVNULL,    # Added
            timeout=None #600 #240 # 30
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: lcov command timed out")
        return 0, 0, 0  # {"error": "lcov command timed out", "total_branches": 0, "covered_branches": 0, "files": {}}
    except subprocess.CalledProcessError as e:
        print(f"Error running lcov: {e.stderr.decode()}")
        return 0, 0, 0  # Fixed the return value

    # line coverage # This means coverage_data will be the latest one. # Parse coverage data
    line_coverage, line_percent = get_line_coverage(coverage_info_path, target_dir, line_path, is_program_path)
    
    # branch coverage
    branch_coverage, branch_percent = get_branch_coverage(coverage_info_path, target_dir, branch_path, is_program_path)

    # function coverage
    function_coverage, coverage_percent = get_function_coverage(coverage_info_path, target_dir, function_path, is_program_path) 

    # Update here
    if os.path.exists(coverage_info_path):
        copy_file(coverage_info_path, current_cov_path)
    
    delete_file(coverage_info_path)

    global current_coverage
    if TARGET == "function":
        current_coverage = coverage_percent #function_coverage
    elif TARGET == "branch":
        current_coverage = branch_coverage

    print("++++++++++++++++++++")
    print(f'{branch_coverage} ({branch_percent} %)')
    print(f'{line_coverage} ({line_percent:.2f} %)')
    print(f'{function_coverage} ({coverage_percent} %)')
    print("++++++++++++++++++++")

    return branch_coverage, line_coverage, function_coverage


def get_is_covered(target_entry, cov_path, target_dir, cov_type): 

    print(f"\nTarget entry: {target_entry}")
    file_path = target_entry['target_path']
    target_function = target_entry['target_function']
    target_line = target_entry['target_line']
    target_branch = target_entry['target_branch']
    target_uncovered_ratio = target_entry['target_uncovered_ratio']
    abs_path = os.path.abspath(file_path)

    is_covered = None
    if cov_type == "function":
        if os.path.exists(cov_path):
            with open(cov_path, 'r') as f:
                coverage_data = json.load(f)
            
            if abs_path not in coverage_data['files']:
                print(f"Error: No coverage data found for {abs_path}")
                return None
                
            file_coverage = coverage_data['files'][abs_path]
            for function in file_coverage['functions']:
                if function['name'] == target_function:
                    is_covered = function['called']
                    return is_covered
            
            print(f"Error: Function {target_function} not found in coverage data")
            return False
            
        return None

    elif cov_type == "branch":
        try:
            with open(cov_path, 'r') as f:
                coverage_data = json.load(f)
            
            if abs_path not in coverage_data['files']:
                print(f"Error: No coverage data found for {abs_path}")
                return None
                
            file_coverage = coverage_data['files'][abs_path]

            total_branches = []
            uncovered_branches = []

            for branch in file_coverage['branches']:
                if branch['line_number'] == target_line:
                    total_branches.append(branch)
                    if not branch["taken"]:
                        uncovered_branches.append(branch)
                    """
                    is_covered = branch['taken']
                    return is_covered
                    """
        
            uncovered_ratio = len(uncovered_branches) / len(total_branches) if len(total_branches) > 0 else 0
            if uncovered_ratio < target_uncovered_ratio:
                is_covered = True
            else:
                is_covered = False
            return is_covered

        except FileNotFoundError:
            print("Error: coverage_details.json not found")
            return None
        except json.JSONDecodeError:
            print("Error: Invalid JSON format in coverage_details.json")
            return None
        except Exception as e:
            print(f"Error while finding uncovered line: {str(e)}")
            return None
        
    elif cov_type == "line":
        print(f"\nTarget entry: {target_entry}")
        file_path = target_entry['target_path']
        target_line = target_entry['target_line']

        try:
            with open(cov_path, 'r') as f:
                coverage_data = json.load(f)
            
            abs_path = os.path.abspath(file_path)
            
            if abs_path not in coverage_data['files']:
                print(f"Error: No coverage data found for {abs_path}")
                return None
                
            file_coverage = coverage_data['files'][abs_path]
            
            # Check the coverage status of a specific line
            line_key = str(target_line) 
            if line_key in file_coverage['lines']:
                coverage_dict = file_coverage['lines'][line_key]
                return coverage_dict['is_covered']  # Return is_covered of the last element of the list
            return None

        except FileNotFoundError:
            print("Error: coverage_details.json not found")
            return None
        except json.JSONDecodeError:
            print("Error: Invalid JSON format in coverage_details.json")
            return None
        except Exception as e:
            print(f"Error while finding uncovered line: {str(e)}")
            return None

def write_testcase(run_test_path, snap_dir, timestamp):
    file_path = f"{snap_dir}/{timestamp}.sh"
    copy_file(run_test_path, file_path)

    return file_path


def get_is_increased(database_dir, target_entry, previous_coverage, current_coverage, cov_type):

    print(f"\nTarget entry: {target_entry}")
    file_path = target_entry['target_path']
    target_line = target_entry['target_line']
    target_branch = target_entry['target_branch']
    target_function = target_entry['target_function']

    is_increased = False
    print()
    if previous_coverage is None or current_coverage is None: 
        print(f"previous_coverage: {previous_coverage}")
        print(f"current_coverage: {current_coverage}")
        raise ValueError("Error in get_is_increased()")

    print(f"previous_coverage: {previous_coverage}")
    print(f"current_coverage: {current_coverage}")

    is_increased = None
    diff = None
    if previous_coverage < current_coverage:
        is_increased = True
        diff = current_coverage - previous_coverage
    else:
        diff = 0

    increased = []
    if os.path.exists(f"{database_dir}/cov_increased.json"):
        increased = read_json(f"{database_dir}/cov_increased.json")

    timestamp = get_timestamp()
    increased.append({
        "timestamp" : timestamp,
        "file_path" : file_path,
        "target_function" : target_function,
        "line_number" : target_line,
        "cov_type" : cov_type, 
        #"branch" : target_branch,
        "is_increased" : is_increased,
        "previous_coverage" : previous_coverage,
        "current_coverage" : current_coverage,
        "diff" : diff
    })

    write_json(f"{database_dir}/cov_increased.json", increased)

    return is_increased, diff


def run_cov_script(
    process_type, run_test_path, entry, branch_path, line_path, function_path, 
    target_dir, database_dir, snap_dir, tmp_dir, 
    initial_coverage, function_branch_path, is_program_path, current_cov_path): # option # timeout, dir_move_flag, option, 
    print("run_cov_script...")

    # setup cov file
    if TARGET == "function":
        cov_type_path = function_path
    if TARGET == "branch":
        cov_type_path = branch_path
    if TARGET == "line":
        cov_type_path = line_path

    delete_file(cov_type_path)

    error, std_out = run_script(process_type, database_dir, run_test_path, 30, True, None, "both")  # , 10000

    branch_coverage, line_coverage, function_coverage = get_coverage(target_dir, database_dir, branch_path, line_path, function_path, is_program_path, current_cov_path)

    if TARGET == "function":
        current_coverage = function_coverage

    elif TARGET == "branch":
        current_coverage = branch_coverage

    is_covered = None
    is_covered = get_is_covered(entry, cov_type_path, target_dir, TARGET)
    
    if is_covered is None:
        print("cov_type_path")
        print(cov_type_path)

    is_increased, diff = get_is_increased(database_dir, entry, initial_coverage, current_coverage, "function")

    timestamp = get_timestamp()
    original_run_test_path = write_testcase(run_test_path, snap_dir, timestamp)

    delete_file(function_branch_path)
    copy_file(function_path, function_branch_path)


    write_json(f"{tmp_dir}/target_{timestamp}.json", entry)
    copy_file(f"{tmp_dir}/target_{timestamp}.json", snap_dir)

    copy_file(branch_path, f"{tmp_dir}/cov_branch_{timestamp}.json")
    copy_file(line_path, f"{tmp_dir}/cov_line_{timestamp}.json")
    copy_file(function_path, f"{tmp_dir}/cov_function_{timestamp}.json")

    copy_file(f"{tmp_dir}/cov_branch_{timestamp}.json", snap_dir)
    copy_file(f"{tmp_dir}/cov_line_{timestamp}.json", snap_dir)
    copy_file(f"{tmp_dir}/cov_function_{timestamp}.json", snap_dir)

    delete_file(f"{tmp_dir}/target_{timestamp}.json")

    delete_file(f"{tmp_dir}/cov_branch_{timestamp}.json")
    delete_file(f"{tmp_dir}/cov_line_{timestamp}.json")
    delete_file(f"{tmp_dir}/cov_function_{timestamp}.json")

    return error, std_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp, original_run_test_path  #, is_covered
    


def run_branch_cov_script(
    process_type, run_test_path, entry, branch_path, line_path, function_path, is_program_path,
    target_dir, database_dir, snap_dir, tmp_dir, 
    initial_coverage, function_branch_path
):
    print("run_branch_cov_script...")

    branch_coverage = None
    line_coverage = None
    function_coverage = None

    # clear gcda and gcov files
    cov_type_path = branch_path
    delete_file(cov_type_path)

    error, std_out = run_script(process_type, database_dir, run_test_path, 30, True, None, "both")  # , 10000

    delete_file(branch_path)

    random = get_random_void()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    timestamp = f"{timestamp}_{random}"

    # Generate coverage information including branch coverage with lcov
    coverage_info_path = f"{database_dir}/coverage_{timestamp}.info" 
    #coverage_info_path = f"{database_dir}/coverage.info" 
    try:
        subprocess.run(
            [
                "lcov", "--capture", "--directory", target_dir,
                "--output-file", coverage_info_path,
                "--rc", "lcov_branch_coverage=1"
            ],
            check=True,
            #stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=None #600 #240 # 30
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: lcov command timed out")

    except subprocess.CalledProcessError as e:
        print(f"Error running lcov: -")

    # branch coverage
    branch_coverage, branch_percent = get_branch_coverage(coverage_info_path, target_dir, branch_path, is_program_path)

    print("++++++++++++++++++++")
    print(f'{branch_coverage} ({branch_percent} %)')
    #print(f'{line_coverage} ({line_percent:.2f} %)')
    #print(f'{function_coverage} ({coverage_percent} %)')
    print("++++++++++++++++++++")

    current_coverage = branch_coverage
    is_covered = None

    is_covered = get_is_covered(entry, cov_type_path, target_dir, "branch")
    if is_covered is None:
        print("cov_type_path")
        print(cov_type_path)

    is_increased, diff = get_is_increased(database_dir, entry, initial_coverage, current_coverage, "branch")

    timestamp = get_timestamp()
    original_run_test_path = write_testcase(run_test_path, snap_dir, timestamp)

    delete_file(function_branch_path)
    copy_file(function_path, function_branch_path)

    write_json(f"{tmp_dir}/target_{timestamp}.json", entry)
    copy_file(f"{tmp_dir}/target_{timestamp}.json", snap_dir)

    copy_file(branch_path, f"{tmp_dir}/cov_branch_{timestamp}.json")
    copy_file(f"{tmp_dir}/cov_branch_{timestamp}.json", snap_dir)

    delete_file(f"{tmp_dir}/target_{timestamp}.json")
    delete_file(f"{tmp_dir}/cov_branch_{timestamp}.json")
    delete_file(coverage_info_path)

    return error, std_out, is_covered, is_increased, diff, current_coverage, branch_coverage, line_coverage, function_coverage, timestamp  #, is_covered
    

def parse_function_id(caller): #def get_info(caller):
    """
    Parse a function identifier to extract file path and start line.
    
    Args:
        caller (str): Function identifier in formats like:
                      "function_name@/path/to/file.c:33" or
                      "function_name@path/to/file.c:33"
    
    Returns:
        tuple: (file_path, start_line) where:
               file_path is the extracted file path or None if not found
               start_line is the extracted line number as int or None if not found
    """
    file_path = None
    start_line = None
    name = None

    # Check if the caller contains '@' which separates function name from path
    if '@' in caller:
        # Split at '@' to get the part containing path and line number
        parts = caller.split('@', 1)
        path_line_part = parts[1]
        name = parts[0]

        # Check if the path part contains ':' which separates path from line number
        if ':' in path_line_part:
            # Split at ':' to separate path and line number
            path_parts = path_line_part.rsplit(':', 1)
            file_path = path_parts[0]
            
            # Try to convert line number to int
            try:
                start_line = int(path_parts[1])
            except ValueError:
                # Line number is not a valid integer
                start_line = None
        
        if '@' in path_line_part:
            # Split at ':' to separate path and line number
            path_parts = path_line_part.rsplit('@', 1)
            file_path = path_parts[0]
            
            # Try to convert line number to int
            try:
                start_line = int(path_parts[1])
            except ValueError:
                # Line number is not a valid integer
                start_line = None
    
    return name, file_path, start_line


def get_metrics(item, graph_metrics):

    target_function_id = f"{item['name']}@{item['def_file_path']}:{item['def_start_line']}"
    
    # """Function to get the centrality metrics of a specific function"""
    result = {
        "in_degree": graph_metrics["in_degree"].get(target_function_id, 0),
        "out_degree": graph_metrics["out_degree"].get(target_function_id, 0),
        "degree_centrality": graph_metrics["degree_centrality"].get(target_function_id, 0),
        "betweenness_centrality": graph_metrics["betweenness_centrality"].get(target_function_id, 0),
        "pagerank": graph_metrics["pagerank"].get(target_function_id, 0),
        "eigenvector_centrality": graph_metrics["eigenvector_centrality"].get(target_function_id, 0),
        "closeness_centrality": graph_metrics["closeness_centrality"].get(target_function_id, 0),
        "katz_centrality": graph_metrics["katz_centrality"].get(target_function_id, 0),  
        "combined_score": graph_metrics["combined_score"].get(target_function_id, 0)
    }
    
    return result

