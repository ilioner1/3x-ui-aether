import { z } from 'zod';
import { parseAetherLink } from '@/lib/xray/aether-link';

export const AetherOutboundSettingsSchema = z.object({
  uri: z
    .string()
    .min(1)
    .refine((uri) => parseAetherLink(uri) !== null),
});
export type AetherOutboundSettings = z.infer<typeof AetherOutboundSettingsSchema>;
