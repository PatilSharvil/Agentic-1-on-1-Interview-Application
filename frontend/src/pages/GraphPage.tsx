import { useEffect, useRef, useState } from 'react'

const NODE_COLOR: Record<string, string> = {
  skill: '#f39c12',
  topic: '#9b59b6',
  claim: '#e74c3c',
  entity: '#2ecc71',
  group: '#3498db',
}

const LINK_COLOR: Record<string, string> = {
  supports: '#2ecc71',
  contradicts: '#e74c3c',
  has_skill: '#f1c40f',
  worked_at: '#1abc9c',
  used_skill: '#16a085',
  studied_at: '#3498db',
  built_with: '#e67e22',
  mentions: '#95a5a6',
  includes: '#5dade2',
  related: '#8e6fd8',
}

const RADIUS_BY_TYPE: Record<string, number> = {
  entity: 11,
  group: 14,
  claim: 6,
}

export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const code = window.location.pathname.split('/graph/')[1] || ''
  const [counts, setCounts] = useState({ nodes: 0, edges: 0 })
  const [live, setLive] = useState(false)

  const initialized = useRef(false)
  useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    const script = document.createElement('script')
    script.src = 'https://d3js.org/d3.v7.min.js'
    script.onload = () => initGraph(code, setCounts, setLive)
    document.head.appendChild(script)
    return () => {}
  }, [code])

  return (
    <div className="graph-page">
      <header className="graph-top">
        <h1>
          <span className="eq still" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          Knowledge graph
          <span className="graph-room">{code}</span>
        </h1>
        <span className="graph-stat">
          <span className="sdot" style={{ color: live ? 'var(--live)' : 'var(--rec)' }} aria-hidden="true">●</span>
          {live ? 'LIVE' : 'OFFLINE'}
          <span className="stat-counts">
            · {counts.nodes} NODES · {counts.edges} EDGES
          </span>
        </span>
      </header>
      <div className="graph-view">
        <div id="graph" ref={containerRef} style={{ width: '100%', height: '100%' }} />
        <div className="kg-legend">
          <div><b>Nodes</b></div>
          <div><span className="kg-dot" style={{ background: NODE_COLOR.skill }} />skill</div>
          <div><span className="kg-dot" style={{ background: NODE_COLOR.group }} />skill category</div>
          <div><span className="kg-dot" style={{ background: NODE_COLOR.topic }} />project / topic</div>
          <div><span className="kg-dot" style={{ background: NODE_COLOR.claim }} />claim</div>
          <div><span className="kg-dot" style={{ background: NODE_COLOR.entity }} />person / company</div>
          <hr />
          <div><b>Edges</b></div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.contradicts }} />contradicts</div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.supports }} />supports</div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.includes }} />includes</div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.built_with }} />built with</div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.used_skill }} />used skill</div>
          <div><span className="kg-line" style={{ background: LINK_COLOR.mentions }} />mentions</div>
        </div>
        <div id="kg-empty" className="kg-empty">
          <span className="eq still" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          <p>No graph yet — upload a resume in the copilot to seed it from the resume.</p>
        </div>
      </div>
    </div>
  )
}

function initGraph(
  code: string,
  setCounts: (c: { nodes: number; edges: number }) => void,
  setLive: (b: boolean) => void,
) {
  const d3 = (window as any).d3
  if (!d3) return
  const HEADER_H = 44
  const viewEl = document.querySelector('.graph-view') as HTMLElement | null
  const width = viewEl?.clientWidth ?? window.innerWidth
  const height = viewEl?.clientHeight ?? window.innerHeight - HEADER_H
  const svg = d3.select('#graph').append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')
  const zoom = d3.zoom().scaleExtent([0.2, 3]).on('zoom', (e: any) => g.attr('transform', e.transform))
  svg.call(zoom)

  const simulation = d3.forceSimulation()
    .force('link', d3.forceLink().id((d: any) => d.id).distance(linkDistance))
    // Milder repulsion + a gentle pull to the centre: the previous -260 charge
    // blasted 40+ skill nodes to the edges of the screen ("scattered around").
    .force('charge', d3.forceManyBody().strength((d: any) => (d.type === 'group' ? -220 : -150)))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.04))
    .force('y', d3.forceY(height / 2).strength(0.04))
    .force('collide', d3.forceCollide().radius((d: any) => (RADIUS_BY_TYPE[d.type] || 8) + 16))

  let linkSel: any, nodeSel: any
  let nodes: any[] = []
  let links: any[] = []

  simulation.on('tick', () => {
    if (linkSel) {
      linkSel
        // Lines without settled positions collapse onto the top-left corner;
        // hide them until both endpoints are finite.
        .attr('visibility', (d: any) =>
          Number.isFinite(d.source?.x) && Number.isFinite(d.target?.x) ? null : 'hidden')
        .attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
    }
    if (nodeSel) nodeSel.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  })

  function render() {
    linkSel = g.selectAll('.kg-link').data(links, (d: any) => `${d.source.id || d.source}-${d.target.id || d.target}-${d.relation}`)
    linkSel.exit().remove()
    const linkEnter = linkSel.enter().append('line').attr('class', (d: any) => `kg-link ${d.relation}`)
    linkSel = linkEnter.merge(linkSel)
      .attr('stroke-width', (d: any) => Math.max(1.2, (d.weight || 0.6) * 2))
      .attr('stroke-dasharray', (d: any) => (d.relation === 'related' ? '4 3' : null))
      .attr('stroke', (d: any) => LINK_COLOR[d.relation] || '#95a5a6')

    nodeSel = g.selectAll('.kg-node').data(nodes, (d: any) => d.id)
    nodeSel.exit().remove()
    const nodeEnter = nodeSel.enter().append('g').attr('class', 'kg-node')
      .call(d3.drag()
        .on('start', (e: any, d: any) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag', (e: any, d: any) => { d.fx = e.x; d.fy = e.y })
        .on('end', (e: any, d: any) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }))
    nodeEnter.append('circle')
      .attr('r', (d: any) => RADIUS_BY_TYPE[d.type] || 8)
      .attr('fill', (d: any) => NODE_COLOR[d.type] || '#999')
      .attr('stroke', '#3a3325')
      .attr('stroke-width', 1.5)
    nodeEnter.append('title').text((d: any) => {
      const meta = d.meta || {}
      return [d.label, d.type, meta.evidence ? `Evidence: ${meta.evidence}` : '', meta.source ? `Source: ${meta.source}` : '', meta.degree ? `Degree: ${meta.degree}` : ''].filter(Boolean).join('\n')
    })
    nodeEnter.append('text').attr('dx', 12).attr('dy', 4).text((d: any) => d.label)

    // Newly entered nodes MUST be merged back into nodeSel, otherwise the
    // tick handler never transforms them and they pile up at (0,0).
    nodeSel = nodeEnter.merge(nodeSel)

    simulation.nodes(nodes)
    simulation.force('link').links(links)
    simulation.alpha(0.9).restart()
    document.getElementById('kg-empty')!.style.display = nodes.length ? 'none' : 'flex'
    setCounts({ nodes: nodes.length, edges: links.length })
  }

  function applyGraph(graph: any) {
    const incoming = (graph.nodes || []).map((n: any) => ({ ...n }))
    // de-duplicate by id (last wins)
    const byId = new Map<string, any>()
    for (const n of incoming) byId.set(String(n.id), n)
    const prevPos = new Map(nodes.map((n: any) => [n.id, n]))
    nodes = Array.from(byId.values()).map((n: any, i: number) => {
      const total = byId.size || 1
      const a = (i / total) * Math.PI * 2
      const prev = prevPos.get(String(n.id))
      if (prev && Number.isFinite(prev.x)) {
        return { ...n, x: prev.x, y: prev.y, vx: prev.vx, vy: prev.vy }
      }
      // spread brand-new nodes in a ring so the first frames are readable
      return { ...n, x: width / 2 + Math.cos(a) * (height / 3), y: height / 2 + Math.sin(a) * (height / 3) }
    })
    // Index the FINAL node objects: the links must reference the same objects
    // the simulation moves — pointing at the pre-map raw values left every
    // edge stuck at NaN forever (invisible lines bug).
    const finalById = new Map(nodes.map((n: any) => [n.id, n]))
    links = (graph.edges || []).map((e: any) => ({
      source: finalById.get(String(e.source)) || e.source,
      target: finalById.get(String(e.target)) || e.target,
      relation: e.relation,
      weight: e.weight,
    })).filter((e: any) => e.source && e.target)
    render()
  }

  fetch(`/api/rooms/${code}/graph`)
    .then((r) => r.json())
    .then(applyGraph)
    .catch((e) => console.error('graph fetch failed', e))

  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${wsProto}//${window.location.host}/ws/${code}?name=graph-viewer`)
  ws.onopen = () => { setLive(true); console.log('graph ws connected') }
  ws.onclose = () => setLive(false)
  ws.onmessage = (ev: any) => {
    try {
      const data = JSON.parse(ev.data)
      if (data.type === 'graph-update') applyGraph({ nodes: data.nodes, edges: data.edges })
    } catch (e) { console.error(e) }
  }

  window.addEventListener('resize', () => {
    const w = viewEl?.clientWidth ?? window.innerWidth
    const h = viewEl?.clientHeight ?? window.innerHeight - HEADER_H
    svg.attr('width', w).attr('height', h)
    simulation.force('center', d3.forceCenter(w / 2, h / 2))
    simulation.alpha(0.3).restart()
  })
}

function linkDistance(d: any) {
  switch (d.relation) {
    case 'includes': return 65
    case 'has_skill': return 130
    case 'mentions': return 105
    case 'worked_at': return 120
    case 'used_skill': return 90
    case 'built_with': return 95
    case 'studied_at': return 130
    default: return 85
  }
}
