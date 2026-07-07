import UrgenciaTable from '../src/UrgenciaTable.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-urgencia')
if (el) mount(UrgenciaTable, { target: el, props: { slug: el.dataset.slug } })
