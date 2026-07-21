import ActivityHeatmap from '../src/ActivityHeatmap.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-activity-heatmap')
if (el) {
  const { slug } = el.dataset
  fetch(`/${slug}/api/v1/naves/actividad/`)
    .then((res) => res.json())
    .then((naves) => {
      const mapped = naves.map((n) => ({
        ...n,
        days: n.days.map((d) => ({ ...d, date: new Date(d.date).getTime() })),
      }))
      mount(ActivityHeatmap, { target: el, props: { naves: mapped } })
    })
    .catch(() => { el.textContent = 'No se pudo cargar el heatmap de actividad.' })
}
