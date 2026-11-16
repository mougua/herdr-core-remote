"""Optional browser regression checks; requires Playwright and installed Chrome.
Run with the local service started: python tests/ui-smoke.py
All API responses are simulated; no existing terminals are read or changed.
"""
import asyncio
import json
from pathlib import Path
import sys
from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote

TERMINALS = [{'address': 't'+str(i), 'agent': 'codex', 'cwd': 'D:/project-'+str(i), 'state':'live', 'status':'blocked' if i==3 else 'idle'} for i in range(1,4)]
SNAPSHOT = {'terminals': TERMINALS, 'warning': None, 'spaces': [
    {'id':'s1','name':'Alpha','tabs':[{'id':'tab1','name':'Build','terminals':[{'terminal':'t1'},{'terminal':'t2'}]}]},
    {'id':'s2','name':'Beta','tabs':[{'id':'tab2','name':'Review','terminals':[{'terminal':'t3'}]}]}
]}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        page = await browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def route_api(route):
            body = route.request.post_data_json
            if route.request.url.endswith('/snapshot'):
                result=SNAPSHOT
            elif route.request.url.endswith('/read'):
                await asyncio.sleep(.6)  # slow network, including prefetches
                result={'text':'SCREEN '+body['address']+'\n'+'Output line\n'*24}
            else:
                result={'ok':True}
            await route.fulfill(json=result)
        await page.route('**/api/**', route_api)
        await page.goto('http://127.0.0.1:'+str(remote.config()['port'])+'/#token=test-token')
        await expect(page.locator('.space-button')).to_have_count(2)
        await expect(page.locator('#screen')).to_contain_text('SCREEN t1')
        await page.locator('#agents-mode').click()
        # Confirm priority order, and allow the prefetched screen to arrive.
        await expect(page.locator('.terminal-button').first).to_contain_text('需要你')
        await page.locator('.terminal-button').filter(has=page.locator('.label')).nth(1).click()
        await page.locator('#message').fill('draft alpha')
        await page.locator('.terminal-button').first.click()
        await expect(page.locator('#screen')).to_contain_text('SCREEN t3')
        # Cache is already warm. Measure immediate DOM update, before network returns.
        result = await page.evaluate("""() => {
            const start=performance.now();
            const buttons=[...document.querySelectorAll('.terminal-button')];
            buttons.find(b=>b.dataset.address==='t1').click();
            return {ms:performance.now()-start, text:document.querySelector('#screen').textContent};
        }""")
        assert 'SCREEN t1' in result['text'], result
        assert result['ms'] < 100, result
        await expect(page.locator('#message')).to_have_value('draft alpha')
        # Rapid switches: a late response must never overwrite the selected screen.
        await page.locator('.terminal-button').first.click()
        await page.locator('.terminal-button').last.click()
        await expect(page.locator('#screen')).to_contain_text('SCREEN t2')
        await page.locator('#search').fill('project-3')
        await expect(page.locator('.terminal-button')).to_have_count(1)
        await page.locator('#search').fill('')
        await page.screenshot(path=str(remote.STATE/'ui-desktop.png'))
        for width,height in [(390,844),(320,640),(768,1024)]:
            await page.set_viewport_size({'width':width,'height':height})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
        await page.set_viewport_size({'width':390,'height':844})
        await page.locator('#menu').click()
        await page.locator('#spaces-mode').click()
        await page.locator('.space-button').last.click()
        await expect(page.locator('#menu')).to_have_attribute('aria-expanded','false')
        await expect(page.locator('#screen')).to_contain_text('SCREEN t3')
        await expect(page.locator('.wrap-indicator')).to_be_visible()
        await page.screenshot(path=str(remote.STATE/'ui-mobile.png'), animations='disabled')
        await page.locator('#logout').click()
        await expect(page.locator('#login')).to_be_visible()
        assert not errors, errors
        print('PASS: spaces/tabs/panes, agent priority, per-terminal drafts, search, rapid switches, mobile widths, logout')
        print('Cached switch %.1f ms with 600 ms simulated read latency' % result['ms'])
        await browser.close()

asyncio.run(main())
