import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import OutboundsTab from '@/pages/xray/outbounds/OutboundsTab';
import type { SetTemplate, XraySettingsValue } from '@/hooks/useXraySetting';

import { renderWithProviders } from './test-utils';

function settingsWithHiddenLoopback(): XraySettingsValue {
  return {
    outbounds: [
      { tag: 'proxy-a', protocol: 'vmess' },
      { tag: '_bl_bal1', protocol: 'loopback' },
      { tag: 'proxy-b', protocol: 'vmess' },
    ],
  } as unknown as XraySettingsValue;
}

describe('OutboundsTab hidden-loopback index mapping', () => {
  it('imports a raw Aether URI through the Import Outbounds menu', async () => {
    const uri =
      'aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2';
    const settings = settingsWithHiddenLoopback();
    const setTemplateSettings = vi.fn<SetTemplate>((update) => {
      const next = typeof update === 'function' ? update(settings) : update;
      Object.assign(settings, next);
    });
    renderWithProviders(
      <QueryClientProvider client={new QueryClient()}>
        <OutboundsTab
          templateSettings={settings}
          setTemplateSettings={setTemplateSettings}
          outboundsTraffic={[]}
          outboundTestStates={{}}
          subscriptionTestStates={{}}
          testingAll={false}
          inboundTags={[]}
          isMobile={false}
          onResetTraffic={vi.fn()}
          onTest={vi.fn()}
          onTestSubscription={vi.fn()}
          onTestAll={vi.fn()}
          onShowWarp={vi.fn()}
          onShowNord={vi.fn()}
          onShowPia={vi.fn()}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /^more$/ })[0]);
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Import Outbounds' }));
    const dialog = await screen.findByRole('dialog', { name: 'Import Outbounds' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Import Outbounds' }), {
      target: { value: uri },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Import Outbounds' }));
    expect(setTemplateSettings).toHaveBeenCalled();
    expect(settings.outbounds).toContainEqual({
      protocol: 'aether',
      tag: 'mokhaberaat2',
      settings: { uri },
    });
  });

  it('probes the outbound at its real array index, not the positional row index', () => {
    const onTest = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    renderWithProviders(
      <QueryClientProvider client={queryClient}>
        <OutboundsTab
          templateSettings={settingsWithHiddenLoopback()}
          setTemplateSettings={vi.fn()}
          outboundsTraffic={[]}
          outboundTestStates={{}}
          subscriptionTestStates={{}}
          testingAll={false}
          inboundTags={[]}
          isMobile={false}
          onResetTraffic={vi.fn()}
          onTest={onTest}
          onTestSubscription={vi.fn()}
          onTestAll={vi.fn()}
          onShowWarp={vi.fn()}
          onShowNord={vi.fn()}
          onShowPia={vi.fn()}
        />
      </QueryClientProvider>,
    );

    const tbody = document.querySelector('.ant-table-tbody');
    const tableRows = tbody?.querySelectorAll('tr.ant-table-row') ?? [];
    expect(tableRows.length).toBe(2);

    const checkButton = tableRows[1].querySelector(
      'button[aria-label="Check"]',
    ) as HTMLButtonElement;
    fireEvent.click(checkButton);

    expect(onTest).toHaveBeenCalledTimes(1);
    expect(onTest.mock.calls[0][0]).toBe(2);
  });

  it('probes the real array index from the mobile card list as well', () => {
    const onTest = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    renderWithProviders(
      <QueryClientProvider client={queryClient}>
        <OutboundsTab
          templateSettings={settingsWithHiddenLoopback()}
          setTemplateSettings={vi.fn()}
          outboundsTraffic={[]}
          outboundTestStates={{}}
          subscriptionTestStates={{}}
          testingAll={false}
          inboundTags={[]}
          isMobile
          onResetTraffic={vi.fn()}
          onTest={onTest}
          onTestSubscription={vi.fn()}
          onTestAll={vi.fn()}
          onShowWarp={vi.fn()}
          onShowNord={vi.fn()}
          onShowPia={vi.fn()}
        />
      </QueryClientProvider>,
    );

    const cards = document.querySelectorAll('.outbound-card');
    expect(cards.length).toBe(2);

    const checkButton = cards[1].querySelector('button[aria-label="Check"]') as HTMLButtonElement;
    fireEvent.click(checkButton);

    expect(onTest).toHaveBeenCalledTimes(1);
    expect(onTest.mock.calls[0][0]).toBe(2);
  });
});
