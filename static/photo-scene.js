import * as THREE from 'three';

export function createPhotoFeatures(features) {
  const root = new THREE.Group(); root.name = 'Photo-derived additions · estimated';
  for (const feature of features) {
    const group = new THREE.Group(); group.name = feature.label;
    group.position.set(...feature.position); group.rotation.y = THREE.MathUtils.degToRad(feature.rotation);
    group.userData.feature = feature;
    const [w,h,d] = feature.size;
    const material = new THREE.MeshStandardMaterial({color:feature.color,roughness:.95,flatShading:true});
    const mesh = (geometry, mat, y=0) => {const item=new THREE.Mesh(geometry,mat);item.position.y=y;item.castShadow=true;item.receiveShadow=true;item.userData.photoColor=mat.color.clone();group.add(item);return item;};
    if (feature.kind === 'tree') {
      mesh(new THREE.CylinderGeometry(Math.max(.04,w*.025),Math.max(.06,w*.04),h*.65,7),new THREE.MeshStandardMaterial({color:'#78644d',roughness:1}),h*.325);
      const canopy=mesh(new THREE.IcosahedronGeometry(1,1),material,h*.64);canopy.scale.set(w/2,h*.36,d/2);
    } else if (feature.kind === 'gable') {
      const shape = new THREE.Shape();shape.moveTo(-w/2,0);shape.lineTo(0,h);shape.lineTo(w/2,0);shape.closePath();
      const geometry=new THREE.ExtrudeGeometry(shape,{depth:d,bevelEnabled:false,steps:1});geometry.translate(0,0,-d/2);mesh(geometry,material);
    } else {
      mesh(new THREE.BoxGeometry(w,h,d),material,h/2);
    }
    root.add(group);
  }
  return root;
}

export function updatePhotoFeatures(root, state) {
  for (const group of root.children) {
    const feature=group.userData.feature;
    group.visible=(state.roof || feature.kind!=='gable') && (state.floor==='all' || (state.floor==='ground' ? feature.position[1]<state.height : feature.position[1]>=state.height));
    group.traverse(item=>{if(item.isMesh)item.material.color.copy(state.style==='clay'?new THREE.Color('#e5e1d5'):item.userData.photoColor);});
  }
}
