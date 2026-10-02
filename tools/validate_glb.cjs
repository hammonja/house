const fs = require('fs');
const path = require('path');
const validator = require('gltf-validator');
(async () => {
  for (const scheme of ['existing','proposed']) {
    const filename = `house-${scheme}.glb`;
    const bytes = new Uint8Array(fs.readFileSync(path.join(__dirname,'..','exports',filename)));
    const result = await validator.validateBytes(bytes, {uri:filename, maxIssues:0});
    console.log(filename, JSON.stringify({...result.issues,messages:result.issues.messages.filter(m=>m.severity<2)}));
    if (result.issues.numErrors || result.issues.numWarnings) process.exitCode=1;
  }
})().catch(error => { console.error(error); process.exitCode=1; });
