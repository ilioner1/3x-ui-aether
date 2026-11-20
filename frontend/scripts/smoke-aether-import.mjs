import { chromium } from 'playwright';

const path = process.env.XUI_WEB_BASE_PATH.replace(/^\/+|\/+$/g, '');
const origin = `http://127.0.0.1:${process.env.XUI_PANEL_PORT}`;
const base = path ? `${origin}/${path}` : origin;
const uri = 'aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2';

const browser = await chromium.launch();
try {
  const delegate = await browser.newPage({ locale: 'en-US' });
  delegate.setDefaultTimeout(15000);
  await delegate.goto(`${base}/delegate/?account=smoke-delegate`);
  const username = delegate.locator('[autocomplete="username"]');
  await username.waitFor();
  if ((await username.inputValue()) !== 'smoke-delegate') throw new Error('Delegate login name was not prefilled');
  await delegate.locator('[autocomplete="current-password"]').fill('integration-delegate-only');
  await Promise.all([
    delegate.waitForURL('**/delegate/panel/'),
    delegate.locator('button[type="submit"]').click(),
  ]);
  await delegate.getByRole('menuitem', { name: 'Overview', exact: true }).first().waitFor();
  for (const name of ['Outbounds', 'Settings', 'Admins']) {
    if (await delegate.getByRole('menuitem', { name, exact: true }).count()) {
      throw new Error(`Restricted menu displayed ${name}`);
    }
  }
  await delegate.goto(`${base}/delegate/panel/inbounds`);
  await delegate.getByText('Delegated smoke VLESS', { exact: true }).first().waitFor();
  if (await delegate.getByRole('button', { name: 'Add Inbound', exact: true }).count()) {
    throw new Error('Delegate could see the Add Inbound action');
  }
  await delegate.goto(`${base}/delegate/panel/clients`);
  await delegate.getByText('delegated-live-client', { exact: true }).first().waitFor();
  console.log('Browser verified the delegated x-ui pages and restricted navigation');
  await delegate.close();

  const page = await browser.newPage({ locale: 'en-US' });
  page.setDefaultTimeout(15000);
  await page.goto(`${base}/`);
  await page.locator('[autocomplete="username"]').fill(process.env.XUI_USERNAME);
  await page.locator('[autocomplete="current-password"]').fill(process.env.XUI_PASSWORD);
  await Promise.all([
    page.waitForURL('**/panel/'),
    page.locator('button[type="submit"]').click(),
  ]);

  await page.goto(`${base}/panel/xray#outbound`);
  async function importLink(link, tag) {
    await page.getByRole('button', { name: 'more', exact: true }).first().click();
    await page.getByRole('menuitem', { name: 'Import Outbounds' }).click();
    const dialog = page.getByRole('dialog', { name: 'Import Outbounds' });
    await dialog.getByRole('textbox', { name: 'Import Outbounds' }).fill(link);
    await dialog.getByRole('button', { name: 'Import Outbounds' }).click();
    await page.getByText(tag, { exact: true }).waitFor();
  }

  await importLink(
    'aether://162.159.199.111:1701?protocol=masque&scan=thorough&ip=v4&transport=h2&psiphon=chain&psiphon_mode=auto&region=IN#mokhaberaat',
    'mokhaberaat',
  );
  console.log('Browser accepted the exact Psiphon chain URI');
  await page.reload();
  await importLink(uri, 'mokhaberaat2');

  const saved = page.waitForResponse((response) =>
    response.url().endsWith('/panel/api/xray/update') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  if (!(await saved).ok()) throw new Error('Panel rejected the imported outbound');
  console.log('Browser imported and saved the raw Aether URI');
} finally {
  await browser.close();
}
