"""Browser regression for mixed agent, shell, finished and unavailable panes."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote
records=[{'address':'t1','agent':'codex','state':'live'}, {'address':'t2','agent':None,'state':'live'}, {'address':'t3','agent':None,'state':'finished'}, {'address':'t4','agent':None,'state':'unavailable'}]
data={'terminals':records,'spaces':[{'id':'s1','name':'Mixed','tabs':[{'id':'tab1','name':'One','terminals':[{'terminal':t['address']} for t in records]}]}]}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 page=b.new_page()
 reads=[]
 def api(route):
  if route.request.url.endswith('/snapshot'):route.fulfill(json=data)
  else:
   address=route.request.post_data_json.get('address');reads.append(address);route.fulfill(json={'text':'screen '+str(address)})
 page.route('**/api/**',api)
 page.goto('http://127.0.0.1:'+str(remote.config()['port'])+'/#token=test')
 expect(page.locator('.terminal-button')).to_have_count(4)
 expect(page.locator('#panes button')).to_have_count(4)
 page.locator('#panes button').nth(1).click()
 expect(page.locator('#screen')).to_contain_text('screen t2')
 assert not page.locator('#submit').is_disabled()
 page.locator('#panes button').nth(2).click()
 expect(page.locator('#screen')).to_contain_text('screen t3')
 assert page.locator('#submit').is_disabled()
 page.locator('#panes button').nth(3).click()
 expect(page.locator('#screen')).to_contain_text('暂未就绪')
 assert page.locator('#submit').is_disabled()
 assert 't4' not in reads
 page.locator('#agents-mode').click()
 expect(page.locator('.terminal-button')).to_have_count(4)
 print('PASS: agent, ordinary shell, finished and unavailable panes remain visible; only live panes accept input')
 b.close()
