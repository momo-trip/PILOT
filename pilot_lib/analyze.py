import os
from typing import NamedTuple

from utils_api import (
    read_json,
    deduplicate_compile_commands,
    create_directory,
)

from c_parser_api import (
    analyze_dependencies,
    parse_all,
)

from pilot_lib.utils import (
    run_script,
    get_metadata,
)

class FunctionId(NamedTuple): # Information to uniquely identify a function"
    name: str
    file_path: str
    line_cov: str
    branch_cov: str

    def __str__(self):
        return f"{self.name} ({self.file_path})"


def search_executable(is_program_path, meta_dir):

    executable = False
    main_list = [] #{} # Handle the case where there are multiple
    program_files = set(read_json(is_program_path))

    for file_path in program_files:
        meta_data, meta_path = get_metadata(file_path, meta_dir, None)
        if meta_data is None: # added
            continue

        for key, item in meta_data.items():
            if item['name'] == 'main':
                executable = True
                main_entry = {}
                main_entry = item.copy()
                main_list.append(main_entry)

    return executable, main_list


def get_compile_commands(process_type, target_dir):
    # Check inside the specified directory
    compile_commands_path = os.path.join(target_dir, "compile_commands.json")
    if os.path.isfile(compile_commands_path):
        if process_type == "gcno":
            deduplicate_compile_commands(f"{target_dir}/compile_commands.json")

        return target_dir
    
    # Search all subdirectories recursively
    for root, dirs, files in os.walk(target_dir):
        if "compile_commands.json" in files:

            if process_type == "gcno":
                deduplicate_compile_commands(f"{root}/compile_commands.json")

            return root
    
    raise ValueError("Did not find compile_commands.json")



def search_main(process_type, target, run_path, dep_json_path, build_path, 
                target_dir, meta_dir, database_dir, ommited_files,
                macro_finder, div_meta_dir, taken_directive_path, unordered_taken_directive_path,
                all_directive_path, is_program_path, all_macros_path, taken_macros_path,
                guards_path, guarded_macros_path, independent_path, flag_path, const_path, global_path):

    print(f"target_dir: {target_dir}")
    print(f"build_path: {build_path}")

    create_directory(meta_dir)

    run_script(process_type, database_dir, build_path, 100000, True, None, "both")

    build_dir = get_compile_commands(process_type, target_dir)
    if process_type == "gcno":
        deduplicate_compile_commands(f"{build_dir}/compile_commands.json")

    print(f"{build_dir}/compile_commands.json")

    analyze_dependencies(target_dir, meta_dir, database_dir, dep_json_path) # Investigate header file inclusion

    # analyze_function(target_dir, func_json_path, prot_json_path, meta_dir, is_program_path, False, dep_json_path, build_dir)
    parse_all("call", target, macro_finder, target_dir, meta_dir, div_meta_dir, database_dir, build_path, 
                 taken_directive_path, unordered_taken_directive_path, all_directive_path, dep_json_path, is_program_path, 
                 all_macros_path, taken_macros_path, guards_path, guarded_macros_path, independent_path, flag_path, const_path,
                 None, None, global_path)

    analyzed_executable, main_list = search_executable(is_program_path, meta_dir)

    print()
    # print(f"analyzed_executable: {analyzed_executable}")
    # print(f"main_list: {main_list}")
    print(f"Count of main functions: {len(main_list)}")

    return analyzed_executable, main_list