<script>
  let { days = [] } = $props()
  let tooltip = $state(null)

  const MAX_COUNT = 6
  // Mismos pasos de color que ActivityHeatmap — DESIGN.md blue family, sin hex inventado.
  const STEPS = ['#3b82f6', '#1d4ed8', '#1e40af', '#0f2d4a']
  const LEGEND = ['#f0f4f8', ...STEPS]
  const DIAS_LABEL = ['Lun', '', 'Mié', '', 'Vie', '', '']
  const MESES_LABEL = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

  function intensity(count) {
    if (count === 0) return '#f0f4f8'
    const idx = Math.min(STEPS.length - 1, Math.ceil((count / MAX_COUNT) * STEPS.length) - 1)
    return STEPS[Math.max(0, idx)]
  }

  function fmtDDMM(ts) {
    const d = new Date(ts)
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
  }

  const weeks = $derived.by(() => {
    const cols = []
    for (let w = 0; w * 7 < days.length; w++) cols.push(days.slice(w * 7, w * 7 + 7))
    return cols
  })

  const monthLabels = $derived.by(() =>
    weeks.map((week, i) => {
      const mes = new Date(week[0].date).getMonth()
      const mesPrevio = i > 0 ? new Date(weeks[i - 1][0].date).getMonth() : null
      return mes !== mesPrevio ? MESES_LABEL[mes] : ''
    })
  )

  function showTooltip(e, day) {
    const rect = e.currentTarget.getBoundingClientRect()
    tooltip = { day, left: rect.left + rect.width / 2, bottom: window.innerHeight - rect.top + 8 }
  }
  const hideTooltip = () => tooltip = null
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Actividad Anual</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">Fichas registradas · último año</p>
    </div>
    <div class="flex items-center gap-1.5 text-[10px] text-ink-muted">
      <span>Sin actividad</span>
      {#each LEGEND as c}
        <span class="h-2.5 w-2.5 rounded-[2px]" style:background-color={c}></span>
      {/each}
      <span>Alta</span>
    </div>
  </div>

  <div class="overflow-x-auto px-4 py-4">
    <div class="inline-flex gap-1.5">
      <div class="flex shrink-0 flex-col gap-1 pt-[18px]">
        {#each DIAS_LABEL as label}
          <div class="h-3.5 text-[9px] leading-[14px] text-ink-muted">{label}</div>
        {/each}
      </div>
      <div>
        <div class="mb-1 flex gap-1">
          {#each monthLabels as label}
            <div class="w-3.5 shrink-0 whitespace-nowrap font-mono text-[9px] text-ink-muted">{label}</div>
          {/each}
        </div>
        <div class="flex gap-1">
          {#each weeks as week}
            <div class="flex flex-col gap-1">
              {#each week as d}
                <div
                  class="h-3.5 w-3.5 cursor-default rounded-[2px] ring-1 ring-inset ring-black/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
                  style:background-color={intensity(d.count)}
                  role="button"
                  tabindex="0"
                  aria-label={`${fmtDDMM(d.date)}: ${d.count} ficha${d.count === 1 ? '' : 's'}`}
                  onmouseenter={(e) => showTooltip(e, d)}
                  onmouseleave={hideTooltip}
                  onfocus={(e) => showTooltip(e, d)}
                  onblur={hideTooltip}
                ></div>
              {/each}
            </div>
          {/each}
        </div>
      </div>
    </div>
  </div>
</div>

{#if tooltip}
  <div class="tooltip-fixed" style:left="{tooltip.left}px" style:bottom="{tooltip.bottom}px">
    <p class="font-mono text-[10px] text-ink-muted">
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
