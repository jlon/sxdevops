import puppeteer from 'puppeteer';

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox']
  });
  const page = await browser.newPage();
  
  page.on('console', msg => {
    console.log(`[BROWSER CONSOLE] ${msg.type()}: ${msg.text()}`);
  });
  
  page.on('pageerror', err => {
    console.log(`[BROWSER ERROR]: ${err.message}`);
  });
  
  try {
    await page.goto('http://localhost:3000/containers/docker', { waitUntil: 'networkidle2', timeout: 10000 });
    console.log('Page loaded.');
  } catch (e) {
    console.log('[PUPPETEER EXCEPTION]:', e.message);
  }
  
  await new Promise(r => setTimeout(r, 2000));
  await browser.close();
})();
