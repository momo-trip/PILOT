#!/bin/bash
# Script configuration
SOURCE_DIR="/root/PILOT/scripts"  #"build_argv"  #"build_asan"  # Source directory (copy from build_shell)
TARGET_DIR="/root/PILOT/program"  # Restore destination directory (current directory)
FILE_NAME="c_build.sh"
FILE_PATTERN="c_build_*.sh"  # Changed to a pattern
# FILE_PATTERN="BBtargets_*.txt"  # Changed to a pattern
# Move
# Check whether the build_shell directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: $SOURCE_DIR directory does not exist."
    exit 1
fi
# Recursively search for c_build.sh files in build_shell and copy them back to their original locations
# find "$SOURCE_DIR" -name "$FILE_NAME" -type f | while read -r filepath; do
find "$SOURCE_DIR" -name "$FILE_PATTERN" -type f | while read -r filepath; do
    # Get the relative path under build_shell/
    relative_path="${filepath#$SOURCE_DIR/}"
    
    # Full destination path for restoration
    dest_path="$TARGET_DIR/$relative_path"
    
    # # Check whether the destination file already exists
    if [ -f "$dest_path" ]; then
        #echo "Skipped (already exists): $dest_path"
        continue
    fi
    # Create the destination directory
    dest_dir=$(dirname "$dest_path")
    # **Added: check whether the destination directory exists**
    if [ ! -d "$dest_dir" ]; then
        echo "Skipped (destination directory does not exist): $dest_dir"
        #echo "  - Would restore: $filepath -> $dest_path"
        continue
    fi
    # # Copy (restore) the file
    # # mkdir -p "$dest_dir"
    cp "$filepath" "$dest_path"
    
    echo "Restored: $filepath -> $dest_path"
done
echo "All c_build.sh files have been restored from build_shell directory to their original locations."