// Minimal robust renderer for login/chat
const API = 'http://localhost:8000/api/v1'
let token = null
let currentConversation = null

function authHeaders(){
  if (token) return { 'Authorization': 'Bearer ' + token }
  return {}
}

async function postJson(url, body){
  const res = await fetch(url, {
    method: 'POST',
    headers: Object.assign(
        {'Content-Type': 'application/json'},
        authHeaders()
    ),
    body: JSON.stringify(body)
  })

  let data = {}

  try {
    data = await res.json()
  } catch (e) {
    data = {}
  }

  if (!res.ok) {
    const message =
        data?.detail ||
        data?.error ||
        `HTTP ${res.status}`

    throw new Error(message)
  }

  return data
}
async function getJson(url){
  const res = await fetch(url, { headers: authHeaders() })
  try{ return await res.json() } catch(e){ return {} }
}

function appLog(msg){
  // Prefer electron logging to persist messages, fallback to debug div + console
  try{ if(window && window.electron && window.electron.logError){ window.electron.logError(msg); return } }catch(e){}
  try{ console.log(msg) }catch(e){}
  const d = document.getElementById('debug-log'); if(!d) return; d.style.display='block'; const el = document.createElement('div'); el.innerText = msg; d.appendChild(el); if(d.childNodes.length>200) d.removeChild(d.firstChild)
}

function showToast(msg, type='success'){
  const root = document.getElementById('toast-root'); if(!root) return
  const el = document.createElement('div'); el.className='toast ' + type; el.innerText = msg; root.appendChild(el); setTimeout(()=>el.classList.add('show'),10); setTimeout(()=>{ el.classList.remove('show'); setTimeout(()=>root.removeChild(el),300) },4000)
  appLog(msg)
}

function showLoader(text='Bitte warten...'){
  let o = document.getElementById('loader-overlay')
  if(!o){ o = document.createElement('div'); o.id='loader-overlay'; o.style.position='fixed'; o.style.left=0; o.style.top=0; o.style.right=0; o.style.bottom=0; o.style.display='flex'; o.style.alignItems='center'; o.style.justifyContent='center'; o.style.background='rgba(0,0,0,0.4)'; o.style.zIndex=9999; const b=document.createElement('div'); b.style.padding='16px'; b.style.background='rgba(11,14,28,0.9)'; b.style.borderRadius='8px'; b.style.color='white'; b.innerText=text; o.appendChild(b); document.body.appendChild(o) }
}
function hideLoader(){ const o = document.getElementById('loader-overlay'); if(o) o.remove() }

async function doLogin(){
  showLoader('Anmeldung...')
  try{
    const email = document.getElementById('email').value
    const password = document.getElementById('password').value
    if(!email || !password){ showToast('Bitte E-Mail und Passwort ausfüllen','error'); return }
    try{
      const res = await postJson(API + '/auth/login', { email, password })
      if(res && res.access_token){ token = res.access_token; showToast('Angemeldet'); document.getElementById('auth').style.display='none'; document.getElementById('projects').style.display='block'; const m = document.querySelector('.main'); if(m) m.style.display='block'; await refreshProjects(); await refreshConversations(); } else { showToast('Login fehlgeschlagen','error') }
    }catch(apiErr){
      // If backend returned a structured error, show it
      const msg = apiErr && apiErr.message ? apiErr.message : 'Login fehlgeschlagen'
      showToast(msg,'error')
      appLog('login error: '+msg)
    }
  }catch(e){ showToast('Fehler: ' + (e && e.message),'error'); appLog('login error: '+(e && e.message)) }
  finally{ hideLoader() }
}

// Expose doLogin on window so inline onclick attributes work in all contexts (Electron/preload)
window.doLogin = doLogin

// attach listener as well (defensive)
document.getElementById('login')?.addEventListener('click', doLogin)
console.log('renderer: login handler attached')
appLog('renderer: script loaded')

const pwd = document.getElementById('password')
if(pwd) pwd.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); doLogin() } })

const projectConversations = new Map() // projectId -> conversationId
let selectedProjectId = null

async function refreshProjects(){
  try{
    const projects = await getJson(API + '/projects/');
    const ul = document.getElementById('project-list'); if(!ul) return; ul.innerHTML='';
    projects.forEach(p=>{
      const li = document.createElement('li');
      const icon = document.createElement('span'); icon.className='project-item-icon'; icon.innerHTML = '📁';
      const title = document.createElement('span'); title.innerText = p.name; title.style.flex='1';
      li.style.display='flex'; li.style.alignItems='center'; li.style.justifyContent='space-between'; li.dataset.projectId = p.id;
      li.appendChild(icon);
      li.appendChild(title);

      // ellipsis menu button
      const ell = document.createElement('button'); ell.className='ellipsis-button'; ell.innerText='⋯';
      const controls = document.createElement('div'); controls.className='project-controls'; controls.appendChild(ell); li.appendChild(controls);

      li.onclick = async (e)=>{ if(e.target === ell) return; selectProject(p.id, p.name, li) };

      ell.addEventListener('click', (e)=>{ e.stopPropagation(); // show dropdown
        // remove existing dropdowns
        document.querySelectorAll('.dropdown-menu').forEach(d=>d.remove())
        const menu = document.createElement('div'); menu.className='dropdown-menu';
        const renameBtn = document.createElement('button'); renameBtn.innerText='Umbenennen';
        const deleteBtn = document.createElement('button'); deleteBtn.innerText='Löschen';
        renameBtn.addEventListener('click', async ()=>{ const newName = await createPromptModal('Neuer Projektname:'); if(!newName) return; showLoader('Umbenennen...'); const res = await postJson(API + '/projects/' + p.id, { name: newName, description: p.description || '', watched_folder: p.watched_folder || null }); hideLoader(); if(res && res.id){ showToast('Umbenannt'); await refreshProjects() } else showToast('Fehler beim Umbenennen','error'); menu.remove(); });
        deleteBtn.addEventListener('click', async ()=>{ if(!confirm('Projekt löschen?')) return; showLoader('Löschen...'); const r = await fetch(API + '/projects/' + p.id, { method: 'DELETE', headers: authHeaders() }); hideLoader(); if(r.ok){ showToast('Gelöscht'); await refreshProjects(); document.getElementById('chat-log').innerHTML=''; } else { showToast('Löschen fehlgeschlagen','error') } menu.remove(); });
        menu.appendChild(renameBtn); menu.appendChild(deleteBtn);
        document.body.appendChild(menu);
        // position menu near button
        const rect = ell.getBoundingClientRect(); menu.style.top = (rect.bottom + window.scrollY + 6) + 'px'; menu.style.left = (rect.left + window.scrollX - 80) + 'px';
      });

      ul.appendChild(li)
    })
  }catch(e){ showToast('Projects error','error') }
}

async function selectProject(id, name, liEl){
  // clear previous selection
  document.querySelectorAll('.project-list li').forEach(el=>el.classList.remove('project-selected'))
  if(liEl) liEl.classList.add('project-selected')
  selectedProjectId = id
  document.getElementById('selected-info').innerText = name
  document.getElementById('selected-info').dataset.projectId = id
  // fetch project details to get watched_folder
  try{
    const proj = await getJson(API + '/projects/' + id)
    if(proj) document.getElementById('selected-info').dataset.watchedFolder = proj.watched_folder || ''
  }catch{}
  // load project-scoped conversations if any
  currentConversation = projectConversations.get(id) || null
  await refreshConversations()
}


// Project creation flow: open modal to enter name and select local folder
// modal prompt helper
function createPromptModal(label){
  return new Promise((resolve)=>{
    const overlay = document.createElement('div'); overlay.className='modal-overlay';
    const box = document.createElement('div'); box.className='modal-box';
    const lbl = document.createElement('div'); lbl.innerText = label; lbl.style.fontWeight='600';
    const input = document.createElement('input'); input.type='text'; input.className='input'; input.style.width='100%';
    const buttons = document.createElement('div'); buttons.style.display='flex'; buttons.style.justifyContent='flex-end'; buttons.style.gap='8px';
    const cancel = document.createElement('button'); cancel.className='button'; cancel.innerText='Abbrechen';
    const ok = document.createElement('button'); ok.className='button'; ok.innerText='Erstellen';
    buttons.appendChild(cancel); buttons.appendChild(ok);
    box.appendChild(lbl); box.appendChild(input); box.appendChild(buttons); overlay.appendChild(box); document.body.appendChild(overlay);
    input.focus();
    function cleanup(){ overlay.remove(); }
    cancel.addEventListener('click', ()=>{ cleanup(); resolve(null) })
    ok.addEventListener('click', ()=>{ const v=input.value.trim(); cleanup(); resolve(v || null) })
    input.addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ e.preventDefault(); ok.click() } if(e.key==='Escape'){ cancel.click() } })
  })
}

// mic recording -> record, upload to /api/v1/audio/transcribe, then send transcript to chat
let mediaRecorder = null
let recordingChunks = []
let isRecording = false
let currentStream = null

async function startRecording(){
  if(isRecording) return
  try{
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    currentStream = stream
    mediaRecorder = new MediaRecorder(stream)
    recordingChunks = []
    mediaRecorder.ondataavailable = (ev)=>{ if(ev.data && ev.data.size) recordingChunks.push(ev.data) }
    mediaRecorder.onstop = async ()=>{
      const blob = new Blob(recordingChunks, { type: 'audio/webm' })
      // upload to backend for transcription
      const fd = new FormData()
      fd.append('file', blob, `recording-${Date.now()}.webm`)
      showToast('Transcription started...', 'success')
      showLoader('Transkribiere...')
      try{
        const res = await fetch(API + '/audio/transcribe', { method: 'POST', headers: Object.assign({}, authHeaders()), body: fd })
        const data = await res.json()
        hideLoader()
        if(res.ok && data && data.text){
          showToast('Transcription completed', 'success')
          appendMessage('You (audio)', data.text)
          // send transcript to chat
          document.getElementById('chat-input').value = data.text
          sendChat()
        } else {
          showToast('Transcription failed','error')
        }
      }catch(e){ hideLoader(); showToast('Transcription error','error') }
      if(currentStream){ currentStream.getTracks().forEach(t=>t.stop()); currentStream = null }
      isRecording = false
      document.getElementById('mic-btn')?.classList.remove('mic-recording')
    }
    mediaRecorder.start()
    isRecording = true
    document.getElementById('mic-btn')?.classList.add('mic-recording')
  }catch(e){ showToast('Microphone access denied or unavailable','error') }
}

function stopRecording(){ if(!isRecording || !mediaRecorder) return; mediaRecorder.stop() }

const micBtn = document.getElementById('mic-btn')
if(micBtn) micBtn.addEventListener('click', ()=>{ if(isRecording) stopRecording(); else startRecording() })


async function openCreateProjectDialog(){
  const name = await createPromptModal('Projektname eingeben:')
  if(!name) return
  showLoader('Wähle geteilten Ordner...')
  try{
    const folder = await window.electron.selectFolder()
    if(!folder){ showToast('Kein Ordner ausgewählt','error'); return }
    showLoader('Projekt wird erstellt...')
    const res = await postJson(API + '/projects/', { name: name, description: '', watched_folder: folder })
    if(res && res.id){ showToast('Projekt erstellt'); await refreshProjects() } else { showToast('Projekt konnte nicht erstellt werden','error') }
  }catch(e){ showToast('Fehler: '+(e && e.message),'error') }
  finally{ hideLoader() }
}

document.getElementById('create-project')?.addEventListener('click', openCreateProjectDialog)
document.getElementById('refresh-projects')?.addEventListener('click', refreshProjects)

document.getElementById('search-btn')?.addEventListener('click', async ()=>{
  const q = document.getElementById('search-input').value
  if(!q) return
  const projectId = selectedProjectId || null
  showLoader('Suche...')
  try{
    const res = await postJson(API + '/search/', { query: q, project_id: projectId, top_k: 6 })
    hideLoader()
    if(res && res.results){
      // render results in chat-log as clickable items with preview modal
      const log = document.getElementById('chat-log'); log.innerHTML=''
      res.results.forEach(r=>{
        const el = document.createElement('div'); el.className='chat-message assistant';
        const bubble = document.createElement('div'); bubble.className='bubble';
        bubble.innerHTML = `<b>Result:</b> ${r.text.slice(0,200)}... <div class="small">score: ${r.score.toFixed(3)}</div>`;
        el.appendChild(bubble);
        el.addEventListener('click', ()=>{ openPreviewModal(r) })
        log.appendChild(el)
      })
      // pagination: show load more if present
      if(res.next_offset !== null){
        const more = document.createElement('button'); more.className='button'; more.innerText='More';
        more.addEventListener('click', async ()=>{
          showLoader('Loading...')
          try{
            const resp = await postJson(API + '/search/', { query: document.getElementById('search-input').value, project_id: selectedProjectId, top_k:6, offset: res.next_offset })
            hideLoader()
            if(resp && resp.results){
              resp.results.forEach(r=>{
                const el = document.createElement('div'); el.className='chat-message assistant';
                const bubble = document.createElement('div'); bubble.className='bubble';
                bubble.innerHTML = `<b>Result:</b> ${r.text.slice(0,200)}... <div class="small">score: ${r.score.toFixed(3)}</div>`;
                el.appendChild(bubble);
                el.addEventListener('click', ()=>{ openPreviewModal(r) });
                log.appendChild(el)
              })
            }
          }catch(err){ hideLoader(); showToast('Search error','error'); appLog('search paging error: '+ (err && err.message)) }
        })
        document.getElementById('chat-log').appendChild(more)
      }
    }
  }catch(e){ hideLoader(); showToast('Search error','error'); appLog('search error: '+ (e && e.message)) }
})

function openPreviewModal(item){
  // simple modal with full text and insert/send options
  const overlay = document.createElement('div'); overlay.className='modal-overlay';
  const box = document.createElement('div'); box.className='modal-box';
  const title = document.createElement('div'); title.innerText = 'Preview'; title.style.fontWeight='600';
  const content = document.createElement('div'); content.style.whiteSpace='pre-wrap'; content.style.maxHeight='60vh'; content.style.overflow='auto'; content.innerText = item.text
  const actions = document.createElement('div'); actions.style.display='flex'; actions.style.justifyContent='flex-end'; actions.style.gap='8px';
  const insertBtn = document.createElement('button'); insertBtn.className='button'; insertBtn.innerText='Insert into chat';
  const sendBtn = document.createElement('button'); sendBtn.className='button'; sendBtn.innerText='Insert and Send';
  const closeBtn = document.createElement('button'); closeBtn.className='button'; closeBtn.innerText='Close';
  actions.appendChild(closeBtn); actions.appendChild(insertBtn); actions.appendChild(sendBtn);
  box.appendChild(title); box.appendChild(content); box.appendChild(actions); overlay.appendChild(box); document.body.appendChild(overlay);
  insertBtn.onclick = ()=>{ document.getElementById('chat-input').value = item.text; overlay.remove() }
  sendBtn.onclick = ()=>{ document.getElementById('chat-input').value = item.text; overlay.remove(); sendChat() }
  closeBtn.onclick = ()=> overlay.remove()
}


document.getElementById('sidebar-new-chat')?.addEventListener('click', ()=>{ currentConversation = null; selectedProjectId = null; document.getElementById('selected-info').innerText=''; document.getElementById('chat-log').innerHTML=''; refreshConversations() })


async function sendChat(){
  try{
    const inputEl = document.getElementById('chat-input')
    const msg = inputEl.value; if(!msg) return; inputEl.value = '';
    // show user's message immediately
    appendMessage('You', msg)

    const projectId = selectedProjectId || null;
    // show thinking loader while waiting
    showLoader('Nachdenken...')
    // call enhanced chat (consult embeddings first)
    const res = await postJson(API + '/chat-enhanced/', { message: msg, conversation_id: currentConversation, project_id: projectId });
    hideLoader()

    if(res && res.conversation_id){ currentConversation = res.conversation_id; if(projectId) projectConversations.set(projectId, currentConversation) }
    if(res && res.reply) appendMessage('Hippo', res.reply)

    // detect generation intent (better heuristic) — only generate if user asked
    const lower = msg.toLowerCase();
    const genKeywords = ['génère','générer','génere','generate','erzeuge','erstellen','crée','créer','create','word','docx','worddatei','word file']
    const wantsGen = genKeywords.some(k => lower.includes(k))

    if(wantsGen && res && res.reply){
      // If assistant returned explicit file markers, prefer them
      const fileMatch = res.reply.match(/<<<FILE:([^>]+)>>>\s*([\s\S]*?)\s*<<<END_FILE>>>/m)
      const folder = document.getElementById('selected-info').dataset.watchedFolder
      if(!folder){ showToast('Bitte ein Projekt mit Ordner auswählen, um Datei zu generieren','error'); return }
      if(fileMatch){
        const filename = fileMatch[1].trim()
        const content = fileMatch[2]
        showLoader('Speichere Datei...')
        const saved = await window.electron.saveFile({ folder, filename, data: content })
        hideLoader()
        if(saved && saved.ok){ showToast('Datei erstellt: ' + saved.path); appendMessage('System', 'Datei erstellt in: ' + saved.path) } else { showToast('Fehler beim Erstellen der Datei','error') }
      } else {
        // build simple RTF from assistant reply
        const rtf = buildRtfFromText(res.reply)
        const filename = `generated-${Date.now()}.rtf`
        showLoader('Erzeuge Datei...')
        const saved = await window.electron.saveFile({ folder, filename, data: rtf })
        hideLoader()
        if(saved && saved.ok){ showToast('Datei erstellt: ' + saved.path); appendMessage('System', 'Datei erstellt in: ' + saved.path) } else { showToast('Fehler beim Erstellen der Datei','error') }
      }
    }

  }catch(e){
    hideLoader()

    console.error('Chat error:', e)

    showToast(
        'Chat error: ' + (e?.message || 'Unknown error'),
        'error'
    )
  }
}

function buildRtfFromText(text){
  // very small RTF wrapper
  const header = '{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}\n'
  const body = text.replace(/\\/g,'\\\\').replace(/\n/g,'\\par \n')
  const footer = '\n}'
  return header + body + footer
}

// refresh conversations list (project-scoped if selected)
async function refreshConversations(){
  try{
    const convs = await getJson(API + '/chat/conversations')
    const container = document.getElementById('conversations'); if(!container) return; container.innerHTML='';

    // split into global (no project) and project-scoped
    const globalConvs = convs.filter(c => !c.project_id)
    const projectConvs = selectedProjectId ? convs.filter(c => c.project_id === selectedProjectId) : []

    // populate sidebar chat list with global conversations (sorted recent first)
    const chatList = document.getElementById('chat-list'); if(chatList) chatList.innerHTML='';
    globalConvs.sort((a,b)=> new Date(b.created_at) - new Date(a.created_at)).forEach(c=>{
      const item = document.createElement('li'); item.style.display='flex'; item.style.alignItems='center'; item.style.justifyContent='space-between';
      const txt = document.createElement('span'); txt.innerText = c.title || ('Chat ' + c.id);
      const ts = document.createElement('span'); ts.className='list-timestamp'; ts.innerText = c.created_at ? new Date(c.created_at).toLocaleString() : '';
      const del = document.createElement('button'); del.className='small'; del.innerText='🗑'; del.title='Löschen';
      const left = document.createElement('div'); left.style.display='flex'; left.style.alignItems='center'; left.style.gap='8px'; left.appendChild(txt); left.appendChild(ts);
      item.appendChild(left); item.appendChild(del);
      item.onclick = async ()=>{ currentConversation = c.id; const resp = await getJson(API + '/chat/conversations/' + c.id); document.getElementById('chat-log').innerHTML=''; resp.messages.forEach(m=>appendMessage(m.role, m.content)); }
      del.addEventListener('click', async (e)=>{ e.stopPropagation(); if(!confirm('Chat löschen?')) return; showLoader('Löschen...'); const r = await fetch(API + '/chat/conversations/' + c.id, { method: 'DELETE', headers: authHeaders() }); hideLoader(); if(r.ok){ showToast('Chat gelöscht'); await refreshConversations(); } else showToast('Löschen fehlgeschlagen','error') })
      chatList.appendChild(item)
    })

    // show project conversations in main conversations area if a project is selected
    if(selectedProjectId){
      const header = document.createElement('div'); header.style.display='flex'; header.style.justifyContent='space-between'; header.style.alignItems='center'; header.style.marginBottom='8px';
      const h = document.createElement('div'); h.innerText = 'Projekt‑Chats'; h.style.fontWeight='600';
      const newBtn = document.createElement('button'); newBtn.className='button'; newBtn.innerText='Neuer Chat'; newBtn.onclick = ()=>{ currentConversation = null; document.getElementById('chat-log').innerHTML=''; }
      header.appendChild(h); header.appendChild(newBtn); container.appendChild(header)

      projectConvs.sort((a,b)=> new Date(b.created_at) - new Date(a.created_at)).forEach(c=>{
        const b = document.createElement('button'); b.className='small'; b.style.marginRight='8px';
        const txt = document.createElement('span'); txt.innerText = c.title || ('Chat ' + c.id);
        const ts = document.createElement('span'); ts.className='list-timestamp'; ts.innerText = c.created_at ? new Date(c.created_at).toLocaleString() : '';
        b.appendChild(txt); b.appendChild(ts);
        b.onclick = async ()=>{ currentConversation = c.id; projectConversations.set(selectedProjectId, c.id); const resp = await getJson(API + '/chat/conversations/' + c.id); document.getElementById('chat-log').innerHTML=''; resp.messages.forEach(m=>appendMessage(m.role, m.content)); }
        container.appendChild(b)
      })
    } else {
      // if no project selected, show recent global convs in main area as optional
      const info = document.createElement('div'); info.className='small'; info.innerText = 'Wähle ein Projekt, oder starte einen neuen Chat mit "＋ Neuer Chat"'; container.appendChild(info)
    }
  }catch(e){ /* ignore */ }
}


document.getElementById('send-chat')?.addEventListener('click', sendChat)

document.getElementById('chat-input')?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); sendChat() } })

function appendMessage(role, text){ const log = document.getElementById('chat-log'); if(!log) return; const msg = document.createElement('div'); msg.className = 'chat-message ' + (role === 'You' || role === 'user' ? 'user' : role === 'System' || role === 'System' ? 'system' : 'assistant'); const bubble = document.createElement('div'); bubble.className='bubble'; bubble.innerHTML = `<strong>${role}:</strong> ${text}`; msg.appendChild(bubble); log.appendChild(msg); log.scrollTop = log.scrollHeight }

 // Ensure event listeners are attached after DOM is ready
 document.addEventListener('DOMContentLoaded', ()=>{
   console.log('renderer: DOMContentLoaded')
   appLog('renderer: DOMContentLoaded')

   // Attach auth/login handlers
   document.getElementById('login')?.addEventListener('click', doLogin)
   const pwd = document.getElementById('password')
   if(pwd) pwd.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); doLogin() } })

   // Attach UI handlers (defensive re-attach)
   document.getElementById('create-project')?.addEventListener('click', openCreateProjectDialog)
   document.getElementById('refresh-projects')?.addEventListener('click', refreshProjects)
   document.getElementById('search-btn')?.addEventListener('click', async ()=>{ const q = document.getElementById('search-input').value; if(!q) return; const projectId = selectedProjectId || null; showLoader('Suche...'); try{ const res = await postJson(API + '/search/', { query: q, project_id: projectId, top_k: 6 }); hideLoader(); if(res && res.results){ const logEl = document.getElementById('chat-log'); logEl.innerHTML=''; res.results.forEach(r=>{ const el = document.createElement('div'); el.className='chat-message assistant'; const bubble = document.createElement('div'); bubble.className='bubble'; bubble.innerHTML = `<b>Result:</b> ${r.text.slice(0,200)}... <div class="small">score: ${r.score.toFixed(3)}</div>`; el.appendChild(bubble); el.addEventListener('click', ()=>{ openPreviewModal(r) }); logEl.appendChild(el) }) } }catch(e){ hideLoader(); showToast('Search error','error') } })

   document.getElementById('sidebar-new-chat')?.addEventListener('click', ()=>{ currentConversation = null; selectedProjectId = null; document.getElementById('selected-info').innerText=''; document.getElementById('chat-log').innerHTML=''; refreshConversations() })
   document.getElementById('send-chat')?.addEventListener('click', sendChat)
   document.getElementById('chat-input')?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); sendChat() } })

   const micBtn = document.getElementById('mic-btn')
   if(micBtn) micBtn.addEventListener('click', ()=>{ if(isRecording) stopRecording(); else startRecording() })

   // initial log to verify renderer loaded
   console.log('renderer: handlers attached')
   appLog('renderer: handlers attached')

   // attach index embedding button
   document.getElementById('index-embedding')?.addEventListener('click', async ()=>{
     const fileInput = document.getElementById('file-upload')
     const file = fileInput && fileInput.files && fileInput.files[0]
     if(!file){ showToast('No file selected','error'); return }
     if(!selectedProjectId){ showToast('Select a project first','error'); return }
     showLoader('Indexing...')
     try{
       const text = await file.text()
       const body = { project_id: selectedProjectId, items: [{ text: text.slice(0,20000), metadata: { source: 'desktop-upload', filename: file.name, type: file.type } }] }
       const res = await postJson(API + '/embeddings-proxy/store', body)
       hideLoader()
       showToast('Indexed in embedding')
       document.getElementById('upload-result').innerText = 'Indexed'
     }catch(e){ hideLoader(); showToast('Indexing error','error'); appLog('indexing error: '+(e && e.message)) }
   })
 })

