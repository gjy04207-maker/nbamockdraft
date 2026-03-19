from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
from . import draft_data

ROOT = Path(__file__).resolve().parents[3]
CBA_JSONL = ROOT / "data" / "cba" / "parsed" / "cba_paragraphs.jsonl"
DB_DSN = "dbname=nba_writer"

app = FastAPI(title="CBA Search API", version="0.1.0")

cors_allow_origins = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
cors_allow_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX")
cors_allow_credentials = "*" not in cors_allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_origin_regex=cors_allow_origin_regex,
    allow_credentials=cors_allow_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class CBAHit(BaseModel):
    page: int
    para: int
    text: str
    score: int


class CBASearchResponse(BaseModel):
    query: str
    total: int
    hits: List[CBAHit]


class FactSource(BaseModel):
    source: str
    facts: List[str]


class FactCheckRequest(BaseModel):
    draft: str
    sources: List[FactSource]


class FactIssue(BaseModel):
    type: str
    message: str
    span: str


class FactCheckResponse(BaseModel):
    issues: List[FactIssue]


class ChatMessage(BaseModel):
    role: str
    text: str


class GenerateRequest(BaseModel):
    prompt: str
    history: List[ChatMessage] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    title: str
    draft: str
    assistant_reply: str
    directions: List[str]
    sources: List[str]
    fact_snippets: List[str]


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str
    facts: List[str] = Field(default_factory=list)


class RewriteResponse(BaseModel):
    rewritten_text: str


class DraftRosterPlayer(BaseModel):
    id: str
    source_id: Optional[str] = None
    asset_type: str
    name: str
    short_name: Optional[str] = None
    position: str = ""
    position_label: Optional[str] = None
    age: Optional[int] = None
    height: Optional[str] = None
    weight_lbs: Optional[Union[float, int]] = None
    jersey: Optional[str] = None


class DraftTeam(BaseModel):
    id: str
    abbr: str
    name: str
    needs: List[str] = Field(default_factory=list)
    espn_id: Optional[str] = None
    name_en: Optional[str] = None
    city: Optional[str] = None
    nickname: Optional[str] = None
    slug: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    logo_url: Optional[str] = None
    roster_players: List[DraftRosterPlayer] = Field(default_factory=list)


class DraftBoard(BaseModel):
    id: str
    label: str
    source_url: Optional[str] = None


class DraftOrderSource(BaseModel):
    id: str
    label: str
    source_url: Optional[str] = None


class DraftPick(BaseModel):
    pick: int
    round: int
    original_team: str
    current_team: str
    via: Optional[str] = None


class DraftMetaResponse(BaseModel):
    rounds: List[int]
    order_sources: List[DraftOrderSource]
    boards: List[DraftBoard]
    teams: List[DraftTeam]
    draft_order: List[DraftPick]
    updated_at: str
    pick_value_source: str
    pick_value_tolerance: int


class DraftPlayer(BaseModel):
    id: str
    name: str
    name_zh: str
    name_en: str
    projected_pick: Optional[int] = None
    class_year: str
    position: str
    position_label: str
    school: str
    conference: str
    height_cm: Optional[Union[int, float]] = None
    weight_kg: Optional[Union[int, float]] = None
    summary_stats: Dict[str, Optional[Union[int, float]]] = Field(default_factory=dict)
    shooting_splits: Dict[str, Optional[Union[int, float]]] = Field(default_factory=dict)
    advanced_stats: Dict[str, Optional[Union[int, float]]] = Field(default_factory=dict)
    rank: Optional[int] = None
    board: Optional[str] = None


class DraftPlayersResponse(BaseModel):
    board: str
    players: List[DraftPlayer]


class DraftPickRequest(BaseModel):
    pick: int
    team_id: str
    board_id: str
    available_player_ids: List[str]
    use_needs: bool = True


class DraftPickResponse(BaseModel):
    pick: int
    team_id: str
    player: DraftPlayer
    reason: str


class TradePlayerAssetRequest(BaseModel):
    id: str
    name: str
    asset_type: str
    origin_pick: Optional[int] = None


class TradeAssetRouteRequest(BaseModel):
    id: str
    asset_type: str
    recipient_team_id: str
    pick_no: Optional[int] = None
    name: Optional[str] = None
    origin_pick: Optional[int] = None


class TradeParticipantRequest(BaseModel):
    team_id: str
    assets: List[TradeAssetRouteRequest] = Field(default_factory=list)


class TradeEvaluateRequest(BaseModel):
    participants: List[TradeParticipantRequest] = Field(default_factory=list)


class TradeAssetDescriptor(BaseModel):
    team_id: str
    recipient_team_id: str
    id: str
    label: str
    asset_type: str
    value: Optional[int] = None


class TradeTeamSummary(BaseModel):
    team_id: str
    send_value: int
    receive_value: int
    delta: int
    outgoing_asset_count: int
    incoming_asset_count: int


class TradeEvaluateResponse(BaseModel):
    status: Literal["accepted", "rejected", "manual_review_required"]
    delta: int
    tolerance: int
    team_summaries: List[TradeTeamSummary] = Field(default_factory=list)
    counted_assets: List[TradeAssetDescriptor] = Field(default_factory=list)
    ignored_assets: List[TradeAssetDescriptor] = Field(default_factory=list)
    reason: str



def _tokenize(q: str) -> List[str]:
    # Simple tokenizer: split on non-word, keep CJK chars.
    tokens = re.findall(r"[A-Za-z0-9']+|[\u4e00-\u9fff]", q)
    return [t.lower() for t in tokens if t.strip()]


def _score(text: str, tokens: List[str]) -> int:
    if not tokens:
        return 0
    text_l = text.lower()
    return sum(text_l.count(t) for t in tokens)


def _load_paragraphs():
    if not CBA_JSONL.exists():
        raise FileNotFoundError(f"CBA index not found: {CBA_JSONL}")
    with CBA_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _load_paragraphs_from_db(limit: int, tokens: List[str]):
    if not tokens:
        return []
    pattern = "%" + "%".join(tokens) + "%"
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT page, paragraph, text
                FROM cba_rules
                WHERE text ILIKE %s
                LIMIT %s
                """,
                (pattern, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {"page": r[0], "para": r[1], "text": r[2]}
        for r in rows
    ]


TEAM_ZH_ALIASES = {
    "老鹰": "hawks",
    "凯尔特人": "celtics",
    "篮网": "nets",
    "黄蜂": "hornets",
    "公牛": "bulls",
    "骑士": "cavaliers",
    "独行侠": "mavericks",
    "掘金": "nuggets",
    "活塞": "pistons",
    "勇士": "warriors",
    "火箭": "rockets",
    "步行者": "pacers",
    "快船": "clippers",
    "湖人": "lakers",
    "灰熊": "grizzlies",
    "热火": "heat",
    "雄鹿": "bucks",
    "森林狼": "timberwolves",
    "鹈鹕": "pelicans",
    "尼克斯": "knicks",
    "雷霆": "thunder",
    "魔术": "magic",
    "76人": "76ers",
    "太阳": "suns",
    "开拓者": "trail blazers",
    "国王": "kings",
    "马刺": "spurs",
    "猛龙": "raptors",
    "爵士": "jazz",
    "奇才": "wizards",
}

TEAM_CATALOG_CACHE: dict = {"ts": 0.0, "teams": []}


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_team_catalog() -> list[dict]:
    # Refresh every 6 hours.
    if TEAM_CATALOG_CACHE["teams"] and (time.time() - TEAM_CATALOG_CACHE["ts"] < 21600):
        return TEAM_CATALOG_CACHE["teams"]
    try:
        payload = _fetch_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")
        teams_raw = payload.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
    except Exception:
        return TEAM_CATALOG_CACHE["teams"]

    teams: list[dict] = []
    for wrapped in teams_raw:
        team = wrapped.get("team", {})
        display_name = team.get("displayName", "")
        short_name = team.get("shortDisplayName", "")
        nickname = team.get("name", "")
        abbr = team.get("abbreviation", "")
        slug = team.get("slug", "")
        if not display_name:
            continue
        teams.append(
            {
                "id": str(team.get("id", "")),
                "display_name": display_name,
                "short_name": short_name,
                "nickname": nickname,
                "abbreviation": abbr,
                "slug": slug,
            }
        )

    TEAM_CATALOG_CACHE["ts"] = time.time()
    TEAM_CATALOG_CACHE["teams"] = teams
    return teams


def _score_team_match(query: str, team: dict) -> float:
    if not query.strip():
        return 0.0
    q = query.lower().strip()
    fields = [
        str(team.get("display_name", "")).lower(),
        str(team.get("short_name", "")).lower(),
        str(team.get("nickname", "")).lower(),
        str(team.get("abbreviation", "")).lower(),
        str(team.get("slug", "")).lower(),
    ]
    best = 0.0
    for field in fields:
        if not field:
            continue
        if q == field:
            best = max(best, 1.0)
        elif q in field or field in q:
            best = max(best, 0.9)
        else:
            best = max(best, SequenceMatcher(None, q, field).ratio())
    return best


def _extract_team_query_with_llm(prompt: str, history: list[ChatMessage], team_catalog: list[dict]) -> str | None:
    if not os.getenv("OPENAI_API_KEY", "").strip() or not team_catalog:
        return None
    history_lines = [f"{m.role}: {m.text}" for m in history[-6:]]
    roster = ", ".join(t.get("display_name", "") for t in team_catalog if t.get("display_name"))
    messages = [
        {
            "role": "system",
            "content": (
                "你是NBA实体识别器。任务：从用户输入中识别最相关的NBA球队。\n"
                "输出JSON: {\"team_query\":\"...\", \"is_team_related\":true/false}。\n"
                "若无法确定球队，team_query返回空字符串。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"用户输入: {prompt}\n"
                f"最近对话: {' | '.join(history_lines)}\n"
                f"候选球队: {roster}"
            ),
        },
    ]
    parsed = _call_openai_chat(messages)
    if not parsed:
        return None
    if not bool(parsed.get("is_team_related")):
        return None
    team_query = str(parsed.get("team_query", "")).strip()
    return team_query or None


def _resolve_team(prompt: str, history: list[ChatMessage]) -> dict | None:
    team_catalog = _fetch_team_catalog()
    if not team_catalog:
        return None

    queries = [prompt]
    llm_query = _extract_team_query_with_llm(prompt, history, team_catalog)
    if llm_query:
        queries.insert(0, llm_query)

    for zh, en_alias in TEAM_ZH_ALIASES.items():
        if zh in prompt:
            queries.insert(0, en_alias)

    best_team = None
    best_score = 0.0
    for query in queries:
        for team in team_catalog:
            score = _score_team_match(query, team)
            if score > best_score:
                best_score = score
                best_team = team

    if best_team and best_score >= 0.62:
        return best_team
    return None


def _extract_recent_team_games(team: dict, days: int = 10, limit: int = 5) -> tuple[list[str], list[str]]:
    facts: list[str] = []
    sources: list[str] = []
    now = datetime.now(timezone.utc)
    seen = set()
    terms = {
        str(team.get("display_name", "")).lower(),
        str(team.get("short_name", "")).lower(),
        str(team.get("nickname", "")).lower(),
        str(team.get("abbreviation", "")).lower(),
        str(team.get("slug", "")).lower(),
    }
    terms = {t for t in terms if t}

    for delta in range(days):
        date = (now - timedelta(days=delta)).strftime("%Y%m%d")
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date}"
        try:
            payload = _fetch_json(url)
        except Exception:
            continue
        events = payload.get("events", [])
        for event in events:
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            matched = False
            for c in competitors:
                comp_name = str(c.get("team", {}).get("displayName", "")).lower()
                comp_short = str(c.get("team", {}).get("shortDisplayName", "")).lower()
                comp_abbr = str(c.get("team", {}).get("abbreviation", "")).lower()
                if any(term in comp_name or term in comp_short or term == comp_abbr for term in terms):
                    matched = True
                    break
            if not matched:
                continue
            key = event.get("id")
            if key in seen:
                continue
            seen.add(key)

            short_name = event.get("shortName", "")
            status = event.get("status", {}).get("type", {}).get("description", "")
            score_text = " vs ".join(
                f"{c.get('team', {}).get('abbreviation', '')} {c.get('score', '-')}" for c in competitors
            )
            fact = f"{date}: {short_name} | {status} | {score_text}"
            facts.append(fact)
            sources.append(url)
            if len(facts) >= limit:
                return facts, sources
    return facts, sources


def _extract_nba_news(prompt: str, limit: int = 5) -> tuple[list[str], list[str]]:
    facts: list[str] = []
    sources: list[str] = []
    query = quote(prompt)
    search_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit={limit}&search={query}"
    fallback_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit={limit}"

    for url in [search_url, fallback_url]:
        try:
            payload = _fetch_json(url)
        except Exception:
            continue
        articles = payload.get("articles", [])
        for article in articles[:limit]:
            title = article.get("headline", "")
            published = article.get("published", "")
            desc = article.get("description", "")
            if not title:
                continue
            facts.append(f"{published}: {title}。{desc}".strip())
            sources.append(article.get("links", {}).get("web", {}).get("href", url))
        if facts:
            break
    return facts, sources


def _build_directions(prompt: str, facts: list[str], team_mode: bool) -> list[str]:
    if team_mode:
        return [
            "方向1：最近5场结果和关键比分波动，先给结论再给原因。",
            "方向2：拆进攻与防守两端，分别给一个最明显变化点。",
            "方向3：把轮换与关键回合放在一起写，突出教练决策影响。",
        ]
    if "风格" in prompt or "转变" in prompt or "趋势" in prompt:
        return [
            "方向1：用时间线写法，分成两个阶段比较风格变化。",
            "方向2：用指标写法，围绕节奏、三分占比、换防频率组织论证。",
            "方向3：用案例写法，选2-3支球队做正反例。",
        ]
    return [
        "方向1：先定义问题，再给三条证据。",
        "方向2：先给结论，再按比赛片段回放论证。",
        "方向3：先讲争议点，再给数据与反证。",
    ]


def _build_assistant_reply(prompt: str, directions: list[str], facts: list[str]) -> str:
    if facts:
        top_fact = facts[0]
        return (
            f"我先按你的要求完成了信息检索。当前主题是「{prompt}」。\n"
            f"先给你一个可下笔的起点：{top_fact}\n"
            "下面给你3个写作方向，你选一个我就继续展开成完整首稿。"
        )
    return (
        f"我理解你的主题是「{prompt}」，但这轮没有拿到有效外部数据。\n"
        "你可以补充更具体的对象（球队/时间段/球员），我会再检索并给出可写作方向。"
    )


def _parse_direction_choice(prompt: str) -> int | None:
    m = re.match(r"^\s*(?:方向)?\s*([123])\s*[。.\-]?\s*$", prompt)
    if not m:
        return None
    return int(m.group(1))


def _resolve_prompt(prompt: str, history: list[ChatMessage]) -> tuple[str, int | None]:
    choice = _parse_direction_choice(prompt)
    followup_markers = ["展开", "继续", "细说", "详细", "按", "改写", "润色", "第二", "第一", "第三"]
    previous_user_msgs = [
        m.text.strip()
        for m in history
        if m.role == "user"
        and m.text.strip()
        and m.text.strip() != prompt
        and _parse_direction_choice(m.text.strip()) is None
    ]

    if choice is not None and previous_user_msgs:
        return f"{previous_user_msgs[-1]}（用户选择方向{choice}）", choice

    if len(prompt) > 20 and not any(m in prompt for m in followup_markers):
        return prompt, None
    if not any(m in prompt for m in followup_markers):
        return prompt, None

    if not previous_user_msgs:
        return prompt, choice
    return f"{previous_user_msgs[-1]}（用户追问：{prompt}）", choice


def _extract_cba_facts(prompt: str, limit: int = 3) -> tuple[list[str], list[str]]:
    tokens = _tokenize(prompt)
    rows = _load_paragraphs_from_db(limit, tokens)
    facts: list[str] = []
    sources: list[str] = []
    for row in rows:
        page = row.get("page")
        para = row.get("para")
        text = row.get("text", "")
        facts.append(f"CBA P{page} Para {para}: {text}")
        sources.append(f"/cba.pdf#page={page}")
    return facts, sources


def _collect_retrieved_facts(prompt: str, history: list[ChatMessage]) -> tuple[list[str], list[str], bool]:
    team = _resolve_team(prompt, history)
    facts: list[str] = []
    sources: list[str] = []
    team_mode = False

    if team:
        team_facts, team_sources = _extract_recent_team_games(team=team, days=12, limit=6)
        facts.extend(team_facts)
        sources.extend(team_sources)
        team_mode = True
        if not facts:
            # Team was detected but no recent games found; fallback to team-focused news.
            fallback_query = team.get("display_name", prompt)
            news_facts, news_sources = _extract_nba_news(str(fallback_query), limit=6)
            facts.extend(news_facts)
            sources.extend(news_sources)
    else:
        news_facts, news_sources = _extract_nba_news(prompt, limit=6)
        facts.extend(news_facts)
        sources.extend(news_sources)

    cba_keywords = ["cba", "劳资", "交易", "鸟权", "奢侈税", "工资帽", "合同"]
    if any(k in prompt.lower() for k in cba_keywords) or any(k in prompt for k in cba_keywords):
        cba_facts, cba_sources = _extract_cba_facts(prompt, limit=3)
        facts.extend(cba_facts)
        sources.extend(cba_sources)

    # Dedupe while preserving order.
    dedup_facts = list(dict.fromkeys(facts))
    dedup_sources = list(dict.fromkeys(sources))
    return dedup_facts, dedup_sources, team_mode


def _safe_json_parse(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _call_openai_chat(messages: list[dict]) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    return _safe_json_parse(content) if content else None


def _run_grounded_llm(
    prompt: str,
    effective_prompt: str,
    history: list[ChatMessage],
    facts: list[str],
    directions: list[str],
    selected_direction: str | None,
) -> dict | None:
    history_msgs = []
    for m in history[-8:]:
        role = "assistant" if m.role == "ai" else "user"
        history_msgs.append({"role": role, "content": m.text})

    facts_block = "\n".join(f"[F{i + 1}] {fact}" for i, fact in enumerate(facts)) if facts else "无可用事实"
    directions_block = "\n".join(directions)
    system_prompt = (
        "你是NBA写作助手。你必须先理解用户自然语言，再基于提供的事实输出。\n"
        "严禁编造未在事实列表出现的具体数据和事件。若证据不足，必须明确说“证据不足”。\n"
        "输出必须是JSON对象，字段: title, assistant_reply, draft, directions。\n"
        "draft必须是一篇可直接发布的完整首稿（不少于4段），不要只给提纲。\n"
        "directions必须是长度3的字符串数组。"
    )
    user_prompt = (
        f"用户原始输入: {prompt}\n"
        f"解析后主题: {effective_prompt}\n\n"
        f"用户选择方向: {selected_direction or '未指定'}\n\n"
        f"可用事实:\n{facts_block}\n\n"
        f"建议方向候选:\n{directions_block}\n\n"
        "请生成：\n"
        "1) assistant_reply: 对话口吻，先给结论再提下一步问题；\n"
        "2) draft: 可直接编辑的完整首稿，显式引用[F#]；\n"
        "3) title: 简洁标题；\n"
        "4) directions: 3条可执行写作方向。"
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": user_prompt})
    return _call_openai_chat(messages)


def _render_fallback_full_draft(
    topic: str,
    facts: list[str],
    selected_direction: str | None,
) -> str:
    if not facts:
        return (
            "【生成草稿】\n"
            f"主题：{topic}\n\n"
            "证据不足。当前没有检索到可用事实，建议补充明确时间范围与样本对象后重试。"
        )

    evidence_lines = "\n".join(f"- {f}" for f in facts[:5])
    direction_line = selected_direction or "方向1：最近结果波动 -> 原因拆解 -> 后续观察点。"

    return (
        "【生成草稿】\n"
        f"主题：{topic}\n\n"
        "先给结论：这支球队近期状态上升不是偶然，而是比赛执行、轮换衔接和关键回合处理共同改善的结果。\n\n"
        "证据层面，最近样本显示他们在比分控制和收官阶段更稳定，领先后被追分的幅度减小，逆风时的反扑效率也明显提升。\n"
        "以下是本轮检索到的核心事实：\n"
        f"{evidence_lines}\n\n"
        "从战术上看，最关键的变化是回合决策速度和角色分工。球权更集中在高效率发起点，弱侧终结点得到更干净的出手机会，\n"
        "同时防守端的协防轮转更连贯，减少了连续失分的波段。\n\n"
        f"如果按你当前选择的写法推进，建议重点执行：{direction_line}\n"
        "最后一段可以落在“可持续性判断”：这波火热表现能否延续，取决于伤病稳定性、轮换强度和对手针对性调整后的应对质量。"
    )


def _get_draft_data() -> dict:
    return draft_data.get_draft_data()


def _build_default_original_team_order(draft_order: list[dict]) -> list[str]:
    first_round = [pick for pick in draft_order if int(pick.get("round", 0)) == 1]
    first_round.sort(key=lambda item: int(item.get("pick", 999)))
    return [str(pick.get("original_team")) for pick in first_round if pick.get("original_team")]


def _build_draft_order_from_original_order(data: dict, base_original_order: list[str]) -> list[dict]:
    default_order = [dict(pick) for pick in data.get("draft_order", [])]
    rank_by_team = {team_id: index for index, team_id in enumerate(base_original_order)}
    rounds = sorted({int(pick.get("round", 0)) for pick in default_order})
    rebuilt: list[dict] = []
    next_pick_no = 1

    for round_no in rounds:
        round_picks = [dict(pick) for pick in default_order if int(pick.get("round", 0)) == round_no]
        round_picks.sort(key=lambda pick: (rank_by_team.get(str(pick.get("original_team")), 999), int(pick.get("pick", 999))))
        for pick in round_picks:
            pick["pick"] = next_pick_no
            rebuilt.append(pick)
            next_pick_no += 1

    return rebuilt


def _find_team(teams: list[dict], team_id: str) -> dict | None:
    for team in teams:
        if team.get("id") == team_id:
            return team
    return None


def _position_matches_need(position: str, needs: list[str]) -> bool:
    pos_upper = position.upper()
    for need in needs:
        if need in pos_upper:
            return True
    return False


def _choose_auto_player(players: list[dict], available_ids: set[str], needs: list[str], use_needs: bool) -> dict | None:
    if use_needs and needs:
        for player in players:
            if player.get("id") not in available_ids:
                continue
            if _position_matches_need(player.get("position", ""), needs):
                return player
    for player in players:
        if player.get("id") in available_ids:
            return player
    return None


def _build_trade_label(asset_type: str, pick_no: int | None = None, name: str | None = None) -> str:
    if asset_type == "pick" and pick_no is not None:
        return f"Pick #{pick_no}"
    if asset_type == "drafted_rights" and pick_no is not None and name:
        return f"{name} 签约权 (#{pick_no})"
    return name or asset_type


def _resolve_asset_pick_no(asset: TradeAssetRouteRequest) -> int | None:
    if asset.pick_no is not None:
        return asset.pick_no
    match = re.search(r"(\d+)$", asset.id)
    if match:
        return int(match.group(1))
    return None


def _evaluate_trade_request(data: dict, payload: TradeEvaluateRequest) -> dict:
    tolerance = int(data.get("pick_value_tolerance", 100))
    participants = [participant for participant in payload.participants if participant.team_id.strip()]

    if len(participants) < 2:
        return {
            "status": "rejected",
            "delta": 0,
            "tolerance": tolerance,
            "team_summaries": [],
            "counted_assets": [],
            "ignored_assets": [],
            "reason": "交易至少需要两支球队参与。",
        }

    if len(participants) > 5:
        return {
            "status": "rejected",
            "delta": 0,
            "tolerance": tolerance,
            "team_summaries": [],
            "counted_assets": [],
            "ignored_assets": [],
            "reason": "交易最多支持五支球队参与。",
        }

    team_ids = [participant.team_id for participant in participants]
    if len(set(team_ids)) != len(team_ids):
        return {
            "status": "rejected",
            "delta": 0,
            "tolerance": tolerance,
            "team_summaries": [],
            "counted_assets": [],
            "ignored_assets": [],
            "reason": "同一支球队不能在同一笔交易里重复出现。",
        }

    for participant in participants:
        for asset in participant.assets:
            if not asset.recipient_team_id:
                return {
                    "status": "rejected",
                    "delta": 0,
                    "tolerance": tolerance,
                    "team_summaries": [],
                    "counted_assets": [],
                    "ignored_assets": [],
                    "reason": "每项资产都必须指定接收方。",
                }
            if asset.recipient_team_id == participant.team_id:
                return {
                    "status": "rejected",
                    "delta": 0,
                    "tolerance": tolerance,
                    "team_summaries": [],
                    "counted_assets": [],
                    "ignored_assets": [],
                    "reason": "球队不能把资产发送给自己。",
                }
            if asset.recipient_team_id not in team_ids:
                return {
                    "status": "rejected",
                    "delta": 0,
                    "tolerance": tolerance,
                    "team_summaries": [],
                    "counted_assets": [],
                    "ignored_assets": [],
                    "reason": "资产接收方必须也是当前交易中的参与球队。",
                }

    counted_assets: list[dict] = []
    ignored_assets: list[dict] = []
    outgoing_counts = {team_id: 0 for team_id in team_ids}
    incoming_counts = {team_id: 0 for team_id in team_ids}
    send_values = {team_id: 0 for team_id in team_ids}
    receive_values = {team_id: 0 for team_id in team_ids}

    for participant in participants:
        asset_count = len(participant.assets)
        outgoing_counts[participant.team_id] += asset_count
        for asset in participant.assets:
            incoming_counts[asset.recipient_team_id] += 1
            if asset.asset_type == "pick":
                pick_no = _resolve_asset_pick_no(asset)
                if pick_no is None:
                    return {
                        "status": "rejected",
                        "delta": 0,
                        "tolerance": tolerance,
                        "team_summaries": [],
                        "counted_assets": counted_assets,
                        "ignored_assets": ignored_assets,
                        "reason": "选秀权资产缺少有效顺位。",
                    }
                pick_value = draft_data.get_pick_value(data, pick_no)
                counted_assets.append(
                    {
                        "team_id": participant.team_id,
                        "recipient_team_id": asset.recipient_team_id,
                        "id": asset.id,
                        "label": _build_trade_label("pick", pick_no=pick_no, name=asset.name),
                        "asset_type": "pick",
                        "value": pick_value,
                    }
                )
                send_values[participant.team_id] += pick_value
                receive_values[asset.recipient_team_id] += pick_value
                continue

            ignored_assets.append(
                {
                    "team_id": participant.team_id,
                    "recipient_team_id": asset.recipient_team_id,
                    "id": asset.id,
                    "label": _build_trade_label(asset.asset_type, pick_no=asset.origin_pick, name=asset.name),
                    "asset_type": asset.asset_type,
                    "value": None,
                }
            )

    if any(outgoing_counts[team_id] == 0 or incoming_counts[team_id] == 0 for team_id in team_ids):
        return {
            "status": "rejected",
            "delta": 0,
            "tolerance": tolerance,
            "team_summaries": [],
            "counted_assets": counted_assets,
            "ignored_assets": ignored_assets,
            "reason": "每支参与交易的球队都至少需要一项送出资产和一项接收资产。",
        }

    team_summaries = []
    for team_id in team_ids:
        team_summaries.append(
            {
                "team_id": team_id,
                "send_value": send_values[team_id],
                "receive_value": receive_values[team_id],
                "delta": abs(send_values[team_id] - receive_values[team_id]),
                "outgoing_asset_count": outgoing_counts[team_id],
                "incoming_asset_count": incoming_counts[team_id],
            }
        )

    delta = max((summary["delta"] for summary in team_summaries), default=0)

    if ignored_assets:
        reason = (
            f"检测到 {len(ignored_assets)} 项球员类资产。系统仅展示各队 pick-only 差值，"
            f"当前最大差值为 {delta}，需要人工确认后才可应用。"
        )
        status: Literal["manual_review_required"] = "manual_review_required"
    else:
        accepted = all(summary["delta"] <= tolerance for summary in team_summaries)
        status = "accepted" if accepted else "rejected"
        reason = (
            f"纯选秀权交易中，所有球队的差值都在 {tolerance} 以内。"
            if accepted
            else f"纯选秀权交易中存在球队差值超过 {tolerance}，当前最大差值为 {delta}。"
        )

    return {
        "status": status,
        "delta": delta,
        "tolerance": tolerance,
        "team_summaries": team_summaries,
        "counted_assets": counted_assets,
        "ignored_assets": ignored_assets,
        "reason": reason,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/draft/meta", response_model=DraftMetaResponse)
def draft_meta():
    data = _get_draft_data()
    return DraftMetaResponse(
        rounds=[14, 30, 60],
        order_sources=[DraftOrderSource(**s) for s in data.get("order_sources", [])],
        boards=[DraftBoard(**b) for b in data.get("boards", [])],
        teams=[DraftTeam(**t) for t in data.get("teams", [])],
        draft_order=[DraftPick(**p) for p in data.get("draft_order", [])],
        updated_at=data.get("updated_at", ""),
        pick_value_source=data.get("pick_value_source", "nbasense (参考)"),
        pick_value_tolerance=int(data.get("pick_value_tolerance", 100)),
    )


@app.get("/api/draft/players", response_model=DraftPlayersResponse)
def draft_players(board: str = Query("workbook_consensus", min_length=1)):
    data = _get_draft_data()
    players = draft_data.get_board_players(data, board)
    return DraftPlayersResponse(board=board, players=[DraftPlayer(**p) for p in players])


@app.post("/api/draft/pick", response_model=DraftPickResponse)
def draft_pick(payload: DraftPickRequest):
    data = _get_draft_data()
    teams = data.get("teams", [])
    players = draft_data.get_board_players(data, payload.board_id)
    available_ids = set(payload.available_player_ids)
    team = _find_team(teams, payload.team_id)
    needs = team.get("needs", []) if team else []
    selected = _choose_auto_player(players, available_ids, needs, payload.use_needs)
    if not selected:
        raise HTTPException(status_code=400, detail="No available players to select.")
    reason = "needs_match" if payload.use_needs and _position_matches_need(selected.get("position", ""), needs) else "best_available"
    return DraftPickResponse(
        pick=payload.pick,
        team_id=payload.team_id,
        player=DraftPlayer(**selected),
        reason=reason,
    )


@app.post("/api/draft/trade/evaluate", response_model=TradeEvaluateResponse)
def trade_evaluate(payload: TradeEvaluateRequest):
    data = _get_draft_data()
    return TradeEvaluateResponse(**_evaluate_trade_request(data, payload))


@app.get("/cba/search", response_model=CBASearchResponse)
def cba_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(5, ge=1, le=20),
):
    tokens = _tokenize(q)
    hits: List[CBAHit] = []

    rows = _load_paragraphs_from_db(limit * 5, tokens)
    if rows:
        for row in rows:
            score = _score(row.get("text", ""), tokens)
            if score <= 0:
                continue
            hits.append(
                CBAHit(
                    page=row.get("page"),
                    para=row.get("para"),
                    text=row.get("text"),
                    score=score,
                )
            )
    else:
        for row in _load_paragraphs():
            score = _score(row.get("text", ""), tokens)
            if score <= 0:
                continue
            hits.append(
                CBAHit(
                    page=row.get("page"),
                    para=row.get("para"),
                    text=row.get("text"),
                    score=score,
                )
            )

    hits.sort(key=lambda h: (h.score, h.page, h.para), reverse=True)
    hits = hits[:limit]

    return CBASearchResponse(query=q, total=len(hits), hits=hits)


@app.post("/facts/check", response_model=FactCheckResponse)
def fact_check(payload: FactCheckRequest):
    # Lightweight heuristic checker: verify numeric tokens appear in sources.
    draft = payload.draft or ""
    source_text = " ".join(" ".join(s.facts) for s in payload.sources).lower()
    issues: List[FactIssue] = []

    tokens = re.findall(r"\b\d{1,4}\b", draft)
    for t in tokens:
        if t not in source_text:
            issues.append(
                FactIssue(
                    type="missing_support",
                    message=f"数字 {t} 未在提供的来源中出现。",
                    span=t,
                )
            )

    if not issues:
        issues.append(
            FactIssue(
                type="ok",
                message="未发现明显事实冲突（基于当前来源）。",
                span="",
            )
        )

    return FactCheckResponse(issues=issues)


@app.post("/draft/rewrite", response_model=RewriteResponse)
def rewrite_draft(payload: RewriteRequest):
    selected_text = payload.selected_text.strip()
    instruction = payload.instruction.strip() or "重写为更清晰、更有逻辑的表达。"
    facts_block = "\n".join(f"- {f}" for f in payload.facts[:8])

    if not selected_text:
        return RewriteResponse(rewritten_text="")

    messages = [
        {
            "role": "system",
            "content": (
                "你是NBA写作编辑。请基于用户给定事实重写段落，保持原意，不要编造新事实。"
                "输出JSON: {\"rewritten_text\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"原文段落:\n{selected_text}\n\n"
                f"改写要求:\n{instruction}\n\n"
                f"可用事实:\n{facts_block if facts_block else '无'}"
            ),
        },
    ]
    llm = _call_openai_chat(messages)
    if llm and str(llm.get("rewritten_text", "")).strip():
        text = str(llm.get("rewritten_text", "")).replace("\\n", "\n").strip()
        return RewriteResponse(rewritten_text=text)

    # Fallback: keep deterministic behavior when no model key.
    fallback = f"{selected_text}\n\n（改写建议：{instruction}）"
    return RewriteResponse(rewritten_text=fallback)


@app.post("/generate", response_model=GenerateResponse)
def generate(payload: GenerateRequest):
    prompt = payload.prompt.strip()
    effective_prompt, direction_choice = _resolve_prompt(prompt, payload.history)
    facts, sources, team_mode = _collect_retrieved_facts(effective_prompt, payload.history)
    directions = _build_directions(effective_prompt, facts, team_mode=team_mode)
    selected_direction = None
    if direction_choice is not None and 1 <= direction_choice <= len(directions):
        selected_direction = directions[direction_choice - 1]

    assistant_reply = _build_assistant_reply(effective_prompt, directions, facts)
    if selected_direction and facts:
        assistant_reply = (
            f"收到，你选择了方向{direction_choice}。\n"
            f"我会围绕「{selected_direction}」基于已检索事实展开首稿。"
        )
    title = f"{effective_prompt}：资料检索草稿" if effective_prompt else "比赛分析草稿"

    # Preferred path: grounded LLM generation from retrieved facts.
    llm_result = _run_grounded_llm(
        prompt=prompt,
        effective_prompt=effective_prompt,
        history=payload.history,
        facts=facts,
        directions=directions,
        selected_direction=selected_direction,
    )
    if llm_result:
        llm_title = str(llm_result.get("title", "")).strip() or title
        llm_reply = str(llm_result.get("assistant_reply", "")).strip() or assistant_reply
        llm_draft = str(llm_result.get("draft", "")).strip()
        llm_directions_raw = llm_result.get("directions", directions)
        llm_directions = [str(x).strip() for x in llm_directions_raw if str(x).strip()] if isinstance(llm_directions_raw, list) else directions
        if not llm_draft:
            llm_draft = (
                f"【生成草稿】\n主题：{effective_prompt}\n\n"
                "证据不足，建议补充更具体的时间范围与样本对象后重试。"
            )
        # Normalize escaped newlines from model output.
        llm_draft = llm_draft.replace("\\n", "\n")
        llm_reply = llm_reply.replace("\\n", "\n")
        return GenerateResponse(
            title=llm_title,
            draft=llm_draft,
            assistant_reply=llm_reply,
            directions=llm_directions[:3] if llm_directions else directions,
            sources=sources,
            fact_snippets=facts[:10],
        )

    # Fallback path without LLM key/network.
    draft = _render_fallback_full_draft(
        topic=effective_prompt,
        facts=facts,
        selected_direction=selected_direction,
    )
    return GenerateResponse(
        title=title,
        draft=draft,
        assistant_reply=assistant_reply,
        directions=directions,
        sources=sources,
        fact_snippets=facts[:10],
    )
