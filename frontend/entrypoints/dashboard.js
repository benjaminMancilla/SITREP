import { mount } from 'svelte'
import UrgenciaTable from '../src/UrgenciaTable.svelte'
import FailureFeed from '../src/FailureFeed.svelte'
import VencimientosTimeline from '../src/VencimientosTimeline.svelte'
import FleetStatusList from '../src/FleetStatusList.svelte'
import ActivityHeatmap from '../src/ActivityHeatmap.svelte'
import ReliabilityScatter from '../src/ReliabilityScatter.svelte'
import { buildFleet, buildFeedEvents, buildVencimientos, buildActivity, FEED_WINDOW_DAYS } from '../src/mockData.js'

const urgenciaEl = document.getElementById('svelte-urgencia')
if (urgenciaEl) mount(UrgenciaTable, { target: urgenciaEl, props: { slug: urgenciaEl.dataset.slug } })

// ponytail: mock fleet feeds every widget below so nave names line up across modules.
// Swap for real API data per-component once each endpoint is ready; delete mockData.js then.
const fleet = buildFleet(14)
const activity = buildActivity(fleet)

const feedEl = document.getElementById('svelte-failure-feed')
if (feedEl) mount(FailureFeed, { target: feedEl, props: { events: buildFeedEvents(fleet), fallosUrl: feedEl.dataset.fallosUrl, windowDays: FEED_WINDOW_DAYS } })

const timelineEl = document.getElementById('svelte-vencimientos-timeline')
if (timelineEl) mount(VencimientosTimeline, { target: timelineEl, props: { hitos: buildVencimientos(fleet) } })

const fleetEl = document.getElementById('svelte-fleet-status')
if (fleetEl) mount(FleetStatusList, { target: fleetEl, props: { naves: fleet, navesUrl: fleetEl.dataset.navesUrl } })

const heatmapEl = document.getElementById('svelte-activity-heatmap')
if (heatmapEl) mount(ActivityHeatmap, { target: heatmapEl, props: { naves: activity, navesUrl: heatmapEl.dataset.navesUrl } })

const scatterEl = document.getElementById('svelte-reliability-scatter')
if (scatterEl) mount(ReliabilityScatter, { target: scatterEl, props: { naves: fleet } })
