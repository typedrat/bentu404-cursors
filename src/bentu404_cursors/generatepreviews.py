import json
import os
import requests
from urllib.parse import urlparse

CURSORS_JSON = "cursors/download_tracking.json"
OVERRIDES_JSON = "overrides.json"
PREVIEW_DIR = "previews"
README_PATH = os.path.join(PREVIEW_DIR, "README.md")

def get_extension_from_url(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext if ext else ".gif"

def main():
    with open(CURSORS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(OVERRIDES_JSON, "r", encoding="utf-8") as f:
        overrides = json.load(f)

    data.sort(key=lambda x: x["name"])

    os.makedirs(PREVIEW_DIR, exist_ok=True)

    table_rows = [["Package", "Preview"]]

    for entry in data:
        raw_name = entry["name"]
        final_name = overrides.get(raw_name, raw_name)
        ext = get_extension_from_url(entry["preview_image"])
        image_path = os.path.join(PREVIEW_DIR, f"{final_name}{ext}")

        # Download preview image
        print(f"Downloading preview for {final_name}...")
        response = requests.get(entry["preview_image"])
        response.raise_for_status()
        with open(image_path, "wb") as f:
            f.write(response.content)

        # Add row to markdown table
        md_name = f"`{final_name}`"
        md_img = f"[![]({final_name}{ext})]({entry['url']})"
        table_rows.append([md_name, md_img])

    # Write README.md
    print(f"Writing {README_PATH}...")
    with open(README_PATH, "w", encoding="utf-8") as f:
        col_widths = [max(len(row[i]) for row in table_rows) for i in range(2)]
        def fmt_row(row):
            return "| " + " | ".join(f"{cell:<{col_widths[i]}}" for i, cell in enumerate(row)) + " |"

        f.write(fmt_row(table_rows[0]) + "\n")
        f.write("| :---: | --- |\n")
        for row in table_rows[1:]:
            f.write(fmt_row(row) + "\n")

if __name__ == "__main__":
    main()
