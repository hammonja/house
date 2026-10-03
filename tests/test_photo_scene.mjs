import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const threeUrl = moduleUrl(await fs.readFile(new URL('../static/vendor/three.module.js', import.meta.url), 'utf8'));
const THREE = await import(threeUrl);
const source = (await fs.readFile(new URL('../static/photo-scene.js', import.meta.url), 'utf8')).replace("from 'three'", `from '${threeUrl}'`);
const {createPhotoFeatures, updatePhotoFeatures} = await import(moduleUrl(source));
const kinds = ['tree','hedge','fence','paving','box','gable'];
const root = createPhotoFeatures(kinds.map((kind, index) => ({kind,label:kind,position:[index*10,0,-5],size:[2,4,3],rotation:0,color:'#758760'})));
assert.equal(root.children.length, 6);
for (const group of root.children) {
  const bounds = new THREE.Box3().setFromObject(group), size = bounds.getSize(new THREE.Vector3());
  assert.ok(Math.abs(bounds.min.y) < .0001, `${group.name} sits on its declared base`);
  assert.ok(size.y > 3.7 && size.y <= 4.001, `${group.name} respects its declared height`);
  assert.ok(size.x > 1.8 && size.x <= 2.001 && size.z > 2.7 && size.z <= 3.001);
  group.traverse(item => {if(item.isMesh)assert.ok(item.geometry.getAttribute('position').count < 300, 'geometry remains low poly');});
}
updatePhotoFeatures(root,{roof:false,floor:'all',style:'clay',height:2.7});
assert.equal(root.children[5].visible,false);
assert.equal(root.children[1].children[0].material.color.getHexString(),'e5e1d5');
updatePhotoFeatures(root,{roof:true,floor:'first',style:'materials',height:2.7});
assert.ok(root.children.every(item => !item.visible));
assert.equal(root.children[1].children[0].material.color.getHexString(),'758760');
console.log('Photo scene: six bounded low-poly shapes, roof/floor filters and material restoration passed.');
