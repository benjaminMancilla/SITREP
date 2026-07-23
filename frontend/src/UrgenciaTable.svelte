<script>
  import { onMount } from 'svelte'

  let { slug, naveDetalleUrlTemplate = '', periodoDetalleUrlTemplate = '' } = $props()

  const PER_PAGE = 10

  let loading = $state(true)
  let error = $state(null)
  let columns = $state([])
  let naves = $state([])
  let page = $state(1)
  let hoveredRow = $state(null)
  let tooltip = $state(null) // { cell, col, left, bottom }
  let formulaVisible = $state(false)
  let formulaHover = $state(false)

  let pagedNaves = $derived(naves.slice((page - 1) * PER_PAGE, page * PER_PAGE))
  let totalPages = $derived(Math.ceil(naves.length / PER_PAGE))

  onMount(async () => {
    try {
      const res = await fetch(`/${slug}/api/v1/dashboard/urgencia/`, {
        credentials: 'same-origin',
      })
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const data = await res.json()
      columns = data.columns
      naves = data.naves
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })

  const getCell = (nave, key) => nave.periodos[key] ?? null

  const HEAT = { fail: '#fe3a34', warn: '#feb800', ok: '#33c75a' }

  function urgency(u) {
    if (u >= 0.65) return { bg: HEAT.fail, text: 'text-fail', bar: HEAT.fail }
    if (u >= 0.35) return { bg: HEAT.warn, text: 'text-warn', bar: HEAT.warn }
    return { bg: HEAT.ok, text: 'text-ok', bar: HEAT.ok }
  }

  function rowBg(ni, hovered) {
    if (hovered) return '#f0f7ff'
    return ni % 2 === 1 ? '#fafcff' : '#ffffff'
  }

  function showTooltip(event, cell, col) {
    const rect = event.currentTarget.getBoundingClientRect()
    tooltip = {
      cell,
      col,
      left: rect.left + rect.width / 2,
      bottom: window.innerHeight - rect.top + 8,
    }
  }

  const hideTooltip = () => tooltip = null

  const naveUrl = (naveId) => naveDetalleUrlTemplate.replace('__ID__', String(naveId))
  const periodoUrl = (naveId, periodoId) =>
    periodoDetalleUrlTemplate.replace('__NAVE_ID__', String(naveId)).replace('__PERIODO_ID__', String(periodoId))
</script>

<!-- Título + leyenda -->
<div class="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
  <div>
    <h2 class="text-sm font-bold text-navy">Urgencia por Periodicidad</h2>
    <p class="mt-0.5 text-[11px] text-ink-muted">
      Cobertura de fichas en períodos activos · actualizado ahora
    </p>
  </div>
  <div class="flex flex-wrap items-center gap-3 lg:gap-4">
    <span class="flex items-center gap-1.5 text-[11px] text-ink-muted">
      <span class="inline-block h-2 w-2 rounded-sm" style="background:#33c75a"></span>Baja &lt;35%
    </span>
    <span class="flex items-center gap-1.5 text-[11px] text-ink-muted">
      <span class="inline-block h-2 w-2 rounded-sm" style="background:#feb800"></span>Media 35–65%
    </span>
    <span class="flex items-center gap-1.5 text-[11px] text-ink-muted">
      <span class="inline-block h-2 w-2 rounded-sm" style="background:#fe3a34"></span>Alta &gt;65%
    </span>
  </div>
</div>

<!-- Skeleton -->
{#if loading}
  <div class="overflow-hidden rounded-lg border border-surface-border bg-white">
    <div class="overflow-x-auto">
      <table class="min-w-full" style="border-collapse: separate; border-spacing: 0;">
        <thead class="bg-neutral-bg">
          <tr>
            <th class="sticky left-0 z-10 bg-neutral-bg px-4 py-2.5 border-b border-r border-surface-border w-44">
              <div class="h-3 w-16 animate-pulse rounded bg-surface-border"></div>
            </th>
            {#each [1,2,3] as _}
              <th class="px-4 py-2.5 border-b border-surface-border min-w-[120px]">
                <div class="h-3 w-14 mx-auto animate-pulse rounded bg-surface-border"></div>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody class="divide-y divide-surface-border">
          {#each [0,1,2,3] as ni}
            <tr style:background-color={ni % 2 === 1 ? '#fafcff' : '#ffffff'}>
              <td class="sticky left-0 z-10 px-4 py-3 border-r border-surface-border"
                  style:background-color={ni % 2 === 1 ? '#fafcff' : '#ffffff'}>
                <div class="space-y-1.5">
                  <div class="h-3 w-28 animate-pulse rounded bg-surface-border"></div>
                  <div class="h-2.5 w-16 animate-pulse rounded bg-surface-border"></div>
                </div>
              </td>
              {#each [1,2,3] as _}
                <td><div class="h-14 animate-pulse bg-surface-border opacity-30"></div></td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>

<!-- Error -->
{:else if error}
  <div class="rounded-lg border border-fail-border bg-fail-bg px-4 py-3 text-[13px] text-fail">
    No se pudieron cargar los datos de urgencia: {error}
  </div>

<!-- Tabla heatmap -->
{:else}
  <div class="overflow-hidden rounded-lg border border-surface-border bg-white">
    <div class="overflow-x-auto">
      <table class="min-w-full text-sm" style="border-collapse: separate; border-spacing: 0;">
        <thead class="bg-neutral-bg">
          <tr>
            <th class="sticky left-0 z-10 bg-neutral-bg px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted border-b border-surface-border">
              Nave
            </th>
            {#each columns as col (col.key)}
              <th class="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-muted border-b border-surface-border min-w-[120px]">
                {col.label}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each pagedNaves as nave, ni (nave.id)}
            <tr
              style:background-color={rowBg(ni, hoveredRow === ni)}
              onmouseenter={() => hoveredRow = ni}
              onmouseleave={() => hoveredRow = null}
            >
              <td
                class="sticky left-0 z-10 px-4 py-0 transition-colors duration-100"
                style:background-color={rowBg(ni, hoveredRow === ni)}
              >
                <a href={naveUrl(nave.id)} class="block py-3">
                  <p class="font-semibold text-navy text-[13px] leading-tight hover:underline">{nave.nombre}</p>
                  <p class="font-mono text-[10px] text-ink-muted mt-0.5">{nave.matricula}</p>
                </a>
              </td>

              {#each columns as col (col.key)}
                {@const cell = getCell(nave, col.key)}
                <td class="p-0.5 text-center align-middle">
                  {#if cell}
                    {#if cell.estado === 'en_curso'}
                      {@const u = urgency(cell.urgencia)}
                      <a
                        href={periodoUrl(nave.id, cell.periodo_id)}
                        class="cell-heat"
                        style:background-color={u.bg}
                        onmouseenter={(e) => showTooltip(e, cell, col)}
                        onmouseleave={hideTooltip}
                      >
                        {#if cell.fallos_nuevos > 0}
                          <span class="badge-nuevos">
                            <svg width="9" height="9" viewBox="0 0 8 8" fill="none">
                              <path d="M4 1L7 7H1L4 1Z" fill="#ea580c" stroke="#ea580c" stroke-width="0.5" stroke-linejoin="round"/>
                              <rect x="3.5" y="3.5" width="1" height="1.5" rx="0.5" fill="white"/>
                              <rect x="3.5" y="5.5" width="1" height="0.8" rx="0.4" fill="white"/>
                            </svg>
                            <span class="font-mono text-[10px] font-semibold text-orange-600 leading-none">{cell.fallos_nuevos}</span>
                          </span>
                        {/if}
                        <span class="font-mono font-medium text-[15px] leading-none text-white">
                          {Math.round(cell.cobertura * 100)}%
                        </span>
                      </a>

                    {:else}
                      <a href={periodoUrl(nave.id, cell.periodo_id)} class="flex flex-col items-center justify-center h-14 px-3 gap-1 hover:bg-neutral-bg">
                        <span class="flex items-center gap-1 text-ok">
                          <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                            <path d="M2.5 7L5.5 10L11.5 4" stroke="currentColor" stroke-width="1.8"
                                  stroke-linecap="round" stroke-linejoin="round"/>
                          </svg>
                          <span class="font-mono text-xs font-semibold">100%</span>
                        </span>
                        <span class="text-[10px] text-ink-muted font-mono">{cell.fecha_cierre}</span>
                      </a>
                    {/if}
                  {:else}
                    <div class="flex items-center justify-center h-14">
                      <span class="text-ink-muted opacity-25 text-sm select-none">—</span>
                    </div>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="border-t border-surface-border px-4 py-2.5 flex items-center justify-between bg-neutral-bg">
      <div class="flex items-center gap-3">
        <p class="text-[11px] text-ink-muted">
          {pagedNaves.length} de {naves.length} naves · {columns.length} periodicidades activas
        </p>
        {#if totalPages > 1}
        <div class="flex items-center gap-1">
          <button
            onclick={() => page = Math.max(1, page - 1)}
            disabled={page === 1}
            class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Anterior
          </button>
          <span class="inline-flex items-center rounded-md border border-navy bg-navy px-2.5 py-1 text-xs font-semibold text-white">
            {page}
          </span>
          <button
            onclick={() => page = Math.min(totalPages, page + 1)}
            disabled={page === totalPages}
            class="inline-flex items-center rounded-md border border-surface-border bg-white px-2.5 py-1 text-xs text-ink-secondary transition hover:bg-neutral-bg disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Siguiente
          </button>
        </div>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        {#if formulaVisible}
          <p class="text-[11px] text-ink-muted font-mono">urgencia = (1 − cob.) × (t. transcurrido / duración)</p>
        {/if}
        <div class="relative">
          <button
            class="info-btn"
            onmouseenter={() => formulaHover = true}
            onmouseleave={() => formulaHover = false}
            onclick={() => { formulaVisible = !formulaVisible; formulaHover = false }}
            aria-label="Ver fórmula de urgencia"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.2"/>
              <rect x="6.4" y="6" width="1.2" height="4.2" rx="0.6" fill="currentColor"/>
              <rect x="6.4" y="3.5" width="1.2" height="1.2" rx="0.6" fill="currentColor"/>
            </svg>
          </button>
          {#if formulaHover && !formulaVisible}
            <div class="formula-tooltip">
              urgencia = (1 − cob.) × (t. transcurrido / duración)
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Tooltip fixed: escapa del overflow container usando position fixed -->
{#if tooltip}
  {@const { cell, col } = tooltip}
  {@const u = urgency(cell.urgencia)}
  <div
    class="tooltip-fixed"
    style:left="{tooltip.left}px"
    style:bottom="{tooltip.bottom}px"
  >
    <p class="text-[10px] font-semibold uppercase tracking-wider text-ink-muted mb-2">
      {col.label} · EN CURSO
    </p>

    <!-- Progress bar (reemplaza el % que ya está en la celda) -->
    <div class="mb-3">
      <div class="prog-track">
        <div class="prog-fill" style:transform="scaleX({cell.cobertura})" style:background-color={u.bar}></div>
      </div>
      <div class="flex justify-between mt-1">
        <span class="text-[10px] text-ink-muted">Cobertura</span>
        <span class="text-[10px] font-mono font-medium {u.text}">{Math.round(cell.cobertura * 100)}%</span>
      </div>
    </div>

    <div class="space-y-1.5 border-t border-surface-border pt-2">
      <div class="flex justify-between text-xs">
        <span class="text-ink-secondary">Días restantes</span>
        <span class="font-mono font-medium text-ink">{cell.dias_restantes} / {cell.duracion_total}</span>
      </div>
      <div class="flex justify-between text-xs">
        <span class="text-ink-secondary">Urgencia</span>
        <span class="font-mono font-semibold {u.text}">{Math.round(cell.urgencia * 100)}%</span>
      </div>
      {#if cell.fallos > 0}
        <div class="flex text-xs border-t border-surface-border pt-1.5">
          <span class="text-fail font-semibold">{cell.fallos} fallo{cell.fallos > 1 ? 's' : ''} detectado{cell.fallos > 1 ? 's' : ''}</span>
        </div>
      {/if}
      {#if cell.fallos_nuevos > 0}
        <div class="flex text-xs">
          <span class="text-warn font-semibold">{cell.fallos_nuevos} nuevo{cell.fallos_nuevos > 1 ? 's' : ''} este período</span>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* Celda heatmap — sin bar, solo color + valor */
  .cell-heat {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 3.5rem;
    padding-inline: 0.75rem;
    cursor: pointer;
    text-decoration: none;
    /* Borde blanco sutil entre celdas */
    outline: 1px solid rgba(255, 255, 255, 0.45);
    outline-offset: -1px;
  }

  /* Badge fallos nuevos */
  .badge-nuevos {
    position: absolute;
    top: 5px;
    right: 5px;
    display: flex;
    align-items: center;
    gap: 3px;
    border-radius: 4px;
    background: #fff7ed;
    border: 1px solid #fdba74;
    padding: 2px 5px;
  }

  /* Tooltip fixed — escapa overflow:auto */
  .tooltip-fixed {
    position: fixed;
    z-index: 9999;
    transform: translateX(-50%);
    width: 13rem;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
    background: #ffffff;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.10), 0 1px 4px rgb(0 0 0 / 0.06);
    padding: 0.75rem;
    pointer-events: none;
    font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
  }

  /* Info icon button */
  .info-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--color-ink-muted, #94a3b8);
    background: none;
    border: none;
    padding: 2px;
    cursor: pointer;
    border-radius: 4px;
    transition: color 120ms;
  }
  .info-btn:hover {
    color: var(--color-ink-secondary, #64748b);
  }

  /* Tooltip fórmula */
  .formula-tooltip {
    position: absolute;
    bottom: calc(100% + 6px);
    right: 0;
    white-space: nowrap;
    background: #1e293b;
    color: #e2e8f0;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    padding: 5px 8px;
    border-radius: 8px;
    pointer-events: none;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.18);
  }

  /* Progress bar en tooltip */
  .prog-track {
    position: relative;
    height: 6px;
    border-radius: 9999px;
    background: rgba(148, 163, 184, 0.2);
    overflow: hidden;
  }

  .prog-fill {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    transform-origin: left;
    transition: transform 150ms ease;
  }
</style>
