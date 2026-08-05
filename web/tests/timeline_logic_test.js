// タイムラインの区間ロジックだけを取り出して検証する（DOM 非依存の部分）
const EPS=0.01, MINW=0.02;
function complement(drops,S,E){
  let ks=[], t=S;
  (drops||[]).map(d=>[Math.max(S,+d[0]),Math.min(E,+d[1])])
    .filter(d=>d[1]-d[0]>EPS).sort((a,b)=>a[0]-b[0])
    .forEach(d=>{ if(d[0]-t>EPS) ks.push([t,d[0]]); t=Math.max(t,d[1]); });
  if(E-t>EPS) ks.push([t,E]);
  return ks;
}
function currentDrops(keeps,S,E){
  let out=[], t=S;
  keeps.slice().sort((a,b)=>a[0]-b[0]).forEach(k=>{
    if(k[0]-t>EPS) out.push([+t.toFixed(3),+k[0].toFixed(3)]);
    t=Math.max(t,k[1]);
  });
  if(E-t>EPS) out.push([+t.toFixed(3),+E.toFixed(3)]);
  return out;
}
function splitAt(keeps,t){
  const ki=keeps.findIndex(k=>t>k[0]+MINW&&t<k[1]-MINW);
  if(ki<0) return false;
  const k=keeps[ki]; keeps.splice(ki,1,[k[0],t],[t,k[1]]); return true;
}
function dropRange(keeps,a,b){
  const ki=keeps.findIndex(k=>k[0]<b-EPS&&a<k[1]-EPS);
  if(ki<0) return false;
  const k=keeps[ki], parts=[];
  if(a-k[0]>MINW) parts.push([k[0],Math.max(a,k[0])]);
  if(k[1]-b>MINW) parts.push([Math.min(b,k[1]),k[1]]);
  keeps.splice(ki,1,...parts); return true;
}
let ok=0,ng=0;
function eq(name,got,want){
  const g=JSON.stringify(got),w=JSON.stringify(want);
  if(g===w){ok++;console.log('  OK  ',name);} else {ng++;console.log('  NG  ',name,'\n     得:',g,'\n     期:',w);}
}
const S=800,E=2022;
console.log('== 往復（drops -> keeps -> drops）==');
let d0=[[909.8,915],[1099.8,1103],[1647,1681]];
let k=complement(d0,S,E);
eq('keeps は4本', k.length, 4);
eq('drops に戻る', currentDrops(k,S,E), d0);
console.log('== カットが無ければ1本の連続バー ==');
eq('keeps=1本', complement([],S,E), [[S,E]]);
console.log('== スプリット ==');
k=complement([],S,E);
eq('中央で分割できる', splitAt(k,1400), true);
eq('分割後は2本', k, [[800,1400],[1400,2022]]);
eq('分割しても drops は空（見た目は黒くならない）', currentDrops(k,S,E), []);
eq('端では分割できない', splitAt(k,800), false);
console.log('== 分割した端をドラッグしてカット ==');
k[0][1]=1350;
eq('黒くなる区間ができる', currentDrops(k,S,E), [[1350,1400]]);
console.log('== 無音だけ落とす ==');
k=complement([],S,E);
eq('無音1本を落とす', dropRange(k,1000,1005), true);
eq('前後が残る', k, [[800,1000],[1005,2022]]);
eq('drops に反映', currentDrops(k,S,E), [[1000,1005]]);
console.log('== 既存の drops がある状態で無音を落とす ==');
k=complement(d0,S,E);
dropRange(k,1200,1204);
eq('drops が4件になる', currentDrops(k,S,E).length, 4);
console.log(`\n合計 OK=${ok} NG=${ng}`);
process.exit(ng?1:0);
