import { mount } from 'svelte'
import UrgenciaTable from '../src/UrgenciaTable.svelte'
import FailureFeed from '../src/FailureFeed.svelte'
import VencimientosTimeline from '../src/VencimientosTimeline.svelte'
import FleetStatusWidget from '../src/FleetStatusWidget.svelte'
import ActivityHeatmap from '../src/ActivityHeatmap.svelte'

const FEED_DIAS = 3 // ponytail: compact dashboard summary, narrower than the standalone Feed page's 30 days
const HEATMAP_WEEKS = 6 // fleet-wide heatmap uses 12 weeks on naves_lista; dashboard gets the shorter summary window

const urgenciaEl = document.getElementById('svelte-urgencia')
if (urgenciaEl) {
  const { slug, naveDetalleUrlTemplate, periodoDetalleUrlTemplate } = urgenciaEl.dataset
  mount(UrgenciaTable, {
    target: urgenciaEl,
    props: {
      slug,
      naveDetalleUrlTemplate: naveDetalleUrlTemplate.replace('987654321', '__ID__'),
      periodoDetalleUrlTemplate: periodoDetalleUrlTemplate
        .replace('987654321', '__NAVE_ID__')
        .replace('123456789', '__PERIODO_ID__'),
    },
  })
}

const feedEl = document.getElementById('svelte-failure-feed')
if (feedEl) {
  const { slug, fallosUrl, fallosResueltosUrl } = feedEl.dataset
  mount(FailureFeed, {
    target: feedEl,
    props: { slug, fallosUrl, fallosResueltosUrl, windowDays: FEED_DIAS },
  })
}

const timelineEl = document.getElementById('svelte-hitos-inminentes')
if (timelineEl) {
  const { slug, calendarioUrl } = timelineEl.dataset
  fetch(`/${slug}/api/v1/hitos/inminentes/`)
    .then((res) => res.json())
    .then((hitos) => {
      const mapped = hitos.map((h) => ({ ...h, fecha: new Date(h.fecha).getTime() }))
      mount(VencimientosTimeline, { target: timelineEl, props: { hitos: mapped, calendarioUrl } })
    })
}

const fleetEl = document.getElementById('svelte-fleet-status')
if (fleetEl) {
  const {
    slug, navesUrl, detalleUrlTemplate,
    fallosActivosUrlTemplate, fallosNuevosUrlTemplate, fallosResueltosUrlTemplate,
  } = fleetEl.dataset
  fetch(`/${slug}/api/v1/naves/`)
    .then((res) => res.json())
    .then((naves) => mount(FleetStatusWidget, {
      target: fleetEl,
      props: {
        naves,
        navesUrl,
        detalleUrlTemplate: detalleUrlTemplate.replace('987654321', '__ID__'),
        fallosActivosUrlTemplate: fallosActivosUrlTemplate.replace('987654321', '__ID__'),
        fallosNuevosUrlTemplate: fallosNuevosUrlTemplate.replace('987654321', '__ID__'),
        fallosResueltosUrlTemplate: fallosResueltosUrlTemplate.replace('987654321', '__ID__'),
      },
    }))
}

const heatmapEl = document.getElementById('svelte-activity-heatmap')
if (heatmapEl) {
  const { slug } = heatmapEl.dataset
  fetch(`/${slug}/api/v1/naves/actividad/?semanas=${HEATMAP_WEEKS}`)
    .then((res) => res.json())
    .then((naves) => {
      const mapped = naves.map((n) => ({
        ...n,
        days: n.days.map((d) => ({ ...d, date: new Date(d.date).getTime() })),
      }))
      mount(ActivityHeatmap, { target: heatmapEl, props: { naves: mapped, weeks: HEATMAP_WEEKS } })
    })
}

// ponytail: reliability scatter deferred (feat/reliability-fleet, feat/reliability-nave not built yet) —
// no #svelte-reliability-scatter mount here; add it back once that endpoint exists.
