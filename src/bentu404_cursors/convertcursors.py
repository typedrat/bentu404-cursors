#!/usr/bin/env python3

import chardet
import os
import sys
import argparse
import toml
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from wininfparser import WinINF
from win2xcur import shadow
from win2xcur.parser import open_blob
from wand.image import Image
from .png2svg import png2svg


@dataclass
class ThemeConfig:
    """Class to store theme configuration."""

    THEME_NAME: str = "Unknown"
    THEME_DESCRIPTION: str = "Converted with convert-cursors.py"
    THEME_VERSION: str = "1.0"
    THEME_AUTHOR: str = "bentu404"
    OUTPUT_DIR: str = ""  # Main output directory
    # Base cursor size and hotspots will be determined from the actual cursor images
    XCUR_SIZES: List[int] = field(default_factory=lambda: [24, 32, 48, 64])
    cursor_mappings: Dict[str, str] = field(default_factory=dict)
    cursor_hotspots: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    cursor_symlinks: Dict[str, List[str]] = field(default_factory=dict)
    cursor_animated: Dict[str, bool] = field(default_factory=dict)
    cursor_anim_delay: Dict[str, int] = field(default_factory=dict)


def parse_install_inf(input_dir, output_dir):
    """Parse the Install.inf file to get cursor names and theme info."""
    inf_path = os.path.join(input_dir, "install.inf")

    if not os.path.isfile(inf_path):
        print(f"Error: install.inf not found in {input_dir}")
        sys.exit(1)

    encoding = 'gbk' # assuming because it's a Chinese Windows system

    # Parse INF file using wininfparser
    inf_file = WinINF()
    inf_file.ParseFile(inf_path, encoding)

    # Get the Strings section
    strings_section = inf_file["Strings"]
    if strings_section is None:
        print("Error: [Strings] section not found in install.inf")
        sys.exit(1)

    # Extract theme name
    theme_name = None
    if strings_section["SCHEME_NAME"] != "":
        theme_name = strings_section["SCHEME_NAME"].replace('"', "")

    # Default fallback
    if not theme_name:
        theme_name = "Unknown"

    print(f"Theme name: {theme_name}")

    # Create theme config
    theme_config = ThemeConfig(THEME_NAME=theme_name)

    # Extract cursor file names
    cursor_types = [
        "pointer",
        "help",
        "working",
        "busy",
        "precision",
        "text",
        "hand",
        "unavailable",
        "vert",
        "horz",
        "dgn1",
        "dgn2",
        "move",
        "alternate",
        "link",
        "person",
        "pin",
    ]

    # Standard mappings for cursor symlinks (Windows to X11/Wayland names)
    # Reference: https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/cursor-shape/cursor-shape-v1.xml#L71
    standard_mappings = {
        "pointer": [
            "default",
            "arrow",
            "left_ptr",
            "size-ver",
            "size-hor",
            "size-bdiag",
            "size-fdiag",
            "top_left_arrow",
        ],
        "text": ["xterm", "ibeam"],
        "horz": [
            "size_hor",
            "w-resize",
            "ew-resize",
            "e-resize",
            "h_double_arrow",
            "sb_h_double_arrow",
        ],
        "vert": [
            "ns-resize",
            "size_ver",
            "n-resize",
            "s-resize",
            "v_double_arrow",
            "sb_v_double_arrow",
        ],
        "move": ["all-scroll", "fleur", "size_all"],
        "dgn2": ["size_bdiag", "ne-resize", "nesw-resize", "sw-resize"],
        "dgn1": ["size_fdiag", "nw-resize", "nwse-resize", "se-resize"],
        "working": ["progress", "half-busy", "left_ptr_watch"],
        "busy": ["wait", "watch"],
        "unavailable": [
            "not-allowed",
            "crossed_circle",
            "circle",
            "no-drop",
            "forbidden",
        ],
        "precision": ["crosshair", "tcross", "cross"],
        "help": ["left_ptr_help", "question_arrow", "whats_this"],
        "link": ["hand1", "hand2", "pointer", "pointing_hand"],
        "hand": ["pencil"],
        "alternate": ["context-menu", "right_ptr"],
        "person": ["man"],
        "pin": [],
    }

    # Default hotspots for cursor types
    default_hotspots = {
        "pointer": (5, 5),
        "help": (15, 15),
        "working": (15, 15),
        "busy": (15, 15),
        "precision": (15, 15),
        "text": (15, 15),
        "hand": (15, 15),
        "unavailable": (15, 15),
        "vert": (15, 15),
        "horz": (15, 15),
        "dgn1": (15, 15),
        "dgn2": (15, 15),
        "move": (15, 15),
        "alternate": (10, 5),
        "link": (10, 10),
        "person": (15, 15),
        "pin": (15, 15),
    }

    # Initialize cursor symlinks and hotspots
    for cursor_type, symlinks in standard_mappings.items():
        theme_config.cursor_symlinks[cursor_type] = symlinks
        # Set default hotspots
        if cursor_type in default_hotspots:
            theme_config.cursor_hotspots[cursor_type] = default_hotspots[cursor_type]
        else:
            # Hotspots will be determined from the cursor image when processing the file
            pass

    print(f"Initialized {len(standard_mappings)} standard cursor type mappings")

    # If cursor values not found in Strings section, try extracting directly
    for cursor_type in cursor_types:
        value = None
        if cursor_type in strings_section:
            value = strings_section[cursor_type]

        if not value:
            # Try to extract from file content
            with open(inf_path, "r", encoding=encoding, errors="ignore") as f:
                content = f.read()
                import re

                cursor_match = re.search(
                    rf'{cursor_type}\s*=\s*"([^"]+)"', content, re.IGNORECASE
                )
                if cursor_match:
                    value = cursor_match.group(1)

        if value:
            base_name = os.path.splitext(value)[0]
            theme_config.cursor_mappings[cursor_type] = base_name
            print(f"Found cursor: {cursor_type} -> {base_name}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    return theme_config


def create_dirs(output_dir, theme_config):
    """Create output directory structures for accurse theme."""
    theme_name = theme_config.THEME_NAME
    # Clean theme name for directory
    clean_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in theme_name)

    # Create output directory for the accurse theme
    output_theme_dir = os.path.join(output_dir, clean_name)
    os.makedirs(output_theme_dir, exist_ok=True)
    print(f"Created output directory: {output_theme_dir}")

    # Update theme config with paths
    theme_config.OUTPUT_DIR = output_theme_dir

    return clean_name


def extract_cursor_images(input_dir, theme_config, add_shadow=False):
    """Extract cursor images from .ani and .cur files for accurse."""
    output_dir = theme_config.OUTPUT_DIR

    # Create a temporary directory that will be automatically cleaned up
    with tempfile.TemporaryDirectory() as tmp_dir:
        print("Extracting cursor images from .ani and .cur files...")
        print("Using original image sizes and hotspots from cursor files")

        # Process cursor files
        def process_cursor_file(file_path, cursor_type, output_name=None):
            base_name = os.path.basename(file_path)

            try:
                # Read the binary blob
                with open(file_path, "rb") as f:
                    blob = f.read()

                # Parse the cursor
                cursor = open_blob(blob)

                # Apply shadow if requested
                if add_shadow and cursor.frames:
                    shadow.apply_to_frames(
                        cursor.frames,
                        color="#000000",
                        radius=0.1,
                        sigma=0.1,
                        xoffset=0.05,
                        yoffset=0.05,
                    )

                # Check if animated
                is_animated = len(cursor.frames) > 1
                theme_config.cursor_animated[cursor_type] = is_animated

                if is_animated:
                    # Set animation delay (use the first frame's delay or default to 25ms)
                    delay = (
                        int(cursor.frames[0].delay * 1000)
                        if cursor.frames[0].delay > 0
                        else 25
                    )
                    theme_config.cursor_anim_delay[cursor_type] = delay

                    # Create directory for animated cursor
                    cursor_dir = os.path.join(output_dir, output_name or cursor_type)
                    os.makedirs(cursor_dir, exist_ok=True)

                    # Process each frame
                    for frame_idx, frame in enumerate(cursor.frames):
                        # Get the largest image in the frame
                        largest_image = max(frame.images, key=lambda img: img.nominal)
                        hotspot = largest_image.hotspot

                        # Set hotspot
                        if frame_idx == 0:
                            # Use original hotspot values from the cursor file
                            x_hotspot, y_hotspot = hotspot
                            theme_config.cursor_hotspots[cursor_type] = (
                                x_hotspot,
                                y_hotspot,
                            )

                        # Save the frame as PNG
                        png_path = os.path.join(
                            tmp_dir,
                            f"{output_name or cursor_type}-{frame_idx + 1:02d}.png",
                        )

                        with Image(image=largest_image.image) as img:
                            # Save without resizing
                            img.save(filename=png_path)

                        # Convert PNG to SVG
                        svg_path = os.path.join(
                            cursor_dir,
                            f"{output_name or cursor_type}-{frame_idx + 1:02d}.svg",
                        )
                        png2svg(png_path, svg_path)
                        print(f"Created {svg_path}")
                else:
                    # Static cursor
                    # Get the largest image
                    largest_image = max(
                        cursor.frames[0].images, key=lambda img: img.nominal
                    )
                    hotspot = largest_image.hotspot

                    # Use original hotspot values from the cursor file
                    x_hotspot, y_hotspot = hotspot
                    theme_config.cursor_hotspots[cursor_type] = (x_hotspot, y_hotspot)

                    # Save as PNG
                    png_path = os.path.join(
                        tmp_dir, f"{output_name or cursor_type}.png"
                    )

                    with Image(image=largest_image.image) as img:
                        # Save without resizing
                        img.save(filename=png_path)

                    # Convert PNG to SVG
                    svg_path = os.path.join(
                        output_dir, f"{output_name or cursor_type}.svg"
                    )
                    png2svg(png_path, svg_path)
                    print(f"Created {svg_path}")

                print(f"Processed {base_name} for cursor type {cursor_type}")
                return True
            except Exception as e:
                print(f"Warning: Error processing {base_name}: {e}")
                return False

        # Process cursor files based on mappings
        success_count = 0
        processed_mappings = {}

        # Filter out cursor types with empty symlink lists
        for cursor_type, symlinks in theme_config.cursor_symlinks.items():
            if not symlinks:  # Skip empty lists
                continue

            # Use the first element of the list as the output name
            output_name = symlinks[0]
            if cursor_type in theme_config.cursor_mappings:
                processed_mappings[cursor_type] = (
                    theme_config.cursor_mappings[cursor_type],
                    output_name,
                )

        total_count = len(processed_mappings)
        print(f"Found {total_count} cursor mappings to process")

        for cursor_type, (cursor_file, output_name) in processed_mappings.items():
            print(
                f"Processing cursor: {cursor_type} -> {cursor_file} (output as {output_name})"
            )

            # Look for .ani file first
            ani_file = os.path.join(input_dir, f"{cursor_file}.ani")
            if os.path.exists(ani_file):
                print(f"Found .ani file: {ani_file}")
                if process_cursor_file(ani_file, cursor_type, output_name):
                    success_count += 1
                continue

            # If .ani not found, look for .cur file
            cur_file = os.path.join(input_dir, f"{cursor_file}.cur")
            if os.path.exists(cur_file):
                print(f"Found .cur file: {cur_file}")
                if process_cursor_file(cur_file, cursor_type, output_name):
                    success_count += 1
                continue

            print(
                f"Warning: Could not find cursor file for {cursor_type} -> {cursor_file}"
            )

        print(
            f"Cursor extraction completed: {success_count}/{total_count} cursors processed successfully."
        )

        # Temporary directory is automatically cleaned up when the with-block exits


def create_metadata_toml(theme_config):
    """Create metadata.toml file for accurse theme."""
    # Prepare theme data
    metadata = {
        "theme": {
            "name": theme_config.THEME_NAME,
            "description": theme_config.THEME_DESCRIPTION,
            "version": theme_config.THEME_VERSION,
            "author": theme_config.THEME_AUTHOR,
        },
        "config": {
            "shape_size": 32,
            "x_hotspot": 15,
            "y_hotspot": 15,
            "xcur_sizes": theme_config.XCUR_SIZES,
        },
        "cursors": {},
    }

    # Add cursor definitions
    for cursor_type in theme_config.cursor_mappings:
        if (
            cursor_type not in theme_config.cursor_hotspots
            or not theme_config.cursor_symlinks.get(cursor_type, [])
        ):
            continue

        # Use the first element of symlinks as the cursor name
        cursor_name = theme_config.cursor_symlinks[cursor_type][0]

        cursor_data = {}

        # Always add hotspot from the cursor image
        x_hotspot, y_hotspot = theme_config.cursor_hotspots[cursor_type]
        cursor_data["x_hotspot"] = x_hotspot
        cursor_data["y_hotspot"] = y_hotspot

        # Add symlinks if any (excluding the first element which is used as the cursor name)
        if (
            cursor_type in theme_config.cursor_symlinks
            and len(theme_config.cursor_symlinks[cursor_type]) > 1
        ):
            cursor_data["symlinks"] = theme_config.cursor_symlinks[cursor_type][1:]

        # Add animation properties if animated
        if (
            cursor_type in theme_config.cursor_animated
            and theme_config.cursor_animated[cursor_type]
        ):
            cursor_data["animated"] = 1
            if cursor_type in theme_config.cursor_anim_delay:
                cursor_data["anim_delay"] = theme_config.cursor_anim_delay[cursor_type]

        # Add to metadata if we have data
        if cursor_data:
            metadata["cursors"][cursor_name] = cursor_data

    # Write the metadata.toml file
    metadata_path = os.path.join(theme_config.OUTPUT_DIR, "metadata.toml")
    with open(metadata_path, "w", encoding="utf-8") as f:
        toml.dump(metadata, f)

    print(f"Created metadata.toml at {metadata_path}")
    return True


# Function removed - replaced by create_metadata_toml


def main():
    parser = argparse.ArgumentParser(
        description="Convert Windows cursors to accurse theme format"
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=".",
        help="Directory containing .ani/.cur files and install.inf",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="./output",
        help="Output directory for the converted cursor theme",
    )

    parser.add_argument(
        "-s", "--shadow", action="store_true", help="Add shadow effect to cursors"
    )

    parser.add_argument(
        "-v", "--version", type=str, default="0.1", help="Theme version (default: 0.1)"
    )

    parser.add_argument(
        "-d",
        "--description",
        type=str,
        default="Converted with convert-cursors.py",
        help="Theme description",
    )

    parser.add_argument(
        "-x",
        "--xcursizes",
        nargs="+",
        type=int,
        default=[24, 32, 48, 64],
        help="X11 cursor sizes to generate (default: 24 32 48 64)",
    )

    parser.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Override theme name (default: use name from INF file)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Cursor Converter for Windows Cursors to accurse Theme Format")
    print("=" * 60)
    print(f"Input directory: {args.input_dir}")
    print(f"Output directory: {args.output_dir}")
    print(f"X11 cursor sizes: {args.xcursizes}")
    print(f"Add shadow: {args.shadow}")
    print("=" * 60)

    # Verify input directory exists
    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory '{args.input_dir}' does not exist!")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Parse INF file
    theme_config = parse_install_inf(args.input_dir, args.output_dir)

    # Update theme config with command-line parameters
    theme_config.THEME_VERSION = args.version
    theme_config.THEME_DESCRIPTION = args.description
    theme_config.XCUR_SIZES = args.xcursizes

    # Override theme name if provided
    if args.name:
        theme_config.THEME_NAME = args.name
        print(f"Using custom theme name: {args.name}")

    # Create output directories
    create_dirs(args.output_dir, theme_config)

    # Extract cursor images
    extract_cursor_images(args.input_dir, theme_config, add_shadow=args.shadow)

    # Create metadata.toml file
    create_metadata_toml(theme_config)

    print("\n" + "=" * 60)
    print("Conversion completed successfully!")
    print("=" * 60)
    print(f"Output theme directory: {theme_config.OUTPUT_DIR}")
    print("\nNext steps:")
    print("1. To compile the cursor theme, use:")
    print(f"   accurse {os.path.join(theme_config.OUTPUT_DIR, 'metadata.toml')}")
    print("\n2. After compilation, copy the theme to your icons directory:")
    print(f"   cp -r {theme_config.OUTPUT_DIR} ~/.local/share/icons/")
    print("=" * 60)


if __name__ == "__main__":
    main()
