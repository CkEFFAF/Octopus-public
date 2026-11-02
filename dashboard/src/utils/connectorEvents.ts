export const CONNECTORS_CHANGED_EVENT = "octop:connectors-changed";

export function notifyConnectorsChanged(): void {
  window.dispatchEvent(new CustomEvent(CONNECTORS_CHANGED_EVENT));
}
