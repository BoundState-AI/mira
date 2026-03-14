import { defineConfig, devices } from '@playwright/test';

const executablePath = process.env.PLAYWRIGHT_BROWSER_EXECUTABLE_PATH;
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8080';
const useLocalDevServer = /^https?:\/\/(127\.0\.0\.1|localhost):8080$/.test(baseURL);
const devServerCommand = process.platform === 'win32'
  ? 'set VITE_API_URL=/api&& npm run dev -- --host 127.0.0.1 --port 8080'
  : 'VITE_API_URL=/api npm run dev -- --host 127.0.0.1 --port 8080';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  testIdAttribute: 'data-testid',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: useLocalDevServer
    ? {
        command: devServerCommand,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      }
    : undefined,
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(executablePath ? { launchOptions: { executablePath } } : {}),
      },
    },
  ],
});
