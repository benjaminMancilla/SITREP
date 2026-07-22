import YearActivityHeatmap from '../src/YearActivityHeatmap.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-year-heatmap')
if (el) {
  const { slug, naveId } = el.dataset
  fetch(`/${slug}/api/v1/naves/${naveId}/actividad/`)
    .then((res) => res.json())
    .then((days) => {
      const mapped = days.map((d) => ({ ...d, date: new Date(d.date).getTime() }))
      mount(YearActivityHeatmap, { target: el, props: { days: mapped } })
    })
    .catch(() => { el.textContent = 'No se pudo cargar el heatmap de actividad.' })
}
