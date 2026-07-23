<script>
  import { onMount } from 'svelte'
  import IconWarning from './icons/IconWarning.svelte'
  import IconCheck from './icons/IconCheck.svelte'

  let {
    slug,
    navesUrl = null,
    detalleUrlTemplate = '',
    fallosActivosUrlTemplate = '',
    fallosNuevosUrlTemplate = '',
    fallosResueltosUrlTemplate = '',
  } = $props()

  const PER_PAGE = 8
  const GRID_COLS = 'grid-cols-[minmax(0,1fr)_92px_92px_100px_140px]'
  const SKELETON_ROWS = [0, 1, 2, 3]

  let loading = $state(true)
  let error = $state(null)
  let naves = $state([])
  let query = $state('')
  let page = $state(1)
  let hoveredNaveId = $state(null)

  onMount(async () => {
    try {
      const res = await fetch(`/${slug}/api/v1/naves/`, { credentials: 'same-origin' })
      if (!res.ok) throw new Error(`Error ${res.status}`)
      naves = await res.json()
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })

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
    const d = new Date(iso)
    const dia = d.toLocaleDateString('es-CL', { day: 'numeric' })
    const mes = d.toLocaleDateString('es-CL', { month: 'short' }).replace('.', '')
    const hora = d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', hour12: false })
    return `${dia} ${mes.charAt(0).toUpperCase()}${mes.slice(1)}, ${hora}`
  }
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Estado de la Flota</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">
        {#if loading}Cargando…{:else}{filtered.length} nave{filtered.length === 1 ? '' : 's'}{/if}
      </p>
    </div>
    <div class="flex items-center gap-3">
      <div class="relative w-full sm:w-[200px]">
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
      {#if navesUrl}
        <a href={navesUrl} class="shrink-0 text-[11px] font-semibold text-info transition hover:text-brand">Ver todas las naves →</a>
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="grid {GRID_COLS} items-center gap-3 border-b border-surface-border bg-neutral-bg px-4 py-2">
      <span class="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Nave</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Fallas</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Nuevos</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Resueltos</span>
      <span class="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Actualización</span>
    </div>
    <ul class="divide-y divide-surface-border">
      {#each SKELETON_ROWS as ni}
        <li class="grid {GRID_COLS} items-center gap-3 px-4 py-3" style:background-color={ni % 2 === 1 ? '#fafcff' : '#ffffff'}>
          <div class="space-y-1.5">
            <div class="h-3 w-28 animate-pulse rounded bg-surface-border"></div>
            <div class="h-2.5 w-16 animate-pulse rounded bg-surface-border"></div>
          </div>
          <div class="h-6 w-14 animate-pulse justify-self-center rounded bg-surface-border"></div>
          <div class="h-6 w-14 animate-pulse justify-self-center rounded bg-surface-border"></div>
          <div class="h-6 w-16 animate-pulse justify-self-center rounded bg-surface-border"></div>
          <div class="h-3 w-24 animate-pulse rounded bg-surface-border"></div>
        </li>
      {/each}
    </ul>
  {:else if error}
    <div class="px-4 py-8 text-center">
      <p class="text-[13px] font-medium text-fail">No se pudo cargar el estado de la flota</p>
      <p class="mt-1 text-[11px] text-ink-muted">{error}</p>
    </div>
  {:else if paged.length === 0}
    <div class="px-4 py-8 text-center text-[13px] text-ink-muted">No se encontraron naves.</div>
  {:else}
    <div class="grid {GRID_COLS} items-center gap-3 border-b border-surface-border bg-neutral-bg px-4 py-2">
      <span class="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Nave</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Fallas</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Nuevos</span>
      <span class="text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Resueltos</span>
      <span class="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted">Actualización</span>
    </div>

    <ul class="divide-y divide-surface-border">
      {#each paged as nave (nave.id)}
        <li class="grid {GRID_COLS} items-center gap-3 px-4 py-3">
          <div
            class="min-w-0 self-stretch rounded-sm px-2 transition-colors duration-100"
            style:background-color={hoveredNaveId === nave.id ? '#f0f7ff' : 'transparent'}
            onmouseenter={() => hoveredNaveId = nave.id}
            onmouseleave={() => hoveredNaveId = null}
          >
            <a
              href={urlFor(detalleUrlTemplate, nave.id)}
              class="flex h-full min-w-0 flex-col justify-center rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            >
              <p class="truncate text-[13px] font-semibold text-navy transition-colors hover:text-brand">{nave.nombre}</p>
              <p class="truncate font-mono text-[11px] text-ink-muted">{nave.matricula}</p>
            </a>
          </div>

          <a
            href={urlFor(fallosActivosUrlTemplate, nave.id)}
            title="Fallas activas"
            aria-label="{nave.fallosActivos} falla{nave.fallosActivos === 1 ? '' : 's'} activas en {nave.nombre}"
            class="fault-badge inline-flex items-center justify-center justify-self-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
            class:bg-fail-bg={nave.fallosActivos > 0}
            class:text-fail={nave.fallosActivos > 0}
            class:bg-neutral-bg={nave.fallosActivos === 0}
            class:text-neutral={nave.fallosActivos === 0}
          >
            {#if nave.fallosActivos > 0}<IconWarning />{/if}{nave.fallosActivos}
          </a>

          <a
            href={urlFor(fallosNuevosUrlTemplate, nave.id)}
            title="Fallas nuevas"
            aria-label="{nave.fallosNuevos} falla{nave.fallosNuevos === 1 ? '' : 's'} nuevas en {nave.nombre}"
            class="fault-badge inline-flex items-center justify-center justify-self-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
            class:bg-warn-bg={nave.fallosNuevos > 0}
            class:text-warn={nave.fallosNuevos > 0}
            class:bg-neutral-bg={nave.fallosNuevos === 0}
            class:text-neutral={nave.fallosNuevos === 0}
          >
            {#if nave.fallosNuevos > 0}<IconWarning />{/if}{nave.fallosNuevos}
          </a>

          <a
            href={urlFor(fallosResueltosUrlTemplate, nave.id)}
            title="Fallas resueltas"
            aria-label="{nave.resoluciones} resuelta{nave.resoluciones === 1 ? '' : 's'} en {nave.nombre}"
            class="fault-badge inline-flex items-center justify-center justify-self-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
            class:bg-ok-bg={nave.resoluciones > 0}
            class:text-ok={nave.resoluciones > 0}
            class:bg-neutral-bg={nave.resoluciones === 0}
            class:text-neutral={nave.resoluciones === 0}
          >
            {#if nave.resoluciones > 0}<IconCheck />{/if}{nave.resoluciones}
          </a>

          <span class="text-[13px] text-ink-secondary">{formatFecha(nave.ultimaFichaEn)}</span>
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

<style>
  /* Convención "eleva y oscurece" para celdas clickeables — ver DESIGN.md § Clickable Rows & Cells */
  .fault-badge {
    transition: transform 160ms cubic-bezier(0.16, 1, 0.3, 1), filter 160ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .fault-badge:hover {
    filter: brightness(0.97) saturate(1.1);
    transform: translateY(-1px);
  }

  .fault-badge:focus-visible {
    outline: 2px solid #1d4ed8;
    outline-offset: 2px;
    filter: brightness(0.97) saturate(1.1);
  }

  @media (prefers-reduced-motion: reduce) {
    .fault-badge {
      transition: filter 160ms ease;
    }
    .fault-badge:hover {
      transform: none;
    }
  }
</style>
