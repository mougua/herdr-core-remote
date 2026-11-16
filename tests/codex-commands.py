"""Codex slash command palette; all APIs are simulated."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote
records=[{'address':'t1','agent':'codex','state':'live'},{'address':'t2','agent':None,'state':'live'},{'address':'t3','agent':'claude','state':'live'}]
data={'terminals':records,'spaces':[{'id':'s','name':'Workspace','tabs':[{'id':'tab','name':'Work','terminals':[{'terminal':t['address']} for t in records]}]}]}
actions=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 page=b.new_page(viewport={'width':1440,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def api(route):
  path=route.request.url.rsplit('/',1)[-1]
  if path=='snapshot':route.fulfill(json=data)
  elif path=='read':route.fulfill(json={'text':'Ready\nCodex command palette preview'})
  else:actions.append(route.request.post_data_json);route.fulfill(json={'ok':True})
 page.route('**/api/**',api)
 page.goto('http://127.0.0.1:'+str(remote.config()['port'])+'/#token=test')
 expect(page.locator('#slash-open')).to_be_visible()
 assert page.locator('[data-codex-key]').count()==0
 page.locator('#message').fill('keep this draft')
 page.locator('#slash-open').click()
 expect(page.locator('#slash-dialog')).to_be_visible()
 expect(page.locator('.slash-command')).to_have_count(9)
 page.locator('[data-command="/resume"]').click()
 expect(page.locator('#message')).to_have_value('/resume')
 assert not actions
 page.locator('#restore-draft').click()
 expect(page.locator('#message')).to_have_value('keep this draft')
 page.locator('#slash-open').click();page.locator('[data-command="/model"]').click()
 page.locator('#submit').click()
 expect(page.locator('#message')).to_have_value('')
 assert actions[-1]=={'address':'t1','action':'send','text':'/model'}
 page.locator('#restore-draft').click();expect(page.locator('#message')).to_have_value('keep this draft')
 page.locator('#slash-open').click()
 page.screenshot(path=str(remote.STATE/'codex-commands-desktop.png'))
 for width,height in [(390,844),(320,640)]:
  page.set_viewport_size({'width':width,'height':height})
  assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
  assert page.locator('#slash-dialog').evaluate('(s)=>s.scrollWidth<=s.clientWidth+1')
  for button in page.locator('.slash-command').all():assert button.bounding_box()['height']>=44
 page.set_viewport_size({'width':390,'height':844})
 page.screenshot(path=str(remote.STATE/'codex-commands-mobile.png'),animations='disabled')
 page.keyboard.press('Escape');expect(page.locator('#slash-dialog')).not_to_be_visible()
 page.set_viewport_size({'width':1440,'height':900})
 for address in ['t2','t3']:
  page.locator('.terminal-button[data-address='+address+']').click();expect(page.locator('#slash-open')).not_to_be_visible()
 page.locator('.terminal-button[data-address=t1]').click()
 records[0]['state']='finished'
 with page.expect_response('**/api/snapshot'):page.locator('#refresh').click()
 expect(page.locator('#slash-open')).to_be_disabled()
 assert not errors,errors
 print('PASS Codex-only commands, no auto-send, restore draft before/after send, exact payload, removed key buttons, finished state and mobile dialog layout')
 b.close()
