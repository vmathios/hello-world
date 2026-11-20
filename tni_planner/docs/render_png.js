const { chromium } = require('playwright');
(async () => {
  const [src, dst, w, h] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 2 });
  await p.goto('file://' + src); await p.screenshot({ path: dst }); await b.close();
})();
