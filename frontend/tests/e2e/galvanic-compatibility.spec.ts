import { expect, test } from '@playwright/test';

test('galvanic compatibility surfaces coat-the-cathode warning on mitigation path', async ({ page }) => {
  await page.goto('/galvanic-compatibility');

  await expect(page.getByRole('heading', { name: 'Galvanic Compatibility' })).toBeVisible();
  await expect(page.getByText('Assessment Result')).toBeVisible();
  await expect(page.getByText('INCOMPATIBLE').first()).toBeVisible();

  await page.getByRole('slider').evaluate((element) => {
    const slider = element as HTMLInputElement;
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    valueSetter?.call(slider, '200');
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    slider.dispatchEvent(new Event('change', { bubbles: true }));
  });

  await expect(page.getByRole('heading', { name: 'Mitigation Path To Target' })).toBeVisible();
  await expect(page.getByText('Priority 1')).toBeVisible();
  await expect(page.getByText('Coat the cathodic member.')).toBeVisible();
  await expect(page.getByText('BoundState screening band')).toBeVisible();
});
