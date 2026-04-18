#!/usr/bin/env python3
"""Generate placeholder thumbnail images for invoice PDF templates.

Each thumbnail is 400x560 pixels (A4 proportions ~1:1.4) with:
- A coloured header bar at the top using the template's primary colour
- A background matching the template's header background colour
- The template display name centred on the image
- A simplified representation of the template layout (logo position, line-item table)
"""

import os
from PIL import Image, ImageDraw, ImageFont

# Template definitions: (id, display_name, primary_colour, header_bg_colour, logo_position, layout_type)
TEMPLATES = [
    ("classic", "Classic", "#2563eb", "#ffffff", "left", "standard"),
    ("modern-dark", "Modern Dark", "#6366f1", "#1e1b4b", "left", "standard"),
    ("compact-blue", "Compact Blue", "#0284c7", "#f0f9ff", "left", "compact"),
    ("bold-header", "Bold Header", "#dc2626", "#1a1a1a", "center", "standard"),
    ("minimal", "Minimal", "#374151", "#ffffff", "left", "standard"),
    ("trade-pro", "Trade Pro", "#059669", "#ecfdf5", "side", "standard"),
    ("corporate", "Corporate", "#1e3a5f", "#f8fafc", "center", "standard"),
    ("compact-green", "Compact Green", "#16a34a", "#f0fdf4", "left", "compact"),
    ("elegant", "Elegant", "#7c3aed", "#faf5ff", "center", "standard"),
    ("compact-mono", "Compact Mono", "#1a1a1a", "#fafafa", "side", "compact"),
    ("sunrise", "Sunrise", "#ea580c", "#fff7ed", "side", "standard"),
    ("ocean", "Ocean", "#0891b2", "#ecfeff", "left", "standard"),
]

WIDTH = 400
HEIGHT = 560
HEADER_HEIGHT = 80
TABLE_ROW_HEIGHT_STANDARD = 24
TABLE_ROW_HEIGHT_COMPACT = 18


def hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    """Convert hex colour string to RGB tuple."""
    h = hex_colour.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def lighten(rgb: tuple[int, int, int], factor: float = 0.3) -> tuple[int, int, int]:
    """Lighten an RGB colour towards white."""
    return tuple(min(255, int(c + (255 - c) * factor)) for c in rgb)


def darken(rgb: tuple[int, int, int], factor: float = 0.3) -> tuple[int, int, int]:
    """Darken an RGB colour towards black."""
    return tuple(max(0, int(c * (1 - factor))) for c in rgb)


def text_colour_for_bg(bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return black or white text depending on background luminance."""
    luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
    return (255, 255, 255) if luminance < 140 else (30, 30, 30)


def generate_thumbnail(
    template_id: str,
    display_name: str,
    primary_hex: str,
    header_bg_hex: str,
    logo_position: str,
    layout_type: str,
    output_dir: str,
) -> str:
    """Generate a single placeholder thumbnail PNG."""
    primary_rgb = hex_to_rgb(primary_hex)
    header_bg_rgb = hex_to_rgb(header_bg_hex)

    img = Image.new("RGB", (WIDTH, HEIGHT), header_bg_rgb)
    draw = ImageDraw.Draw(img)

    # --- Header bar ---
    draw.rectangle([0, 0, WIDTH, HEADER_HEIGHT], fill=primary_rgb)
    header_text_colour = text_colour_for_bg(primary_rgb)

    # Try to load a font; fall back to default
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large
        font_tiny = font_large

    # --- Logo placeholder based on position ---
    logo_box_w, logo_box_h = 50, 40
    logo_y = (HEADER_HEIGHT - logo_box_h) // 2

    if logo_position == "left":
        logo_x = 16
        # Company name to the right of logo
        draw.rectangle([logo_x, logo_y, logo_x + logo_box_w, logo_y + logo_box_h],
                       fill=lighten(primary_rgb, 0.2), outline=header_text_colour)
        draw.text((logo_x + 8, logo_y + 10), "LOGO", fill=header_text_colour, font=font_tiny)
        draw.text((logo_x + logo_box_w + 12, logo_y + 2), "Company Name", fill=header_text_colour, font=font_medium)
        draw.text((logo_x + logo_box_w + 12, logo_y + 22), "INVOICE", fill=header_text_colour, font=font_small)
    elif logo_position == "center":
        logo_x = (WIDTH - logo_box_w) // 2
        draw.rectangle([logo_x, logo_y - 5, logo_x + logo_box_w, logo_y - 5 + logo_box_h],
                       fill=lighten(primary_rgb, 0.2), outline=header_text_colour)
        draw.text((logo_x + 8, logo_y + 5), "LOGO", fill=header_text_colour, font=font_tiny)
        # Company name centred below logo area
        bbox = draw.textbbox((0, 0), "Company Name", font=font_small)
        tw = bbox[2] - bbox[0]
        draw.text(((WIDTH - tw) // 2, logo_y + logo_box_h), "Company Name", fill=header_text_colour, font=font_small)
    else:  # side
        logo_x = WIDTH - logo_box_w - 16
        draw.rectangle([logo_x, logo_y, logo_x + logo_box_w, logo_y + logo_box_h],
                       fill=lighten(primary_rgb, 0.2), outline=header_text_colour)
        draw.text((logo_x + 8, logo_y + 10), "LOGO", fill=header_text_colour, font=font_tiny)
        draw.text((16, logo_y + 2), "Company Name", fill=header_text_colour, font=font_medium)
        draw.text((16, logo_y + 22), "INVOICE", fill=header_text_colour, font=font_small)

    body_text_colour = text_colour_for_bg(header_bg_rgb)
    muted_colour = lighten(body_text_colour, 0.4) if sum(body_text_colour) < 400 else darken(body_text_colour, 0.4)

    # --- Invoice details section ---
    y = HEADER_HEIGHT + 16
    draw.text((16, y), "Invoice #INV-0042", fill=body_text_colour, font=font_medium)
    draw.text((WIDTH - 140, y), "Date: 15 Jan 2026", fill=muted_colour, font=font_small)
    y += 24

    # Bill To section
    draw.text((16, y), "Bill To:", fill=muted_colour, font=font_small)
    y += 16
    draw.text((16, y), "James Wilson", fill=body_text_colour, font=font_medium)
    y += 18
    draw.text((16, y), "Wilson Contracting Ltd", fill=muted_colour, font=font_small)
    y += 28

    # --- Line items table ---
    table_x = 16
    table_w = WIDTH - 32
    row_h = TABLE_ROW_HEIGHT_COMPACT if layout_type == "compact" else TABLE_ROW_HEIGHT_STANDARD

    # Table header
    draw.rectangle([table_x, y, table_x + table_w, y + row_h], fill=primary_rgb)
    th_text = text_colour_for_bg(primary_rgb)
    draw.text((table_x + 6, y + (row_h - 11) // 2), "Description", fill=th_text, font=font_tiny)
    draw.text((table_x + table_w - 120, y + (row_h - 11) // 2), "Qty", fill=th_text, font=font_tiny)
    draw.text((table_x + table_w - 80, y + (row_h - 11) // 2), "Rate", fill=th_text, font=font_tiny)
    draw.text((table_x + table_w - 42, y + (row_h - 11) // 2), "Amount", fill=th_text, font=font_tiny)
    y += row_h

    # Table rows
    line_items = [
        ("Full vehicle service", "1", "$250.00", "$250.00"),
        ("Engine oil 5W-30 (5L)", "1", "$89.50", "$89.50"),
        ("Oil filter", "1", "$24.00", "$24.00"),
        ("Brake pad replacement", "1.5", "$95.00", "$142.50"),
    ]

    stripe_colour = lighten(primary_rgb, 0.85) if sum(header_bg_rgb) > 600 else lighten(header_bg_rgb, 0.15)

    for i, (desc, qty, rate, amount) in enumerate(line_items):
        if i % 2 == 1:
            draw.rectangle([table_x, y, table_x + table_w, y + row_h], fill=stripe_colour)
        draw.text((table_x + 6, y + (row_h - 9) // 2), desc, fill=body_text_colour, font=font_tiny)
        draw.text((table_x + table_w - 120, y + (row_h - 9) // 2), qty, fill=body_text_colour, font=font_tiny)
        draw.text((table_x + table_w - 80, y + (row_h - 9) // 2), rate, fill=body_text_colour, font=font_tiny)
        draw.text((table_x + table_w - 42, y + (row_h - 9) // 2), amount, fill=body_text_colour, font=font_tiny)
        y += row_h

    # Table bottom border
    draw.line([table_x, y, table_x + table_w, y], fill=primary_rgb, width=1)
    y += 12

    # --- Totals ---
    totals_x = WIDTH - 160
    draw.text((totals_x, y), "Subtotal:", fill=muted_colour, font=font_small)
    draw.text((totals_x + 80, y), "$506.00", fill=body_text_colour, font=font_small)
    y += 18
    draw.text((totals_x, y), "GST (15%):", fill=muted_colour, font=font_small)
    draw.text((totals_x + 80, y), "$75.90", fill=body_text_colour, font=font_small)
    y += 18
    draw.line([totals_x, y, totals_x + 150, y], fill=primary_rgb, width=2)
    y += 6
    draw.text((totals_x, y), "Total:", fill=body_text_colour, font=font_medium)
    draw.text((totals_x + 80, y), "$581.90", fill=body_text_colour, font=font_medium)
    y += 30

    # --- Payment status banner ---
    banner_h = 28
    banner_colour = lighten(primary_rgb, 0.7)
    draw.rectangle([table_x, y, table_x + table_w, y + banner_h], fill=banner_colour)
    bbox = draw.textbbox((0, 0), "BALANCE DUE: $581.90", font=font_small)
    tw = bbox[2] - bbox[0]
    draw.text(((WIDTH - tw) // 2, y + 8), "BALANCE DUE: $581.90",
              fill=darken(primary_rgb, 0.2), font=font_small)
    y += banner_h + 16

    # --- Footer area ---
    footer_y = HEIGHT - 40
    draw.line([16, footer_y, WIDTH - 16, footer_y], fill=lighten(primary_rgb, 0.5), width=1)
    draw.text((16, footer_y + 8), "Thank you for your business", fill=muted_colour, font=font_tiny)

    # --- Template name label (bottom-right) ---
    label = f"{display_name} Template"
    bbox = draw.textbbox((0, 0), label, font=font_small)
    lw = bbox[2] - bbox[0]
    draw.text((WIDTH - lw - 16, footer_y + 8), label, fill=muted_colour, font=font_small)

    # --- Layout type badge ---
    if layout_type == "compact":
        badge_text = "COMPACT"
        badge_colour = darken(primary_rgb, 0.1)
        bbox = draw.textbbox((0, 0), badge_text, font=font_tiny)
        bw = bbox[2] - bbox[0]
        bx = WIDTH - bw - 24
        by = HEADER_HEIGHT + 4
        draw.rectangle([bx, by, bx + bw + 8, by + 14], fill=badge_colour)
        draw.text((bx + 4, by + 2), badge_text, fill=text_colour_for_bg(badge_colour), font=font_tiny)

    # Save
    output_path = os.path.join(output_dir, f"{template_id}.png")
    img.save(output_path, "PNG")
    return output_path


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "templates")
    os.makedirs(output_dir, exist_ok=True)

    for template_id, display_name, primary, header_bg, logo_pos, layout in TEMPLATES:
        path = generate_thumbnail(template_id, display_name, primary, header_bg, logo_pos, layout, output_dir)
        print(f"  ✓ {path}")

    print(f"\nGenerated {len(TEMPLATES)} thumbnail images in {output_dir}")


if __name__ == "__main__":
    main()
