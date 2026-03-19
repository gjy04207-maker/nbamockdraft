from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "draft"
TEAM_PROFILES_PATH = DATA_DIR / "team_profiles_2026.json"
PICK_VALUES_PATH = DATA_DIR / "pick_values_kevin_pelton_2017.json"
ROSTER_SNAPSHOT_PATH = DATA_DIR / "rosters_snapshot_2026.json"
DRAFT_ORDER_PATH = DATA_DIR / "draft_order_2026.json"
OUTPUT_PATH = DATA_DIR / "draft_data.json"

TEAM_CODE_MAP = {
    "atl": "ATL",
    "bkn": "BKN",
    "bos": "BOS",
    "cha": "CHA",
    "chi": "CHI",
    "cle": "CLE",
    "dal": "DAL",
    "den": "DEN",
    "det": "DET",
    "gs": "GSW",
    "hou": "HOU",
    "ind": "IND",
    "lac": "LAC",
    "lal": "LAL",
    "mem": "MEM",
    "mia": "MIA",
    "mil": "MIL",
    "min": "MIN",
    "no": "NOP",
    "ny": "NYK",
    "okc": "OKC",
    "orl": "ORL",
    "phi": "PHI",
    "phx": "PHX",
    "por": "POR",
    "sa": "SAS",
    "sac": "SAC",
    "tor": "TOR",
    "uta": "UTA",
    "was": "WAS",
}

ESPN_ABBR_ALIASES = {
    "GSW": "GS",
    "SAS": "SA",
    "NOP": "NO",
    "NYK": "NY",
    "PHX": "PHO",
    "UTA": "UTAH",
    "WAS": "WSH",
}

CANONICAL_TEAM_ABBRS = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "PHO": "PHX",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}

POSITION_MAP = {
    "后卫": ("G", "后卫"),
    "前锋": ("F", "前锋"),
    "中锋": ("C", "中锋"),
    "前锋/中锋": ("F/C", "前锋/中锋"),
    "后卫/前锋": ("G/F", "后卫/前锋"),
    "侧翼": ("F", "侧翼"),
}

CLASS_YEAR_MAP = {
    "1": "大一",
    "2": "大二",
    "3": "大三",
    "4": "大四",
    "5": "其他",
}

WORKBOOK_HEADERS = {
    "A": "name_zh",
    "B": "name_en",
    "C": "projected_pick",
    "D": "class_year",
    "E": "position_raw",
    "F": "height_cm",
    "G": "weight_kg",
    "H": "school",
    "I": "conference",
    "J": "minutes",
    "K": "fg",
    "L": "fga",
    "M": "fg_pct",
    "N": "three_p",
    "O": "three_pa",
    "P": "three_pct",
    "Q": "two_p",
    "R": "two_pa",
    "S": "two_pct",
    "T": "efg_pct",
    "U": "ft",
    "V": "fta",
    "W": "ft_pct",
    "X": "orb",
    "Y": "drb",
    "Z": "trb",
    "AA": "ast",
    "AB": "stl",
    "AC": "blk",
    "AD": "tov",
    "AE": "pf",
    "AF": "pts",
    "AG": "per",
    "AH": "ts_pct",
    "AI": "three_par",
    "AJ": "ftr",
    "AK": "pprod",
    "AL": "orb_pct",
    "AM": "drb_pct",
    "AN": "trb_pct",
    "AO": "ast_pct",
    "AP": "stl_pct",
    "AQ": "blk_pct",
    "AR": "tov_pct",
    "AS": "usg_pct",
    "AT": "ows",
    "AU": "dws",
    "AV": "ws",
    "AW": "ws_per_40",
    "AX": "obpm",
    "AY": "dbpm",
    "AZ": "bpm",
    "BA": "ast_to_turnover",
    "BB": "offensive_involvement",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def title_fragment(fragment: str) -> str:
    chars: list[str] = []
    cap_next = True
    for ch in fragment:
        if cap_next and ch.isalpha():
            chars.append(ch.upper())
            cap_next = False
        else:
            chars.append(ch.lower() if ch.isalpha() else ch)
            if ch.isalpha():
                cap_next = False
        if ch in {"-", "'", "’"}:
            cap_next = True
    return "".join(chars)


def normalize_english_name(value: str) -> str:
    value = collapse_spaces(value)
    if not value:
        return ""
    tokens = []
    for token in value.split(" "):
        if token.isupper() and len(token) <= 4:
            tokens.append(token)
            continue
        if any(ch.isupper() for ch in token[1:]):
            tokens.append(token)
            continue
        tokens.append(title_fragment(token))
    return " ".join(tokens)


def parse_number(value: str) -> int | float | None:
    value = collapse_spaces(value)
    if not value:
        return None
    number = float(value)
    return int(number) if number.is_integer() else round(number, 3)


def xlsx_rows(workbook_path: Path) -> list[dict[str, str]]:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[dict[str, str]] = []
    with ZipFile(workbook_path) as archive:
        shared_strings: list[str] = []
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in shared_root.findall("a:si", namespace):
            text = "".join(node.text or "" for node in item.iterfind(".//a:t", namespace))
            shared_strings.append(text)

        sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in sheet_root.findall(".//a:sheetData/a:row", namespace)[1:]:
            parsed: dict[str, str] = {}
            for col, key in WORKBOOK_HEADERS.items():
                ref = f"{col}{row.attrib['r']}"
                cell = row.find(f"a:c[@r='{ref}']", namespace)
                if cell is None:
                    parsed[key] = ""
                    continue
                value_node = cell.find("a:v", namespace)
                if value_node is None:
                    parsed[key] = ""
                    continue
                value = value_node.text or ""
                if cell.attrib.get("t") == "s":
                    parsed[key] = shared_strings[int(value)]
                else:
                    parsed[key] = value
            rows.append(parsed)
    return rows


def build_prospects(workbook_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    prospects: list[dict[str, Any]] = []
    for index, row in enumerate(xlsx_rows(workbook_path), start=1):
        position_code, position_label = POSITION_MAP.get(row["position_raw"], ("F", row["position_raw"] or "未知"))
        projected_pick = parse_number(row["projected_pick"])
        name_zh = collapse_spaces(row["name_zh"]) or normalize_english_name(row["name_en"])
        name_en = normalize_english_name(row["name_en"])
        prospect = {
            "id": f"prospect-{index:03d}",
            "name": name_zh,
            "name_zh": name_zh,
            "name_en": name_en,
            "projected_pick": projected_pick,
            "class_year": CLASS_YEAR_MAP.get(collapse_spaces(row["class_year"]), collapse_spaces(row["class_year"]) or "未知"),
            "position": position_code,
            "position_label": position_label,
            "school": collapse_spaces(row["school"]),
            "conference": collapse_spaces(row["conference"]),
            "height_cm": parse_number(row["height_cm"]),
            "weight_kg": parse_number(row["weight_kg"]),
            "summary_stats": {
                "minutes": parse_number(row["minutes"]),
                "points": parse_number(row["pts"]),
                "rebounds": parse_number(row["trb"]),
                "assists": parse_number(row["ast"]),
                "steals": parse_number(row["stl"]),
                "blocks": parse_number(row["blk"]),
                "turnovers": parse_number(row["tov"]),
                "fg_pct": parse_number(row["fg_pct"]),
                "three_pct": parse_number(row["three_pct"]),
                "ft_pct": parse_number(row["ft_pct"]),
            },
            "shooting_splits": {
                "fg": parse_number(row["fg"]),
                "fga": parse_number(row["fga"]),
                "fg_pct": parse_number(row["fg_pct"]),
                "three_p": parse_number(row["three_p"]),
                "three_pa": parse_number(row["three_pa"]),
                "three_pct": parse_number(row["three_pct"]),
                "two_p": parse_number(row["two_p"]),
                "two_pa": parse_number(row["two_pa"]),
                "two_pct": parse_number(row["two_pct"]),
                "efg_pct": parse_number(row["efg_pct"]),
                "ft": parse_number(row["ft"]),
                "fta": parse_number(row["fta"]),
                "ft_pct": parse_number(row["ft_pct"]),
            },
            "advanced_stats": {
                "per": parse_number(row["per"]),
                "ts_pct": parse_number(row["ts_pct"]),
                "three_par": parse_number(row["three_par"]),
                "ftr": parse_number(row["ftr"]),
                "pprod": parse_number(row["pprod"]),
                "orb_pct": parse_number(row["orb_pct"]),
                "drb_pct": parse_number(row["drb_pct"]),
                "trb_pct": parse_number(row["trb_pct"]),
                "ast_pct": parse_number(row["ast_pct"]),
                "stl_pct": parse_number(row["stl_pct"]),
                "blk_pct": parse_number(row["blk_pct"]),
                "tov_pct": parse_number(row["tov_pct"]),
                "usg_pct": parse_number(row["usg_pct"]),
                "ows": parse_number(row["ows"]),
                "dws": parse_number(row["dws"]),
                "ws": parse_number(row["ws"]),
                "ws_per_40": parse_number(row["ws_per_40"]),
                "obpm": parse_number(row["obpm"]),
                "dbpm": parse_number(row["dbpm"]),
                "bpm": parse_number(row["bpm"]),
                "ast_to_turnover": parse_number(row["ast_to_turnover"]),
                "offensive_involvement": parse_number(row["offensive_involvement"]),
            },
        }
        prospects.append(prospect)

    sorted_prospects = sorted(
        prospects,
        key=lambda prospect: (
            prospect["projected_pick"] is None,
            prospect["projected_pick"] if prospect["projected_pick"] is not None else 999,
            prospect["name_en"],
        ),
    )
    rankings = [prospect["id"] for prospect in sorted_prospects]
    for rank, prospect in enumerate(sorted_prospects, start=1):
        prospect["rank"] = rank
        prospect["board"] = "workbook_consensus"
    return sorted_prospects, rankings


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:  # pragma: no cover - network fallback path
            last_error = exc
            time.sleep(0.5 * (attempt + 1))

    completed = subprocess.run(
        ["curl", "-L", "--http1.1", "-A", "Mozilla/5.0", url],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive path
        raise RuntimeError(f"Unable to decode JSON from {url}") from (last_error or exc)


def build_roster_snapshot(team_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    team_catalog = fetch_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")
    teams_raw = team_catalog["sports"][0]["leagues"][0]["teams"]
    by_abbr = {
        CANONICAL_TEAM_ABBRS.get(wrapped["team"]["abbreviation"], wrapped["team"]["abbreviation"]): wrapped["team"]
        for wrapped in teams_raw
    }

    teams: list[dict[str, Any]] = []
    for profile in team_profiles:
        lookup_abbr = ESPN_ABBR_ALIASES.get(profile["abbr"], profile["abbr"])
        team = by_abbr.get(profile["abbr"]) or by_abbr[lookup_abbr]
        roster_payload = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team['id']}/roster")
        roster_players = []
        for athlete in roster_payload.get("athletes", []):
            roster_players.append(
                {
                    "id": f"nba-{athlete['id']}",
                    "source_id": athlete["id"],
                    "asset_type": "roster_player",
                    "name": athlete.get("displayName") or athlete.get("fullName"),
                    "short_name": athlete.get("shortName"),
                    "position": athlete.get("position", {}).get("abbreviation", ""),
                    "position_label": athlete.get("position", {}).get("displayName", ""),
                    "age": athlete.get("age"),
                    "height": athlete.get("displayHeight"),
                    "weight_lbs": athlete.get("weight"),
                    "jersey": athlete.get("jersey"),
                }
            )
        teams.append(
            {
                "id": profile["id"],
                "abbr": profile["abbr"],
                "name": profile["zh_name"],
                "needs": profile["needs"],
                "espn_id": team["id"],
                "name_en": team.get("displayName", ""),
                "city": team.get("location", ""),
                "nickname": team.get("name", ""),
                "slug": team.get("slug", ""),
                "primary_color": f"#{team.get('color', '111111')}",
                "secondary_color": f"#{team.get('alternateColor', 'f3f3f3')}",
                "logo_url": next((logo["href"] for logo in team.get("logos", []) if "default" in logo.get("rel", [])), team.get("logos", [{}])[0].get("href")),
                "roster_players": roster_players,
            }
        )

    return {
        "updated_at": iso_now(),
        "season": "2025-26",
        "source": "ESPN public NBA teams and roster endpoints",
        "teams": teams,
    }


def fetch_tankathon_html() -> str:
    completed = subprocess.run(
        ["curl", "-L", "--http1.1", "-A", "Mozilla/5.0", "https://www.tankathon.com/full_draft"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def build_draft_order() -> dict[str, Any]:
    html = fetch_tankathon_html()
    rows = re.findall(r'<tr><td class="pick-number">(\d+)</td>\s*<td>(.*?)</td></tr>', html)
    if len(rows) != 60:
        raise RuntimeError(f"Expected 60 draft-order rows from Tankathon, found {len(rows)}.")

    order = []
    for pick_raw, body in rows:
        pick = int(pick_raw)
        codes = re.findall(r"/nba/([a-z0-9]+)\.svg", body)
        if not codes:
            raise RuntimeError(f"Missing team code for pick {pick}.")
        current_team = TEAM_CODE_MAP[codes[0]]
        original_team = TEAM_CODE_MAP[codes[1]] if len(codes) > 1 else current_team
        order.append(
            {
                "pick": pick,
                "round": 1 if pick <= 30 else 2,
                "original_team": original_team,
                "current_team": current_team,
                "via": original_team if original_team != current_team else None,
            }
        )

    return {
        "updated_at": iso_now(),
        "source": "Tankathon full_draft",
        "source_url": "https://www.tankathon.com/full_draft",
        "draft_order": order,
    }


def build_dataset(
    workbook_path: Path,
    roster_snapshot: dict[str, Any],
    draft_order_snapshot: dict[str, Any],
    pick_values: dict[str, int],
) -> dict[str, Any]:
    prospects, rankings = build_prospects(workbook_path)
    teams = roster_snapshot["teams"]
    order = draft_order_snapshot["draft_order"]

    return {
        "updated_at": iso_now(),
        "workbook_source": str(workbook_path),
        "teams": teams,
        "players": prospects,
        "boards": [
            {
                "id": "workbook_consensus",
                "label": "附件 Big Board",
                "source_url": None,
            }
        ],
        "rankings": {"workbook_consensus": rankings},
        "draft_order": order,
        "order_sources": [
            {
                "id": "tankathon_20260318",
                "label": "Tankathon 2026 默认顺位",
                "source_url": draft_order_snapshot.get("source_url"),
            }
        ],
        "pick_values": pick_values,
        "pick_value_source": "Kevin Pelton 2017 / NBA Sense",
        "pick_value_tolerance": 100,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the 2026 mock draft dataset from workbook + cached configs.")
    parser.add_argument("--workbook", required=True, help="Path to the 2026 workbook.")
    parser.add_argument("--refresh-rosters", action="store_true", help="Fetch fresh NBA team rosters from ESPN.")
    parser.add_argument("--refresh-order", action="store_true", help="Fetch the latest Tankathon 2026 full draft order.")
    args = parser.parse_args(argv)

    workbook_path = Path(args.workbook).expanduser().resolve()
    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    team_profiles = read_json(TEAM_PROFILES_PATH)
    pick_values = read_json(PICK_VALUES_PATH)

    if args.refresh_rosters or not ROSTER_SNAPSHOT_PATH.exists():
        roster_snapshot = build_roster_snapshot(team_profiles)
        write_json(ROSTER_SNAPSHOT_PATH, roster_snapshot)
    else:
        roster_snapshot = read_json(ROSTER_SNAPSHOT_PATH)

    if args.refresh_order or not DRAFT_ORDER_PATH.exists():
        draft_order_snapshot = build_draft_order()
        write_json(DRAFT_ORDER_PATH, draft_order_snapshot)
    else:
        draft_order_snapshot = read_json(DRAFT_ORDER_PATH)

    dataset = build_dataset(workbook_path, roster_snapshot, draft_order_snapshot, pick_values)
    write_json(OUTPUT_PATH, dataset)
    print(f"Wrote {len(dataset['players'])} prospects to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
