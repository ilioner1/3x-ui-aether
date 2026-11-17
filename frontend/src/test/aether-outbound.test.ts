import { describe, expect, it } from 'vitest';
import { parseOutboundLink } from '@/lib/xray/outbound-link-parser';
import { rawOutboundToFormValues, formValuesToWirePayload } from '@/lib/xray/outbound-form-adapter';

describe('Aether outbound import', () => {
  it('keeps the URI through import, form editing and serialization', () => {
    const uri = 'aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2';
    const parsed = parseOutboundLink(uri);
    expect(parsed).toEqual({ protocol: 'aether', tag: 'mokhaberaat2', settings: { uri } });
    const form = rawOutboundToFormValues(parsed);
    expect(formValuesToWirePayload(form)).toMatchObject(parsed!);
  });
});
