#!/usr/bin/env python3
"""Independently consume an actual TrackFold ZIP; never import product code."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

HEADERS = {
    "role-tracks.csv": ["track_id", "role_id", "role_name", "appearance_count"],
    "track-appearances.csv": ["track_id", "appearance_id", "role_id", "entrance_seconds", "exit_seconds", "cue"],
    "track-transitions.csv": ["track_id", "from_appearance", "to_appearance", "from_role", "to_role", "exit_seconds", "entrance_seconds", "gap_seconds", "required_seconds", "slack_seconds"],
}
FILES = set(HEADERS) | {"recipe.json", "run-sheet.html", "assumptions.txt"}
MAX_MEMBER, MAX_ARCHIVE = 8 * 1024 * 1024, 16 * 1024 * 1024
# ECMAScript whitespace, including BOM, to express the published escaping rule.
PREFIX = re.compile(r"^[\t\n\r]|^[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*[=+@-]")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class VerificationError(Exception):
    pass


def need(condition, message):
    if not condition:
        raise VerificationError(message)


def safe_cell(value):
    value = str(value)
    return "'" + value if PREFIX.search(value) else value


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, f"recipe: duplicate JSON key {key!r}")
        result[key] = value
    return result


def integer(value, low, high, label):
    need(type(value) is int and low <= value <= high, f"{label}: invalid integer")
    return value


def text_value(value, maximum, label):
    need(isinstance(value, str), f"{label}: expected text")
    # json.loads combines valid UTF-16 escape pairs into astral code points.
    # Any residual surrogate is unpaired and cannot round-trip through UTF-8.
    need(not any(0xD800 <= ord(char) <= 0xDFFF for char in value),
         f"{label}: unpaired Unicode surrogate")
    need("\r" not in value, f"{label}: noncanonical carriage return; exported text must use LF line endings")
    need(len(value.encode("utf-16-le")) // 2 <= maximum, f"{label}: text too long")
    need(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value), f"{label}: invalid control character")


def read_bundle(path):
    need(path.is_file(), f"Bundle not found: {path}")
    need(path.stat().st_size <= MAX_ARCHIVE, "ZIP exceeds size bound")
    content = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        need(len(names) == len(set(names)), "Duplicate ZIP filenames")
        need(set(names) == FILES, f"ZIP member mismatch: missing={sorted(FILES-set(names))}, extra={sorted(set(names)-FILES)}")
        need(sum(entry.file_size for entry in entries) <= MAX_ARCHIVE, "Uncompressed ZIP exceeds size bound")
        output = {}
        for entry in entries:
            name = PurePosixPath(entry.filename)
            need(not name.is_absolute() and len(name.parts) == 1 and "\\" not in entry.filename, "Unsafe ZIP path")
            need(not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16), "Directory/symlink ZIP member")
            need(not entry.flag_bits & 1, "Encrypted ZIP unsupported")
            need(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "Unsupported ZIP compression")
            need(entry.file_size <= MAX_MEMBER, "ZIP member exceeds size bound")
            need(entry.file_size <= max(1, entry.compress_size) * 1000, "ZIP expansion ratio exceeds bound")
            output[entry.filename] = archive.read(entry)  # Python checks CRC, no extractall.
    return output, hashlib.sha256(content).hexdigest()


def read_recipe(raw):
    def bad_constant(value):
        raise VerificationError(f"Non-finite JSON: {value}")
    recipe = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_json, parse_constant=bad_constant)
    need(isinstance(recipe, dict) and recipe.get("modelVersion") == 1, "Unsupported recipe version")
    roles, apps = recipe.get("roles"), recipe.get("appearances")
    need(isinstance(roles, list) and 1 <= len(roles) <= 16, "1–16 recipe roles required")
    need(isinstance(apps, list) and 1 <= len(apps) <= 128, "1–128 recipe appearances required")
    role_map, app_map = {}, {}
    for role in roles:
        need(isinstance(role, dict), "Invalid role")
        rid = role.get("id")
        need(isinstance(rid, str) and ID.fullmatch(rid) and rid not in role_map, "Invalid/duplicate role ID")
        text_value(role.get("name"), 80, f"Role {rid} name")
        role_map[rid] = role
    for app in apps:
        need(isinstance(app, dict), "Invalid appearance")
        aid = app.get("id")
        need(isinstance(aid, str) and ID.fullmatch(aid) and aid not in app_map, "Invalid/duplicate appearance ID")
        need(app.get("roleId") in role_map, f"Appearance {aid}: unknown role")
        start = integer(app.get("start"), 0, 86400, f"{aid} entrance")
        end = integer(app.get("end"), 0, 86400, f"{aid} exit")
        need(start < end, f"Appearance {aid}: empty/reversed interval")
        text_value(app.get("cue"), 500, f"Appearance {aid} cue")
        app_map[aid] = app
    need({app["roleId"] for app in apps} == set(role_map), "Recipe role without appearance")
    integer(recipe.get("defaultChangeover"), 0, 86400, "Default changeover")
    integer(recipe.get("targetTracks"), 1, 16, "Target tracks")
    overrides = recipe.get("overrides")
    need(isinstance(overrides, list) and len(overrides) <= 256, "Invalid overrides")
    directed = {}
    for item in overrides:
        need(isinstance(item, dict), "Invalid override")
        key = (item.get("from"), item.get("to"))
        need(key[0] in role_map and key[1] in role_map and key[0] != key[1] and key not in directed, "Invalid/duplicate directed override")
        directed[key] = integer(item.get("seconds"), 0, 86400, "Directed override")
    for kind, maximum, group_max in (("mustShare", 32, 16), ("neverShare", 120, 2)):
        groups = recipe.get(kind)
        need(isinstance(groups, list) and len(groups) <= maximum, f"Invalid {kind}")
        for group in groups:
            need(isinstance(group, list) and 2 <= len(group) <= group_max, f"Invalid {kind} group")
            need(all(isinstance(rid, str) and rid in role_map for rid in group), f"{kind}: unknown role")
            need(len(set(group)) == len(group), f"{kind}: repeated role")
    return recipe, role_map, app_map, directed


def read_csvs(files):
    tables = {}
    for name, header in HEADERS.items():
        raw = files[name]
        need(raw.startswith(b"\xef\xbb\xbf"), f"{name}: UTF-8 BOM missing")
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True))
        need(rows and rows[0] == header, f"{name}: header mismatch")
        need(all(len(row) == len(header) for row in rows), f"{name}: ragged row")
        need(all("\x00" not in cell for row in rows for cell in row), f"{name}: NUL cell")
        tables[name] = rows
    return tables


def verify_csvs(recipe, roles, apps, directed, tables):
    rows = tables["role-tracks.csv"][1:]
    need(len(rows) == len(roles), "Each role must occur once in role CSV")
    role_track, tracks = {}, defaultdict(lambda: {"roles": [], "apps": [], "transitions": []})
    counts = Counter(app["roleId"] for app in apps.values())
    for tid, rid, name, count in rows:
        need(re.fullmatch(r"T[1-9][0-9]*", tid), f"Not an anonymous track ID: {tid!r}")
        need(rid in roles and rid not in role_track, f"Duplicate/unknown role: {rid!r}")
        need(name == safe_cell(roles[rid]["name"]), f"Role {rid}: name, Unicode or formula escaping differs")
        need(count == str(counts[rid]), f"Role {rid}: appearance count differs")
        role_track[rid] = tid
        tracks[tid]["roles"].append(rid)
    track_ids = [f"T{i}" for i in range(1, len(tracks) + 1)]
    need(set(tracks) == set(track_ids), "Track IDs must be contiguous T1…Tn")
    need([row[0] for row in rows] == [tid for tid in track_ids for _ in tracks[tid]["roles"]], "Role track order is interleaved or non-contiguous")
    for group in recipe["mustShare"]:
        need(len({role_track[rid] for rid in group}) == 1, f"mustShare violated: {group}")
    for left, right in recipe["neverShare"]:
        need(role_track[left] != role_track[right], f"neverShare violated: {left}, {right}")
    expected_apps = []
    for tid in track_ids:
        seq = sorted((app for app in apps.values() if role_track[app["roleId"]] == tid), key=lambda app: (app["start"], app["end"], app["id"]))
        tracks[tid]["apps"] = seq
        expected_apps.extend([[tid, app["id"], app["roleId"], str(app["start"]), str(app["end"]), safe_cell(app["cue"])] for app in seq])
    actual_apps = tables["track-appearances.csv"][1:]
    need(Counter(row[1] for row in actual_apps) == Counter({aid: 1 for aid in apps}), "Each appearance must occur exactly once")
    need(actual_apps == expected_apps, "Appearance CSV differs from recipe, track, chronological order, Unicode or escaping")
    expected_transitions, coverage = [], Counter()
    for tid in track_ids:
        seq = tracks[tid]["apps"]
        for left, right in zip(seq, seq[1:]):
            gap = right["start"] - left["end"]
            pair = (left["roleId"], right["roleId"])
            if pair[0] == pair[1]:
                required, kind = 0, "same_role_zero"
            elif pair in directed:
                required, kind = directed[pair], "directed_override"
            else:
                required, kind = recipe["defaultChangeover"], "default_changeover"
            coverage[kind] += 1
            need(gap >= 0, f"Track {tid}: overlap {left['id']} / {right['id']}")
            need(gap >= required, f"Track {tid}: insufficient changeover {left['id']} → {right['id']}")
            slack = gap - required
            coverage["equality_boundary"] += int(slack == 0)
            entry = [tid, left["id"], right["id"], pair[0], pair[1], str(left["end"]), str(right["start"]), str(gap), str(required), str(slack)]
            expected_transitions.append(entry)
            tracks[tid]["transitions"].append(entry)
    need(tables["track-transitions.csv"][1:] == expected_transitions, "Transition CSV must contain exactly every consecutive pair with correct direction, gap, requirement and slack")
    texts = [role["name"] for role in roles.values()] + [app["cue"] for app in apps.values()]
    return tracks, track_ids, {
        "roles": len(roles), "appearances": len(apps), "tracks": len(tracks), "consecutive_transitions": len(expected_transitions),
        "formula_prefixed_text_fields": sum(bool(PREFIX.search(value)) for value in texts),
        "non_ascii_text_fields": sum(any(ord(char) > 127 for char in value) for value in texts),
        "must_share_groups": len(recipe["mustShare"]), "never_share_pairs": len(recipe["neverShare"]),
        "transition_coverage": {key: coverage[key] for key in ("same_role_zero", "directed_override", "default_changeover", "equality_boundary")},
    }


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return "".join(child.text() if isinstance(child, Node) else child for child in self.children)

    def all(self, tag):
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    found.append(child)
                found.extend(child.all(tag))
        return found


class HandoffHTML(HTMLParser):
    VOID = {"meta", "br", "hr", "img", "input", "link", "area", "base", "col", "embed", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        need(tag not in {"script", "iframe", "object", "embed", "link", "base", "img", "form", "input", "audio", "video", "svg", "math"}, f"Active/external HTML element: {tag}")
        for key, _ in attrs:
            need(not key.lower().startswith("on") and key.lower() not in {"href", "src", "srcset", "action", "formaction", "ping"}, f"Active/external HTML attribute: {key}")
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag == "br":
            node.children.append("\n")
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        need(len(self.stack) > 1 and self.stack[-1].tag == tag, f"Malformed HTML end tag: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)


def table_rows(table):
    return [[cell.text() for cell in row.children if isinstance(cell, Node) and cell.tag in {"th", "td"}] for row in table.all("tr")]


def minutes(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}"


def verify_html_and_assumptions(files, recipe, roles, tracks, track_ids):
    parser = HandoffHTML()
    parser.feed(files["run-sheet.html"].decode("utf-8"))
    parser.close()
    need(len(parser.stack) == 1, "Unclosed HTML tags")
    root = parser.root
    metas = root.all("meta")
    need(any(node.attrs.get("charset", "").lower() == "utf-8" for node in metas), "HTML UTF-8 declaration missing")
    need(any(node.attrs.get("http-equiv", "").lower() == "content-security-policy" and node.attrs.get("content") == "default-src 'none'; style-src 'unsafe-inline'" for node in metas), "HTML CSP differs")
    for style in root.all("style"):
        need(not re.search(r"@import|url\s*\(", style.text(), re.I), "HTML CSS references external resources")
    sections = root.all("section")
    need(len(sections) == len(tracks) + 1, "HTML section count differs")
    strong = root.all("header")[0].all("strong") if root.all("header") else []
    need(len(strong) == 1 and strong[0].text() == str(len(tracks)), "HTML track-count label differs")
    for tid, section in zip(track_ids, sections[:-1]):
        track = tracks[tid]
        headings, paragraphs, tables = section.all("h2"), section.all("p"), section.all("table")
        need(len(headings) == 1 and headings[0].text() == tid + " · " + " + ".join(track["roles"]), f"HTML {tid}: heading differs")
        need(paragraphs and paragraphs[0].text() == " / ".join(f"{rid}: {roles[rid]['name']}" for rid in track["roles"]), f"HTML {tid}: names/Unicode differ")
        need(len(tables) == 1 + bool(track["transitions"]), f"HTML {tid}: table count differs")
        expected = [[f"{app['id']} / {app['roleId']}", f"{app['start']} / {app['end']}", f"{minutes(app['start'])}–{minutes(app['end'])}", app["cue"]] for app in track["apps"]]
        need(table_rows(tables[0])[1:] == expected, f"HTML {tid}: appearances, times, cues or escaping differ")
        if track["transitions"]:
            expected = [[f"{row[1]} → {row[2]}\n{row[3]} → {row[4]}", row[7], row[8], row[9]] for row in track["transitions"]]
            need(table_rows(tables[1])[1:] == expected, f"HTML {tid}: handoffs differ")
    assumptions_html = sections[-1].text()
    need(f"Default changeover: {recipe['defaultChangeover']}s." in assumptions_html, "HTML default changeover differs")
    overrides = "; ".join(f"{item['from']} → {item['to']}: {item['seconds']}s" for item in recipe["overrides"]) or "none"
    need(f"Directed overrides: {overrides}." in assumptions_html, "HTML directed overrides differ")
    for label, key in (("Must share", "mustShare"), ("Never share", "neverShare")):
        need(f"{label}: {json.dumps(recipe[key], ensure_ascii=False, separators=(',', ':'))}" in assumptions_html, f"HTML {label} differs")
    assumptions = files["assumptions.txt"].decode("utf-8")
    expected_lines = ["TrackFold model version 1", f"Minimum tracks: {len(tracks)}", f"Target maximum: {recipe['targetTracks']}", f"Target sufficient: {str(len(tracks) <= recipe['targetTracks']).lower()}"]
    need(assumptions.splitlines()[:4] == expected_lines, "Assumptions metadata differs")
    return {"status": "passed", "track_sections": len(tracks), "appearance_rows": sum(len(track["apps"]) for track in tracks.values()), "static_only": True}


def xml_part(archive, name):
    need(archive.getinfo(name).file_size <= MAX_MEMBER, f"XLSX XML part too large: {name}")
    data = archive.read(name)
    need(b"<!DOCTYPE" not in data and b"<!ENTITY" not in data, "XLSX DTD/entity unsupported")
    return ET.fromstring(data)


def ooxml_text(node):
    value = "".join(part.text or "" for part in node.iter(f"{{{NS['s']}}}t"))
    return re.sub(r"_x([0-9a-fA-F]{4})_", lambda match: chr(int(match[1], 16)), value)


def coordinate(reference):
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference or "")
    need(match is not None, f"Invalid XLSX coordinate: {reference}")
    col = 0
    for char in match[1]:
        col = col * 26 + ord(char) - 64
    return int(match[2]), col


def inspect_xlsx(path, expected):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        need(len(names) == len(set(names)), "Duplicate XLSX part")
        need(not any(name.startswith("xl/externalLinks/") for name in names), "Unexpected XLSX external link")
        sheets = xml_part(archive, "xl/workbook.xml").findall("s:sheets/s:sheet", NS)
        need(len(sheets) == 1, "CSV conversion must yield one sheet")
        rid = sheets[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        targets = [rel.attrib for rel in xml_part(archive, "xl/_rels/workbook.xml.rels") if rel.get("Id") == rid]
        need(len(targets) == 1 and targets[0].get("TargetMode") != "External", "Invalid XLSX sheet relationship")
        target = targets[0]["Target"]
        need(".." not in PurePosixPath(target).parts and "\\" not in target, "Unsafe XLSX sheet target")
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        worksheet = xml_part(archive, target)
        need(not worksheet.findall(".//s:f", NS), "Native workbook contains formulas")
        need(not worksheet.findall(".//s:hyperlink", NS), "Native workbook contains hyperlinks")
        shared = [ooxml_text(node) for node in xml_part(archive, "xl/sharedStrings.xml").findall("s:si", NS)] if "xl/sharedStrings.xml" in names else []
        actual = {}
        for cell in worksheet.findall("s:sheetData/s:row/s:c", NS):
            point = coordinate(cell.get("r"))
            need(point not in actual, "Duplicate XLSX coordinate")
            need(point[0] <= len(expected) and point[1] <= len(expected[0]), "Native CSV has extra rows/columns")
            kind = cell.get("t")
            if kind == "s":
                index = int(cell.findtext("s:v", default="-1", namespaces=NS))
                need(0 <= index < len(shared), "Invalid XLSX shared-string index")
                value = shared[index]
            elif kind == "inlineStr":
                value = ooxml_text(cell)
            else:
                value = cell.findtext("s:v", default="", namespaces=NS)
                need(not value, f"Native CSV {cell.get('r')} was not preserved as text")
            actual[point] = value
        for rn, row in enumerate(expected, 1):
            for cn, wanted in enumerate(row, 1):
                got = actual.get((rn, cn), "")
                need(got == wanted, f"Native {path.name} R{rn}C{cn} differs: {got!r} != {wanted!r}")
        need(max((p[0] for p in actual), default=0) == len(expected), "Native row count differs")
        need(max((p[1] for p in actual), default=0) == len(expected[0]), "Native column count differs")
    return {"status": "passed", "file": path.name, "rows_including_header": len(expected), "columns": len(expected[0]), "xml_cells": len(actual), "formula_cells": 0, "all_values_preserved_as_text": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_native(files, tables, out, report, require, skip=False):
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    native = report["native_libreoffice"]
    native["available"] = executable is not None
    if skip:
        native.update(status="skipped", reason="Explicit --skip-libreoffice; no native application executed")
        return
    if executable is None:
        native.update(status="failed" if require else "skipped", reason="LibreOffice/soffice executable not found")
        need(not require, "--require-libreoffice requested but LibreOffice is missing")
        return
    native.update(status="running", executable=executable, files=[])
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
    need(version.returncode == 0, f"LibreOffice version check failed: {version.stderr}")
    native["version"] = version.stdout.strip()
    native_out = out / "native"
    native_out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trackfold-native-") as directory:
        temp = Path(directory)
        converted, cache = temp / "converted", temp / "cache"
        converted.mkdir()
        cache.mkdir()
        # Isolate profile/cache without modifying existing desktop settings.
        profile = (temp / "profile").as_uri()
        environment = dict(os.environ, XDG_CACHE_HOME=str(cache))
        for name, rows in tables.items():
            source = temp / name
            source.write_bytes(files[name])  # The exact ZIP bytes, not regenerated CSV.
            columns = "/".join(f"{number}/2" for number in range(1, len(rows[0]) + 1))
            options = f"44,34,76,1,{columns},0,true,false,false,false,false,0,false,false,false"
            command = [executable, "-env:UserInstallation=" + profile, "--headless", "--nologo", "--nodefault", "--nolockcheck", "--norestore", "--infilter=Text - txt - csv (StarCalc):" + options, "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(converted), str(source)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=90, env=environment)
            target = converted / (Path(name).stem + ".xlsx")
            need(run.returncode == 0 and target.is_file() and target.stat().st_size > 0, f"LibreOffice conversion failed for {name}: exit={run.returncode}; stdout={run.stdout}; stderr={run.stderr}")
            check = inspect_xlsx(target, rows)
            check.update(source_csv=name, import_filter_options=options, stdout=run.stdout.strip(), stderr=run.stderr.strip())
            shutil.copyfile(target, native_out / target.name)
            check["file"] = "native/" + target.name
            native["files"].append(check)
    native["status"] = "passed"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--bundle", required=True, type=Path, help="Actual browser or CLI export ZIP")
    cli.add_argument("--out", type=Path, default=Path("artifacts/consumer"), help="Report/evidence directory")
    native_flags = cli.add_mutually_exclusive_group()
    native_flags.add_argument("--require-libreoffice", action="store_true", help="Fail rather than skip if LibreOffice is missing")
    native_flags.add_argument("--skip-libreoffice", action="store_true", help="Explicitly skip native execution in restricted local environments")
    args = cli.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"consumer": "TrackFold independent handoff verifier v1", "created_utc": datetime.now(timezone.utc).isoformat(), "bundle": str(args.bundle), "status": "running", "solver_imported": False, "optimality_rechecked": False, "native_libreoffice": {"available": None, "required": args.require_libreoffice, "skip_requested": args.skip_libreoffice, "status": "not_run"}}
    exit_code = 0
    try:
        files, digest = read_bundle(args.bundle)
        report["bundle_sha256"] = digest
        report["members"] = {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(files.items())}
        recipe, roles, apps, directed = read_recipe(files["recipe.json"])
        tables = read_csvs(files)
        tracks, track_ids, counts = verify_csvs(recipe, roles, apps, directed, tables)
        report["csv_semantics"] = {"status": "passed", **counts, "tables": {name: {"rows_including_header": len(rows), "columns": len(rows[0])} for name, rows in tables.items()}}
        report["html_and_assumptions"] = verify_html_and_assumptions(files, recipe, roles, tracks, track_ids)
        verify_native(files, tables, args.out, report, args.require_libreoffice, args.skip_libreoffice)
        report["status"] = "passed"
    except (VerificationError, OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError, csv.Error, zipfile.BadZipFile, ET.ParseError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if report["native_libreoffice"]["status"] == "running":
            report["native_libreoffice"]["status"] = "failed"
        exit_code = 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    destination = args.out / "consumer-report.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(destination), "native_libreoffice": report["native_libreoffice"]["status"], **({"error": report["error"]} if "error" in report else {})}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
