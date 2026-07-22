import atexit
import logging
import os
import random
import shutil
import sys
import time
import traceback

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
    run_script,
    get_coverage,
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
    set_timeout,
    start_periodic_server,
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

############################################
#### configurations
############################################

FEEDBACK = True 
SURROUND = True  #False #True imposes more constraints


def get_basic_report(target, target_dir, original_target_dir, archive_dir, result_path, dep_json_path,
                    meta_dir, exec_time, logging_path, target_cmd,
                    process_type, llm_model, strategy, llm_choice,
                    fixed_explore_time, temperature, total_time, interval, 
                    fixed_metric, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
                    chat_dir, snap_dir,
                    cov_report_path, select_path, database_dir, token_path,
                    config_data
):
    print("\n====== Getting output report =======")
    last_dir = os.path.basename(target)
    last_dir = target_cmd
    log_json = read_json(logging_path)
    if last_dir not in log_json:
        log_json[last_dir] = {}

    if 'current_count' not in log_json[last_dir]:
        log_json[last_dir]['current_count'] = 1
    
    trial_id = str(log_json[last_dir]['current_count'])
    log_json[last_dir]['current_count'] += 1

    write_json(logging_path, log_json)

    result_json = read_json(result_path)

    if result_json is None:
        result_json = {}
    if last_dir not in result_json:
        result_json[last_dir] = {}
    if trial_id not in result_json[last_dir]:
        result_json[last_dir][trial_id] = {}

    llm = ""
    if process_type in ["core"]:
        llm = f"_{llm_model}" 
    
    strategy_str = ""
    if process_type == "core" and strategy != "":
        strategy_str = f"_{strategy}" 
        
    if SURROUND:
        sur = "T"
    else:
        sur = "F"
    
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
    destination = archive_dir + "/" + last_dir + "/" f"{formatted_id}_" f"{process_type}" + f"{llm}" +  f"{strategy_str}" + f"_{sur}" + f"_{MIN_LENGTH}" + f"_{fixed_explore_time}" + f"_{feedback}" + f"{fixed_str}" # + f"_{trial_id}" # + f"_{included}"

    # print(chat_dir)
    # print(snap_dir)
    # print(cov_report_path)
    # print(select_path)

    if os.path.exists(chat_dir):
        copy_directory(f"{chat_dir}", destination)
        rename_directory(f"{destination}/{target_cmd}", f"{destination}/chats")

    if os.path.exists(snap_dir):
        copy_directory(f"{snap_dir}", destination)
        rename_directory(f"{destination}/{target_cmd}", f"{destination}/snapdata")

    if os.path.exists(cov_report_path):
        copy_file(cov_report_path, destination)

    if os.path.exists(select_path):
        copy_file(select_path, destination)

    if os.path.exists(f"{database_dir}/cov_increased.json"):
        copy_file(f"{database_dir}/cov_increased.json", destination)

    if os.path.exists(f"{database_dir}/cov_time.csv"):
        copy_file(f"{database_dir}/cov_time.csv", destination)

    if os.path.exists(token_path):
        copy_file(token_path, destination)

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
        "SURROUND" : SURROUND,
    }
    write_json(setting_path, setting)

    total_in = 0
    total_out = 0
    if os.path.exists(token_path):
        token_data = read_json(token_path)
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

    result_json[last_dir][trial_id]['cwd'] = current_directory
    result_json[last_dir][trial_id]['exec_time'] = exec_time
    result_json[last_dir][trial_id]['archive_dir'] = destination
    result_json[last_dir][trial_id]["process_type"] = process_type

    for key, value in config_data.items():
        result_json[last_dir][trial_id][key] = value

    if 'repair_details' not in result_json[last_dir]:
        result_json[last_dir][trial_id]['repair_details'] = {}

    if 'input_token' not in result_json[last_dir]:
        result_json[last_dir][trial_id]['input_token'] = {}
    
    if 'output_token' not in result_json[last_dir]:
        result_json[last_dir][trial_id]['output_token'] = {}
    
    write_json(result_path, result_json)


will_show = None
def get_final_report(target_dir, process_type, start_time, original_target_dir, 
                    archive_dir, result_path, dep_json_path, meta_dir, logging_path, target_cmd, target,
                    fixed_explore_time, temperature, total_time, interval, 
                    fixed_metric, llm_choice, llm_model, strategy,
                    chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
                    cov_report_path, select_path, database_dir, token_path,
                    config_data):

    global will_show
    if will_show:
        print("Program ended! Done.")

    end_time = time.time()
    exec_time = end_time - start_time

    get_basic_report(target, target_dir, original_target_dir, archive_dir, result_path, dep_json_path,
                    meta_dir, exec_time, logging_path, target_cmd,
                    process_type, llm_model, strategy, llm_choice,
                    fixed_explore_time, temperature, total_time, interval, 
                    fixed_metric, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
                    chat_dir, snap_dir,
                    cov_report_path, select_path, database_dir, token_path,
                    config_data)


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


def get_fixed_metric(strategy):
    fixed_metric = None
    # if strategy == "random_t":

    if strategy == "close":
        fixed_metric = "closeness_centrality"
        
    elif strategy == "page":
        fixed_metric = "pagerank"
        
    elif strategy == "bet":
        fixed_metric = "betweenness_centrality"
        
    elif strategy == "deg":
        fixed_metric = "degree_centrality"
    
    elif strategy == "katz":
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


def get_strategies(strategy, optimal_centrality):
    
    fixed_metric = None
    WO_READ = False
    WO_PATH = False
    WO_VALIDATION = False
    
    if strategy == "wo_read":
        WO_READ = True
        fixed_metric = get_fixed_metric(optimal_centrality)  

    elif strategy == "wo_t":
        max_target_func = None

    elif strategy == "wo_v": # without validation
        WO_VALIDATION = True
        fixed_metric = get_fixed_metric(optimal_centrality)  

    elif strategy == "wo_p": # without path guiding
        WO_READ = True   
        WO_PATH = True #True #False
        fixed_metric = get_fixed_metric(optimal_centrality)  

    elif strategy == "wo_pv": # without path guiding
        WO_VALIDATION = True 
        WO_READ = True   
        WO_PATH = True
        fixed_metric = get_fixed_metric(optimal_centrality)  

    elif strategy == "wo_tool": # without tool
        fixed_metric = get_fixed_metric(optimal_centrality)

    # elif strategy == "random_t":
        
    elif strategy in ["close", "page", "bet", "deg", "katz"]:
        fixed_metric = get_fixed_metric(strategy)
        
    if strategy not in ["wo_read", "wo_t", "random_t", "topo", "page", "katz", "close", "hy", "wo_p", "wo_pv", "wo_v", "bet", "deg", "wo_k", "wo_tool"]:
        raise ValueError('Must within ["wo_read", "wo_t", "random_t", "topo", "page", "katz", "close", "hy", "wo_p", "wo_pv", "wo_v", "bet", "deg", "wo_k", "wo_tool"]')
    
    return fixed_metric, WO_READ, WO_PATH, WO_VALIDATION



def initialize(original_target_dir, meta_dir, target_dir, work_dir, snap_dir, database_dir, 
               chat_dir, tmp_dir, preset_dir, all_struct_path, all_typedef_path, 
               type_json_path, func_json_path, prot_json_path, reformed_path, isolated_path, 
               callee_path, callee_main_path, func_used_path, branch_path, line_path, periodic_path, logging_path, 
               priority_path, select_path, is_program_path, token_path, cov_report_path, time_path, process_type, target_cmd):

    delete_directory(meta_dir)
    create_directory(meta_dir)

    delete_directory(target_dir)
    delete_directory(work_dir)
    delete_directory("coverage")

    delete_directory(snap_dir)
    create_directory(snap_dir)

    delete_file(f"{database_dir}/passed_tests.txt")

    # delete_directory(database_dir)
    # create_directory(database_dir)

    delete_directory(chat_dir)
    create_directory(chat_dir)

    delete_directory(tmp_dir)
    create_directory(tmp_dir)

    delete_file(all_struct_path)
    delete_file(all_typedef_path)
    delete_file(type_json_path)

    write_json(all_struct_path, [])
    write_json(all_typedef_path, [])
    write_json(type_json_path, [])
    
    delete_file(func_json_path)
    delete_file(prot_json_path)

    delete_file(reformed_path)
    delete_file(isolated_path)
    delete_file(callee_path)

    delete_file(f"{database_dir}/flow_moment.txt")
    delete_file(f"{database_dir}/cov_increased.json")

    delete_file(func_used_path)

    delete_file(branch_path)
    delete_file(line_path)
    delete_file(periodic_path)
    delete_file(priority_path)

    delete_file(select_path)
    # delete_file(is_program_path)

    delete_file(token_path)
    delete_file(f"{cov_report_path}")

    delete_file(time_path)

    init_prompt_count(logging_path)

    if process_type != "prepare" and os.path.exists(preset_dir):
        copy_directory(f"{preset_dir}/workspace_{target_cmd}", "./") 
        copy_directory(f"{preset_dir}/metadata_{target_cmd}", "./") 

        copy_file(f"{preset_dir}/dependencies.json", database_dir) 

        copy_file(f"{preset_dir}/functions.json", func_json_path)
        copy_file(f"{preset_dir}/prototypes.json", prot_json_path)

        copy_file(f"{preset_dir}/reformed.json", reformed_path)
        copy_file(f"{preset_dir}/isolated.json", isolated_path)
        copy_file(f"{preset_dir}/callee.json", callee_path)
        copy_file(f"{preset_dir}/callee_main.json", callee_main_path)
        
    else:
        copy_directory(original_target_dir, work_dir) 


def explorer_main(config):

    #######################################################
    ###### Setup
    #######################################################

    target_cmd       = config["target_cmd"]
    process_type     = config["process_type"]
    llm_choice       = config["llm_choice"]
    api_key          = config["api_key"]
    azure_endpoint   = config["azure_endpoint"]
    max_target_func  = config["max_target_func"]
    total_time       = config["total_time"]
    interval         = config["interval"]
    cov_target       = config["cov_target"] 
    fixed_explore_time = config["fixed_explore_time"]
    fixed_version_count = config["fixed_version_count"]
    explore_time     = config["explore_time"]
    temperature      = config["temperature"]
    max_num_test     = config["max_num_test"]
    max_iterations   = config["max_iterations"]
    home_dir         = config["home_dir"]
    directory_id     = config["directory_id"]
    config_path      = config["config_path"]
    macro_parser_dir = config["macro_parser_dir"]
    # explore_fix    = config["explore_fix"]
    
    TESTFILE_COUNTER = config["TESTFILE_COUNTER"]
    AGENT            = config["AGENT"]
    COUNT_PERIODIC   = config["COUNT_PERIODIC"]
    WEIGHT           = config["WEIGHT"]

    if target_cmd.startswith('openssl'):
        interval = 120

    macro_finder = f"{macro_parser_dir}/macro_finder/build/macro-finder"
    database_path = 'database.json'
    occupy_path = "instances.json"
    strategy_path = 'strategy.json'

    explore_fix = "t" # True
    strategy = ""
    fixed_metric = None
    WO_READ = False
    WO_PATH = False
    WO_VALIDATION = False
    
    GDB_OPTION = False
    MIN_LENGTH = False

    database_json = read_json(database_path)
    optimal_centrality = read_json(strategy_path)

    if len(sys.argv) > 5:
        strategy = str(sys.argv[5])
        fixed_metric, WO_READ, WO_PATH, WO_VALIDATION = get_strategies(strategy, optimal_centrality[target_cmd])
    
    original_target_dir = database_json[target_cmd]["dir_name"]
    target = get_last_directory(original_target_dir)

    #######################################################
    ###### Paths
    #######################################################

    work_dir = f"workspace_{target_cmd}" 
    meta_dir = f"metadata_{target_cmd}"
    div_meta_dir = f"div_metadata_{user_id}/{target}"

    database_dir = f'database/{target_cmd}'  
    preset_dir = f"preset/{target_cmd}" 
    persistent_dir = f"persistent/{target_cmd}"
    chat_dir = f"chats_{process_type}/{target_cmd}"
    snap_dir = f"snapdata/{target_cmd}"
    tmp_dir = f"tmp/{target_cmd}"
    archive_dir = f"archive/{target_cmd}"
    tool_dir = f"tools/{target_cmd}"
    log_dir = f"log/{target_cmd}"
    seed_dir = f"seeds"
    transit_dir = f"{home_dir}/transit"

    logging_path = f'{persistent_dir}/log_manager.json'
    history_path = f'{database_dir}/chat_history.json'
    dep_json_path = f"{database_dir}/dependencies.json"
    call_json_path = f"{database_dir}/calls.json"
    callee_path = f"{database_dir}/callee.json"
    isolated_path = f"{database_dir}/isolated.json"
    reformed_path = f"{database_dir}/reformed.json"

    cov_json_path = f"{database_dir}/coverages.json"
    result_path = f"{database_dir}/result.json"

    branch_path = f"{database_dir}/cov_branch.json" 
    line_path = f"{database_dir}/cov_line.json" 
    function_path = f"{database_dir}/cov_function.json" 

    periodic_path = f"{database_dir}/cov_periodic.json"
    priority_path = f"{database_dir}/cov_priority.json"
    select_path = f"{database_dir}/cov_select.json"
    cov_report_path = f"{database_dir}/cov_report.json"

    callee_main_path = f"{database_dir}/callee_main.json"
    distance_path = f"{database_dir}/distance.json"

    token_path = f"{database_dir}/token_{process_type}.json"
    count_path = f"{database_dir}/count_{process_type}.json"
    time_path = f"{database_dir}/cov_time.csv"
    func_json_path = f"{database_dir}/functions.json"
    type_json_path = f"{database_dir}/types.json"
    prot_json_path = f"{database_dir}/prototypes.json"

    all_struct_path = f"{database_dir}/struct_def.json"
    all_typedef_path = f"{database_dir}/typedef_def.json"

    func_used_path = f"{database_dir}/function_used.json"
    used_path = f"{database_dir}/used.json"
    flow_log_path = f"{database_dir}/flow_all.log"

    tmp_branch_path = f"{database_dir}/cov_branch_tmp.json"
    tmp_line_path = f"{database_dir}/cov_line_tmp.json"
    tmp_function_path = f"{database_dir}/cov_function_tmp.json"

    taken_directive_path = f"{database_dir}/taken_directive.json"
    unordered_taken_directive_path = f"{database_dir}/unordered_taken_directive.json"
    all_directive_path = f"{database_dir}/all_directive.json"
    is_program_path = f"{database_dir}/is_program.json"
    all_macros_path = f"{database_dir}/all_macros.json"
    taken_macros_path = f"{database_dir}/taken_macros.json"
    guards_path = f"{database_dir}/guards.json"
    guarded_macros_path = f"{database_dir}/guarded_macros.json"
    independent_path = f"{database_dir}/independent.json"
    flag_path = f"{database_dir}/flag.json"
    const_path = f"{database_dir}/const.json"
    global_path = f"{database_dir}/globals.json"
    tool_json_path = f"{tool_dir}/tools.json"

    current_cov_path = f"{database_dir}/current_cov_info.info"
    write_file(current_cov_path, "")

    target_dir = f"{work_dir}/{target}" # set the target dir
    run_all_path = f"{target_dir}/run_all.sh"
    run_test_path = f"{target_dir}/run_test.sh"
    build_path = f"{target_dir}/c_build.sh"

    if process_type in ["exp", "set", "file", "carpet", "zigzag", "afl_argv"]: #"preset", "gcno", "exp", "set", "file", "carpet", "zigzag", "afl_argv"]:
        seed_dir = f"{home_dir}/seeds"
        shell_dir = f"{seed_dir}/shell"

        target_shell_dir = f"{shell_dir}/{target_cmd}_{directory_id}"
        base_argv_path = f'{transit_dir}/{target_cmd}_{directory_id}.txt'


    #######################################################
    ###### Main pipeline
    #######################################################

    AGENT = False
    if AGENT is False:
        llm_interface = LLMInterface(
            AGENT=AGENT,
            project_id=target,
            occupy_path=occupy_path,
            llm_choice=llm_choice,
            llm_model=None,
            temperature=0,
            api_key=None,
            timeout=300,
            output_max=128000, # 4000,
            context_window=1000000,
            history_path=history_path,
            token_path=token_path,
            database_dir=database_dir,
            chat_dir=chat_dir,
            count_path=count_path,
            exp_data={},
        )

    else:
        work_dir_abs = os.path.abspath(work_dir)
        database_dir_abs = os.path.abspath(database_dir)
        run_all_abs = os.path.abspath(f"{work_dir}/run_all.sh")
        rust_build_abs = os.path.abspath(f"{work_dir}/trans_rust/rust_build.sh")

        session_path = f"{database_dir}/session_id.txt"
        cost_path = f"{database_dir}/cost_total.txt"

        if os.path.exists(session_path):
            delete_file(session_path)

        if os.path.exists(cost_path):
            delete_file(cost_path)
    
        llm_interface = AgentInterface(
            AGENT=AGENT,
            project_id=target,
            occupy_path=occupy_path,
            llm_choice=llm_choice,
            llm_model=None,
            api_key=None,
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
            session_path=session_path,
            database_dir=database_dir,
            chat_dir=chat_dir,
            count_path=count_path,
            token_path=token_path,
        )
    
    llm_model = get_claude_model(llm_choice)
    llm_interface = configure_llm(
        llm_interface,
        api_key,
        azure_endpoint,
        llm_model
    )
    
    # start the hybrid
    start_time = time.time()
    will_show = True
    targeted_set = set()

    try:
        ommited_files = []
        target_funcs = []
        
        if process_type in ["prepare", "core"]: #"preset", "gcno", "exp", "set", "file", "carpet", "zigzag", "afl_argv"]:
            initialize(
                original_target_dir, meta_dir, target_dir, work_dir, snap_dir, database_dir, 
                chat_dir, tmp_dir, preset_dir, all_struct_path, all_typedef_path, 
                type_json_path, func_json_path, prot_json_path, reformed_path, isolated_path, 
                callee_path, callee_main_path, func_used_path, branch_path, line_path, periodic_path, logging_path,
                priority_path, select_path, is_program_path, token_path, cov_report_path, time_path, process_type, target_cmd
            )

        if process_type == "core":
            atexit.register(partial(get_final_report,
                            target_dir, process_type, start_time, original_target_dir,
                            archive_dir, result_path, dep_json_path, meta_dir, logging_path, target_cmd, target,
                            fixed_explore_time, temperature, total_time, interval, 
                            fixed_metric, llm_choice, llm_model, strategy,
                            chat_dir, snap_dir, MIN_LENGTH, WO_READ, WO_PATH, WO_VALIDATION, SURROUND, 
                            cov_report_path, select_path, database_dir, token_path,
                            config_data)) 
        

        print(f"\n=============== Start of {process_type} ===============\n\n")
        
        if process_type == "tool":

            if not os.path.exists(tool_dir):
                create_directory(tool_dir)

            find_tool(target, target_cmd, target_dir, llm_interface, os_version)

        elif process_type == "prepare":
            print("Preparing ...")
            executable = True
            executable, main_list = search_main(process_type, target, run_test_path, dep_json_path, build_path, 
                                                target_dir, meta_dir, database_dir, 
                                                all_struct_path, all_typedef_path, ommited_files,
                                                macro_finder, div_meta_dir, taken_directive_path, unordered_taken_directive_path,
                                                all_directive_path, is_program_path, all_macros_path, taken_macros_path,
                                                guards_path, guarded_macros_path, independent_path, flag_path, const_path, global_path) 

            print("---------------- Result ----------------")
            main_paths = []
            for entry in main_list:
                def_file_path, def_start_line, _ = parse_def_loc(entry['definition'])
                base_path = remove_base_path(def_file_path, f"{home_dir}/{target_dir}")
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
            analyze_call_dependencies(target_dir, meta_dir, database_dir, is_program_path, reformed_path, isolated_path)

            # get call relationship
            analyze_call_relationship(meta_dir, callee_path, target_dir, is_program_path)

            # get main-function surrounded 
            get_related_main(
                database_json, target_cmd, home_dir, WEIGHT, 
                work_dir, callee_main_path, callee_path, distance_path, 
                meta_dir, database_dir
            )

            graph_metrics, G = build_graph(callee_path, callee_main_path)

            write_metrics(target_cmd, graph_metrics)

            delete_directory(preset_dir)
            copy_directory(meta_dir, preset_dir)
            copy_file(is_program_path, preset_dir)
            copy_file(dep_json_path, preset_dir)

            copy_file(func_json_path, preset_dir)
            copy_file(prot_json_path, preset_dir)

            copy_file(reformed_path, preset_dir)
            copy_file(isolated_path, preset_dir)
            copy_file(callee_path, preset_dir)
            copy_file(callee_main_path, preset_dir)

        elif process_type == "gcno":
            # work_dir comes from afl's directory with gcno
            delete_directory(work_dir)
            copy_directory(original_target_dir, work_dir)
            run_script(process_type, database_dir, build_path, 10000, True, None, "both")
            copy_directory(work_dir, preset_dir)


        elif process_type == "core":
            # func_sum = get_func_sum(callee_main_path)
            check_command_availability(tool_json_path, target_cmd, target)
        
            # Set at the start of execution
            set_timeout(
                total_time, start_time, original_target_dir, archive_dir, 
                result_path, dep_json_path, meta_dir, logging_path, target_cmd, target
            ) 
            print(f"Target_dir: {target_dir}")
            create_permissioned_file(run_test_path)

            graph_metrics, G = build_graph(callee_path, callee_main_path)

            error = None
            std_out = None
            cycle = 1
            total_start_time = time.time()
            clear_gcda_files(target_dir)
            tool_string, cmd_self = get_tool_string(tool_json_path, target_cmd, target)

            # Write the first testcase
            ask_basic_command(
                llm_interface, target_cmd, max_iterations, tool_string, strategy, TESTFILE_COUNTER, WO_VALIDATION,
                target_dir, work_dir, database_dir, snap_dir, log_dir, original_target_dir, 
                is_program_path, meta_dir, build_path, run_test_path, branch_path, function_path, 
                flow_log_path, database_json
            )

            target_function_count = 0
            current_coverage = None

            while(1):
                print(f"Current_coverage: {current_coverage}")
                if current_coverage == 100:
                    break

                elapsed_time = time.time() - total_start_time

                if target_function_count >= max_target_func:
                    print(f"Reached {target_function_count} functions, so stopping")
                    minutes = int(elapsed_time // 60)
                    print(f"{elapsed_time:.2f} seconds ({minutes} min) elapsed")
                    break

                if cycle == 1:
                    if COUNT_PERIODIC is True:
                        start_periodic_server(
                            process_type, strategy, interval, target_dir, azure_endpoint, target_function_count, tmp_branch_path, tmp_line_path, tmp_function_path
                        )                

                # Explore pathes
                try:
                    current_coverage, target_entry = explore_path(
                        llm_interface, strategy, tool_string, max_num_test, cov_target, current_coverage, targeted_set, target_cmd, target_dir, is_program_path, 
                        meta_dir, work_dir, database_dir, original_target_dir, snap_dir, tmp_dir, log_dir, 
                        build_path, run_test_path, branch_path, line_path, function_path, flow_log_path, dep_json_path, time_path, token_path, select_path, 
                        current_cov_path, cov_report_path, fixed_metric, fixed_version_count, fixed_explore_time, explore_fix,
                        database_json, priority_path, error, std_out, callee_path, callee_main_path, graph_metrics, G,
                        WO_READ, WO_PATH, WO_VALIDATION, MIN_LENGTH, GDB_OPTION, TESTFILE_COUNTER
                    ) 
                    print(f"Target_dir: {target_dir}")

                    # repair branches
                    if target_entry['is_covered'] is True and target_entry['is_full_branch_covered'] is False:
                    # target_entry = {
                    #     "target_path": f"{home_dir}/workspace_tiffcp_old/libtiff-git-b51bb/libtiff/tiffiop.h",
                    #     "target_line": 114,
                    #     "target_function": "tiff",
                    #     'target_uncovered_ratio' : 0.2,
                    #     'target_branch' : 2,
                    #     'target_end_line' : 32,
                    #     'explore_time' : 300,
                    #     'original_run_test_path' : run_test_path,
                    # }
                    # TEST = True
                    # if TEST is True:
                        try:
                            explore_branch(llm_interface, strategy, cov_target, target_cmd, target_dir, target_entry, is_program_path, meta_dir, build_path, run_test_path,
                                work_dir, original_target_dir, database_dir, snap_dir, tmp_dir, log_dir,
                                dep_json_path, time_path, token_path, max_num_test,
                                branch_path, line_path, function_path, cov_report_path, select_path, fixed_explore_time,
                                flow_log_path, database_json, priority_path, error, std_out, callee_path, graph_metrics, G
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
                    cov_target, target_dir, database_dir, branch_path, line_path, function_path, 
                    is_program_path, current_cov_path
                )
                save_coverage_report(cov_target, cov_report_path, token_path, branch_coverage, line_coverage, func_coverage, None)

                if strategy == "wo_t":
                    print("Finished: WO_TARGET senario done!")
                    sys.exit(0)

                error = None
                std_out = None
                cycle += 1
                target_function_count += 1

        elif process_type == "exp":

            empty_id = export_to_seed_dir(snap_dir, shell_dir, target_cmd)

            print(f"\nNext action:")
            print(f"python3 run.py {target_cmd} set {empty_id}")

        elif process_type == "set": # "car_prepare"  # prepare the set directory

            if not os.path.exists(f"{transit_dir}"):
                create_directory(f"{transit_dir}")
                
            generate_base_argv(
                target_shell_dir, base_argv_path,
                process_type, target_dir, database_dir, database_json, target_cmd, directory_id
            )

            print(f"Input argvs: saved at {base_argv_path}")
        
        elif process_type == "file":

            input_file_dir = f"{seed_dir}/pilot/input/{target_cmd}_{directory_id}"

            generate_input_files(
                base_argv_path, input_file_dir,
                target_cmd, directory_id, llm_interface,
                database_dir, target_dir, transit_dir, database_json, seed_dir
            )

            print(f"\nInput files: saved at {input_file_dir}")


        elif process_type == "carpet":

            carpet_argv_path = f'{seed_dir}/pilot/carpet_argvs/{target_cmd}_{directory_id}.txt'
  
            generate_carpet_argv(
                base_argv_path, carpet_argv_path,
                llm_interface, chat_dir, transit_dir, database_dir, target_cmd, directory_id
            )
            print(f"\nSaved: {carpet_argv_path}")
            

        elif process_type == "zigzag": 

            zigzag_argv_path = f"{seed_dir}/pilot/keyword_dict/list_{target_cmd}_{directory_id}.txt"
            
            generate_zigzag_argv(
                base_argv_path, zigzag_argv_path,
                target_cmd
            )
            print(f"\nSaved: {zigzag_argv_path}")
            
        elif process_type == "afl_argv":

            #input_path = f"{transit_dir}/afl_{target_cmd}_{directory_id}.txt"
            afl_argv_dir = f"{seed_dir}/pilot/afl_argvs/{target_cmd}_{directory_id}"

            generate_afl_argv(
                base_argv_path, afl_argv_dir,
                chat_dir, transit_dir, target_cmd, directory_id
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
    # explore_fix = str(sys.argv[2])
    # llm_argument = str(sys.argv[4])

    user_id = "0000"
    home_dir  = f"/root/PILOT"
    config_path = f"{home_dir}/config.json"
    macro_parser_dir = "/root/kiso-parser-macro"

    max_target_func = 5
    total_time = 180000 # 5400 #3600 #14400 
    interval = 30 #5 #30  # The measurement interval
    fixed_explore_time = 250
    fixed_version_count = 3 # 2
    cov_target = "function"  # "line" # "function" # "branch"
    explore_time = 300 #180
    temperature = 0 #1 #0
    max_num_test = 20
    max_iterations = 20
    TESTFILE_COUNTER = 0
    AGENT = True 
    COUNT_PERIODIC = True
    WEIGHT = None

    config_data = read_json(f"{config_path}")

    llm_choice     = config_data["llm_choice"]
    api_key        = config_data["api_key"]
    azure_endpoint = config_data["azure_endpoint"]
    os_vendor      = config_data['os_vendor']
    os_version     = config_data['os_version'] # os_version = "Ubnutu 20.04"
    # "os_vendor" : "Mac OS",
    # "os_version" : "Sonoma 14.3",

    config = {
        "process_type": process_type,
        #"original_dir": original_dir,
        #"llm_argument" : llm_argument,
        # "explore_fix" : explore_fix,
        "target_cmd" : target_cmd,
        "user_id": user_id,
        "llm_choice": llm_choice,
        "api_key": api_key,
        "azure_endpoint": azure_endpoint,
        "max_target_func" : max_target_func,
        "max_iterations" : max_iterations,
        "total_time" : total_time,
        "interval" : interval,
        "fixed_explore_time" : fixed_explore_time,
        "fixed_version_count" : fixed_version_count,
        "cov_target" : cov_target,
        "explore_time" : explore_time,
        "temperature" : temperature, 
        "max_num_test" : max_num_test,
        "home_dir" : home_dir,
        "directory_id" : directory_id,
        "config_path" : config_path,
        "macro_parser_dir" : macro_parser_dir,
        "TESTFILE_COUNTER" : TESTFILE_COUNTER,
        "AGENT" : AGENT,
        "COUNT_PERIODIC" : COUNT_PERIODIC,
        "WEIGHT" : WEIGHT,
    }

    try:
        explorer_main(config)  

    except:
        will_show = False
        traceback.print_exc()
        sys.exit(1)
        



"""
python3 run.py tiffcp_old tool
python3 run.py tiffcp_old prepare
python3 run.py tiffcp_old preset
python3 run.py tiffcp_old gcno
python3 run.py tiffcp_old core

python3 run.py tiffcp_old exp
python3 run.py tiffcp_old set 000
python3 run.py tiffcp_old carpet 000
python3 run.py tiffcp_old zig 000
python3 run.py tiffcp_old afl_argv 000
"""
