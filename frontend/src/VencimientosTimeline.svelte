<script>
  let { hitos = [], visiblePerGroup = 3 } = $props()

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
    <span
      class="shrink-0 text-[11px] font-semibold text-ink-muted opacity-70"
      title="Disponible cuando se habilite la sección de calendario"
    >
      Ver calendario completo
    </span>
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
              {@const past = h.fecha < now}
              <li class="flex gap-3">
                <div class="flex w-2 shrink-0 flex-col items-center">
                  <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full" class:bg-fail={past} class:bg-warn={!past}></span>
                  {#if i < visible.length - 1}
                    <span class="mt-1 w-px flex-1 bg-surface-border"></span>
                  {/if}
                </div>
                <div class="min-w-0 flex-1 pb-3">
                  <div class="flex items-baseline justify-between gap-2">
                    <p class="text-[13px] font-medium text-ink">
                      <span class="font-semibold text-navy">{h.nave}</span> · {h.periodicidad}
                    </p>
                    <span class="shrink-0 font-mono text-[11px]" class:text-fail={past} class:text-warn={!past}>
                      {fmtDate(h.fecha)}
                    </span>
                  </div>
                  <div class="mt-1.5 flex items-center gap-2">
                    <div class="h-[4px] flex-1 overflow-hidden rounded-full bg-surface-border">
                      <div class="h-full rounded-full bg-brand" style:width="{h.avance}%"></div>
                    </div>
                    <span class="shrink-0 font-mono text-[10px] text-ink-muted">{h.avance}% avance</span>
                  </div>
                </div>
              </li>
            {/each}
          </ol>
          {#if hiddenCount > 0}
            <p class="pl-5 text-[11px] text-ink-muted">+{hiddenCount} más</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
