<script>
  let { events = [], fallosUrl = null, fallosResueltosUrl = null, windowDays = 3 } = $props()

  const PER_PAGE = 5
  let page = $state(1)

  let totalPages = $derived(Math.max(1, Math.ceil(events.length / PER_PAGE)))
  let paged = $derived(events.slice((page - 1) * PER_PAGE, page * PER_PAGE))

  function relativeTime(ts) {
    const diffMin = Math.round((Date.now() - ts) / 60000)
    if (diffMin < 1) return 'ahora'
    if (diffMin < 60) return `hace ${diffMin} min`
    const diffH = Math.round(diffMin / 60)
    if (diffH < 24) return `hace ${diffH} h`
    return `hace ${Math.round(diffH / 24)} d`
  }

  function eventoUrl(ev) {
    const base = ev.tipo === 'nuevo' ? fallosUrl : fallosResueltosUrl
    if (!base) return null
    const sep = base.includes('?') ? '&' : '?'
    return `${base}${sep}matriz_id=${ev.id}`
  }

  function naveLine(ev) {
    if (ev.tipo !== 'nuevo' || ev.requisitosFallidos.length === 0) return ev.nave
    const n = ev.requisitosFallidos.length
    return `${ev.nave} · ${n} requisito${n === 1 ? '' : 's'} con falla`
  }
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Últimos Eventos</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">Eventos de los últimos {windowDays} días</p>
    </div>
    <div class="flex items-center gap-2">
      <span class="rounded-full bg-neutral-bg px-2 py-0.5 font-mono text-[11px] font-semibold text-ink-secondary">{events.length}</span>
      {#if fallosUrl}
        <a href={fallosUrl} class="text-[11px] font-semibold text-info transition hover:text-brand">Ver todos los fallos →</a>
      {/if}
    </div>
  </div>

  {#if events.length === 0}
    <div class="px-4 py-8 text-center">
      <p class="text-[13px] font-medium text-ok">Sin novedades en los últimos {windowDays} días</p>
      <p class="mt-1 text-[11px] text-ink-muted">La flota está operando sin cambios recientes</p>
    </div>
  {:else}
    <ul class="divide-y divide-surface-border">
      {#each paged as ev (ev.id)}
        {@const url = eventoUrl(ev)}
        <li class="relative flex items-center gap-3 px-4 py-3 transition-colors hover:bg-neutral-bg">
          {#if url}
            <a href={url} class="absolute inset-0" aria-label="Ver {ev.item} en {ev.nave}"></a>
          {/if}
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
            class:bg-fail-bg={ev.tipo === 'nuevo'}
            class:bg-ok-bg={ev.tipo === 'resuelto'}
          >
            {#if ev.tipo === 'nuevo'}
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                <path d="M5 1L9 8.5H1L5 1Z" stroke="#b91c1c" stroke-width="1.1" stroke-linejoin="round" />
                <line x1="5" y1="4" x2="5" y2="6.2" stroke="#b91c1c" stroke-width="1.1" stroke-linecap="round" />
                <circle cx="5" cy="7.4" r="0.6" fill="#b91c1c" />
              </svg>
            {:else}
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                <path d="M1.5 5.3L4 7.8L8.5 2.5" stroke="#15803d" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            {/if}
          </span>

          <div class="min-w-0 flex-1">
            <p class="truncate text-[13px] font-bold leading-snug text-ink" title={ev.item}>{ev.item}</p>
            <p class="truncate text-[13px] leading-snug text-ink-secondary" title={naveLine(ev)}>{naveLine(ev)}</p>
            <p class="mt-1 truncate font-mono text-[11px] text-ink-muted">{relativeTime(ev.timestamp)} · {ev.usuario}</p>
          </div>
        </li>
      {/each}
    </ul>

    {#if totalPages > 1}
      <div class="flex items-center justify-between border-t border-surface-border bg-neutral-bg px-4 py-2.5">
        <p class="text-[11px] text-ink-muted">{paged.length} de {events.length} eventos</p>
        <div class="flex items-center gap-1">
          <button
            onclick={() => page = Math.max(1, page - 1)}
            disabled={page === 1}
            class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Anterior
          </button>
          <span class="inline-flex items-center rounded-md border border-navy bg-navy px-2.5 py-1 text-xs font-semibold text-white">{page}</span>
          <button
            onclick={() => page = Math.min(totalPages, page + 1)}
            disabled={page === totalPages}
            class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Siguiente
          </button>
        </div>
      </div>
    {/if}
  {/if}
</div>
