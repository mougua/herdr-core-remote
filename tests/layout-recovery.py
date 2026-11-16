"""Regression: wrapping, hierarchy, friendly labels and automatic recovery."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote
state={'read_error':False,'nav_error':False,'action_error':False}
data={'terminals':[{'address':'t2n','agent':'codex','state':'live','status':'idle'},{'address':'t3n','agent':'codex','state':'live'}], 'spaces':[{'id':'s','name':'Orders','tabs':[{'id':'tab','name':'Build','terminals':[{'terminal':'t2n'},{'terminal':'t3n'}]}]}]}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 page=b.new_page(viewport={'width':1440,'height':900})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def api(route):
  path=route.request.url.rsplit('/',1)[-1]
  if path=='snapshot':
   route.fulfill(status=503,json={'error':'navigation offline'}) if state['nav_error'] else route.fulfill(json=data)
  elif path=='read':
   route.fulfill(status=503,json={'error':'screen offline'}) if state['read_error'] else route.fulfill(json={'text':('https://example.com/'+ 'longword'*500)+'\n'+('table    '*200)})
  else:route.fulfill(status=400,json={'error':'action denied'})
 page.route('**/api/**',api)
 page.goto('http://127.0.0.1:'+str(remote.config()['port'])+'/#token=test')
 expect(page.locator('#screen')).to_contain_text('longword')
 expect(page.locator('#title')).to_have_text('codex · 终端 1')
 expect(page.locator('#title')).not_to_contain_text('t2n')
 expect(page.locator('.space-terminals .terminal-button')).to_have_count(2)
 for width,height in [(1440,900),(390,844),(320,640)]:
  page.set_viewport_size({'width':width,'height':height})
  assert page.locator('#screen').evaluate('(s)=>s.scrollWidth<=s.clientWidth+1')
  assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
 page.set_viewport_size({'width':1440,'height':900})
 state['read_error']=True
 expect(page.locator('#error')).to_contain_text('screen offline',timeout=8000)
 state['read_error']=False
 expect(page.locator('#error')).to_be_hidden(timeout=8000)
 expect(page.locator('#connection')).to_contain_text('已连接')
 state['nav_error']=True
 expect(page.locator('#error')).to_contain_text('navigation offline',timeout=10000)
 state['nav_error']=False
 expect(page.locator('#error')).to_be_hidden(timeout=10000)
 page.locator('#message').fill('test')
 page.locator('#submit').click()
 expect(page.locator('#error')).to_contain_text('action denied')
 # A successful automatic read must preserve the separate operation error.
 with page.expect_response('**/api/read'):pass
 expect(page.locator('#error')).to_contain_text('action denied')
 assert not errors,errors
 page.screenshot(path=str(remote.STATE/'layout-recovery-desktop.png'))
 page.set_viewport_size({'width':390,'height':844})
 page.screenshot(path=str(remote.STATE/'layout-recovery-mobile.png'), animations='disabled')
 print('PASS: no horizontal screen overflow at 3 widths; hierarchy and friendly labels; automatic screen/navigation recovery; action errors preserved')
 b.close()
