export const aetherLinkError =
  'Invalid Aether link. Use aether://IP:port with supported MASQUE options.';
export const isAetherLink = (value: string) => /^aether:\/\//i.test(value.trim());

const options: Record<string, readonly string[]> = {
  protocol: ['masque'],
  scan: ['turbo', 'balanced', 'thorough', 'stealth', 'ironclad'],
  ip: ['v4', 'v6', 'both'],
  transport: ['h2', 'h3'],
  noize: ['off', 'light', 'firewall', 'balanced', 'gfw', 'aggressive'],
};

interface AetherLinkOutbound extends Record<string, unknown> {
  protocol: 'aether';
  tag: string;
  settings: { uri: string };
}

export function parseAetherLink(raw: string): AetherLinkOutbound | null {
  if (!isAetherLink(raw)) return null;
  const uri = raw.trim().replace(/^aether:/i, 'aether:');
  try {
    const u = new URL(uri);
    if (
      u.protocol !== 'aether:' ||
      u.username ||
      u.password ||
      u.pathname ||
      !u.hostname ||
      !u.port ||
      Number(u.port) > 65535 ||
      Number(u.port) < 1
    )
      return null;
    for (const [key, value] of u.searchParams) {
      if (!options[key]?.includes(value) || u.searchParams.getAll(key).length !== 1) return null;
    }
    return { protocol: 'aether', tag: decodeURIComponent(u.hash.slice(1)), settings: { uri } };
  } catch {
    return null;
  }
}
