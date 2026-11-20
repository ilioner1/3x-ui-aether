import { chromium } from 'playwright';

const path = process.env.XUI_WEB_BASE_PATH.replace(/^\/+|\/+$/g, '');
const origin = `http://127.0.0.1:${process.env.XUI_PANEL_PORT}`;
const base = path ? `${origin}/${path}` : origin;
const uri = 'aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2';

const browser = await chromium.launch();
try {
  const delegate = await browser.newPage({ locale: 'en-US' });
  delegate.setDefaultTimeout(25000);
  delegate.on('pageerror', (error) => console.error('Delegate page error:', error.message));
  delegate.on('response', (response) => {
    const path = new URL(response.url()).pathname;
    if (response.status() >= 400 && path.includes('/delegate/api/')) {
      console.error('Delegate API response:', response.status(), path.split('/delegate/api/')[1]);
    }
  });
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
  const forbidden = await delegate.request.post(`${base}/panel/api/server/restartXrayService`, {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    maxRedirects: 0,
  });
  if (![401, 403, 404].includes(forbidden.status())) {
    throw new Error('Delegate reached the master restart endpoint');
  }
  await delegate.goto(`${base}/delegate/panel/inbounds`);
  await delegate.getByText('Delegated smoke VLESS', { exact: true }).first().waitFor();
  if (await delegate.getByRole('button', { name: 'Add Inbound', exact: true }).count()) {
    throw new Error('Delegate could see the Add Inbound action');
  }
  await delegate.goto(`${base}/delegate/panel/clients`);
  await delegate.getByText('delegated-live-client', { exact: true }).first().waitFor();
  await delegate.getByRole('button', { name: 'Add Clients', exact: true }).click();
  const clientForm = delegate.getByRole('dialog');
  await clientForm.getByRole('textbox').first().fill('delegated-browser-client');
  await clientForm.getByRole('button', { name: 'Select all', exact: true }).click();
  await clientForm.getByRole('spinbutton').fill('1');
  const created = delegate.waitForResponse((response) =>
    response.url().endsWith('/delegate/api/clients/add') && response.request().method() === 'POST',
  );
  await clientForm.getByRole('button', { name: 'Create', exact: true }).click();
  const createResponse = await created;
  const result = await createResponse.json();
  const submitted = createResponse.request().postDataJSON();
  if (!result.success || !result.obj?.subscriptionUrl || submitted.inboundIds.length !== 2) {
    throw new Error('Delegate select-all form did not create a subscription for both assigned inbounds');
  }
  const subscription = delegate.getByRole('dialog', { name: 'Subscription info' });
  await subscription.getByText(result.obj.subscriptionUrl, { exact: true }).waitFor();
  await subscription.getByRole('button', { name: 'OK', exact: true }).click();
  const clientRow = delegate.getByRole('row').filter({ hasText: 'delegated-browser-client' });
  const enabled = clientRow.getByRole('switch');
  await enabled.waitFor();
  const disabled = delegate.waitForResponse((response) =>
    response.url().includes('/delegate/api/clients/update') && response.request().method() === 'POST',
  );
  await enabled.click();
  if (!(await (await disabled).json()).success) throw new Error('Delegate could not disable its client');
  console.log('Browser verified the delegated x-ui pages, client form and restricted navigation');
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

  await page.goto(`${base}/panel/admins`);
  await page.getByRole('button', { name: 'Add admin' }).waitFor();
  await page.getByRole('button', { name: 'Edit group' }).first().click();
  const groupForm = page.getByRole('dialog', { name: 'Edit group' });
  const groupSaved = page.waitForResponse((response) =>
    response.url().endsWith('/panel/delegated-admins/group') && response.request().method() === 'POST',
  );
  await groupForm.getByRole('button', { name: 'Save', exact: true }).click();
  if (!(await (await groupSaved).json()).success) throw new Error('Native admin group edit failed');

  await page.goto(`${base}/panel/admins-reports`);
  const adminRow = page.getByRole('row').filter({ hasText: 'smoke-delegate' });
  await adminRow.getByRole('button', { name: 'Edit', exact: true }).click();
  const adminForm = page.getByRole('dialog', { name: 'Edit admin' });
  await adminForm.getByRole('spinbutton', { name: 'Quota (GiB)' }).fill('3');
  const quotaSaved = page.waitForResponse((response) =>
    response.url().endsWith('/panel/delegated-admins/account') && response.request().method() === 'POST',
  );
  await adminForm.getByRole('button', { name: 'Save', exact: true }).click();
  if (!(await (await quotaSaved).json()).success) throw new Error('Native admin quota edit failed');
  await adminForm.waitFor({ state: 'hidden' });
  await adminRow.getByRole('link', { name: 'Clients', exact: true }).click();
  await page.getByRole('row').filter({ hasText: 'delegated-live-client' }).waitFor();
  await page.goto(`${base}/panel/clients`);
  const masterList = await page.request.get(`${base}/panel/api/clients/list/paged?scope=master`);
  if ((await masterList.json()).obj.items.some((item) => item.comment === 'delegated-live-client')) {
    throw new Error('Master clients scope included a delegated client');
  }
  console.log('Browser verified native admin management, reports, quota edits and scoped clients');

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
