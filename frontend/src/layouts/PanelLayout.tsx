import { isDelegatedPanel } from '@/lib/panel-access';
import { Outlet } from 'react-router';

import { useWebSocketBridge } from '@/api/websocketBridge';
import { usePageTitle } from '@/hooks/usePageTitle';
import CommandPalette from '@/components/command-palette/CommandPalette';

function MasterTools() {
  useWebSocketBridge();
  return <CommandPalette />;
}

export default function PanelLayout() {
  usePageTitle();
  return (
    <>
      <Outlet />
      {!isDelegatedPanel && <MasterTools />}
    </>
  );
}
