<script>
  import IconWarning from './icons/IconWarning.svelte'
  import IconCheck from './icons/IconCheck.svelte'
  import RowActionsMenu from './RowActionsMenu.svelte'

  let {
    naves = [],
    puedeEditar = false,
    detalleUrlTemplate = '',
    editarUrlTemplate = '',
    fallosActivosUrlTemplate = '',
    fallosNuevosUrlTemplate = '',
    fallosResueltosUrlTemplate = '',
  } = $props()

  const PER_PAGE = 15
  let query = $state('')
  let page = $state(1)
  let hoveredNaveId = $state(null)

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

  function pedirDesactivar(nave) {
    window.dispatchEvent(new CustomEvent('nave-desactivar', {
      detail: { id: nave.id, subtitulo: `${nave.nombre} · ${nave.matricula}` },
    }))
  }

  function accionesFor(nave) {
    if (!puedeEditar) return []
    return [
      { label: 'Editar', href: urlFor(editarUrlTemplate, nave.id) },
      { label: 'Desactivar', variant: 'danger', onclick: () => pedirDesactivar(nave) },
    ]
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

<div class="rounded-lg border border-surface-border bg-white shadow-sm">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
    <p class="text-[12px] text-ink-muted">{filtered.length} nave{filtered.length === 1 ? '' : 's'}</p>
    <div class="relative w-full sm:w-[240px]">
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
    <div class="px-5 py-8 text-center text-sm text-ink-muted">No se encontraron naves.</div>
  {:else}
    <div class="overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="bg-neutral-bg text-ink-muted">
          <tr>
            <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.07em]">Nave</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Fallas activas</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Fallas nuevas</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Resoluciones</th>
            <th class="hidden md:table-cell px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.07em]">Actualización</th>
            <th class="px-4 py-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.07em]"><span class="sr-only">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          {#each paged as nave (nave.id)}
            <tr class="border-b border-surface-border bg-white transition last:border-b-0 even:bg-[#fafcff]">
              <td class="px-2 py-1.5">
                <div
                  class="rounded-sm px-2 py-2 transition-colors duration-100"
                  style:background-color={hoveredNaveId === nave.id ? '#f0f7ff' : 'transparent'}
                  onmouseenter={() => hoveredNaveId = nave.id}
                  onmouseleave={() => hoveredNaveId = null}
                >
                  <a
                    href={urlFor(detalleUrlTemplate, nave.id)}
                    class="block rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                  >
                    <p class="font-semibold text-navy transition-colors hover:text-brand">{nave.nombre}</p>
                    <p class="font-mono text-[11px] text-ink-muted">{nave.matricula}</p>
                  </a>
                </div>
              </td>
              <td class="px-4 py-3.5 text-center">
                <a
                  href={urlFor(fallosActivosUrlTemplate, nave.id)}
                  title="Fallas activas"
                  aria-label="{nave.fallosActivos} falla{nave.fallosActivos === 1 ? '' : 's'} activas en {nave.nombre}"
                  class="fault-badge inline-flex items-center justify-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
                  class:bg-fail-bg={nave.fallosActivos > 0}
                  class:text-fail={nave.fallosActivos > 0}
                  class:bg-neutral-bg={nave.fallosActivos === 0}
                  class:text-neutral={nave.fallosActivos === 0}
                >{#if nave.fallosActivos > 0}<IconWarning />{/if}{nave.fallosActivos}</a>
              </td>
              <td class="px-4 py-3.5 text-center">
                <a
                  href={urlFor(fallosNuevosUrlTemplate, nave.id)}
                  title="Fallas nuevas"
                  aria-label="{nave.fallosNuevos} falla{nave.fallosNuevos === 1 ? '' : 's'} nuevas en {nave.nombre}"
                  class="fault-badge inline-flex items-center justify-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
                  class:bg-warn-bg={nave.fallosNuevos > 0}
                  class:text-warn={nave.fallosNuevos > 0}
                  class:bg-neutral-bg={nave.fallosNuevos === 0}
                  class:text-neutral={nave.fallosNuevos === 0}
                >{#if nave.fallosNuevos > 0}<IconWarning />{/if}{nave.fallosNuevos}</a>
              </td>
              <td class="px-4 py-3.5 text-center">
                <a
                  href={urlFor(fallosResueltosUrlTemplate, nave.id)}
                  title="Fallas resueltas"
                  aria-label="{nave.resoluciones} resuelta{nave.resoluciones === 1 ? '' : 's'} en {nave.nombre}"
                  class="fault-badge inline-flex items-center justify-center gap-1 rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-semibold"
                  class:bg-ok-bg={nave.resoluciones > 0}
                  class:text-ok={nave.resoluciones > 0}
                  class:bg-neutral-bg={nave.resoluciones === 0}
                  class:text-neutral={nave.resoluciones === 0}
                >{#if nave.resoluciones > 0}<IconCheck />{/if}{nave.resoluciones}</a>
              </td>
              <td class="hidden md:table-cell px-4 py-3.5 text-[13px] text-ink-secondary">{formatFecha(nave.ultimaFichaEn)}</td>
              <td class="px-4 py-3.5 text-right">
                {#if puedeEditar}
                  <RowActionsMenu actions={accionesFor(nave)} label="Más acciones sobre {nave.nombre}" />
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if totalPages > 1}
      <div class="flex items-center justify-between border-t border-surface-border bg-neutral-bg px-4 py-2.5">
        <p class="text-[11px] text-ink-muted">{paged.length} de {filtered.length} naves</p>
        <div class="flex items-center gap-1">
          <button onclick={() => page = Math.max(1, page - 1)} disabled={page === 1} class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:cursor-not-allowed disabled:opacity-40">Anterior</button>
          <span class="inline-flex items-center rounded-md border border-navy bg-navy px-2.5 py-1 text-xs font-semibold text-white">{page}</span>
          <button onclick={() => page = Math.min(totalPages, page + 1)} disabled={page === totalPages} class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:cursor-not-allowed disabled:opacity-40">Siguiente</button>
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
