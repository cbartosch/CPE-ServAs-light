from __future__ import annotations

import subprocess
from pathlib import Path
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx", ".vsdx"}


def _tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode("utf-8")
    return [ROOT / item for item in output.split("\0") if item and (ROOT / item).is_file()]


def test_current_tree_uses_only_dvsum_caddi_product_nomenclature() -> None:
    obsolete = ("dal" + "li").encode("utf-8")
    offenders: list[str] = []
    for path in _tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if obsolete in relative.lower().encode("utf-8"):
            offenders.append(relative)
            continue
        raw = path.read_bytes()
        if path.suffix.lower() in OFFICE_SUFFIXES:
            try:
                with ZipFile(path) as archive:
                    for member in archive.namelist():
                        if obsolete in archive.read(member).lower():
                            offenders.append(f"{relative}!{member}")
                            break
            except BadZipFile:
                offenders.append(f"{relative}: invalid Office archive")
            continue
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if obsolete.decode("utf-8") in text.lower():
            offenders.append(relative)
    assert offenders == []


def test_canonical_caddi_module_contract_and_route() -> None:
    from lpr_cpe_demo.caddi import caddi_contract

    contract = caddi_contract()
    assert contract["layer"] == "DvSum CADDI"
    assert contract["product"] == "CADDI"
    assert contract["compatibility"]["canonical_route"] == "/api/integrations/caddi"
    assert contract["compatibility"]["canonical_query_view"] == "caddi"
