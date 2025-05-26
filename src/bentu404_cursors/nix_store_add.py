import json
import os
import shutil
import subprocess
import tempfile
import sys

# Get the script's directory and project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))

# Define paths relative to project root
CURSORS_JSON = os.path.join(PROJECT_ROOT, "cursors/download_tracking.json")
OVERRIDES_JSON = os.path.join(PROJECT_ROOT, "overrides.json")
CURSORS_DIR = os.path.join(PROJECT_ROOT, "cursors")


def main():
    # Load cursor data
    try:
        with open(CURSORS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find cursor data at {CURSORS_JSON}")
        print(
            "Make sure you're running the script from the project root or correct directory"
        )
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {CURSORS_JSON}")
        sys.exit(1)

    # Load overrides if available
    try:
        with open(OVERRIDES_JSON, "r", encoding="utf-8") as f:
            overrides = json.load(f)
    except FileNotFoundError:
        print(
            f"Warning: Overrides file not found at {OVERRIDES_JSON}, using default names"
        )
        overrides = {}
    except json.JSONDecodeError:
        print(f"Warning: Invalid JSON in {OVERRIDES_JSON}, using default names")
        overrides = {}

    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Created temporary directory: {temp_dir}")

        # Dict to store nix-store paths
        nix_store_paths = {}

        # Process each cursor package
        for entry in data:
            raw_name = entry["name"]
            final_name = overrides.get(raw_name, raw_name)

            # Get the original filename from the entry
            if "filename" not in entry or not entry["filename"]:
                print(f"Error: No filename found for {final_name}. Skipping.")
                continue

            original_filename = entry["filename"]
            source_file_path = os.path.join(CURSORS_DIR, original_filename)

            if not os.path.exists(source_file_path):
                print(f"Error: Source file not found: {source_file_path}")
                # Try alternative paths
                possible_paths = [
                    os.path.join(os.getcwd(), "cursors", original_filename),
                    os.path.join(os.getcwd(), original_filename),
                    os.path.join(PROJECT_ROOT, original_filename),
                ]

                found = False
                for alt_path in possible_paths:
                    if os.path.exists(alt_path):
                        print(f"Found file at {alt_path}")
                        source_file_path = alt_path
                        found = True
                        break

                if not found:
                    print(
                        f"File not found in any expected location. Skipping {final_name}."
                    )
                    continue

            # Create a copy in the temp directory with the package name
            # Determine file extension from the original filename
            _, ext = os.path.splitext(original_filename)
            if not ext:
                ext = ".zip"  # Default extension if none is found

            # Clean the final name to remove any characters that might cause issues in filenames
            safe_name = "".join(
                c if c.isalnum() or c in "-_." else "_" for c in final_name
            )
            temp_file_path = os.path.join(temp_dir, f"{safe_name}{ext}")

            # Copy the file to temp directory
            print(f"Copying {original_filename} to {temp_file_path}...")
            try:
                shutil.copy2(source_file_path, temp_file_path)
                print(f"Copied to {temp_file_path}")

                # Run nix-store --add-fixed sha256 on the file
                print(f"Adding {final_name} to nix store...")
                try:
                    result = subprocess.run(
                        ["nix-store", "--add-fixed", "sha256", temp_file_path],
                        capture_output=True,
                        text=True,
                        check=True,
                    )

                    nix_store_path = result.stdout.strip()
                    if not nix_store_path:
                        print(f"Warning: Empty output from nix-store for {final_name}")
                        print(f"Command stdout: {result.stdout}")
                        print(f"Command stderr: {result.stderr}")
                        # Try to extract the path from stderr if possible
                        if "/nix/store/" in result.stderr:
                            import re

                            match = re.search(
                                r"(/nix/store/[a-z0-9]+-[^/\s]+)", result.stderr
                            )
                            if match:
                                nix_store_path = match.group(1)
                                print(f"Extracted path from stderr: {nix_store_path}")

                    nix_store_paths[final_name] = nix_store_path
                    print(f"Added to nix store: {nix_store_path}")
                except subprocess.CalledProcessError as e:
                    print(f"Error adding {final_name} to nix store: {e}")
                    print(f"Output: {e.stdout}")
                    print(f"Error: {e.stderr}")

            except IOError as e:
                print(f"Error copying {original_filename}: {e}")

        # Output results
        print("\nNix store paths:")
        for name, path in nix_store_paths.items():
            print(f"{name}: {path}")

        if nix_store_paths:
            # Create a JSON file with the results
            output_file = os.path.join(PROJECT_ROOT, "nix_store_paths.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(nix_store_paths, f, indent=2, sort_keys=True)

            print(f"\nResults saved to {output_file}")

            # Also save a copy in the current directory
            local_output = "nix_store_paths.json"
            with open(local_output, "w", encoding="utf-8") as f:
                json.dump(nix_store_paths, f, indent=2, sort_keys=True)

            print(f"Results also saved to {os.path.abspath(local_output)}")
        else:
            print("\nNo nix store paths were generated. Check for errors above.")


if __name__ == "__main__":
    try:
        # Check if nix-store is available
        try:
            subprocess.run(["nix-store", "--version"], capture_output=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            print(
                "Error: 'nix-store' command not found. Make sure Nix is installed and in your PATH."
            )
            sys.exit(1)

        main()
        print("Process completed successfully!")
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
