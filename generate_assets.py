"""
Generate MSIX-required icon assets for Zava Insurance Store package.
Creates all required PNG sizes from the SVG favicon concept.
Uses Pillow to draw the shield + checkmark icon programmatically.
"""
import math
from PIL import Image, ImageDraw

def create_icon(size, padding_ratio=0.15):
    """Create the Zava Insurance shield icon at given size."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * padding_ratio)
    inner = size - 2 * pad

    # Background rounded rectangle (green gradient approximation)
    corner_radius = int(size * 0.22)
    draw.rounded_rectangle(
        [0, 0, size - 1, size - 1],
        radius=corner_radius,
        fill=(6, 95, 70)  # #065f46
    )

    # Draw lighter top-left gradient overlay
    for i in range(size // 2):
        alpha = int(60 * (1 - i / (size // 2)))
        draw.line([(0, i), (size - i, 0)], fill=(16, 185, 129, alpha))

    # Shield outline
    cx, cy = size // 2, size // 2
    shield_h = int(inner * 0.75)
    shield_w = int(inner * 0.55)
    top = cy - int(shield_h * 0.45)
    bot = cy + int(shield_h * 0.55)

    # Shield path points
    shield_points = [
        (cx, top),  # top center
        (cx + shield_w // 2, top + shield_h // 4),  # right shoulder
        (cx + shield_w // 2, cy),  # right mid
        (cx + int(shield_w * 0.35), bot - shield_h // 6),  # right lower
        (cx, bot),  # bottom point
        (cx - int(shield_w * 0.35), bot - shield_h // 6),  # left lower
        (cx - shield_w // 2, cy),  # left mid
        (cx - shield_w // 2, top + shield_h // 4),  # left shoulder
    ]

    # Filled shield with slight transparency
    draw.polygon(shield_points, fill=(255, 255, 255, 40), outline=(255, 255, 255, 220))

    # Draw shield outline thicker
    line_w = max(2, size // 32)
    for i in range(len(shield_points)):
        p1 = shield_points[i]
        p2 = shield_points[(i + 1) % len(shield_points)]
        draw.line([p1, p2], fill=(255, 255, 255, 240), width=line_w)

    # Checkmark inside shield
    check_size = int(shield_w * 0.45)
    check_cx = cx
    check_cy = cy + int(shield_h * 0.05)
    check_points = [
        (check_cx - check_size // 2, check_cy),
        (check_cx - check_size // 6, check_cy + check_size // 3),
        (check_cx + check_size // 2, check_cy - check_size // 3),
    ]
    check_w = max(3, size // 20)
    draw.line(check_points[:2], fill=(255, 255, 255, 255), width=check_w)
    draw.line(check_points[1:], fill=(255, 255, 255, 255), width=check_w)

    return img


def create_wide_tile(width, height):
    """Create a wide tile with icon + text area."""
    img = Image.new('RGBA', (width, height), (6, 95, 70, 255))
    draw = ImageDraw.Draw(img)

    # Add gradient effect
    for i in range(width // 3):
        alpha = int(40 * (1 - i / (width // 3)))
        draw.line([(0, i), (width, i)], fill=(16, 185, 129, alpha))

    # Place icon on left side
    icon_size = int(height * 0.7)
    icon = create_icon(icon_size, padding_ratio=0.05)
    icon_x = int(width * 0.08)
    icon_y = (height - icon_size) // 2
    img.paste(icon, (icon_x, icon_y), icon)

    return img


def create_splash(width, height):
    """Create a splash screen."""
    img = Image.new('RGBA', (width, height), (6, 95, 70, 255))
    draw = ImageDraw.Draw(img)

    # Center icon
    icon_size = min(width, height) // 3
    icon = create_icon(icon_size, padding_ratio=0.05)
    x = (width - icon_size) // 2
    y = (height - icon_size) // 2
    img.paste(icon, (x, y), icon)

    return img


def main():
    import os
    out_dir = os.path.join(os.path.dirname(__file__), 'packaging', 'Assets')
    os.makedirs(out_dir, exist_ok=True)

    # Required MSIX assets
    assets = {
        'Square44x44Logo.png': (44, 44),
        'Square150x150Logo.png': (150, 150),
        'Square310x310Logo.png': (310, 310),
        'StoreLogo.png': (50, 50),
    }

    for name, (w, h) in assets.items():
        icon = create_icon(w)
        path = os.path.join(out_dir, name)
        icon.save(path, 'PNG')
        print(f"  Created {name} ({w}x{h})")

    # Wide tile
    wide = create_wide_tile(310, 150)
    wide.save(os.path.join(out_dir, 'Wide310x150Logo.png'), 'PNG')
    print(f"  Created Wide310x150Logo.png (310x150)")

    # Splash screen
    splash = create_splash(620, 300)
    splash.save(os.path.join(out_dir, 'SplashScreen.png'), 'PNG')
    print(f"  Created SplashScreen.png (620x300)")

    # Also create scaled versions (200% and 400% for high-DPI)
    scaled = {
        'Square44x44Logo.scale-200.png': (88, 88),
        'Square44x44Logo.scale-400.png': (176, 176),
        'Square150x150Logo.scale-200.png': (300, 300),
        'StoreLogo.scale-200.png': (100, 100),
        'StoreLogo.scale-400.png': (200, 200),
    }

    for name, (w, h) in scaled.items():
        icon = create_icon(w)
        path = os.path.join(out_dir, name)
        icon.save(path, 'PNG')
        print(f"  Created {name} ({w}x{h})")

    print(f"\nAll assets saved to: {out_dir}")


if __name__ == '__main__':
    main()
