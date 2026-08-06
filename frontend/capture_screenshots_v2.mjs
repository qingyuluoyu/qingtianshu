import { chromium } from "playwright";

const FRONTEND = "http://localhost:5173";
const BACKEND = "http://localhost:8000";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Navigate to login page
  console.log("Navigating to login page...");
  await page.goto(`${FRONTEND}/today`);
  await page.waitForTimeout(2000);

  // Take screenshot of login page
  await page.screenshot({
    path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-login.png",
    fullPage: true,
  });
  console.log("Login page screenshot saved");

  // Try to login via the auth modal
  // The frontend uses a modal for login, let's try to find and fill the form
  console.log("Page title:", await page.title());
  console.log("Page URL:", page.url());

  // Check if there's a login form visible
  const loginButton = await page.$('button:has-text("登录")');
  if (loginButton) {
    console.log("Found login button, clicking...");
    await loginButton.click();
    await page.waitForTimeout(1000);

    // Fill in credentials
    const accountInput = await page.$('input[name="login"], input[placeholder*="账号"], input[placeholder*="手机"]');
    const passwordInput = await page.$('input[name="password"], input[type="password"]');

    if (accountInput && passwordInput) {
      await accountInput.fill("verification-user");
      await passwordInput.fill("Password-123");

      // Submit
      const submitButton = await page.$('button[type="submit"]');
      if (submitButton) {
        await submitButton.click();
        await page.waitForTimeout(3000);

        // Take screenshot after login
        await page.screenshot({
          path: "C:/Users/dazhu/AppData/Local/Temp/screenshot-after-login.png",
          fullPage: true,
        });
        console.log("After login screenshot saved");
      }
    }
  } else {
    console.log("No login button found, page might already be authenticated");
  }

  await browser.close();
}

main().catch(console.error);
