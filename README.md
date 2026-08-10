# PILOT: Path-guided, Iterative LLM-Orchestrated Testing

PILOT is a novel CLI fuzzing framework that leverages Large Language Models (LLMs) to generate semantically-rich command-line options and input files for discovering vulnerabilities in CLI applications.

## Important Notice
If you have any questions, please contact me at the email address below.

<u>shiraishi@os.is.s.u-tokyo.ac.jp</u>


## Directory structure
```
PILOT/
├── run.py               # main Python script
├── config.json          # Configuration JSON file
├── config_sys.json      # System configuration for the generation loop
├── database.json        # Per-target main function path and executable path
├── pilot_lib/
│   ├── __init__.py
│   ├── analyze.py       # Function metadata and call relationship extraction
│   ├── generate.py      # LLM-driven seed generation loop
│   ├── graph.py         # Call graph construction and centrality metrics
│   ├── reformat.py      # Conversion of test scripts into fuzzer inputs
│   ├── tool.py          # Native tools exposed to the LLM
│   └── utils.py         # Shared helpers
├── program/               # Target applications
│   └── h_download.sh      # Download script for target programs
├── .gitignore          
└── README.md           # Project documentation
```

## Setup

### Prerequisites
- **Python**: Python 3.12 or higher
- **Operating system**: Ubuntu 20.04 or later (recommended)

### Note:
<!-- - Sandboxed environment setup: Docker configurations are not provided with this code. Please set up your own sandboxed environment and deploy this repository within it. -->
- Seed generation uses the environment specified above, while each fuzzer (mutator) requires its own separate environment. Please follow the respective mutator's guidelines for setting up the fuzzing execution environment.

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
docker build --platform=linux/amd64 -f PILOT/Dockerfile -t pilot:latest .
```

Requires Docker 23 or later (BuildKit). The build takes roughly 40–60 minutes,
most of which is spent compiling and instrumenting the target programs.

#### 2. Start a container

```bash
docker run -it --rm pilot:latest
```

All commands in the following sections are run inside the container, where the
repository is at `/root/PILOT` and `PILOT_BASE_DIR` is already set.


<!-- #### 1. Clone the repository

```bash
git clone https://github.com/momo-trip/PILOT.git
```

#### 2. Install python dependencies

```bash
pip install -r requirements.txt
```

Required packages include:
- `libclang` (for C code parsing)
- `networkx` (for call graph analysis)
- `anthropic` or `openai` (for LLM API) -->


#### 3. Prepare the target program
```bash
cd PILOT/program
git clone {target_program_repository}
cd {program_name}
touch c_build.sh
# Edit c_build.sh to generate compile_commands.json (e.g., using bear)
```
See [program/README.md](program/README.md) for detailed instructions on downloading and building target programs.


#### 4. Setup
Set the model parameters in the JSON file at [PILOT/config.json](https://github.com/momo-trip/PILOT/blob/main/config.json).

**Configuration parameters (`config.json`):**
- `llm_choice` - LLM service provider (e.g., `claude_azure`, `claude`, `gpt`)
- `llm_model` - Specific model name (e.g., `databricks-claude-sonnet-4`, `gpt-4`, `claude-3-sonnet`). If `null`, the default model of the selected provider is used
- `api_key` - Your API key for the LLM service
- `azure_endpoint` - Serving endpoint URL (if using Azure or Databricks)
- `AGENT` - Whether to use the agent SDK based generation pipeline
- `os_vendor` - Operating system name (e.g., `Ubuntu`)
- `os_version` - Operating system version (e.g., `20.04`, `22.04`)
- `strategy` - Seed generation strategy (e.g., `base`)
- `cent` - Centrality metric used to select target functions (see below)

**System parameters (`config_sys.json`):**

These usually do not need to be changed.
- `user_id` - Identifier for the run
- `database_path` - Path to the target definition file (default: `database.json`)
- `max_target_func` - Maximum number of target functions to select
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


**Centrality metric options (for `cent` parameter):**
- `deg` - Degree centrality (number of connections)
- `bet` - Betweenness centrality (importance in shortest paths)
- `close` - Closeness centrality (average distance to all other nodes)
- `page` - PageRank algorithm
- `random_t` - Random selection (baseline)


**LLM options (for `{llm_type}` parameter):**
- `claude` - Claude via Anthropic API
- `claude_azure` - Claude via Azure
- `gpt` - GPT models via OpenAI API
- `gpt_azure` - GPT via Azure
- `gemini` - Gemini via Google API


**Agent SDK authentication (required when `AGENT` is enabled):**

When `AGENT` is enabled in `config.json`, PILOT drives generation through the
Claude Agent SDK, which launches Claude Code as a subprocess. This path does **not**
use the `api_key` field in `config.json`.
Provide credentials in one of the following ways *inside the container*.


## Phase 1: Seed generation
#### 1. Extract function metadata
```bash
cd PILOT
export PILOT_BASE_DIR=/root/PILOT
python3.12 run.py {target_cmd} prepare
```

> [!NOTE]
> The list of available `target_cmd` values of the benchmark set is defined in
> [`benchmark.json`](https://github.com/momo-trip/PILOT/blob/main/benchmark.json).


#### 2. Extract function call relationships
```bash
python3.12 run.py {target_cmd} preset
```

After executing the script, you will see output like the following:
```
---------------- Prepare result ----------------
/root/PILOT/program/expat-2.4.1/tests/benchmark/benchmark.c
/root/PILOT/program/expat-2.4.1/xmlwf/xmltchar.h
/root/PILOT/program/expat-2.4.1/examples/outline.c
/root/PILOT/program/expat-2.4.1/examples/elements.c
Should avoid using as the target because it has two main functions.
=============== End of prepare ===============
```

Identify the correct main function for your target command and add it to [PILOT/database.json](https://github.com/momo-trip/PILOT/blob/main/database.json). For example:
```json
"xmlwf_old": {
    "main_path": "program/expat-2.4.1/xmlwf/xmltchar.h",
    "dir_name": "program/expat-2.4.1",
    "cmd_exe": "xmlwf/xmlwf",
    "notes": []
}
```
For `cmd_exe`, specify the relative path to the target command's executable binary from the base `PILOT_BASE_DIR` directory.

#### 3. Instrument with gcov for coverage measurement
```bash
python3.12 run.py {target_cmd} gcno
```

#### 4. Prepare native tools for input generation via LLM interaction
```bash
python3.12 run.py {target_cmd} tool
```

#### 5. Run iterative seed generation cycle
```bash
python3.12 run.py {target_cmd} gen
```

The strategy that PILOT chooses based on the pre-experiment is saved here: `h_strategy.json`.

#### 6. Extract generated shell scripts
Run the following command to extract the generated shell scripts. The seed scripts for each command will be saved in `{PILOT_BASE_DIR}/seeds`.
```bash
python3.12 run.py {target_cmd} exp
```

## Phase 2: Reformatting
#### 1. Setup
```bash
python3.12 run.py {target_cmd} set {seed_id}
```

#### 2. Retrieve input files
```bash
python3.12 run.py {target_cmd} file {seed_id}
```

#### 3. Format test scripts into fuzzing inputs
```bash
python3.12 run.py {target_cmd} {fuzzer_type} {seed_id}
```

| `fuzzer_type` | Output directory | Used by |
|---|---|---|
| `carpet` | `carpet_argvs/` | CarpetFuzz |
| `zigzag` | `keyword_dict/` | ZigZagFuzz |
| `afl_argv` | `afl_argvs/` | SelectFuzz |


After completing these steps, the formatted seeds for each fuzzer (mutator) will be generated in `{PILOT_BASE_DIR}/seeds/pilot/`:
- `input/{target_cmd}_{seed_id}/` - Input files for fuzzing
- `carpet_argvs/{target_cmd}_{seed_id}.txt` - Argument configurations for CarpetFuzz
- `keyword_dict/list_{target_cmd}_{seed_id}.txt` - Keyword dictionary for ZigZagFuzz
- `afl_argvs/{target_cmd}_{seed_id}/` - Argument configurations for SelectFuzz

These seeds are now ready to be used with your chosen fuzzer in Phase 3.


## Phase 3: Fuzzing

After reformatting, the seeds will be available in the specified output directory.\
Use these seeds with your chosen fuzzer according to its specific environment requirements.

### CarpetFuzz
- Repo URL: https://github.com/waugustus/CarpetFuzz-fuzzer/tree/717289769d8219c129fa2ea1cbfba73e23de17d2
- Configuration parameters:
    - `i_dir`: {PILOT_BASE_DIR}/set/PILOT/{target_cmd}/input
    - `K_path`: {PILOT_BASE_DIR}/set/PILOT/{target_cmd}/argvs
- Command to run:
```bash
${CarpetFuzz}/afl-fuzz -i {i_dir} -o out_1 -K {K_path} -- ./{target_cmd}.afl @@
```

### ZigZagFuzz
- Repo URL: https://github.com/swtv-kaist/ZigZagFuzz
- Configuration parameters:
    - `seed_dir`: {PILOT_BASE_DIR}/set/PILOT/{target_cmd}/input
    - `keyword_dir`: {PILOT_BASE_DIR}/set/PILOT/{target_cmd}/keyword_dict
- Command to run:
```bash
${ZigZagFuzz_repo}/afl-fuzz -i {seed_dir} -o out_1 -K 2 -a {keyword_dir} -- ./{target_cmd}.afl {prefix}
```

### SelectFuzz
- Repo URL: https://github.com/cuhk-seclab/SelectFuzz
- Setup for target functions\
  Please set the target functions in each BBtargets_{target_cmd}.txt file.
- argv interface\
  Before fuzing, it is required to insert AFL++ argv fuzzing interface.
- Configuration parameters:
    - `seed_dir`: {PILOT_BASE_DIR}/set/PILOT/{target_cmd}/afl_argvs
- Command to run: 
```bash
$AFLGO/afl-fuzz -m none -z exp -c 45m -i {seed_dir} -o out_1 -- ./{target_cmd}.afl
```


## Materials
- ArXiv: https://arxiv.org/abs/2511.20555
- 🆕 This work has been accepted at IEEE S&P 2026.

## Contact
Momoko Shiraishi\
University email: <u>shiraishi@os.is.s.u-tokyo.ac.jp</u>\
(Personal email: <u>momoko.shiraishi36@gmail.com</u>)
