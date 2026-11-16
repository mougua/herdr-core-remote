"""Creates and removes one owned Space to verify the real browser flow."""
import json, subprocess, uuid, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote
name='remote-ui-check-'+uuid.uuid4().hex[:6]
created=None
try:
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
  page=b.new_page();page.goto('http://127.0.0.1:'+str(remote.config()['port'])+'/#token='+remote.init_state());page.locator('#dashboard').wait_for(state='visible')
  page.locator('#new-space').click();page.locator('#space-name').fill(name);page.locator('#space-folder').fill(str(remote.ROOT))
  with page.expect_response('**/api/spaces/create') as response:page.locator('#space-create').click()
  created=response.value.json();assert response.value.status==200,created
  expect(page.locator('#space-dialog')).not_to_be_visible();expect(page.locator('#breadcrumb')).to_contain_text(name);expect(page.locator('#context-notice')).to_contain_text('尚未启动 Agent')
  assert not page.locator('#submit').is_disabled()
  print('PASS real browser creation; shell hint and composer available')
  with page.expect_response('**/api/terminals/create') as response:
   page.locator('.space:has(.space-button.selected) .add-terminal').click()
  added=response.value.json();assert response.value.status==200,added
  expect(page.locator('#title')).to_have_attribute('title','终端编号：'+added['terminal']+'（排查问题时使用）')
  expect(page.locator('#context-notice')).to_contain_text('尚未启动 Agent')
  state=remote.Core('hc').snapshot()
  space=next(s for s in state['spaces'] if s['id']==created['space'])
  assert any(t['terminal']==added['terminal'] for tab in space['tabs'] for t in tab['terminals'])
  assert len(space['tabs'])==2
  print('PASS new terminal created in the selected Space and selected in browser')
  data=remote.Core('hc').snapshot();data['spaces'].append({'id':'empty-test','name':'Empty','folder':str(remote.ROOT),'tabs':[]})
  page.route('**/api/snapshot',lambda route:route.fulfill(json=data))
  with page.expect_response('**/api/snapshot'):page.locator('#refresh').click()
  page.locator('.space-button').filter(has_text='Empty').click()
  expect(page.locator('#screen')).to_contain_text('暂无运行中的终端');assert page.locator('#submit').is_disabled()
  with page.expect_response('**/api/snapshot'):page.locator('#refresh').click()
  expect(page.locator('#breadcrumb')).to_contain_text('Empty');assert page.locator('#submit').is_disabled()
  print('PASS empty space stays selected after refresh; input disabled')
  b.close()
finally:
 if created and created.get('space'):
  r=subprocess.run(['herdr-app','do','space.close',json.dumps({'id':created['space'],'confirmed':True})],capture_output=True)
  print('Owned test space cleanup:',r.returncode)
