'use client';

import { startTransition, useDeferredValue, useEffect, useMemo, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

type DraftAssetType = 'roster_player' | 'drafted_rights';
type ControlMode = 'selected_teams_manual' | 'all_teams_manual' | 'full_auto';
type TradeStatus = 'accepted' | 'rejected' | 'manual_review_required';
type TradeAssetType = 'pick' | DraftAssetType;
type OrderSetupMode = 'default' | 'manual';

type DraftAssetPlayer = {
  id: string;
  source_id?: string | null;
  asset_type: DraftAssetType;
  name: string;
  short_name?: string | null;
  position: string;
  position_label?: string | null;
  age?: number | null;
  height?: string | null;
  weight_lbs?: number | null;
  jersey?: string | null;
  origin_pick?: number | null;
};

type Team = {
  id: string;
  abbr: string;
  name: string;
  needs: string[];
  primary_color?: string | null;
  secondary_color?: string | null;
  logo_url?: string | null;
  roster_players: DraftAssetPlayer[];
};

type Board = {
  id: string;
  label: string;
  source_url?: string | null;
};

type OrderSource = {
  id: string;
  label: string;
  source_url?: string | null;
};

type DraftPick = {
  pick: number;
  round: number;
  original_team: string;
  current_team: string;
  via?: string | null;
};

type DraftMeta = {
  rounds: number[];
  order_sources: OrderSource[];
  boards: Board[];
  teams: Team[];
  draft_order: DraftPick[];
  updated_at: string;
  pick_value_source: string;
  pick_value_tolerance: number;
};

type StatBag = Record<string, number | null>;

type DraftPlayer = {
  id: string;
  name: string;
  name_zh: string;
  name_en: string;
  projected_pick?: number | null;
  class_year: string;
  position: string;
  position_label: string;
  school: string;
  conference: string;
  height_cm?: number | null;
  weight_kg?: number | null;
  summary_stats: StatBag;
  shooting_splits: StatBag;
  advanced_stats: StatBag;
  rank?: number | null;
  board?: string | null;
};

type TradeAssetRouteRequest = {
  id: string;
  asset_type: TradeAssetType;
  recipient_team_id: string;
  pick_no?: number | null;
  name?: string | null;
  origin_pick?: number | null;
};

type TradeAssetDescriptor = {
  team_id: string;
  recipient_team_id: string;
  id: string;
  label: string;
  asset_type: string;
  value?: number | null;
};

type TradeTeamSummary = {
  team_id: string;
  send_value: number;
  receive_value: number;
  delta: number;
  outgoing_asset_count: number;
  incoming_asset_count: number;
};

type TradeEval = {
  status: TradeStatus;
  delta: number;
  tolerance: number;
  team_summaries: TradeTeamSummary[];
  counted_assets: TradeAssetDescriptor[];
  ignored_assets: TradeAssetDescriptor[];
  reason: string;
};

type TradeParticipantSlot = {
  slotId: string;
  teamId: string;
  assetRecipients: Record<string, string>;
};

type ResolvedTradeAsset = {
  id: string;
  assetType: TradeAssetType;
  recipientTeamId: string;
  pickNo?: number;
  label: string;
  originPick?: number | null;
  playerAsset?: DraftAssetPlayer;
};

type ResolvedTradeParticipant = {
  slotId: string;
  teamId: string;
  assets: ResolvedTradeAsset[];
};

type TradeFlowSummary = {
  teamId: string;
  outgoing: string[];
  incoming: string[];
};

type DraftSelection = {
  pick: number;
  round: number;
  team_id: string;
  player_id: string;
  player_name: string;
  player_name_en: string;
  position: string;
  school: string;
  asset: DraftAssetPlayer;
};

type TeamAssetBuckets = Record<
  string,
  {
    rosterPlayers: DraftAssetPlayer[];
    draftedRights: DraftAssetPlayer[];
  }
>;

type DraftSession = {
  order: DraftPick[];
  selections: Record<number, DraftSelection>;
  index: number;
  teamAssets: TeamAssetBuckets;
};

const CONTROL_MODE_LABELS: Record<ControlMode, string> = {
  selected_teams_manual: '选中球队手动',
  all_teams_manual: '全部手动',
  full_auto: '全自动',
};

const POSITION_FILTERS = ['ALL', 'G', 'F', 'C', 'G/F', 'F/C'];
const MAX_TRADE_TEAMS = 5;
const ORDER_SETUP_LABELS: Record<OrderSetupMode, string> = {
  default: '默认内置顺位',
  manual: '自主调整',
};

function createTradeSlot(slotId: string): TradeParticipantSlot {
  return { slotId, teamId: '', assetRecipients: {} };
}

function createTradeSlots(): TradeParticipantSlot[] {
  return [createTradeSlot('slot-1'), createTradeSlot('slot-2')];
}

function buildPickAssetId(pickNo: number) {
  return `pick-${pickNo}`;
}

function resolvePickNo(assetId: string) {
  const match = assetId.match(/(\d+)$/);
  return match ? Number(match[1]) : null;
}

function normalizeTradeSlots(slots: TradeParticipantSlot[]) {
  const activeTeamIds = slots.map((slot) => slot.teamId).filter(Boolean);
  let changed = false;
  const nextSlots = slots.map((slot) => {
    const filteredRecipients = Object.fromEntries(
      Object.entries(slot.assetRecipients).filter(
        ([, recipientTeamId]) =>
          recipientTeamId && recipientTeamId !== slot.teamId && activeTeamIds.includes(recipientTeamId)
      )
    );
    if (Object.keys(filteredRecipients).length === Object.keys(slot.assetRecipients).length) {
      return slot;
    }
    changed = true;
    return {
      ...slot,
      assetRecipients: filteredRecipients,
    };
  });
  return changed ? nextSlots : slots;
}

function positionMatches(position: string, filter: string) {
  if (filter === 'ALL') return true;
  return position.toUpperCase().includes(filter.toUpperCase());
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

function formatCompact(value?: number | null) {
  if (value === null || value === undefined) return '—';
  return Number.isInteger(value) ? String(value) : Number(value).toFixed(1);
}

function formatHeight(player: DraftPlayer) {
  if (!player.height_cm) return '—';
  return `${player.height_cm} cm`;
}

function formatWeight(player: DraftPlayer) {
  if (!player.weight_kg) return '—';
  return `${player.weight_kg} kg`;
}

function formatPickLabel(pick: DraftPick) {
  return `R${pick.round} · #${pick.pick}`;
}

function formatTradeAssetLabel(asset: ResolvedTradeAsset) {
  if (asset.assetType === 'pick' && asset.pickNo !== undefined) return `#${asset.pickNo}`;
  if (asset.assetType === 'drafted_rights') {
    return asset.originPick ? `${asset.label} (#${asset.originPick})` : asset.label;
  }
  return asset.label;
}

function sortAssets<T extends DraftAssetPlayer>(assets: T[]) {
  return [...assets].sort((left, right) => {
    if ((left.origin_pick ?? 999) !== (right.origin_pick ?? 999)) {
      return (left.origin_pick ?? 999) - (right.origin_pick ?? 999);
    }
    return left.name.localeCompare(right.name, 'zh-Hans-CN');
  });
}

function buildInitialTeamAssets(teams: Team[]): TeamAssetBuckets {
  return Object.fromEntries(
    teams.map((team) => [
      team.id,
      {
        rosterPlayers: sortAssets(team.roster_players ?? []),
        draftedRights: [],
      },
    ])
  );
}

function createInitialSession(meta: DraftMeta, roundCount: number): DraftSession {
  return {
    order: meta.draft_order.slice(0, roundCount),
    selections: {},
    index: 0,
    teamAssets: buildInitialTeamAssets(meta.teams),
  };
}

function createSessionFromOrder(meta: DraftMeta, order: DraftPick[], roundCount: number): DraftSession {
  return {
    order: order.slice(0, roundCount),
    selections: {},
    index: 0,
    teamAssets: buildInitialTeamAssets(meta.teams),
  };
}

function buildBaseOriginalOrder(order: DraftPick[]) {
  return [...order]
    .filter((pick) => pick.round === 1)
    .sort((left, right) => left.pick - right.pick)
    .map((pick) => pick.original_team);
}

function buildDraftOrderFromOriginalOrder(order: DraftPick[], baseOriginalOrder: string[]) {
  const teamRank = new Map(baseOriginalOrder.map((teamId, index) => [teamId, index]));
  const rounds = Array.from(new Set(order.map((pick) => pick.round))).sort((left, right) => left - right);
  let nextPickNumber = 1;
  const rebuilt: DraftPick[] = [];

  rounds.forEach((round) => {
    const roundPicks = order
      .filter((pick) => pick.round === round)
      .map((pick) => ({ ...pick }))
      .sort((left, right) => {
        const leftRank = teamRank.get(left.original_team) ?? 999;
        const rightRank = teamRank.get(right.original_team) ?? 999;
        if (leftRank !== rightRank) return leftRank - rightRank;
        return left.pick - right.pick;
      });
    roundPicks.forEach((pick) => {
      rebuilt.push({
        ...pick,
        pick: nextPickNumber,
      });
      nextPickNumber += 1;
    });
  });

  return rebuilt;
}

function moveListItem(items: string[], fromIndex: number, toIndex: number) {
  const next = [...items];
  const [removed] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, removed);
  return next;
}

function moveTeamByStep(items: string[], teamId: string, delta: number) {
  const index = items.indexOf(teamId);
  if (index < 0) return items;
  const nextIndex = Math.max(0, Math.min(items.length - 1, index + delta));
  if (nextIndex === index) return items;
  return moveListItem(items, index, nextIndex);
}

function buildDraftedRightsAsset(player: DraftPlayer, pick: DraftPick): DraftAssetPlayer {
  return {
    id: `drafted-${pick.pick}-${player.id}`,
    asset_type: 'drafted_rights',
    name: player.name_zh,
    short_name: player.name_en,
    position: player.position,
    position_label: player.position_label,
    origin_pick: pick.pick,
    height: player.height_cm ? `${player.height_cm} cm` : null,
  };
}

function createSelection(player: DraftPlayer, pick: DraftPick): DraftSelection {
  return {
    pick: pick.pick,
    round: pick.round,
    team_id: pick.current_team,
    player_id: player.id,
    player_name: player.name_zh,
    player_name_en: player.name_en,
    position: player.position,
    school: player.school,
    asset: buildDraftedRightsAsset(player, pick),
  };
}

function applySelectionToSession(session: DraftSession, player: DraftPlayer, pick: DraftPick): DraftSession {
  const selection = createSelection(player, pick);
  const nextSelections = { ...session.selections, [pick.pick]: selection };
  const nextTeamAssets = {
    ...session.teamAssets,
    [pick.current_team]: {
      rosterPlayers: session.teamAssets[pick.current_team]?.rosterPlayers ?? [],
      draftedRights: sortAssets([
        ...(session.teamAssets[pick.current_team]?.draftedRights ?? []),
        selection.asset,
      ]),
    },
  };

  return {
    ...session,
    selections: nextSelections,
    teamAssets: nextTeamAssets,
    index: session.index + 1,
  };
}

function moveTradeAssets(session: DraftSession, participants: ResolvedTradeParticipant[]) {
  const nextTeamAssets: TeamAssetBuckets = {
    ...Object.fromEntries(
      Object.entries(session.teamAssets).map(([teamId, teamAssets]) => [
        teamId,
        {
          rosterPlayers: [...teamAssets.rosterPlayers],
          draftedRights: [...teamAssets.draftedRights],
        },
      ])
    ),
  };

  const incomingAssets: TeamAssetBuckets = {};

  const takeAsset = (teamId: string, assetId: string) => {
    const teamAssets = nextTeamAssets[teamId];
    const rosterIndex = teamAssets.rosterPlayers.findIndex((asset) => asset.id === assetId);
    if (rosterIndex >= 0) {
      return {
        assetType: 'rosterPlayers' as const,
        asset: teamAssets.rosterPlayers.splice(rosterIndex, 1)[0],
      };
    }

    const rightsIndex = teamAssets.draftedRights.findIndex((asset) => asset.id === assetId);
    if (rightsIndex >= 0) {
      return {
        assetType: 'draftedRights' as const,
        asset: teamAssets.draftedRights.splice(rightsIndex, 1)[0],
      };
    }

    return null;
  };

  for (const participant of participants) {
    for (const asset of participant.assets) {
      if (asset.assetType === 'pick' || !asset.playerAsset) continue;
      const moved = takeAsset(participant.teamId, asset.playerAsset.id);
      if (!moved) continue;
      if (!incomingAssets[asset.recipientTeamId]) {
        incomingAssets[asset.recipientTeamId] = { rosterPlayers: [], draftedRights: [] };
      }
      incomingAssets[asset.recipientTeamId][moved.assetType].push(moved.asset);
    }
  }

  for (const [teamId, assets] of Object.entries(incomingAssets)) {
    nextTeamAssets[teamId].rosterPlayers = sortAssets([
      ...nextTeamAssets[teamId].rosterPlayers,
      ...assets.rosterPlayers,
    ]);
    nextTeamAssets[teamId].draftedRights = sortAssets([
      ...nextTeamAssets[teamId].draftedRights,
      ...assets.draftedRights,
    ]);
  }

  return nextTeamAssets;
}

export default function Page() {
  const [meta, setMeta] = useState<DraftMeta | null>(null);
  const [draftOrder, setDraftOrder] = useState<DraftPick[]>([]);
  const [boardId, setBoardId] = useState('');
  const [orderSource, setOrderSource] = useState('');
  const [orderSourceLabel, setOrderSourceLabel] = useState('');
  const [roundCount, setRoundCount] = useState(60);
  const [players, setPlayers] = useState<DraftPlayer[]>([]);
  const [session, setSession] = useState<DraftSession | null>(null);
  const [controlMode, setControlMode] = useState<ControlMode>('selected_teams_manual');
  const [controlledTeams, setControlledTeams] = useState<string[]>([]);
  const [useNeeds, setUseNeeds] = useState(true);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [positionFilter, setPositionFilter] = useState('ALL');
  const [statusMessage, setStatusMessage] = useState('');
  const [selectedProspectId, setSelectedProspectId] = useState<string | null>(null);
  const [autoBusy, setAutoBusy] = useState(false);
  const [selectionHistory, setSelectionHistory] = useState<DraftSession[]>([]);

  const [tradeSlots, setTradeSlots] = useState<TradeParticipantSlot[]>(createTradeSlots());
  const [tradeEval, setTradeEval] = useState<TradeEval | null>(null);
  const [tradeLoading, setTradeLoading] = useState(false);
  const [tradeError, setTradeError] = useState('');
  const [tradeOpen, setTradeOpen] = useState(false);
  const [orderSetupOpen, setOrderSetupOpen] = useState(true);
  const [orderSetupMode, setOrderSetupMode] = useState<OrderSetupMode>('default');
  const [setupOriginalOrder, setSetupOriginalOrder] = useState<string[]>([]);
  const [orderSetupError, setOrderSetupError] = useState('');
  const [draggingTeamId, setDraggingTeamId] = useState<string | null>(null);

  const teamsById = useMemo(() => {
    const map = new Map<string, Team>();
    meta?.teams.forEach((team) => map.set(team.id, team));
    return map;
  }, [meta]);

  const defaultOriginalOrder = useMemo(
    () => (meta ? buildBaseOriginalOrder(meta.draft_order) : []),
    [meta]
  );

  useEffect(() => {
    async function loadMeta() {
      try {
        const res = await fetch(`${API_BASE}/api/draft/meta`);
        if (!res.ok) throw new Error('meta');
        const data = (await res.json()) as DraftMeta;
        setMeta(data);
        setDraftOrder(data.draft_order ?? []);
        setBoardId(data.boards[0]?.id ?? 'workbook_consensus');
        setOrderSource(data.order_sources[0]?.id ?? 'tankathon_20260318');
        setOrderSourceLabel(data.order_sources[0]?.label ?? '默认内置顺位');
        setRoundCount(data.rounds.includes(60) ? 60 : data.rounds[0] ?? 60);
        setSetupOriginalOrder(buildBaseOriginalOrder(data.draft_order ?? []));
        setOrderSetupOpen(true);
        setOrderSetupMode('default');
        setOrderSetupError('');
        setStatusMessage('');
      } catch {
        setStatusMessage('无法加载模拟器数据，请先启动 API 服务。');
      }
    }
    loadMeta();
  }, []);

  useEffect(() => {
    if (!meta || draftOrder.length === 0) return;
    startTransition(() => {
      setSession(createSessionFromOrder(meta, draftOrder, roundCount));
      setSelectionHistory([]);
      setControlledTeams([]);
      setTradeSlots(createTradeSlots());
      setTradeEval(null);
      setTradeError('');
      setSelectedProspectId(null);
      setTradeOpen(false);
    });
  }, [meta, draftOrder, roundCount]);

  useEffect(() => {
    if (!boardId) return;
    async function loadPlayers() {
      try {
        const res = await fetch(`${API_BASE}/api/draft/players?board=${encodeURIComponent(boardId)}`);
        if (!res.ok) throw new Error('players');
        const data = (await res.json()) as { players: DraftPlayer[] };
        setPlayers(data.players ?? []);
        setSelectedProspectId(data.players?.[0]?.id ?? null);
      } catch {
        setPlayers([]);
        setStatusMessage('无法加载附件 Big Board。');
      }
    }
    loadPlayers();
  }, [boardId]);

  const currentPick = session?.order[session.index];
  const draftFinished = !session || session.index >= session.order.length;
  const selectedIds = useMemo(() => new Set(Object.values(session?.selections ?? {}).map((item) => item.player_id)), [session]);

  const availablePlayers = useMemo(
    () => players.filter((player) => !selectedIds.has(player.id)),
    [players, selectedIds]
  );

  const filteredPlayers = useMemo(() => {
    const keyword = deferredSearch.trim().toLowerCase();
    return availablePlayers.filter((player) => {
      const haystack = [player.name_zh, player.name_en, player.school, player.position_label, player.position]
        .join(' ')
        .toLowerCase();
      const matchSearch = !keyword || haystack.includes(keyword);
      return matchSearch && positionMatches(player.position, positionFilter);
    });
  }, [availablePlayers, deferredSearch, positionFilter]);

  const selectedProspect = useMemo(
    () => players.find((player) => player.id === selectedProspectId) ?? filteredPlayers[0] ?? availablePlayers[0] ?? null,
    [players, selectedProspectId, filteredPlayers, availablePlayers]
  );

  const manualRequired = useMemo(() => {
    if (!currentPick) return false;
    if (controlMode === 'all_teams_manual') return true;
    if (controlMode === 'full_auto') return false;
    return controlledTeams.includes(currentPick.current_team);
  }, [currentPick, controlMode, controlledTeams]);

  const remainingPicks = useMemo(() => {
    if (!session) return [];
    return session.order.filter((pick) => !session.selections[pick.pick]);
  }, [session]);

  const draftOrderedTeams = useMemo(() => {
    if (!meta) return [];
    const rankMap = new Map<string, number>();
    [...remainingPicks, ...(session?.order ?? [])].forEach((pick) => {
      if (!rankMap.has(pick.current_team)) {
        rankMap.set(pick.current_team, pick.pick);
      }
    });
    return [...meta.teams].sort((left, right) => {
      const leftRank = rankMap.get(left.id) ?? 999;
      const rightRank = rankMap.get(right.id) ?? 999;
      if (leftRank !== rightRank) return leftRank - rightRank;
      return left.name.localeCompare(right.name, 'zh-Hans-CN');
    });
  }, [meta, remainingPicks, session]);

  const setupPreviewOrder = useMemo(() => {
    if (!meta || setupOriginalOrder.length === 0) return [];
    return buildDraftOrderFromOriginalOrder(meta.draft_order, setupOriginalOrder);
  }, [meta, setupOriginalOrder]);

  const setupReady = Boolean(meta) && setupOriginalOrder.length > 0;

  const firstRoundPreview = useMemo(
    () => setupPreviewOrder.filter((pick) => pick.round === 1),
    [setupPreviewOrder]
  );

  const originalFirstRoundHolders = useMemo(() => {
    const map = new Map<string, string>();
    meta?.draft_order
      .filter((pick) => pick.round === 1)
      .forEach((pick) => map.set(pick.original_team, pick.current_team));
    return map;
  }, [meta]);

  const activeTradeSlots = useMemo(() => tradeSlots.filter((slot) => slot.teamId), [tradeSlots]);
  const totalSelectedTradeAssets = useMemo(
    () =>
      tradeSlots.reduce(
        (count, slot) => count + Object.values(slot.assetRecipients).filter(Boolean).length,
        0
      ),
    [tradeSlots]
  );

  const resolvedTradeParticipants = useMemo<ResolvedTradeParticipant[]>(() => {
    if (!session) return [];
    return activeTradeSlots.map((slot) => {
      const rosterPlayers = session.teamAssets[slot.teamId]?.rosterPlayers ?? [];
      const draftedRights = session.teamAssets[slot.teamId]?.draftedRights ?? [];
      const outgoingAssets = Object.entries(slot.assetRecipients).reduce<ResolvedTradeAsset[]>(
        (assets, [assetId, recipientTeamId]) => {
          if (!recipientTeamId) return assets;

          if (assetId.startsWith('pick-')) {
            const pickNo = resolvePickNo(assetId);
            if (pickNo === null) return assets;
            assets.push({
              id: assetId,
              assetType: 'pick',
              recipientTeamId,
              pickNo,
              label: `Pick #${pickNo}`,
            });
            return assets;
          }

          const playerAsset = [...rosterPlayers, ...draftedRights].find((asset) => asset.id === assetId);
          if (!playerAsset) return assets;
          assets.push({
            id: assetId,
            assetType: playerAsset.asset_type,
            recipientTeamId,
            label:
              playerAsset.asset_type === 'drafted_rights'
                ? `${playerAsset.name} 签约权`
                : playerAsset.name,
            originPick: playerAsset.origin_pick ?? null,
            playerAsset,
          });
          return assets;
        },
        []
      );
      return {
        slotId: slot.slotId,
        teamId: slot.teamId,
        assets: outgoingAssets,
      };
    });
  }, [activeTradeSlots, session]);

  const tradeFlowSummaries = useMemo<TradeFlowSummary[]>(() => {
    const activeTeamIds = activeTradeSlots.map((slot) => slot.teamId).filter(Boolean);
    const summaryMap = new Map<string, TradeFlowSummary>(
      activeTeamIds.map((teamId) => [teamId, { teamId, outgoing: [], incoming: [] }])
    );

    resolvedTradeParticipants.forEach((participant) => {
      participant.assets.forEach((asset) => {
        const label = formatTradeAssetLabel(asset);
        summaryMap.get(participant.teamId)?.outgoing.push(label);
        summaryMap.get(asset.recipientTeamId)?.incoming.push(label);
      });
    });

    return activeTeamIds
      .map((teamId) => summaryMap.get(teamId))
      .filter((summary): summary is TradeFlowSummary => Boolean(summary));
  }, [activeTradeSlots, resolvedTradeParticipants]);

  useEffect(() => {
    if (activeTradeSlots.length < 2 || totalSelectedTradeAssets === 0) {
      setTradeEval(null);
      setTradeError('');
      setTradeLoading(false);
      return;
    }

    let active = true;
    async function evaluateTrade() {
      setTradeLoading(true);
      setTradeError('');
      try {
        const res = await fetch(`${API_BASE}/api/draft/trade/evaluate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            participants: resolvedTradeParticipants.map((participant) => ({
              team_id: participant.teamId,
              assets: participant.assets.map<TradeAssetRouteRequest>((asset) => ({
                id: asset.id,
                asset_type: asset.assetType,
                recipient_team_id: asset.recipientTeamId,
                pick_no: asset.pickNo ?? null,
                name: asset.playerAsset?.name ?? asset.label,
                origin_pick: asset.originPick ?? null,
              })),
            })),
          }),
        });
        if (!res.ok) throw new Error('trade');
        const data = (await res.json()) as TradeEval;
        if (active) setTradeEval(data);
      } catch {
        if (active) {
          setTradeError('交易估值失败，请确认 API 正常运行。');
          setTradeEval(null);
        }
      } finally {
        if (active) setTradeLoading(false);
      }
    }
    evaluateTrade();
    return () => {
      active = false;
    };
  }, [
    activeTradeSlots,
    totalSelectedTradeAssets,
    resolvedTradeParticipants,
  ]);

  function resetDraft() {
    if (!meta || draftOrder.length === 0) return;
    startTransition(() => {
      setSession(createSessionFromOrder(meta, draftOrder, roundCount));
      setSelectionHistory([]);
      resetTradeMachine();
      setTradeOpen(false);
      setStatusMessage('模拟进度已重置。');
    });
  }

  function resetTradeMachine() {
    setTradeSlots(createTradeSlots());
    setTradeEval(null);
    setTradeError('');
    setTradeLoading(false);
  }

  function switchOrderSetupMode(mode: OrderSetupMode) {
    setOrderSetupMode(mode);
    setOrderSetupError('');
    if (mode === 'default') {
      setSetupOriginalOrder(defaultOriginalOrder);
    }
  }

  function confirmDraftOrderSetup() {
    if (!meta) {
      setOrderSetupError('顺位数据还在加载，请稍后再试。');
      return;
    }

    const nextOriginalOrder =
      setupOriginalOrder.length > 0 ? setupOriginalOrder : buildBaseOriginalOrder(meta.draft_order);
    if (nextOriginalOrder.length === 0) {
      setOrderSetupError('顺位列表为空，无法进入模拟。');
      return;
    }

    const nextDraftOrder = buildDraftOrderFromOriginalOrder(meta.draft_order, nextOriginalOrder);

    startTransition(() => {
      setSetupOriginalOrder(nextOriginalOrder);
      setDraftOrder(nextDraftOrder);
      setSession(createSessionFromOrder(meta, nextDraftOrder, roundCount));
      setSelectionHistory([]);
      setControlledTeams([]);
      setSelectedProspectId((prev) => prev ?? players[0]?.id ?? null);
      resetTradeMachine();
      setTradeOpen(false);
      setOrderSourceLabel(
        orderSetupMode === 'manual' ? '用户自主调整' : meta.order_sources[0]?.label ?? '默认内置顺位'
      );
      setOrderSetupError('');
      setOrderSetupOpen(false);
      setStatusMessage(
        orderSetupMode === 'manual' ? '已按你调整后的顺位进入模拟。' : '已按默认顺位进入模拟。'
      );
    });
  }

  function resetSetupToDefault() {
    setSetupOriginalOrder(defaultOriginalOrder);
    setOrderSetupMode('default');
    setOrderSetupError('');
  }

  function moveSetupTeam(teamId: string, delta: number) {
    setSetupOriginalOrder((prev) => moveTeamByStep(prev, teamId, delta));
  }

  function handleSetupDrop(targetTeamId: string) {
    if (!draggingTeamId || draggingTeamId === targetTeamId) return;
    setSetupOriginalOrder((prev) => {
      const fromIndex = prev.indexOf(draggingTeamId);
      const toIndex = prev.indexOf(targetTeamId);
      if (fromIndex < 0 || toIndex < 0) return prev;
      return moveListItem(prev, fromIndex, toIndex);
    });
    setDraggingTeamId(null);
  }

  function toggleControlledTeam(teamId: string) {
    setControlledTeams((prev) => (prev.includes(teamId) ? prev.filter((id) => id !== teamId) : [...prev, teamId]));
  }

  function updateTradeSlot(
    slotId: string,
    updater: (slot: TradeParticipantSlot) => TradeParticipantSlot
  ) {
    setTradeSlots((prev) =>
      normalizeTradeSlots(prev.map((slot) => (slot.slotId === slotId ? updater(slot) : slot)))
    );
  }

  function setTradeAssetRecipient(slotId: string, assetId: string, recipientTeamId: string) {
    updateTradeSlot(slotId, (slot) => {
      const nextRecipients = { ...slot.assetRecipients };
      if (recipientTeamId) {
        nextRecipients[assetId] = recipientTeamId;
      } else {
        delete nextRecipients[assetId];
      }
      return {
        ...slot,
        assetRecipients: nextRecipients,
      };
    });
  }

  function addTradeSlot() {
    if (tradeSlots.length >= MAX_TRADE_TEAMS) return;
    const nextIndex =
      tradeSlots.reduce((maxValue, slot) => {
        const current = Number(slot.slotId.replace('slot-', ''));
        return Number.isFinite(current) ? Math.max(maxValue, current) : maxValue;
      }, 0) + 1;
    setTradeSlots((prev) => normalizeTradeSlots([...prev, createTradeSlot(`slot-${nextIndex}`)]));
  }

  function removeTradeSlot(slotId: string) {
    if (tradeSlots.length <= 2) return;
    setTradeSlots((prev) => normalizeTradeSlots(prev.filter((slot) => slot.slotId !== slotId)));
  }

  function applyManualSelection(player: DraftPlayer) {
    if (!session || !currentPick || !manualRequired) return;
    startTransition(() => {
      setSelectionHistory((prev) => [...prev, session]);
      setSession((prev) => (prev ? applySelectionToSession(prev, player, currentPick) : prev));
      setStatusMessage(`${teamsById.get(currentPick.current_team)?.name ?? currentPick.current_team} 选择了 ${player.name_zh}`);
    });
  }

  async function requestAutoPlayer(teamId: string, pickNo: number, availableIds: string[]) {
    const res = await fetch(`${API_BASE}/api/draft/pick`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pick: pickNo,
        team_id: teamId,
        board_id: boardId,
        available_player_ids: availableIds,
        use_needs: useNeeds,
      }),
    });
    if (!res.ok) throw new Error('pick');
    const data = (await res.json()) as { player: DraftPlayer; reason: string };
    return data;
  }

  async function autoPickNext() {
    if (!session || !currentPick || draftFinished) return;
    if (manualRequired) {
      setStatusMessage('当前顺位已设置为手动控制。');
      return;
    }

    setAutoBusy(true);
    try {
      const data = await requestAutoPlayer(
        currentPick.current_team,
        currentPick.pick,
        availablePlayers.map((player) => player.id)
      );
      startTransition(() => {
        setSelectionHistory((prev) => [...prev, session]);
        setSession((prev) => (prev ? applySelectionToSession(prev, data.player, currentPick) : prev));
        setStatusMessage(
          `${teamsById.get(currentPick.current_team)?.name ?? currentPick.current_team} 自动选择了 ${data.player.name_zh}`
        );
      });
    } catch {
      setStatusMessage('自动选人失败，请检查 API。');
    } finally {
      setAutoBusy(false);
    }
  }

  async function autoAdvance() {
    if (!session || draftFinished) return;
    if (controlMode === 'all_teams_manual') {
      setStatusMessage('当前是全部手动模式，不能连续自动推进。');
      return;
    }

    setAutoBusy(true);
    let workingSession = session;
    const historySnapshots: DraftSession[] = [];
    try {
      while (workingSession.index < workingSession.order.length) {
        const pick = workingSession.order[workingSession.index];
        const shouldPause =
          controlMode === 'selected_teams_manual' && controlledTeams.includes(pick.current_team);
        if (shouldPause) break;

        const takenIds = new Set(Object.values(workingSession.selections).map((selection) => selection.player_id));
        const ids = players.filter((player) => !takenIds.has(player.id)).map((player) => player.id);
        if (ids.length === 0) break;

        const data = await requestAutoPlayer(pick.current_team, pick.pick, ids);
        historySnapshots.push(workingSession);
        workingSession = applySelectionToSession(workingSession, data.player, pick);
      }

      startTransition(() => {
        if (historySnapshots.length > 0) {
          setSelectionHistory((prev) => [...prev, ...historySnapshots]);
        }
        setSession(workingSession);
        if (workingSession.index >= workingSession.order.length) {
          setStatusMessage('模拟已自动完成。');
        } else {
          const nextPick = workingSession.order[workingSession.index];
          setStatusMessage(
            `已自动推进至 ${teamsById.get(nextPick.current_team)?.name ?? nextPick.current_team} 的 ${formatPickLabel(
              nextPick
            )}。`
          );
        }
      });
    } catch {
      setStatusMessage('自动推进失败，请稍后重试。');
    } finally {
      setAutoBusy(false);
    }
  }

  function undoLastPick() {
    if (selectionHistory.length === 0) {
      setStatusMessage('没有可回退的顺位。');
      return;
    }

    const previousSession = selectionHistory[selectionHistory.length - 1];
    const restoredPick = previousSession.order[previousSession.index];
    startTransition(() => {
      setSelectionHistory((prev) => prev.slice(0, -1));
      setSession(previousSession);
      resetTradeMachine();
      setStatusMessage(
        restoredPick
          ? `已回退到 ${teamsById.get(restoredPick.current_team)?.name ?? restoredPick.current_team} 的 ${formatPickLabel(
              restoredPick
            )}。`
          : '已回退到上一个可选顺位。'
      );
    });
  }

  function applyTrade() {
    if (!session || !tradeEval || resolvedTradeParticipants.length < 2) return;
    if (tradeEval.status === 'rejected') return;

    const pickRecipients = new Map<number, string>();
    resolvedTradeParticipants.forEach((participant) => {
      participant.assets.forEach((asset) => {
        if (asset.assetType === 'pick' && asset.pickNo !== undefined) {
          pickRecipients.set(asset.pickNo, asset.recipientTeamId);
        }
      });
    });

    const nextOrder = session.order.map((pick) => {
      const recipientTeamId = pickRecipients.get(pick.pick);
      if (recipientTeamId) {
        return { ...pick, current_team: recipientTeamId, via: pick.current_team };
      }
      return pick;
    });

    const nextTeamAssets = moveTradeAssets(session, resolvedTradeParticipants);

    startTransition(() => {
      setSession({
        ...session,
        order: nextOrder,
        teamAssets: nextTeamAssets,
      });
      setTradeOpen(false);
      resetTradeMachine();
      setStatusMessage(
        tradeEval.status === 'manual_review_required'
          ? '交易已按人工确认结果应用，球员资产未自动估值。'
          : '交易已应用到当前模拟。'
      );
    });
  }

  const prospectStatCards = selectedProspect
    ? [
        { label: 'PTS', value: formatCompact(selectedProspect.summary_stats.points) },
        { label: 'TRB', value: formatCompact(selectedProspect.summary_stats.rebounds) },
        { label: 'AST', value: formatCompact(selectedProspect.summary_stats.assists) },
        { label: 'TS%', value: formatPercent(selectedProspect.advanced_stats.ts_pct) },
        { label: '3P%', value: formatPercent(selectedProspect.shooting_splits.three_pct) },
        { label: 'PER', value: formatCompact(selectedProspect.advanced_stats.per) },
      ]
    : [];

  return (
    <div className="draft-page">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-kicker">2026 NBA Draft Desk</div>
          <h1>Mock Draft Command Center</h1>
          <p>Fanspo 的操作骨架，中文化为真实附件数据、动态签约权与资产级交易流向。</p>
        </div>
        <div className="status-strip">
          <div className="status-chip">
            <span>更新</span>
            <strong>{meta?.updated_at ?? '—'}</strong>
          </div>
          <div className="status-chip">
            <span>顺位来源</span>
            <strong>{orderSourceLabel || (meta?.order_sources.find((source) => source.id === orderSource)?.label ?? '—')}</strong>
          </div>
          <div className="status-chip">
            <span>Pick Value</span>
            <strong>{meta?.pick_value_source ?? '—'}</strong>
          </div>
        </div>
        <div className="header-actions">
          <button className="action muted" onClick={() => setTradeOpen(true)}>
            交易
          </button>
          <button className="action muted" onClick={undoLastPick} disabled={selectionHistory.length === 0}>
            回退
          </button>
          <button className="action danger" onClick={resetDraft}>
            重置模拟
          </button>
        </div>
      </header>

      <section className="control-hub">
        <div className="control-hub-head">
          <div>
            <div className="eyebrow">Command Deck</div>
            <h2>模拟控制台</h2>
          </div>
          <div className="panel-meta">
            {session ? `${Object.keys(session.selections).length}/${session.order.length} 已完成` : '等待顺位确认'}
          </div>
        </div>
        <div className="control-hub-grid">
          <div className="hub-panel">
            <div className="rail-label">模拟范围</div>
            <div className="pill-row">
              {(meta?.rounds ?? []).map((round) => (
                <button
                  key={round}
                  className={roundCount === round ? 'pill active' : 'pill'}
                  onClick={() => setRoundCount(round)}
                >
                  {round === 14 ? '乐透 14' : round === 30 ? '首轮 30' : '全 60'}
                </button>
              ))}
            </div>
          </div>

          <div className="hub-panel">
            <div className="rail-label">控制模式</div>
            <div className="pill-row">
              {(Object.keys(CONTROL_MODE_LABELS) as ControlMode[]).map((mode) => (
                <button
                  key={mode}
                  className={controlMode === mode ? 'pill active' : 'pill'}
                  onClick={() => setControlMode(mode)}
                >
                  {CONTROL_MODE_LABELS[mode]}
                </button>
              ))}
            </div>
          </div>

          <div className="hub-panel hub-panel-manual">
            <div className="hub-copy">
              <div className="rail-label">手动球队</div>
              <strong>
                {controlMode === 'selected_teams_manual' ? `已选择 ${controlledTeams.length} 支球队` : '该模块仅在选中球队手动模式下生效'}
              </strong>
              <span>轮到这些球队时，模拟会暂停，等待你手动提交这一签。</span>
            </div>
            <div className="team-pill-tray">
              {draftOrderedTeams.map((team) => (
                <button
                  key={team.id}
                  className={controlledTeams.includes(team.id) ? 'team-pill active' : 'team-pill'}
                  disabled={controlMode !== 'selected_teams_manual'}
                  onClick={() => toggleControlledTeam(team.id)}
                >
                  {team.abbr}
                </button>
              ))}
            </div>
          </div>

          <div className="hub-panel">
            <div className="hub-copy">
              <div className="rail-label">自动选秀</div>
              <strong>{manualRequired ? '当前顺位需要你手动处理' : '可以继续自动推进'}</strong>
              <span>自动选秀会沿用附件 Big Board，并可按球队需求进行位置加权。</span>
            </div>
            <div className="auto-actions">
              <label className="toggle">
                <input type="checkbox" checked={useNeeds} onChange={(event) => setUseNeeds(event.target.checked)} />
                <span>按球队需求加权</span>
              </label>
              <div className="button-row">
                <button className="action muted" onClick={autoPickNext} disabled={autoBusy || manualRequired || draftFinished}>
                  自动下一签
                </button>
                <button className="action" onClick={autoAdvance} disabled={autoBusy || draftFinished}>
                  自动推进
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {statusMessage ? <div className="status-banner">{statusMessage}</div> : null}

      {orderSetupOpen ? (
        <div className="setup-shell">
          <section className="setup-overlay">
            <div className="setup-head">
              <div>
                <div className="eyebrow">Order Setup</div>
                <h2>先确认选秀顺位</h2>
                <p>你可以直接使用默认顺位，或者自己拖动球队卡片重排基础顺位。确认后再进入模拟选秀。</p>
              </div>
              <div className="setup-meta">
                <span>默认来源</span>
                <strong>{meta?.order_sources.find((source) => source.id === orderSource)?.label ?? '—'}</strong>
              </div>
            </div>

            <div className="setup-mode-grid">
              {(Object.keys(ORDER_SETUP_LABELS) as OrderSetupMode[]).map((mode) => (
                <button
                  key={mode}
                  className={orderSetupMode === mode ? 'setup-mode-card active' : 'setup-mode-card'}
                  onClick={() => switchOrderSetupMode(mode)}
                >
                  <span>{ORDER_SETUP_LABELS[mode]}</span>
                  <strong>
                    {mode === 'default' ? '直接使用当前内置顺位' : '拖动 30 支原始顺位球队卡片'}
                  </strong>
                </button>
              ))}
            </div>

            <div className="setup-content">
              <div className="setup-main">
                {orderSetupMode === 'manual' ? (
                  <div className="manual-board">
                    <div className="setup-copy">
                      <strong>自主调整基础顺位</strong>
                      <span>拖动卡片或用上下箭头重排 30 支原始顺位球队。若首轮签已被交易，卡片会额外标注当前持签方。</span>
                    </div>
                    <div className="manual-team-list">
                      {setupOriginalOrder.map((teamId, index) => {
                        const team = teamsById.get(teamId);
                        const holderId = originalFirstRoundHolders.get(teamId) ?? teamId;
                        const holder = teamsById.get(holderId);
                        return (
                          <div
                            key={teamId}
                            className={draggingTeamId === teamId ? 'manual-team-card dragging' : 'manual-team-card'}
                            draggable
                            onDragStart={() => setDraggingTeamId(teamId)}
                            onDragEnd={() => setDraggingTeamId(null)}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={() => handleSetupDrop(teamId)}
                          >
                            <div className="manual-team-rank">#{index + 1}</div>
                            <div className="manual-team-copy">
                              <strong>{team?.name ?? teamId}</strong>
                              <span>
                                原始顺位队伍 {team?.abbr ?? teamId}
                                {holderId !== teamId ? ` · 当前持签 ${holder?.abbr ?? holderId}` : ''}
                              </span>
                            </div>
                            <div className="manual-team-actions">
                              <button className="mini-link" onClick={() => moveSetupTeam(teamId, -1)}>
                                上移
                              </button>
                              <button className="mini-link" onClick={() => moveSetupTeam(teamId, 1)}>
                                下移
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="setup-copy">
                    <strong>默认顺位</strong>
                    <span>直接使用仓库内置的 2026 顺位快照。你确认后会立刻进入模拟界面，也可以切到“自主调整”再继续。</span>
                  </div>
                )}
                {orderSetupError ? <div className="trade-note error">{orderSetupError}</div> : null}
              </div>

              <div className="setup-preview">
                <div className="setup-preview-head">
                  <div>
                    <div className="eyebrow">Preview</div>
                    <h3>首轮预览</h3>
                  </div>
                  <span>{ORDER_SETUP_LABELS[orderSetupMode]}</span>
                </div>
                <div className="setup-preview-list">
                  {firstRoundPreview.slice(0, 14).map((pick) => (
                    <div key={`setup-${pick.pick}-${pick.original_team}`} className="setup-preview-card">
                      <div className="setup-preview-rank">#{pick.pick}</div>
                      <div>
                        <strong>{teamsById.get(pick.original_team)?.name ?? pick.original_team}</strong>
                        <small>
                          当前持签：{teamsById.get(pick.current_team)?.name ?? pick.current_team}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="setup-footer">
              <button className="action muted" onClick={resetSetupToDefault}>
                恢复默认顺位
              </button>
              <button className="action" onClick={confirmDraftOrderSetup} disabled={!setupReady}>
                {setupReady ? '使用当前顺位进入模拟' : '顺位加载中…'}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <main className="workspace">
        <section className="panel panel-board">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Draft Board</div>
              <h2>完整顺位</h2>
            </div>
            <div className="board-head-meta">
              <div className="board-spotlight">
                <span>{draftFinished || !currentPick ? 'Draft Status' : 'On The Clock'}</span>
                <strong>
                  {draftFinished || !currentPick
                    ? '模拟已完成'
                    : `${teamsById.get(currentPick.current_team)?.name ?? currentPick.current_team} · ${formatPickLabel(
                        currentPick
                      )}`}
                </strong>
                <small>
                  {draftFinished || !currentPick
                    ? session
                      ? `${Object.keys(session.selections).length}/${session.order.length} 已完成`
                      : '—'
                    : `Needs: ${(teamsById.get(currentPick.current_team)?.needs ?? []).join(' / ') || '—'}`}
                </small>
              </div>
              <div className={manualRequired ? 'mode-badge manual' : 'mode-badge auto'}>
                {manualRequired ? '手动' : '自动'}
              </div>
            </div>
          </div>
          <div className="board-list">
            {session?.order.map((pick) => {
              const selection = session.selections[pick.pick];
              const active = currentPick?.pick === pick.pick;
              return (
                <div key={pick.pick} className={active ? 'board-pick active' : 'board-pick'}>
                  <div className="board-pick-no">{pick.pick}</div>
                  <div className="board-pick-main">
                    <div className="board-team-line">
                      <span className="team-code">{teamsById.get(pick.current_team)?.abbr ?? pick.current_team}</span>
                      <span className="team-name">{teamsById.get(pick.current_team)?.name ?? pick.current_team}</span>
                      {active ? <span className="clock-chip">当前选择</span> : null}
                    </div>
                    {pick.via ? <div className="board-via">via {pick.via}</div> : null}
                    {selection ? (
                      <div className="board-selection">
                        <strong>{selection.player_name}</strong>
                        <span>
                          {selection.position} · {selection.school}
                        </span>
                      </div>
                    ) : (
                      <div className="board-selection pending">待选择</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel panel-bigboard">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Prospect Board</div>
              <h2>附件 Big Board</h2>
            </div>
            <div className="panel-meta">{availablePlayers.length} 名可选</div>
          </div>
          <div className="board-toolbar">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索中文名 / 英文名 / 学校 / 位置"
            />
            <div className="pill-row compact">
              {POSITION_FILTERS.map((filter) => (
                <button
                  key={filter}
                  className={positionFilter === filter ? 'pill active' : 'pill'}
                  onClick={() => setPositionFilter(filter)}
                >
                  {filter}
                </button>
              ))}
            </div>
          </div>
          <div className="prospect-table">
            <div className="prospect-header">
              <span>Rank</span>
              <span>球员</span>
              <span>位置 / 学校</span>
              <span>核心数据</span>
              <span>操作</span>
            </div>
            {filteredPlayers.map((player) => (
              <div
                key={player.id}
                className={selectedProspect?.id === player.id ? 'prospect-row active' : 'prospect-row'}
                onClick={() => setSelectedProspectId(player.id)}
              >
                <div className="rank-col">
                  {player.projected_pick ?? '—'}
                  <small>#{player.rank}</small>
                </div>
                <div className="name-col">
                  <strong>{player.name_zh}</strong>
                  <span>{player.name_en}</span>
                </div>
                <div className="meta-col">
                  <strong>{player.position}</strong>
                  <span>
                    {player.school} · {player.class_year}
                  </span>
                </div>
                <div className="stat-col">
                  <span>{formatCompact(player.summary_stats.points)} PTS</span>
                  <span>{formatCompact(player.summary_stats.rebounds)} REB</span>
                  <span>{formatPercent(player.shooting_splits.three_pct)} 3P</span>
                </div>
                <div className="action-col">
                  <button
                    className="row-action"
                    disabled={!manualRequired || draftFinished}
                    onClick={(event) => {
                      event.stopPropagation();
                      applyManualSelection(player);
                    }}
                  >
                    选择
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>

      {tradeOpen ? (
        <div className="trade-shell" onClick={() => setTradeOpen(false)}>
          <section className="trade-overlay" onClick={(event) => event.stopPropagation()}>
            <div className="trade-overlay-head">
              <div>
                <div className="eyebrow">Trade Machine</div>
                <h2>交易面板</h2>
                <p>支持 2-5 队交易，每一项资产都可以单独指定接收方；纯选秀权包裹会按顺位价值自动判定。</p>
              </div>
              <div className="button-row">
                <button className="action muted" onClick={addTradeSlot} disabled={tradeSlots.length >= MAX_TRADE_TEAMS}>
                  添加球队
                </button>
                <button className="action muted" onClick={resetTradeMachine}>
                  清空
                </button>
                <button className="action muted" onClick={() => setTradeOpen(false)}>
                  关闭
                </button>
              </div>
            </div>

            <div className="trade-columns multi">
              {tradeSlots.map((slot, index) => {
                const availableTeamIds = new Set(
                  tradeSlots
                    .filter((item) => item.slotId !== slot.slotId)
                    .map((item) => item.teamId)
                    .filter(Boolean)
                );
                const selectedAssetCount = Object.values(slot.assetRecipients).filter(Boolean).length;
                const pickOptions = remainingPicks.filter((pick) => pick.current_team === slot.teamId);
                const rosterAssets = session?.teamAssets[slot.teamId]?.rosterPlayers ?? [];
                const draftedRights = session?.teamAssets[slot.teamId]?.draftedRights ?? [];
                const recipientOptions = draftOrderedTeams
                  .map((team) => team.id)
                  .filter((teamId) => activeTradeSlots.some((item) => item.teamId === teamId) && teamId !== slot.teamId);

                return (
                  <div key={slot.slotId} className="trade-column">
                    <div className="trade-column-head">
                      <div>
                        <div className="trade-column-title">参与方 {index + 1}</div>
                        <div className="trade-route">{selectedAssetCount} 项资产待送出</div>
                      </div>
                      {tradeSlots.length > 2 ? (
                        <button className="mini-link" onClick={() => removeTradeSlot(slot.slotId)}>
                          移除
                        </button>
                      ) : null}
                    </div>
                    <div className="trade-selectors">
                      <label>
                        <span>球队</span>
                        <select
                          value={slot.teamId}
                          onChange={(event) =>
                            updateTradeSlot(slot.slotId, () => ({
                              slotId: slot.slotId,
                              teamId: event.target.value,
                              assetRecipients: {},
                            }))
                          }
                        >
                          <option value="">选择球队</option>
                          {draftOrderedTeams
                            .filter((team) => team.id === slot.teamId || !availableTeamIds.has(team.id))
                            .map((team) => (
                              <option key={team.id} value={team.id}>
                                {team.name}
                              </option>
                            ))}
                        </select>
                      </label>
                    </div>

                    <div className="asset-group">
                      <h3>未使用选秀权</h3>
                      {pickOptions.length === 0 ? (
                        <div className="asset-empty">无可交易签位</div>
                      ) : (
                        pickOptions.map((pick) => {
                          const assetId = buildPickAssetId(pick.pick);
                          return (
                            <div key={`${slot.slotId}-${assetId}`} className="asset-row">
                              <div className="asset-copy">
                                <strong>{formatPickLabel(pick)}</strong>
                                <span>{teamsById.get(pick.current_team)?.abbr ?? pick.current_team}</span>
                              </div>
                              <select
                                value={slot.assetRecipients[assetId] ?? ''}
                                disabled={!slot.teamId || recipientOptions.length === 0}
                                onChange={(event) => setTradeAssetRecipient(slot.slotId, assetId, event.target.value)}
                              >
                                <option value="">保留</option>
                                {recipientOptions.map((teamId) => (
                                  <option key={`${assetId}-${teamId}`} value={teamId}>
                                    {teamsById.get(teamId)?.name ?? teamId}
                                  </option>
                                ))}
                              </select>
                            </div>
                          );
                        })
                      )}
                    </div>

                    <div className="asset-group">
                      <h3>现役 roster</h3>
                      {rosterAssets.length === 0 ? (
                        <div className="asset-empty">暂无现役球员资产</div>
                      ) : (
                        rosterAssets.map((asset) => (
                          <div key={`${slot.slotId}-${asset.id}`} className="asset-row">
                            <div className="asset-copy">
                              <strong>{asset.name}</strong>
                              <span>{asset.position || '球员资产'}</span>
                            </div>
                            <select
                              value={slot.assetRecipients[asset.id] ?? ''}
                              disabled={!slot.teamId || recipientOptions.length === 0}
                              onChange={(event) => setTradeAssetRecipient(slot.slotId, asset.id, event.target.value)}
                            >
                              <option value="">保留</option>
                              {recipientOptions.map((teamId) => (
                                <option key={`${asset.id}-${teamId}`} value={teamId}>
                                  {teamsById.get(teamId)?.name ?? teamId}
                                </option>
                              ))}
                            </select>
                          </div>
                        ))
                      )}
                    </div>

                    <div className="asset-group">
                      <h3>签约权</h3>
                      {draftedRights.length === 0 ? (
                        <div className="asset-empty">暂无已选中新秀签约权</div>
                      ) : (
                        draftedRights.map((asset) => (
                          <div key={`${slot.slotId}-${asset.id}`} className="asset-row">
                            <div className="asset-copy">
                              <strong>{asset.name}</strong>
                              <span>#{asset.origin_pick ?? '—'} 签约权</span>
                            </div>
                            <select
                              value={slot.assetRecipients[asset.id] ?? ''}
                              disabled={!slot.teamId || recipientOptions.length === 0}
                              onChange={(event) => setTradeAssetRecipient(slot.slotId, asset.id, event.target.value)}
                            >
                              <option value="">保留</option>
                              {recipientOptions.map((teamId) => (
                                <option key={`${asset.id}-${teamId}`} value={teamId}>
                                  {teamsById.get(teamId)?.name ?? teamId}
                                </option>
                              ))}
                            </select>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="trade-summary">
              <div className="trade-note">阈值 {meta?.pick_value_tolerance ?? 100}。每支参与球队都必须至少送出一项并收到一项资产。</div>
              {tradeFlowSummaries.length > 0 ? (
                <div className="trade-ledger">
                  {tradeFlowSummaries.map((summary) => (
                    <div key={summary.teamId} className="trade-ledger-card">
                      <span>{teamsById.get(summary.teamId)?.name ?? summary.teamId}</span>
                      <strong>
                        付出：{summary.outgoing.length > 0 ? summary.outgoing.join('，') : '—'}
                      </strong>
                      <small>
                        得到：{summary.incoming.length > 0 ? summary.incoming.join('，') : '—'}
                      </small>
                    </div>
                  ))}
                </div>
              ) : null}
              {tradeLoading ? <div className="trade-note">估值中…</div> : null}
              {tradeError ? <div className="trade-note error">{tradeError}</div> : null}
              {tradeEval ? (
                <>
                  <div className="trade-math">
                    {tradeEval.team_summaries.map((summary) => (
                      <div key={summary.team_id}>
                        <span>{teamsById.get(summary.team_id)?.abbr ?? summary.team_id}</span>
                        <strong>
                          {summary.send_value} → {summary.receive_value}
                        </strong>
                        <small>差值 {summary.delta}</small>
                      </div>
                    ))}
                  </div>
                  <div className={`trade-decision ${tradeEval.status}`}>{tradeEval.reason}</div>
                  {tradeEval.ignored_assets.length > 0 ? (
                    <div className="ignored-assets">
                      {tradeEval.ignored_assets.map((asset) => (
                        <span key={`${asset.team_id}-${asset.id}`}>
                          {teamsById.get(asset.team_id)?.abbr ?? asset.team_id}
                          {' -> '}
                          {teamsById.get(asset.recipient_team_id)?.abbr ?? asset.recipient_team_id}
                          : {asset.label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <button className="action" disabled={tradeEval.status === 'rejected'} onClick={applyTrade}>
                    {tradeEval.status === 'manual_review_required' ? '人工确认后交易' : '交易'}
                  </button>
                </>
              ) : (
                <div className="trade-note">先配置 2-5 支球队，再为具体资产指定接收方，系统才会开始计算交易反馈。</div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {selectedProspect ? (
        <aside className="prospect-drawer">
          <div className="drawer-head">
            <div>
              <div className="eyebrow">Prospect Detail</div>
              <h2>{selectedProspect.name_zh}</h2>
              <div className="drawer-subtitle">{selectedProspect.name_en}</div>
            </div>
            <div className="drawer-rank">预测 #{selectedProspect.projected_pick ?? '—'}</div>
          </div>
          <div className="drawer-tags">
            <span>{selectedProspect.position}</span>
            <span>{selectedProspect.class_year}</span>
            <span>{selectedProspect.school}</span>
            <span>{selectedProspect.conference}</span>
          </div>
          <div className="drawer-measures">
            <div>
              <span>身高</span>
              <strong>{formatHeight(selectedProspect)}</strong>
            </div>
            <div>
              <span>体重</span>
              <strong>{formatWeight(selectedProspect)}</strong>
            </div>
          </div>
          <div className="drawer-stat-grid">
            {prospectStatCards.map((item) => (
              <div key={item.label} className="drawer-stat-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="drawer-sections">
            <section>
              <h3>基础数据</h3>
              <div className="kv-grid">
                <div><span>MP</span><strong>{formatCompact(selectedProspect.summary_stats.minutes)}</strong></div>
                <div><span>PTS</span><strong>{formatCompact(selectedProspect.summary_stats.points)}</strong></div>
                <div><span>TRB</span><strong>{formatCompact(selectedProspect.summary_stats.rebounds)}</strong></div>
                <div><span>AST</span><strong>{formatCompact(selectedProspect.summary_stats.assists)}</strong></div>
                <div><span>STL</span><strong>{formatCompact(selectedProspect.summary_stats.steals)}</strong></div>
                <div><span>BLK</span><strong>{formatCompact(selectedProspect.summary_stats.blocks)}</strong></div>
              </div>
            </section>
            <section>
              <h3>投篮拆分</h3>
              <div className="kv-grid">
                <div><span>FG</span><strong>{formatCompact(selectedProspect.shooting_splits.fg)}</strong></div>
                <div><span>FGA</span><strong>{formatCompact(selectedProspect.shooting_splits.fga)}</strong></div>
                <div><span>FG%</span><strong>{formatPercent(selectedProspect.shooting_splits.fg_pct)}</strong></div>
                <div><span>3P</span><strong>{formatCompact(selectedProspect.shooting_splits.three_p)}</strong></div>
                <div><span>3PA</span><strong>{formatCompact(selectedProspect.shooting_splits.three_pa)}</strong></div>
                <div><span>3P%</span><strong>{formatPercent(selectedProspect.shooting_splits.three_pct)}</strong></div>
                <div><span>2P</span><strong>{formatCompact(selectedProspect.shooting_splits.two_p)}</strong></div>
                <div><span>2PA</span><strong>{formatCompact(selectedProspect.shooting_splits.two_pa)}</strong></div>
                <div><span>2P%</span><strong>{formatPercent(selectedProspect.shooting_splits.two_pct)}</strong></div>
                <div><span>FT%</span><strong>{formatPercent(selectedProspect.shooting_splits.ft_pct)}</strong></div>
                <div><span>eFG%</span><strong>{formatPercent(selectedProspect.shooting_splits.efg_pct)}</strong></div>
                <div><span>FTr</span><strong>{formatCompact(selectedProspect.advanced_stats.ftr)}</strong></div>
              </div>
            </section>
            <section>
              <h3>高阶数据</h3>
              <div className="kv-grid">
                <div><span>PER</span><strong>{formatCompact(selectedProspect.advanced_stats.per)}</strong></div>
                <div><span>TS%</span><strong>{formatPercent(selectedProspect.advanced_stats.ts_pct)}</strong></div>
                <div><span>USG%</span><strong>{formatCompact(selectedProspect.advanced_stats.usg_pct)}</strong></div>
                <div><span>BPM</span><strong>{formatCompact(selectedProspect.advanced_stats.bpm)}</strong></div>
                <div><span>OBPM</span><strong>{formatCompact(selectedProspect.advanced_stats.obpm)}</strong></div>
                <div><span>DBPM</span><strong>{formatCompact(selectedProspect.advanced_stats.dbpm)}</strong></div>
                <div><span>WS</span><strong>{formatCompact(selectedProspect.advanced_stats.ws)}</strong></div>
                <div><span>WS/40</span><strong>{formatCompact(selectedProspect.advanced_stats.ws_per_40)}</strong></div>
                <div><span>AST/TOV</span><strong>{formatCompact(selectedProspect.advanced_stats.ast_to_turnover)}</strong></div>
                <div><span>PProd</span><strong>{formatCompact(selectedProspect.advanced_stats.pprod)}</strong></div>
                <div><span>参与度</span><strong>{formatCompact(selectedProspect.advanced_stats.offensive_involvement)}</strong></div>
                <div><span>3PAr</span><strong>{formatCompact(selectedProspect.advanced_stats.three_par)}</strong></div>
              </div>
            </section>
          </div>
        </aside>
      ) : null}
    </div>
  );
}
