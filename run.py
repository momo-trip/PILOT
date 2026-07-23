import atexit
import logging
import os
import random
import shutil
import sys
import time
import traceback
import signal
import threading

from functools import partial

from utils_api import (
    read_json,
    write_json,
    read_file,
    write_file,
    copy_file,
    delete_file,
    create_permissioned_file,
    rename_directory,
    create_directory,
    delete_directory,
    get_last_directory,
    parse_def_loc,
    remove_base_path,
)

from llm_api import (
    LLMInterface,
    init_prompt_count,
    save_coverage_report,
    get_claude_model,
    configure_llm,
    AgentInterface,
)

from c_parser_api import analyze_call_relationship

from pilot_lib.utils import (
    Paths,
    ExplorerConfig,
    run_script,
    get_coverage,
    merge_config,
)

from pilot_lib.tool import find_tool, get_tool_string
from pilot_lib.analyze import search_main
from pilot_lib.graph import (
    analyze_call_dependencies,
    get_related_main,
    build_graph,
    write_metrics,
)
from pilot_lib.generate import (
    check_command_availability,
    ask_basic_command,
    explore_path,
    explore_branch,
    clear_gcda_files,
)

from pilot_lib.reformat import (
    export_to_seed_dir,
    generate_input_files,
    generate_base_argv,
    generate_carpet_argv,
    generate_zigzag_argv,
    generate_afl_argv,
)


FEEDBACK = True 

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


def get_basic_report(
    paths, target, original_target_dir, exec_time, target_cmd,
    process_type, llm_model, strategy, llm_choice,
    fixed_explore_time, temperature, total_time, interval,
    fixed_metric, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION
):
    print("\n====== Getting output report =======")
    log_json = read_json(paths.logging_path)
    if target_cmd not in log_json:
        log_json[target_cmd] = {}

    if 'current_count' not in log_json[target_cmd]:
        log_json[target_cmd]['current_count'] = 1
    
    trial_id = str(log_json[target_cmd]['current_count'])
    log_json[target_cmd]['current_count'] += 1

    write_json(paths.logging_path, log_json)

    result_json = read_json(paths.result_path)

    if result_json is None:
        result_json = {}
    if target_cmd not in result_json:
        result_json[target_cmd] = {}
    if trial_id not in result_json[target_cmd]:
        result_json[target_cmd][trial_id] = {}

    llm = ""
    if process_type in ["gen"]:
        llm = f"_{llm_model}" 
    
    strategy_str = ""
    if process_type == "gen" and strategy != "":
        strategy_str = f"_{strategy}" 
        
    fixed_str = ""
    if fixed_metric is not None:
        fixed_str = f"_{fixed_metric}"
    else:
        fixed_str = ""

    feedback = ''
    if FEEDBACK:
        feedback = 'w_feed'
    else:
        feedback = 'no_feed'

    formatted_id = str(trial_id).zfill(3)
    destination = paths.archive_dir + "/" + target_cmd + "/" f"{formatted_id}_" f"{process_type}" + f"{llm}" +  f"{strategy_str}" + f"_{MIN_LENGTH}" + f"_{fixed_explore_time}" + f"_{feedback}" + f"{fixed_str}"

    # print(paths.chat_dir)
    # print(paths.snap_dir)
    # print(cov_report_path)
    # print(paths.select_path)

    if os.path.exists(paths.chat_dir):
        copy_directory(f"{paths.chat_dir}", destination)
        rename_directory(f"{destination}/{target_cmd}", f"{destination}/chats")

    if os.path.exists(paths.snap_dir):
        copy_directory(f"{paths.snap_dir}", destination)
        rename_directory(f"{destination}/{target_cmd}", f"{destination}/snapdata")

    if os.path.exists(paths.cov_report_path):
        copy_file(paths.cov_report_path, destination)

    if os.path.exists(paths.select_path):
        copy_file(paths.select_path, destination)

    if os.path.exists(f"{paths.database_dir}/cov_increased.json"):
        copy_file(f"{paths.database_dir}/cov_increased.json", destination)

    if os.path.exists(f"{paths.database_dir}/cov_time.csv"):
        copy_file(f"{paths.database_dir}/cov_time.csv", destination)

    if os.path.exists(paths.token_path):
        copy_file(paths.token_path, destination)

    setting_path = f"{destination}/setting.json"
    
    setting = {
        "process_type" : process_type,
        "llm_model" : llm_model,
        "total_time" : total_time,
        "interval" : interval,  # The measurement interval
        "explore_time" : fixed_explore_time, # = 300 #180
        "temperature" : temperature,
        #"explore_fix" : explore_fix,
        "WO_READ" : WO_READ,
        "WO_PATH" : WO_PATH,
        "WO_VALIDATION" : WO_VALIDATION,
    }
    write_json(setting_path, setting)

    total_in = 0
    total_out = 0
    if os.path.exists(paths.token_path):
        token_data = read_json(paths.token_path)
        for item in token_data:
            total_in += item['input_token']
            total_out += item['output_token']

    USD_TO_JPY = 150
    if "claude" in llm_choice:
        total_cost = total_in * 0.0000030 + total_out * 0.0000150
    else:
        total_cost = total_in * 0.0000050 + total_out * 0.0000150
    total_cost_jpy = total_cost * USD_TO_JPY

    print(f"\nTotal cost: {total_cost:.6f} USD, {total_cost_jpy:.2f} JPY\n")

    current_directory = os.getcwd()

    result_json[target_cmd][trial_id]['cwd'] = current_directory
    result_json[target_cmd][trial_id]['exec_time'] = exec_time
    result_json[target_cmd][trial_id]['archive_dir'] = destination
    result_json[target_cmd][trial_id]["process_type"] = process_type

    """
    for key, value in config.items():
        result_json[target_cmd][trial_id][key] = value

    if 'repair_details' not in result_json[target_cmd]:
        result_json[target_cmd][trial_id]['repair_details'] = {}

    if 'input_token' not in result_json[target_cmd]:
        result_json[target_cmd][trial_id]['input_token'] = {}
    
    if 'output_token' not in result_json[target_cmd]:
        result_json[target_cmd][trial_id]['output_token'] = {}
    """

    write_json(paths.result_path, result_json)


will_show = None
def get_final_report(
    paths, process_type, start_time, target_cmd, target, original_target_dir,
    fixed_explore_time, temperature, total_time, interval, 
    fixed_metric, llm_choice, llm_model, strategy,
    MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION
):
    global will_show
    if will_show:
        print("Program ended! Done.")

    end_time = time.time()
    exec_time = end_time - start_time

    get_basic_report(
        paths, target, original_target_dir, exec_time, target_cmd,
        process_type, llm_model, strategy, llm_choice,
        fixed_explore_time, temperature, total_time, interval,
        fixed_metric, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION
    )


def stop_periodic_server():
    global periodic_running
    periodic_running = False
    time.sleep(1)


def set_timeout(
    seconds, start_time, process_type, target_cmd, target, 
    target_dir, original_target_dir, archive_dir, meta_dir, 
    result_path, dep_json_path, logging_path,
    fixed_explore_time, temperature, total_time, interval, 
    fixed_metric, llm_choice, llm_model, strategy,
    chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, 
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
            chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, 
            cov_report_path, select_path, database_dir, token_path,
            config_data
        )
        os._exit(1)  # Terminate the entire process

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)


def copy_directory(source_directory, destination_root, target=None):

    if target != "wireshark-4.0.1":
        # Get only the directory name from source_directory
        source_directory_name = os.path.basename(os.path.normpath(source_directory))
        final_destination = os.path.join(destination_root, source_directory_name) # Build the path of the final destination directory
        shutil.copytree(source_directory, final_destination, dirs_exist_ok=True) # Copy the source directory to the final destination # Set the third argument dirs_exist_ok of shutil.copytree to True to # avoid an error when the destination directory already exists (requires Python 3.8 or higher)

        print(f"Copied {source_directory} to {final_destination}")

    else:
        try:
            # Get only the directory name from source_directory
            source_directory_name = os.path.basename(os.path.normpath(source_directory))
            final_destination = os.path.join(destination_root, source_directory_name)
            
            # Remove the destination if it is a file
            if os.path.exists(final_destination) and not os.path.isdir(final_destination):
                print(f"Warning: Removing file {final_destination} to create directory")
                os.remove(final_destination)
            
            # Create the directory
            os.makedirs(final_destination, exist_ok=True)
            
            # Copy recursively by hand
            for root, dirs, files in os.walk(source_directory):
                # Compute the relative path
                rel_path = os.path.relpath(root, source_directory)
                dest_dir = os.path.join(final_destination, rel_path)
                
                # Create directories that do not exist
                os.makedirs(dest_dir, exist_ok=True)
                
                # Copy the files
                for file in files:
                    try:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(dest_dir, file)
                        
                        # Remove the destination if it is a directory
                        if os.path.isdir(dst_file):
                            print(f"Warning: Removing directory {dst_file} to create file")
                            shutil.rmtree(dst_file)
                        
                        # In the case of a symbolic link
                        if os.path.islink(src_file):
                            link_to = os.readlink(src_file)
                            if os.path.exists(dst_file):
                                os.remove(dst_file)
                            os.symlink(link_to, dst_file)
                            print(f"Created symlink from {dst_file} to {link_to}")
                        # In the case of a regular file
                        elif os.path.isfile(src_file):
                            shutil.copy2(src_file, dst_file)
                    except Exception as file_error:
                        print(f"Warning: Failed to copy {src_file}: {file_error}")
                
            print(f"Copied {source_directory} to {final_destination}")
            
        except Exception as e:
            print(f"Error during copy from {source_directory} to {destination_root}: {e}")
            import traceback
            traceback.print_exc()


def get_fixed_metric(cent):
    fixed_metric = None
    # if cent == "random_t":

    if cent == "close":
        fixed_metric = "closeness_centrality"
        
    elif cent == "page":
        fixed_metric = "pagerank"
        
    elif cent == "bet":
        fixed_metric = "betweenness_centrality"
        
    elif cent == "deg":
        fixed_metric = "degree_centrality"
    
    elif cent == "katz":
        fixed_metric = "katz_centrality"
        
    return fixed_metric


def get_random_id(process_type):
    return ""
    if process_type in ["prepare", "preset", "gcno", "gen_seed", "seed"]:
        return ""
    
    # Get the current UNIX timestamp
    timestamp = int(time.time())
    
    # Combine the last 3 digits of the timestamp with a 3-digit random number
    timestamp_part = timestamp % 1000  # Last 3 digits
    random_part = random.randint(0, 999)  # A random number from 0 to 999
    
    return f"_{timestamp_part:03d}{random_part:03d}"  # 6 digits in total


def get_strategies(strategy, cent):
    
    fixed_metric = None
    WO_READ = False
    WO_PATH = False
    WO_VALIDATION = False
    
    if strategy == "wo_read":
        WO_READ = True
        fixed_metric = get_fixed_metric(cent)  

    elif strategy == "wo_t":
        max_target_func = None

    elif strategy == "wo_v": # without validation
        WO_VALIDATION = True
        fixed_metric = get_fixed_metric(cent)  

    elif strategy == "wo_p": # without path guiding
        WO_READ = True   
        WO_PATH = True #True #False
        fixed_metric = get_fixed_metric(cent)  

    elif strategy == "wo_pv": # without path guiding
        WO_VALIDATION = True 
        WO_READ = True   
        WO_PATH = True
        fixed_metric = get_fixed_metric(cent)  

    elif strategy == "wo_tool": # without tool
        fixed_metric = get_fixed_metric(cent)

    # elif strategy == "random_t":
        
    elif strategy is None: #in ["close", "page", "bet", "deg", "katz"]:
        fixed_metric = get_fixed_metric(cent)
        
    # if strategy not in ["wo_read", "wo_t", "random_t", "topo", "page", "katz", "close", "hy", "wo_p", "wo_pv", "wo_v", "bet", "deg", "wo_k", "wo_tool"]:
    #     raise ValueError('Must within ["wo_read", "wo_t", "random_t", "topo", "page", "katz", "close", "hy", "wo_p", "wo_pv", "wo_v", "bet", "deg", "wo_k", "wo_tool"]')
    
    return fixed_metric, WO_READ, WO_PATH, WO_VALIDATION




def initialize(paths, original_target_dir):

    delete_directory(paths.meta_dir)
    create_directory(paths.meta_dir)

    delete_directory(paths.target_dir)
    delete_directory(paths.work_dir)

    delete_directory(paths.snap_dir)
    create_directory(paths.snap_dir)

    # delete_directory(paths.database_dir)
    # create_directory(paths.database_dir)

    delete_directory(paths.chat_dir)
    create_directory(paths.chat_dir)

    delete_directory(paths.tmp_dir)
    create_directory(paths.tmp_dir)
    
    delete_file(paths.reformed_path)
    delete_file(paths.isolated_path)
    delete_file(paths.callee_path)

    delete_file(f"{paths.database_dir}/flow_moment.txt")
    delete_file(f"{paths.database_dir}/cov_increased.json")

    delete_file(paths.branch_path)
    delete_file(paths.line_path)
    delete_file(paths.priority_path)

    delete_file(paths.select_path)
    # delete_file(paths.is_program_path)

    delete_file(paths.token_path)
    delete_file(f"{paths.cov_report_path}")

    delete_file(paths.time_path)

    write_file(paths.current_cov_path, "")

    init_prompt_count(paths.logging_path)

    if process_type != "prepare" and os.path.exists(paths.preset_dir):
        copy_directory(f"{paths.preset_dir}/workspace_{target_cmd}", "./") 
        copy_directory(f"{paths.preset_dir}/metadata_{target_cmd}", "./") 

        copy_file(f"{paths.preset_dir}/dependencies.json", paths.database_dir) 

        copy_file(f"{paths.preset_dir}/reformed.json", paths.reformed_path)
        copy_file(f"{paths.preset_dir}/isolated.json", paths.isolated_path)
        copy_file(f"{paths.preset_dir}/callee.json", paths.callee_path)
        copy_file(f"{paths.preset_dir}/callee_main.json", paths.callee_main_path)
        
    else:
        copy_directory(original_target_dir, paths.work_dir) 


def explorer_main(target_cmd, process_type, directory_id, home_dir, config):

    #######################################################
    ###### Setup
    #######################################################

    if target_cmd.startswith('openssl'):
        config.interval = 120

    database_json = read_json(config.database_path)
    original_target_dir = database_json[target_cmd]["dir_name"]
    target = get_last_directory(original_target_dir)

    paths = Paths(
        target_cmd=target_cmd,
        process_type=process_type,
        target=target,
        directory_id=directory_id,
        home_dir=home_dir,
        macro_parser_dir=config.macro_parser_dir,
    )

    if config.cent is None:
        # optimal_centrality = read_json(paths.strategy_path)
        config.cent = get_estimated_cent(paths.strategy_path)

    fixed_metric, WO_READ, WO_PATH, WO_VALIDATION = get_strategies(
        config.strategy, config.cent
    )

    #######################################################
    ###### Main pipeline
    #######################################################

    if config.llm_model is None:
        if "claude" in config.llm_choice:
            config.llm_model = get_claude_model(config.llm_choice)

    if config.AGENT is False:
        llm_interface = LLMInterface(
            AGENT=config.AGENT,
            project_id=target,
            occupy_path=paths.occupy_path,
            llm_choice=config.llm_choice,
            llm_model=config.llm_model,
            api_key=config.api_key,
            azure_endpoint=config.azure_endpoint,
            temperature=config.temperature,
            timeout=config.timeout, 
            output_max=config.output_max, #128000, #4000,
            context_window=config.context_window, #1000000,
            history_path=paths.history_path,
            token_path=paths.token_path,
            database_dir=paths.database_dir,
            chat_dir=paths.chat_dir,
            count_path=paths.count_path,
        )
    else:
        work_dir_abs = os.path.abspath(paths.work_dir)
        database_dir_abs = os.path.abspath(paths.database_dir)
 
        if os.path.exists(paths.session_path):
            delete_file(paths.session_path)

        if os.path.exists(paths.cost_path):
            delete_file(paths.cost_path)

        llm_interface = AgentInterface(
            AGENT=config.AGENT,
            project_id=target,
            occupy_path=paths.occupy_path,
            llm_choice=config.llm_choice,
            llm_model=config.llm_model,
            api_key=config.api_key,
            azure_endpoint=config.azure_endpoint,
            work_dir=work_dir_abs,
            # allowed_tools=["Read", "Grep", "Glob", "Edit", "Write"],
            allowed_tools=[
                "Read", "Grep", "Glob", "Bash",
                f"Edit({work_dir_abs}/**)",
                f"Write({work_dir_abs}/**)",
                # f"Bash(bash {run_all_abs})",
                # f"Bash(bash {rust_build_abs})",
                # "Bash(cargo build:*)",
                # "Bash(cargo check:*)",
            ],
            add_dirs=[database_dir_abs], 
            max_turns=50,
            permission_mode="acceptEdits",
            session_path=paths.session_path,
            database_dir=paths.database_dir,
            chat_dir=paths.chat_dir,
            count_path=paths.count_path,
            token_path=paths.token_path,
        )
    
    if process_type in ["prepare", "gen"]: #"preset", "gcno", "exp", "set", "file", "carpet", "zigzag", "afl_argv"]:
        initialize(paths, original_target_dir)

    # Start
    print(f"\n=============== Start of {process_type} ===============\n\n")
    
    will_show = True
    targeted_set = set()
    ommited_files = []

    start_time = time.time()

    try:
        if process_type == "gen":
            atexit.register(partial(get_final_report, paths, 
                process_type, start_time, target_cmd, target, original_target_dir,
                config.fixed_explore_time, config.temperature, config.total_time, config.interval, 
                fixed_metric, config.llm_choice, config.llm_model, config.strategy,
                config.MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION        
            )) 

        if process_type == "tool":
            if not os.path.exists(paths.tool_dir):
                create_directory(paths.tool_dir)

            find_tool(target, target_cmd, paths.target_dir, llm_interface, config.os_version)

        elif process_type == "prepare":
            print("Preparing ...")
            executable = True
            executable, main_list = search_main(
                process_type, target, paths.run_test_path, paths.dep_json_path, paths.build_path, 
                paths.target_dir, paths.meta_dir, paths.database_dir, ommited_files,
                paths.macro_finder, paths.div_meta_dir, paths.taken_directive_path, paths.unordered_taken_directive_path,
                paths.all_directive_path, paths.is_program_path, paths.all_macros_path, paths.taken_macros_path,
                paths.guards_path, paths.guarded_macros_path, paths.independent_path, paths.flag_path, paths.const_path, paths.global_path
            ) 

            print("---------------- Result ----------------")
            main_paths = []
            for entry in main_list:
                def_file_path, def_start_line, _ = parse_def_loc(entry['definition'])
                base_path = remove_base_path(def_file_path, f"{home_dir}/{paths.target_dir}")
                main_paths.append(f"{original_target_dir}/{base_path}")

            if len(main_list) > 1:
                print("-------------")
                for path in main_paths:
                    print(path)
                #raise ValueError("Should avoid using as the target because it has two main functions.")
                print("Should avoid using as the target because it has two main functions.")
            
            elif len(main_list) == 0:
                #raise ValueError("Should avoid using as the target because it has no main function.")
                print("Should avoid using as the target because it has no main function.")

            else:
                for path in main_paths:
                    print(path)

        elif process_type == "preset":
            
            if target_cmd == "gm_old":
                json_data = read_json(f"{home_dir}/metadata_gm_old/workspace_gm_old/GraphicsMagick-1.3.36/utilities/gm_c.json")
                
                for item in json_data:
                    for callee_item in item['callees']:
                        callee_item['def_file_path'] = f"{home_dir}/workspace_gm_old/GraphicsMagick-1.3.36/magick/command.c"
                        callee_item['def_start_line'] = 17493
                        callee_item['def_end_line'] = 17505

                write_json(f"{home_dir}/metadata_gm_old/workspace_gm_old/GraphicsMagick-1.3.36/utilities/gm_c.json", json_data)

            elif target_cmd == "gm":
                json_data = read_json(f"{home_dir}/metadata_gm/workspace_gm/GraphicsMagick-1.3.45/utilities/gm_c.json")
                
                for item in json_data:
                    for callee_item in item['callees']:
                        callee_item['def_file_path'] = f"{home_dir}/workspace_gm/GraphicsMagick-1.3.45/magick/command.c"
                        callee_item['def_start_line'] = 17757
                        callee_item['def_end_line'] = 17769

                write_json(f"{home_dir}/metadata_gm/workspace_gm/GraphicsMagick-1.3.45/utilities/gm_c.json", json_data)

            # get dependencies
            analyze_call_dependencies(
                paths.target_dir, paths.meta_dir, paths.database_dir, paths.is_program_path, paths.reformed_path, paths.isolated_path
            )

            # get call relationship
            analyze_call_relationship(
                paths.meta_dir, paths.callee_path, paths.target_dir, paths.is_program_path
            )

            # get main-function surrounded 
            get_related_main(
                paths.program_dir, database_json, target_cmd, home_dir, config.WEIGHT, 
                paths.work_dir, paths.callee_main_path, paths.callee_path, paths.distance_path, 
                paths.meta_dir, paths.database_dir
            )

            graph_metrics, G = build_graph(paths.callee_path, paths.callee_main_path)
            write_metrics(target_cmd, graph_metrics)

            delete_directory(paths.preset_dir)
            copy_directory(paths.meta_dir, paths.preset_dir)
            copy_file(paths.is_program_path, paths.preset_dir)
            copy_file(paths.dep_json_path, paths.preset_dir)

            copy_file(paths.reformed_path, paths.preset_dir)
            copy_file(paths.isolated_path, paths.preset_dir)
            copy_file(paths.callee_path, paths.preset_dir)
            copy_file(paths.callee_main_path, paths.preset_dir)

        elif process_type == "gcno":
            # paths.work_dir comes from afl's directory with gcno
            delete_directory(paths.work_dir)
            copy_directory(original_target_dir, paths.work_dir)
            run_script(process_type, paths.database_dir, paths.build_path, 10000, True, None, "both")
            copy_directory(paths.work_dir, paths.preset_dir)


        elif process_type == "gen":
            # func_sum = get_func_sum(paths.callee_main_path)
            check_command_availability(paths.tool_json_path, target_cmd, target)
        
            # Set at the start of execution
            set_timeout(
                config.total_time, start_time, process_type, target_cmd, target, 
                paths.target_dir, original_target_dir, paths.archive_dir, paths.meta_dir, 
                paths.result_path, paths.dep_json_path, paths.logging_path,
                config.fixed_explore_time, config.temperature, config.total_time, config.interval, 
                fixed_metric, config.llm_choice, config.llm_model, config.strategy,
                paths.chat_dir, paths.snap_dir, config.MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, 
                paths.cov_report_path, paths.select_path, paths.database_dir, paths.token_path
            ) 
            print(f"Target_dir: {paths.target_dir}")
            create_permissioned_file(paths.run_test_path)

            graph_metrics, G = build_graph(paths.callee_path, paths.callee_main_path)

            error = None
            std_out = None
            cycle = 1
            total_start_time = time.time()
            clear_gcda_files(paths.target_dir)
            tool_string, cmd_self = get_tool_string(paths.tool_json_path, target_cmd, target)

            # Write the first testcase
            ask_basic_command(
                paths, llm_interface, target_cmd, config.cov_target, config.max_num_test, fixed_metric, config.fixed_version_count,
                original_target_dir, database_json, config.max_iterations, tool_string, config.strategy, config.testfile_counter, WO_VALIDATION
            )

            target_function_count = 0
            current_coverage = None

            while(1):
                print(f"Current_coverage: {current_coverage}")
                if current_coverage == 100:
                    break

                elapsed_time = time.time() - total_start_time
                if target_function_count >= config.max_target_func:
                    print(f"Reached {target_function_count} functions, so stopping")
                    minutes = int(elapsed_time // 60)
                    print(f"{elapsed_time:.2f} seconds ({minutes} min) elapsed")
                    break

                if cycle == 1:
                    if config.COUNT_PERIODIC is True:
                        start_periodic_server(
                            process_type, config.strategy, config.interval, paths.target_dir, config.azure_endpoint, target_function_count, 
                            paths.tmp_branch_path, paths.tmp_line_path, paths.tmp_function_path
                        )                

                # Explore pathes
                try:
                    current_coverage, target_entry = explore_path(
                        paths, llm_interface, config.strategy, config.cent, tool_string, config.max_num_test, config.cov_target, current_coverage, targeted_set, target_cmd, 
                        original_target_dir, fixed_metric, config.fixed_version_count, config.fixed_explore_time, config.explore_fix,
                        database_json, error, std_out, graph_metrics, G,
                        WO_READ, WO_PATH, WO_VALIDATION, config.MIN_LENGTH, config.GDB_OPTION, config.testfile_counter
                    ) 
                    print(f"Target_dir: {paths.target_dir}")

                    # # repair branches
                    # target_entry = {
                    #     "target_path": f"{home_dir}/workspace_tiffcp_old/libtiff-git-b51bb/libtiff/tiffiop.h",
                    #     "target_line": 114,
                    #     "target_function": "tiff",
                    #     'target_uncovered_ratio' : 0.2,
                    #     'target_branch' : 2,
                    #     'target_end_line' : 32,
                    #     'explore_time' : 300,
                    #     'original_run_test_path' : paths.run_test_path,
                    # }
                    # TEST = True
                    # if TEST is True:
                    if target_entry['is_covered'] is True and target_entry['is_full_branch_covered'] is False:
                        try:
                            explore_branch(
                                paths, llm_interface, config.strategy, config.cov_target, target_cmd, target_entry, tool_string, fixed_metric,
                                original_target_dir, config.max_num_test, 
                                config.fixed_explore_time, config.explore_fix, config.max_iterations, config.fixed_version_count, config.testfile_counter,
                                WO_READ, WO_PATH, WO_VALIDATION, config.MIN_LENGTH, config.GDB_OPTION,
                                database_json, error, std_out, graph_metrics, G
                            )
                            # current_coverage = explore_branch(
                        except Exception as e:
                            msg = str(e)
                            if "flagged this message for a cybersecurity topic" in msg or "Claude Code returned an error result" in msg:
                                logging.warning(f"Cyber safeguard flagged target {target_cmd}, skipping")
                                continue
                            raise

                except Exception as e:
                    msg = str(e)
                    if "flagged this message for a cybersecurity topic" in msg or "Claude Code returned an error result" in msg:
                        logging.warning(f"Cyber safeguard flagged target {target_cmd}, skipping")
                        continue
                    raise


                branch_coverage, line_coverage, func_coverage = get_coverage(
                    config.cov_target, paths.target_dir, paths.database_dir, paths.branch_path, paths.line_path, paths.function_path, 
                    paths.is_program_path, paths.current_cov_path
                )
                save_coverage_report(config.cov_target, paths.cov_report_path, paths.token_path, branch_coverage, line_coverage, func_coverage, None)

                if config.strategy == "wo_t":
                    print("Finished: WO_TARGET senario done!")
                    sys.exit(0)

                error = None
                std_out = None
                cycle += 1
                target_function_count += 1

        elif process_type == "exp":

            empty_id = export_to_seed_dir(paths.snap_dir, paths.shell_dir, target_cmd)

            print(f"\nNext action:")
            print(f"python3 run.py {target_cmd} set {empty_id}")

        elif process_type == "set": # "car_prepare"  # prepare the set directory

            if not os.path.exists(f"{paths.transit_dir}"):
                create_directory(f"{paths.transit_dir}")
                
            generate_base_argv(
                paths.target_shell_dir, paths.base_argv_path,
                process_type, paths.target_dir, paths.database_dir, database_json, target_cmd, directory_id
            )

            print(f"Input argvs: saved at {paths.base_argv_path}")
        
        elif process_type == "file":

            input_file_dir = f"{paths.seed_dir}/pilot/input/{target_cmd}_{directory_id}"

            generate_input_files(
                paths.base_argv_path, input_file_dir,
                target_cmd, directory_id, llm_interface,
                paths.database_dir, paths.target_dir, paths.transit_dir, database_json, paths.seed_dir
            )

            print(f"\nInput files: saved at {input_file_dir}")


        elif process_type == "carpet":

            carpet_argv_path = f'{paths.seed_dir}/pilot/carpet_argvs/{target_cmd}_{directory_id}.txt'
  
            generate_carpet_argv(
                paths.base_argv_path, carpet_argv_path,
                llm_interface, paths.chat_dir, paths.transit_dir, paths.database_dir, target_cmd, directory_id
            )
            print(f"\nSaved: {carpet_argv_path}")
            

        elif process_type == "zigzag": 

            zigzag_argv_path = f"{paths.seed_dir}/pilot/keyword_dict/list_{target_cmd}_{directory_id}.txt"
            
            generate_zigzag_argv(
                base_argv_path, zigzag_argv_path,
                target_cmd
            )
            print(f"\nSaved: {zigzag_argv_path}")
            
        elif process_type == "afl_argv":

            #input_path = f"{paths.transit_dir}/afl_{target_cmd}_{directory_id}.txt"
            afl_argv_dir = f"{paths.seed_dir}/pilot/afl_argvs/{target_cmd}_{directory_id}"

            generate_afl_argv(
                paths.base_argv_path, afl_argv_dir,
                paths.chat_dir, paths.transit_dir, target_cmd, directory_id
            )

        pass

        print(f"\n=============== End of {process_type} ===============\n\n")

    except SystemExit as e:
        if e.code == 0:
            will_show = True
        else:
            will_show = False
            traceback.print_exc()
    except KeyboardInterrupt:
        will_show = True 
        traceback.print_exc()
    except:
        will_show = False
        traceback.print_exc()
        sys.exit(1)
    


if __name__ == "__main__":

    target_cmd = str(sys.argv[1])
    process_type = str(sys.argv[2]) 

    directory_id = None
    if process_type in ["set", "file", "carpet", "zigzag", "afl_argv"]:
        directory_id = str(sys.argv[3]) 

    home_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = f"{home_dir}/config.json"
    sys_config_path = f"{home_dir}/config_sys.json"

    user_config = read_json(f"{config_path}")
    sys_config = read_json(f"{sys_config_path}")

    config = merge_config(user_config, sys_config)

    try:
        explorer_main(
            target_cmd, process_type, directory_id, home_dir, config
        )  

    except:
        will_show = False
        traceback.print_exc()
        sys.exit(1)
        



"""
python3 run.py tiffcp_old tool
python3 run.py tiffcp_old prepare
python3 run.py tiffcp_old preset
python3 run.py tiffcp_old gcno
python3 run.py tiffcp_old gen

python3 run.py tiffcp_old exp
python3 run.py tiffcp_old set 000
python3 run.py tiffcp_old file 000
python3 run.py tiffcp_old carpet 000
python3 run.py tiffcp_old zig 000
python3 run.py tiffcp_old afl_argv 000
"""
