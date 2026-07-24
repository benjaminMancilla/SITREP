import YearActivityHeatmap from '../src/YearActivityHeatmap.svelte'
import { mount } from 'svelte'

const el = document.getElementById('svelte-year-heatmap')
if (el) {
  const { slug, naveId } = el.dataset
  mount(YearActivityHeatmap, { target: el, props: { slug, naveId } })
}
