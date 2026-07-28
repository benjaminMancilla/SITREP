import VencimientosCalendario from '../src/VencimientosCalendario.svelte'
import { localDateMs } from '../src/dateOnly.js'
import { mount } from 'svelte'

const el = document.getElementById('svelte-hitos-inminentes')
if (el) {
  const { slug } = el.dataset
  fetch(`/${slug}/api/v1/hitos/inminentes/`)
    .then((res) => res.json())
    .then((hitos) => {
      const mapped = hitos.map((h) => ({ ...h, fecha: localDateMs(h.fecha) }))
      mount(VencimientosCalendario, { target: el, props: { hitos: mapped } })
    })
}
