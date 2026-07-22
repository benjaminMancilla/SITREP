<script>
  let { naves = [], weeks = 6 } = $props()
  let tooltip = $state(null)

  const MAX_COUNT = 6
  // DESIGN.md blue family only — no invented hex. Baseline is Instrument Grey.
  const STEPS = ['#3b82f6', '#1d4ed8', '#1e40af', '#0f2d4a'] // brand-light -> brand -> brand-dark -> navy
  const LEGEND = ['#f0f4f8', ...STEPS]

  function intensity(count) {
    if (count === 0) return '#f0f4f8'
    const idx = Math.min(STEPS.length - 1, Math.ceil((count / MAX_COUNT) * STEPS.length) - 1)
    return STEPS[Math.max(0, idx)]
  }

  function fmtDDMM(ts) {
    const d = new Date(ts)
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
  }

  function showTooltip(e, nave, day) {
    const rect = e.currentTarget.getBoundingClientRect()
    tooltip = { nave: nave.nombre, day, left: rect.left + rect.width / 2, bottom: window.innerHeight - rect.top + 8 }
  }
  const hideTooltip = () => tooltip = null
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Heatmap de Actividad</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">Fichas registradas · últimas {weeks} semanas</p>
    </div>
    <div class="flex items-center gap-1.5 text-[10px] text-ink-muted">
      <span>Sin actividad</span>
      {#each LEGEND as c}
        <span class="h-2.5 w-2.5 rounded-[2px]" style:background-color={c}></span>
      {/each}
      <span>Alta</span>
    </div>
  </div>

  {#if naves.length === 0}
    <div class="px-4 py-8 text-center text-[13px] text-ink-muted">No se encontraron naves.</div>
  {:else}
    <div class="overflow-x-auto px-4 py-4">
      <div class="min-w-fit space-y-1.5">
        <!-- Monday date markers -->
        <div class="flex items-center gap-3">
          <div class="w-32 shrink-0"></div>
          <div class="flex gap-1.5">
            {#each Array(weeks) as _, week}
              <div class="relative flex gap-1">
                {#each Array(7) as _, day}
                  <div class="h-3.5 w-3.5">
                    {#if day === 0 && naves[0]}
                      <span class="absolute -top-0.5 left-0 whitespace-nowrap font-mono text-[9px] leading-none text-ink-muted">
                        {fmtDDMM(naves[0].days[week * 7].date)}
                      </span>
                    {/if}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        </div>

        {#each naves as nave (nave.id)}
          <div class="flex items-center gap-3">
            <div class="w-32 shrink-0">
              <p class="truncate text-[12px] font-medium text-ink">{nave.nombre}</p>
            </div>
            <div class="flex gap-1.5">
              {#each Array(weeks) as _, week}
                <div class="flex gap-1">
                  {#each nave.days.slice(week * 7, week * 7 + 7) as d}
                    <div
                      class="h-3.5 w-3.5 cursor-default rounded-[2px] ring-1 ring-inset ring-black/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
                      style:background-color={intensity(d.count)}
                      role="button"
                      tabindex="0"
                      aria-label={`${fmtDDMM(d.date)}: ${d.count} ficha${d.count === 1 ? '' : 's'}`}
                      onmouseenter={(e) => showTooltip(e, nave, d)}
                      onmouseleave={hideTooltip}
                      onfocus={(e) => showTooltip(e, nave, d)}
                      onblur={hideTooltip}
                    ></div>
                  {/each}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

{#if tooltip}
  <div class="tooltip-fixed" style:left="{tooltip.left}px" style:bottom="{tooltip.bottom}px">
    <p class="text-[11px] font-semibold text-navy">{tooltip.nave}</p>
    <p class="mt-0.5 font-mono text-[10px] text-ink-muted">
      {fmtDDMM(tooltip.day.date)} · {tooltip.day.count} ficha{tooltip.day.count === 1 ? '' : 's'}
    </p>
  </div>
{/if}

<style>
  .tooltip-fixed {
    position: fixed;
    z-index: 9999;
    transform: translateX(-50%);
    border-radius: 8px;
    border: 1px solid #e2e8f0;
    background: #ffffff;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.10), 0 1px 4px rgb(0 0 0 / 0.06);
    padding: 0.5rem 0.65rem;
    pointer-events: none;
    font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
  }
</style>
