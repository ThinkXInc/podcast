#!/usr/bin/env python3
# web/preview_local.py — mac ローカルで生成物(contents/)を確認するスタンドアロン preview。
#
# 依存ゼロ（Python 標準ライブラリのみ）。本番の uWSGI / nginx / general/base.html には
# 一切依存しない。本番の雛形（templates/page.html, config/uwsgi.ini, nginx/*）は触らない。
#
# 動画がメイン。各動画の下に「切り出し全文」を出し、校正用PDFに近い配色で
# カット済み(確定)/カット推奨(未決)/事実確認/候補外/詰め候補(無音)/象徴的セリフ を
# すべて全文中にインライン表示する。
#
# 起動:  python3 web/preview_local.py        → http://127.0.0.1:8010/
# data:  既定は web/ の1つ上の data/。 環境変数 SITE_DATA_DIR で上書き可。

import os
import re
import json
import html
import mimetypes
import urllib.parse
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.realpath(
    os.environ.get("SITE_DATA_DIR") or os.path.join(os.path.dirname(HERE), "data")
)
PORT = int(os.environ.get("PORT", "8010"))

MEDIA_FILES = [
    ("final.mp4", "mp4(字幕あり)"),
    ("video_nosub.mp4", "mp4(字幕なし)"),
    ("audio.m4a", "m4a"),
    ("segment.ass", ".ass"),
]

PAGE_CSS = """
/* 既定はダーク（従来のレイアウト）。data-theme="light" でライトに切り替え */
:root { color-scheme: dark; }
:root[data-theme="light"] { color-scheme: light; }
body { font-family: -apple-system, "Hiragino Sans", sans-serif; margin: 24px auto;
       max-width: 960px; padding: 0 16px; line-height: 1.6;
       background:#1b1b1b; color:#e8e8e8; }
:root[data-theme="light"] body { background:#ffffff; color:#111111; }
h1 { font-size: 22px; } h2 { font-size: 18px; margin: 0 0 3px; }
a { color: #2563eb; text-decoration: none; } a:hover { text-decoration: underline; }
.crumb { font-size: 14px; margin-bottom: 16px; }
.crumb a { color:#8c8c8c; }
.meta { color: #ffffff; font-size: 15px; }
:root[data-theme="light"] .meta { color:#111111; }
/* テーマ切替ボタン（右上・最小限） */
.theme-btn { position:fixed; top:10px; right:12px; z-index:9; cursor:pointer;
             font-size:13px; color:#6b7280; border:1px solid #6b728066;
             border-radius:6px; padding:2px 8px; background:transparent; }
/* ライトでは「沈む＝薄い」方向を反転（濃→淡） */
:root[data-theme="light"] .box.summary { background:#f1f1f1; }
:root[data-theme="light"] .r-donespk { color:#c2c2c2; }
:root[data-theme="light"] .ann-donespk { color:#c2c2c2; }
:root[data-theme="light"] .ann-keep { color:#b8b8b8; }
:root[data-theme="light"] .trim.done { color:#c8c8c8; }
ul.ids { list-style: none; padding: 0; }
ul.ids li { padding: 9px 0; border-bottom: 1px solid #ccc4; }

.seg { border: 1px solid #ccc4; border-radius: 12px; padding: 16px 19px 21px;
       margin-bottom: 35px; }
.seghd { padding-left: 11px; margin-bottom: 13px; }
.seghd .rank { font-weight:700; }
video { width: 100%; max-width: 860px; display: block; border-radius: 6px;
        background: #000; margin: 5px 0 11px; }
.dl { font-size: 13px; margin-bottom: 13px; }
.dl a { margin-right: 16px; color: inherit; }

/* 要約・レビュー：少し行間をつける */
.box.summary { background:#292929; border-radius:5px;
               padding:11px 14px; margin:10px 0; font-size:14px; line-height:1.9; }
.box.summary p { margin:9px 0; }

/* 本文：行間を詰める */
.transcript { margin-top:16px; border-top:1px dashed #ccc6; padding-top:10px; }
.transcript h3 { font-size:14px; margin:3px 0 8px; }
.tp { margin:9px 0; line-height:1.7; }
.ts { color:#94a3b8; font-size:12px; font-variant-numeric:tabular-nums;
      display:block; margin-bottom:0px; }
.ts-link { cursor:pointer; color:#6b7280; }
.ts-link:hover { text-decoration:underline; }
/* 本文チャンク: クリックで直前から再生 */
.txt { cursor:pointer; border-radius:3px; }
.txt:hover { background:#2563eb14; box-shadow:0 0 0 2px #2563eb22; }
/* いま再生中の箇所（hoverと同系だが少し強め） */
.txt.playing { background:#2563eb2e; }
/* 理由の注釈: 該当箇所の直上に独立行で置く（本文の流れを邪魔しない・重ならない） */
.ann-label { display:block; font-size:10px; font-weight:700; line-height:1.35;
             margin:2px 0 0; opacity:.85; }
.ann-done{ color:#888888b3; } .ann-todo{ color:#e7a7bc; }
.ann-fact{ color:#c9eb00; }
.ann-spk{ color:#6b7280; } .ann-donespk{ color:#575757; }
/* 詰め: |← X秒 →| のみ。目立たないグレー（候補=グレー / 詰め済み=より見えにくい薄グレー）。クリックで直前から再生 */
.trim { cursor:pointer; color:#9ca3af; font-weight:700; font-size:12px;
        white-space:nowrap; padding:0 2px; border-radius:3px;
        font-variant-numeric:tabular-nums; }
.trim:hover { background:#9ca3af22; text-decoration:underline; }
.trim.done { color:#575757; }
.trim.done:hover { background:#9ca3af22; }

.chip { display:inline; font-size:12px; font-weight:700; padding:0 5px;
        border-radius:4px; margin:0 3px; white-space:normal; }
/* 線（下線・取り消し線・背景帯）は引かない。色だけで判別する。
   確定＝見えにくいグレー / 未決＝分類ごとの色 */
/* カット済み(確定) = ごく薄いグレー（読み飛ばし用） */
.r-done { color:#888888b3; }
.chip-done { background:#9ca3af; color:#fff; }
/* カット推奨(未決・gpt) = ピンク #e7a7bc（ラベルも本文も） */
.r-todo { color:#e7a7bc; }
.chip-todo { background:#6b7280; color:#fff; }
/* 会話相手(未決) = #30d8ff（ラベルも本文も） */
.r-spkopen { color:#30d8ff; }
.ann-spkopen { color:#30d8ff; }
/* その他の分類(未決) = 紫系 */
.r-other { color:#cdb4e2; }
.ann-other { color:#cdb4e2; }
/* 事実確認 = #c9eb00（ラベルも本文も。下線・背景なし） */
.r-fact { color:#c9eb00; }
.chip-fact { background:#ea580c; color:#fff; }
/* 会話相手の発言（cutlist由来・未処理） = #30d8ff */
.r-spk { color:#30d8ff; }
.chip-spk { background:#6b7280; color:#fff; }
/* カット済み(会話相手の発言) = 削除確定なので沈ませる（#575757 ユーザー指定） */
.r-donespk { color:#575757; }
/* カット/残す 確定ボタン（未決の注釈行に置く） */
.dbtn button { font-size:11px; margin-left:6px; padding:0 8px; cursor:pointer;
               background:transparent; color:inherit; border:1px solid #6b728088;
               border-radius:4px; line-height:1.6; }
.dbtn button:hover { background:#6b728033; }
/* 判断済み: 残す = ただのグレーのテキスト #5d5d5d（ユーザー指定）。本文への下線などは付けない */
.ann-keep { color:#5d5d5d; }
/* オーナー評価 = 金の星（見出し直下）。根拠の発言を併記 */
.rating { font-size:15px; margin:2px 0 2px; }
.rating .stars { color:#f59e0b; letter-spacing:.05em; }
.rating .rq { color:#94a3b8; font-size:13px; }
.rating.unrated { color:#94a3b8; font-size:13px; }
/* 象徴的セリフ = 色なしの太字（モノトーン方針） */
.r-quote { font-weight:700; }
/* 詰め候補(無音) = 紫の点マーカー（本文中に差し込む） */
.chip-trim { background:#7c3aed; color:#fff; font-size:11px; }
.chip-trim.muted { background:#a78bfa; }

/* 目次（縦並び。タイトル・尺・★＋ハイライト原文） */
.toc { margin:10px 0 22px; }
.toc-item { line-height:1.9; font-size:18px; margin-top:8px; }
.toc-item a { color:inherit; }
.toc-item a:hover { text-decoration:underline; }
.toc-q { font-size:14px; color:#9ca3af; line-height:1.7; margin-left:10px; }
.toc-sum { font-size:14px; line-height:1.8; margin:2px 0 4px 10px; opacity:.92; }
.seg { scroll-margin-top:42px; }
.editlink { font-size:13px; color:#6b7280; }
"""

# ---------- タイムライン編集ページ (/edit) ----------
# AE/Premiere 風。要点は「文字もバーも同じ時間軸の座標に置く」こと。
# x = (単語の開始時刻 - その行の先頭時刻) * pxPerSec で配置するので、
# 無音のぶんだけ文字と文字のあいだが空き、見た目がそのまま時間になる。
# バーは残す区間(keeps)で、切った区間はバーが消える。
EDIT_CSS = """
.etoolbar { position:sticky; top:0; z-index:8; display:flex; align-items:center; gap:14px;
            padding:8px 2px; background:#1b1b1b; border-bottom:1px solid #ccc3; font-size:13px; }
:root[data-theme="light"] .etoolbar { background:#ffffff; }
.etoolbar button { font-size:13px; padding:2px 12px; cursor:pointer; background:transparent;
                   color:inherit; border:1px solid #6b728088; border-radius:5px; }
.etoolbar button:hover { background:#6b728033; }
.etime { font-variant-numeric:tabular-nums; font-size:14px; min-width:78px; }
.ekeep { color:#9ca3af; font-variant-numeric:tabular-nums; }
.estatus { color:#9ca3af; margin-left:auto; }
.ezoom { color:#9ca3af; font-size:12px; }
.ehelp { color:#6b7280; font-size:12px; margin:6px 0 16px; line-height:1.9; }

/* 1行＝一定の時間幅。文字もバーも x = (t - 行頭時刻) * pxPerSec に置く。
   だから無音のぶんだけ文字と文字のあいだが空き、見た目がそのまま時間になる。 */
.row { position:relative; margin:0 0 4px; }
.rowtime { position:absolute; left:0; top:0; font-size:10px; color:#6b7280;
           font-variant-numeric:tabular-nums; }
.lane { position:relative; margin-left:52px; height:46px; }
.w { position:absolute; top:0; white-space:pre; font-size:14px; line-height:20px;
     cursor:pointer; border-radius:2px; }
.w.cut { color:#585858; }
:root[data-theme="light"] .w.cut { color:#c9c9c9; }
.w.playing { background:#2563eb33; }
.strip { position:absolute; left:0; right:0; top:24px; height:18px; cursor:crosshair; }
.bar { position:absolute; top:3px; height:9px; background:#7d8b9f; border-radius:2px; }
:root[data-theme="light"] .bar { background:#9aa6b6; }
.bar.sel { background:#2563eb; }
.gapline { position:absolute; top:7px; height:1px; background:#4b5563; }
:root[data-theme="light"] .gapline { background:#d4d4d4; }
.hoverline { position:absolute; top:-24px; bottom:-2px; width:1px; background:#9ca3af;
             display:none; pointer-events:none; }
.playline { position:absolute; top:-24px; bottom:-2px; width:2px; background:#e11d48;
            display:none; pointer-events:none; z-index:3; }
.tlabel { position:absolute; top:-38px; font-size:10px; color:#9ca3af; display:none;
          pointer-events:none; font-variant-numeric:tabular-nums; white-space:nowrap; }
"""

EDIT_JS = r"""
(function(){
var D=JSON.parse(document.getElementById('edit-data').textContent);
var EPS=0.01, MINW=0.02;
var audio=document.getElementById('aud');
var wrap=document.getElementById('rows');
var keeps=complement(D.drops||[]);
var undoStack=[], redoStack=[];
var playhead=D.segStart, selKi=-1, playing=false;
/* 既定140px/秒。実測で1行あたり平均31語≒62字なので、100px/秒だと1字13pxしか取れず
   14pxの文字が重なる。140なら1字18px前後になり、押し出し補正がほぼ働かない。 */
var pxPerSec=parseFloat(localStorage.getItem('edit_pps'))||140;
var rows=[], dragging=null, pendingDrag=null, saveTimer=null, laneW=0;

function complement(drops){
  var ks=[], t=D.segStart;
  (drops||[]).map(function(d){return [Math.max(D.segStart,+d[0]),Math.min(D.segEnd,+d[1])];})
    .filter(function(d){return d[1]-d[0]>EPS;})
    .sort(function(a,b){return a[0]-b[0];})
    .forEach(function(d){ if(d[0]-t>EPS) ks.push([t,d[0]]); t=Math.max(t,d[1]); });
  if(D.segEnd-t>EPS) ks.push([t,D.segEnd]);
  return ks;
}
function currentDrops(){
  var out=[], t=D.segStart;
  keeps.slice().sort(function(a,b){return a[0]-b[0];}).forEach(function(k){
    if(k[0]-t>EPS) out.push([+t.toFixed(3),+k[0].toFixed(3)]);
    t=Math.max(t,k[1]);
  });
  if(D.segEnd-t>EPS) out.push([+t.toFixed(3),+D.segEnd.toFixed(3)]);
  return out;
}
function fmt(t){
  t=Math.max(0,t-D.segStart);
  var m=Math.floor(t/60), s=t-m*60;
  return m+':'+(s<10?'0':'')+s.toFixed(2);
}
function fmtAbs(t){
  var h=Math.floor(t/3600), m=Math.floor((t%3600)/60), s=Math.floor(t%60);
  return (h?h+':':'')+(m<10&&h?'0':'')+m+':'+(s<10?'0':'')+s;
}

/* ---- 時間比例レイアウト。1行の時間幅 = laneW / pxPerSec ---- */
function build(){
  wrap.innerHTML='';
  rows=[];
  var probe=document.createElement('div');
  probe.className='lane'; wrap.appendChild(probe);
  laneW=probe.clientWidth||800; wrap.removeChild(probe);
  var rowSec=laneW/pxPerSec;
  var nRows=Math.ceil((D.segEnd-D.segStart)/rowSec);
  document.getElementById('ezoom').textContent=
    pxPerSec.toFixed(0)+'px/秒 ・ 1行'+rowSec.toFixed(1)+'秒 ・ '+nRows+'行';

  var wi=0;
  for(var r=0;r<nRows;r++){
    var t0=D.segStart+r*rowSec, t1=Math.min(D.segEnd,t0+rowSec);
    var row=document.createElement('div'); row.className='row';
    var lab=document.createElement('div'); lab.className='rowtime';
    lab.textContent=fmtAbs(t0); row.appendChild(lab);
    var lane=document.createElement('div'); lane.className='lane'; row.appendChild(lane);
    var strip=document.createElement('div'); strip.className='strip'; lane.appendChild(strip);

    /* 単語を時間位置に置く。重なるときだけ右へ最小限ずらす */
    var lastRight=-1e9, els=[];
    while(wi<D.words.length && D.words[wi].s < t1){
      var w=D.words[wi];
      if(w.e<=t0){ wi++; continue; }
      var x=(w.s-t0)*pxPerSec;
      if(x<lastRight) x=lastRight;
      var el=document.createElement('span');
      el.className='w'; el.textContent=w.t;
      el.style.left=x+'px';
      el.dataset.s=w.s; el.dataset.e=w.e;
      lane.appendChild(el);
      els.push(el);
      lastRight=x+el.offsetWidth;
      wi++;
    }
    wrap.appendChild(row);
    var R={t0:t0,t1:t1,lane:lane,strip:strip,els:els,bars:[]};
    rows.push(R);
    bindStrip(R);
  }
  renderBars(); styleWords(); movePlayhead();
}
function X(R,t){ return (t-R.t0)*pxPerSec; }
function T(R,x){ return R.t0 + x/pxPerSec; }

function renderBars(){
  rows.forEach(function(R){
    R.strip.innerHTML=''; R.bars=[];
    var g=document.createElement('div'); g.className='gapline';
    g.style.left='0px'; g.style.width=X(R,R.t1)+'px'; R.strip.appendChild(g);
    keeps.forEach(function(k,ki){
      if(k[1]<=R.t0||k[0]>=R.t1) return;
      var a=Math.max(k[0],R.t0), b=Math.min(k[1],R.t1);
      var x0=X(R,a), x1=X(R,b);
      var bar=document.createElement('div');
      bar.className='bar'+(ki===selKi?' sel':'');
      bar.style.left=x0+'px'; bar.style.width=Math.max(1,x1-x0)+'px';
      R.strip.appendChild(bar);
      R.bars.push({ki:ki,x0:x0,x1:x1,edgeS:(k[0]>=R.t0-1e-9),edgeE:(k[1]<=R.t1+1e-9)});
    });
    R.hover=document.createElement('div'); R.hover.className='hoverline'; R.strip.appendChild(R.hover);
    R.play=document.createElement('div'); R.play.className='playline'; R.strip.appendChild(R.play);
    R.tlab=document.createElement('div'); R.tlab.className='tlabel'; R.strip.appendChild(R.tlab);
  });
}
function inKeep(t){ return keeps.some(function(k){return k[0]<=t&&t<k[1];}); }
function styleWords(){
  rows.forEach(function(R){
    R.els.forEach(function(el){
      var mid=(+el.dataset.s + +el.dataset.e)/2;
      el.classList.toggle('cut', !inKeep(mid));
    });
  });
  var kept=keeps.reduce(function(a,k){return a+(k[1]-k[0]);},0);
  var m=Math.floor(kept/60), s=Math.round(kept-m*60);
  document.getElementById('ekeep').textContent='残り尺 '+m+'分'+(s<10?'0':'')+s+'秒';
}
function movePlayhead(){
  rows.forEach(function(R){ R.play.style.display='none'; });
  var R=rows.find(function(R){return R.t0<=playhead&&playhead<R.t1;})||rows[rows.length-1];
  if(R){ R.play.style.left=X(R,playhead)+'px'; R.play.style.display='block'; }
  document.getElementById('etime').textContent=fmt(playhead);
}
function highlight(t){
  document.querySelectorAll('.w.playing').forEach(function(x){x.classList.remove('playing');});
  var R=rows.find(function(R){return R.t0<=t&&t<R.t1;});
  if(!R) return;
  var best=null;
  R.els.forEach(function(el){ if(+el.dataset.s<=t+0.01&&(!best||+el.dataset.s>+best.dataset.s)) best=el; });
  if(best&&t-(+best.dataset.s)<10) best.classList.add('playing');
}

/* ---- 編集 ---- */
function pushUndo(){ undoStack.push(JSON.stringify(keeps)); if(undoStack.length>200)undoStack.shift(); redoStack=[]; }
function afterEdit(){ renderBars(); styleWords(); movePlayhead(); scheduleSave(); }
function undo(){ if(!undoStack.length)return; redoStack.push(JSON.stringify(keeps));
  keeps=JSON.parse(undoStack.pop()); selKi=-1; afterEdit(); }
function redo(){ if(!redoStack.length)return; undoStack.push(JSON.stringify(keeps));
  keeps=JSON.parse(redoStack.pop()); selKi=-1; afterEdit(); }
function splitAt(t){
  var ki=keeps.findIndex(function(k){return t>k[0]+MINW&&t<k[1]-MINW;});
  if(ki<0) return;
  pushUndo();
  var k=keeps[ki];
  keeps.splice(ki,1,[k[0],t],[t,k[1]]);
  selKi=-1; afterEdit();
}
function setStatus(s){ document.getElementById('estatus').textContent=s; }
function scheduleSave(){ setStatus('未保存'); clearTimeout(saveTimer); saveTimer=setTimeout(doSave,700); }
function doSave(){
  setStatus('保存中…');
  fetch('/edit_save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:D.id,index:D.index,drops:currentDrops()})})
  .then(function(r){ setStatus(r.ok?'保存済み（動画は render 再実行で反映）':'保存失敗'); })
  .catch(function(){ setStatus('保存失敗'); });
}

/* ---- 再生（カット区間はスキップ） ---- */
function tick(){
  if(!playing) return;
  var t=audio.currentTime;
  if(t>=D.segEnd){ stopPlay(); return; }
  if(!inKeep(t)){
    var nk=keeps.find(function(k){return k[0]>t;});
    if(!nk){ stopPlay(); return; }
    audio.currentTime=nk[0]+0.001;
  }
  playhead=audio.currentTime;
  movePlayhead(); highlight(playhead);
  requestAnimationFrame(tick);
}
function startPlay(){
  if(playing||!audio) return;
  if(!inKeep(playhead)){
    var nk=keeps.find(function(k){return k[0]>=playhead;});
    playhead=nk?nk[0]:(keeps[0]?keeps[0][0]:D.segStart);
  }
  audio.currentTime=playhead;
  audio.play().then(function(){ playing=true;
    document.getElementById('ebtn').textContent='∎ 停止'; requestAnimationFrame(tick);
  }).catch(function(){ setStatus('再生できません（音源なし）'); });
}
function stopPlay(){
  if(audio) audio.pause();
  playing=false;
  document.getElementById('ebtn').textContent='▶ 再生';
  document.querySelectorAll('.w.playing').forEach(function(x){x.classList.remove('playing');});
}
document.getElementById('ebtn').onclick=function(){ playing?stopPlay():startPlay(); };

/* ---- ストリップ操作 ---- */
function edgesAt(R,x){
  var out=[];
  R.bars.forEach(function(b){
    if(b.edgeS&&Math.abs(x-b.x0)<6) out.push({ki:b.ki,which:0});
    if(b.edgeE&&Math.abs(x-b.x1)<6) out.push({ki:b.ki,which:1});
  });
  return out;
}
function bindStrip(R){
  R.strip.addEventListener('mousemove',function(ev){
    if(dragging||pendingDrag) return;
    var x=ev.clientX-R.strip.getBoundingClientRect().left;
    R.hover.style.left=x+'px'; R.hover.style.display='block';
    R.tlab.style.left=(x+4)+'px'; R.tlab.style.display='block';
    R.tlab.textContent=fmt(T(R,x));
    R.strip.style.cursor=edgesAt(R,x).length?'ew-resize':'crosshair';
  });
  R.strip.addEventListener('mouseleave',function(){
    R.hover.style.display='none'; R.tlab.style.display='none';
  });
  R.strip.addEventListener('mousedown',function(ev){
    ev.preventDefault();
    var x=ev.clientX-R.strip.getBoundingClientRect().left;
    var cand=edgesAt(R,x);
    if(cand.length===1){ pushUndo(); dragging={R:R,ki:cand[0].ki,which:cand[0].which}; }
    else if(cand.length>1){ pendingDrag={R:R,cand:cand,x0:ev.clientX}; }
    else{
      playhead=T(R,x);
      var hit=R.bars.find(function(b){return x>=b.x0&&x<=b.x1;});
      selKi=hit?hit.ki:-1;
      renderBars(); movePlayhead();
      if(playing) audio.currentTime=playhead;
    }
  });
}
document.addEventListener('mousemove',function(ev){
  if(pendingDrag){
    var dx=ev.clientX-pendingDrag.x0;
    if(Math.abs(dx)>=3){
      var pick=null;
      pendingDrag.cand.forEach(function(c){
        if(dx>0&&c.which===0) pick=c;
        if(dx<0&&c.which===1&&!pick) pick=c;
      });
      pushUndo();
      dragging={R:pendingDrag.R,ki:(pick||pendingDrag.cand[0]).ki,
                which:(pick||pendingDrag.cand[0]).which};
      pendingDrag=null;
    }
    return;
  }
  if(!dragging) return;
  var R=dragging.R;
  var t=T(R, ev.clientX-R.strip.getBoundingClientRect().left);
  var k=keeps[dragging.ki];
  if(dragging.which===0){
    var lo=dragging.ki>0?keeps[dragging.ki-1][1]:D.segStart;
    k[0]=Math.min(Math.max(t,lo),k[1]-MINW);
  }else{
    var hi=dragging.ki<keeps.length-1?keeps[dragging.ki+1][0]:D.segEnd;
    k[1]=Math.max(Math.min(t,hi),k[0]+MINW);
  }
  renderBars(); styleWords(); movePlayhead();
});
document.addEventListener('mouseup',function(){
  if(pendingDrag) pendingDrag=null;
  if(dragging){ dragging=null; scheduleSave(); }
});

/* ---- 単語クリックで頭出し ---- */
wrap.addEventListener('click',function(ev){
  var el=ev.target.closest('.w'); if(!el) return;
  playhead=+el.dataset.s; movePlayhead();
  if(playing) audio.currentTime=playhead;
});

/* ---- ズーム ---- */
function setZoom(v){
  pxPerSec=Math.max(20,Math.min(600,v));
  localStorage.setItem('edit_pps',pxPerSec);
  build();
}
document.getElementById('ezin').onclick=function(){ setZoom(pxPerSec*1.4); };
document.getElementById('ezout').onclick=function(){ setZoom(pxPerSec/1.4); };

/* ---- キーボード ---- */
document.addEventListener('keydown',function(e){
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  if(e.code==='Space'){ e.preventDefault(); playing?stopPlay():startPlay(); }
  else if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='d'){ e.preventDefault(); splitAt(playhead); }
  else if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){ e.preventDefault(); e.shiftKey?redo():undo(); }
  else if((e.metaKey||e.ctrlKey)&&(e.key==='='||e.key==='+')){ e.preventDefault(); setZoom(pxPerSec*1.4); }
  else if((e.metaKey||e.ctrlKey)&&e.key==='-'){ e.preventDefault(); setZoom(pxPerSec/1.4); }
  else if((e.key==='Delete'||e.key==='Backspace')&&selKi>=0){
    e.preventDefault(); pushUndo(); keeps.splice(selKi,1); selKi=-1; afterEdit();
  }
});
var rsz=null;
window.addEventListener('resize',function(){ clearTimeout(rsz); rsz=setTimeout(build,180); });
build();
})();
"""


def render_edit(idv, seg_q):
    """タイムライン編集ページ。文字もバーも時間軸上の同じ座標に置く（時間比例レイアウト）。"""
    if not idv or "/" in idv or idv.startswith("."):
        return None
    base = os.path.join(DATA_DIR, idv)
    segs = _load_json(os.path.join(base, "segments.json"), {}).get("segments", [])
    try:
        idx = int(seg_q)
    except (TypeError, ValueError):
        return None
    sg = next((x for x in segs if x.get("index") == idx), None)
    if sg is None:
        return None
    s, e = float(sg["start_sec"]), float(sg["end_sec"])
    drops = sg.get("drops") or []
    tr = _load_json(os.path.join(base, "transcript.json"), {})

    # 単語は {t: 表記, s: 開始, e: 終了} だけ渡す。描画位置はブラウザ側で時刻から決める。
    words = []
    for w in (tr.get("word_segments") or []):
        st, en = w.get("start"), w.get("end")
        if st is None or en is None or not (s <= st < e):
            continue
        tok = (w.get("word") or "").strip()
        if tok:
            words.append({"t": tok, "s": round(float(st), 3), "e": round(float(en), 3)})
    words.sort(key=lambda w: w["s"])

    src_name = None
    if os.path.isdir(base):
        names = sorted(os.listdir(base))
        src_name = next((n for n in names if n.lower().endswith(".m4a")), None) \
            or next((n for n in names if n.lower().endswith((".mp3", ".wav", ".mp4"))), None)

    data = json.dumps({"id": idv, "index": idx, "segStart": s, "segEnd": e,
                       "drops": drops, "words": words},
                      ensure_ascii=False).replace("</", "<\\/")
    if src_name:
        audio_html = (f"<audio id='aud' src='/media?p={urllib.parse.quote(idv + '/' + src_name)}'"
                      " preload='metadata' style='display:none'></audio>")
    else:
        audio_html = ("<p class='meta'>元音源が見つからないため再生できません（編集と保存は可能）。</p>"
                      "<audio id='aud' style='display:none'></audio>")

    dur = int(round(e - s))
    body = (
        f"<style>{EDIT_CSS}</style>"
        f"<div class='crumb'><a href='/id?id={urllib.parse.quote(idv)}#seg{idx}'>← {esc(idv)} 生成物</a></div>"
        f"<h1>{idx}　{esc(sg.get('title') or '')}</h1>"
        f"<div class='meta'>元音源 {fmt_time(s)}〜{fmt_time(e)}（{dur // 60}分{dur % 60}秒）"
        f" ・ 単語 {len(words)}</div>"
        + audio_html +
        "<div class='etoolbar'>"
        "<button id='ebtn'>▶ 再生</button>"
        "<span class='etime' id='etime'>0:00.00</span>"
        "<span class='ekeep' id='ekeep'></span>"
        "<button id='ezout'>−</button><button id='ezin'>＋</button>"
        "<span class='ezoom' id='ezoom'></span>"
        "<span class='estatus' id='estatus'>保存済み</span>"
        "</div>"
        "<div class='ehelp'>"
        "文字は時間軸上の位置に置いてあるので、<b>文字と文字のあいだの空白がそのまま無音の長さ</b>です。"
        "下のバーが残る区間で、切ると消えます。"
        "Space 再生/停止（カット部はスキップ）・⌘D スプリット・バー端をドラッグでトリム・"
        "バーをクリックで選択して Delete で削除・⌘Z 取り消し・⌘± でズーム。"
        "編集は自動保存され segments.json の drops に入ります。"
        "</div>"
        "<div id='rows'></div>"
        f"<script type='application/json' id='edit-data'>{data}</script>"
        f"<script>{EDIT_JS}</script>"
    )
    return page(f"{idv} #{idx} タイムライン編集", body)


def apply_timeline_save(payload):
    """/edit_save: タイムライン編集の drops を segments.json に保存する。"""
    idv = str(payload.get("id") or "")
    if not idv or "/" in idv or idv.startswith("."):
        return False
    base = os.path.join(DATA_DIR, idv)
    seg_path = os.path.join(base, "segments.json")
    if not os.path.isfile(seg_path):
        return False
    try:
        idx = int(payload.get("index"))
    except (TypeError, ValueError):
        return False
    seg = _load_json(seg_path, {})
    changed = False
    for sg in seg.get("segments", []):
        if sg.get("index") != idx:
            continue
        s, e = sg["start_sec"], sg["end_sec"]
        clean = []
        for d in payload.get("drops") or []:
            try:
                a, b = max(float(d[0]), s), min(float(d[1]), e)
            except (TypeError, ValueError, IndexError):
                continue
            if b - a > 0.01:
                clean.append([round(a, 3), round(b, 3)])
        sg["drops"] = sorted(clean)
        changed = True
    if not changed:
        return False
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(seg, f, ensure_ascii=False, indent=2)
    return True


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt_time(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def page(title, body):
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title><style>{PAGE_CSS}</style>"
        "<script>document.documentElement.dataset.theme="
        "localStorage.getItem('theme')||'light';</script></head>"
        f"<body><button class='theme-btn' onclick=\"var r=document.documentElement,"
        "t=r.dataset.theme==='dark'?'light':'dark';r.dataset.theme=t;"
        "localStorage.setItem('theme',t);\">dark / light</button>"
        f"{body}"
        "<script>"
        # クリックしてもスクロールはしない
        "function seekTo(id,t){var a=document.getElementById('orig');if(a)a.pause();"
        "var v=document.getElementById(id);if(!v)return;v.currentTime=t;v.play();}"
        # カット済み区間は元音源で再生して内容を確認する
        "function seekOrig(t){document.querySelectorAll('video').forEach(function(v){v.pause();});"
        "var a=document.getElementById('orig');if(!a)return;a.currentTime=t;a.play();}"
        "function decide(cid,action){var idv=new URLSearchParams(location.search).get('id');"
        "fetch('/decide?id='+encodeURIComponent(idv)+'&cid='+cid+'&action='+action)"
        ".then(function(){location.reload();});}"
        # 再生中の箇所の背景ハイライト
        "document.addEventListener('timeupdate',function(e){var el=e.target,sel,attr;"
        "if(el.tagName==='VIDEO'){sel=\"[data-v='\"+el.id+\"']\";attr='data-t';}"
        "else if(el.id==='orig'){sel='[data-ot]';attr='data-ot';}else return;"
        "if(el.paused)return;var t=el.currentTime,best=null,bt=-1;"
        "document.querySelectorAll(sel).forEach(function(sp){"
        "var v=parseFloat(sp.getAttribute(attr));if(v<=t+0.01&&v>bt){bt=v;best=sp;}});"
        "document.querySelectorAll('.playing').forEach(function(x){x.classList.remove('playing');});"
        "if(best&&t-bt<90)best.classList.add('playing');},true);"
        "</script>"
        "</body></html>"
    ).encode("utf-8")


# ---------- データ読み込み ----------
def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def list_ids():
    out = []
    if not os.path.isdir(DATA_DIR):
        return out
    for name in sorted(os.listdir(DATA_DIR)):
        if os.path.isdir(os.path.join(DATA_DIR, name, "contents")):
            out.append(name)
    return out


def list_segments(idv):
    cdir = os.path.join(DATA_DIR, idv, "contents")
    if not os.path.isdir(cdir):
        return []
    return sorted(n for n in os.listdir(cdir) if os.path.isdir(os.path.join(cdir, n)))


def seg_dirname(idv, index, title):
    prefix = f"{index:02d}_"
    for n in list_segments(idv):
        if n.startswith(prefix):
            return n
    return None


def load_id_data(idv):
    base = os.path.join(DATA_DIR, idv)
    segments = _load_json(os.path.join(base, "segments.json"), {}).get("segments", [])
    cands = _load_json(os.path.join(base, "candidates_raw.json"), [])
    cand_by_title = {c.get("title"): c for c in cands}
    sil = _load_json(os.path.join(base, "silences.json"), {})
    sil_by_index = {s.get("index"): s for s in sil.get("segments", [])}
    ex = _load_json(os.path.join(base, "exclude_zones.json"), {})
    tr = _load_json(os.path.join(base, "transcript.json"), {})
    # カット候補リストは ID ごと（data/<ID>/cutlist.json）。CUTLIST 環境変数で上書き可。
    cutlist_path = os.environ.get("CUTLIST") or os.path.join(base, "cutlist.json")
    cutlist = _load_json(cutlist_path, {"speakers": [], "manual": []})
    cutdec = _load_json(os.path.join(base, "cut_decisions.json"), {"cuts": []})
    ratings = _load_json(os.path.join(base, "ratings.json"), {"ratings": []})
    return {
        "segments": segments,
        "cand_by_title": cand_by_title,
        "sil_by_index": sil_by_index,
        "sil_meta": sil,
        "exclude_zones": ex.get("exclude_zones", []),
        "fact_checks": ex.get("fact_checks", []),
        "tsegments": tr.get("segments", []),
        "cut_speakers": cutlist.get("speakers", []),
        "cut_manual": cutlist.get("manual", []),
        "cut_decisions": cutdec.get("cuts", []),
        "ratings_by_index": {r.get("index"): r for r in ratings.get("ratings", [])},
    }


def media_url(idv, seg, fname):
    return "/media?p=" + urllib.parse.quote(f"{idv}/contents/{seg}/{fname}")


def trim_applied(idv, segments):
    base = os.path.join(DATA_DIR, idv)
    if os.path.isfile(os.path.join(base, "trim_plan.json")):
        return True
    for sg in segments:
        d = seg_dirname(idv, sg.get("index"), sg.get("title"))
        if d and os.path.isfile(os.path.join(base, "contents", d, "final_orig.mp4")):
            return True
    return False


# ---------- 区間(region)計算 ----------
def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _seg_speaker(tsegments, a, b):
    """[a,b] に最も重なる transcript セグメントの話者を返す。"""
    best, bestov = None, 0.0
    for ts in tsegments or []:
        t0, t1 = ts.get("start"), ts.get("end")
        if t0 is None or t1 is None:
            continue
        ov = _overlap(a, b, t0, t1)
        if ov > bestov:
            bestov, best = ov, ts.get("speaker")
    return best


def _drop_reason(a, b, tsegments, cut_manual):
    """カット済み区間の理由を簡潔に返す（手動カテゴリ優先、無ければ話者判定）。"""
    for m in cut_manual or []:
        span = min(b - a, m["end"] - m["start"])
        if _overlap(a, b, m["start"], m["end"]) >= 0.5 * max(0.1, span):
            c, r = m.get("category", ""), m.get("reason", "")
            return (c + "：" + r) if (c and r) else (c or r or "確定カット")
    spk = _seg_speaker(tsegments, a, b)
    if spk and not str(spk).endswith("01"):
        n = str(spk).split("_")[-1].lstrip("0") or "?"
        return f"会話相手(Sp{n})の発言"
    return "確定カット"


def to_final(t, s, drops):
    """元音源時刻 t を、その区間の final 動画時刻へ（区間開始を引き、途中のdrop分を差し引く）。"""
    ft = max(0.0, t - s)
    for d0, d1 in drops:
        lo, hi = max(d0, s), min(d1, t)
        if hi > lo:
            ft -= (hi - lo)
    return max(0.0, ft)


def build_regions(sg, cand, fact_checks, exclude_zones, cut_speakers=None, cut_manual=None, tsegments=None,
                  cut_decisions=None):
    """本文に重ねる時間区間を優先度付きで返す（元音源タイムライン）。
    優先度: done(7) > spk(6) > cutlist(6) > todo(4) > fact(3) > quote(2) > exclude(1)。"""
    s, e = sg["start_sec"], sg["end_sec"]
    idx = sg.get("index")
    drops = sg.get("drops") or []
    cand_cuts = (cand or {}).get("cuts") or []
    regions = []

    # 会話相手の発言（Notta話者。基本カット対象）
    spk_blocks = [b for b in (cut_speakers or []) if b.get("index") == idx]
    for b in spk_blocks:
        if _overlap(b["start"], b["end"], s, e) <= 0:
            continue
        regions.append({"s": max(b["start"], s), "e": min(b["end"], e), "kind": "spk",
                        "prio": 6, "label": "会話相手", "reason": ""})

    for d0, d1 in drops:
        reason = _drop_reason(d0, d1, tsegments, cut_manual)
        # 会話相手の発言カットは通常カットと表示を分ける（ラベルは「会話相手」のみ）
        if reason.startswith("会話相手"):
            regions.append({"s": max(d0, s), "e": min(d1, e), "kind": "donespk",
                            "prio": 7, "label": "会話相手", "reason": ""})
        else:
            regions.append({"s": max(d0, s), "e": min(d1, e), "kind": "done",
                            "prio": 7, "label": "カット", "reason": reason})

    # カット候補はすべて cut_decisions.json（C番号・分類・判断状況）から描く。
    # 初期状態は全件オープン（勝手にカットしない）。オーナーが カット/残す ボタンで確定する。
    # 確定＝見えにくいグレー / 未決＝分類ごとの色（gpt=ピンク, speaker=#30d8ff, その他=紫系）
    todo = []
    for cd in (cut_decisions or []):
        cs, ce = float(cd["start_sec"]), float(cd["end_sec"])
        if _overlap(cs, ce, s, e) <= 0:
            continue
        cid = cd.get("cid", "")
        status = cd.get("status", "pending")
        cat = cd.get("category", "gpt")
        if status == "keep":
            regions.append({"s": max(cs, s), "e": min(ce, e), "kind": "keep", "prio": 4,
                            "label": f"{cid} 残す(判断済)", "reason": cd.get("note", "")})
            continue
        if status == "cut":
            if any(_overlap(cs, ce, d0, d1) >= 0.5 * (ce - cs) for d0, d1 in drops):
                continue  # 既に drops で薄グレー表示されている
            regions.append({"s": max(cs, s), "e": min(ce, e), "kind": "done", "prio": 4,
                            "label": f"{cid} カット指示", "reason": cd.get("note", "")})
            continue
        # 未決: 分類ごとの色＋カット/残すボタン
        if cat == "speaker":
            kind, name, reason = "spkopen", "会話相手(未決)", ""
        elif cat == "gpt":
            kind, name, reason = "todo", "カット推奨(未決)", cd.get("reason", "")
        else:
            kind, name, reason = "other", f"{esc(cat)}(未決)", cd.get("reason", "")
        regions.append({"s": max(cs, s), "e": min(ce, e), "kind": kind, "prio": 4,
                        "label": f"{cid} {name}", "reason": reason, "cid": cid})
        todo.append(cd)

    facts = []
    for fc in fact_checks:
        if _overlap(fc["start_sec"], fc["end_sec"], s, e) <= 0:
            continue
        regions.append({"s": max(fc["start_sec"], s), "e": min(fc["end_sec"], e),
                        "kind": "fact", "prio": 3, "label": "⚠ 事実確認",
                        "reason": fc.get("issue", "")})
        facts.append(fc)

    # 候補外という分類は廃止（exclude_zones は assign_cut_ids がカット推奨として取り込む）

    return regions, todo, facts


def region_for(mid, regions):
    best = None
    for r in regions:
        if r["s"] <= mid < r["e"] and (best is None or r["prio"] > best["prio"]):
            best = r
    return best


# ---------- 単語モデル（インライン差し込みの土台） ----------
_PUNCT = set(" 　、。，．・…！？!?「」『』（）()［］[]〈〉《》\"'\n\t")


def _norm(s):
    """正規化文字列と、正規化index→元index の対応表。"""
    out, imap = [], []
    for i, ch in enumerate(s):
        if ch in _PUNCT:
            continue
        out.append(ch)
        imap.append(i)
    return "".join(out), imap


def build_word_model(tsegments, s, e):
    """[s,e] の単語を段落構造付きで集める。
    返り値: paras=[{ts, words:[gidx,...]}], toks[gidx], gmid[gidx](中点時刻),
            raw(全単語連結), char_gidx(各文字→gidx)"""
    paras, toks, gmid = [], [], []
    char_gidx, raw_parts = [], []
    for tseg in tsegments:
        ts0, ts1 = tseg.get("start"), tseg.get("end")
        if ts0 is None or ts1 is None or _overlap(ts0, ts1, s, e) <= 0:
            continue
        words = tseg.get("words") or []
        pw = []
        for w in words:
            wt = w.get("start")
            if wt is None or not (s <= wt < e):
                continue
            tok = w.get("word", "")
            gidx = len(toks)
            toks.append(tok)
            gmid.append((wt + w.get("end", wt)) / 2)
            for _ in tok:
                char_gidx.append(gidx)
            raw_parts.append(tok)
            pw.append(gidx)
        if not pw:
            txt = (tseg.get("text") or "").strip()
            if txt:
                paras.append({"ts": max(ts0, s), "words": None, "text": txt})
            continue
        paras.append({"ts": max(ts0, s), "words": pw, "text": None})
    return paras, toks, gmid, "".join(raw_parts), char_gidx


def assign_regions(toks, gmid, regions):
    """各 gidx に時間ベースの region を割り当て（無ければ None）。"""
    per = [None] * len(toks)
    for g in range(len(toks)):
        per[g] = region_for(gmid[g], regions)
    return per


def overlay_quotes(per, raw, char_gidx, quotes):
    """象徴的セリフを本文に重ねる。GPTのセリフはASRと表記が微妙に違うため、
    最長共通部分文字列をアンカーにして元文長ぶんを重ねる（一致率0.6以上のみ採用）。"""
    norm, imap = _norm(raw)
    quote_region = {"kind": "quote", "prio": 2, "label": "", "reason": ""}
    for q in quotes or []:
        qn, _ = _norm(q)
        if len(qn) < 6 or not norm:
            continue
        sm = SequenceMatcher(None, norm, qn, autojunk=False)
        a = sm.find_longest_match(0, len(norm), 0, len(qn))
        if a.size < 6:
            continue
        astart = max(0, a.a - a.b)
        aend = min(len(norm), astart + len(qn))
        if aend <= astart:
            continue
        if SequenceMatcher(None, norm[astart:aend], qn, autojunk=False).ratio() < 0.6:
            continue
        c0, c1 = imap[astart], imap[aend - 1]
        for c in range(c0, c1 + 1):
            if c < len(char_gidx):
                g = char_gidx[c]
                if per[g] is None:  # cut/fact/exclude を上書きしない
                    per[g] = quote_region


def locate_trims(raw, char_gidx, gaps, vid_id, applied):
    """詰めギャップを before+after のマッチで単語境界に割り付ける。
    表示は |← X.X秒 →| のみ（秒数以外の文字を出さない）。クリックでその直前から再生。
    候補=紫 / 詰め済み=緑（cssで区別）。返り値: dict gidx -> [chip_html,...]"""
    ins = {}
    for g in gaps:
        before, after = g.get("before", ""), g.get("after", "")
        if len(before) < 3 or len(after) < 3:
            continue
        pos = raw.find(before + after)
        if pos < 0:
            continue
        boundary = pos + len(before)
        if boundary >= len(char_gidx):
            continue
        gidx = char_gidx[boundary]
        t = max(0.0, g.get("start_sec", 0) - 1.0)          # 詰め位置(final時刻)の直前から
        cls = "trim done" if applied else "trim"
        onclick = (f" onclick=\"event.stopPropagation();seekTo('{vid_id}',{t:.2f})\"" if vid_id else "")
        chip = f"<span class='{cls}'{onclick}>|← {g.get('duration', 0):.1f}s →|</span>"
        ins.setdefault(gidx, []).append(chip)
    return ins


def render_transcript(tsegments, s, e, regions, quotes, gaps, drops=None, vid_id=None, applied=False,
                      seg_no=None):
    paras, toks, gmid, raw, char_gidx = build_word_model(tsegments, s, e)
    per = assign_regions(toks, gmid, regions)
    overlay_quotes(per, raw, char_gidx, quotes)
    trim_ins = locate_trims(raw, char_gidx, gaps, vid_id, applied)
    drops = drops or []
    emitted_chip = set()

    def seek_at(t, cls, inner):
        """inner をクリック可能spanで包む。カット済み区間内なら元音源(seekOrig)を、
        それ以外は final 動画を、原音時刻 t の少し前から再生する。
        data-v/data-t（動画）・data-ot（元音源）は再生位置ハイライト用。"""
        if not vid_id:
            return inner
        if any(d0 <= t < d1 for d0, d1 in drops):
            return (f"<span class='{cls}' data-ot='{t:.2f}'"
                    f" onclick=\"seekOrig({max(0.0, t - 1.0):.2f})\">{inner}</span>")
        ft = to_final(t, s, drops)
        return (f"<span class='{cls}' data-v='{vid_id}' data-t='{ft:.2f}'"
                f" onclick=\"seekTo('{vid_id}',{max(0.0, ft - 1.5):.2f})\">{inner}</span>")

    def emit(cur, buf):
        if not buf:
            return ""
        text = esc("".join(toks[g] for g in buf))
        if cur is None:
            return text
        if cur["kind"] == "quote":
            return f"<span class='r-quote'>{text}</span>"
        # 理由は該当語の“上の行間”に注釈として置く（同一regionは初回のみ）
        label = ""
        if id(cur) not in emitted_chip:
            emitted_chip.add(id(cur))
            rs = esc(cur.get("reason", ""))
            full = esc(cur["label"]) + (f"：{rs}" if rs else "")
            btn = ""
            if cur.get("cid"):  # 未決 → オーナーがその場で確定するボタン
                btn = ("<span class='dbtn'>"
                       f"<button onclick=\"decide('{cur['cid']}','cut')\">カット</button>"
                       f"<button onclick=\"decide('{cur['cid']}','keep')\">残す</button></span>")
            label = f"<span class='ann-label ann-{cur['kind']}' title=\"{full}\">{full}{btn}</span>"
        return f"<span class='ann'>{label}<span class='r-{cur['kind']}'>{text}</span></span>"

    def render_words(word_ids):
        pieces, cur, buf = [], None, []
        for gidx in word_ids:
            if gidx in trim_ins:
                pieces.append(emit(cur, buf)); buf = []
                pieces.extend(trim_ins[gidx])
            r = per[gidx]
            if r is not cur:
                pieces.append(emit(cur, buf)); buf = []; cur = r
            buf.append(gidx)
        pieces.append(emit(cur, buf))
        return "".join(pieces)

    def para_head(t, bno):
        """発言ブロック頭の [セグ番号-ブロック連番] ＋時刻表示。
        「[6-3] をカット」「⑥の 02:30 をカット」のように指示しやすくするためのもの。"""
        ft = to_final(t, s, drops)
        ftxt = fmt_time(ft)
        stxt = fmt_time(t)
        if vid_id and any(d0 <= t < d1 for d0, d1 in drops):
            # カット済みブロック → 元音源で頭出し（カット内容の確認用）
            link = (f"<span class='ts-link' onclick=\"seekOrig({max(0.0, t - 1.0):.2f})\">"
                    f"{ftxt}</span>")
        elif vid_id:
            link = (f"<span class='ts-link' onclick=\"seekTo('{vid_id}',{max(0.0, ft - 0.5):.2f})\">"
                    f"{ftxt}</span>")
        else:
            link = ftxt
        bn = f"<b>[{seg_no}-{bno}]</b>　" if seg_no is not None else ""
        return f"<span class='ts'>{bn}{link}　<span>({stxt})</span></span>"

    out = []
    bno = 0
    for para in paras:
        bno += 1
        if para["words"] is None:
            txt = seek_at(para["ts"], "txt", esc(para["text"]))
            out.append(f"<div class='tp'>{para_head(para['ts'], bno)}{txt}</div>")
            continue
        # 適当な長さ（文末。！？ または 40字）でチャンク化。各チャンクをクリック可能に。
        chunks, cur = [], []
        for gidx in para["words"]:
            cur.append(gidx)
            tok = toks[gidx]
            if (any(p in tok for p in "。！？") and len(cur) >= 8) or len(cur) >= 40:
                chunks.append(cur); cur = []
        if cur:
            chunks.append(cur)
        parts = []
        for ch in chunks:
            inner = render_words(ch)
            parts.append(seek_at(gmid[ch[0]], "txt", inner))
        body = "".join(parts)
        if body.strip():
            out.append(f"<div class='tp'>{para_head(para['ts'], bno)}{body}</div>")
    return "".join(out)


# ---------- ページ描画 ----------
def render_index():
    ids = list_ids()
    if ids:
        items = "".join(
            f"<li><a href='/id?id={urllib.parse.quote(i)}'>{esc(i)}</a> "
            f"<span class='meta'>{len(list_segments(i))} セグメント</span></li>"
            for i in ids
        )
        body = f"<h1>生成物チェック (ローカル preview)</h1><ul class='ids'>{items}</ul>"
    else:
        body = ("<h1>生成物チェック (ローカル preview)</h1>"
                f"<p class='meta'>contents/ を持つ ID が見つかりません。<br>data: {esc(DATA_DIR)}</p>")
    body += f"<p class='meta'>data: {esc(DATA_DIR)}</p>"
    return page("生成物チェック (ローカル preview)", body)




def render_id(idv):
    if idv not in list_ids():
        return None
    d = load_id_data(idv)
    segments = d["segments"]
    parts = [
        "<div class='crumb'><a href='/'>← 一覧</a></div>",
        f"<h1>{esc(idv)}　生成物</h1>",
    ]
    # 元音源（無編集）。カット済み区間のクリック時にここから再生して内容を確認できるようにする
    src_name = next((n for n in sorted(os.listdir(os.path.join(DATA_DIR, idv)))
                     if n.lower().endswith(".m4a")), None)
    if not src_name:
        src_name = next((n for n in sorted(os.listdir(os.path.join(DATA_DIR, idv)))
                         if n.lower().endswith(".mp4")), None)
    if src_name:
        parts.append(f"<audio id='orig' src='/media?p={urllib.parse.quote(idv + '/' + src_name)}'"
                     " preload='none' style='display:none'></audio>")
    # 並び順: オーナー評価の★が高い順。未評価は★1.5相当（★2以上の下・★0〜1の上）。同順位は index 順。
    def seg_order(sg):
        rt = d["ratings_by_index"].get(sg.get("index"))
        stars = float(rt["stars"]) if rt and rt.get("stars") is not None else 1.5
        return (-stars, sg.get("index", 0))
    ordered = sorted(segments, key=seg_order)

    # 目次: タイトル・尺・オーナー評価(★と根拠)を縦に並べる
    def dur_jp_of(sg):
        s0, e0 = sg["start_sec"], sg["end_sec"]
        dsec = sum(min(d1, e0) - max(d0, s0) for d0, d1 in (sg.get("drops") or []))
        dm0, ds0 = divmod(int(round((e0 - s0) - dsec)), 60)
        dh0, dm0 = divmod(dm0, 60)
        return f"{dh0}時間{dm0}分{ds0}秒" if dh0 else f"{dm0}分{ds0}秒"

    toc = []
    for sg in ordered:
        i = sg["index"]
        rt = d["ratings_by_index"].get(i)
        st_html = ""
        if rt and rt.get("stars") is not None:
            st_n = max(0, min(5, int(rt["stars"])))
            st_html = f"　<span class='stars'>{'★' * st_n}{'☆' * (5 - st_n)}</span>"
            if rt.get("quote"):  # 理由を述べた評価だけ根拠が入っている（直接指定は空）
                st_html += f"　<span class='rq'>「{esc(rt['quote'])}」</span>"
        toc.append(f"<div class='toc-item'><a href='#seg{i}'>{i} {esc(sg.get('title') or '')}</a>"
                   f"　{dur_jp_of(sg)}{st_html}</div>")
        # 要約（現在の切り出し内容ベース）→ ハイライト原文 の順に下へ並べる
        tcand = d["cand_by_title"].get(sg.get("title"))
        summary = sg.get("summary") or (tcand or {}).get("summary")
        if summary:
            toc.append(f"<div class='toc-sum'>{esc(summary)}</div>")
        for q in sg.get("highlight_quotes") or (tcand or {}).get("highlight_quotes") or []:
            toc.append(f"<div class='toc-q'>・{esc(q)}</div>")
    parts.append("<div class='toc'>" + "".join(toc) + "</div>")

    for sg in ordered:
        idx = sg.get("index")
        title = sg.get("title", "")
        cand = d["cand_by_title"].get(title)
        s, e = sg["start_sec"], sg["end_sec"]
        drops = sg.get("drops") or []
        drop_sec = sum(min(d1, e) - max(d0, s) for d0, d1 in drops)
        dur = (e - s) - drop_sec

        regions, todo, facts = build_regions(sg, cand, d["fact_checks"], d["exclude_zones"],
                                             d["cut_speakers"], d["cut_manual"], d["tsegments"],
                                             d["cut_decisions"])
        segfolder = seg_dirname(idv, idx, title)
        silseg = d["sil_by_index"].get(idx)
        # 自然詰めが実際に触るギャップ＝ likely_dropped(取りこぼし) を除き 1.5秒以上
        gaps = [g for g in (silseg or {}).get("gaps", [])
                if g.get("flag") != "likely_dropped" and g.get("duration", 0) >= 1.5]

        parts.append(f"<div class='seg' id='seg{idx}'>")
        rank = cand.get("rank") if cand else None
        # オーナー評価（★5段階＋根拠の発言を併記。分割したら評価はリセットされる）
        rt = d["ratings_by_index"].get(idx)
        if rt and rt.get("stars") is not None:
            st_n = max(0, min(5, int(rt["stars"])))
            rate_html = (f"<div class='rating'><b>オーナー評価:</b> "
                         f"<span class='stars'>{'★' * st_n}{'☆' * (5 - st_n)}</span> {st_n}/5")
            if rt.get("quote"):
                rate_html += (f"　<span class='rq'>根拠:「{esc(rt['quote'])}」"
                              f"{('(' + esc(rt.get('date') or '') + ')') if rt.get('date') else ''}</span>")
            rate_html += "</div>"
        else:
            rate_html = "<div class='rating unrated'><b>オーナー評価:</b> ☆☆☆☆☆ 未評価</div>"
        dm, ds = divmod(int(round(dur)), 60)
        dh, dm = divmod(dm, 60)
        dur_jp = (f"{dh}時間{dm}分{ds}秒" if dh else f"{dm}分{ds}秒")
        parts.append(
            "<div class='seghd'>"
            f"<h2><span class='rank'>{idx}</span>　{esc(title)}</h2>"
            + rate_html +
            f"<div class='meta'>{dur_jp} [{fmt_time(s)}〜{fmt_time(e)}]　"
            f"<a class='editlink' href='/edit?id={urllib.parse.quote(idv)}&seg={idx}'>タイムライン編集</a></div></div>"
        )

        if segfolder and os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, "final.mp4")):
            parts.append(f"<video id='vid{idx}' src='{media_url(idv, segfolder, 'final.mp4')}' controls preload='metadata'></video>")
            links = [f"<a href='{media_url(idv, segfolder, fn)}'>{esc(lb)}</a>"
                     for fn, lb in MEDIA_FILES
                     if os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, fn))]
            if links:
                parts.append("<div class='dl'>" + "".join(links) + "</div>")
        else:
            parts.append("<p class='meta'>final.mp4 なし</p>")

        # 要約: segments.json の summary（現在の切り出し内容から作り直したもの）を優先。
        # レビューは表示しない。見出しラベルも付けず本文だけ。
        summary = sg.get("summary") or (cand or {}).get("summary")
        if summary:
            parts.append(f"<div class='box summary'>{esc(summary)}</div>")

        # 切り出し全文（すべての注釈を本文中に）
        quotes = sg.get("highlight_quotes") or (cand or {}).get("highlight_quotes") or []
        trim_done = bool(segfolder) and os.path.isfile(
            os.path.join(DATA_DIR, idv, "contents", segfolder, "final_orig.mp4"))
        tr_html = render_transcript(d["tsegments"], s, e, regions, quotes, gaps, drops, f"vid{idx}",
                                    trim_done, seg_no=idx)
        parts.append("<div class='transcript'>"
                     + (tr_html or "<p class='meta'>文字起こしなし</p>") + "</div>")
        parts.append("</div>")

    return page(f"{idv} 生成物", "".join(parts))


def apply_decision(idv, cid, action):
    """カット/残す ボタンの確定処理。cut_decisions.json の status を更新し、
    cut なら該当セグメントの drops に区間を追加、keep なら（同一区間の drop があれば）外す。
    動画への反映は render.py の再実行時（チャットで依頼）。"""
    import datetime
    if idv not in list_ids() or action not in ("cut", "keep"):
        return False
    base = os.path.join(DATA_DIR, idv)
    dec_path = os.path.join(base, "cut_decisions.json")
    dec = _load_json(dec_path, {"cuts": []})
    target = None
    for c in dec.get("cuts", []):
        if c.get("cid") == cid:
            c["status"] = action
            c["decided"] = datetime.date.today().isoformat()
            target = c
            break
    if target is None:
        return False
    seg_path = os.path.join(base, "segments.json")
    seg = _load_json(seg_path, {})
    st, en = float(target["start_sec"]), float(target["end_sec"])
    for sg in seg.get("segments", []):
        s0, e0 = sg["start_sec"], sg["end_sec"]
        cs, ce = max(st, s0), min(en, e0)
        if ce - cs <= 0:
            continue
        drops = sg.get("drops") or []
        if action == "cut":
            if not any(abs(d0 - cs) < 0.3 and abs(d1 - ce) < 0.3 for d0, d1 in drops):
                drops.append([cs, ce])
                sg["drops"] = sorted(drops)
        else:
            sg["drops"] = [d for d in drops
                           if not (abs(d[0] - cs) < 0.3 and abs(d[1] - ce) < 0.3)]
    with open(dec_path, "w", encoding="utf-8") as f:
        json.dump(dec, f, ensure_ascii=False, indent=2)
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(seg, f, ensure_ascii=False, indent=2)
    return True


def safe_media_path(p):
    rel = urllib.parse.unquote(p or "")
    full = os.path.realpath(os.path.join(DATA_DIR, rel))
    if (full == DATA_DIR or full.startswith(DATA_DIR + os.sep)) and os.path.isfile(full):
        return full
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "podcast-preview/3.0"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/":
                self._send_html(render_index())
            elif route == "/id":
                content = render_id((qs.get("id") or [""])[0])
                if content is None:
                    self._send_html(page("404", "<h1>404</h1><a href='/'>一覧へ</a>"), 404)
                else:
                    self._send_html(content)
            elif route == "/edit":
                content = render_edit((qs.get("id") or [""])[0],
                                      (qs.get("seg") or [""])[0])
                if content is None:
                    self._send_html(page("404", "<h1>404</h1><a href='/'>一覧へ</a>"), 404)
                else:
                    self._send_html(content)
            elif route == "/decide":
                ok = apply_decision((qs.get("id") or [""])[0],
                                    (qs.get("cid") or [""])[0],
                                    (qs.get("action") or [""])[0])
                data = (b"ok" if ok else b"ng")
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif route == "/media":
                full = safe_media_path((qs.get("p") or [""])[0])
                if full is None:
                    self.send_error(404)
                else:
                    self._send_file(full)
            else:
                self.send_error(404)
        except BrokenPipeError:
            pass
        except Exception as ex:
            try:
                self._send_html(page("500", f"<h1>500</h1><pre>{esc(ex)}</pre>"), 500)
            except Exception:
                pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        ok = False
        if parsed.path == "/edit_save":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                ok = apply_timeline_save(payload)
            except Exception:
                ok = False
        data = b"ok" if ok else b"ng"
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, fullpath):
        ctype = mimetypes.guess_type(fullpath)[0] or "application/octet-stream"
        fs = os.path.getsize(fullpath)
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            start = int(m.group(1)) if m and m.group(1) else 0
            end = int(m.group(2)) if m and m.group(2) else fs - 1
            end = min(end, fs - 1)
            if start > end or start >= fs:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{fs}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{fs}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self._stream(fullpath, start, end - start + 1)
        else:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(fs))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._stream(fullpath, 0, fs)

    def _stream(self, fullpath, start, length):
        with open(fullpath, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main():
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("audio/mp4", ".m4a")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[preview] http://127.0.0.1:{PORT}/  (data: {DATA_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[preview] 停止しました")


if __name__ == "__main__":
    main()
