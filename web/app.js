'use strict';
const $ = id => document.getElementById(id);
const names={working:'工作中',idle:'空闲',done:'已完成',blocked:'需要你',error:'异常',live:'运行中',finished:'已结束',unavailable:'暂未就绪'};
let token=sessionStorage.getItem('core-token')||'', selected=null, spaceId=null, mode='spaces';
let creatingSpace=false, creatingTerminal=false;
let snapshot={terminals:[],spaces:[]}, epoch=0, busy=false, loading=false, following=true;
const cache=new Map(), inflight=new Map(), drafts=new Map(), positions=new Map(), remembered=new Map();
const savedDrafts=new Map();
const fragment=new URLSearchParams(location.hash.slice(1));
if(fragment.has('token')){token=fragment.get('token');history.replaceState(null,'',location.pathname);}
const notices=new Map();
function paintNotices(){const message=notices.get('action')||notices.get('screen')||notices.get('navigation')||notices.get('layout')||'';$('error').textContent=message;$('error').hidden=!message;const connected=!!token&&!notices.has('screen')&&!notices.has('navigation');$('connection').classList.toggle('connected',connected);if(token)$('connection').textContent=connected?'已连接':'连接中断';}
function notify(message,kind='action'){if(message)notices.set(kind,message);else notices.delete(kind);paintNotices();}
function recovered(kind){notices.delete(kind);paintNotices();}

function loggedOut(){$('slash-dialog').close();savedDrafts.clear();notices.clear();paintNotices();$('space-dialog').close();epoch++;token='';sessionStorage.removeItem('core-token');cache.clear();inflight.clear();drafts.clear();positions.clear();remembered.clear();selected=null;snapshot={terminals:[],spaces:[]};$('dashboard').hidden=true;$('login').hidden=false;$('screen').textContent='';$('message').value='';$('connection').classList.remove('connected');$('connection').textContent='未连接';navOpen(false);}
async function api(path,data={}){
 const generation=epoch;
 const r=await fetch('/api/'+path,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data),cache:'no-store'});
 if(generation!==epoch)throw new Error('连接已变更');
 if(r.status===401){loggedOut();throw new Error('令牌已失效，请重新连接');}
 let result;try{result=await r.json();}catch{throw new Error('连接已中断，请检查 Cloudflare 登录状态并刷新页面');}
 if(!r.ok)throw new Error(result.error||'请求失败');return result;
}
function button(text,fn,cls=''){const b=document.createElement('button');b.textContent=text;b.className=cls;b.onclick=fn;return b;}
function terminal(id){return snapshot.terminals.find(t=>t.address===id);}
function locationOf(id){for(const s of snapshot.spaces)for(const tab of s.tabs||[])if((tab.terminals||[]).some(t=>t.terminal===id))return {space:s,tab};return {};}
function terminalLabel(t){const base=t.name||t.agent||'普通终端';const tab=locationOf(t.address).tab;const peers=(tab?.terminals||[]).map(p=>terminal(p.terminal)).filter(p=>p&&(p.name||p.agent||'普通终端')===base);return peers.length>1?base+' · 终端 '+(peers.findIndex(p=>p.address===t.address)+1):base;}
function isCodex(t){return ['codex','codex.exe','codex-cli'].includes((t?.agent||'').split(/[\\/]/).pop().toLowerCase());}
function status(t){return ['finished','unavailable'].includes(t.state)?t.state:(t.status||t.state||'live');}
function navOpen(open){document.body.classList.toggle('nav-open',open);$('shade').hidden=!open;$('menu').setAttribute('aria-expanded',String(open));}
function matches(t){return [t.address,t.agent,t.cwd,t.where,t.name,names[status(t)]].join(' ').toLowerCase().includes($('search').value.trim().toLowerCase());}
function terminalButton(t){const b=button('',()=>choose(t.address), 'terminal-button'+(t.address===selected?' selected':''));b.dataset.address=t.address;const dot=document.createElement('span');dot.className='dot '+status(t);const label=document.createElement('div');label.className='label';const title=document.createElement('span');title.textContent=terminalLabel(t);const sub=document.createElement('small');const loc=locationOf(t.address);sub.textContent=(t.agent?'Agent':'Shell')+' · '+(mode==='spaces'?'标签页 '+(loc.tab?.name||'未命名'):(loc.space?.name||t.cwd||'独立终端'));label.append(title,sub);const meta=document.createElement('small');meta.textContent=names[status(t)]||status(t);b.append(dot,label,meta);b.title='终端编号：'+t.address+'（排查问题时使用）\n'+(t.cwd||'');return b;}
function renderNav(){
 $('spaces-mode').setAttribute('aria-selected',String(mode==='spaces'));$('agents-mode').setAttribute('aria-selected',String(mode==='agents'));
 $('agent-count').textContent=snapshot.terminals.filter(t=>t.agent&&!['finished','unavailable'].includes(t.state)).length;
 const count=snapshot.terminals.reduce((a,t)=>(a[status(t)]=(a[status(t)]||0)+1,a),{});
 $('summary').textContent=`${snapshot.terminals.length} 个终端 · ${count.working||0} 工作中 · ${(count.blocked||0)+(count.error||0)} 需要你`;
 const nav=$('navigation');nav.replaceChildren();
 if(mode==='spaces'){
  for(const s of snapshot.spaces){const ids=(s.tabs||[]).flatMap(t=>(t.terminals||[]).map(x=>x.terminal));const items=snapshot.terminals.filter(t=>ids.includes(t.address)&&matches(t));if($('search').value&&!items.length&&!s.name.toLowerCase().includes($('search').value.toLowerCase()))continue;
   const group=document.createElement('div');group.className='space';const b=button('▸  '+s.name,()=>{spaceId=s.id;const target=remembered.get(s.id);choose(items.find(t=>t.address===target)?.address||items[0]?.address||null);},'space-button'+(s.id===spaceId?' selected':''));const n=document.createElement('small');n.textContent='工作区 · '+ids.length+' 个终端';b.append(n);group.append(b);if(s.id===spaceId){const children=document.createElement('div');children.className='space-terminals';for(const t of items)children.append(terminalButton(t));const add=button(creatingTerminal?'正在创建…':'＋ 新建终端',()=>createTerminal(s.id),'add-terminal');add.disabled=creatingTerminal;children.append(add);group.append(children);}nav.append(group);
  }
  const orphan=snapshot.terminals.filter(t=>!locationOf(t.address).space&&matches(t));if(orphan.length){const label=document.createElement('div');label.className='nav-label';label.textContent='其他终端';nav.append(label,...orphan.map(terminalButton));}
 }else{
  const order={blocked:0,error:1,working:2,done:3,idle:4,live:5};
  const items=snapshot.terminals.filter(matches).slice().sort((a,b)=>(order[status(a)]??6)-(order[status(b)]??6));
  const agents=items.filter(t=>t.agent), shells=items.filter(t=>!t.agent);
  if(!agents.length){const label=document.createElement('div');label.className='empty';label.textContent='尚未运行 Agent';nav.append(label);}
  for(const t of agents)nav.append(terminalButton(t));
  if(shells.length){const label=document.createElement('div');label.className='nav-label';label.textContent='普通终端';nav.append(label,...shells.map(terminalButton));}
 }
 if(!nav.children.length){const e=document.createElement('div');e.className='empty';e.textContent='没有匹配的终端';nav.append(e);}
}
function renderHeading(){
 const t=terminal(selected), loc=locationOf(selected), s=loc.space||snapshot.spaces.find(s=>s.id===spaceId);
 $('title').textContent=t?terminalLabel(t):(s?.name||'暂无运行中的终端');
 $('title').title=t?'终端编号：'+t.address+'（排查问题时使用）':'';
 $('breadcrumb').textContent=s?`${s.name}${loc.tab?' / 标签页 '+(loc.tab.name||'未命名'):''}`:'ALL AGENTS';$('detail').textContent=t?.cwd||s?.folder||'';
 $('terminal-status').textContent=t?(names[status(t)]||status(t)):'';$('compose-label').textContent=t?'发送到 '+terminalLabel(t):'选择终端后发送';
 $('tabs').replaceChildren();$('panes').replaceChildren();
 if(s)for(const tab of s.tabs||[]){const members=(tab.terminals||[]).map(x=>terminal(x.terminal)).filter(Boolean);$('tabs').append(button(tab.name||'标签页',()=>{const target=members.find(x=>x.address===remembered.get(tab.id))||members[0];choose(target?.address||null);},loc.tab?.id===tab.id?'selected':''));}
 if(loc.tab&&(loc.tab.terminals||[]).length>1)for(const p of loc.tab.terminals){const t=terminal(p.terminal);if(t)$('panes').append(button(terminalLabel(t),()=>choose(t.address),t.address===selected?'selected':''));}
 $('codex-keys').hidden=!isCodex(t);
 const inactive=t&&['finished','unavailable'].includes(t.state);
 const shell=t&&!t.agent&&!inactive;
 $('context-notice').hidden=!!t&&!shell&&!inactive;
 $('context-notice').textContent=inactive?(t.state==='finished'?'这个终端已结束，保留输出供查看。可在公司 Herdr App 中重新打开终端。':'这个终端暂未就绪，已保留在工作区中。稍后刷新重试。'):shell?'尚未启动 Agent。这是普通终端，可在下方输入 codex、claude 等命令启动。':'这个 Space 暂无终端，可在公司 Herdr App 中打开终端后继续。';
 $('message').placeholder=shell?'输入终端命令，例如 codex 或 claude…':'输入任务或回复…';
 setDisabled();
}
function setDisabled(){$('restore-draft').hidden=!savedDrafts.has(selected);$('restore-draft').disabled=busy;document.querySelectorAll('#keys button,#codex-keys button,#submit').forEach(b=>b.disabled=busy||!selected||['finished','unavailable'].includes(terminal(selected)?.state));}
function showScreen(id,restoring=false){const value=cache.get(id);if(!value){$('screen').textContent= id?'正在读取终端…':'此 Space 暂无运行中的终端。';$('freshness').textContent=id?'正在读取':'暂无输出';return;}
 const screen=$('screen'),bottom=screen.scrollHeight-screen.scrollTop-screen.clientHeight<40;
 if(screen.textContent!==value.text)screen.textContent=value.text;
 if(restoring)screen.scrollTop=positions.get(id)??screen.scrollHeight;else if(following&&bottom)screen.scrollTop=screen.scrollHeight;
 $('freshness').textContent=(Date.now()-value.time<4000?'实时屏幕 · ':'缓存 · ')+new Date(value.time).toLocaleTimeString();
}
function read(id){if(terminal(id)?.state==='unavailable'){if(selected===id){$('freshness').textContent='暂未就绪';$('screen').textContent='终端暂未就绪，请稍后刷新。';}return Promise.resolve();}if(inflight.has(id))return inflight.get(id);const generation=epoch;
 const promise=api('read',{address:id}).then(data=>{if(generation!==epoch)return;cache.delete(id);cache.set(id,{text:data.text||'',time:Date.now()});while(cache.size>40)cache.delete(cache.keys().next().value);if(selected===id){showScreen(id);recovered('screen');}}).finally(()=>{if(inflight.get(id)===promise)inflight.delete(id);});inflight.set(id,promise);return promise;
}
function choose(id){$('slash-dialog').close();if(selected){drafts.set(selected,$('message').value);positions.set(selected,$('screen').scrollTop);}selected=id;const loc=locationOf(id);if(loc.space){spaceId=loc.space.id;remembered.set(spaceId,id);remembered.set(loc.tab.id,id);}sessionStorage.setItem('core-selected',id||'');$('message').value=drafts.get(id)||'';renderNav();renderHeading();showScreen(id,true);navOpen(false);if(id)read(id).catch(e=>notify(e.message,'screen'));}
async function preload(){const generation=epoch;const ids=snapshot.terminals.filter(t=>t.address!==selected&&(!cache.has(t.address)||Date.now()-cache.get(t.address).time>15000)).slice(0,8).map(t=>t.address);async function lane(){while(ids.length&&generation===epoch&&token&&!document.hidden){const id=ids.shift();try{await read(id);}catch{/* background reads must not disrupt the current terminal */}}}await Promise.all([lane(),lane()]);}
async function refresh(){if(!token||loading)return;loading=true;const generation=epoch;
 try{const data=await api('snapshot');if(generation!==epoch)return;snapshot=data;sessionStorage.setItem('core-token',token);$('dashboard').hidden=false;$('login').hidden=true;recovered('navigation');
 if(!terminal(selected)){const kept=data.spaces.find(s=>s.id===spaceId);if(kept){if(selected!==null)choose(null);else{renderNav();renderHeading();showScreen(null);}}else{const last=sessionStorage.getItem('core-selected');choose(terminal(last)?.address||data.terminals[0]?.address||null);}}else{renderNav();renderHeading();}
 notify(data.warning||'','layout');preload();
 }catch(e){if(generation===epoch){notify(e.message,'navigation');}}finally{loading=false;}
}
async function act(data){if(!selected||busy)return false;const address=selected,generation=epoch;busy=true;setDisabled();notify('');try{await api('action',{address,...data});return generation===epoch;}catch(e){notify(e.message);return false;}finally{busy=false;setDisabled();if(generation===epoch)read(address).catch(e=>notify(e.message,'screen'));}}
$('login').onsubmit=e=>{e.preventDefault();epoch++;token=$('token').value.trim();$('token').value='';notify('');refresh();};
$('logout').onclick=loggedOut;$('menu').onclick=()=>navOpen(!document.body.classList.contains('nav-open'));$('shade').onclick=()=>navOpen(false);
$('spaces-mode').onclick=()=>{mode='spaces';renderNav();};$('agents-mode').onclick=()=>{mode='agents';renderNav();};$('search').oninput=renderNav;
$('refresh').onclick=()=>{notify('');refresh();if(selected)read(selected).catch(e=>notify(e.message,'screen'));};
$('follow').onclick=()=>{following=!following;$('follow').setAttribute('aria-pressed',String(following));if(following)$('screen').scrollTop=$('screen').scrollHeight;};

$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('screen').textContent);$('copy').textContent='已复制';setTimeout(()=>$('copy').textContent='复制',1500);}catch{notify('浏览器未允许复制，请在终端中选择文字复制');}};
$('send').onsubmit=async e=>{e.preventDefault();const id=selected,text=$('message').value;if(await act({action:'send',text})){if(drafts.get(id)===text)drafts.delete(id);if(selected===id&&$('message').value===text)$('message').value='';}};
$('message').oninput=()=>{if(selected)drafts.set(selected,$('message').value);};
$('message').onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();if(!busy)$('send').requestSubmit();}};
for(const b of document.querySelectorAll('[data-key]'))b.onclick=()=>act({action:'key',key:b.dataset.key});
window.addEventListener('keydown',e=>{if(e.key==='Escape')navOpen(false);if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const list=snapshot.terminals;const n=list.findIndex(t=>t.address===selected);if(list.length)choose(list[(n+(e.key==='ArrowDown'?1:-1)+list.length)%list.length].address);}});
setInterval(()=>{if(token&&!document.hidden&&selected)read(selected).catch(e=>notify(e.message,'screen'));},1800);
setInterval(()=>{if(!document.hidden)refresh();},5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();if(selected)read(selected).catch(e=>notify(e.message,'screen'));}});refresh();



$('new-space').onclick=()=>{if(creatingSpace)return;$('space-error').hidden=true;$('space-name').value='';$('space-folder').value=locationOf(selected).space?.folder||terminal(selected)?.cwd||'';navOpen(false);$('space-dialog').showModal();$('space-name').focus();};
$('space-cancel').onclick=()=>{if(!creatingSpace)$('space-dialog').close();};
$('space-dialog').addEventListener('cancel',e=>{if(creatingSpace)e.preventDefault();});
$('space-form').onsubmit=async e=>{e.preventDefault();if(creatingSpace)return;creatingSpace=true;$('space-create').disabled=true;$('space-cancel').disabled=true;$('space-create').textContent='正在创建…';$('space-error').hidden=true;
 try{const result=await api('spaces/create',{name:$('space-name').value.trim(),folder:$('space-folder').value.trim()});$('space-dialog').close();spaceId=result.space;mode='spaces';$('search').value='';try{const data=await api('snapshot');snapshot=data;choose(terminal(result.terminal)?.address||null);notify('');}catch(error){notify('Space 已创建，列表刷新失败，请点击刷新查看。'+error.message);}}
 catch(error){$('space-error').textContent=error.message;$('space-error').hidden=false;}
 finally{creatingSpace=false;$('space-create').disabled=false;$('space-cancel').disabled=false;$('space-create').textContent='创建 Space';}
};

async function createTerminal(targetSpace){
 if(creatingTerminal)return;creatingTerminal=true;renderNav();notify('');
 try{const result=await api('terminals/create',{space:targetSpace});spaceId=targetSpace;mode='spaces';$('search').value='';try{snapshot=await api('snapshot');choose(terminal(result.terminal)?.address||null);}catch(error){notify('终端已创建，请刷新列表查看。'+error.message);}}
 catch(error){notify(error.message);}
 finally{creatingTerminal=false;renderNav();}
}



const slashCommands=[
 ['/resume','历史会话','打开已保存的对话列表，继续之前的工作'],
 ['/model','选择模型','打开模型与推理设置'],
 ['/status','会话状态','查看上下文用量、限制及会话信息'],
 ['/permissions','权限设置','查看或调整当前会话权限'],
 ['/compact','压缩上下文','压缩当前对话，保留关键上下文'],
 ['/new','新建对话','在同一终端中开始新对话'],
 ['/diff','查看改动','查看当前 Git 工作区改动'],
 ['/review','代码审查','让 Codex 审查当前代码改动'],
 ['/plan','计划模式','先讨论方案，再开始实现']
];
for(const [command,label,description] of slashCommands){
 const b=button('',()=>{
  const t=terminal(selected);if(!isCodex(t)||busy||['finished','unavailable'].includes(t.state))return;
  const text=$('message').value;
  if(text.trim()&&!slashCommands.some(([c])=>c===text.trim()))savedDrafts.set(selected,text);
  $('message').value=command;drafts.set(selected,command);$('slash-dialog').close();setDisabled();$('message').focus();
 },'slash-command');b.dataset.command=command;
 const code=document.createElement('code');code.textContent=command;
 const title=document.createElement('strong');title.textContent=label;
 const desc=document.createElement('small');desc.textContent=description;b.append(code,title,desc);$('slash-list').append(b);
}
$('slash-open').onclick=()=>{if(isCodex(terminal(selected))&&!busy)$('slash-dialog').showModal();};
$('slash-close').onclick=()=>$('slash-dialog').close();
$('restore-draft').onclick=()=>{if(busy||!savedDrafts.has(selected))return;const text=savedDrafts.get(selected);savedDrafts.delete(selected);$('message').value=text;drafts.set(selected,text);setDisabled();$('message').focus();};
