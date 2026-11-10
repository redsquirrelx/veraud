import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button, Spinner } from "../../shared/ui-kit/index.ts"
import { getProjectGraphArtifact } from "./projectGraphApi.ts"
import {
  aggregateModuleEdgesToGroups,
  buildArchitectureIndex,
  buildDirectoryGroups,
  moduleOf,
  traverseImpact,
  type AggregatedEdge,
  type ArchitectureIndex,
  type GroupingPerspective,
  type ImpactGraph,
  type ModuleGroup,
  type SymbolNode,
} from "./graphAdapter.ts"
import { boundsOf, clamp, detectSCC, layoutCircular, layoutForce, layoutImpact, layoutTree } from "./explorerLayout.ts"
import "./StructuralGraph.css"

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; index: ArchitectureIndex }

type Level = "system" | "subgroups" | "modules" | "symbols" | "impact"

interface View { scale: number; x: number; y: number }
interface HoverState { id: string; x: number; y: number }
interface SceneNode {
  id: string
  kind: "group" | "module" | "class" | "function" | "symbol"
  label: string
  x: number
  y: number
  radius: number
  width?: number
  height?: number
  meta?: Record<string, unknown>
}
interface SceneEdge { id: string; source: string; target: string; weight: number; relation?: string | null; directed?: boolean; cyclic?: boolean }

const MIN_SCALE = 0.03
const MAX_SCALE = 6
const DEFAULT_VIEW: View = { scale: 1, x: 0, y: 0 }
const kindKeys = {
  module: "kinds.module", class: "kinds.class", function: "kinds.function", other: "kinds.other", group: "kinds.group",
} as const

function color(styles: CSSStyleDeclaration, token: string, fallback: string): string {
  return styles.getPropertyValue(token).trim() || fallback
}

export function StructuralGraph({ projectId, taskId, commitHash, onOpenFile }: {
  projectId: number
  taskId: number
  commitHash: string
  onOpenFile?: (path: string, range?: { from: number; to: number | null }) => void
}) {
  const { t } = useTranslation("graph")
  const [state, setState] = useState<LoadState>({ status: "loading" })
  const [attempt, setAttempt] = useState(0)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [view, setView] = useState<View | null>(null)
  const [autoFit, setAutoFit] = useState(false)
  const prevNavKey = useRef<string | null>(null)
  const viewCache = useRef(new Map<string, View>())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [cyclesOpen, setCyclesOpen] = useState(false)
  const [hoverCycle, setHoverCycle] = useState<number | null>(null)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [level, setLevel] = useState<Level>("system")
  const [perspective, setPerspective] = useState<GroupingPerspective>("directory")
  const [directoryDepth, setDirectoryDepth] = useState<1 | 2 | 3>(1)
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const [activeSubgroupId, setActiveSubgroupId] = useState<string | null>(null)
  const [activeModuleId, setActiveModuleId] = useState<string | null>(null)
  const [impactCenterId, setImpactCenterId] = useState<string | null>(null)
  const [impactDepth, setImpactDepth] = useState(1)
  const [search, setSearch] = useState("")
  const [searchPick, setSearchPick] = useState<string | null>(null)
  const [relationFilter, setRelationFilter] = useState<string>("")
  const [direction, setDirection] = useState<"both" | "in" | "out">("both")

  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const [legendFaded, setLegendFaded] = useState(false)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; viewX: number; viewY: number; moved: boolean } | null>(null)

  const index = state.status === "ready" ? state.index : null

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    // Reset visible state for a new artifact/load attempt.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ status: "loading" })
    getProjectGraphArtifact(projectId, taskId, controller.signal).then(
      (graph) => {
        if (controller.signal.aborted || !active) return
        try {
          const idx = buildArchitectureIndex(graph)
          setState({ status: "ready", index: idx })
          setLevel("system"); setActiveGroupId(null); setActiveSubgroupId(null); setActiveModuleId(null); setImpactCenterId(null)
          setSelectedId(null); setView(null); setSearch(""); setSearchPick(null)
        } catch {
          setState({ status: "error" })
        }
      },
      () => { if (!controller.signal.aborted && active) setState({ status: "error" }) },
    )
    return () => { active = false; controller.abort() }
  }, [projectId, taskId, attempt])

  useEffect(() => {
    const element = containerRef.current
    if (element === null) return
    function measure() { if (element) setSize({ width: element.clientWidth, height: element.clientHeight }) }
    measure()
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure)
      observer.observe(element)
      return () => observer.disconnect()
    }
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [])

  const groups = useMemo((): ModuleGroup[] => {
    if (!index) return []
    if (perspective === "community" && index.groupsByCommunity.length > 0) return index.groupsByCommunity
    if (perspective === "external" && index.groupsByExternal.length > 0) return index.groupsByExternal
    if (perspective === "coupling" && index.groupsByCoupling.length > 0) return index.groupsByCoupling
    return buildDirectoryGroups(index.modules, directoryDepth)
  }, [directoryDepth, index, perspective])

  const groupEdges = useMemo(() => {
    if (!index) return []
    // Map pre-aggregated module dependency edges to the active groups/perspective/depth.
    return aggregateModuleEdgesToGroups(index.moduleEdges, groups)
  }, [index, groups])

  const subgroups = useMemo((): ModuleGroup[] => {
    if (!index || !activeGroupId || perspective !== "directory") return []
    const nextDepth = Math.min(3, directoryDepth + 1) as 1 | 2 | 3
    if (nextDepth === directoryDepth) return []
    const parent = groups.find((g) => g.id === activeGroupId)
    if (!parent) return []
    const scopedModules = parent.moduleIds
      .map((id) => index.modulesById.get(id))
      .filter(Boolean) as NonNullable<ReturnType<typeof index.modulesById.get>>[]
    if (scopedModules.length === 0) return []
    // Scoped directory subgroups at the next verifiable hierarchy depth.
    const scoped = buildDirectoryGroups(scopedModules, nextDepth)
    return scoped.length > 1 ? scoped : []
  }, [activeGroupId, directoryDepth, groups, index, perspective])

  const subgroupEdges = useMemo(() => {
    if (!index || subgroups.length === 0) return []
    // Layer 2: keep intra-subgroup dependencies as self-loops so internal
    // connections are not silently dropped (they were discarded by source===target).
    return aggregateModuleEdgesToGroups(index.moduleEdges, subgroups, true)
  }, [index, subgroups])

  const impact: ImpactGraph | null = useMemo(() => {
    if (!index || !impactCenterId || level !== "impact") return null
    return traverseImpact(index, impactCenterId, impactDepth)
  }, [impactCenterId, impactDepth, index, level])

  const relationOptions = useMemo(() => {
    if (!index) return []
    const names = new Set<string>()
    const pool = level === "modules" && activeGroupId ? index.moduleEdges.filter((e) => inActiveGroup(groups, activeGroupId, e)) : level === "impact" && impact ? [...impact.relationIds].map((id) => index.relationsById.get(id)).filter(Boolean) : index.relations
    if (Array.isArray(pool)) for (const item of pool as Array<{ relations?: string[]; relation?: string | null }>) {
      if ("relations" in item && item.relations) item.relations.forEach((r) => names.add(r))
      else if ("relation" in item && item.relation) names.add(item.relation)
    }
    return [...names].sort()
  }, [activeGroupId, groups, impact, index, level])

  const scene = useMemo((): { nodes: SceneNode[]; edges: SceneEdge[]; notice: string | null; cycleCount?: number; cycleComponents?: string[][]; cycleEdges?: Array<{ source: string; target: string }> } => {
    if (!index) return { nodes: [], edges: [], notice: null }
    if (level === "system") return buildSystemScene(index, groups, groupEdges, relationFilter, false)
    if (level === "subgroups") return buildSystemScene(index, subgroups, subgroupEdges, relationFilter, false)
    if (level === "modules") return buildModuleScene(index, groups, activeGroupId, activeSubgroupId, subgroups, relationFilter, direction, false)
    if (level === "symbols") return buildSymbolScene(index, activeModuleId)
    return buildImpactScene(index, impact, relationFilter, direction)
  }, [activeGroupId, activeModuleId, activeSubgroupId, direction, groupEdges, groups, impact, index, level, relationFilter, subgroupEdges, subgroups])

  const nodeById = useMemo(() => new Map(scene.nodes.map((n) => [n.id, n])), [scene.nodes])
  const sceneBounds = useMemo(() => boundsOf(scene.nodes.map((n) => ({ x: n.x, y: n.y, radius: n.radius, width: n.width, height: n.height }))), [scene.nodes])
  const navKey = `${projectId}|${taskId}|${level}|${activeGroupId ?? ""}|${activeSubgroupId ?? ""}|${activeModuleId ?? ""}|${impactCenterId ?? ""}|${perspective}|${directoryDepth}`
  const fittedView = useMemo(() => fitViewFor(sceneBounds, size.width, size.height, autoFit ? "full" : "readable"), [autoFit, sceneBounds, size.height, size.width])
  const resolvedView = view ?? fittedView ?? DEFAULT_VIEW
  const saveView = useCallback((next: View) => { viewCache.current.set(navKey, next); setView(next) }, [navKey])

  // Per-level view: restore the zoom/pan of this level if saved, else auto-fit on entering.
  useEffect(() => {
    if (prevNavKey.current !== null && prevNavKey.current !== navKey) {
      const cached = viewCache.current.get(navKey)
      setAutoFit(!cached)
      setView(cached ?? null)
    } else if (prevNavKey.current === null) {
      setView(null)
    }
    prevNavKey.current = navKey
  }, [navKey])

  const fitView = useCallback(() => {
    const next = fitViewFor(sceneBounds, size.width, size.height, "full")
    if (next) saveView(next)
  }, [saveView, sceneBounds, size.height, size.width])

  const searchResults = useMemo(() => {
    if (!index || search.trim().length < 2) return []
    const q = search.trim().toLowerCase()
    const hits: Array<{ id: string; label: string; kind: string; moduleId: string | null }> = []
    for (const mod of index.modules) {
      if (hits.length >= 20) break
      if (mod.label.toLowerCase().includes(q) || (mod.sourceFile ?? "").toLowerCase().includes(q)) hits.push({ id: mod.id, label: mod.label, kind: "module", moduleId: mod.id })
    }
    for (const sym of index.symbolsById.values()) {
      if (hits.length >= 20) break
      if (sym.label.toLowerCase().includes(q)) hits.push({ id: sym.id, label: sym.label, kind: sym.kind, moduleId: sym.moduleId })
    }
    return hits
  }, [index, search])

  function resolveSubgroupFor(groupId: string, moduleId: string): string | null {
    if (!index || perspective !== "directory") return null
    const nextDepth = Math.min(3, directoryDepth + 1) as 1 | 2 | 3
    if (nextDepth === directoryDepth) return null
    const parent = groups.find((g) => g.id === groupId)
    if (!parent) return null
    const scoped = parent.moduleIds.map((id) => index.modulesById.get(id)).filter(Boolean) as NonNullable<ReturnType<typeof index.modulesById.get>>[]
    if (scoped.length === 0) return null
    const subs = buildDirectoryGroups(scoped, nextDepth)
    return subs.length > 1 ? (subs.find((g) => g.moduleIds.includes(moduleId))?.id ?? null) : null
  }

  function resolveContextForModule(moduleId: string): { groupId: string | null; subgroupId: string | null } {
    const group = groups.find((g) => g.moduleIds.includes(moduleId)) ?? (activeGroupId ? groups.find((g) => g.id === activeGroupId) : null)
    const groupId = group?.id ?? activeGroupId
    return { groupId, subgroupId: groupId ? resolveSubgroupFor(groupId, moduleId) : null }
  }

  function navigateToNode(nodeId: string) {
    if (!index) return
    const moduleId = moduleOf(index, nodeId)
    if (!moduleId) return
    const ctx = resolveContextForModule(moduleId)
    if (ctx.groupId) setActiveGroupId(ctx.groupId)
    setActiveSubgroupId(ctx.subgroupId)
    setActiveModuleId(moduleId)
    setLevel(index.symbolsById.has(nodeId) ? "symbols" : "modules")
    setSelectedId(nodeId)
    setSearchPick(nodeId)
    setView(null)
  }

  function openGroup(groupId: string) {
    // Genuine intermediate step when verifiable subgroups exist (directory depth < 3).
    if (perspective === "directory" && directoryDepth < 3) {
      const parent = groups.find((g) => g.id === groupId)
      if (parent) {
        const idx = index
        const scoped = idx
          ? (parent.moduleIds
              .map((id) => idx.modulesById.get(id))
              .filter(Boolean) as NonNullable<ReturnType<typeof idx.modulesById.get>>[])
          : []
        const hasSubgroups = scoped.length > 0 && buildDirectoryGroups(scoped, (directoryDepth + 1) as 1 | 2 | 3).length > 1
        if (hasSubgroups) {
          setActiveGroupId(groupId); setActiveSubgroupId(null); setActiveModuleId(null); setLevel("subgroups"); setSelectedId(null); setImpactCenterId(null); setView(null)
          return
        }
      }
    }
    setActiveGroupId(groupId); setActiveSubgroupId(null); setActiveModuleId(null); setLevel("modules"); setSelectedId(null); setImpactCenterId(null); setView(null)
  }

  function openSubgroup(subgroupId: string) {
    setActiveSubgroupId(subgroupId); setActiveModuleId(null); setLevel("modules"); setSelectedId(null); setImpactCenterId(null); setView(null)
  }

  function goSubgroups() {
    if (activeGroupId) { setLevel("subgroups"); setActiveSubgroupId(null); setActiveModuleId(null); setImpactCenterId(null); setSelectedId(null); setView(null) }
  }
  function openModule(moduleId: string) {
    const ctx = resolveContextForModule(moduleId)
    if (ctx.groupId) setActiveGroupId(ctx.groupId)
    setActiveSubgroupId(ctx.subgroupId)
    setActiveModuleId(moduleId); setLevel("symbols"); setSelectedId(null); setImpactCenterId(null); setView(null)
  }
  function goGroup() {
    if (!activeGroupId) { goSystem(); return }
    if (subgroups.length > 0) {
      if (level === "subgroups") goSystem()
      else goSubgroups()
    } else {
      if (level === "modules") goSystem()
      else goModules()
    }
  }
  function openImpact(nodeId: string) {
    if (index) {
      const moduleId = moduleOf(index, nodeId)
      if (moduleId) {
        const ctx = resolveContextForModule(moduleId)
        if (ctx.groupId) setActiveGroupId(ctx.groupId)
        setActiveSubgroupId(ctx.subgroupId)
        setActiveModuleId(moduleId)
      }
    }
    setImpactCenterId(nodeId); setLevel("impact"); setSelectedId(nodeId); setView(null)
  }
  function goSystem() { setLevel("system"); setActiveGroupId(null); setActiveSubgroupId(null); setActiveModuleId(null); setImpactCenterId(null); setSelectedId(null); setView(null) }
  function goModules() { if (activeGroupId) { setLevel("modules"); setActiveModuleId(null); setImpactCenterId(null); setSelectedId(null); setView(null) } else goSystem() }
  function goSymbols() { if (activeModuleId) { setLevel("symbols"); setImpactCenterId(null); setSelectedId(null); setView(null) } }

  // Drawing
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (canvas === null || size.width === 0 || size.height === 0) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    const pw = Math.max(1, Math.round(size.width * dpr))
    const ph = Math.max(1, Math.round(size.height * dpr))
    if (canvas.width !== pw) canvas.width = pw
    if (canvas.height !== ph) canvas.height = ph
    const styles = getComputedStyle(canvas)
    const colors = {
      module: color(styles, "--color-brand", "#006194"), class: color(styles, "--status-warning-solid", "#b45309"),
      function: color(styles, "--status-success-accent", "#047857"), edge: color(styles, "--color-border-control", "#64748b"),
      border: color(styles, "--color-border", "#cbd5e1"), text: color(styles, "--color-text", "#0f172a"),
      in: color(styles, "--status-success-accent", "#047857"), out: color(styles, "--status-warning-solid", "#b45309"),
    }
    const font = color(styles, "--font-sans", "sans-serif")
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, size.width, size.height)
    ctx.save()
    ctx.translate(resolvedView.x, resolvedView.y)
    ctx.scale(resolvedView.scale, resolvedView.scale)
    ctx.lineCap = "round"

    const selected = selectedId ? nodeById.get(selectedId) : null
    const focus = selected?.id ?? searchPick

    // One visual arrow per directed pair: merge duplicates (same source->target) keeping total weight.
    const dedupedMap = new Map<string, SceneEdge>()
    for (const e of scene.edges) {
      const key = `${e.source}->${e.target}`
      const cur = dedupedMap.get(key)
      if (!cur) dedupedMap.set(key, { ...e })
      else cur.weight += e.weight
    }
    const visualEdges = [...dedupedMap.values()]

    const neighbors = new Set<string>()
    if (focus) for (const e of visualEdges) { if (e.source === focus) neighbors.add(e.target); if (e.target === focus) neighbors.add(e.source) }

    const hoverCycleComp = hoverCycle !== null ? (scene.cycleComponents?.[hoverCycle] ?? null) : null
    const hoverCycleNodes = hoverCycleComp ? new Set(hoverCycleComp) : null
    const hoverCycleEdges = hoverCycleComp && scene.cycleEdges ? new Set(scene.cycleEdges.filter((e) => hoverCycleComp.includes(e.source) && hoverCycleComp.includes(e.target)).map((e) => `${e.source}->${e.target}`)) : null

    // Separate overlapping bidirectional edges with opposite-side curves.
    const pairGroups = new Map<string, SceneEdge[]>()
    for (const e of visualEdges) {
      if (e.source === e.target) continue
      const key = e.source < e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`
      ;(pairGroups.get(key) ?? pairGroups.set(key, []).get(key)!).push(e)
    }
    const edgeCurve = new Map<SceneEdge, number>()
    for (const group of pairGroups.values()) {
      if (group.length < 2) continue
      const sorted = [...group].sort((a, b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target))
      sorted.forEach((e, i) => edgeCurve.set(e, i - (sorted.length - 1) / 2))
    }

    for (const edge of visualEdges) {
      const s = nodeById.get(edge.source); const t = nodeById.get(edge.target)
      if (!s || !t) continue
      const active = focus !== null && (edge.source === focus || edge.target === focus)
      const hoverActive = !active && hover?.id != null && (edge.source === hover.id || edge.target === hover.id)
      const inHoverCycle = hoverCycleEdges?.has(`${edge.source}->${edge.target}`) ?? false
      const emphasized = active || hoverActive || inHoverCycle
      const refId = active ? focus : hoverActive ? hover!.id : null
      // Direction relative to focused node: target === focus is incoming, source === focus is outgoing.
      const isIncoming = refId !== null && edge.target === refId && edge.source !== refId
      const isOutgoing = refId !== null && edge.source === refId && edge.target !== refId
      const dimmed = (focus !== null && !active) || (hoverCycle !== null && !inHoverCycle && !active && !hoverActive)
      ctx.globalAlpha = dimmed ? (edge.cyclic ? 0.25 : 0.06) : emphasized ? 0.85 : edge.cyclic ? 0.8 : Math.min(0.35, 0.08 + Math.log2(edge.weight + 1) * 0.07)
      ctx.strokeStyle = isIncoming ? colors.in : isOutgoing ? colors.out : emphasized ? colors.module : edge.cyclic ? "#dc2626" : colors.edge
      ctx.lineWidth = (emphasized ? 1.8 : edge.cyclic ? 1.5 : 0.8 + Math.log2(edge.weight + 1) * 0.3) / resolvedView.scale
      // Redundant encoding: incoming dashed, outgoing solid (resets each edge).
      ctx.setLineDash(isIncoming ? [6 / resolvedView.scale, 4 / resolvedView.scale] : [])
      // Self-loop (intra-subgroup / intra-group): draw a loop above the card.
      if (edge.source === edge.target) {
        const hw = (s.width ?? s.radius * 2) / 2
        const hh = (s.height ?? s.radius * 2) / 2
        const loopH = Math.min(26, 10 + Math.log2(edge.weight + 1) * 4)
        const topY = s.y - hh
        ctx.beginPath()
        ctx.moveTo(s.x - hw * 0.28, topY)
        ctx.bezierCurveTo(s.x - hw * 0.38, topY - loopH, s.x + hw * 0.38, topY - loopH, s.x + hw * 0.28, topY)
        ctx.stroke()
        continue
      }
      // Draw each connection to the borders of the node shapes so lines do not overlap nodes.
      const dx = t.x - s.x, dy = t.y - s.y
      const len = Math.hypot(dx, dy)
      if (len < 1) continue
      const ux = dx / len, uy = dy / len
      const sPad = nodeBorderDistance(s, ux, uy)
      const tPad = nodeBorderDistance(t, ux, uy)
      const sx = s.x + ux * sPad, sy = s.y + uy * sPad
      const tx = t.x - ux * tPad, ty = t.y - uy * tPad
      const curveIndex = edgeCurve.get(edge) ?? 0
      if (curveIndex !== 0) {
        const midX = (sx + tx) / 2, midY = (sy + ty) / 2
        const perpX = -uy, perpY = ux
        const bend = curveIndex * 22
        const cx = midX + perpX * bend, cy = midY + perpY * bend
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.quadraticCurveTo(cx, cy, tx, ty); ctx.stroke()
        if (resolvedView.scale > 0.15) drawArrow(ctx, cx, cy, tx, ty, 1)
      } else {
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(tx, ty); ctx.stroke()
        if (resolvedView.scale > 0.15) drawArrow(ctx, sx, sy, tx, ty, 1)
      }
      ctx.setLineDash([])
    }

    ctx.globalAlpha = 1
    for (const node of scene.nodes) {
      const inHoverCycle = hoverCycleNodes?.has(node.id) ?? false
      const dimmed = (focus !== null && node.id !== focus && !neighbors.has(node.id)) || (hoverCycle !== null && !inHoverCycle && node.id !== focus && node.id !== hover?.id)
      ctx.globalAlpha = dimmed ? (node.meta?.cyclic === true ? 0.45 : 0.16) : 1
      drawSceneNode(ctx, node, colors, focus === node.id || hover?.id === node.id || inHoverCycle, resolvedView.scale)
    }

    ctx.globalAlpha = 1; ctx.fillStyle = colors.text; ctx.textBaseline = "middle"
    const labelBoxes: Array<{ x: number; y: number; w: number; h: number }> = []
    for (const node of scene.nodes) {
      const important = node.id === focus || node.id === hover?.id
      if (level === "symbols") {
        ctx.font = `${11 / resolvedView.scale}px ${font}`
        const text = truncateLabel(ctx, node.label, 260 / resolvedView.scale)
        ctx.fillText(text, node.x + node.radius + 4 / resolvedView.scale, node.y)
        continue
      }
      // Semantic zoom: detail increases with scale.
      const isCard = (node.kind === "group" || (node.kind === "module" && level === "modules")) && !!node.width && !!node.height
      const showLabel = important || isCard || (node.kind === "module" ? resolvedView.scale > 0.18 : resolvedView.scale > 0.55)
      const showMeta = important || (node.kind === "group" ? resolvedView.scale > 0.45 : resolvedView.scale > 0.9)
      if (!showLabel) continue
      if (isCard && node.width && node.height) {
        const pad = 6
        const innerW = Math.max(10, node.width - pad * 2)
        ctx.save()
        ctx.textAlign = "center"
        ctx.textBaseline = "middle"
        ctx.font = `${(node.kind === "group" ? 12 : 11) / resolvedView.scale}px ${font}`
        const title = truncateLabel(ctx, node.label, innerW)
        const hasMeta = showMeta && typeof node.meta?.info === "string"
        const titleY = hasMeta ? node.y - (node.kind === "group" ? 7 : 6) : node.y
        ctx.globalAlpha = important ? 1 : 0.95
        ctx.fillText(title, node.x, titleY)
        if (hasMeta) {
          ctx.globalAlpha = important ? 0.85 : 0.72
          ctx.font = `${10 / resolvedView.scale}px ${font}`
          ctx.fillText(truncateLabel(ctx, String(node.meta?.info ?? ""), innerW), node.x, node.y + (node.kind === "group" ? 7 : 6))
        }
        ctx.restore()
        continue
      }
      ctx.font = `${11 / resolvedView.scale}px ${font}`
      const maxW = 130 / resolvedView.scale
      const text = truncateLabel(ctx, node.label, maxW)
      const lx = node.x + node.radius + 4 / resolvedView.scale
      const ly = node.y - (showMeta ? 5 / resolvedView.scale : 0)
      const tw = ctx.measureText(text).width
      if (!important && labelBoxes.some((b) => Math.abs(b.y - ly) < 12 / resolvedView.scale && lx < b.x + b.w && lx + tw > b.x)) continue
      labelBoxes.push({ x: lx, y: ly, w: tw, h: 12 / resolvedView.scale })
      ctx.fillText(text, lx, ly)
      if (showMeta && typeof node.meta?.info === "string") {
        ctx.save(); ctx.globalAlpha = important ? 0.9 : 0.7
        ctx.font = `${10 / resolvedView.scale}px ${font}`
        ctx.fillText(truncateLabel(ctx, node.meta.info, maxW), lx, ly + 12 / resolvedView.scale)
        ctx.restore()
      }
    }
    ctx.restore()
  }, [hover, hoverCycle, level, nodeById, resolvedView, scene.cycleComponents, scene.cycleEdges, scene.edges, scene.nodes, searchPick, selectedId, size.height, size.width])

  useEffect(() => { draw() }, [draw])

  // Wheel zoom (saves into the per-level cache; base is the current resolved view).
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      const rect = canvas!.getBoundingClientRect()
      const px = event.clientX - rect.left, py = event.clientY - rect.top
      const base = resolvedView
      const nextScale = clamp(base.scale * Math.exp(-event.deltaY * 0.001), MIN_SCALE, MAX_SCALE)
      const wx = (px - base.x) / base.scale, wy = (py - base.y) / base.scale
      saveView({ scale: nextScale, x: px - wx * nextScale, y: py - wy * nextScale })
    }
    canvas.addEventListener("wheel", onWheel, { passive: false })
    return () => canvas.removeEventListener("wheel", onWheel)
  }, [resolvedView, saveView, state.status])

  const hitTest = useCallback((clientX: number, clientY: number): SceneNode | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const wx = (clientX - rect.left - resolvedView.x) / resolvedView.scale
    const wy = (clientY - rect.top - resolvedView.y) / resolvedView.scale
    const threshold = 6 / resolvedView.scale
    let best: SceneNode | null = null, bestD = Infinity
    for (const node of scene.nodes) {
      if (node.width && node.height) {
        const inside = wx >= node.x - node.width / 2 - threshold && wx <= node.x + node.width / 2 + threshold && wy >= node.y - node.height / 2 - threshold && wy <= node.y + node.height / 2 + threshold
        const d = inside ? Math.hypot(node.x - wx, node.y - wy) : Infinity
        if (inside && d < bestD) { best = node; bestD = d }
        continue
      }
      const d = Math.hypot(node.x - wx, node.y - wy)
      if (d <= node.radius + threshold && d < bestD) { best = node; bestD = d }
    }
    return best
  }, [resolvedView, scene.nodes])

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, viewX: resolvedView.x, viewY: resolvedView.y, moved: false }
  }
  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (drag && drag.pointerId === event.pointerId) {
      const dx = event.clientX - drag.startX, dy = event.clientY - drag.startY
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true
      saveView({ ...resolvedView, x: drag.viewX + dx, y: drag.viewY + dy })
      return
    }
    // Fade the corner legend when the cursor is near it (it never captures events).
    const canvasRect = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - canvasRect.left, py = event.clientY - canvasRect.top
    const legendRect = legendRef.current?.getBoundingClientRect()
    if (legendRect) {
      const lx = legendRect.left - canvasRect.left, ly = legendRect.top - canvasRect.top
      const near = px >= lx - 24 && px <= lx + legendRect.width + 24 && py >= ly - 24 && py <= ly + legendRect.height + 24
      setLegendFaded((prev) => (prev === near ? prev : near))
    }
    const node = hitTest(event.clientX, event.clientY)
    if (!node) { setHover(null); return }
    setHover({ id: node.id, x: px, y: py })
  }
  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current; dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (drag?.moved) return
    const node = hitTest(event.clientX, event.clientY)
    if (!node) { setSelectedId(null); return }
    setSelectedId(node.id)
  }
  function onDoubleClick(event: ReactPointerEvent<HTMLCanvasElement>) {
    const node = hitTest(event.clientX, event.clientY)
    if (!node) return
    if (level === "system" && node.kind === "group") openGroup(node.id)
    else if (level === "subgroups" && node.kind === "group") openSubgroup(node.id)
    else if (level === "modules" && node.kind === "module") openModule(node.id)
  }
  function onPointerLeave() { dragRef.current = null; setHover(null); setLegendFaded(false) }

  const hovered = hover ? nodeById.get(hover.id) : null
  const cycleTexts = useMemo(() => {
    if (!index || !scene.cycleComponents || !scene.cycleEdges) return []
    const labelOf = (id: string) => index.modulesById.get(id)?.label ?? [...groups, ...subgroups].find((g) => g.id === id)?.label ?? id
    return scene.cycleComponents.map((comp, i) => {
      const edges = [...new Map(scene.cycleEdges!.filter((e) => comp.includes(e.source) && comp.includes(e.target)).map((e) => [`${e.source}->${e.target}`, e])).values()]
      // Traversal order following real intra-cycle edges (DFS), for a readable sequence.
      const adj = new Map<string, string[]>()
      for (const id of comp) adj.set(id, [])
      for (const e of edges) adj.get(e.source)!.push(e.target)
      for (const list of adj.values()) list.sort((a, b) => labelOf(a).localeCompare(labelOf(b)))
      const order: string[] = []
      const seen = new Set<string>()
      const dfs = (v: string) => { seen.add(v); order.push(v); for (const n of adj.get(v) ?? []) if (!seen.has(n)) dfs(n) }
      if (comp[0]) dfs(comp[0])
      for (const id of comp) if (!seen.has(id)) { seen.add(id); order.push(id) }
      const orderIdx = new Map(order.map((id, idx) => [id, idx]))
      const sequence = [...edges]
        .sort((a, b) => (orderIdx.get(a.source) ?? 0) - (orderIdx.get(b.source) ?? 0) || (orderIdx.get(a.target) ?? 0) - (orderIdx.get(b.target) ?? 0))
        .map((e) => `${labelOf(e.source)} → ${labelOf(e.target)}`).join(" · ")
      const participants = order.map(labelOf).join(", ")
      return { key: `${i}:${comp[0]}`, firstId: comp[0]!, comp, participants, sequence }
    })
  }, [groups, subgroups, index, scene.cycleComponents, scene.cycleEdges])

  const details = useMemo(() => buildDetails(index, selectedId, [...groups, ...subgroups], impact, t, scene.cycleComponents, scene.cycleEdges), [groups, subgroups, impact, index, scene.cycleComponents, scene.cycleEdges, selectedId, t])

  return (
    <div className="structural-graph architecture-explorer">
      <div className="explorer-topbar">
        {index && (
          <nav className="explorer-breadcrumbs" aria-label={t("explorer.breadcrumbs")}>
            <button type="button" className={`ui-button ui-button-secondary crumb${level === "system" ? " crumb-current" : ""}`} aria-current={level === "system" ? "page" : undefined} onClick={goSystem} title={t("explorer.levels.system")}>{t("explorer.levels.system")}</button>
            {activeGroupId && level !== "system" && groups.some((g) => g.id === activeGroupId) && <><span className="crumb-sep" aria-hidden="true">›</span><button type="button" className={`ui-button ui-button-secondary crumb${level === "subgroups" || (level === "modules" && !activeSubgroupId) ? " crumb-current" : ""}`} aria-current={level === "subgroups" || (level === "modules" && !activeSubgroupId) ? "page" : undefined} onClick={goGroup} title={groups.find((g) => g.id === activeGroupId)!.label}>{groups.find((g) => g.id === activeGroupId)!.label}</button></>}
            {level === "subgroups" && <><span className="crumb-sep" aria-hidden="true">›</span><span className="crumb-current-label" aria-current="page">{t("explorer.levels.subgroups")}</span></>}
            {activeSubgroupId && (level === "modules" || level === "symbols" || level === "impact") && subgroups.some((g) => g.id === activeSubgroupId) && <><span className="crumb-sep" aria-hidden="true">›</span><button type="button" className={`ui-button ui-button-secondary crumb${level === "modules" ? " crumb-current" : ""}`} aria-current={level === "modules" ? "page" : undefined} onClick={goModules} title={subgroups.find((g) => g.id === activeSubgroupId)!.label}>{subgroups.find((g) => g.id === activeSubgroupId)!.label}</button></>}
            {activeModuleId && (level === "symbols" || level === "impact") && <><span className="crumb-sep" aria-hidden="true">›</span><button type="button" className={`ui-button ui-button-secondary crumb${level === "symbols" ? " crumb-current" : ""}`} aria-current={level === "symbols" ? "page" : undefined} onClick={goSymbols} title={index.modulesById.get(activeModuleId)?.label ?? activeModuleId}>{index.modulesById.get(activeModuleId)?.label ?? activeModuleId}</button></>}
            {level === "impact" && impactCenterId && <><span className="crumb-sep" aria-hidden="true">›</span><span className="crumb-current-label" aria-current="page">{t("explorer.levels.impact")}: {nodeLabel(index, impactCenterId)}</span></>}
          </nav>
        )}
        <div className="explorer-topbar-actions">
        <div className="explorer-search-wrap">
          <input className="ui-input explorer-search-input" aria-label={t("explorer.search")} value={search} placeholder={t("explorer.searchPlaceholder")} onChange={(e) => setSearch(e.target.value)} />
          {search.trim().length >= 2 && (
            <div className="explorer-search-results" role="listbox" aria-label={t("explorer.search")}>
              <span className="label">{searchResults.length > 0 ? t("explorer.searchResults", { count: searchResults.length }) : t("explorer.noResults")}</span>
              {searchResults.map((hit) => (
                <button key={hit.id} type="button" className="explorer-search-hit" onClick={() => navigateToNode(hit.id)}>
                  <Badge tone="neutral">{t(`kinds.${hit.kind === "module" ? "module" : hit.kind === "class" ? "class" : "function"}` as never)}</Badge>
                  <span>{hit.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <Button variant="secondary" onClick={fitView} disabled={index === null}>{t("fit")}</Button>
        </div>
      </div>

      <div className="explorer-main">
        <div className="structural-graph-canvas" ref={containerRef}>
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={t("canvasLabel", { commit: commitHash.slice(0, 7) })}
            title={t("zoomHint")}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerLeave}
            onDoubleClick={onDoubleClick}
          />
          {state.status === "loading" && (
            <div className="structural-graph-overlay" role="status">
              <Spinner />
              <span className="label">{t("graphLoading")}</span>
            </div>
          )}
          {state.status === "error" && (
            <div className="structural-graph-overlay" role="status">
              <p className="label">{t("graphLoadError")}</p>
              <Button variant="secondary" onClick={() => { setState({ status: "loading" }); setView(null); setAttempt((v) => v + 1) }}>{t("graphRetry")}</Button>
            </div>
          )}
          {state.status === "ready" && scene.nodes.length === 0 && (
            <div className="structural-graph-overlay" role="status"><p className="label">{t("emptyGraph")}</p></div>
          )}
          <div ref={legendRef} className={`graph-legend-overlay${legendFaded ? " is-faded" : ""}`} aria-hidden="true">
            <ul className="structural-graph-legend">
              <li><span className="dir-sample dir-in" />{t("legend.incoming")}</li>
              <li><span className="dir-sample dir-out" />{t("legend.outgoing")}</li>
              <li><span className="dir-sample dir-neutral" />{t("legend.neutral")}</li>
              <li><span className="dir-loop" />{t("legend.selfLoop")}</li>
              <li><span className="dir-sample dir-cycle" />{t("details.cyclic")}</li>
            </ul>
            <p className="explorer-legend-hint">{t("legend.focusHint")}</p>
          </div>
          {hovered && hover && (
            <div className="structural-graph-tooltip" style={{ left: Math.min(hover.x + 12, Math.max(0, size.width - 300)), top: Math.min(hover.y + 12, Math.max(0, size.height - 120)) }}>
              <strong>{hovered.label}</strong>
              <span>{t(kindKeys[hovered.kind === "symbol" ? "function" : hovered.kind] ?? "kinds.other")}</span>
              {typeof hovered.meta?.path === "string" && <span className="mono">{hovered.meta.path}</span>}
              {typeof hovered.meta?.info === "string" && <span>{hovered.meta.info}</span>}
            </div>
          )}
        </div>

        <aside className="explorer-side">
          <ul className="structural-graph-legend" aria-label={t("legend.label")}>
            <li><i className="structural-graph-swatch structural-graph-swatch-module" aria-hidden="true" />{t("legend.modules")} <b>{index?.counts.modules ?? 0}</b></li>
            <li><i className="structural-graph-swatch structural-graph-swatch-class" aria-hidden="true" />{t("legend.classes")} <b>{index?.counts.classes ?? 0}</b></li>
            <li><i className="structural-graph-swatch structural-graph-swatch-function" aria-hidden="true" />{t("legend.functions")} <b>{index?.counts.functions ?? 0}</b></li>
            {level === "system" && <li><span className="label">{t("legend.groups")}</span> <b>{groups.length}</b></li>}
          </ul>
          {index && (
            <div className="explorer-controls-row">
              {level === "system" && (
                <>
                  <label className="label"><span>{t("filters.grouping")}</span>
                    <select className="ui-input" value={perspective} onChange={(e) => { setPerspective(e.target.value as GroupingPerspective); setActiveGroupId(null); setView(null) }}>
                      <option value="directory">{t("explorer.groupingDirectory")}</option>
                      <option value="community" disabled={index.groupsByCommunity.length === 0}>{t("explorer.groupingCommunity")}</option>
                      {index.groupsByExternal.length > 0 && <option value="external">{t("explorer.groupingExternal")}</option>}
                      {index.groupsByCoupling.length > 0 && <option value="coupling">{t("explorer.groupingCoupling")}</option>}
                    </select>
                  </label>
                  {perspective === "directory" && (
                    <label className="label"><span>{t("filters.hierarchyDepth")}</span>
                      <select className="ui-input" value={directoryDepth} onChange={(e) => { setDirectoryDepth(Number(e.target.value) as 1 | 2 | 3); setActiveGroupId(null); setView(null) }}>
                        {[1, 2, 3].map((d) => <option key={d} value={d}>{t("explorer.depthLevel", { level: d })}</option>)}
                      </select>
                    </label>
                  )}
                </>
              )}
              {(level === "subgroups" || level === "modules" || level === "impact") && (
                <>
                  <label className="label"><span>{t("filters.relationType")}</span>
                    <select className="ui-input" value={relationFilter} onChange={(e) => setRelationFilter(e.target.value)}>
                      <option value="">{t("filters.all")}</option>
                      {relationOptions.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </label>
                  <label className="label"><span>{t("filters.direction")}</span>
                    <select className="ui-input" value={direction} onChange={(e) => setDirection(e.target.value as "both" | "in" | "out")}>
                      <option value="both">{t("filters.both")}</option>
                      <option value="out">{t("filters.outgoing")}</option>
                      <option value="in">{t("filters.incoming")}</option>
                    </select>
                  </label>
                </>
              )}
              {level === "impact" && (
                <label className="label"><span>{t("filters.depth")}</span>
                  <select className="ui-input" value={impactDepth} onChange={(e) => setImpactDepth(Number(e.target.value))}>
                    {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </label>
              )}
            </div>
          )}
          {(scene.notice || (scene.cycleCount !== undefined && scene.cycleCount > 0)) && (
            <div className="explorer-notes">
              {scene.notice && <p className="label structural-graph-hint">{scene.notice}</p>}
              {scene.cycleCount !== undefined && scene.cycleCount > 0 && (
                <div className="explorer-cycles">
                  <button type="button" className="explorer-cycles-head" aria-expanded={cyclesOpen} onClick={() => setCyclesOpen((v) => !v)}>
                    <span>{t("explorer.cycles", { count: scene.cycleCount })}</span><span aria-hidden="true">{cyclesOpen ? "▾" : "▸"}</span>
                  </button>
                  {cyclesOpen && (
                    <ul className="explorer-cycles-list">
                      {cycleTexts.map((c, i) => (
                        <li key={c.key}>
                          <button type="button" className="explorer-cycle-item" onClick={() => { setSelectedId(c.firstId); setSearchPick(c.firstId) }} onMouseEnter={() => setHoverCycle(i)} onMouseLeave={() => setHoverCycle(null)} onFocus={() => setHoverCycle(i)} onBlur={() => setHoverCycle(null)}>
                            <span className="explorer-cycle-participants">{c.participants}</span>
                            <span className="explorer-cycle-sequence">{c.sequence}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
          {details && (
            <div className="structural-graph-details explorer-details">
              <div className="detail-head">
                {details.path && onOpenFile ? (
                  <button type="button" className="detail-title-btn" onClick={() => onOpenFile(details.path!.replace(/:L\d+.*$/, ""), details._from !== null ? { from: details._from, to: details._to } : undefined)} title={details.path}>{details.name} ↗</button>
                ) : (
                  <strong>{details.name}</strong>
                )}
                <Badge tone="neutral">{details.typeLabel}</Badge>
              </div>
              {details.group && <span className="detail-context" title={t(details.contextType === "module" ? "details.module" : "details.group")}>{details.group}</span>}
              <span className="detail-id mono" title={t("details.id")}>{details._id}</span>
              <div className="detail-metrics">
                {details.metrics.map((m) => (
                  <div key={m.label} className="detail-metric">
                    <div className="detail-metric-head">
                      <span className="detail-metric-name">{m.label}</span>
                      <span className="detail-metric-value">{m.value}{m.unit ? <span className="detail-metric-unit"> {m.unit}</span> : null}</span>
                    </div>
                    {m.desc && <span className="detail-metric-desc">{m.desc}</span>}
                  </div>
                ))}
              </div>
              {details.cycleText && (
                <div className="detail-cycle">
                  <span className="detail-cycle-title">{t("details.cycle")}</span>
                  <span className="detail-cycle-body">{details.cycleText}</span>
                </div>
              )}
              {details.impact && <Badge tone={details.impact === "observed" ? "info" : "neutral"}>{details.impact === "observed" ? t("explorer.impactObserved") : t("explorer.impactTransitive")}</Badge>}
              <div className="explorer-details-actions">
                {details._kind === "group" && <Button variant="secondary" onClick={() => (level === "subgroups" ? openSubgroup(details._id) : openGroup(details._id))}>{t("explorer.openGroup")}</Button>}
                {details._kind === "module" && <Button variant="secondary" onClick={() => openModule(details._id)}>{t("explorer.openModule")}</Button>}
                {details._kind === "symbol" && details._moduleId && <Button variant="secondary" onClick={() => openModule(details._moduleId!)}>{t("explorer.openModule")}</Button>}
                {(details._kind === "module" || details._kind === "symbol" || details._kind === "node") && <Button variant="secondary" onClick={() => openImpact(details._id)}>{t("explorer.exploreImpact")}</Button>}
                <Button variant="secondary" onClick={() => void navigator.clipboard?.writeText(details._id)}>{t("details.copyId")}</Button>
                <Button variant="secondary" onClick={() => setSelectedId(null)}>{t("clearSelection")}</Button>
              </div>
            </div>
          )}
          {level === "impact" && impact && (
            <div className="explorer-impact-legend" role="note">
              <span className="label"><strong>{t("explorer.impactTitle")}</strong> — {t("explorer.depth", { count: impactDepth })}</span>
              <span className="label">{t("explorer.impactObserved")}; {t("explorer.impactInferred")}; {t("explorer.impactTransitive")}</span>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function fitViewFor(bounds: { minX: number; minY: number; maxX: number; maxY: number }, width: number, height: number, mode: "readable" | "full" = "full"): View | null {
  if (width === 0 || height === 0) return null
  const padding = mode === "readable" ? 48 : 36
  const bw = Math.max(1, bounds.maxX - bounds.minX)
  const bh = Math.max(1, bounds.maxY - bounds.minY)
  const raw = Math.min((width - padding * 2) / bw, (height - padding * 2) / bh)
  let scale = clamp(Math.min(raw, 1.5), MIN_SCALE, MAX_SCALE)
  if (mode === "readable") {
    // Keep nodes/labels readable on load; "Fit view" still provides full overview.
    scale = clamp(Math.max(scale, 0.32), MIN_SCALE, MAX_SCALE)
  }
  const cx = (bounds.minX + bounds.maxX) / 2
  const cy = (bounds.minY + bounds.maxY) / 2
  return { scale, x: width / 2 - cx * scale, y: height / 2 - cy * scale }
}

function inActiveGroup(groups: ModuleGroup[], groupId: string, edge: AggregatedEdge): boolean {
  const group = groups.find((g) => g.id === groupId)
  if (!group) return false
  return group.moduleIds.includes(edge.source) || group.moduleIds.includes(edge.target)
}

function buildSystemScene(index: ArchitectureIndex, groups: ModuleGroup[], edges: AggregatedEdge[], relationFilter: string, showAllRelations: boolean) {
  if (groups.length === 0 && index.modules.length > 0) {
    const shownModules = index.modules.slice(0, 250)
    const idSet = new Set(shownModules.map((m) => m.id))
    const edgeCap = showAllRelations ? 5000 : 400
    const allEdges = index.moduleEdges.filter((e) => idSet.has(e.source) && idSet.has(e.target))
    const shownEdges = allEdges.slice(0, edgeCap)
    const laid = layoutForce(shownModules, { id: (m) => m.id, weight: (m) => Math.max(1, m.symbolIds.length), edges: shownEdges, minSize: 58, maxSize: 92 })
    return {
      nodes: laid.map(({ item, x, y, width, height }) => ({ id: item.id, kind: "module" as const, label: item.label, x, y, radius: Math.max(width, height) / 2, width, height, meta: { path: item.sourceFile, info: `${item.symbolIds.length} symbols`, evidence: "structural" } })),
      edges: shownEdges.map((e) => ({ id: e.id, source: e.source, target: e.target, weight: e.weight })),
      notice: index.modules.length > 250 || allEdges.length > shownEdges.length ? `Showing ${shownModules.length}/${index.modules.length} modules and ${shownEdges.length}/${allEdges.length} connections (no data discarded). Use search or expand groups.` : null,
    }
  }
  const visibleGroups = groups.slice(0, 350)
  const visibleIds = new Set(visibleGroups.map((g) => g.id))
  const filtered = edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target) && (relationFilter === "" || e.relations.includes(relationFilter)))
  const maxEdges = showAllRelations ? 6000 : 500
  const shownEdges = filtered.slice(0, maxEdges)
  const scc = detectSCC(visibleGroups.map((g) => g.id), shownEdges)
  const laid = layoutForce(visibleGroups, {
    id: (g) => g.id, weight: (g) => Math.max(1, g.moduleCount), edges: shownEdges,
    width: (g) => Math.min(240, Math.max(148, 112 + Math.sqrt(g.moduleCount) * 8)),
    height: (g) => Math.min(110, Math.max(68, 60 + Math.log2(g.moduleCount + 1) * 5)),
  })
  const limited = filtered.length > maxEdges || groups.length > visibleGroups.length
  const notice = limited
    ? `Showing ${visibleGroups.length}/${groups.length} groups and ${shownEdges.length}/${filtered.length} connections (no data discarded). Rendering capped for performance.`
    : null
  return {
    nodes: laid.map(({ item, x, y, radius, width, height }) => ({
      id: item.id, kind: "group" as const, label: item.label, x, y, radius, width, height,
      meta: { info: `${item.moduleCount} modules · ${item.classCount} classes · ${item.functionCount} functions`, groupingKind: item.kind, evidence: item.evidence, cyclic: scc.nodeIds.has(item.id) },
    })),
    edges: shownEdges.map((e) => ({ id: e.id, source: e.source, target: e.target, weight: e.weight, relation: e.relations[0] ?? null, cyclic: scc.edgeKeys.has(`${e.source}->${e.target}`) })),
    notice,
    cycleCount: scc.count,
    cycleComponents: scc.components,
    cycleEdges: [...scc.edgeKeys].map((k) => { const i = k.indexOf("->"); return { source: k.slice(0, i), target: k.slice(i + 2) } }),
  }
}

function buildModuleScene(index: ArchitectureIndex, groups: ModuleGroup[], groupId: string | null, subgroupId: string | null, subgroups: ModuleGroup[], relationFilter: string, direction: "both" | "in" | "out", showAllRelations: boolean) {
  const subgroup = subgroups.find((g) => g.id === subgroupId)
  const group = groupId ? groups.find((g) => g.id === groupId) : null
  const moduleIds = subgroup ? subgroup.moduleIds : group ? group.moduleIds : index.modules.slice(0, 200).map((m) => m.id)
  const modules = moduleIds.map((id) => index.modulesById.get(id)).filter(Boolean) as NonNullable<ReturnType<typeof index.modulesById.get>>[]
  const moduleSet = new Set(modules.map((m) => m.id))
  let edges = index.moduleEdges.filter((e) => (moduleSet.has(e.source) || moduleSet.has(e.target)) && (relationFilter === "" || e.relations.includes(relationFilter)))
  if (direction === "out") edges = edges.filter((e) => moduleSet.has(e.source))
  if (direction === "in") edges = edges.filter((e) => moduleSet.has(e.target))
  const maxEdges = showAllRelations ? 5000 : 450
  const shown = edges.slice(0, maxEdges)
  const extraIds = new Set<string>()
  for (const e of shown) { if (!moduleSet.has(e.source)) extraIds.add(e.source); if (!moduleSet.has(e.target)) extraIds.add(e.target) }
  const external = [...extraIds].slice(0, showAllRelations ? 120 : 40).map((id) => index.modulesById.get(id)).filter(Boolean) as typeof modules
  const all = [...modules, ...external]
  // Circular layout: nodes on a circle ordered by connections.
  const laid = shown.length > 0
    ? layoutCircular(all, { id: (m) => m.id, edges: shown.map((e) => ({ source: e.source, target: e.target, weight: e.weight })), nodeWidth: 180, nodeHeight: 46 })
    : all.map((item, i) => ({ item, x: (i % 12) * 170, y: Math.floor(i / 12) * 56 }))
  const scc = detectSCC(modules.map((m) => m.id), shown.filter((e) => moduleSet.has(e.source) && moduleSet.has(e.target)))
  return {
    nodes: laid.map(({ item, x, y }) => ({
      id: item.id, kind: "module" as const, label: item.label, x, y, radius: 18, width: 180, height: 46,
      meta: { path: item.sourceFile, info: `↑${item.inDegree} ↓${item.outDegree} · ${item.classCount}c/${item.functionCount}f`, external: !moduleSet.has(item.id), coupling: item.inDegree + item.outDegree, cyclic: scc.nodeIds.has(item.id) },
    })),
    edges: shown.map((e) => ({ id: e.id, source: e.source, target: e.target, weight: e.weight, relation: e.relations[0] ?? null, directed: true, cyclic: scc.edgeKeys.has(`${e.source}->${e.target}`) })),
    notice: edges.length > maxEdges ? `Showing ${shown.length}/${edges.length} connections (no data discarded). Rendering capped for performance.` : null,
    cycleCount: scc.count,
    cycleComponents: scc.components,
    cycleEdges: [...scc.edgeKeys].map((k) => { const i = k.indexOf("->"); return { source: k.slice(0, i), target: k.slice(i + 2) } }),
  }
}

function buildSymbolScene(index: ArchitectureIndex, moduleId: string | null) {
  if (!moduleId) return { nodes: [], edges: [], notice: null }
  const mod = index.modulesById.get(moduleId)
  if (!mod) return { nodes: [], edges: [], notice: null }
  const symbols = mod.symbolIds.map((id) => index.symbolsById.get(id)).filter(Boolean) as SymbolNode[]
  const visible = symbols
  // Build simple ownership hierarchy from `method` relations (class -> method/callable target where target is in module).
  const childrenOf = new Map<string, string[]>()
  const hasParent = new Set<string>()
  for (const rel of index.relations) {
    if (rel.relation !== "method" && rel.relation !== "contains") continue
    if (!visible.some((s) => s.id === rel.source) || !visible.some((s) => s.id === rel.target)) continue
    // method: class -> method; contains may be module/callable->symbol. prefer class ownership.
    const src = index.symbolsById.get(rel.source)
    if (!src || src.kind !== "class") continue
    ;(childrenOf.get(rel.source) ?? childrenOf.set(rel.source, []).get(rel.source)!).push(rel.target)
    hasParent.add(rel.target)
  }
  const roots = visible.filter((s) => !hasParent.has(s.id))
  const { positions } = layoutTree(roots, (s) => s.id, (s) => (childrenOf.get(s.id) ?? []).map((id) => index.symbolsById.get(id)).filter(Boolean) as SymbolNode[], (s) => s.label)
  // Include the module as structural root context in the hierarchy.
  positions.set(moduleId, { x: 24, y: 0 })
  const nodes: SceneNode[] = [
    { id: moduleId, kind: "module" as const, label: mod.label, x: 24, y: 0, radius: 7, meta: { path: mod.sourceFile, info: `${mod.classCount} classes · ${mod.functionCount} functions` } },
    ...visible.map((s) => {
      const p = positions.get(s.id) ?? { x: 44, y: 24 }
      return { id: s.id, kind: s.kind, label: s.label, x: p.x + 10, y: p.y + 24, radius: s.kind === "class" ? 6 : 5, meta: { path: s.sourceFile ? `${s.sourceFile}${s.sourceLocation ? ":" + s.sourceLocation : ""}` : null } }
    }),
  ]
  const nodeSet = new Set(nodes.map((n) => n.id))
  const relEdges = index.relations.filter((r) => nodeSet.has(r.source) && nodeSet.has(r.target) && r.relation !== "rationale_for")
    .slice(0, 800)
    .map((r) => ({ id: r.id, source: r.source, target: r.target, weight: 1, relation: r.relation, directed: true }))
  return { nodes, edges: relEdges, notice: symbols.length > visible.length ? null : null }
}

function buildImpactScene(index: ArchitectureIndex, impact: ImpactGraph | null, relationFilter: string, direction: "both" | "in" | "out") {
  if (!impact) return { nodes: [], edges: [], notice: null }
  const ids = [...impact.nodeIds].filter((id) => index.nodesById.has(id) || index.modulesById.has(id))
  const items = ids.map((id) => ({ id }))
  let rels = [...impact.relationIds].map((id) => index.relationsById.get(id)).filter(Boolean) as NonNullable<ReturnType<typeof index.relationsById.get>>[]
  if (relationFilter) rels = rels.filter((r) => r.relation === relationFilter)
  if (direction === "out") rels = rels.filter((r) => impact.hits.has(r.target) && impact.hits.get(r.target)?.direction === "out" || r.source === impact.centerId)
  if (direction === "in") rels = rels.filter((r) => impact.hits.has(r.source) && impact.hits.get(r.source)?.direction === "in" || r.target === impact.centerId)
  const laid = layoutImpact(items, {
    id: (i) => i.id,
    centerId: impact.centerId,
    directionOf: (id) => id === impact.centerId ? "center" : (impact.hits.get(id)?.direction ?? "out"),
    depthOf: (id) => impact.hits.get(id)?.depth ?? 1,
  })
  const nodes: SceneNode[] = laid.map(({ item, x, y }) => {
    const mod = index.modulesById.get(item.id)
    const sym = index.symbolsById.get(item.id)
    const raw = index.nodesById.get(item.id)
    const hit = impact.hits.get(item.id)
    const kind = mod ? "module" : sym?.kind ?? (raw?.kind === "class" || raw?.kind === "function" ? raw.kind : "module")
    return {
      id: item.id, kind: kind as SceneNode["kind"], label: mod?.label ?? sym?.label ?? raw?.label ?? item.id,
      x, y, radius: item.id === impact.centerId ? 24 : hit?.depth === 1 ? 18 : 14,
      meta: { path: mod?.sourceFile ?? sym?.sourceFile ?? raw?.sourceFile, info: hit ? (hit.observed ? "direct" : `depth ${hit.depth}, ${hit.direction}`) : "center" },
    }
  })
  const nodeSet = new Set(nodes.map((n) => n.id))
  return {
    nodes,
    edges: rels.filter((r) => nodeSet.has(r.source) && nodeSet.has(r.target)).map((r) => ({ id: r.id, source: r.source, target: r.target, weight: 1, relation: r.relation, directed: true })),
    notice: null,
  }
}

function truncateLabel(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 8 || ctx.measureText(text).width <= maxWidth) return text
  let out = text
  while (out.length > 1 && ctx.measureText(`${out}…`).width > maxWidth) out = out.slice(0, -1)
  return `${out}…`
}

function nodeBorderDistance(node: SceneNode, ux: number, uy: number): number {
  // Distance from the node center to its border along the edge direction,
  // so edges terminate/originate at the shape boundary instead of its center.
  // Cards (group / module cards)
  if ((node.kind === "group" || node.kind === "module") && node.width && node.height) {
    const hw = node.width / 2
    const hh = node.height / 2
    const au = Math.abs(ux), av = Math.abs(uy)
    if (au < 1e-6) return hh
    if (av < 1e-6) return hw
    return 1 / Math.max(au / hw, av / hh)
  }
  // Module squares
  if (node.kind === "module") {
    const s = node.radius * 1.5 / 2
    const au = Math.abs(ux), av = Math.abs(uy)
    if (au < 1e-6) return s
    if (av < 1e-6) return s
    return 1 / Math.max(au / s, av / s)
  }
  // Circular / diamond nodes
  return node.radius
}

function drawSceneNode(ctx: CanvasRenderingContext2D, node: SceneNode, colors: Record<string, string>, highlighted: boolean, scale: number) {
  const r = node.radius
  ctx.fillStyle = node.kind === "group" ? colors.module : node.kind === "module" ? colors.module : node.kind === "class" ? colors.class : colors.function
  if (node.kind === "group") {
    const w = node.width ?? r * 1.8
    const h = node.height ?? r
    const x = node.x - w / 2, y = node.y - h / 2
    const rr = Math.min(8 / scale, w / 4, h / 4)
    ctx.save(); ctx.globalAlpha *= highlighted ? 0.28 : 0.16
    roundRect(ctx, x, y, w, h, rr); ctx.fill()
    ctx.restore()
    ctx.strokeStyle = colors.module; ctx.lineWidth = (highlighted ? 2 : 1.2) / scale
    roundRect(ctx, x, y, w, h, rr); ctx.stroke()
  } else if (node.kind === "module") {
    if (node.width && node.height) {
      const x = node.x - node.width / 2, y = node.y - node.height / 2
      const rr = Math.min(6 / scale, 8)
      ctx.save(); ctx.globalAlpha *= 0.22; roundRect(ctx, x, y, node.width, node.height, rr); ctx.fill(); ctx.restore()
      ctx.strokeStyle = colors.module; ctx.lineWidth = (highlighted ? 2 : 1.2) / scale
      roundRect(ctx, x, y, node.width, node.height, rr); ctx.stroke()
    } else {
      const s = r * 1.5; ctx.beginPath(); ctx.rect(node.x - s / 2, node.y - s / 2, s, s); ctx.fill()
    }
  } else if (node.kind === "class") {
    ctx.beginPath(); ctx.moveTo(node.x, node.y - r); ctx.lineTo(node.x + r, node.y); ctx.lineTo(node.x, node.y + r); ctx.lineTo(node.x - r, node.y); ctx.closePath(); ctx.fill()
  } else {
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2); ctx.fill()
  }
  if (highlighted) {
    ctx.strokeStyle = colors.module; ctx.lineWidth = 2 / scale
    const hr = node.width ? Math.max(node.width, node.height ?? 0) / 2 + 4 / scale : r + 4 / scale
    ctx.beginPath(); ctx.arc(node.x, node.y, hr, 0, Math.PI * 2); ctx.stroke()
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function drawArrow(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, pad: number) {
  const dx = x2 - x1, dy = y2 - y1
  const len = Math.hypot(dx, dy)
  if (len < pad + 8) return
  const ux = dx / len, uy = dy / len
  const tipX = x2 - ux * pad, tipY = y2 - uy * pad
  const size = 5
  ctx.beginPath()
  ctx.moveTo(tipX, tipY)
  ctx.lineTo(tipX - ux * size - uy * size * 0.45, tipY - uy * size + ux * size * 0.45)
  ctx.lineTo(tipX - ux * size + uy * size * 0.45, tipY - uy * size - ux * size * 0.45)
  ctx.closePath()
  ctx.fillStyle = ctx.strokeStyle
  ctx.globalAlpha = Math.min(1, ctx.globalAlpha + 0.15)
  ctx.fill()
}

function nodeLabel(index: ArchitectureIndex | null, nodeId: string): string {
  if (!index) return nodeId
  return index.modulesById.get(nodeId)?.label ?? index.symbolsById.get(nodeId)?.label ?? index.nodesById.get(nodeId)?.label ?? nodeId
}

type DetailsT = (key: string, opts?: Record<string, unknown>) => string

function parseLine(location: string | null): number | null {
  if (!location) return null
  const m = location.match(/(\d+)/)
  return m ? Number.parseInt(m[1]!, 10) : null
}

function buildDetails(index: ArchitectureIndex | null, selectedId: string | null, groups: ModuleGroup[], impact: ImpactGraph | null, t: DetailsT, cycleComponents?: string[][], cycleEdges?: Array<{ source: string; target: string }>) {
  if (!index || !selectedId) return null
  const hit = impact?.hits.get(selectedId)
  const cycleGroup = cycleComponents?.find((c) => c.includes(selectedId))
  const labelOf = (id: string) => index.modulesById.get(id)?.label ?? groups.find((g) => g.id === id)?.label ?? id
  const cycleText = cycleGroup && cycleEdges
    ? [...new Map(cycleEdges.filter((e) => cycleGroup.includes(e.source) && cycleGroup.includes(e.target)).map((e) => [`${e.source}->${e.target}`, e])).values()]
        .sort((a, b) => labelOf(a.source).localeCompare(labelOf(b.source)) || labelOf(a.target).localeCompare(labelOf(b.target)))
        .map((e) => `${labelOf(e.source)} → ${labelOf(e.target)}`).join(" · ") || null
    : null
  const group = groups.find((g) => g.id === selectedId)
  if (group) {
    const memberSet = new Set(group.moduleIds)
    let gIn = 0, gOut = 0
    for (const e of index.moduleEdges) {
      if (memberSet.has(e.target)) gIn += e.weight
      if (memberSet.has(e.source)) gOut += e.weight
    }
    const relUnit = t("details.mRelations")
    return {
      name: group.label, typeLabel: t("kinds.group"), path: group.label, group: null, contextType: "group" as const,
      relationsText: `${t("details.incoming", { count: gIn })} / ${t("details.outgoing", { count: gOut })}`,
      metrics: [
        { label: t("details.mIncoming"), value: String(gIn), desc: t("details.mIncomingDesc"), unit: relUnit },
        { label: t("details.mOutgoing"), value: String(gOut), desc: t("details.mOutgoingDesc"), unit: relUnit },
        { label: t("details.mCoupling"), value: String(gIn + gOut), desc: t("details.mCouplingDesc"), unit: relUnit },
        { label: t("details.mModules"), value: String(group.moduleCount), desc: t("details.mModulesDesc") },
        { label: t("details.mClasses"), value: String(group.classCount), desc: t("details.mClassesDesc") },
        { label: t("details.mFunctions"), value: String(group.functionCount), desc: t("details.mFunctionsDesc") },
        { label: t("details.mEvidence"), value: group.evidence, desc: t("details.mEvidenceDesc") },
      ],
      cycleText,
      _kind: "group" as const, _id: selectedId, _moduleId: null as string | null, _from: null as number | null, _to: null as number | null,
    }
  }
  const mod = index.modulesById.get(selectedId)
  if (mod) {
    const depIn = index.relations.filter((r) => (r.target === selectedId || index.moduleIdByNodeId.get(r.target) === selectedId) && r.relation !== "contains" && r.relation !== "rationale_for").length
    const depOut = index.relations.filter((r) => (r.source === selectedId || index.moduleIdByNodeId.get(r.source) === selectedId) && r.relation !== "contains" && r.relation !== "rationale_for").length
    const community = mod.raw && typeof (mod.raw as { community?: unknown }).community === "number" ? String((mod.raw as { community?: unknown }).community) : null
    const relUnit = t("details.mRelations")
    return {
      name: mod.label, typeLabel: t("kinds.module"),
      path: mod.sourceFile ? `${mod.sourceFile}${mod.sourceLocation ? ":" + mod.sourceLocation : ""}` : null,
      group: mod.groupKey, contextType: "group" as const,
      relationsText: `${t("details.incoming", { count: depIn })} / ${t("details.outgoing", { count: depOut })}`,
      metrics: [
        { label: t("details.mIncoming"), value: String(depIn), desc: t("details.mIncomingDesc"), unit: relUnit },
        { label: t("details.mOutgoing"), value: String(depOut), desc: t("details.mOutgoingDesc"), unit: relUnit },
        { label: t("details.mCoupling"), value: String(mod.inDegree + mod.outDegree), desc: t("details.mCouplingDesc"), unit: relUnit },
        { label: t("details.mClasses"), value: String(mod.classCount), desc: t("details.mClassesDesc") },
        { label: t("details.mFunctions"), value: String(mod.functionCount), desc: t("details.mFunctionsDesc") },
        ...(community ? [{ label: t("details.mCommunity"), value: community, desc: t("details.mCommunityDesc") }] : []),
      ],
      cycleText,
      _kind: "module" as const, _id: selectedId, _moduleId: selectedId, _from: parseLine(mod.sourceLocation) ?? 1, _to: null as number | null, impact: hit ? (hit.observed ? "observed" : "transitive") : null,
    }
  }
  const sym = index.symbolsById.get(selectedId)
  if (sym) {
    const inR = index.incoming.get(selectedId)?.length ?? 0
    const outR = index.outgoing.get(selectedId)?.length ?? 0
    const sample = (index.outgoing.get(selectedId) ?? index.incoming.get(selectedId) ?? []).find((r) => r.confidence || r.origin)
    const ownerLabel = sym.ownerClassId ? index.symbolsById.get(sym.ownerClassId)?.label ?? sym.ownerClassId : null
    const from = parseLine(sym.sourceLocation)
    // Zone end: next symbol start in the same file (evidence-based, capped); last symbol caps at +500 lines.
    let to: number | null = null
    if (from !== null) {
      const starts = [...index.symbolsById.values()]
        .filter((s) => s.sourceFile === sym.sourceFile)
        .map((s) => parseLine(s.sourceLocation))
        .filter((n): n is number => n !== null && n > from)
        .sort((a, b) => a - b)
      to = starts.length > 0 ? Math.min(starts[0]! - 1, from + 1000) : from + 500
    }
    return {
      name: sym.label, typeLabel: t(sym.kind === "class" ? "kinds.class" : "kinds.function"),
      path: sym.sourceFile ? `${sym.sourceFile}${sym.sourceLocation ? ":" + sym.sourceLocation : ""}` : null,
      group: index.modulesById.get(sym.moduleId)?.label ?? sym.moduleId, contextType: "module" as const,
      relationsText: `${t("details.incoming", { count: inR })} / ${t("details.outgoing", { count: outR })}`,
      metrics: (() => {
        const relUnit = t("details.mRelations")
        return [
          { label: t("details.mIncoming"), value: String(inR), desc: t("details.mIncomingDesc"), unit: relUnit },
          { label: t("details.mOutgoing"), value: String(outR), desc: t("details.mOutgoingDesc"), unit: relUnit },
          ...(ownerLabel ? [{ label: t("details.mOwner"), value: ownerLabel, desc: t("details.mOwnerDesc") }] : []),
          ...(sample?.confidence ? [{ label: t("details.mConfidence"), value: sample.confidence, desc: t("details.mConfidenceDesc") }] : []),
          ...(sample?.origin ? [{ label: t("details.mOrigin"), value: sample.origin, desc: t("details.mOriginDesc") }] : []),
        ]
      })(),
      _kind: "symbol" as const, _id: selectedId, _moduleId: sym.moduleId, _from: from, _to: to, cycleText: null as string | null, impact: hit ? (hit.observed ? "observed" : "transitive") : null,
    }
  }
  const raw = index.nodesById.get(selectedId)
  if (raw) return {
    name: raw.label, typeLabel: t("kinds.other"), path: raw.sourceFile, group: null, contextType: "group" as const,
    relationsText: `${t("details.incoming", { count: index.incoming.get(selectedId)?.length ?? 0 })} / ${t("details.outgoing", { count: index.outgoing.get(selectedId)?.length ?? 0 })}`,
    metrics: [
      { label: t("details.mIncoming"), value: String(index.incoming.get(selectedId)?.length ?? 0), desc: t("details.mIncomingDesc"), unit: t("details.mRelations") },
      { label: t("details.mOutgoing"), value: String(index.outgoing.get(selectedId)?.length ?? 0), desc: t("details.mOutgoingDesc"), unit: t("details.mRelations") },
    ],
    _kind: "node" as const, _id: selectedId, _moduleId: null as string | null, _from: parseLine(raw.sourceLocation), _to: null as number | null, cycleText: null as string | null, impact: hit ? (hit.observed ? "observed" : "transitive") : null,
  }
  return null
}
