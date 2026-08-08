from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
import posixpath
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def cell_to_col_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Za-z]", "", cell_ref)
    index = 0
    for char in letters.upper():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(raw)
    strings: list[str] = []
    for item in root.findall("main:si", NS):
        parts = [text_node.text or "" for text_node in item.findall(".//main:t", NS)]
        strings.append("".join(parts))
    return strings


def first_sheet_info(archive: zipfile.ZipFile) -> tuple[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    sheet = workbook.find("main:sheets/main:sheet", NS)
    if sheet is None:
        raise ValueError("工作簿里没有工作表")

    sheet_name = sheet.attrib.get("name", "Sheet1")
    relationship_id = sheet.attrib[f"{{{NS['rel']}}}id"]
    target = None
    for rel in relationships.findall("pkgrel:Relationship", NS):
        if rel.attrib.get("Id") == relationship_id:
            target = rel.attrib["Target"]
            break

    if not target:
        raise ValueError("找不到第一个工作表的文件路径")

    if target.startswith("/"):
        return sheet_name, target.lstrip("/")
    return sheet_name, posixpath.normpath(posixpath.join("xl", target))


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", NS)).strip()

    value_node = cell.find("main:v", NS)
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except (ValueError, IndexError):
            return raw_value.strip()

    return raw_value.strip()


def read_rows(xlsx_path: Path) -> list[tuple[int, dict[int, str]]]:
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = read_shared_strings(archive)
        _, sheet_path = first_sheet_info(archive)
        root = ET.fromstring(archive.read(sheet_path))

    rows: list[tuple[int, dict[int, str]]] = []
    for row in root.findall(".//main:sheetData/main:row", NS):
        row_number = int(row.attrib.get("r", len(rows) + 1))
        values: dict[int, str] = {}
        for cell in row.findall("main:c", NS):
            reference = cell.attrib.get("r", "")
            if not reference:
                continue
            value = cell_value(cell, shared_strings)
            if value:
                values[cell_to_col_index(reference)] = value
        if values:
            rows.append((row_number, values))
    return rows


def relationship_map(archive: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
    try:
        root = ET.fromstring(archive.read(rels_path))
    except KeyError:
        return {}

    return {rel.attrib["Id"]: rel.attrib["Target"] for rel in root.findall("pkgrel:Relationship", NS)}


def normalize_archive_path(base_path: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_path), target))


def read_embedded_images(xlsx_path: Path) -> dict[tuple[int, int], list[dict[str, object]]]:
    images: dict[tuple[int, int], list[dict[str, object]]] = {}
    with zipfile.ZipFile(xlsx_path) as archive:
        drawing_paths = [
            name
            for name in archive.namelist()
            if name.startswith("xl/drawings/")
            and name.endswith(".xml")
            and not name.startswith("xl/drawings/_rels/")
        ]

        for drawing_path in drawing_paths:
            rels_path = posixpath.join(
                posixpath.dirname(drawing_path),
                "_rels",
                f"{posixpath.basename(drawing_path)}.rels",
            )
            rels = relationship_map(archive, rels_path)
            root = ET.fromstring(archive.read(drawing_path))

            for anchor in root:
                from_node = anchor.find("xdr:from", NS)
                blip = anchor.find(".//a:blip", NS)
                if from_node is None or blip is None:
                    continue

                row_text = from_node.findtext("xdr:row", namespaces=NS)
                col_text = from_node.findtext("xdr:col", namespaces=NS)
                relationship_id = blip.attrib.get(f"{{{NS['rel']}}}embed")
                if row_text is None or col_text is None or not relationship_id:
                    continue

                target = rels.get(relationship_id)
                if not target:
                    continue

                media_path = normalize_archive_path(drawing_path, target)
                if media_path not in archive.namelist():
                    continue

                row_number = int(row_text) + 1
                col_index = int(col_text)
                extension = Path(media_path).suffix.lower() or ".png"
                images.setdefault((row_number, col_index), []).append(
                    {
                        "mediaPath": media_path,
                        "extension": extension,
                        "data": archive.read(media_path),
                    }
                )

    return images


def evidence_host(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return host[4:] if host.startswith("www.") else host


def detect_tags(*parts: str) -> list[str]:
    text = " ".join(part for part in parts if part)
    tags: list[str] = []
    checks = [
        ("聚光灯", "聚光灯"),
        ("BOOOM", "BOOOM"),
        ("无开发者验证", "无开发者验证"),
        ("疑似", "疑似"),
        ("bilibili.com", "B站"),
        ("itch.io", "itch.io"),
    ]
    for needle, label in checks:
        if needle.lower() in text.lower() and label not in tags:
            tags.append(label)
    return tags


def status_for(note: str, has_evidence: bool) -> str:
    if note and has_evidence:
        return "有备注与证据"
    if has_evidence:
        return "有证据"
    if note:
        return "有备注"
    return "待补充证据"


def header_lookup(header: dict[int, str], fallback: int, *keywords: str) -> int:
    for index, value in header.items():
        for keyword in keywords:
            if keyword in value:
                return index
    return fallback


def has_header_row(row: dict[int, str]) -> bool:
    values = set(row.values())
    return "名称" in values or "开发者（曾用名）" in values or "跳转链接" in values


def write_item_images(
    images: dict[tuple[int, int], list[dict[str, object]]],
    row_number: int,
    col_index: int,
    item_id: str,
    slug: str,
    label: str,
    output_dir: Path,
) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    for image_index, image in enumerate(images.get((row_number, col_index), []), start=1):
        extension = str(image["extension"])
        suffix = f"-{image_index}" if image_index > 1 else ""
        filename = f"{item_id}-{slug}{suffix}{extension}"
        target = output_dir / filename
        target.write_bytes(image["data"])
        extracted.append(
            {
                "label": label,
                "url": f"assets/images/{filename}",
            }
        )
    return extracted


def build_payload(xlsx_path: Path) -> dict:
    rows = read_rows(xlsx_path)
    images = read_embedded_images(xlsx_path)
    items: list[dict[str, object]] = []
    image_output_dir = Path("docs/assets/images")
    image_output_dir.mkdir(parents=True, exist_ok=True)
    for stale_image in image_output_dir.glob("yc-*"):
        if stale_image.is_file():
            stale_image.unlink()

    if rows and has_header_row(rows[0][1]):
        header = rows[0][1]
        data_rows = rows[1:]
    else:
        header = {}
        data_rows = rows

    name_col = header_lookup(header, 0, "名称", "条目")
    project_image_col = header_lookup(header, 1, "金海豚项目", "项目")
    evidence_image_col = header_lookup(header, 2, "证据")
    note_col = header_lookup(header, 3, "备注")
    evidence_url_col = header_lookup(header, 4, "跳转链接", "链接", "URL", "url")
    related_col = header_lookup(header, 5, "开发者", "关联对象")

    for row_number, row in data_rows:
        name = row.get(name_col, "").strip()
        if not name:
            continue

        note = row.get(note_col, "").strip()
        evidence_url = row.get(evidence_url_col, "").strip()
        related = row.get(related_col, "").strip()
        item_id = f"yc-{len(items) + 1:03d}"
        project_images = write_item_images(
            images,
            row_number,
            project_image_col,
            item_id,
            "project",
            header.get(project_image_col, "金海豚项目"),
            image_output_dir,
        )
        evidence_images = write_item_images(
            images,
            row_number,
            evidence_image_col,
            item_id,
            "evidence",
            header.get(evidence_image_col, "证据"),
            image_output_dir,
        )
        item_images = project_images + evidence_images
        has_evidence = bool(evidence_url or evidence_images)
        items.append(
            {
                "id": item_id,
                "name": name,
                "related": related,
                "note": note,
                "evidenceUrl": evidence_url,
                "evidenceHost": evidence_host(evidence_url),
                "images": item_images,
                "projectImages": project_images,
                "evidenceImages": evidence_images,
                "status": status_for(note, has_evidence),
                "tags": detect_tags(related, note, evidence_url),
            }
        )

    related_values = sorted({str(item["related"]) for item in items if item["related"]})
    payload = {
        "title": "预制菜名单",
        "sourceFile": xlsx_path.name,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "total": len(items),
            "withEvidence": sum(1 for item in items if item["evidenceUrl"] or item["evidenceImages"]),
            "withNotes": sum(1 for item in items if item["note"]),
            "relatedCount": len(related_values),
            "withImages": sum(1 for item in items if item["images"]),
        },
        "columns": {
            "name": "条目",
            "related": "关联对象",
            "note": "备注",
            "evidenceUrl": "证据链接",
        },
        "items": items,
    }
    return payload


def write_csv(payload: dict, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id",
                "name",
                "related",
                "status",
                "note",
                "evidenceUrl",
                "evidenceHost",
                "images",
                "tags",
            ],
        )
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "related": item["related"],
                    "status": item["status"],
                    "note": item["note"],
                    "evidenceUrl": item["evidenceUrl"],
                    "evidenceHost": item["evidenceHost"],
                    "images": "、".join(image["url"] for image in item.get("images", [])),
                    "tags": "、".join(item.get("tags", [])),
                }
            )


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "预制菜.xlsx")
    output_json = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/data/prepared-foods.json")
    output_csv = output_json.with_suffix(".csv")

    if not source.exists():
        print(f"找不到源文件：{source}", file=sys.stderr)
        return 1

    payload = build_payload(source)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(payload, output_csv)
    print(f"已导出 {payload['summary']['total']} 条：{output_json}")
    print(f"CSV：{output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
