# PILOT: Path-guided, Iterative LLM-Orchestrated Testing

PILOT is a novel CLI fuzzing framework that leverages Large Language Models (LLMs) to generate semantically-rich command-line options and input files for discovering vulnerabilities in CLI applications.

## Directory structure
```
PILOT/
├── Dockerfile               # Container image definition
├── Dockerfile.dockerignore  # Build context exclusions for the Dockerfile
├── requirements.txt         # Python dependencies installed in the image
├── run.py               # main Python script
├── config.json          # Configuration JSON file
├── config_sys.json      # System configuration for the generation loop
├── database.json        # Per-target main function path and executable path
├── pilot_lib/
│   ├── __init__.py
│   ├── analyze.py       # Function metadata and call relationship extraction
│   ├── generate.py      # LLM-driven seed generation loop
│   ├── graph.py         # Call graph construction
│   ├── reformat.py      # Conversion of test scripts into fuzzer inputs
│   ├── tool.py          # Native tools detection
│   └── utils.py         # Shared helpers
├── program/               # Target applications
│   └── h_download.sh      # Download script for target programs
├── scripts/               # Helper scripts for building/instrumenting targets
│   └── h_set_build.sh     # Sets up c_build.sh for each target program
├── .gitignore          
└── README.md           # Project documentation
```

## Setup
### Installation

#### 1. Build the Docker image

Clone all five repositories into the same parent directory:

```bash
mkdir pilot-workspace && cd pilot-workspace
git clone https://github.com/momo-trip/PILOT.git
git clone https://github.com/momo-trip/kiso-utils.git
git clone https://github.com/momo-trip/kiso-parser-c.git
git clone https://github.com/momo-trip/kiso-parser-macro.git
git clone https://github.com/momo-trip/kiso-llm.git
```

Then build from the **parent** directory — not from inside `PILOT/`, since the
build context must include the `kiso-*` repositories:

```bash
docker build -f PILOT/Dockerfile -t pilot:latest .
```

#### 2. Start a container

```bash
docker run -it --name pilot-run pilot:latest
```

All commands in the following sections are run inside the container.


#### 3. Prepare the target program
```bash
cd ~/PILOT/program
git clone {target_program_repository}
cd {program_name}
touch c_build.sh
# Edit c_build.sh to generate compile_commands.json (e.g., using bear)
```
See [program/README.md](program/README.md) for detailed instructions on downloading and building target programs.


#### 4. Setup
Create a JSON file at `/root/PILOT/config.json` and set the model parameters in
that file. See [config_example.json](https://github.com/momo-trip/PILOT/blob/main/config_example.json)
for a template.

**Configuration parameters (`config.json`):**
- `llm_choice` - LLM service provider (e.g., `claude`, `claude_azure`)
- `llm_model` - Specific model name (e.g., `claude-4-sonnet`, `databricks-claude-opus-4-8`). If `null`, the default model of the selected provider is used
- `api_key` - Your API key for the LLM service
- `azure_endpoint` - Serving endpoint URL (if using Azure Databricks)
- `AGENT` - Whether to use the agent SDK based generation pipeline
- `os_vendor` - Operating system name (e.g., `Ubuntu`)
- `os_version` - Operating system version (e.g., `20.04`, `22.04`)
- `max_target_func` - Maximum number of target functions to select
- `strategy` - Seed generation strategy (e.g., `base`)
- `cent` - Centrality metric used to select target functions (see below)



**Centrality metric options (for `cent` parameter):**
- `deg` - Degree centrality (number of connections)
- `bet` - Betweenness centrality (importance in shortest paths)
- `close` - Closeness centrality (average distance to all other nodes)
- `page` - PageRank algorithm
- `random_t` - Random selection (baseline)

The strategy that PILOT chooses based on the pre-experiment is saved here: [`decision.json`](https://github.com/momo-trip/PILOT/blob/main/decision.json).


**LLM options (for `{llm_choice}` parameter):**
- `claude` - Claude via Anthropic API
- `claude_azure` - Claude via Azure Databricks
<!-- - `gpt` - GPT models via OpenAI API
- `gpt_azure` - GPT via Azure
- `gemini` - Gemini via Google API -->


**Agent SDK authentication (required when `AGENT` is enabled):**

When `AGENT` is enabled in `config.json`, PILOT drives generation through the
Claude Agent SDK, which launches Claude Code as a subprocess. This path does **not**
use the `api_key` field in `config.json`.

Authentication follows the standard Claude Code setup. See the official
documentation for the available account types and credentials:
<https://code.claude.com/docs/en/authentication>


**System parameters (`config_sys.json`):**

Defaults are provided. Override them as necessary.
- `user_id` - Identifier for the run
- `database_path` - Path to the target definition file (default: `database.json`)
- `total_time` - Overall time budget for the generation loop, in seconds
- `interval` - Interval between periodic tasks such as coverage measurement, in seconds
- `max_explore_time` - Upper bound on a single exploration phase, in seconds
- `max_version_count` - Number of seed variations to generate per target
- `cov_target` - Granularity of coverage measurement (e.g., `function`)
- `explore_time` - Baseline duration of the exploration phase, in seconds
- `explore_fix` - Whether the exploration time is fixed (`t` or `f`)
- `temperature` - Sampling temperature for the LLM
- `max_num_test` - Maximum number of tests generated per iteration
- `max_iterations` - Maximum number of iterations of the generation loop
- `timeout` - Timeout for each command execution, in seconds
- `output_max` - Maximum number of characters of program output passed to the LLM
- `context_window` - Context window size of the LLM
- `COUNT_PERIODIC` - Whether to measure coverage periodically


### Important notes:
- While the codebase includes code paths for other LLM providers, only Claude models are currently supported.
- The harness was originally hand-written, but continuous maintenance is costly, so this part is now partly delegated to Claude Code. Please run with `"AGENT": true`; the hand-written path is retained for reference but is no longer actively maintained.
- In recent runs, seed generation may occasionally be blocked by the LLM provider's safety filter. PILOT treats this as a skip and proceeds to the next target function.
- Seed generation uses the environment specified above, while each fuzzer requires its own separate environment. Please follow the respective fuzzer's guidelines for setting up the fuzzing execution environment.


## Phase 1: Seed generation
#### 1. Extract function metadata
```bash
cd ~/PILOT
python3.12 run.py {target_cmd} prepare
```

**Output:**
- `metadata_{target_cmd}/` - Extracted function metadata
- `workspace_{target_cmd}/` - The target rebuilt directory
- `database/{target_cmd}/` - Per-program misc data


> [!NOTE]
> The list of available `target_cmd` values of the benchmark set is defined in
> [`benchmark.json`](https://github.com/momo-trip/PILOT/blob/main/benchmark.json). 
> The directory path for each `target_cmd` is defined in [`database.json`](https://github.com/momo-trip/PILOT/blob/main/database.json). Verify that the corresponding program has been downloaded to the program directory.
> If you want to try a program outside the benchmark set, add the `target_cmd` identifier and the directory name to [PILOT/database.json](https://github.com/momo-trip/PILOT/blob/main/database.json). For example:
```json
"xmlwf_old": {
    "main_path": "",
    "dir_name": "program/expat-2.4.1",
    "cmd_exe": "",
    "notes": []
}
```
For `dir_name`, specify the path relative to `/root/PILOT`.


After executing the script, you will see output like the following:
```
---------------- Result ----------------
/root/PILOT/program/expat-2.4.1/tests/benchmark/benchmark.c
/root/PILOT/program/expat-2.4.1/xmlwf/xmltchar.h
/root/PILOT/program/expat-2.4.1/examples/outline.c
/root/PILOT/program/expat-2.4.1/examples/elements.c

Should avoid using as the target because it has multiple main functions.

=============== End of prepare ===============
```

If you want to try a program outside the benchmark set, identify the correct main function for your target command and the path to the target command's executable binary, and add them to [PILOT/database.json](https://github.com/momo-trip/PILOT/blob/main/database.json). For example:
```json
"xmlwf_old": {
    "main_path": "program/expat-2.4.1/xmlwf/xmltchar.h",
    "dir_name": "program/expat-2.4.1",
    "cmd_exe": "xmlwf/xmlwf",
    "notes": []
}
```
For `cmd_exe`, specify the path to the target command's executable binary,
relative to `dir_name`. For `main_path`, specify the path relative to
`/root/PILOT`.


#### 2. Extract function call relationships
```bash
python3.12 run.py {target_cmd} preset
```

**Output:**
  - `database/{target_cmd}/callee.json` / `callee_main.json` - Function call relationships


#### 3. Instrument with gcov for coverage measurement
```bash
python3.12 run.py {target_cmd} gcno
```

**Output:**
- `preset/{target_cmd}/workspace_{target_cmd}/` - Copy of the instrumented build for reuse


#### 4. Prepare native tools for input generation via LLM interaction
```bash
python3.12 run.py {target_cmd} tool
```

**Output:**
- `tools/{target_cmd}/` - Extracted tool data
- `chats_tool/{target_cmd}/` - LLM conversation logs for this step


#### 5. Run iterative seed generation cycle
```bash
python3.12 run.py {target_cmd} gen
```

**Output:**
- `snapdata/{target_cmd}/` - Generated test scripts per target function
- `chats_gen/{target_cmd}/` - LLM conversation logs for this step
- `archive/{trial_id}_gen_{llm_model}_{strategy}_{cent}/` - Archived run results (chats, snapdata, coverage report, token usage, `setting.json`)


#### 6. Extract generated shell scripts
```bash
python3.12 run.py {target_cmd} exp
```

**Output:**
- `seeds/shell/{target_cmd}_{seed_id}/` - Generated seed scripts, collected from `snapdata/`

The assigned `{seed_id}` is printed at the end of the run, along with the next
command to run.


## Phase 2: Reformatting
#### 1. Setup
`{seed_id}` is the index assigned to each exported seed script, numbered in the
order the `python3.12 run.py {target_cmd} exp` command writes them.

```bash
python3.12 run.py {target_cmd} set {seed_id}
```

**Output:**
- `transit/{target_cmd}_{seed_id}_base_argv.txt` - Candidate command lines extracted from the seed scripts


#### 2. Retrieve input files
```bash
python3.12 run.py {target_cmd} file {seed_id}
```
**Output:**
- `seeds/pilot/input/{target_cmd}_{seed_id}/` - Input files collected by replaying the seed scripts
- `chats_file/{target_cmd}/` - LLM conversation logs for this step


#### 3. Format test scripts into fuzzing inputs
```bash
python3.12 run.py {target_cmd} {fuzzer_type} {seed_id}
```

| `fuzzer_type` | Used by |
|---|---|
| `carpet` | CarpetFuzz |
| `zigzag` | ZigZagFuzz |
| `afl_argv` | SelectFuzz |


**Output:**
- `seeds/pilot/carpet_argvs/{target_cmd}_{seed_id}.txt` - Argument configurations for CarpetFuzz
- `seeds/pilot/keyword_dict/list_{target_cmd}_{seed_id}.txt` - Keyword dictionary for ZigZagFuzz
- `seeds/pilot/afl_argvs/{target_cmd}_{seed_id}/` - Argument configurations for SelectFuzz

Together with the input files from the previous step
(`seeds/pilot/input/{target_cmd}_{seed_id}/`), these seeds are ready to be used
with your chosen fuzzer in Phase 3.


## Phase 3: Fuzzing

After reformatting, the seeds will be available in the specified output directory.\
Use these seeds with your chosen fuzzer according to its specific environment requirements.

### CarpetFuzz
- Repo URL: https://github.com/waugustus/CarpetFuzz-fuzzer/tree/717289769d8219c129fa2ea1cbfba73e23de17d2
- Configuration parameters:
    - `i_dir`: /root/PILOT/seeds/pilot/input/{target_cmd}_{seed_id}
    - `K_path`: /root/PILOT/seeds/pilot/carpet_argvs/{target_cmd}_{seed_id}.txt
- Command to run:
```bash
${CarpetFuzz}/afl-fuzz -i {i_dir} -o out_1 -K {K_path} -- ./{target_cmd}.afl @@
```

### ZigZagFuzz
- Repo URL: https://github.com/swtv-kaist/ZigZagFuzz
- Configuration parameters:
    - `seed_dir`: /root/PILOT/seeds/pilot/input/{target_cmd}_{seed_id}
    - `keyword_path`: /root/PILOT/seeds/pilot/keyword_dict/list_{target_cmd}_{seed_id}.txt
- Command to run:
```bash
${ZigZagFuzz_repo}/afl-fuzz -i {seed_dir} -o out_1 -K 2 -a {keyword_path} -- ./{target_cmd}.afl
```

### SelectFuzz
- Repo URL: https://github.com/cuhk-seclab/SelectFuzz
- Setup for target functions\
  Please set the target functions in each BBtargets_{target_cmd}.txt file.
- argv interface\
  Before fuzzing, it is required to insert AFL++ argv fuzzing interface.
- Configuration parameters:
    - `seed_dir`: /root/PILOT/seeds/pilot/afl_argvs/{target_cmd}_{seed_id}
- Command to run: 
```bash
$AFLGO/afl-fuzz -m none -z exp -c 45m -i {seed_dir} -o out_1 -- ./{target_cmd}.afl
```


## Materials
- ArXiv: https://arxiv.org/abs/2511.20555
- 🆕 This work has been accepted at IEEE S&P 2026.


## Contact
If you have any questions, please contact me at the email address below.

Momoko Shiraishi\
University email: <u>shiraishi@os.is.s.u-tokyo.ac.jp</u>\
(Personal email: <u>momoko.shiraishi36@gmail.com</u>)
