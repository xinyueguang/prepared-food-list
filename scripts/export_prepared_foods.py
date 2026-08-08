from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
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


def first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    sheet = workbook.find("main:sheets/main:sheet", NS)
    if sheet is None:
        raise ValueError("工作簿里没有工作表")

    relationship_id = sheet.attrib[f"{{{NS['rel']}}}id"]
    target = None
    for rel in relationships.findall("pkgrel:Relationship", NS):
        if rel.attrib.get("Id") == relationship_id:
            target = rel.attrib["Target"]
            break

    if not target:
        raise ValueError("找不到第一个工作表的文件路径")

    if target.startswith("/"):
        return target.lstrip("/")
    return str(PurePosixPath("xl") / target)


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


def read_rows(xlsx_path: Path) -> list[dict[int, str]]:
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_path = first_sheet_path(archive)
        root = ET.fromstring(archive.read(sheet_path))

    rows: list[dict[int, str]] = []
    for row in root.findall(".//main:sheetData/main:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("main:c", NS):
            reference = cell.attrib.get("r", "")
            if not reference:
                continue
            value = cell_value(cell, shared_strings)
            if value:
                values[cell_to_col_index(reference)] = value
        if values:
            rows.append(values)
    return rows


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


def status_for(note: str, evidence_url: str) -> str:
    if note and evidence_url:
        return "有备注与链接"
    if evidence_url:
        return "有证据链接"
    if note:
        return "有备注"
    return "待补充证据"


def build_payload(xlsx_path: Path) -> dict:
    rows = read_rows(xlsx_path)
    items: list[dict[str, object]] = []

    for row in rows:
        name = row.get(0, "").strip()
        if not name:
            continue

        note = row.get(3, "").strip()
        evidence_url = row.get(4, "").strip()
        related = row.get(5, "").strip()
        item_id = f"yc-{len(items) + 1:03d}"
        items.append(
            {
                "id": item_id,
                "name": name,
                "related": related,
                "note": note,
                "evidenceUrl": evidence_url,
                "evidenceHost": evidence_host(evidence_url),
                "status": status_for(note, evidence_url),
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
            "withEvidence": sum(1 for item in items if item["evidenceUrl"]),
            "withNotes": sum(1 for item in items if item["note"]),
            "relatedCount": len(related_values),
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
            fieldnames=["id", "name", "related", "status", "note", "evidenceUrl", "evidenceHost", "tags"],
        )
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow({**item, "tags": "、".join(item.get("tags", []))})


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
