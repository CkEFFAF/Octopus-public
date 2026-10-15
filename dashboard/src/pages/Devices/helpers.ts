import type { Device, DevicePermission } from "../../api/modules/devices";

export const permissionKeys: DevicePermission[] = [
  "desktop_view",
  "desktop_control",
  "files_read",
  "files_write",
  "command_exec",
  "acp_run",
];

export type DeviceWorkspaceView = "desktop" | "files" | "command";

export function workspaceView(
  value: string | null,
): DeviceWorkspaceView | null {
  return value === "desktop" || value === "files" || value === "command"
    ? value
    : null;
}

export function deviceWorkspaceUrl(
  id: string,
  view: DeviceWorkspaceView,
): string {
  return `/devices?${new URLSearchParams({ device: id, view })}`;
}

/** Opening an offline workspace is safe; execution still requires canUse. */
export function supportsWorkspaceView(
  device: Device,
  view: DeviceWorkspaceView,
): boolean {
  if (device.revoked_at !== null) return false;
  const permissions: DevicePermission[] =
    view === "desktop"
      ? ["desktop_view"]
      : view === "command"
      ? ["command_exec"]
      : ["files_read", "files_write"];
  return permissions.some(
    (permission) =>
      device.permissions.includes(permission) &&
      device.capabilities.includes(permission),
  );
}

export function canUse(
  device: Pick<
    Device,
    "online" | "revoked_at" | "capabilities" | "permissions"
  >,
  permission: DevicePermission,
): boolean {
  return (
    device.online &&
    device.revoked_at === null &&
    device.capabilities.includes(permission) &&
    device.permissions.includes(permission) &&
    (permission !== "desktop_control" || canUse(device, "desktop_view"))
  );
}

export function selectedDeviceId(devices: Device[], current: string): string {
  if (devices.some((device) => device.device_id === current)) return current;
  return (
    devices.find((device) => device.revoked_at === null)?.device_id ??
    devices[0]?.device_id ??
    ""
  );
}

export function desktopPoint(
  clientX: number,
  clientY: number,
  bounds: { left: number; top: number; width: number; height: number },
  screen: { width: number; height: number; left?: number; top?: number },
): { x: number; y: number } | null {
  if (
    bounds.width <= 0 ||
    bounds.height <= 0 ||
    screen.width <= 0 ||
    screen.height <= 0 ||
    clientX < bounds.left ||
    clientY < bounds.top ||
    clientX > bounds.left + bounds.width ||
    clientY > bounds.top + bounds.height
  )
    return null;
  return {
    x:
      (screen.left ?? 0) +
      Math.min(
        screen.width - 1,
        Math.floor(((clientX - bounds.left) / bounds.width) * screen.width),
      ),
    y:
      (screen.top ?? 0) +
      Math.min(
        screen.height - 1,
        Math.floor(((clientY - bounds.top) / bounds.height) * screen.height),
      ),
  };
}

export function parentPath(path: string): string {
  return path.split("/").slice(0, -1).join("/");
}

export function joinPath(path: string, name: string): string {
  return [path, name].filter(Boolean).join("/");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}

export function base64ToBytes(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) return sha256Portable(bytes);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** Checksum fallback for explicit LAN HTTP, where mobile browsers lack SubtleCrypto. */
export function sha256Portable(bytes: Uint8Array): string {
  const primes: number[] = [];
  for (let n = 2; primes.length < 64; n++) {
    if (primes.every((p) => p * p > n || n % p !== 0)) primes.push(n);
  }
  const fraction = (n: number) =>
    Math.floor((n - Math.floor(n)) * 0x100000000) >>> 0;
  const constants = primes.map((p) => fraction(Math.cbrt(p)));
  const hash = primes.slice(0, 8).map((p) => fraction(Math.sqrt(p)));
  const padded = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(bytes.length / 0x20000000));
  view.setUint32(padded.length - 4, (bytes.length * 8) >>> 0);
  const rotate = (v: number, n: number) => (v >>> n) | (v << (32 - n));
  const words = new Uint32Array(64);
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i++) words[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = words[i - 15],
        b = words[i - 2];
      words[i] =
        (words[i - 16] +
          (rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3)) +
          words[i - 7] +
          (rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10))) >>>
        0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let i = 0; i < 64; i++) {
      const sum =
        (h +
          (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) +
          ((e & f) ^ (~e & g)) +
          constants[i] +
          words[i]) >>>
        0;
      const second =
        ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) +
          ((a & b) ^ (a & c) ^ (b & c))) >>>
        0;
      h = g;
      g = f;
      f = e;
      e = (d + sum) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (sum + second) >>> 0;
    }
    [a, b, c, d, e, f, g, h].forEach((word, i) => {
      hash[i] = (hash[i] + word) >>> 0;
    });
  }
  return hash.map((v) => v.toString(16).padStart(8, "0")).join("");
}
