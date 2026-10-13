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


# The same material organised the way a Portuguese studio might: plural and
# Portuguese folder names, a numbered section with sub-folders, utility
# folders ("Final", "Selecionadas/Hi-Res") and a brief.
PT_ROOT = "Café Lusitano — Identidade Visual"
PT_LAYOUT: dict[str, list[tuple[str, str]]] = {
    "1. Logos/PNG": [("01 Logo/butter-bean-logo-primary.png", "logo-principal.png"), ("01 Logo/butter-bean-logo-alternative-stacked.png", "logo-vertical.png")],
    "1. Logos/Versões": [("01 Logo/logo-negative-on-espresso.jpg", "negativo.jpg"), ("01 Logo/butter-bean-monogram.png", "simbolo.png")],
    "2. Cores": [("02 Brand Elements/colour-palette.png", "paleta.png")],
    "3. Tipografia": [("02 Brand Elements/typography-specimen.png", "fontes.png")],
    "4. Padrão": [("02 Brand Elements/brand-pattern.png", "padrao-01.png")],
    "5. Embalagens/Rótulos": [("04 Packaging/coffee-bag-mockup.jpg", "IMG_4021.jpg")],
    "5. Embalagens/Copos/Final": [("04 Packaging/takeaway-cups.jpg", "IMG_4022.jpg"), ("04 Packaging/pastry-box.jpg", "caixa-logo.jpg")],
    "6. Cartazes": [("05 Campaign/poster-specialty-coffee.jpg", "cartaz-01.jpg"), ("05 Campaign/poster-favourite-corner.jpg", "cartaz-02.jpg")],
    "7. Outdoors": [("05 Campaign/billboard-48-sheet.jpg", "mupi.jpg")],
    "8. Redes Sociais/Posts": [("06 Social Media/instagram-post-01.jpg", "post1.jpg"), ("06 Social Media/instagram-post-02.jpg", "post2.jpg")],
    "8. Redes Sociais/Stories": [("06 Social Media/instagram-post-03.jpg", "story1.jpg"), ("06 Social Media/instagram-post-04.jpg", "story2.jpg")],
    "9. Fotografia/Selecionadas/Hi-Res": [("03 Photography/DSC_0142.jpg", "IMG_5001.jpg"), ("03 Photography/DSC_0157 shop interior.jpg", "IMG_5002.jpg"),
                                          ("03 Photography/DSC_0163.jpg", "IMG_5003.jpg"), ("03 Photography/DSC_0171.jpg", "IMG_5004.jpg"),
                                          ("03 Photography/DSC_0188.jpg", "IMG_5005.jpg")],
}
PT_SECTIONS = ["Logos", "Cores", "Tipografia", "Padrão", "Embalagens", "Cartazes", "Outdoors", "Redes Sociais", "Fotografia"]


def build_organized_pt(demo: Path, target: Path) -> Path:
    root = target / PT_ROOT
    for folder, files in PT_LAYOUT.items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        for src, name in files:
            shutil.copy(demo / src, root / folder / name)
    (root / "brief.txt").write_text("Projeto: Café Lusitano\nCategoria: Identidade visual\nCores: #2E2017, #F4C95D, #D9653F\n"
                                    "Tipografia: Fraunces, Manrope\n", encoding="utf-8")
    return root


def pt_section(asset) -> str:
    """Top-level folder (section) of an asset of the Portuguese fixture."""
    parts = (asset.source_folder or "").split("/")
    return parts[1] if len(parts) > 1 and parts[0] == PT_ROOT else ""
