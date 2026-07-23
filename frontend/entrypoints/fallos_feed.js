import FailureFeed from '../src/FailureFeed.svelte'
import { mount } from 'svelte'

const DIAS = 30 // ponytail: standalone Feed page bound, tune freely; dashboard variant passes its own windowDays

const el = document.getElementById('svelte-failure-feed')
if (el) {
  const { slug, fallosUrl, fallosResueltosUrl } = el.dataset
  mount(FailureFeed, {
    target: el,
    props: { slug, fallosUrl, fallosResueltosUrl, windowDays: DIAS },
  })
}
