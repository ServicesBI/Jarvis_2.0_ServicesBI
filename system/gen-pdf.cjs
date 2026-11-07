const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const os = require('os');

function findChrome() {
  const paths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(os.homedir(), 'AppData', 'Local', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ];
  for (const p of paths) {
    try { if (fs.existsSync(p)) return p; } catch {}
  }
  return null;
}

(async () => {
  const htmlPath = path.resolve(__dirname, 'guide-update.html');
  const pdfPath = 'C:/Users/Gamer/Downloads/Leia Me.pdf';
  const chromePath = findChrome();

  const launchOpts = {
    headless: true,
    pipe: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-setuid-sandbox']
  };
  if (chromePath) launchOpts.executablePath = chromePath;

  const browser = await puppeteer.launch(launchOpts);
  const page = await browser.newPage();
  await page.goto('file:///' + htmlPath.replace(/\\/g, '/'), { waitUntil: 'networkidle0' });
  await page.pdf({ path: pdfPath, format: 'A4', printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await browser.close();
  console.log('PDF gerado com sucesso em:', pdfPath);
})();
