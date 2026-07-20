<script>
  let { naves = [] } = $props()
  let tooltip = $state(null)

  const W = 560
  const H = 240
  const PAD = { l: 34, r: 16, t: 16, b: 26 }

  let maxVencidos = $derived(Math.max(3, ...naves.map((n) => n.vencidos)))

  function x(completitud) {
    return PAD.l + (completitud / 100) * (W - PAD.l - PAD.r)
  }
  function y(vencidos, max) {
    return H - PAD.b - (vencidos / max) * (H - PAD.t - PAD.b)
  }

  function band(n) {
    if (n.completitud >= 80 && n.vencidos <= 1) return '#15803d'
    if (n.completitud < 50 || n.vencidos >= 3) return '#b91c1c'
    return '#b45309'
  }

  function showTooltip(e, nave) {
    const rect = e.currentTarget.getBoundingClientRect()
    tooltip = { nave, left: rect.left + rect.width / 2, bottom: window.innerHeight - rect.top + 8 }
  }
  const hideTooltip = () => tooltip = null
</script>

<div class="rounded-lg border border-surface-border bg-white">
  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-4 py-3">
    <div>
      <h2 class="text-[15px] font-bold text-navy">Métricas de Confiabilidad</h2>
      <p class="mt-0.5 text-[11px] text-ink-muted">Completitud vs. períodos vencidos, por nave</p>
    </div>
    <div class="flex items-center gap-3 text-[10px] text-ink-muted">
      <span class="flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#15803d"></span>Estable</span>
      <span class="flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#b45309"></span>Atención</span>
      <span class="flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#b91c1c"></span>Crítico</span>
    </div>
  </div>

  {#if naves.length === 0}
    <div class="px-4 py-8 text-center text-[13px] text-ink-muted">No hay naves para mostrar.</div>
  {:else}
    <div class="px-4 py-4">
      <svg viewBox="0 0 {W} {H}" class="w-full" style="max-height: 260px" role="img" aria-label="Gráfico de dispersión: completitud vs períodos vencidos por nave">
        <rect x={PAD.l} y={PAD.t} width={(W - PAD.l - PAD.r) / 2} height={(H - PAD.t - PAD.b) / 2} fill="#fef2f2" opacity="0.5" />
        <rect
          x={PAD.l + (W - PAD.l - PAD.r) / 2}
          y={H - PAD.b - (H - PAD.t - PAD.b) / 2}
          width={(W - PAD.l - PAD.r) / 2}
          height={(H - PAD.t - PAD.b) / 2}
          fill="#f0fdf4"
          opacity="0.5"
        />

        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} stroke="#e2e8f0" stroke-width="1" />
        <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} stroke="#e2e8f0" stroke-width="1" />

        {#each [0, 1, 2, 3] as t}
          <text x={PAD.l - 6} y={y((t / 3) * maxVencidos, maxVencidos) + 3} text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="9" fill="#94a3b8">
            {Math.round((t / 3) * maxVencidos)}
          </text>
        {/each}
        {#each [0, 50, 100] as t}
          <text x={x(t)} y={H - PAD.b + 14} text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="9" fill="#94a3b8">
            {t}%
          </text>
        {/each}

        {#each naves as n (n.id)}
          <circle
            cx={x(n.completitud)}
            cy={y(n.vencidos, maxVencidos)}
            r={tooltip?.nave?.id === n.id ? 6 : 4.5}
            fill={band(n)}
            fill-opacity="0.85"
            stroke="white"
            stroke-width="1.5"
            class="cursor-default transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
            role="button"
            tabindex="0"
            aria-label={`${n.nombre}: ${n.completitud}% completitud, ${n.vencidos} vencido${n.vencidos === 1 ? '' : 's'}`}
            onmouseenter={(e) => showTooltip(e, n)}
            onmouseleave={hideTooltip}
            onfocus={(e) => showTooltip(e, n)}
            onblur={hideTooltip}
          />
        {/each}
      </svg>

      <div class="mt-1 flex justify-between px-1 font-mono text-[10px] text-ink-muted">
        <span>Completitud (%)</span>
        <span>Períodos vencidos ↑</span>
      </div>
    </div>
  {/if}
</div>

{#if tooltip}
  <div class="tooltip-fixed" style:left="{tooltip.left}px" style:bottom="{tooltip.bottom}px">
    <p class="text-[11px] font-semibold text-navy">{tooltip.nave.nombre}</p>
    <p class="mt-0.5 font-mono text-[10px] text-ink-muted">
      {tooltip.nave.completitud}% completitud · {tooltip.nave.vencidos} vencido{tooltip.nave.vencidos === 1 ? '' : 's'}
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
