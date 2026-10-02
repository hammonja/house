import * as THREE from 'three';
import { HOUSE, plotBounds } from './plot.mjs';

// Display geometry inferred from the supplied overhead and front photographs.
// u runs left to right as seen from the street; v runs from house to street.
export function createDriveway(plot, reference, anisotropy = 4) {
  const root = new THREE.Group(); root.name = 'Photo-informed driveway (approximate)';
  if (plot.setback <= 0) return root;
  const bounds = plotBounds(plot), back = HOUSE.front - .65, depth = bounds.front - back;
  const at = ([u,v]) => [bounds.left + u * plot.width, back + v * depth];
  let seed = 4417;
  const random = () => {seed = (1664525 * seed + 1013904223) >>> 0; return seed / 4294967296;};
  const material = (color, extra={}) => new THREE.MeshStandardMaterial({color, roughness:1, side:THREE.DoubleSide, ...extra});

  // A repeatable 200 x 100 mm herringbone pattern, mapped in metres so plot
  // edits change the paved area without stretching the individual blocks.
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1024;
  const ctx = canvas.getContext('2d'), unit = 64;
  ctx.fillStyle = '#777362'; ctx.fillRect(0,0,1024,1024);
  for(let y=-2;y<18;y++) for(let x=-2;x<18;x++) {
    const phase = ((x+y)%4+4)%4;
    if(phase !== 0 && phase !== 2) continue;
    const w=phase===0?unit*2:unit, h=phase===0?unit:unit*2;
    ctx.fillStyle=`hsl(${36+random()*5} 19% ${48+random()*13}%)`;
    ctx.fillRect(x*unit+1.3,y*unit+1.3,w-2.6,h-2.6);
    for(let i=0;i<35;i++) {
      ctx.fillStyle=random()>.5?'#eee0b720':'#514c3715';
      ctx.fillRect(x*unit+2+random()*(w-4),y*unit+2+random()*(h-4),2,2);
    }
  }
  const map=new THREE.CanvasTexture(canvas); map.colorSpace=THREE.SRGBColorSpace;
  map.wrapS=map.wrapT=THREE.RepeatWrapping; map.anisotropy=anisotropy;
  const paving=material('#dedbcd',{map}), edging=material('#766e59');
  const grass=material('#8c9d65'), soil=material('#859166');
  const timber=material('#847765'), posts=material('#6b6355');
  const leaves=material('#647d43');

  function surface(points,mat,y=-.006,normalized=true) {
    const vertices=normalized?points.map(at):points;
    const geometry=new THREE.ShapeGeometry(new THREE.Shape(vertices.map(([x,z])=>new THREE.Vector2(x,z))));
    const p=geometry.getAttribute('position'),uv=geometry.getAttribute('uv');
    for(let i=0;i<p.count;i++) {
      const x=p.getX(i),z=p.getY(i); p.setXYZ(i,x,y,z);
      uv.setXY(i,(x+z)/Math.SQRT2/1.6,(z-x)/Math.SQRT2/1.6);
    }
    geometry.computeVertexNormals();
    const mesh=new THREE.Mesh(geometry,mat); mesh.receiveShadow=true; root.add(mesh); return mesh;
  }
  function strip(a,b,w,mat,y=.005) {
    const dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz);
    if(length<.001)return;
    const nx=-dz/length*w/2,nz=dx/length*w/2;
    surface([[a[0]+nx,a[1]+nz],[b[0]+nx,b[1]+nz],[b[0]-nx,b[1]-nz],[a[0]-nx,a[1]-nz]],mat,y,false);
  }
  function box(w,h,d,x,z,mat,base=0) {
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);
    mesh.position.set(x,base+h/2,z);mesh.castShadow=true;mesh.receiveShadow=true;root.add(mesh);return mesh;
  }
  surface(reference.outline,paving);
  surface(reference.left_green,grass,-.005);
  surface(reference.right_bed,soil,-.005);
  // Borders around the angled edges and entrance, with no kerb blocking access.
  const outline=reference.outline.map(at);
  for(let i=1;i<outline.length;i++)strip(outline[i],outline[(i+1)%outline.length],.12,edging);
  strip(...reference.entrance.map(at),.18,edging);
  // The faint inset diamond visible in the overhead image is illustrative.
  if(plot.setback>4) {
    const [x,z]=at([.52,.32]),r=Math.min(.78,depth*.09);
    const diamond=[[x,z-r],[x+r,z],[x,z+r],[x-r,z]];
    diamond.forEach((p,i)=>strip(p,diamond[(i+1)%4],.075,edging,.002));
  }
  // Timber panels close to the house, becoming hedging towards the street.
  const fenceLength=Math.min(4,plot.setback*.30);
  for(const x of [bounds.left+.06,bounds.right-.06]) {
    box(.07,1.15,fenceLength,x,back+fenceLength/2,timber);
    const count=Math.ceil(fenceLength/.15);
    for(let i=0;i<=count;i++)box(.095,1.20,.025,x,back+fenceLength*i/count,posts);
    for(let z=back;z<=back+fenceLength;z+=1.8)box(.13,1.27,.13,x,z,posts);
  }
  const hedgeStart=back+fenceLength,hedgeEnd=bounds.front;
  if(hedgeEnd>hedgeStart)box(.40,1.0,hedgeEnd-hedgeStart,bounds.left+.20,(hedgeStart+hedgeEnd)/2,leaves);
  const leftEntrance=at(reference.entrance[0]);
  box(Math.max(.01,leftEntrance[0]-bounds.left),.9,.42,(bounds.left+leftEntrance[0])/2,bounds.front-.21,leaves);
  // One symbolic tree; the photographs do not determine species or height.
  if(plot.setback>3) {
    const [x,z]=at(reference.tree),radius=Math.min(1.7,plot.width*.115,depth*.14);
    const trunk=new THREE.Mesh(new THREE.CylinderGeometry(.10,.16,3.1,9),material('#75614b'));
    trunk.position.set(x,1.55,z);trunk.castShadow=true;root.add(trunk);
    for(let i=0;i<13;i++) {
      const angle=i*2.39996,spread=i===0?0:radius*.52;
      const crown=new THREE.Mesh(new THREE.IcosahedronGeometry(radius*(.62+random()*.20),1),material(i%3===0?'#7b8b4e':i%3===1?'#647c43':'#8a965d'));
      crown.position.set(x+Math.cos(angle)*spread,3.15+random()*.65,z+Math.sin(angle)*spread);
      crown.scale.y=.83;crown.rotation.y=angle;crown.castShadow=true;crown.receiveShadow=true;root.add(crown);
    }
  }
  // Continue the same paved access across the public footpath to the road.
  const [a,b]=reference.entrance.map(at);
  surface([[a[0],bounds.front],[b[0],bounds.front],[b[0],bounds.front+1.5],[a[0],bounds.front+1.5]],material('#b8b5a8'),-.035,false);
  return root;
}
