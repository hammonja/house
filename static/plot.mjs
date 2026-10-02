// Plot placement uses the same metre coordinates as the registered CAD models.
export let HOUSE;
export function configureHouse(bounds) { HOUSE = Object.freeze({...bounds}); }
export const STORAGE_KEY = 'house-design-plot-v1';
export function validatePlot(input) {
  const limits={depth:[25,200],width:[10,40],setback:[0,100],leftGap:[0,20]};
  const result={};
  for(const [key,[min,max]] of Object.entries(limits)) {
    if(input[key] === '' || input[key] == null)throw new Error('Enter all four plot dimensions.');
    const value=Number(input[key]);
    if(!Number.isFinite(value)||value<min||value>max)throw new Error(`${{depth:'Plot depth',width:'Plot width',setback:'Front setback',leftGap:'Left gap'}[key]} must be between ${min} and ${max} m.`);
    result[key]=value;
  }
  if(result.leftGap+HOUSE.right-HOUSE.left>result.width+.001)throw new Error('The existing house and left gap exceed the plot width. Check both values.');
  if(result.setback+HOUSE.front-HOUSE.rear>result.depth+.001)throw new Error('The existing house and front setback exceed the plot depth.');
  return result;
}
export function plotBounds(plot) {
  const left=HOUSE.left-plot.leftGap, right=left+plot.width;
  const front=HOUSE.front+plot.setback, rear=front-plot.depth;
  return {left,right,front,rear,cx:(left+right)/2,cz:(front+rear)/2,area:plot.width*plot.depth};
}
export function readSavedPlot(storage, defaults) {
  try {
    const saved=storage.getItem(STORAGE_KEY);
    return saved?validatePlot(JSON.parse(saved)):validatePlot(defaults);
  } catch {return validatePlot(defaults)}
}
