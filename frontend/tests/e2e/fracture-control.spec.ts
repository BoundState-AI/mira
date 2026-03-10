import { expect, test } from '@playwright/test';

test('fracture control page classifies a fracture-critical metallic part', async ({ page }) => {
  await page.goto('/fracture-control');

  await expect(page.getByRole('heading', { name: 'Fracture Control' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Assessment Inputs' })).toBeVisible();

  await page.getByLabel('Part Name').fill('Primary bracket');
  await page.getByLabel('Material').fill('Ti-6Al-4V');
  await page.getByRole('button', { name: 'Run Fracture Screen' }).click();

  await expect(page.getByText('Assessment Result')).toBeVisible();
  await expect(page.getByText('FC_METALLIC_GENERAL')).toBeVisible();
  await expect(page.getByText('10, 12, 15, 16, 21, 22, 23, 24, 25')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Required Actions' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Applicable FCRs' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Material Findings' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Authority Pack' })).toBeVisible();
});

test('fracture control can show indeterminate fallback for unresolved inputs', async ({ page }) => {
  await page.goto('/fracture-control');

  await page.getByLabel('Part Name').fill('Unknown bracket');
  await page.getByRole('combobox').nth(1).click();
  await page.getByRole('option', { name: 'Unknown' }).click();
  await page.getByRole('combobox').nth(2).click();
  await page.getByRole('option', { name: 'Unknown' }).click();
  await page.getByRole('button', { name: 'Run Fracture Screen' }).click();

  await expect(page.getByText('INDETERMINATE').first()).toBeVisible();
  await expect(page.getByText('Treat as FC pending review')).toBeVisible();
  await expect(page.getByText('hazard_consequence')).toBeVisible();
  await expect(page.getByText('load_path_type')).toBeVisible();
});
