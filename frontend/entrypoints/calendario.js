import VencimientosTimeline from '../src/VencimientosTimeline.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-hitos-inminentes')
if (el) {
  const { slug } = el.dataset
  fetch(`/${slug}/api/v1/hitos/inminentes/`)
    .then((res) => res.json())
    .then((hitos) => {
      const mapped = hitos.map((h) => ({ ...h, fecha: new Date(h.fecha).getTime() }))
      mount(VencimientosTimeline, { target: el, props: { hitos: mapped } })
    })
}
