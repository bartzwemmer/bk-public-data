"""
Wildflower Annotation Visualizer
Visualizes Pascal VOC bounding box annotations on high-resolution wildflower images.
Produces both a full-scene overview and a 1:1 detail zoom comparison.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont


# High-contrast color palette for species annotations
PALETTE = [
    (0, 229, 255),    # Cyan
    (255, 214, 0),    # Yellow
    (0, 230, 118),    # Lime green
    (255, 61, 0),     # Orange/Red
    (224, 64, 251),   # Magenta
    (0, 176, 255),    # Light Blue
    (255, 145, 0),    # Amber
    (118, 255, 3),    # Bright Lime
]

ARTIFACT_DIR = Path(r"C:\Users\bzwem\.gemini\antigravity-cli\brain\5bb163af-bb46-472a-b12b-47332dbf9ea1")


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Attempts to load a standard system TrueType font, falling back to default."""
    for font_path in [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def parse_voc_xml(xml_path: Path) -> dict:
    """Parses a Pascal VOC annotation XML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    filename = root.findtext("filename", "")
    size_elem = root.find("size")
    width = int(size_elem.findtext("width", 0)) if size_elem is not None else 0
    height = int(size_elem.findtext("height", 0)) if size_elem is not None else 0

    objects = []
    for obj in root.findall("object"):
        name = obj.findtext("name", "Unknown").strip()
        bnd = obj.find("bndbox")
        if bnd is not None:
            xmin = int(float(bnd.findtext("xmin", 0)))
            ymin = int(float(bnd.findtext("ymin", 0)))
            xmax = int(float(bnd.findtext("xmax", 0)))
            ymax = int(float(bnd.findtext("ymax", 0)))
            objects.append({
                "name": name,
                "box": (xmin, ymin, xmax, ymax),
                "width": xmax - xmin,
                "height": ymax - ymin,
            })

    return {
        "filename": filename,
        "width": width,
        "height": height,
        "objects": objects,
    }


def find_dense_crop_region(objects: list[dict], img_w: int, img_h: int, crop_w: int = 1400, crop_h: int = 900) -> tuple[int, int, int, int]:
    """Finds an image region with a rich cluster of flower bounding boxes for 1:1 detail inspection."""
    if not objects:
        return (0, 0, min(crop_w, img_w), min(crop_h, img_h))

    best_count = -1
    best_crop = (0, 0, crop_w, crop_h)

    # Test candidate centers based on actual object locations
    for obj in objects:
        cx, cy = (obj["box"][0] + obj["box"][2]) // 2, (obj["box"][1] + obj["box"][3]) // 2
        x1 = max(0, min(cx - crop_w // 2, img_w - crop_w))
        y1 = max(0, min(cy - crop_h // 2, img_h - crop_h))
        x2 = x1 + crop_w
        y2 = y1 + crop_h

        # Count objects inside this crop
        count = sum(1 for o in objects if x1 <= o["box"][0] and o["box"][2] <= x2 and y1 <= o["box"][1] and o["box"][3] <= y2)
        if count > best_count:
            best_count = count
            best_crop = (x1, y1, x2, y2)

    return best_crop


def draw_annotations(
    img: Image.Image,
    objects: list[dict],
    color_map: dict[str, tuple[int, int, int]],
    line_width: int = 6,
    font_size: int = 28,
    draw_labels: bool = True,
    crop_offset: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Draws bounding boxes and labels on an image copy."""
    annotated = img.copy()
    draw = ImageDraw.Draw(annotated, "RGBA")
    font = get_font(font_size)
    ox, oy = crop_offset

    for i, obj in enumerate(objects, 1):
        color = color_map.get(obj["name"], (255, 0, 0))
        xmin, ymin, xmax, ymax = obj["box"]
        # Adjust for crop offset if any
        xmin, xmax = xmin - ox, xmax - ox
        ymin, ymax = ymin - oy, ymax - oy

        # Bounding box rectangle
        draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=line_width)

        if draw_labels:
            label = f"{obj['name']}"
            # Text bounding box for badge background
            bbox = font.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad = 4

            # Position badge above box if space permits, otherwise below
            badge_y2 = ymin - 2 if ymin - th - pad * 2 > 0 else ymax + th + pad * 2 + 2
            badge_y1 = badge_y2 - th - pad * 2
            badge_x1 = xmin
            badge_x2 = xmin + tw + pad * 2

            # Semi-transparent background badge
            draw.rectangle(
                [badge_x1, badge_y1, badge_x2, badge_y2],
                fill=(*color, 210),
            )
            # Label text
            draw.text(
                (badge_x1 + pad, badge_y1 + pad - bbox[1]),
                label,
                fill=(0, 0, 0),
                font=font,
            )

    return annotated


def visualize(image_path: Path, xml_path: Path, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    anno_data = parse_voc_xml(xml_path)
    objects = anno_data["objects"]

    print(f"Loaded XML: {xml_path.name}")
    print(f"Image reference: {anno_data['filename']}")
    print(f"Total annotated flowers: {len(objects)}")

    # Assign distinct colors to species
    unique_species = sorted(list({o["name"] for o in objects}))
    color_map = {sp: PALETTE[i % len(PALETTE)] for i, sp in enumerate(unique_species)}
    for sp in unique_species:
        count = sum(1 for o in objects if o["name"] == sp)
        print(f"  * {sp}: {count} annotations")

    # Load high-res source image
    print(f"Loading {image_path.name}...")
    source_img = Image.open(image_path).convert("RGB")
    img_w, img_h = source_img.size

    # 1. Full Annotated Image
    print("Drawing full annotation overlay...")
    full_annotated = draw_annotations(
        img=source_img,
        objects=objects,
        color_map=color_map,
        line_width=8,        # Bold enough for 6720x4480
        font_size=36,
        draw_labels=True,
    )

    # 2. Display-friendly resized overview (max 2000px)
    scale = 2000 / max(img_w, img_h)
    new_w, new_h = int(img_w * scale), int(img_h * scale)
    overview_img = full_annotated.resize((new_w, new_h), Image.Resampling.LANCZOS)
    overview_path = output_dir / f"{image_path.stem}_annotated_overview.jpg"
    overview_img.save(overview_path, quality=90)
    print(f"Saved overview ({new_w}x{new_h}): {overview_path.name}")

    # 3. 1:1 High-Resolution Detail Crop (Raw vs Annotated Comparison)
    print("Generating 1:1 detail zoom comparison...")
    cx1, cy1, cx2, cy2 = find_dense_crop_region(objects, img_w, img_h, crop_w=1200, crop_h=800)
    crop_objects = [
        o for o in objects
        if cx1 <= o["box"][0] and o["box"][2] <= cx2 and cy1 <= o["box"][1] and o["box"][3] <= cy2
    ]

    raw_crop = source_img.crop((cx1, cy1, cx2, cy2))
    annotated_crop = draw_annotations(
        img=raw_crop,
        objects=crop_objects,
        color_map=color_map,
        line_width=4,
        font_size=24,
        draw_labels=True,
        crop_offset=(cx1, cy1),
    )

    # Combine Raw Crop and Annotated Crop into a side-by-side comparison image
    spacing = 20
    comp_w = (cx2 - cx1) * 2 + spacing
    comp_h = (cy2 - cy1) + 60
    comp_img = Image.new("RGB", (comp_w, comp_h), color=(30, 30, 30))
    header_font = get_font(32)
    header_draw = ImageDraw.Draw(comp_img)

    header_draw.text((20, 15), "Raw Image (1:1 Native Resolution)", fill=(240, 240, 240), font=header_font)
    header_draw.text(((cx2 - cx1) + spacing + 20, 15), f"Pascal VOC Annotations ({len(crop_objects)} flowers)", fill=(0, 229, 255), font=header_font)

    comp_img.paste(raw_crop, (0, 60))
    comp_img.paste(annotated_crop, ((cx2 - cx1) + spacing, 60))

    zoom_path = output_dir / f"{image_path.stem}_zoom_comparison.jpg"
    comp_img.save(zoom_path, quality=92)
    print(f"Saved 1:1 zoom comparison: {zoom_path.name}")

    # Also copy to artifact directory if it exists
    if ARTIFACT_DIR.exists():
        shutil.copy2(overview_path, ARTIFACT_DIR / overview_path.name)
        shutil.copy2(zoom_path, ARTIFACT_DIR / zoom_path.name)
        print(f"Copied visualization images to artifact folder: {ARTIFACT_DIR}")

    return {
        "overview": overview_path,
        "zoom": zoom_path,
    }


def main():
    parser = argparse.ArgumentParser(description="Visualize Pascal VOC annotations on wildflower images.")
    parser.add_argument("--image", default="20210402102531-Urban.jpg", help="Path to JPG image")
    parser.add_argument("--xml", default="20210402102531-Urban.xml", help="Path to VOC XML annotation")
    parser.add_argument("--output-dir", default=".", help="Directory to save output visualizations")
    args = parser.parse_args()

    image_path = Path(args.image).resolve()
    xml_path = Path(args.xml).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not image_path.exists():
        print(f"Error: Image file not found: {image_path}", file=sys.stderr)
        return 1
    if not xml_path.exists():
        print(f"Error: XML file not found: {xml_path}", file=sys.stderr)
        return 1

    visualize(image_path, xml_path, output_dir)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
