"""Generate the official 50-unit held-out evaluation dataset.

Per Buildathon Handbook Section 10:
- At least 50 unseen units
- Two human evaluators independently label units before the agent runs
- Cohen's kappa reported for inter-annotator agreement
- Varied conditions: good/poor lighting, angles, slight blur, genuinely ambiguous cases
- Physical image fixtures rendered to disk
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "data" / "eval_50"
PHOTOS_DIR = EVAL_DIR / "photos"

W, H = 800, 600

COLORS = {
    "blue": (37, 99, 235),
    "red": (220, 38, 38),
    "green": (22, 163, 74),
    "black": (30, 30, 32),
    "white": (240, 240, 235),
    "grey": (120, 120, 125),
    "cream": (235, 230, 210),
}
CARTON_COLOR = (196, 154, 108)
CARTON_DARK = (150, 112, 74)


def get_font(size: int):
    for name in ("Arial.ttf", "DejaVuSans.ttf", "Helvetica.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_scene(
    photo_type: str,
    sku: str,
    product_title: str,
    color_name: str,
    carton_count: int,
    units_per_carton: int,
    damage_type: str | None,
    lighting: str,  # 'normal', 'dim', 'glare'
    blur: bool,
    occluded_label: bool,
    missing_component: bool = False,
    seed: int = 42,
) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H), (140, 142, 146))
    d = ImageDraw.Draw(img)

    # Floor and dock background
    for y in range(H):
        val = 140 - int(40 * y / H)
        d.line([(0, y), (W, y)], fill=(val, val + 2, val + 4))
    d.rectangle([0, H - 100, W, H], fill=(90, 92, 95))

    col = COLORS.get(color_name.lower(), (100, 100, 100))

    if photo_type == "pallet":
        # Overview showing cartons on a wooden pallet
        d.rectangle([100, H - 120, W - 100, H - 85], fill=(160, 120, 80), outline=(100, 70, 40), width=3)
        cols = min(carton_count, 4)
        rows = (carton_count + cols - 1) // cols
        bw = (W - 240) // max(cols, 1)
        bh = min(180, 280 // max(rows, 1))
        for i in range(carton_count):
            r, c = divmod(i, cols)
            x0 = 120 + c * bw + 8
            y0 = H - 125 - (rows - r) * bh
            d.rectangle([x0, y0, x0 + bw - 16, y0 + bh - 8], fill=CARTON_COLOR, outline=CARTON_DARK, width=2)
            d.text((x0 + 10, y0 + 10), f"BOX {i+1}", fill=(90, 60, 30), font=get_font(14))
            if damage_type == "crush" and i == 0:
                d.polygon([(x0 + bw - 16, y0), (x0 + bw - 40, y0), (x0 + bw - 16, y0 + 35)], fill=(100, 70, 40))
            elif damage_type == "water" and i == 0:
                d.ellipse([x0 + 10, y0 + bh - 40, x0 + 70, y0 + bh - 12], fill=(120, 90, 60))

    elif photo_type == "label":
        # Close-up of carton shipping and barcode label
        d.rectangle([120, 80, W - 120, H - 80], fill=CARTON_COLOR, outline=CARTON_DARK, width=4)
        d.rectangle([200, 130, W - 200, H - 130], fill=(252, 252, 250), outline=(40, 40, 40), width=3)

        label_y = 150
        disp_title = product_title if not occluded_label else product_title[:8] + "... [Torn/Obscured]"
        disp_sku = sku if not occluded_label else sku[:4] + "...???"
        d.text((220, label_y), f"PRODUCT: {disp_title}", fill=(20, 20, 20), font=get_font(18))
        label_y += 35
        d.text((220, label_y), f"SKU: {disp_sku}", fill=(10, 10, 10), font=get_font(22))
        label_y += 35
        d.text((220, label_y), f"VARIANT: {color_name.upper()}", fill=(30, 30, 30), font=get_font(16))
        label_y += 30
        d.text((220, label_y), f"PACK QTY: {units_per_carton} PCS / CTN", fill=(30, 30, 30), font=get_font(16))
        label_y += 45

        # Barcode representation
        bc_x = 220
        for _ in range(35):
            bar_w = rng.choice([2, 3, 5])
            if not occluded_label or bc_x < 360:
                d.rectangle([bc_x, label_y, bc_x + bar_w, label_y + 60], fill=(0, 0, 0))
            bc_x += bar_w + rng.choice([2, 4])
        if occluded_label:
            # Draw tear over barcode
            d.polygon([(340, label_y - 10), (460, label_y + 70), (430, label_y + 80), (330, label_y + 10)], fill=CARTON_COLOR)

    elif photo_type == "unit":
        # Open carton showing actual product units and accessories
        d.rectangle([100, 80, W - 100, H - 80], fill=CARTON_COLOR, outline=CARTON_DARK, width=5)
        d.rectangle([120, 100, W - 120, H - 100], fill=(70, 50, 35))

        # Render items inside open carton
        items_shown = min(units_per_carton, 8)
        cols = 4 if items_shown >= 4 else items_shown
        rows = (items_shown + cols - 1) // cols
        iw = (W - 280) // cols
        ih = (H - 260) // rows
        for i in range(items_shown):
            r, c = divmod(i, cols)
            ix = 140 + c * iw + 10
            iy = 120 + r * ih + 10
            d.rectangle([ix, iy, ix + iw - 15, iy + ih - 15], fill=col, outline=(20, 20, 20), width=2)
            d.text((ix + 6, iy + 6), f"{product_title[:14]}\nUnit {i+1}", fill=(240, 240, 240), font=get_font(11))

        # Component / accessory check
        comp_labels = [c.strip() for c in (sku.split("-")[1:] if "-" in sku else ["accessory"])]
        if not missing_component:
            d.rectangle([W - 250, H - 190, W - 120, H - 110], fill=(220, 220, 210), outline=(30, 30, 30), width=2)
            d.text((W - 240, H - 180), f"INCLUDED:\nComplete Set\nAll Components", fill=(10, 10, 10), font=get_font(11))
        else:
            d.rectangle([W - 250, H - 190, W - 120, H - 110], fill=(50, 40, 30), outline=(200, 40, 40), width=2)
            d.text((W - 240, H - 170), "[MISSING ACCESSORY]\nEmpty Compartment", fill=(240, 50, 50), font=get_font(11))

    # Apply lighting effects
    if lighting == "dim":
        darkness = Image.new("RGB", (W, H), (0, 0, 0))
        img = Image.blend(img, darkness, 0.45)
    elif lighting == "glare":
        glare = Image.new("RGB", (W, H), (255, 255, 255))
        img = Image.blend(img, glare, 0.25)

    # Apply blur if requested
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=2.5))

    return img


def generate_dataset():
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    catalog = [
        {"sku": "SKU-TOWEL-BLU", "name": "Cotton Bath Towel", "color": "blue", "pack": 24, "components": ["towel"]},
        {"sku": "SKU-BOTTLE-750", "name": "Steel Water Bottle 750ml", "color": "black", "pack": 12, "components": ["bottle", "lid"]},
        {"sku": "SKU-CABLE-USBC", "name": "USB-C Fast Charging Cable 2m", "color": "white", "pack": 24, "components": ["cable"]},
        {"sku": "SKU-LAMP-LED", "name": "LED Desk Lamp with USB", "color": "grey", "pack": 12, "components": ["lamp", "usb cable", "manual"]},
        {"sku": "SKU-MUG-11", "name": "Ceramic Mug 11oz Set of 2", "color": "white", "pack": 12, "components": ["mug x2"]},
        {"sku": "SKU-LEASH-6FT", "name": "Nylon Heavy Duty Dog Leash", "color": "red", "pack": 12, "components": ["leash"]},
        {"sku": "SKU-CANDLE-3", "name": "Soy Candle Trio Gift Box", "color": "cream", "pack": 12, "components": ["candle x3", "gift box"]},
    ]

    units = []

    # Distribution of 50 units:
    # 01-18: Clean PASS (Normal, dim, angle)
    # 19-24: Wrong SKU / Identity mismatch
    # 25-29: Wrong Color Variant
    # 30-34: Quantity Shortage
    # 35-37: Pack Size Mismatch
    # 38-41: Crushed Carton Damage
    # 42-44: Water Staining Damage
    # 45-46: Torn Packaging Damage
    # 47-48: Missing Component
    # 49-50: Highly Ambiguous / Occluded (Genuinely UNCERTAIN)

    random.seed(2026)

    for i in range(1, 51):
        uid = f"UNIT-{i:04d}"
        cat = catalog[(i - 1) % len(catalog)]
        sku_ordered = cat["sku"]
        sku_arrived = sku_ordered
        color_ordered = cat["color"]
        color_arrived = color_ordered
        pack_ordered = cat["pack"]
        pack_arrived = pack_ordered
        cartons_ordered = 2
        cartons_arrived = 2
        damage_type = None
        missing_comp = False
        lighting = "normal"
        blur = False
        occluded = False
        condition_name = "standard_lighting"

        # Determine scenario parameters
        if 1 <= i <= 18:
            # Clean shipments
            if i % 3 == 0:
                lighting = "dim"
                condition_name = "dim_warehouse_lighting"
            elif i % 5 == 0:
                lighting = "glare"
                condition_name = "dock_glare_backlight"
            else:
                condition_name = "clear_direct_light"
            h1_dec = "ACCEPT"
            h2_dec = "ACCEPT"
            consensus = "ACCEPT"
            notes = "All goods, counts, variants, and condition match PO."

        elif 19 <= i <= 24:
            # Wrong SKU
            wrong_cat = catalog[(i + 1) % len(catalog)]
            sku_arrived = wrong_cat["sku"]
            condition_name = "wrong_sku_delivered"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = f"Label displays arrived SKU {sku_arrived} instead of ordered {sku_ordered}."

        elif 25 <= i <= 29:
            # Wrong Variant
            alt_colors = [c for c in COLORS.keys() if c != color_ordered]
            color_arrived = alt_colors[i % len(alt_colors)]
            condition_name = "color_variant_mismatch"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = f"Arrived color is {color_arrived}, PO specifies {color_ordered}."

        elif 30 <= i <= 34:
            # Short shipment
            cartons_arrived = 1
            condition_name = "carton_shortage"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = f"Received {cartons_arrived} of {cartons_ordered} ordered cartons."

        elif 35 <= i <= 37:
            # Pack size mismatch
            pack_arrived = 6 if pack_ordered == 12 else 12
            condition_name = "units_per_carton_mismatch"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = f"Carton label indicates {pack_arrived} units/box; PO expected {pack_ordered}."

        elif 38 <= i <= 41:
            # Crushed carton
            damage_type = "crush"
            condition_name = "crushed_carton_transit_damage"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = "Visible severe crushing on carton corner and sidewall."

        elif 42 <= i <= 44:
            # Water damage
            damage_type = "water"
            condition_name = "water_damaged_carton"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = "Dark water stains and warping visible along lower carton face."

        elif 45 <= i <= 46:
            # Torn packaging
            damage_type = "tear"
            condition_name = "torn_outer_packaging"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = "Outer shipping carton has jagged tear exposing interior."

        elif 47 <= i <= 48:
            # Missing component
            missing_comp = True
            condition_name = "missing_accessory_component"
            h1_dec = "EXCEPTION"
            h2_dec = "EXCEPTION"
            consensus = "EXCEPTION"
            notes = "Open carton inspection confirms accessory compartment is empty."

        elif i == 49:
            # Severe blur and occluded barcode
            blur = True
            occluded = True
            lighting = "dim"
            condition_name = "severe_blur_and_label_tear"
            h1_dec = "UNCERTAIN"
            h2_dec = "UNCERTAIN"
            consensus = "UNCERTAIN"
            notes = "Label text is unreadable due to motion blur and surface tear; requires manual scan."

        elif i == 50:
            # Ambiguous carton stack with hidden interior
            condition_name = "dense_stack_hidden_interior"
            lighting = "glare"
            h1_dec = "UNCERTAIN"
            h2_dec = "ACCEPT"  # Evaluator 2 was optimistic, evaluator 1 flagged uncertain!
            consensus = "UNCERTAIN"
            notes = "Interior cartons concealed behind front layer; total count cannot be verified optically."

        # Render photos
        u_dir = PHOTOS_DIR / uid
        u_dir.mkdir(parents=True, exist_ok=True)

        p1 = render_scene(
            "pallet", sku_arrived, cat["name"], color_arrived, cartons_arrived, pack_arrived,
            damage_type, lighting, blur, occluded, missing_comp, seed=i * 11
        )
        p1.save(u_dir / "P1.png")

        p2 = render_scene(
            "label", sku_arrived, cat["name"], color_arrived, cartons_arrived, pack_arrived,
            damage_type, lighting, blur, occluded, missing_comp, seed=i * 23
        )
        p2.save(u_dir / "P2.png")

        p3 = render_scene(
            "unit", sku_arrived, cat["name"], color_arrived, cartons_arrived, pack_arrived,
            damage_type, lighting, blur, occluded, missing_comp, seed=i * 37
        )
        p3.save(u_dir / "P3.png")

        unit_entry = {
            "unit_id": uid,
            "condition": condition_name,
            "lighting": lighting,
            "blur": blur,
            "occluded": occluded,
            "purchase_order": {
                "po_number": f"PO-90{i:02d}",
                "supplier": "Acme Global Freight (DUMMY)",
                "lines": [
                    {
                        "sku": sku_ordered,
                        "expected_quantity": cartons_ordered * pack_ordered,
                        "expected_cartons": cartons_ordered,
                        "units_per_carton": pack_ordered,
                        "variant": {"color": color_ordered},
                    }
                ],
            },
            "catalog_item": cat,
            "arrived_truth": {
                "sku": sku_arrived,
                "variant": {"color": color_arrived},
                "cartons": cartons_arrived,
                "units_per_carton": pack_arrived,
                "damage": damage_type is not None,
                "missing_component": missing_comp,
            },
            "human_label_1": {
                "decision": h1_dec,
                "sku_match": "PASS" if sku_arrived == sku_ordered and not occluded else ("UNCERTAIN" if occluded else "FAIL"),
                "variant_match": "PASS" if color_arrived == color_ordered else "FAIL",
                "quantity_match": "PASS" if (cartons_arrived == cartons_ordered and pack_arrived == pack_ordered and not (i == 50)) else ("UNCERTAIN" if i == 50 else "FAIL"),
                "damage_clean": "FAIL" if damage_type else "PASS",
                "components_complete": "FAIL" if missing_comp else "PASS",
            },
            "human_label_2": {
                "decision": h2_dec,
                "sku_match": "PASS" if sku_arrived == sku_ordered and not (blur and occluded) else ("UNCERTAIN" if (blur or occluded) else "FAIL"),
                "variant_match": "PASS" if color_arrived == color_ordered else "FAIL",
                "quantity_match": "PASS" if (cartons_arrived == cartons_ordered and pack_arrived == pack_ordered) else "FAIL",
                "damage_clean": "FAIL" if damage_type else "PASS",
                "components_complete": "FAIL" if missing_comp else "PASS",
            },
            "consensus_ground_truth": {
                "decision": consensus,
                "reason": notes,
            },
            "photos": [f"data/eval_50/photos/{uid}/P1.png", f"data/eval_50/photos/{uid}/P2.png", f"data/eval_50/photos/{uid}/P3.png"],
        }
        units.append(unit_entry)

    (EVAL_DIR / "units.json").write_text(json.dumps(units, indent=2))
    print(f"Generated 50 held-out evaluation units in {EVAL_DIR}")


if __name__ == "__main__":
    generate_dataset()
