import { useEffect, useRef } from 'react'

export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const code = window.location.pathname.split('/graph/')[1] || ''

  const initialized = useRef(false)
  useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    const script = document.createElement('script')
    script.src = 'https://d3js.org/d3.v7.min.js'
    script.onload = () => initGraph(code)
    document.head.appendChild(script)
    return () => {
      // don't reset initialized — StrictMode remount should not re-init
    }
  }, [code])

  return (
    <div style={{ margin: 0, fontFamily: 'sans-serif', background: '#0b1020', color: '#e6e6e6', height: '100vh' }}>
      <h1 style={{ padding: '12px 16px', margin: 0, fontSize: 16, borderBottom: '1px solid #222' }}>
        Knowledge Graph — Room {code}
      </h1>
      <div id="graph" ref={containerRef} style={{ width: '100vw', height: 'calc(100vh - 44px)' }} />
    </div>
  )
}

function initGraph(code: string) {
  const d3 = (window as any).d3
  if (!d3) return
  const width = window.innerWidth
  const height = window.innerHeight - 44
  const svg = d3.select('#graph').append('svg').attr('width', width).attr('height', height)
  const g = svg.append('g')
  const zoom = d3.zoom().on('zoom', (e: any) => g.attr('transform', e.transform))
  svg.call(zoom)

  const NODE_COLOR: Record<string, string> = { skill: '#f39c12', topic: '#9b59b6', claim: '#e74c3c', entity: '#2ecc71' }
  let simulation = d3.forceSimulation()
    .force('link', d3.forceLink().id((d: any) => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))

  let linkSel: any, nodeSel: any
  let nodes: any[] = [], links: any[] = []

  function render() {
    linkSel = g.selectAll('.link').data(links)
    linkSel.exit().remove()
    const linkEnter = linkSel.enter().append('line').attr('class', (d: any) => 'link ' + d.relation)
    linkSel = linkEnter.merge(linkSel).attr('stroke-width', (d: any) => Math.max(1, (d.weight || 1) * 2))
      .attr('stroke-opacity', 0.6)

    nodeSel = g.selectAll('.node').data(nodes, (d: any) => d.id)
    nodeSel.exit().remove()
    const nodeEnter = nodeSel.enter().append('g').attr('class', 'node')
      .call(d3.drag().on('start', dragStart).on('drag', dragging).on('end', dragEnd))
    nodeEnter.append('circle').attr('r', 8).attr('fill', (d: any) => NODE_COLOR[d.type] || '#999').attr('stroke', '#fff').attr('stroke-width', 1.5)
    nodeEnter.append('text').attr('dx', 12).attr('dy', 4).text((d: any) => d.label).attr('font-size', 11).attr('fill', '#e6e6e6')
    nodeSel = nodeEnter.merge(nodeSel)

    simulation.nodes(nodes)
    simulation.force('link').links(links)
    simulation.alpha(1).restart()
    simulation.on('tick', () => {
      linkSel.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
      nodeSel.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    })
  }

  function dragStart(e: any, d: any) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y }
  function dragging(e: any, d: any) { d.fx = e.x; d.fy = e.y }
  function dragEnd(e: any, d: any) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }

  function applyGraph(g: any) {
    nodes = (g.nodes || []).map((n: any) => ({ ...n }))
    const nodeMap = new Map(nodes.map((n: any) => [n.id, n]))
    links = (g.edges || []).map((e: any) => ({
      source: nodeMap.get(e.source) || e.source,
      target: nodeMap.get(e.target) || e.target,
      relation: e.relation,
      weight: e.weight,
    }))
    render()
  }

  fetch(`/api/rooms/${code}/graph`)
    .then(r => r.json())
    .then(applyGraph)
    .catch(e => console.error(e))

  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${wsProto}//${window.location.host}/ws/${code}?name=graph-viewer`)
  ws.onmessage = (ev: any) => {
    try {
      const data = JSON.parse(ev.data)
      if (data.type === 'graph-update') {
        applyGraph({ nodes: data.nodes, edges: data.edges })
      }
    } catch (e) { console.error(e) }
  }
  ws.onopen = () => console.log('ws connected')
}