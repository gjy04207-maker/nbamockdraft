from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "draft"

CACHE_TTL_SECONDS = 300
_CACHE: dict = {"ts": 0.0, "data": None}


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _default_teams() -> List[dict]:
    return [
        {"id": "ATL", "abbr": "ATL", "name": "亚特兰大 老鹰", "needs": ["G", "F"]},
        {"id": "BOS", "abbr": "BOS", "name": "波士顿 凯尔特人", "needs": ["G", "F"]},
        {"id": "BKN", "abbr": "BKN", "name": "布鲁克林 篮网", "needs": ["G", "C"]},
        {"id": "CHA", "abbr": "CHA", "name": "夏洛特黄蜂", "needs": ["F", "C"]},
        {"id": "CHI", "abbr": "CHI", "name": "芝加哥 公牛", "needs": ["G", "F"]},
        {"id": "CLE", "abbr": "CLE", "name": "克利夫兰 骑士", "needs": ["F", "C"]},
        {"id": "DAL", "abbr": "DAL", "name": "达拉斯 独行侠", "needs": ["F", "C"]},
        {"id": "DEN", "abbr": "DEN", "name": "丹佛 掘金", "needs": ["G", "F"]},
        {"id": "DET", "abbr": "DET", "name": "底特律 活塞", "needs": ["G", "F"]},
        {"id": "GSW", "abbr": "GSW", "name": "金州 勇士", "needs": ["G", "F"]},
        {"id": "HOU", "abbr": "HOU", "name": "休斯顿 火箭", "needs": ["G", "F"]},
        {"id": "IND", "abbr": "IND", "name": "印第安纳 步行者", "needs": ["F", "C"]},
        {"id": "LAC", "abbr": "LAC", "name": "洛杉矶 快船", "needs": ["G", "F"]},
        {"id": "LAL", "abbr": "LAL", "name": "洛杉矶 湖人", "needs": ["G", "C"]},
        {"id": "MEM", "abbr": "MEM", "name": "孟菲斯 灰熊", "needs": ["F", "C"]},
        {"id": "MIA", "abbr": "MIA", "name": "迈阿密 热火", "needs": ["G", "F"]},
        {"id": "MIL", "abbr": "MIL", "name": "密尔沃基 雄鹿", "needs": ["G", "F"]},
        {"id": "MIN", "abbr": "MIN", "name": "明尼苏达 森林狼", "needs": ["G", "F"]},
        {"id": "NOP", "abbr": "NOP", "name": "新奥尔良 鹈鹕", "needs": ["G", "C"]},
        {"id": "NYK", "abbr": "NYK", "name": "纽约 尼克斯", "needs": ["G", "F"]},
        {"id": "OKC", "abbr": "OKC", "name": "俄克拉荷马 雷霆", "needs": ["G", "F"]},
        {"id": "ORL", "abbr": "ORL", "name": "奥兰多 魔术", "needs": ["F", "C"]},
        {"id": "PHI", "abbr": "PHI", "name": "费城 76人", "needs": ["G", "F"]},
        {"id": "PHX", "abbr": "PHX", "name": "菲尼克斯 太阳", "needs": ["G", "F"]},
        {"id": "POR", "abbr": "POR", "name": "波特兰 开拓者", "needs": ["G", "C"]},
        {"id": "SAC", "abbr": "SAC", "name": "萨克拉门托 国王", "needs": ["G", "F"]},
        {"id": "SAS", "abbr": "SAS", "name": "圣安东尼奥 马刺", "needs": ["G", "F"]},
        {"id": "TOR", "abbr": "TOR", "name": "多伦多 猛龙", "needs": ["F", "C"]},
        {"id": "UTA", "abbr": "UTA", "name": "犹他 爵士", "needs": ["G", "F"]},
        {"id": "WAS", "abbr": "WAS", "name": "华盛顿 奇才", "needs": ["G", "F"]},
    ]


def _default_players(count: int = 90) -> List[dict]:
    positions = ["G", "G/F", "F", "F/C", "C"]
    schools = [
        "杜克",
        "肯塔基",
        "堪萨斯",
        "北卡",
        "维拉诺瓦",
        "冈萨加",
        "贝勒",
        "休斯顿",
        "密歇根州立",
        "UCLA",
        "阿拉巴马",
        "田纳西",
    ]
    archetypes = [
        "持球核心",
        "侧翼防守者",
        "空间型四号位",
        "换防尖兵",
        "护筐内线",
        "挡拆终结",
        "稳定投射",
        "转换加速",
        "二阵组织",
        "低位强攻",
    ]
    heights = ["6'1\"", "6'3\"", "6'4\"", "6'6\"", "6'7\"", "6'8\"", "6'9\"", "6'10\"", "7'0\""]

    players: List[dict] = []
    for i in range(count):
        idx = i + 1
        players.append(
            {
                "id": f"p{idx:03d}",
                "name": f"新秀 {idx:02d}",
                "position": positions[i % len(positions)],
                "school": schools[i % len(schools)],
                "height": heights[i % len(heights)],
                "age": 18 + (i % 5),
                "notes": archetypes[i % len(archetypes)],
            }
        )
    return players


def _rotate_list(items: List[str], shift: int) -> List[str]:
    if not items:
        return items
    shift = shift % len(items)
    return items[shift:] + items[:shift]


def _build_boards(players: List[dict]) -> tuple[List[dict], Dict[str, List[str]]]:
    base_ids = [p["id"] for p in players]
    boards = [
        {
            "id": "tankathon",
            "label": "Tankathon Big Board",
            "source_url": "https://www.tankathon.com/mock_draft",
        },
        {
            "id": "fanspo",
            "label": "Fanspo Big Board",
            "source_url": "https://fanspo.com/nba/mock-draft-simulator",
        },
        {
            "id": "noceilings",
            "label": "No Ceilings Big Board",
            "source_url": "https://noceilingsnba.com",
        },
    ]

    rankings: Dict[str, List[str]] = {
        "tankathon": base_ids,
        "fanspo": _rotate_list(base_ids, 5),
        "noceilings": [],
    }

    rng = random.Random(7)
    shuffled = base_ids[:]
    rng.shuffle(shuffled)
    rankings["noceilings"] = shuffled

    return boards, rankings


def _build_draft_order(teams: List[dict], rounds: int = 2) -> List[dict]:
    order: List[dict] = []
    pick_no = 1
    for rd in range(1, rounds + 1):
        for team in teams:
            order.append(
                {
                    "pick": pick_no,
                    "round": rd,
                    "original_team": team["id"],
                    "current_team": team["id"],
                    "via": None,
                }
            )
            pick_no += 1
    return order


def _build_pick_values(total_picks: int = 60) -> Dict[int, int]:
    values: Dict[int, int] = {}
    for pick in range(1, total_picks + 1):
        curve = 3000 * (0.965 ** (pick - 1))
        values[pick] = max(100, int(round(curve)))
    return values


def _default_data() -> dict:
    teams = _default_teams()
    players = _default_players()
    boards, rankings = _build_boards(players)
    draft_order = _build_draft_order(teams, rounds=2)
    pick_values = _build_pick_values(total_picks=len(draft_order))
    return {
        "updated_at": _iso_now(),
        "teams": teams,
        "players": players,
        "boards": boards,
        "rankings": rankings,
        "draft_order": draft_order,
        "pick_values": pick_values,
        "order_sources": [
            {"id": "tankathon", "label": "Tankathon 模拟顺序"},
            {"id": "custom", "label": "自定义顺序"},
        ],
        "pick_value_source": "nbasense (参考)",
        "pick_value_tolerance": 100,
    }


def get_draft_data() -> dict:
    now = time.time()
    if _CACHE["data"] and now - _CACHE["ts"] < CACHE_TTL_SECONDS:
        return _CACHE["data"]

    payload = _load_json(DATA_DIR / "draft_data.json")
    if not payload:
        payload = _default_data()

    _CACHE["data"] = payload
    _CACHE["ts"] = now
    return payload


def get_board_players(data: dict, board_id: str) -> List[dict]:
    players = data.get("players", [])
    rankings = data.get("rankings", {})
    order = rankings.get(board_id) or rankings.get("tankathon") or [p.get("id") for p in players]
    players_by_id = {p["id"]: p for p in players}

    sorted_players = []
    for idx, player_id in enumerate(order, start=1):
        player = players_by_id.get(player_id)
        if not player:
            continue
        merged = dict(player)
        merged["rank"] = idx
        merged["board"] = board_id
        sorted_players.append(merged)

    return sorted_players


def get_pick_value(data: dict, pick_no: int) -> int:
    values = data.get("pick_values", {})
    return int(values.get(str(pick_no), values.get(pick_no, 0)))
