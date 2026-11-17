const options: Record<string, readonly string[]> = {
  protocol: ['masque'],
  scan: ['turbo', 'balanced', 'thorough', 'stealth', 'ironclad'],
  ip: ['v4', 'v6', 'both'],
  transport: ['h2', 'h3'],
  noize: ['off', 'light', 'firewall', 'balanced', 'gfw', 'aggressive'],
};

export function parseAetherLink(raw: string): Record<string, unknown> | null {
  const uri = raw.trim();
  try {
    const u = new URL(uri);
    if (u.protocol !== 'aether:' || u.username || u.password || u.pathname || !u.hostname || !u.port || Number(u.port) > 65535 || Number(u.port) < 1) return null;
    for (const [key, value] of u.searchParams) {
      if (!options[key]?.includes(value) || u.searchParams.getAll(key).length !== 1) return null;
    }
    return { protocol: 'aether', tag: decodeURIComponent(u.hash.slice(1)), settings: { uri } };
  } catch { return null; }
}
