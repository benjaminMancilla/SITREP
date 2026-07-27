<script>
  import IconKebab from './icons/IconKebab.svelte'

  /**
   * @typedef {Object} RowAction
   * @property {string} label
   * @property {string} [href]
   * @property {() => void} [onclick]
   * @property {'default'|'danger'} [variant]
   */

  /** @type {{ actions: RowAction[], label?: string }} */
  let { actions = [], label = 'Más acciones' } = $props()

  let open = $state(false)
  let triggerEl = $state(null)
  let pos = $state({ top: 0, left: 0 })

  function toggle() {
    if (open) {
      close()
      return
    }
    const rect = triggerEl.getBoundingClientRect()
    pos = { top: rect.bottom + 4, left: rect.right }
    open = true
  }

  function close() {
    open = false
  }

  function runAction(action) {
    close()
    action.onclick?.()
  }

  function onWindowKeydown(e) {
    if (e.key === 'Escape') close()
  }

  function onClickOutside(e) {
    if (triggerEl?.contains(e.target)) return
    close()
  }
</script>

<svelte:window
  onkeydown={open ? onWindowKeydown : undefined}
  onscroll={open ? close : undefined}
  onresize={open ? close : undefined}
/>

<div class="relative inline-block">
  <button
    bind:this={triggerEl}
    type="button"
    onclick={toggle}
    aria-haspopup="true"
    aria-expanded={open}
    aria-label={label}
    class="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-muted transition hover:bg-neutral-bg hover:text-ink-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
  >
    <IconKebab />
  </button>
</div>

{#if open}
  <div class="fixed inset-0 z-40" onclick={onClickOutside} aria-hidden="true"></div>
  <div
    role="menu"
    class="fixed z-40 min-w-[160px] -translate-x-full rounded-md border border-surface-border bg-white py-1 shadow-[0_4px_16px_rgb(0_0_0_/_0.10),0_1px_4px_rgb(0_0_0_/_0.06)]"
    style:top="{pos.top}px"
    style:left="{pos.left}px"
  >
    {#each actions as action}
      <a
        role="menuitem"
        href={action.href ?? '#'}
        onclick={(e) => { if (!action.href) e.preventDefault(); runAction(action) }}
        class="block px-3 py-1.5 text-left text-[13px] font-medium transition"
        class:text-ink-secondary={action.variant !== 'danger'}
        class:hover:bg-neutral-bg={action.variant !== 'danger'}
        class:hover:text-ink={action.variant !== 'danger'}
        class:text-fail={action.variant === 'danger'}
        class:hover:bg-fail-bg={action.variant === 'danger'}
      >
        {action.label}
      </a>
    {/each}
  </div>
{/if}
