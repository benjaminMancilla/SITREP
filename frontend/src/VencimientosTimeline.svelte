<script>
  let { hitos = [], visiblePerGroup = 3, calendarioUrl = null, periodoDetalleUrlTemplate = '' } = $props()

  const DAY = 86400000
  const now = Date.now()

  function bucketOf(fecha) {
    const diffDays = Math.round((fecha - now) / DAY)
    if (diffDays < 0) return { label: 'Vencidos recientemente', order: 0 }
    if (diffDays <= 6) return { label: 'Vence esta semana', order: 1 }
    return { label: 'Vence próxima semana', order: 2 }
  }

  function fmtDate(ts) {
    return new Date(ts).toLocaleDateString('es-CL', { day: '2-digit', month: 'short' })
  }

  function fmtRelativo(fecha) {
    const diffDays = Math.round((fecha - now) / DAY)
    if (diffDays === 0) return 'Hoy'
    if (diffDays === 1) return 'Mañana'
    if (diffDays === -1) return 'Ayer'
    if (diffDays > 1) return `En ${diffDays} días`
    return `Hace ${Math.abs(diffDays)} días`
  }

  const ESTADO_CLASSES = {
    ok: { dot: 'bg-ok', text: 'text-ok' },
    fail: { dot: 'bg-fail', text: 'text-fail' },
    warn: { dot: 'bg-warn', text: 'text-warn' },
    neutral: { dot: 'bg-neutral', text: 'text-neutral' },
  }

  function estadoDeHito(h) {
    if (h.avance >= 100) return 'ok'
    const diffDays = Math.round((h.fecha - now) / DAY)
    if (diffDays <= 0) return 'fail'
    if (diffDays > 8) return 'neutral'
    return 'warn'
  }

  const periodoUrl = (h) =>
    periodoDetalleUrlTemplate.replace('__NAVE_ID__', String(h.naveId)).replace('__PERIODO_ID__', String(h.id))

  let grouped = $derived.by(() => {
    const map = new Map()
    for (const h of hitos) {
      const b = bucketOf(h.fecha)
      if (!map.has(b.label)) map.set(b.label, { order: b.order, items: [] })
      map.get(b.label).items.push(h)
    }
    return [...map.entries()].sort((a, b) => a[1].order - b[1].order)
  })
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Hitos Inminentes</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">Vencimientos de períodos, lunes a domingo</p>
    </div>
    {#if calendarioUrl}
      <a href={calendarioUrl} class="shrink-0 text-[11px] font-semibold text-info transition hover:text-brand">
        Ver calendario completo →
      </a>
    {/if}
  </div>

  {#if hitos.length === 0}
    <div class="px-4 py-8 text-center">
      <p class="text-[13px] font-medium text-ok">Sin vencimientos en los próximos 14 días</p>
    </div>
  {:else}
    <div class="px-4 py-4">
      {#each grouped as [label, group] (label)}
        {@const visible = group.items.slice(0, visiblePerGroup)}
        {@const hiddenCount = group.items.length - visible.length}
        <div class="mb-4 last:mb-0">
          <p class="mb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">{label}</p>
          <ol>
            {#each visible as h, i (h.id)}
              {@const estado = ESTADO_CLASSES[estadoDeHito(h)]}
              <li class="flex gap-3">
                <div class="flex w-2 shrink-0 flex-col items-center">
                  <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full {estado.dot}"></span>
                  {#if i < visible.length - 1}
                    <span class="mt-1 w-px flex-1 bg-surface-border"></span>
                  {/if}
                </div>
                <a
                  href={periodoUrl(h)}
                  class="-mx-2 -mt-1 block min-w-0 flex-1 rounded-md px-2 pb-2 pt-1 transition-colors duration-150 hover:bg-neutral-bg focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand"
                >
                  <p class="truncate text-[13px] font-semibold text-ink">Cierre {h.periodicidad}</p>
                  <p class="truncate text-[12px] text-ink-muted">{h.nave}</p>
                  <div class="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                    <span class="font-medium {estado.text}">
                      {fmtRelativo(h.fecha)} <span class="font-normal text-ink-muted">({fmtDate(h.fecha)})</span>
                    </span>
                    <span class="text-ink-muted">•</span>
                    <div class="flex items-center gap-1.5 font-medium {estado.text}">
                      <svg class="h-3.5 w-3.5 -rotate-90" viewBox="0 0 36 36">
                        <circle cx="18" cy="18" r="16" fill="none" class="stroke-current opacity-20" stroke-width="4"></circle>
                        <circle cx="18" cy="18" r="16" fill="none" class="stroke-current" stroke-width="4" pathLength="100" stroke-dasharray="{h.avance} 100" stroke-dashoffset="0"></circle>
                      </svg>
                      <span>{h.avance}% avance</span>
                    </div>
                  </div>
                </a>
              </li>
            {/each}
          </ol>
          {#if hiddenCount > 0}
            {#if calendarioUrl}
              <a
                href={calendarioUrl}
                class="ml-5 mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-info transition hover:text-brand"
              >
                +{hiddenCount} más
                <svg width="8" height="8" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                  <path d="M1.5 3.5L5 7L8.5 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </a>
            {:else}
              <p class="pl-5 text-[11px] text-ink-muted">+{hiddenCount} más</p>
            {/if}
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
