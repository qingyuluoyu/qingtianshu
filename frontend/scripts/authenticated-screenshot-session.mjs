function normalizeFrontend(frontend) {
  return frontend.replace(/\/$/, "");
}

export function createScreenshotCredentials() {
  const nonce = `${Date.now()}${Math.floor(Math.random() * 1_000_000)}`.slice(-18);
  return {
    account: `shot-${nonce}`.slice(0, 32),
    phone: `13${Math.floor(Math.random() * 1_000_000_000).toString().padStart(9, "0")}`,
    password: `Screenshot-${nonce}-2026`,
  };
}

export async function ensureAuthenticatedScreenshotSession(context, { frontend, account, phone, password }) {
  const origin = normalizeFrontend(frontend);
  const registration = await context.request.post(`${origin}/auth/register`, {
    data: { account, phone, password },
  });
  if (!registration.ok()) {
    throw new Error(`Screenshot registration failed with HTTP ${registration.status()}.`);
  }

  const status = await context.request.get(`${origin}/session/status`);
  if (!status.ok()) {
    throw new Error(`Screenshot session/status failed with HTTP ${status.status()}.`);
  }
  const payload = await status.json();
  if (payload?.authenticated !== true) {
    throw new Error("Screenshot session/status did not establish an authenticated session.");
  }
}
