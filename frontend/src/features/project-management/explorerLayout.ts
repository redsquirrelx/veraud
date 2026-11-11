/** Deterministic layout helpers for the architecture explorer (no external deps). */

export interface Point { x: number; y: number }
export interface Rect { x: number; y: number; width: number; height: number }
export interface Bounds { minX: number; minY: number; maxX: number; maxY: number }

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function boundsOf(items: Array<{ x: number; y: number; width?: number; height?: number; radius?: number }>): Bounds {
  if (items.length === 0) return { minX: 0, minY: 0, maxX: 1, maxY: 1 }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const item of items) {
    const pad = item.radius ?? 0
    const w = item.width ?? pad * 2
    const h = item.height ?? pad * 2
    const left = item.width !== undefined ? item.x : item.x - pad
    const top = item.height !== undefined ? item.y : item.y - pad
    minX = Math.min(minX, left)
    minY = Math.min(minY, top)
    maxX = Math.max(maxX, left + w)
    maxY = Math.max(maxY, top + h)
  }
  return minX === Infinity ? { minX: 0, minY: 0, maxX: 1, maxY: 1 } : { minX, minY, maxX, maxY }
}

/** Grid layout sized by weight (module count). Returns center positions + radii. */
export function layoutCircles<T>(items: T[], weight: (item: T) => number, minR = 26, maxR = 72): Array<{ item: T; x: number; y: number; radius: number }> {
  if (items.length === 0) return []
  const weights = items.map(weight)
  const minW = Math.min(...weights)
  const maxW = Math.max(...weights)
  const scale = (w: number) => maxW === minW ? (minR + maxR) / 2 : minR + ((Math.sqrt(w) - Math.sqrt(minW)) / (Math.sqrt(maxW) - Math.sqrt(minW) || 1)) * (maxR - minR)
  const nodes = items.map((item, i) => ({ item, radius: scale(weights[i]!), x: 0, y: 0 }))
  // Shelf packing by rows
  nodes.sort((a, b) => b.radius - a.radius)
  const gap = 18
  const total = nodes.reduce((s, n) => s + (n.radius * 2 + gap) ** 2, 0)
  const targetWidth = Math.max(900, Math.sqrt(total) * 1.3)
  let x = 0, y = 0, rowH = 0
  for (const node of nodes) {
    const d = node.radius * 2
    if (x > 0 && x + d > targetWidth) { x = 0; y += rowH + gap; rowH = 0 }
    node.x = x + node.radius
    node.y = y + node.radius
    x += d + gap
    rowH = Math.max(rowH, d)
  }
  return nodes
}

/** Simple radial/ring layout for a focused dependency neighborhood. */
export function layoutRadial<T>(items: T[], id: (item: T) => string, centerId: string | null, edges: Array<{ source: string; target: string }>): Array<{ item: T; x: number; y: number }> {
  if (items.length === 0) return []
  const ids = new Set(items.map(id))
  const dist = new Map<string, number>()
  if (centerId && ids.has(centerId)) {
    dist.set(centerId, 0)
    const adj = new Map<string, string[]>()
    for (const e of edges) {
      if (!ids.has(e.source) || !ids.has(e.target)) continue
      ;(adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target)
      ;(adj.get(e.target) ?? adj.set(e.target, []).get(e.target)!).push(e.source)
    }
    const q = [centerId]
    while (q.length) {
      const cur = q.shift()!
      const d = dist.get(cur)!
      for (const n of adj.get(cur) ?? []) if (!dist.has(n)) { dist.set(n, d + 1); q.push(n) }
    }
  }
  const buckets = new Map<number, T[]>()
  for (const item of items) {
    const d = dist.get(id(item)) ?? 99
    ;(buckets.get(d) ?? buckets.set(d, []).get(d)!).push(item)
  }
  const result: Array<{ item: T; x: number; y: number }> = []
  for (const [d, bucket] of [...buckets.entries()].sort((a, b) => a[0] - b[0])) {
    bucket.sort((a, b) => id(a).localeCompare(id(b)))
    if (d === 0 && bucket.length === 1) { result.push({ item: bucket[0]!, x: 0, y: 0 }); continue }
    const r = d === 99 ? 320 : d * 140
    bucket.forEach((item, i) => {
      const a = (Math.PI * 2 * i) / Math.max(1, bucket.length) - Math.PI / 2
      result.push({ item, x: Math.cos(a) * r, y: Math.sin(a) * r })
    })
  }
  return result
}

/** Hierarchical tree layout for module symbols (classes/functions). */
export function layoutTree<T>(roots: T[], id: (item: T) => string, children: (item: T) => T[], label: (item: T) => string): { positions: Map<string, { x: number; y: number }>; bounds: Bounds } {
  const positions = new Map<string, { x: number; y: number }>()
  const rowH = 28
  const indent = 22
  let y = 24
  function walk(item: T, depth: number) {
    const x = 24 + depth * indent
    positions.set(id(item), { x, y })
    y += rowH
    for (const child of [...children(item)].sort((a, b) => label(a).localeCompare(label(b)))) walk(child, depth + 1)
  }
  for (const root of [...roots].sort((a, b) => label(a).localeCompare(label(b)))) walk(root, 0)
  const pts = [...positions.values()]
  return { positions, bounds: pts.length ? { minX: 0, minY: 0, maxX: 420, maxY: y + 20 } : { minX: 0, minY: 0, maxX: 1, maxY: 1 } }
}

function hashSeed(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}
function seeded(i: number, seed: number): number {
  const x = Math.sin(seed + i * 127.1) * 43758.5453
  return x - Math.floor(x)
}

/** Force-directed layout: connected groups/nodes attract, all repel. Deterministic and bounded. */
export function layoutForce<T>(items: T[], opts: {
  id: (item: T) => string
  weight: (item: T) => number
  edges: Array<{ source: string; target: string; weight?: number }>
  width?: (item: T) => number
  height?: (item: T) => number
  minSize?: number
  maxSize?: number
}): Array<{ item: T; x: number; y: number; radius: number; width: number; height: number }> {
  if (items.length === 0) return []
  const minS = opts.minSize ?? 44
  const maxS = opts.maxSize ?? 140
  const weights = items.map(opts.weight)
  const minW = Math.min(...weights), maxW = Math.max(...weights)
  const sizeOf = (w: number) => maxW === minW ? (minS + maxS) / 2 : minS + ((Math.sqrt(w) - Math.sqrt(minW)) / (Math.sqrt(maxW) - Math.sqrt(minW) || 1)) * (maxS - minS)
  const seed = hashSeed(items.map(opts.id).sort().join("|"))
  const nodes = items.map((item, i) => {
    const w = opts.width?.(item) ?? sizeOf(opts.weight(item))
    const h = opts.height?.(item) ?? Math.max(40, w * 0.58)
    const a = seeded(i, seed) * Math.PI * 2
    const r = 120 + seeded(i + 1000, seed) * 220
    return { item, id: opts.id(item), x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0, width: w, height: h, radius: Math.max(w, h) / 2 }
  })
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const links = opts.edges.map((e) => ({ s: byId.get(e.source), t: byId.get(e.target), w: Math.max(1, e.weight ?? 1) })).filter((e): e is { s: typeof nodes[0]; t: typeof nodes[0]; w: number } => !!e.s && !!e.t)
  const hasLinks = links.length > 0
  const nCount = nodes.length
  const maxPairs = Math.max(1, (nCount * (nCount - 1)) / 2)
  const density = Math.min(1, links.length / maxPairs)
  // Adaptive tuning: sparse/few-node System Overview graphs disperse under global
  // repulsion with little attraction. Increase gravity and reduce spread while
  // preserving "connected groups closer" when links exist.
  const sparse = density < 0.18 || (nCount <= 10 && density < 0.35)
  const few = nCount <= 14
  const area = nodes.reduce((s, n) => s + (Math.max(n.width, n.height) + (sparse ? 12 : 18)) ** 2, 0)
  const spreadMul = sparse ? (few ? 0.48 : 0.58) : (hasLinks ? 0.74 : 0.9)
  const k = Math.sqrt(area / Math.max(1, nCount)) * spreadMul
  const gravity = sparse ? (few ? 0.085 : 0.055) : (density < 0.35 ? 0.018 : 0.006)
  const repMul = sparse ? 0.42 : 0.6
  const springMul = sparse ? 0.16 : 0.13
  const iterations = nCount > 500 ? 70 : nCount > 180 ? 100 : 150
  // Compact deterministic initialization near the origin.
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]!
    const a = seeded(i, seed) * Math.PI * 2
    const r = (sparse && few ? 14 : 28) + seeded(i + 1000, seed) * (sparse && few ? 38 : 75)
    n.x = Math.cos(a) * r; n.y = Math.sin(a) * r
  }
  for (let it = 0; it < iterations; it++) {
    const temp = k * (1 - it / iterations) * 0.9
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]!, b = nodes[j]!
        let dx = a.x - b.x, dy = a.y - b.y
        let d2 = dx * dx + dy * dy
        if (d2 < 0.01) { dx = (seeded(i * 31 + j, seed) - 0.5) * 2; dy = (seeded(j * 31 + i, seed) - 0.5) * 2; d2 = dx * dx + dy * dy }
        const d = Math.sqrt(d2)
        const minD = (Math.max(a.width, a.height) + Math.max(b.width, b.height)) / 2 + (sparse ? 18 : 22)
        const rep = ((k * k) * repMul) / d + (d < minD ? (minD - d) * 2.4 : 0)
        const fx = (dx / d) * rep, fy = (dy / d) * rep
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy
      }
    }
    for (const l of links) {
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y
      const d = Math.max(1, Math.hypot(dx, dy))
      const idealBase = (Math.max(l.s.width, l.s.height) + Math.max(l.t.width, l.t.height)) / 2 + (sparse ? 26 : 34)
      const ideal = Math.max(idealBase, k * ((sparse ? 0.72 : 0.5) + (sparse ? 0.4 : 0.65) / Math.sqrt(l.w + 1)))
      const f = ((d - ideal) / d) * springMul * Math.min(4, Math.log2(l.w + 1) + 1)
      const fx = dx * f, fy = dy * f
      l.s.vx += fx; l.s.vy += fy; l.t.vx -= fx; l.t.vy -= fy
    }
    for (const n of nodes) {
      // Gentle gravity prevents sparse/disconnected layouts from drifting apart.
      n.vx -= n.x * gravity
      n.vy -= n.y * gravity
      const d = Math.hypot(n.vx, n.vy) || 1
      const lim = Math.min(temp, d)
      n.x += (n.vx / d) * lim
      n.y += (n.vy / d) * lim
      n.vx *= 0.4; n.vy *= 0.4
    }
  }
  // center
  const cx = nodes.reduce((s, n) => s + n.x, 0) / nodes.length
  const cy = nodes.reduce((s, n) => s + n.y, 0) / nodes.length
  for (const n of nodes) { n.x -= cx; n.y -= cy }
  return nodes.map(({ item, x, y, radius, width, height }) => ({ item, x, y, radius, width, height }))
}

/** Directed/layered layout (Sugiyama-lite) for module dependencies.
 *  Positions reflect dependency direction and are ordered to reduce edge crossings. */
export function layoutLayered<T>(items: T[], opts: {
  id: (item: T) => string
  edges: Array<{ source: string; target: string; weight?: number }>
  nodeWidth?: number
  nodeHeight?: number
}): Array<{ item: T; x: number; y: number }> {
  if (items.length === 0) return []
  const nw = opts.nodeWidth ?? 180
  const nh = opts.nodeHeight ?? 46
  const vGap = 34 // vertical gap between nodes in a layer
  const hGap = 80 // horizontal gap between layers (extra room for edges)
  const ids = items.map(opts.id)
  const idSet = new Set(ids)
  const out = new Map<string, string[]>()
  const inc = new Map<string, string[]>()
  for (const id of ids) { out.set(id, []); inc.set(id, []) }
  const edges = opts.edges.filter((e) => idSet.has(e.source) && idSet.has(e.target) && e.source !== e.target)
  for (const e of edges) { out.get(e.source)!.push(e.target); inc.get(e.target)!.push(e.source) }

  // Greedy feedback arc removal for layering (data unchanged).
  const forward = new Set<string>()
  const state = new Map<string, 0 | 1 | 2>()
  function dfs(id: string) {
    state.set(id, 1)
    for (const n of out.get(id) ?? []) {
      const s = state.get(n) ?? 0
      if (s === 0) { forward.add(`${id}->${n}`); dfs(n) }
      else if (s === 2) forward.add(`${id}->${n}`)
      // s===1 => back edge, omit from layering
    }
    state.set(id, 2)
  }
  for (const id of ids) if ((state.get(id) ?? 0) === 0) dfs(id)
  const layerEdges = edges.filter((e) => forward.has(`${e.source}->${e.target}`))
  const lOut = new Map<string, string[]>()
  const lIn = new Map<string, string[]>()
  for (const id of ids) { lOut.set(id, []); lIn.set(id, []) }
  for (const e of layerEdges) { lOut.get(e.source)!.push(e.target); lIn.get(e.target)!.push(e.source) }

  // Longest-path layering
  const layer = new Map<string, number>()
  const order = [...ids].sort((a, b) => (inc.get(a)!.length - inc.get(b)!.length) || a.localeCompare(b))
  for (const id of order) {
    let l = 0
    for (const p of lIn.get(id) ?? []) l = Math.max(l, (layer.get(p) ?? 0) + 1)
    layer.set(id, l)
  }
  const maxLayer = Math.max(0, ...layer.values())
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => [])
  for (const id of ids) layers[layer.get(id) ?? 0]!.push(id)
  for (const l of layers) l.sort((a, b) => a.localeCompare(b))

  // Adjacency including dummy nodes for long edges (spanning > 1 layer) so
  // ordering/crossing reduction accounts for them.
  const adjOut = new Map<string, string[]>()
  const adjIn = new Map<string, string[]>()
  function addAdj(a: string, b: string) {
    ;(adjOut.get(a) ?? adjOut.set(a, []).get(a)!).push(b)
    ;(adjIn.get(b) ?? adjIn.set(b, []).get(b)!).push(a)
  }
  for (const id of ids) { adjOut.set(id, []); adjIn.set(id, []) }
  let dummySeq = 0
  for (const e of layerEdges) {
    const ls = layer.get(e.source) ?? 0
    const lt = layer.get(e.target) ?? 0
    if (lt <= ls + 1) { addAdj(e.source, e.target); continue }
    let prev = e.source
    for (let li = ls + 1; li < lt; li++) {
      const d = `__d${dummySeq++}__`
      adjOut.set(d, []); adjIn.set(d, [])
      layers[li]!.push(d)
      addAdj(prev, d)
      prev = d
    }
    addAdj(prev, e.target)
  }

  // Barycenter + transpose sweeps to reduce edge crossings.
  const passes = ids.length > 120 ? 10 : 18
  for (let pass = 0; pass < passes; pass++) {
    for (let li = 1; li < layers.length; li++) sweepLayer(layers, li, layers[li - 1]!, adjIn)
    for (let li = layers.length - 2; li >= 0; li--) sweepLayer(layers, li, layers[li + 1]!, adjOut)
  }

  // Coordinate assignment (real nodes only) preserving order.
  const positions = new Map<string, Point>()
  layers.forEach((l, li) => {
    const real = l.filter((id) => !id.startsWith("__d"))
    const totalH = real.length * nh + Math.max(0, real.length - 1) * vGap
    real.forEach((id, i) => positions.set(id, { x: li * (nw + hGap), y: i * (nh + vGap) - totalH / 2 }))
  })
  return items.map((item) => ({ item, ...(positions.get(opts.id(item)) ?? { x: 0, y: 0 }) }))
}

/** Circular layout for module dependencies: nodes on a circle ordered by connections. */
export function layoutCircular<T>(items: T[], opts: {
  id: (item: T) => string
  edges: Array<{ source: string; target: string; weight?: number }>
  nodeWidth?: number
  nodeHeight?: number
}): Array<{ item: T; x: number; y: number }> {
  if (items.length === 0) return []
  const nw = opts.nodeWidth ?? 180
  const nh = opts.nodeHeight ?? 46
  const ids = items.map(opts.id)
  const idSet = new Set(ids)
  const n = ids.length
  if (n === 1) return [{ item: items[0]!, x: 0, y: 0 }]

  // Undirected weighted adjacency (data unchanged, only for ordering).
  const adj = new Map<string, Map<string, number>>()
  const degree = new Map<string, number>()
  for (const id of ids) { adj.set(id, new Map()); degree.set(id, 0) }
  const edges = opts.edges.filter((e) => idSet.has(e.source) && idSet.has(e.target) && e.source !== e.target)
  for (const e of edges) {
    const w = Math.max(1, e.weight ?? 1)
    adj.get(e.source)!.set(e.target, (adj.get(e.source)!.get(e.target) ?? 0) + w)
    adj.get(e.target)!.set(e.source, (adj.get(e.target)!.get(e.source) ?? 0) + w)
    degree.set(e.source, (degree.get(e.source) ?? 0) + w)
    degree.set(e.target, (degree.get(e.target) ?? 0) + w)
  }

  // Greedy ordering that keeps connected nodes adjacent around the circle.
  const order: string[] = []
  const remaining = new Set(ids)
  while (remaining.size > 0) {
    if (order.length === 0) {
      const first = [...remaining].sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0) || a.localeCompare(b))[0]!
      order.push(first); remaining.delete(first)
      continue
    }
    const current = order[order.length - 1]!
    const currentAdj = adj.get(current)!
    const pool = [...remaining].filter((c) => currentAdj.has(c))
    const candidates = pool.length > 0 ? pool : [...remaining]
    let best: string | null = null
    let bestScore = -Infinity
    for (const cand of candidates) {
      let score = (currentAdj.get(cand) ?? 0) * 4 + (degree.get(cand) ?? 0) * 0.01
      const tail = Math.min(4, order.length)
      for (let k = 0; k < tail; k++) {
        const prev = order[order.length - 1 - k]!
        score += (adj.get(prev)?.get(cand) ?? 0) * (4 - k) * 0.7
      }
      let visitedW = 0
      for (const prev of order) visitedW += adj.get(prev)?.get(cand) ?? 0
      score += visitedW * 0.35
      if (score > bestScore || (score === bestScore && best !== null && ((degree.get(cand) ?? 0) > (degree.get(best) ?? 0) || ((degree.get(cand) ?? 0) === (degree.get(best) ?? 0) && cand.localeCompare(best) < 0)))) {
        bestScore = score; best = cand
      }
    }
    const next = best!
    order.push(next); remaining.delete(next)
  }

  // Unique undirected edges for the circular-distance cost.
  const uniq = new Map<string, { a: string; b: string; w: number }>()
  for (const e of edges) {
    if (e.source === e.target) continue
    const key = e.source < e.target ? `${e.source}\\u0000${e.target}` : `${e.target}\\u0000${e.source}`
    const w = Math.max(1, e.weight ?? 1)
    const cur = uniq.get(key)
    if (cur) cur.w += w
    else uniq.set(key, { a: e.source, b: e.target, w })
  }
  const uniqEdges = [...uniq.values()]
  const costOf = (ord: string[]): number => {
    if (ord.length <= 2 || uniqEdges.length === 0) return 0
    const pos = new Map(ord.map((id, i) => [id, i]))
    let total = 0
    for (const e of uniqEdges) {
      const pa = pos.get(e.a), pb = pos.get(e.b)
      if (pa === undefined || pb === undefined) continue
      const d = Math.abs(pa - pb)
      total += e.w * Math.min(d, ord.length - d)
    }
    return total
  }

  // Adjacent-swap improvement (circular neighbours) to reduce circular span of edges.
  if (n >= 3 && uniqEdges.length > 0) {
    const passes = uniqEdges.length > 2000 ? 1 : n > 150 ? 2 : 4
    let currentCost = costOf(order)
    for (let pass = 0; pass < passes; pass++) {
      let improved = false
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n
        const tmp = order[i]!; order[i] = order[j]!; order[j] = tmp
        const nextCost = costOf(order)
        if (nextCost < currentCost - 1e-9) { currentCost = nextCost; improved = true }
        else { const t2 = order[i]!; order[i] = order[j]!; order[j] = t2 }
      }
      if (!improved) break
    }
  }

  const positions = new Map<string, Point>()
  const spacing = Math.max(nw, nh) + 20
  if (n <= 36) {
    const radius = n === 2 ? spacing / 2 : spacing / (2 * Math.sin(Math.PI / n))
    order.forEach((id, i) => {
      const theta = -Math.PI / 2 + (i * Math.PI * 2) / n
      positions.set(id, { x: Math.cos(theta) * radius, y: Math.sin(theta) * radius })
    })
  } else {
    // Multi-ring circular layout for large counts: keeps bounds compact so the
    // whole circle (and its chords) stays visible instead of cropping edges.
    const radialGap = Math.max(nh + 40, 86)
    const baseRadius = 150
    const rings: Array<{ radius: number; ids: string[] }> = []
    let idx = 0
    for (let ring = 0; idx < n; ring++) {
      const radius = baseRadius + ring * radialGap
      const capacity = Math.max(3, Math.floor((Math.PI * 2 * radius) / spacing))
      const take = Math.min(capacity, n - idx)
      rings.push({ radius, ids: order.slice(idx, idx + take) })
      idx += take
    }
    for (const ring of rings) {
      ring.ids.forEach((id, i) => {
        const theta = -Math.PI / 2 + (i * Math.PI * 2) / Math.max(1, ring.ids.length)
        positions.set(id, { x: Math.cos(theta) * ring.radius, y: Math.sin(theta) * ring.radius })
      })
    }
  }
  return items.map((item) => ({ item, ...(positions.get(opts.id(item)) ?? { x: 0, y: 0 }) }))
}

function sweepLayer(layers: string[][], li: number, adjLayer: string[], adj: Map<string, string[]>) {
  const pos = new Map(adjLayer.map((id, i) => [id, i]))
  const l = layers[li]!
  const b = (id: string) => bary(id, adj.get(id) ?? [], pos)
  l.sort((a, bId) => b(a) - b(bId) || a.localeCompare(bId))
  // Transpose adjacent nodes while it reduces crossings with the adjacent layer.
  let improved = true
  let guard = 0
  while (improved && guard++ < 8) {
    improved = false
    for (let i = 0; i < l.length - 1; i++) {
      if (crossingsDelta(l, i, adjLayer, adj) > 0) {
        const tmp = l[i]!; l[i] = l[i + 1]!; l[i + 1] = tmp
        improved = true
      }
    }
  }
}

function crossingsDelta(l: string[], i: number, adjLayer: string[], adj: Map<string, string[]>): number {
  // Positive => swapping l[i],l[i+1] reduces crossings to adjLayer.
  const pos = new Map(adjLayer.map((id, idx) => [id, idx]))
  const n1 = (adj.get(l[i]!) ?? []).map((n) => pos.get(n)).filter((v): v is number => v !== undefined)
  const n2 = (adj.get(l[i + 1]!) ?? []).map((n) => pos.get(n)).filter((v): v is number => v !== undefined)
  let before = 0, after = 0
  for (const a of n1) for (const b of n2) { if (a > b) before++; else if (a < b) after++ }
  return before - after
}
function bary(_id: string, neighbors: string[], pos: Map<string, number>): number {
  const vals = neighbors.map((n) => pos.get(n)).filter((v): v is number => v !== undefined)
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 1e9
}

/** Directional impact layout: incoming left, focus center, outgoing right, grouped by depth. */
export function layoutImpact<T>(items: T[], opts: {
  id: (item: T) => string
  centerId: string
  directionOf: (id: string) => "center" | "in" | "out"
  depthOf: (id: string) => number
}): Array<{ item: T; x: number; y: number }> {
  const buckets = new Map<string, T[]>()
  for (const item of items) {
    const id = opts.id(item)
    const dir = opts.directionOf(id)
    const depth = dir === "center" ? 0 : opts.depthOf(id)
    const key = `${dir}:${depth}`
    ;(buckets.get(key) ?? buckets.set(key, []).get(key)!).push(item)
  }
  const result: Array<{ item: T; x: number; y: number }> = []
  const xStep = 185
  const yGap = 46
  for (const [key, bucket] of [...buckets.entries()].sort()) {
    bucket.sort((a, b) => opts.id(a).localeCompare(opts.id(b)))
    const [dir, depthStr] = key.split(":") as ["center" | "in" | "out", string]
    const depth = Number(depthStr)
    const x = dir === "center" ? 0 : dir === "out" ? depth * xStep : -depth * xStep
    const totalH = (bucket.length - 1) * yGap
    bucket.forEach((item, i) => result.push({ item, x, y: i * yGap - totalH / 2 }))
  }
  return result
}

/** Detect directed cycles (returns count of back-edges found via DFS). */
export function detectCycleCount(nodeIds: string[], edges: Array<{ source: string; target: string }>): number {
  return detectSCC(nodeIds, edges).count
}

export interface SCCResult {
  count: number
  components: string[][]
  nodeIds: Set<string>
  edgeKeys: Set<string>
}

/** Strongly connected components (Tarjan, directed) that contain a cycle. */
export function detectSCC(nodeIds: string[], edges: Array<{ source: string; target: string }>): SCCResult {
  const set = new Set(nodeIds)
  const adj = new Map<string, string[]>()
  const selfLoops = new Set<string>()
  for (const id of nodeIds) adj.set(id, [])
  for (const e of edges) {
    if (!set.has(e.source) || !set.has(e.target)) continue
    if (e.source === e.target) { selfLoops.add(e.source); continue }
    adj.get(e.source)!.push(e.target)
  }
  let index = 0
  const indices = new Map<string, number>()
  const low = new Map<string, number>()
  const onStack = new Set<string>()
  const stack: string[] = []
  const components: string[][] = []
  function strongconnect(v: string) {
    indices.set(v, index); low.set(v, index); index += 1
    stack.push(v); onStack.add(v)
    for (const w of adj.get(v) ?? []) {
      if (!indices.has(w)) { strongconnect(w); low.set(v, Math.min(low.get(v)!, low.get(w)!)) }
      else if (onStack.has(w)) low.set(v, Math.min(low.get(v)!, indices.get(w)!))
    }
    if (low.get(v) === indices.get(v)) {
      const comp: string[] = []
      let w: string
      do { w = stack.pop()!; onStack.delete(w); comp.push(w) } while (w !== v)
      if (comp.length > 1 || selfLoops.has(comp[0]!)) components.push(comp.sort())
    }
  }
  for (const id of nodeIds) if (!indices.has(id)) strongconnect(id)
  const nodeIdsCyclic = new Set(components.flat())
  const edgeKeys = new Set<string>()
  const compOf = new Map<string, number>()
  components.forEach((c, i) => c.forEach((id) => compOf.set(id, i)))
  for (const e of edges) {
    if (!set.has(e.source) || !set.has(e.target)) continue
    const a = compOf.get(e.source), b = compOf.get(e.target)
    if (a !== undefined && a === b) edgeKeys.add(`${e.source}->${e.target}`)
  }
  for (const id of selfLoops) edgeKeys.add(`${id}->${id}`)
  return { count: components.length, components, nodeIds: nodeIdsCyclic, edgeKeys }
}
