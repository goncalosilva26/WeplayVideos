"""A professionally organised branding project built from the synthetic
Butter & Bean images (clearly a test fixture): numbered section folders,
nested sub-folders, camera-style and duplicated file names."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT_NAME = "Butter & Bean - Brand Identity"
LAYOUT: dict[str, list[tuple[str, str]]] = {
    "01 Logo": [("01 Logo/butter-bean-logo-primary.png", "primary.png"), ("01 Logo/butter-bean-logo-alternative-stacked.png", "secondary.png"),
                ("01 Logo/butter-bean-monogram.png", "symbol.png"), ("01 Logo/logo-negative-on-espresso.jpg", "negative.jpg")],
    "02 Brand Elements": [("02 Brand Elements/colour-palette.png", "sheet-1.png"), ("02 Brand Elements/typography-specimen.png", "sheet-2.png"),
                          ("02 Brand Elements/brand-pattern.png", "sheet-3.png")],
    "03 Packaging": [("04 Packaging/coffee-bag-mockup.jpg", "IMG_4021.jpg"), ("04 Packaging/takeaway-cups.jpg", "IMG_4022.jpg")],
    "03 Packaging/Boxes/JPG": [("04 Packaging/pastry-box.jpg", "logo-on-box.jpg")],  # nested + generic folder + misleading name
    "04 Campaign/Posters": [("05 Campaign/poster-specialty-coffee.jpg", "01.jpg"), ("05 Campaign/poster-favourite-corner.jpg", "02.jpg")],
    "04 Campaign/Outdoor": [("05 Campaign/billboard-48-sheet.jpg", "01.jpg")],
    "05 Social Media": [("06 Social Media/instagram-post-01.jpg", "01.jpg"), ("06 Social Media/instagram-post-02.jpg", "02.jpg"),
                        ("06 Social Media/instagram-post-03.jpg", "03.jpg"), ("06 Social Media/instagram-post-04.jpg", "04.jpg")],
    "06 Photography": [("03 Photography/DSC_0142.jpg", "IMG_5001.jpg"), ("03 Photography/DSC_0157 shop interior.jpg", "IMG_5002.jpg"),
                       ("03 Photography/DSC_0163.jpg", "IMG_5003.jpg"), ("03 Photography/DSC_0171.jpg", "IMG_5004.jpg"),
                       ("03 Photography/DSC_0188.jpg", "IMG_5005.jpg")],
}
# Section (top-level folder) each file must stay in.
EXPECTED = {f"{folder}/{name}": folder.split("/")[0] for folder, files in LAYOUT.items() for _, name in files}


def build_organized(demo: Path, target: Path) -> Path:
    root = target / ROOT_NAME
    for folder, files in LAYOUT.items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        for src, name in files:
            shutil.copy(demo / src, root / folder / name)
    return root


def expected_section(asset) -> str:
    """Top-level section folder of an imported asset of this fixture."""
    parts = (asset.source_folder or "").split("/")
    return parts[1] if parts and parts[0] == ROOT_NAME and len(parts) > 1 else ""
