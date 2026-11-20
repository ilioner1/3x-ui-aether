export const isDelegatedPanel =
  typeof document !== 'undefined' &&
  document.querySelector('meta[name="x-ui-role"]')?.getAttribute('content') === 'delegate';

export const panelRoutePrefix = isDelegatedPanel ? '/delegate/panel' : '/panel';
