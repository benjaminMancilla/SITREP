import FailureFeed from '../src/FailureFeed.svelte'
import { mount } from 'svelte'

const DIAS = 30 // ponytail: standalone Feed page bound, tune freely; dashboard variant will pass its own windowDays later

const el = document.getElementById('svelte-failure-feed')
if (el) {
  const { slug, fallosUrl, fallosResueltosUrl } = el.dataset
  fetch(`/${slug}/api/v1/fallos/feed/?dias=${DIAS}`)
    .then((res) => res.json())
    .then((events) => mount(FailureFeed, {
      target: el,
      props: { events, fallosUrl, fallosResueltosUrl, windowDays: DIAS },
    }))
}
