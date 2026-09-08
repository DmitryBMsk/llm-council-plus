const { defineConfig } = require('./frontend/node_modules/@playwright/test');
const path = require('node:path');
const root = __dirname;
const python = process.env.E2E_PYTHON || path.join(root, '.venv/bin/python');
const backendPort = process.env.E2E_BACKEND_PORT || '18765';
const providerPort = process.env.E2E_PROVIDER_PORT || '18766';
const frontendPort = process.env.E2E_FRONTEND_PORT || '5175';

module.exports = defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'output/e2e-report' }]],
  outputDir: 'output/e2e-results',
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    { command: `"${python}" e2e/serve.py provider`, cwd: root,
      url: `http://127.0.0.1:${providerPort}/api/tags`, reuseExistingServer: false },
    { command: `"${python}" e2e/serve.py backend`, cwd: root,
      url: `http://127.0.0.1:${backendPort}/api/auth/status`, reuseExistingServer: false },
    { command: `"${python}" e2e/serve.py frontend`, cwd: root,
      url: `http://localhost:${frontendPort}`, reuseExistingServer: false },
  ],
});
