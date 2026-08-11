## Download and build programs

### 1. Download the baseline programs:
```bash
cd ~/PILOT/program
bash h_download.sh
```
<!-- 
**Note:** Each program directory must contain its own `c_build.sh` script.
- `target/` contains normal builds
- `target_cov/` contains coverage-instrumented builds for measurement -->

### 2. Create build scripts for each program:

   **Requirements:**
   - Must be named exactly `c_build.sh` and placed at the top level of the
     program directory (`program/{program_name}/c_build.sh`).
   - Must generate `compile_commands.json` (e.g., using the `bear` command or CMake's `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`)
   - Must generate `.gcno` files by setting appropriate compiler flags for gcov instrumentation

   The following are example build scripts. You may need to adjust them based on each program's specific build requirements.

   **Example for coverage-instrumented builds** (`{program_name}/c_build.sh`):
   ```bash
   #!/bin/bash
   
   make distclean
   export CFLAGS="-fprofile-arcs -ftest-coverage"
   export LDFLAGS="-lgcov --coverage -ldeflate"
   export LIBS="-ldeflate"
   
   ./autogen.sh
   ./configure
   bear -- make
   ```

### 3. Make the build scripts executable and run them:
   ```bash
   cd ~/PILOT/program/{program_name}
   chmod +x c_build.sh
   ./c_build.sh
   ```

**Important:** Replace `{program_name}` with the actual program name (e.g., `ffmpeg-N-103440-g2f0113be3f`, `yara-4.1.1`).

