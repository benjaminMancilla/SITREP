<script>
  import IconWarning from './icons/IconWarning.svelte'
  import IconCheck from './icons/IconCheck.svelte'

  let { naves = [], puedeEditar = false, detalleUrlTemplate = '', editarUrlTemplate = '' } = $props()

  const PER_PAGE = 15
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

  function pedirDesactivar(nave) {
    window.dispatchEvent(new CustomEvent('nave-desactivar', {
      detail: { id: nave.id, subtitulo: `${nave.nombre} · ${nave.matricula}` },
    }))
  }

  function formatFecha(iso) {
    if (!iso) return 'Sin fichas'
    return new Date(iso).toLocaleString('es-CL', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    })
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
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Eslora</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Arqueo bruto</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Cap. personas</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Períodos abiertos</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Fallos activos</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Fallos nuevos</th>
            <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em]">Resoluciones</th>
            <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.07em]">Última ficha</th>
            <th class="px-4 py-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.07em]">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {#each paged as nave (nave.id)}
            <tr class="border-b border-surface-border bg-white transition last:border-b-0 even:bg-[#fafcff] hover:!bg-[#f0f7ff]">
              <td class="px-4 py-3.5">
                <a href={urlFor(detalleUrlTemplate, nave.id)} class="font-semibold text-navy transition hover:text-brand">{nave.nombre}</a>
                <p class="font-mono text-[11px] text-ink-muted">{nave.matricula}</p>
              </td>
              <td class="px-4 py-3.5 text-center text-[13px] text-ink">{Number(nave.eslora)}</td>
              <td class="px-4 py-3.5 text-center text-[13px] text-ink">{nave.arqueoBruto}</td>
              <td class="px-4 py-3.5 text-center text-[13px] text-ink">{nave.capacidadPersonas}</td>
              <td class="px-4 py-3.5 text-center">
                <span
                  class="inline-flex items-center rounded-[4px] border px-2 py-0.5 text-[11px] font-semibold"
                  class:border-info-border={nave.periodosAbiertos > 0}
                  class:bg-info-bg={nave.periodosAbiertos > 0}
                  class:text-info={nave.periodosAbiertos > 0}
                  class:border-neutral-border={nave.periodosAbiertos === 0}
                  class:bg-neutral-bg={nave.periodosAbiertos === 0}
                  class:text-neutral={nave.periodosAbiertos === 0}
                >{nave.periodosAbiertos}</span>
              </td>
              <td class="px-4 py-3.5 text-center">
                <span
                  class="inline-flex items-center gap-1 justify-center rounded-[4px] px-2.5 py-1 text-[11px] font-semibold"
                  class:bg-fail-bg={nave.fallosActivos > 0}
                  class:text-fail={nave.fallosActivos > 0}
                  class:bg-neutral-bg={nave.fallosActivos === 0}
                  class:text-neutral={nave.fallosActivos === 0}
                >{#if nave.fallosActivos > 0}<IconWarning />{/if}{nave.fallosActivos}</span>
              </td>
              <td class="px-4 py-3.5 text-center">
                <span
                  class="inline-flex items-center gap-1 justify-center rounded-[4px] px-2.5 py-1 text-[11px] font-semibold"
                  class:bg-warn-bg={nave.fallosNuevos > 0}
                  class:text-warn={nave.fallosNuevos > 0}
                  class:bg-neutral-bg={nave.fallosNuevos === 0}
                  class:text-neutral={nave.fallosNuevos === 0}
                >{#if nave.fallosNuevos > 0}<IconWarning />{/if}{nave.fallosNuevos}</span>
              </td>
              <td class="px-4 py-3.5 text-center">
                <span
                  class="inline-flex items-center gap-1 justify-center rounded-[4px] px-2.5 py-1 text-[11px] font-semibold"
                  class:bg-ok-bg={nave.resoluciones > 0}
                  class:text-ok={nave.resoluciones > 0}
                  class:bg-neutral-bg={nave.resoluciones === 0}
                  class:text-neutral={nave.resoluciones === 0}
                >{#if nave.resoluciones > 0}<IconCheck />{/if}{nave.resoluciones}</span>
              </td>
              <td class="px-4 py-3.5 font-mono text-[11px] text-ink-secondary">{formatFecha(nave.ultimaFichaEn)}</td>
              <td class="px-4 py-3.5">
                <div class="flex flex-wrap justify-end gap-1.5">
                  <a href={urlFor(detalleUrlTemplate, nave.id)} class="btn-ghost-info inline-flex items-center rounded-md border border-info-border bg-white px-2.5 py-1.5 text-[11px] font-semibold text-info transition">Ver detalle</a>
                  {#if puedeEditar}
                    <a href={urlFor(editarUrlTemplate, nave.id)} class="btn-ghost-warn inline-flex items-center rounded-md border border-warn-border bg-white px-2.5 py-1.5 text-[11px] font-semibold text-warn transition">Editar</a>
                    <button type="button" onclick={() => pedirDesactivar(nave)} class="btn-ghost-fail inline-flex items-center rounded-md border border-fail-border bg-white px-2.5 py-1.5 text-[11px] font-semibold text-fail transition">Desactivar</button>
                  {/if}
                </div>
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
