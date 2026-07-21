import FleetTable from '../src/FleetTable.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-fleet-table')
if (el) {
  const { slug, puedeEditar, detalleUrlTemplate, editarUrlTemplate } = el.dataset
  fetch(`/${slug}/api/v1/naves/`)
    .then((res) => res.json())
    .then((naves) => mount(FleetTable, {
      target: el,
      props: {
        naves,
        puedeEditar: puedeEditar === 'true',
        detalleUrlTemplate: detalleUrlTemplate.replace('987654321', '__ID__'),
        editarUrlTemplate: editarUrlTemplate.replace('987654321', '__ID__'),
      },
    }))
    .catch(() => {
      el.textContent = 'No se pudieron cargar las naves.'
    })
}
