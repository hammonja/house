import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { HOUSE, configureHouse, STORAGE_KEY, validatePlot, plotBounds, readSavedPlot } from './plot.mjs';
import { createDriveway } from './driveway.js';

const $ = (id) => document.getElementById(id);
const state = { scheme: 'existing', compare: false, floor: 'all', roof: true, explode: false,
  changes: false, style: 'materials', edges: true, height: 2.7, guides: true, view: 'perspective', scope:'house', plotVisible:true };
let project, renderer, scene, camera, controls, roots, guideRoot, width, height;
let plot, plotRoot, boundaryRoot;
const metrics = {};
const meshes = [], edgeLines = [], plates = [], modelMaterials = [], selected = new THREE.Vector2();
let scheduled = false, toastTimer;

function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 3000);
}
function failure(error) {
  $('loading').hidden = true; $('error').hidden = false;
  $('error-message').textContent = error.message || 'Please enable WebGL in your browser, then reload.';
  console.error(error);
}

// Reproducible, code-generated material patterns. The source photos remain untouched.
let seed = 44;
function random() { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 4294967296; }
function texture(kind) {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (kind === 'render') {
    ctx.fillStyle = '#e0dfd2'; ctx.fillRect(0, 0, 512, 512);
    for (let i = 0; i < 37000; i++) {
      const tone = 145 + Math.floor(random()*90);
      ctx.fillStyle = `rgba(${tone},${tone},${tone-8},.18)`;
      ctx.fillRect(random()*512, random()*512, 1+random()*2, 1+random()*2);
    }
  } else if (kind === 'brick') {
    ctx.fillStyle = '#b8ac94'; ctx.fillRect(0, 0, 512, 512);
    for (let row = 0; row < 14; row++) for (let col = -1; col < 5; col++) {
      const x = col*128 + (row%2)*64, y = row*36.57;
      const l = 31 + random()*12;
      ctx.fillStyle = `hsl(${16+random()*7} 33% ${l}%)`; ctx.fillRect(x+2, y+2, 124, 32.5);
      ctx.fillStyle = '#e6c7a014'; ctx.fillRect(x+3, y+3, 122, 3);
      for (let j = 0; j < 35; j++) {
        ctx.fillStyle = '#361e191b';ctx.fillRect(x+random()*124, y+random()*30+3, random()*5+1, 1);
      }
    }
  } else if (kind === 'roof') {
    ctx.fillStyle = '#4b392c'; ctx.fillRect(0,0,512,512);
    for (let row=0;row<10;row++) for(let col=-1;col<8;col++) {
      const x=col*73.14+(row%2)*36.57,y=row*51.2;
      ctx.fillStyle=`hsl(${25+random()*6} 23% ${27+random()*9}%)`;
      ctx.fillRect(x+1,y+2,71,47);ctx.fillStyle='#251e1855';ctx.fillRect(x+1,y+47,71,3);
    }
  }
  const result = new THREE.CanvasTexture(canvas);
  result.colorSpace = THREE.SRGBColorSpace; result.wrapS = result.wrapT = THREE.RepeatWrapping;
  result.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 8);
  return result;
}

function makeMaterials() {
  const plaster = texture('render'), brick = texture('brick'), roof = texture('roof');
  const make = (settings) => new THREE.MeshStandardMaterial({ roughness: .88, side: THREE.DoubleSide, ...settings });
  const renderGround = make({ color: '#ffffff', map: plaster });
  renderGround.onBeforeCompile = (shader) => {
    shader.uniforms.brickTexture = { value: brick };
    shader.vertexShader = 'varying float localHeight;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nlocalHeight = position.y;');
    shader.fragmentShader = 'uniform sampler2D brickTexture;\nvarying float localHeight;\n' + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', '#include <map_fragment>\nif (localHeight < 0.85) { diffuseColor.rgb = texture2D(brickTexture, vMapUv).rgb; }');
  };
  renderGround.customProgramCacheKey = () => 'ground-render-brick-v1';
  const materialMap = {
    groundRender: renderGround, render: make({color:'#ffffff',map:plaster}),
    interior: make({color:'#eeebe1'}), roof: make({color:'#ffffff',map:roof}),
    trim:make({color:'#e9e8de'}), frame:make({color:'#f4f4eb',roughness:.5}),
    glass:make({color:'#618d98',roughness:.22,metalness:.1,transparent:true,opacity:.48,depthWrite:false}),
    door:make({color:'#8d9e86',roughness:.68}),stairs:make({color:'#bcad91'}),
  };
  const clay = make({color:'#eeeae0'});
  const clayGlass = make({color:'#abb4b1',transparent:true,opacity:.5,depthWrite:false});
  const changed = make({color:'#c59961'}), changedGlass=make({color:'#c59961',transparent:true,opacity:.6,depthWrite:false});
  return { materialMap, clay, clayGlass, changed, changedGlass };
}

function createHouse(model, scheme, materials) {
  const root = new THREE.Group(); root.name = scheme;
  const floorGroups = {ground:new THREE.Group(),first:new THREE.Group()};
  root.add(floorGroups.ground,floorGroups.first); root.userData.floors = floorGroups;
  for (const item of model.meshes) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(item.positions,3));
    geometry.setAttribute('normal',new THREE.Float32BufferAttribute(item.normals,3));
    geometry.setAttribute('uv',new THREE.Float32BufferAttribute(item.uvs,2));
    geometry.computeBoundingSphere();
    const key = item.material === 'render' && item.floor === 'ground' ? 'groundRender' : item.material;
    const mesh = new THREE.Mesh(geometry,materials.materialMap[key]);
    mesh.userData = { ...item, positions:undefined, normals:undefined, uvs:undefined,
      scheme, normalMaterial:materials.materialMap[key] };
    mesh.name = `${scheme} / ${item.floor} / ${item.layer}`;
    mesh.castShadow = item.material !== 'glass'; mesh.receiveShadow = true;
    floorGroups[item.floor].add(mesh); meshes.push(mesh);
    const line = new THREE.LineSegments(new THREE.EdgesGeometry(geometry,27),new THREE.LineBasicMaterial({color:'#3b4238',transparent:true,opacity:.16}));
    line.userData = { mesh }; mesh.add(line); edgeLines.push(line);
  }
  return root;
}

function worldPoint(x,y) { return new THREE.Vector2((x-project.config.origin_mm[0])/1000,-(y-project.config.origin_mm[1])/1000); }
function floorPlate(points,level,scheme) {
  const shape=new THREE.Shape(points.map(([x,y])=>worldPoint(x,y)));
  const geometry = new THREE.ShapeGeometry(shape);
  // ShapeGeometry XY -> horizontal XZ; keep orientation because material is double-sided.
  const pos=geometry.getAttribute('position');
  for(let i=0;i<pos.count;i++) { const z=pos.getY(i);pos.setXYZ(i,pos.getX(i),.016,z); }
  geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:'#d9d2be',roughness:1,side:THREE.DoubleSide}));
  mesh.receiveShadow=true;mesh.userData={floor:level,scheme};guideRoot.add(mesh);plates.push(mesh);
}
function makeGuides() {
  guideRoot=new THREE.Group();scene.add(guideRoot);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardMaterial({color:'#e4e9df',roughness:1}));
  ground.rotation.x=-Math.PI/2;ground.position.y=-.08;ground.receiveShadow=true;guideRoot.add(ground);
  buildPlot();
  for(const plate of project.config.floor_plates)floorPlate(plate.points,plate.floor,plate.scheme);
}

function buildPlot() {
  if(plotRoot) {
    guideRoot.remove(plotRoot);
    plotRoot.traverse(obj=>{obj.geometry?.dispose();if(obj.material){obj.material.map?.dispose();obj.material.dispose();}});
  }
  plotRoot=new THREE.Group();plotRoot.name='Estimated plot';guideRoot.add(plotRoot);
  const b=plotBounds(plot);
  function rectangle(w,d,x,z,color,y=-.02) {
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,d),new THREE.MeshStandardMaterial({color,roughness:1,side:THREE.DoubleSide}));
    mesh.rotation.x=-Math.PI/2;mesh.position.set(x,y,z);mesh.receiveShadow=true;plotRoot.add(mesh);return mesh;
  }
  rectangle(plot.width,plot.depth,b.cx,b.cz,'#adb994');
  plotRoot.add(createDriveway(plot,project.plot.driveway,Math.min(renderer.capabilities.getMaxAnisotropy(),8)));
  const patioDepth=Math.min(3,Math.max(0,HOUSE.rear-b.rear));
  if(patioDepth>0)rectangle(Math.min(10,plot.width),patioDepth,b.cx,HOUSE.rear-patioDepth/2,'#c7c2ae',-.007);
  rectangle(plot.width+12,5,b.cx,b.front+4,'#a5aaa2',-.06);
  rectangle(plot.width+12,1.5,b.cx,b.front+.75,'#cccfc2',-.05);
  rectangle(plot.width+12,9,b.cx,b.rear-4.5,'#a4b88a',-.06);
  // Hedge is a symbolic strip at the owner-confirmed rear extent; its height is illustrative.
  const hedge=new THREE.Mesh(new THREE.BoxGeometry(plot.width,1.6,.65),new THREE.MeshStandardMaterial({color:'#657c51',roughness:1}));
  hedge.position.set(b.cx,.8,b.rear+.32);plotRoot.add(hedge);
  boundaryRoot=new THREE.Group();plotRoot.add(boundaryRoot);
  const points=[[b.left,b.front],[b.left,b.rear],[b.right,b.rear],[b.right,b.front],[b.left,b.front]].map(([x,z])=>new THREE.Vector3(x,.04,z));
  const border=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineDashedMaterial({color:'#8e794b',dashSize:.7,gapSize:.32}));
  border.computeLineDistances();boundaryRoot.add(border);
  for(const [x,z] of [[b.left,b.front],[b.left,b.rear],[b.right,b.rear],[b.right,b.front]]) {
    const marker=new THREE.Mesh(new THREE.CylinderGeometry(.10,.10,.4,10),new THREE.MeshStandardMaterial({color:'#947d4d'}));
    marker.position.set(x,.2,z);boundaryRoot.add(marker);
  }
  function label(text,x,z) {
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    ctx.font='500 32px Segoe UI, sans-serif';canvas.width=Math.ceil(ctx.measureText(text).width)+38;canvas.height=72;
    ctx.fillStyle='#f7f5edf0';ctx.fillRect(0,0,canvas.width,72);
    ctx.fillStyle='#47553f';ctx.font='500 32px Segoe UI, sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,canvas.width/2,36);
    const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;
    const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map,depthTest:false,transparent:true,sizeAttenuation:false}));
    sprite.position.set(x,1,z);sprite.renderOrder=3;
    sprite.userData={plotLabel:true,pixels:[canvas.width/3,24]};boundaryRoot.add(sprite);
  }
  label(`≈ ${plot.depth.toFixed(1)} m · map estimate`,b.left-15,b.cz);
  label(`≈ ${plot.width.toFixed(1)} m`,b.cx,b.front+1);
  label('FIELD HEDGE · approximate line',b.cx,b.rear-2);
  label('STREET',b.cx,b.front+7);
  updatePlotUI();
}

function updatePlotUI() {
  const b=plotBounds(plot);
  $('plot-dimensions').textContent=`≈ ${plot.depth.toFixed(1)} × ${plot.width.toFixed(1)} m`;
  $('plot-area').textContent=`≈ ${(Math.round(b.area/10)*10).toLocaleString()} m² · rectangular estimate`;
  $('plot-view-note').hidden=state.scope==='house'||!state.guides;
  $('plot-view-note').textContent=state.scope==='drive'?'Photo-informed layout · approximate edges':'Indicative boundary · flat ground · map estimates';
  if(boundaryRoot){boundaryRoot.visible=state.plotVisible;boundaryRoot.children.forEach(obj=>{if(obj.userData.plotLabel)obj.visible=state.scope==='plot';});}
  document.querySelectorAll('[data-scope]').forEach(button=>{const on=button.dataset.scope===state.scope;button.classList.toggle('selected',on);button.setAttribute('aria-pressed',on)});
}

function populatePlotForm() {
  for(const [key,id] of Object.entries({depth:'plot-depth',width:'plot-width',setback:'plot-setback',leftGap:'plot-left-gap'}))$(id).value=plot[key];
  $('plot-form-error').hidden=true;
}

function savePlot() {
  try {localStorage.setItem(STORAGE_KEY,JSON.stringify(plot));$('plot-save-status').textContent='Saved in this browser. These remain unverified study dimensions.';}
  catch {$('plot-save-status').textContent='Browser storage is unavailable. Changes apply for this visit only.';}
}

let materials;
function setup3D() {
  const container=$('viewer');
  renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true,alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
  container.appendChild(renderer.domElement);
  renderer.domElement.addEventListener('webglcontextlost',(event)=>{event.preventDefault();failure(new Error('The graphics connection was lost. Reload to restart the model.'));});
  scene=new THREE.Scene();scene.background=new THREE.Color('#e6ebe2');scene.fog=new THREE.Fog('#e6ebe2',600,1400);
  camera=new THREE.PerspectiveCamera(35,1,.1,2000);
  controls=new OrbitControls(camera,renderer.domElement);controls.target.set(.2,2.6,-1.2);
  controls.enableDamping=false;controls.minDistance=5;controls.maxDistance=900;controls.maxPolarAngle=Math.PI*.495;
  controls.addEventListener('change',schedule);
  scene.add(new THREE.HemisphereLight('#f7f8ed','#b0b49e',2.5));
  const sun=new THREE.DirectionalLight('#ffeed7',3.3);sun.position.set(-12,20,12);sun.castShadow=true;
  sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-21,right:21,top:24,bottom:-22,near:.5,far:80});
  sun.shadow.normalBias=.035;sun.shadow.bias=-.0001;sun.shadow.radius=3;scene.add(sun);
  const fill=new THREE.DirectionalLight('#e1efff',.8);fill.position.set(14,10,-12);scene.add(fill);
  materials=makeMaterials();modelMaterials.push(...Object.values(materials.materialMap));
  roots={existing:createHouse(project.models.existing,'existing',materials),proposed:createHouse(project.models.proposed,'proposed',materials)};
  scene.add(roots.existing,roots.proposed);makeGuides();
  new ResizeObserver(resize).observe(container);
  let pointerStart;
  renderer.domElement.addEventListener('pointerdown',(event)=>{pointerStart=[event.clientX,event.clientY]});
  renderer.domElement.addEventListener('pointerup',(event)=>{
    if(!pointerStart || Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])>5 || event.button!==0)return;
    pick(event);
  });
  setView('perspective');resize();
}

function resize() {
  if(!renderer)return;
  width=$('viewer').clientWidth;height=$('viewer').clientHeight;
  renderer.setSize(width,height);
  const previousFit=Math.max(1,.95/camera.aspect);
  camera.aspect=(state.compare?width/2:width)/height;
  const nextFit=Math.max(1,.95/camera.aspect);
  camera.position.sub(controls.target).multiplyScalar(nextFit/previousFit).add(controls.target);
  camera.updateProjectionMatrix();controls.update();schedule();
  if(state.scope!=='house')setView(state.view);
}
function showScheme(scheme) {
  roots.existing.visible=scheme==='existing';roots.proposed.visible=scheme==='proposed';
  for(const plate of plates) {
    plate.visible=state.guides&&plate.userData.scheme===scheme&&(state.floor==='all'||state.floor===plate.userData.floor);
    plate.position.y=plate.userData.floor==='first'?state.height+(state.explode?3:0):0;
  }
}
function render() {
  scheduled=false;if(!renderer)return;
  const screenUnit=2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))/height;
  boundaryRoot?.children.forEach(obj=>{if(obj.userData.plotLabel){const [w,h]=obj.userData.pixels;obj.scale.set(w*screenUnit,h*screenUnit,1);}});
  renderer.setScissorTest(true);
  if(state.compare) {
    const half=Math.floor(width/2);
    for(const [index,scheme] of ['existing','proposed'].entries()) {
      const x=index*half,w=index?width-half:half;
      showScheme(scheme);renderer.setViewport(x,0,w,height);renderer.setScissor(x,0,w,height);renderer.render(scene,camera);
    }
  } else {
    showScheme(state.scheme);renderer.setViewport(0,0,width,height);renderer.setScissor(0,0,width,height);renderer.render(scene,camera);
  }
  renderer.setScissorTest(false);
}
function schedule() {if(!scheduled){scheduled=true;requestAnimationFrame(render)}}

function setView(view) {
  state.view=view;
  const b=plotBounds(plot);
  const target=state.scope==='plot'?new THREE.Vector3(b.cx,2,b.cz):state.scope==='drive'?new THREE.Vector3(b.cx,1.5,(HOUSE.front-3+b.front)/2):new THREE.Vector3(.4,(state.floor==='first'?state.height+1.2:2.6)+(state.explode?1.5:0),-1.5);
  controls.target.copy(target);
  const distance=(state.compare?48:33)*Math.max(1,.95/camera.aspect);
  const views={perspective:[distance*.67,distance*.5,distance*.76],front:[0,3,distance],rear:[0,3,-distance],top:[0,distance,.01]};
  if(state.scope!=='house') {
    const drive=state.scope==='drive';
    const direction=new THREE.Vector3(...{perspective:drive?[-.65,1.35,1.2]:[.9,1.25,1.2],front:[0,.18,1],rear:[0,.18,-1],top:[0,1,.0001]}[view]).normalize();
    const right=new THREE.Vector3(0,1,0).cross(direction).normalize(),up=direction.clone().cross(right).normalize();
    const tangent=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
    let fit=10;
    for(const x of [b.left-(drive?1.5:22),b.right+(drive?1.5:5)])for(const y of [0,drive?9:12])for(const z of [drive?HOUSE.front-5:b.rear-4,b.front+(drive?3:9)]) {
      const p=new THREE.Vector3(x,y,z).sub(target),near=p.dot(direction);
      fit=Math.max(fit,near+Math.abs(p.dot(right))/(tangent*camera.aspect),near+Math.abs(p.dot(up))/tangent);
    }
    camera.position.copy(target).addScaledVector(direction,fit*1.12);
  } else camera.position.copy(target).add(new THREE.Vector3(...views[view]));
  controls.update();
  document.querySelectorAll('[data-view]').forEach(b=>{const on=b.dataset.view===view;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on)});
  $('orientation-label').textContent=view==='rear'?'REAR / GARDEN':view==='top'?'FRONT AT BOTTOM':'FRONT / STREET';
  schedule();
}

function update() {
  if(!roots)return;
  for(const root of Object.values(roots))root.userData.floors.first.position.y=state.height+(state.explode?3:0);
  for(const mesh of meshes) {
    const d=mesh.userData,roof=d.layer==='Roof'||d.layer==='Facia';
    mesh.visible=(state.floor==='all'||state.floor===d.floor)&&(!roof||state.roof);
    mesh.material=state.changes&&d.changed?(d.material==='glass'?materials.changedGlass:materials.changed):state.style==='clay'?(d.material==='glass'?materials.clayGlass:materials.clay):d.normalMaterial;
  }
  for(const line of edgeLines)line.visible=state.edges;
  guideRoot.visible=state.guides;
  updatePlotUI();
  $('compare-labels').hidden=!state.compare;$('compare-line').hidden=!state.compare;$('view-chip').hidden=state.compare;
  $('changed-legend').hidden=!state.changes;$('selection-label').hidden=true;
  $('compare-button').classList.toggle('active',state.compare);$('compare-button').setAttribute('aria-pressed',state.compare);
  $('view-eyebrow').textContent=state.compare?'THE POSSIBILITIES, SIDE BY SIDE':state.scheme==='existing'?'EXISTING HOUSE':'PROPOSED EXTENSION';
  $('view-title').textContent=state.compare?'Same perspective. Two possibilities.':state.scheme==='existing'?'A familiar place. A new perspective.':'Room for the way you want to live.';
  $('view-chip').textContent=`${state.scheme==='existing'?'Existing':'Proposed'} · ${state.scope==='plot'?'Whole plot (estimate)':state.scope==='drive'?'Driveway (approximate)':state.floor==='all'?'Whole house':state.floor==='first'?'First floor':'Ground floor'}`;
  const report=project.models[state.scheme].report;
  $('face-count').textContent=state.compare?['existing','proposed'].map(s=>project.models[s].report.faces.toLocaleString()).join(' / '):report.faces.toLocaleString();
  const bounds=metrics[state.scheme];
  $('model-size').textContent=state.compare?`${metrics.existing.width.toFixed(2)} / ${metrics.proposed.width.toFixed(2)} m`:`${bounds.width.toFixed(2)} × ${bounds.depth.toFixed(2)} m`;
  $('model-size').nextElementSibling.textContent=state.compare?'existing / proposed width':'model footprint bounds';
  $('face-count').nextElementSibling.textContent='source CAD faces';
  if(state.scope==='plot') {
    const b=plotBounds(plot);
    $('face-count').textContent=`≈ ${(Math.round(b.area/10)*10).toLocaleString()} m²`;
    $('face-count').nextElementSibling.textContent='indicative rectangular area';
    $('model-size').textContent=`≈ ${plot.depth.toFixed(1)} × ${plot.width.toFixed(1)} m`;
    $('model-size').nextElementSibling.textContent='map-estimated plot bounds';
  }
  $('roof-note').textContent=state.compare||state.scheme==='proposed'?'The source roof does not cover the upper extension. View notes ↗':'The photo’s front gable is absent from the CAD roof. View notes ↗';
  $('floor-height-value').textContent=`${state.height.toFixed(2)} m`;
  $('export-height').textContent=`${state.height.toFixed(2)} m`;
  for(const scheme of ['existing','proposed'])$('export-'+scheme).href=`/models/${scheme}.glb?floor_height=${state.height.toFixed(2)}`;
  resize();schedule();
}

function pick(event) {
  const rect=renderer.domElement.getBoundingClientRect();let x=event.clientX-rect.left,scheme=state.scheme,w=width;
  if(state.compare){w=width/2;scheme=x<w?'existing':'proposed';x=x%w;}
  selected.set(x/w*2-1,-(event.clientY-rect.top)/height*2+1);
  const raycaster=new THREE.Raycaster();raycaster.setFromCamera(selected,camera);
  roots[scheme].updateMatrixWorld(true);
  const hits=raycaster.intersectObjects(meshes.filter(m=>m.userData.scheme===scheme&&m.visible),false);
  if(hits.length){const d=hits[0].object.userData;$('selection-label').textContent=`${d.floor==='first'?'First':'Ground'} floor · ${d.layer}${d.changed?' · Changed surface':''}`;$('selection-label').hidden=false;}
  else $('selection-label').hidden=true;
}

function openReferences(){ $('references-dialog').showModal(); }
function bindControls() {
  document.querySelectorAll('[data-scope]').forEach(button=>button.addEventListener('click',()=>{
    state.scope=button.dataset.scope;
    if(state.scope!=='house'){state.guides=true;state.plotVisible=true;$('guides-toggle').checked=true;$('plot-toggle').checked=true;}
    update();setView(state.view);
  }));
  $('plot-toggle').addEventListener('change',event=>{state.plotVisible=event.target.checked;updatePlotUI();schedule()});
  $('edit-plot').addEventListener('click',()=>{populatePlotForm();$('plot-dialog').showModal()});
  $('plot-form').addEventListener('submit',event=>{
    event.preventDefault();
    try {
      plot=validatePlot(Object.fromEntries(new FormData(event.currentTarget)));savePlot();buildPlot();
      $('plot-form-error').hidden=true;update();setView(state.view);$('plot-dialog').close();toast('Plot dimensions applied. Estimates remain editable.');
    } catch(error){$('plot-form-error').textContent=error.message;$('plot-form-error').hidden=false;}
  });
  $('reset-plot').addEventListener('click',()=>{plot=validatePlot(project.plot.defaults);savePlot();populatePlotForm();buildPlot();update();setView(state.view)});
  for(const id of ['references-button','source-note','review-note'])$(id).addEventListener('click',openReferences);
  $('export-button').addEventListener('click',()=>$('export-dialog').showModal());
  document.querySelectorAll('.close-dialog').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
  document.querySelectorAll('[data-scheme]').forEach(button=>button.addEventListener('click',()=>{
    state.scheme=button.dataset.scheme;state.compare=false;
    document.querySelectorAll('[data-scheme]').forEach(b=>{const on=b===button;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on)});
    update();setView(state.view);
  }));
  $('compare-button').addEventListener('click',()=>{state.compare=!state.compare;update();setView(state.view)});
  document.querySelectorAll('[data-floor]').forEach(button=>button.addEventListener('click',()=>{
    state.floor=button.dataset.floor;
    document.querySelectorAll('[data-floor]').forEach(b=>{const on=b===button;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on)});
    update();
  }));
  document.querySelectorAll('[data-style]').forEach(button=>button.addEventListener('click',()=>{
    state.style=button.dataset.style;
    document.querySelectorAll('[data-style]').forEach(b=>{const on=b===button;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on)});update();
  }));
  for(const key of ['roof','explode','changes','edges','guides'])$(key+'-toggle').addEventListener('change',event=>{state[key]=event.target.checked;update();if(key==='explode')setView(state.view)});
  $('floor-height').addEventListener('input',event=>{state.height=Number(event.target.value);update()});
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.view)));
  $('reset-view').addEventListener('click',()=>setView('perspective'));
  $('snapshot').addEventListener('click',()=>{
    render();const link=document.createElement('a');link.download=`house-${state.compare?'comparison':state.scheme}-${state.view}.png`;
    renderer.domElement.toBlob(blob=>{if(!blob){toast('The snapshot could not be created.');return;}const url=URL.createObjectURL(blob);link.href=url;link.click();setTimeout(()=>URL.revokeObjectURL(url),3000);toast('View saved as a PNG.');},'image/png');
  });
}

function populateReferences() {
  const list=$('source-list');
  for(const scheme of ['existing','proposed']) {
    const r=project.models[scheme].report;
    sourceRow(r.filename,`${r.retained_faces.toLocaleString()} usable faces · ${r.degenerate_faces_skipped} zero-area faces skipped`);
  }
  for(const e of project.elevations)sourceRow(e.filename,`${e.entities} entities · Empty export`);
  function sourceRow(filename,status){
    const row=document.createElement('div');row.className='source-row';
    const a=document.createElement('a');a.href='/reference/'+encodeURIComponent(filename);a.textContent=filename+' ↓';
    const span=document.createElement('span');span.textContent=status;row.append(a,span);list.append(row);
  }
  for(const note of project.config.notes){const li=document.createElement('li');li.textContent=note;$('model-notes').append(li);}
  for(const note of project.plot.notes){const li=document.createElement('li');li.textContent=note;$('plot-source-notes').append(li);}
}

try {
  const response=await fetch('/api/project');if(!response.ok)throw new Error(`Model data could not be loaded (${response.status}).`);
  project=await response.json();configureHouse(project.config.house_bounds);state.height=project.config.floor_height_m;
  try {plot=readSavedPlot(localStorage,project.plot.defaults);} catch {plot=validatePlot(project.plot.defaults);}
  for(const scheme of ['existing','proposed']) {
    let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;
    for(const mesh of project.models[scheme].meshes)for(let i=0;i<mesh.positions.length;i+=3){const p=mesh.positions;minX=Math.min(minX,p[i]);maxX=Math.max(maxX,p[i]);minZ=Math.min(minZ,p[i+2]);maxZ=Math.max(maxZ,p[i+2]);}
    metrics[scheme]={width:maxX-minX,depth:maxZ-minZ};
  }
  populateReferences();bindControls();setup3D();update();$('loading').hidden=true;
} catch(error) {failure(error)}
