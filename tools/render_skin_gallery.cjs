// Local artifact QA only; not part of the app's runtime or game automation.
const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs');const path=require('path');const {pathToFileURL}=require('url');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(pathToFileURL(path.join(root,'styling/skin-gallery.html')).href);
  const count=await page.locator('.choice').count();if(count!==10)throw Error(`Expected 10 skins, got ${count}`);
  fs.mkdirSync(path.join(root,'styling/previews'),{recursive:true});
  for(let i=0;i<count;i++){
   await page.locator('.choice').nth(i).click();
   const name=await page.locator('#name').innerText();
   if(!name)throw Error('Empty selected skin');
   await page.locator('.workbench').screenshot({path:path.join(root,`styling/previews/skin-${String(i+1).padStart(2,'0')}.png`)});
  }
  await page.locator('.choice').nth(2).click();
  await page.screenshot({path:path.join(root,'styling/skin-gallery-overview.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(root,'analysis/skin-gallery-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(overflow)throw Error('Gallery overflows mobile viewport');
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Ten skin concepts rendered and selected; desktop/mobile layout and script checks passed. No game input.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
