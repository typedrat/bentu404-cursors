#!/usr/bin/env python3
import os
import sys
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom
from wand.image import Image


def png2svg(png_path, svg_path, scale=1):
    """Convert a PNG to SVG with optimized rectangle conversion using wand."""
    with Image(filename=png_path) as img:
        width, height = img.width, img.height

        # Create SVG root
        svg = ET.Element(
            "svg",
            {
                "width": str(width * scale),
                "height": str(height * scale),
                "xmlns": "http://www.w3.org/2000/svg",
                "version": "1.1",
                "viewBox": f"0 0 {width * scale} {height * scale}",
                "shape-rendering": "crispEdges",  # Ensures pixel-perfect rendering
            },
        )

        # Add a background group to collect all rectangles
        # This ensures consistent rendering across browsers
        pixel_group = ET.SubElement(svg, "g")

        # Get all pixel data
        img.depth = 8  # Ensure 8-bit channels
        pixel_view = img.export_pixels(channel_map="RGBA")

        # Create a 2D grid to store pixel data and processing state
        # Each cell contains (color, opacity) or None for transparent pixels
        grid = []
        for y in range(height):
            row = []
            for x in range(width):
                idx = (y * width + x) * 4  # RGBA has 4 channels
                r = pixel_view[idx]
                g = pixel_view[idx + 1]
                b = pixel_view[idx + 2]
                a = pixel_view[idx + 3]

                if a == 0:  # Skip fully transparent pixels
                    row.append(None)
                else:
                    opacity = a / 255.0
                    color = f"rgb({r},{g},{b})"
                    row.append((color, opacity))
            grid.append(row)

        # First phase: combine horizontally
        horizontal_runs = []
        for y in range(height):
            x = 0
            while x < width:
                if grid[y][x] is None:
                    x += 1
                    continue

                # Start a new run
                start_x = x
                color, opacity = grid[y][x]

                # Extend run as far as possible horizontally
                while x < width and grid[y][x] == (color, opacity):
                    x += 1

                # Add the run (y, start_x, end_x, color, opacity)
                horizontal_runs.append((y, start_x, x, color, opacity))

        # Second phase: combine runs vertically where possible
        rectangles = []
        while horizontal_runs:
            y, start_x, end_x, color, opacity = horizontal_runs.pop(0)
            height_run = 1

            # Try to find matching runs below this one
            i = 0
            while i < len(horizontal_runs):
                next_y, next_start_x, next_end_x, next_color, next_opacity = (
                    horizontal_runs[i]
                )

                # Check if this run is directly below and matches in x-coords and color
                if (
                    next_y == y + height_run
                    and next_start_x == start_x
                    and next_end_x == end_x
                    and next_color == color
                    and next_opacity == opacity
                ):
                    # Extend vertically
                    height_run += 1
                    horizontal_runs.pop(i)
                else:
                    i += 1

            # Add the optimized rectangle
            rectangles.append((start_x, y, end_x - start_x, height_run, color, opacity))

        # Create SVG elements for each rectangle
        for x, y, width_px, height_px, color, opacity in rectangles:
            rect = ET.SubElement(
                pixel_group,
                "rect",
                {
                    "x": str(x * scale),
                    "y": str(y * scale),
                    "width": str(width_px * scale + 0.5),  # Slight overlap
                    "height": str(height_px * scale + 0.5),  # Slight overlap
                    "fill": color,
                    "stroke": color,  # Add stroke matching fill color
                    "stroke-width": "0.5",  # Thin stroke to fill gaps
                },
            )

            if opacity < 1.0:
                rect.set("fill-opacity", str(opacity))
                rect.set("stroke-opacity", str(opacity))

        # Convert to string
        rough_string = ET.tostring(svg, "utf-8")

        # Clean up the XML
        reparsed = minidom.parseString(rough_string)
        pretty_svg = reparsed.toprettyxml(indent="  ")

        # Remove XML declaration which can cause issues in some contexts
        pretty_svg = "\n".join(pretty_svg.split("\n")[1:])

        # Write to file
        with open(svg_path, "w") as f:
            f.write(pretty_svg)


def process_directory(input_dir, output_dir, scale=1):
    """Process all PNGs in a directory tree and copy all other files."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for root, dirs, files in os.walk(input_dir):
        # Create equivalent output directory structure
        rel_path = os.path.relpath(root, input_dir)
        out_subdir = os.path.join(output_dir, rel_path)

        if not os.path.exists(out_subdir):
            os.makedirs(out_subdir)

        for file in files:
            # Create paths
            source_path = os.path.join(root, file)
            dest_path = os.path.join(out_subdir, file)

            if file.lower().endswith(".png"):
                # Convert PNGs to SVG
                svg_path = dest_path.replace(".png", ".svg").replace(".PNG", ".svg")
                png2svg(source_path, svg_path, scale)
                print(f"Converted: {source_path} → {svg_path}")
            else:
                # Copy all other files directly
                shutil.copy2(source_path, dest_path)
                print(f"Copied: {source_path} → {dest_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python png2svg.py <input_dir> <output_dir> [scale]")
        sys.exit(1)

    scale = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    process_directory(sys.argv[1], sys.argv[2], scale)


if __name__ == "__main__":
    main()
