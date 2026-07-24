import VencimientosCalendario from '../src/VencimientosCalendario.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-hitos-inminentes')
if (el) {
  const { slug } = el.dataset
  fetch(`/${slug}/api/v1/hitos/inminentes/`)
    .then((res) => res.json())
    .then((hitos) => {
      const mapped = hitos.map((h) => ({ ...h, fecha: new Date(h.fecha).getTime() }))
      mount(VencimientosCalendario, { target: el, props: { hitos: mapped } })
    })
}
