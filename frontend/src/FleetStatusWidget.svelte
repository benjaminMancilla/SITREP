<script>
  let {
    naves = [],
    navesUrl = null,
    detalleUrlTemplate = '',
    fallosActivosUrlTemplate = '',
    fallosNuevosUrlTemplate = '',
    fallosResueltosUrlTemplate = '',
  } = $props()

  const PER_PAGE = 5
  let query = $state('')
  let page = $state(1)

  let filtered = $derived.by(() => {
    if (!query.trim()) return naves
    const q = query.trim().toLowerCase()
    return naves.filter((n) => n.nombre.toLowerCase().includes(q) || n.matricula.toLowerCase().includes(q))
  })

  let totalPages = $derived(Math.max(1, Math.ceil(filtered.length / PER_PAGE)))
  let paged = $derived(filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE))

  $effect(() => {
    query
    page = 1
  })

  function urlFor(template, id) {
    return template.replace('__ID__', String(id))
  }

  function formatFecha(iso) {
    if (!iso) return 'Sin fichas'
    return new Date(iso).toLocaleString('es-CL', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  }
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Estado de la Flota</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">{filtered.length} nave{filtered.length === 1 ? '' : 's'}</p>
    </div>
    {#if navesUrl}
      <a href={navesUrl} class="text-[11px] font-semibold text-info transition hover:text-brand">Ver todas las naves →</a>
    {/if}
  </div>

  <div class="border-b border-surface-border px-4 py-2.5">
    <div class="relative w-full sm:w-[220px]">
      <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-ink-muted">
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.3" />
          <line x1="9.5" y1="9.5" x2="13" y2="13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
        </svg>
      </span>
      <input
        bind:value={query}
        type="text"
        placeholder="Buscar nave o matrícula…"
        class="h-[30px] w-full rounded-md border border-surface-border bg-white pl-8 pr-3 text-xs text-ink outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
      />
    </div>
  </div>

  {#if paged.length === 0}
    <div class="px-4 py-8 text-center text-[13px] text-ink-muted">No se encontraron naves.</div>
  {:else}
    <ul class="divide-y divide-surface-border">
      {#each paged as nave (nave.id)}
        <li class="group flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 transition hover:bg-[#f0f7ff]">
          <a href={urlFor(detalleUrlTemplate, nave.id)} class="min-w-[150px]">
            <p class="text-[13px] font-semibold text-navy transition group-hover:text-brand">{nave.nombre}</p>
            <p class="font-mono text-[11px] text-ink-muted">{nave.matricula}</p>
          </a>

          <div class="flex flex-wrap items-center gap-1.5">
            <a
              href={urlFor(fallosActivosUrlTemplate, nave.id)}
              class="inline-flex items-center gap-1 rounded-[4px] border px-2 py-0.5 font-mono text-[11px] font-semibold transition hover:opacity-80"
              class:border-fail-border={nave.fallosActivos > 0}
              class:bg-fail-bg={nave.fallosActivos > 0}
              class:text-fail={nave.fallosActivos > 0}
              class:border-neutral-border={nave.fallosActivos === 0}
              class:bg-neutral-bg={nave.fallosActivos === 0}
              class:text-neutral={nave.fallosActivos === 0}
            >
              {nave.fallosActivos} falla{nave.fallosActivos === 1 ? '' : 's'}
            </a>
            <a
              href={urlFor(fallosNuevosUrlTemplate, nave.id)}
              class="inline-flex items-center gap-1 rounded-[4px] border px-2 py-0.5 font-mono text-[11px] font-semibold transition hover:opacity-80"
              class:border-orange-300={nave.fallosNuevos > 0}
              class:bg-orange-50={nave.fallosNuevos > 0}
              class:text-orange-600={nave.fallosNuevos > 0}
              class:border-neutral-border={nave.fallosNuevos === 0}
              class:bg-neutral-bg={nave.fallosNuevos === 0}
              class:text-neutral={nave.fallosNuevos === 0}
            >
              {nave.fallosNuevos} nuevo{nave.fallosNuevos === 1 ? '' : 's'}
            </a>
            <a
              href={urlFor(fallosResueltosUrlTemplate, nave.id)}
              class="inline-flex items-center rounded-[4px] border px-2 py-0.5 font-mono text-[11px] font-semibold transition hover:opacity-80"
              class:border-ok-border={nave.resoluciones > 0}
              class:bg-ok-bg={nave.resoluciones > 0}
              class:text-ok={nave.resoluciones > 0}
              class:border-neutral-border={nave.resoluciones === 0}
              class:bg-neutral-bg={nave.resoluciones === 0}
              class:text-neutral={nave.resoluciones === 0}
            >
              {nave.resoluciones} resuelta{nave.resoluciones === 1 ? '' : 's'}
            </a>
          </div>

          <div class="ml-auto flex items-center gap-3">
            <span class="font-mono text-[11px] text-ink-secondary">{formatFecha(nave.ultimaFichaEn)}</span>
            <a href={urlFor(detalleUrlTemplate, nave.id)} class="text-[11px] font-semibold text-info opacity-0 transition group-hover:opacity-100">Ver detalle →</a>
          </div>
        </li>
      {/each}
    </ul>

    {#if totalPages > 1}
      <div class="flex items-center justify-between border-t border-surface-border bg-neutral-bg px-4 py-2.5">
        <p class="text-[11px] text-ink-muted">{paged.length} de {filtered.length} naves</p>
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
