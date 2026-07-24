import ActivityHeatmap from '../src/ActivityHeatmap.svelte'
import { mount } from 'svelte'

const WEEKS = 12

const el = document.getElementById('svelte-activity-heatmap')
if (el) {
  const { slug } = el.dataset
  mount(ActivityHeatmap, { target: el, props: { slug, weeks: WEEKS } })
}
