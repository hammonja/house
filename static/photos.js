const $ = id => document.getElementById(id);
document.getElementById('photo-app').innerHTML = `
<header><a class="brand" href="/">⌂ House design<small>DESIGN STUDIO / PHOTO SURVEYS</small></a><a class="button" href="/">View model ↗</a></header>
<main class="page"><div class="intro"><span class="eyebrow">A clearer picture of home</span><h1>Walk. Capture. Refine.</h1><p>Build on your drawings with a walk around the property. Overlapping photographs help refine the simple shapes, materials and planting you already know.</p>
<div class="row"><button id="install" class="install" hidden>Install House on this device</button><span class="help">On iPhone: Share → Add to Home Screen. On Android: use your browser’s Install app option.</span></div></div>
<div id="message" class="status" role="status" aria-live="polite"></div><div class="layout"><div>
<section class="card"><div class="step">01 / CAPTURE A SURVEY</div><h2>A walk around your property</h2>
<label for="survey">Your surveys</label><div class="row"><select id="survey" aria-label="Your surveys"><option value="">Loading surveys…</option></select><button id="new">New survey</button></div>
<form id="new-form" class="new-survey row" hidden><input id="survey-name" aria-label="Survey name" maxlength="100" placeholder="e.g. Garden walk · October" required><button class="primary" type="submit">Create</button></form>
<label for="zone">Where are you looking?</label><select id="zone"><option value="front">Front of house</option><option value="rear">Rear of house</option><option value="left">Left side (from the street)</option><option value="right">Right side (from the street)</option><option value="garden">Garden</option><option value="driveway">Driveway</option><option value="other">Other</option></select>
<label for="note">A useful detail <span class="muted">· optional</span></label><textarea id="note" maxlength="500" placeholder="e.g. Looking towards the house; this gate is 1 m wide."></textarea>
<div class="capture"><button id="take" class="primary">◎ Take photo</button><button id="upload">↑ Upload photos</button></div>
<input id="camera" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden><input id="files" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden>
<progress id="upload-progress" class="progress" value="0" max="100" hidden aria-label="Upload progress"></progress><p id="upload-state" class="help" aria-live="polite"></p>
<details><summary>How to take useful photographs</summary><ul><li>Walk slowly around the outside and keep about half of the previous view in each next photo.</li><li>Take wide views first, then details of windows, roofs, boundaries and planting. Include corners that connect each side.</li><li>Keep the camera at a similar height. Use daylight and avoid blur, digital zoom and very close views.</li><li>Add a measured width or height in the notes where you know it. Photos alone cannot recover precise dimensions.</li><li>Up to 120 photos per survey, 20 MB each. JPEG, PNG or WebP; export HEIC as JPEG if needed.</li></ul></details>
<div class="gallery-heading"><h3 id="photo-count">Survey photos</h3><span class="help">Private on your Pi</span></div><div id="gallery" class="photos"></div><div id="gallery-empty" class="empty">Start a survey, then add your first photographs.</div>
</section><section id="draft-card" class="card" hidden><div class="step">ON THIS DEVICE</div><h2>Photos waiting to upload</h2><p class="help">These unsynced drafts stay in this browser. Keep this device secure and do not clear browser data until they are uploaded. Select the destination survey above, then sync explicitly.</p><div id="draft-list"></div><button id="sync" class="primary">Upload drafts to selected survey</button></section>
</div><div><section class="card"><div class="step">02 / REFINE THE MODEL</div><h2>Turn observations into simple shapes</h2><p class="help">The drawings keep their scale. Photo additions appear on the existing-house view; the planner’s proposed model stays as drawn. Your current model remains in place until you apply a preview.</p>
<div id="api-status" class="status">Checking photo processing…</div><button id="refresh" class="install">Refresh connection & status</button>
<label class="consent"><input id="consent" type="checkbox"><span>Send this survey’s photos and model dimensions to OpenAI for analysis. This uses the configured paid API account. Photos remain private in House and are not published.</span></label>
<p id="request-estimate" class="help"></p><button id="process" class="primary" disabled>Process photos</button><p class="help">You can close this browser after processing starts. The Pi continues the job.</p><div id="jobs"></div>
</section><section class="card"><div class="step">03 / REVIEW & KEEP</div><h2>Model revisions</h2><p id="active-status" class="help">Your drawing-based model is the starting point.</p><div class="row"><button id="undo" disabled>Undo last applied revision</button><a class="button" href="/">Open current model ↗</a></div><div id="revisions"></div><div id="preview" hidden></div></section>
<p class="bottom-note">Study model · Photo-derived dimensions are estimates, not a measured survey. No photorealistic textures are generated. GLB downloads currently contain the original CAD geometry; use a viewer snapshot to share photo additions.</p></div></div></main>`;

let status = null, survey = '', csrf = '', busy = false, photos = [], preview = null, installPrompt;
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function element(tag, text, className) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; }
async function api(path, options = {}) {
  const response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options, headers: {'X-CSRF-Token':csrf, ...(options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...options.headers}});
  if (response.status === 401) throw new Error('Sign in again to upload or process photos. Your device drafts are still saved.');
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'The request could not be completed. Reload the page and try again.');
  return result;
}
const post = (path, data) => api(path, {method:'POST', body:JSON.stringify(data)});
function controls() {
  const running = status?.jobs.some(job => ['queued','running'].includes(job.state));
  $('process').disabled = busy || !status?.configured || !photos.length || !$('consent').checked || running;
  $('sync').disabled = busy || !survey || !status;
  $('undo').disabled = busy || !status?.active;
  for (const id of ['take','upload','new','survey']) $(id).disabled = busy;
  if ($('preview-apply')) $('preview-apply').disabled = busy || status?.active === preview?.id;
  $('request-estimate').textContent = photos.length ? `${photos.length} photo${photos.length===1?'':'s'} · ${Math.ceil(photos.length / (status?.batch_size || 8))} image batch${photos.length>(status?.batch_size||8)?'es':''} + 1 consolidation request. Every photo currently in this survey is included.` : 'Add photos to estimate the processing requests.';
}
async function refresh() {
  try {
    status = await api('/api/photos/status'); csrf = status.csrf;
    const selected = survey;
    $('survey').replaceChildren(element('option', status.surveys.length ? 'Select a survey' : 'Create your first survey'));
    $('survey').firstChild.value = '';
    for (const item of status.surveys) { const option = element('option', `${item.name} (${item.photo_count})`); option.value = item.id; $('survey').append(option); }
    survey = status.surveys.some(s => s.id === selected) ? selected : status.surveys[0]?.id || '';
    $('survey').value = survey;
    $('api-status').textContent = status.configured ? `${status.model} · Ready to process on the Pi` : 'OpenAI key is not configured on the server. You can capture and upload photos now.';
    $('active-status').textContent = status.active ? 'A photo revision is applied to the existing-house model.' : 'Original drawing-based model · no photo revision applied.';
    renderJobs(); renderRevisions(); await loadSurvey(); controls();
    return true;
  } catch(error) {
    status = null; $('api-status').textContent = 'Connect and sign in to sync photos or process a survey.';
    $('survey').replaceChildren(element('option','Offline / sign-in required'));
    message(error.message + ' You can still save new captures as device drafts.', true);
    const login = element('a', ' Sign in'); login.href='/login'; $('message').append(login);
    controls(); return false;
  }
}
async function loadSurvey() {
  photos = survey ? (await api(`/api/surveys/${survey}`)).photos : [];
  $('photo-count').textContent = `${photos.length} survey photo${photos.length === 1 ? '' : 's'}`;
  $('gallery').replaceChildren(); $('gallery-empty').hidden = photos.length > 0;
  for (const photo of photos) {
    const figure = element('figure',null,'photo'), link = element('a'), image = element('img');
    link.href = `/api/photos/${photo.id}/image`; link.target='_blank'; link.rel='noopener';
    image.src = `${link.getAttribute('href')}?thumb=1`; image.alt = `${photo.zone} view${photo.note ? ': '+photo.note : ''}`; image.loading='lazy';
    link.append(image); figure.append(link,element('figcaption',photo.zone)); $('gallery').append(figure);
  }
  controls();
}
function renderJobs() {
  $('jobs').replaceChildren();
  for (const job of status.jobs.filter(j => j.survey === survey)) {
    const card = element('div',null,'job'); card.append(element('span',job.state === 'ready' ? 'Ready to review' : job.state,'pill'));
    card.append(element('p',`${job.photo_count} photo${job.photo_count===1?'':'s'} · ${job.completed_batches}/${job.total_batches} batches analysed${job.state==='running' && job.completed_batches===job.total_batches ? ' · consolidating the model' : ''}`));
    if (job.error) card.append(element('p',job.error));
    if (job.state === 'ready') { const button = element('button','Review revision'); button.onclick=()=>review(job.revision).catch(showError); card.append(button); }
    if (job.state === 'failed') { const button = element('button','Retry unfinished work'); button.onclick=async()=>{
      if (!$('consent').checked) { message('Tick the OpenAI consent box before retrying. An interrupted request may be charged again.',true); return; }
      button.disabled=true; try { await post(`/api/jobs/${job.id}/retry`,{consent:true}); await refresh(); } catch(error) { showError(error);button.disabled=false; }
    }; card.append(button); }
    $('jobs').append(card);
  }
}
function renderRevisions() {
  $('revisions').replaceChildren();
  for (const revision of status.revisions) {
    const card=element('div',null,'revision'), button=element('button',`Review · ${new Date(revision.created*1000).toLocaleString()}`);
    button.onclick=()=>review(revision.id).catch(showError); card.append(button);
    if (revision.id === status.active) card.append(element('span',' Applied','pill'));
    $('revisions').append(card);
  }
}
async function review(id) {
  preview = await api(`/api/revisions/${id}`); const panel=$('preview');panel.hidden=false;panel.replaceChildren();
  panel.append(element('h3','Preview this revision'),element('p',preview.data.summary,'result-summary'));
  const list=element('ul',null,'preview-list');
  for (const feature of preview.data.features) list.append(element('li',`${feature.label} · ${feature.kind} · ${feature.confidence} confidence. ${feature.reason} (${feature.evidence.length} source photo${feature.evidence.length===1?'':'s'}; dimensions estimated.)`));
  if (!preview.data.features.length) list.append(element('li','No supported geometry additions found. Read the uncertainties below before taking more photos.'));
  panel.append(list,element('h3','Details to check'));
  const uncertainties=element('ul',null,'preview-list');
  for(const text of preview.data.uncertainties) uncertainties.append(element('li',text));
  panel.append(uncertainties);
  const actions=element('div',null,'row preview-actions'), link=element('a','Preview in 3D ↗','button');link.href=`/?revision=${id}`;link.target='_blank';link.rel='noopener';
  const apply=element('button','Apply this revision','primary');apply.id='preview-apply';apply.disabled=status.active===id;
  apply.onclick=async()=>{apply.disabled=true;try {await post(`/api/revisions/${id}/apply`,{expected_active:status.active});await refresh();message('Revision applied. Open the model to see your updated existing house.');} catch(error){showError(error);apply.disabled=false;}};
  actions.append(link,apply);panel.append(actions);panel.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function showError(error) { message(error.message || 'Something went wrong. Your current model is unchanged.',true); }

// Device drafts are explicit, private local storage; the service worker caches public assets only.
function database() { return new Promise((resolve,reject)=>{const request=indexedDB.open('house-photo-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts',{keyPath:'id'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('Device storage is unavailable. Keep the photo in your camera roll and upload it when connected.'));}); }
async function draftOperation(mode, action) {const db=await database();return new Promise((resolve,reject)=>{const tx=db.transaction('drafts',mode);const request=action(tx.objectStore('drafts'));tx.oncomplete=()=>{db.close();resolve(request?.result);};tx.onerror=()=>{db.close();reject(new Error('Device draft storage is full or unavailable. Keep the original photos and upload them when connected.'));};});}
const drafts=()=>draftOperation('readonly',s=>s.getAll());
async function renderDrafts() {
  try {const items=await drafts();$('draft-card').hidden=!items.length;$('draft-list').replaceChildren();
    for(const item of items) {const row=element('div',null,'draft-item');row.append(element('p',`${item.name} · ${item.zone} · waiting on this device`));const remove=element('button','Remove device draft');remove.onclick=async()=>{await draftOperation('readwrite',s=>s.delete(item.id));await renderDrafts();};row.append(remove);$('draft-list').append(row);}
  }catch(error){showError(error);}
}
async function uploadOne(file, zone, note, onProgress) {
  const data=new FormData();data.append('photo',file,file.name||'capture.jpg');data.append('zone',zone);data.append('note',note);
  return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',`/api/surveys/${survey}/photos`);xhr.setRequestHeader('X-CSRF-Token',csrf);xhr.timeout=120000;
    xhr.upload.onprogress=event=>{if(event.lengthComputable)onProgress(event.loaded/event.total);};
    xhr.onload=()=>{let response={};try{response=JSON.parse(xhr.responseText);}catch{} if(xhr.status>=200&&xhr.status<300)resolve(response);else reject(new Error(response.error||'Upload was not accepted. Sign in again if your session expired.'));};
    xhr.onerror=xhr.ontimeout=()=>reject(new Error('The upload connection was interrupted.'));
    xhr.send(data);
  });
}
async function capture(files) {
  if (!files.length) return;
  if (files.length>120) {message('Choose at most 120 photos at a time.',true);return;}
  busy=true;controls();$('upload-progress').hidden=false;let uploaded=0,saved=0,duplicates=0,failed=0;const errors=[];
  const zone=$('zone').value,note=$('note').value;
  try {
    for(const [index,file] of [...files].entries()) {
      $('upload-state').textContent=`Photo ${index+1} of ${files.length}…`;
      if(file.size>20*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type)) {failed++;errors.push(`${file.name}: use JPEG, PNG or WebP below 20 MB.`);continue;}
      try {
        if (!navigator.onLine || !survey || !status) throw new Error('Connection or survey unavailable.');
        const result=await uploadOne(file,zone,note,fraction=>{$('upload-progress').value=100*(index+fraction)/files.length;});
        result.duplicate?duplicates++:uploaded++;
      } catch(error) {
        try {const current=await drafts();if(current.length>=120)throw new Error('Device draft limit reached.');await draftOperation('readwrite',s=>s.put({id:crypto.randomUUID(),file,name:file.name,zone,note,created:Date.now()}));saved++;}
        catch(storageError){failed++;errors.push(`${file.name}: ${storageError.message}`);}
      }
    }
    message(`${uploaded} uploaded · ${duplicates} duplicates skipped · ${saved} saved on this device for explicit sync${failed?` · ${failed} could not be saved. ${errors.slice(0,3).join(' ')}`:''}`,failed>0);
    if(status)await refresh();await renderDrafts();
  } finally {busy=false;$('upload-progress').hidden=true;$('upload-state').textContent='';controls();}
}
$('take').onclick=()=>$('camera').click();$('upload').onclick=()=>$('files').click();
for(const id of ['camera','files'])$(id).onchange=async event=>{await capture([...event.target.files]).catch(showError);event.target.value='';};
$('new').onclick=()=>{$('new-form').hidden=!$('new-form').hidden;$('survey-name').focus();};
$('new-form').onsubmit=async event=>{event.preventDefault();if(busy)return;busy=true;controls();try{const result=await post('/api/surveys',{name:$('survey-name').value});survey=result.id;$('new-form').hidden=true;await refresh();message('Survey created. Add photographs from each side.');}catch(error){showError(error);}finally{busy=false;controls();}};
$('survey').onchange=async()=>{survey=$('survey').value;try{await loadSurvey();renderJobs();}catch(error){showError(error);}};
$('consent').onchange=controls;
$('refresh').onclick=async()=>{if(busy)return;if(await refresh())message('Connected. Your surveys and processing status are up to date.');};
$('process').onclick=async()=>{if(busy)return;busy=true;controls();try{await post(`/api/surveys/${survey}/process`,{consent:$('consent').checked});message('Processing started on the Pi. You can close this browser and return later.');await refresh();}catch(error){showError(error);}finally{busy=false;controls();}};
$('undo').onclick=async()=>{try{await post('/api/revisions/undo',{expected_active:status.active});await refresh();message('Last applied revision undone. Uploaded photos are retained.');}catch(error){showError(error);}};
$('sync').onclick=async()=>{if(busy||!survey)return;busy=true;controls();try{const items=await drafts();let count=0;for(const item of items){$('upload-state').textContent=`Syncing ${count+1} of ${items.length}…`;await uploadOne(item.file,item.zone,item.note,()=>{});await draftOperation('readwrite',s=>s.delete(item.id));count++;}message(`${count} device drafts uploaded to this survey.`);await refresh();}catch(error){showError(error);}finally{busy=false;$('upload-state').textContent='';await renderDrafts();controls();}};
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('install').hidden=false;});
$('install').onclick=async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('install').hidden=true;}};
window.addEventListener('online',()=>{message('Connection restored. Use “Upload drafts” when ready.');if(!busy)refresh();});
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
await refresh();await renderDrafts();
setInterval(()=>{if(!busy&&status?.jobs.some(j=>['queued','running'].includes(j.state)))refresh();},5000);
