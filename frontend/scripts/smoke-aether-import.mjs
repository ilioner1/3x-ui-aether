import { chromium } from 'playwright';

const path = process.env.XUI_WEB_BASE_PATH.replace(/^\/+|\/+$/g, '');
const origin = `http://127.0.0.1:${process.env.XUI_PANEL_PORT}`;
const base = path ? `${origin}/${path}` : origin;
const uri = 'aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2';

const browser = await chromium.launch();
try {
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
  await page.getByRole('button', { name: 'more', exact: true }).first().click();
  await page.getByRole('menuitem', { name: 'Import Outbounds' }).click();
  const dialog = page.getByRole('dialog', { name: 'Import Outbounds' });
  await dialog.getByRole('textbox', { name: 'Import Outbounds' }).fill(uri);
  await dialog.getByRole('button', { name: 'Import Outbounds' }).click();
  await page.getByText('mokhaberaat2', { exact: true }).waitFor();

  const saved = page.waitForResponse((response) =>
    response.url().endsWith('/panel/api/xray/update') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  if (!(await saved).ok()) throw new Error('Panel rejected the imported outbound');
  console.log('Browser imported and saved the raw Aether URI');
} finally {
  await browser.close();
}
