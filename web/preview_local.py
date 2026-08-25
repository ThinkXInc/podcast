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
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）
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
ul.ids { list-style: none; padding: 0; max-width: 620px; }
ul.ids li { display:flex; align-items:center; gap:14px;
            padding: 11px 0; border-bottom: 1px solid #ccc4; }
ul.ids li a { flex:1; color: inherit; font-size: 16px; }
ul.ids li a:hover { text-decoration: underline; }
/* 進み具合。白抜きで、落ち着いた色。タイムラインの配色と揃える */
.st { flex:none; font-size: 11px; font-weight: 700; color: #fff;
      padding: 3px 11px; border-radius: 11px; letter-spacing: .04em; }
.st-none  { background: #6b7280; }   /* 未処理  グレー */
.st-done0 { background: #5f8a9c; }   /* 処理済み 青緑（タイムラインの発話色） */
.st-wip   { background: #a08040; }   /* 編集中  黄土（タイムラインの無音色） */
.st-done  { background: #4a7c59; }   /* 編集済み 緑 */

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
/* 全編セグメントは枠で区別する（オーナー指示・2026-08-08） */
.seg.fullep { border: 3px solid #68000044; border-radius: 12px; }
.editlink { font-size:13px; color:#6b7280; }
"""

# ---------- タイムライン（文字起こしの場所に埋め込む・別ページは作らない） ----------
TIMELINE_CSS = """
/* 文字起こしの場所がそのままタイムラインになる。別ページは作らない。
   要点は「文字もバーも同じ時間軸の座標に置く」こと。
   x = (時刻 - 行頭時刻) * pxPerSec なので、無音のぶんだけ文字と文字のあいだが空き、
   見た目がそのまま時間になる。 */
.tlbar { display:flex; align-items:center; gap:12px; font-size:12px; color:#9ca3af;
         margin:10px 0 6px; }
.tlbar button { font-size:12px; padding:1px 10px; cursor:pointer; background:transparent;
                color:inherit; border:1px solid #6b728088; border-radius:5px; }
.tlbar button:hover { background:#6b728033; }
.tltime { font-variant-numeric:tabular-nums; min-width:70px; color:#e8e8e8; font-size:13px; }
:root[data-theme="light"] .tltime { color:#111; }
.tlstat { margin-left:auto; }
.tlhelp { font-size:11px; color:#6b7280; line-height:1.8; margin:0 0 8px; }

.row { position:relative; margin:0 0 10px; }
.lane { position:relative; height:76px; }
/* 上から: タイムスタンプ / 発話テキスト / バー。すべて同じ時間軸の x 座標に置く。 */
.ts2 { position:absolute; top:0; font-size:11px; color:#8a8a8a;
       font-variant-numeric:tabular-nums; white-space:nowrap; }
.w { position:absolute; top:16px; white-space:pre; font-size:14px; line-height:20px;
     cursor:pointer; border-radius:2px; }
.w.cut { color:#6d6d6d; }
/* 話者の色分け。メイン話者（最多話者＝大塚さん）は既定色のまま、
   会話相手はモックの赤系に寄せたオレンジ系にする。docs/編集規則.md の
   「Speaker1 はほぼそのまま／会話相手は基本カット」を目で見て分けられるようにする。 */
.w.s2 { color:#d97a2b; } .w.s3 { color:#c9603a; } .w.s4 { color:#b8813a; }
.w.s5 { color:#d4643a; } .w.s6 { color:#c08a3f; } .w.s7 { color:#e0863c; }
.w.s8 { color:#b06a45; } .w.sx { color:#c9773a; }
/* カット済みでも話者の色は保つ。ただし沈める。
   一律グレーにすると「話者が違うから切った」のか「内容で切った」のかが分からなくなる。 */
.w.cut.s2 { color:#8a5a2e; } .w.cut.s3 { color:#84462c; } .w.cut.s4 { color:#7a562c; }
.w.cut.s5 { color:#8a4a2e; } .w.cut.s6 { color:#7d5c2e; } .w.cut.s7 { color:#91582a; }
.w.cut.s8 { color:#754b33; } .w.cut.sx { color:#815129; }
:root[data-theme="light"] .w.cut { color:#c4c4c4; }
:root[data-theme="light"] .w.cut.s2 { color:#f0c79b; }
:root[data-theme="light"] .w.cut.s3 { color:#eeb9a2; }
:root[data-theme="light"] .w.cut.s4 { color:#e8cda0; }
:root[data-theme="light"] .w.cut.s5 { color:#f2bda6; }
:root[data-theme="light"] .w.cut.s6 { color:#ead3a4; }
:root[data-theme="light"] .w.cut.s7 { color:#f5cba3; }
:root[data-theme="light"] .w.cut.s8 { color:#e3c3ae; }
:root[data-theme="light"] .w.cut.sx { color:#eec9a4; }
/* 話者ラベル。会話相手のターンの頭に小さく出す */
.spk { position:absolute; top:0; font-size:10px; font-weight:700; white-space:nowrap; }
.spk.s2 { color:#d97a2b; } .spk.s3 { color:#c9603a; } .spk.s4 { color:#b8813a; }
.spk.s5 { color:#d4643a; } .spk.s6 { color:#c08a3f; } .spk.s7 { color:#e0863c; }
.spk.s8 { color:#b06a45; } .spk.sx { color:#c9773a; }
.w.playing { background:#2563eb33; }
/* バーは常に1本の連続した帯。カットしても消さず、黒く塗る（AfterEffects と同じ見え方）。
   青緑＝発話 / 黄＝VADが検出した無音 / 黒＝カット済み。 */
.strip { position:absolute; left:0; right:0; top:40px; height:16px; cursor:crosshair; }
.barbase { position:absolute; top:0; height:16px; background:#5f8a9c; }
.sil { position:absolute; top:0; height:16px; background:#a89a3c; }
.cutz { position:absolute; top:0; height:16px; background:#2e2e2e; }
/* ドラッグ中の端は印として明示する（AfterEffects と同様） */
.splitline { position:absolute; top:-3px; height:22px; width:12px; pointer-events:none; }
.splitline::before, .splitline::after {
  content:''; position:absolute; top:0; bottom:0; width:4px;
  border-top:2px solid #e8e8e8; border-bottom:2px solid #e8e8e8; }
.splitline::before { left:0;  border-right:2px solid #e8e8e8; }   /* ] 左クリップの終端 */
.splitline::after  { right:0; border-left:2px solid #e8e8e8; }    /* [ 右クリップの始端 */
.edge { position:absolute; top:-2px; height:20px; width:2px; background:#e8e8e8; opacity:0; }
.edge.on { opacity:1; }
.hoverline { position:absolute; top:-26px; bottom:-2px; width:1px; background:#9ca3af;
             display:none; pointer-events:none; }
.playline { position:absolute; top:-26px; bottom:-2px; width:2px; background:#e11d48;
            display:none; pointer-events:none; z-index:3; }
.tlabel { position:absolute; top:-40px; font-size:10px; color:#9ca3af; display:none;
          pointer-events:none; font-variant-numeric:tabular-nums; white-space:nowrap; }
.tlwait { color:#6b7280; font-size:12px; padding:12px 0; }
/* 象徴的セリフ（highlight_quotes）は色を付けず太字にする（D-008 モノトーン方針） */
.w.hl { font-weight:700; }
/* 未決のカット候補。バーの直下に細い帯で出す。分類色は D-013 準拠 */
.pend { position:absolute; top:58px; height:5px; cursor:pointer; border-radius:2px; }
.pend.gpt { background:#e7a7bc; } .pend.speaker { background:#30d8ff; }
.pend.fact { background:#c9eb00; } .pend.other { background:#cdb4e2; }
.pend:hover { filter:brightness(1.25); }
.pcid { position:absolute; top:64px; font-size:10px; font-weight:700; white-space:nowrap;
        pointer-events:none; }
.pcid.gpt { color:#e7a7bc; } .pcid.speaker { color:#30d8ff; }
.pcid.fact { color:#c9eb00; } .pcid.other { color:#cdb4e2; }
/* 未決をクリックしたときに出す小さなパネル */
.pbox { position:fixed; z-index:50; max-width:420px; background:#232323; color:#e8e8e8;
        border:1px solid #6b7280; border-radius:8px; padding:10px 12px; font-size:12px;
        line-height:1.7; box-shadow:0 6px 24px #0008; }
:root[data-theme="light"] .pbox { background:#fff; color:#111; box-shadow:0 6px 24px #0003; }
.pbox b { font-size:13px; }
.pbox .q { color:#9ca3af; }
.pbox .btns { margin-top:8px; display:flex; gap:8px; }
.pbox button { font-size:12px; padding:3px 14px; cursor:pointer; background:transparent;
               color:inherit; border:1px solid #6b728088; border-radius:5px; }
.pbox button:hover { background:#6b728033; }
/* いまキー操作の対象になっているタイムライン。Space がどれに効くかを示す */
.tl { border-left:3px solid transparent; padding-left:9px; margin-left:-12px; }
.tl.tlfocus { border-left-color:#2563eb; }
"""

TIMELINE_JS = r"""
/* 1ページに複数のタイムラインが載る（セグメントごと）。重いので、画面に入ってから組む。
   再生は元音源の <audio id="orig"> を共有し、同時に鳴るのは1つだけにする。 */
(function(){
var EPS=0.01, MINW=0.02;
var audio=document.getElementById('orig');
var active=null;                      /* いま再生中のタイムライン */
var pxPerSec=parseFloat(localStorage.getItem('tl_pps'))||140;
var insts=[];
var hovered=null;   /* マウスが乗っているタイムライン。キー操作はここを最優先 */

function fmtJp(t){
  t=Math.round(t);
  var h=Math.floor(t/3600), m=Math.floor((t%3600)/60), s=t%60;
  return (h?h+'時間':'')+m+'分'+(s<10?'0':'')+s+'秒';
}
function fmtAbs(t){
  var h=Math.floor(t/3600), m=Math.floor((t%3600)/60), s=Math.floor(t%60);
  return (h?h+':':'')+((m<10&&h)?'0':'')+m+':'+(s<10?'0':'')+s;
}

function makeTimeline(root){
  var D=JSON.parse(root.querySelector('script[type="application/json"]').textContent);
  var keeps=complement(D.drops||[]);
  /* 前回の保存がサーバーに届かないまま閉じた/リロードした形跡（dirty）を検知する。
     自動では何も書き換えない。通知とボタンだけ出し、押されたときに限り復元する */
  var hasUnsaved=false;
  try{ hasUnsaved=!!(D.sid && localStorage.getItem('tl_dirty_'+D.sid)
        && JSON.parse(localStorage.getItem('tl_journal_'+D.sid)||'[]').length); }catch(e){}
  var undoStack=[], redoStack=[], playhead=D.segStart, selKi=-1;
  var rows=[], laneW=0, built=false, saveTimer=null;
  var dragging=null, pendingDrag=null;
  var host=root.querySelector('.tlrows');
  var elTime=root.querySelector('.tltime'), elKeep=root.querySelector('.tlkeep');
  var elStat=root.querySelector('.tlstat'), elZoom=root.querySelector('.tlzoom');
  var elBtn=root.querySelector('.tlplay');

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
  function X(R,t){ return (t-R.t0)*pxPerSec; }
  function T(R,x){ return R.t0 + x/pxPerSec; }
  function inKeep(t){ return keeps.some(function(k){return k[0]<=t&&t<k[1];}); }

  /* 象徴的セリフの単語番号を集合にしておく */
  var hlSet=(function(){ var st={}; (D.hl||[]).forEach(function(r){
    for(var i=r[0];i<=r[1];i++) st[i]=1; }); return st; })();

  function build(){
    host.innerHTML=''; rows=[];
    var probe=document.createElement('div'); probe.className='lane';
    host.appendChild(probe); laneW=probe.clientWidth||800; host.removeChild(probe);
    var rowSec=laneW/pxPerSec;
    var nRows=Math.ceil((D.segEnd-D.segStart)/rowSec);
    if(elZoom) elZoom.textContent=pxPerSec.toFixed(0)+'px/秒・1行'+rowSec.toFixed(1)+'秒';
    var wi=0;
    for(var r=0;r<nRows;r++){
      var t0=D.segStart+r*rowSec, t1=Math.min(D.segEnd,t0+rowSec);
      var row=document.createElement('div'); row.className='row';
      var lane=document.createElement('div'); lane.className='lane'; row.appendChild(lane);
      var strip=document.createElement('div'); strip.className='strip'; lane.appendChild(strip);
      var lastRight=-1e9, lastTsRight=-1e9, els=[], prevEnd=null, prevSpk=null;
      while(wi<D.words.length && D.words[wi].s < t1){
        var w=D.words[wi];
        if(w.e<=t0){ wi++; continue; }
        var x=(w.s-t0)*pxPerSec;
        if(x<lastRight) x=lastRight;
        /* 上の行に、発話ブロックの頭ならタイムスタンプ、
           会話相手のターンが始まったら「Speaker N」を出す。
           同じ位置に両方来ることがあるので、置いた幅を覚えて重なりを避ける。 */
        var newBlock=(prevEnd===null || w.s-prevEnd>=0.8);
        var newSpk=(w.p!==prevSpk);
        if(newBlock && x>=lastTsRight){
          var ts=document.createElement('div'); ts.className='ts2';
          ts.textContent=fmtAbs(w.s); ts.style.left=x+'px';
          lane.appendChild(ts); lastTsRight=x+ts.offsetWidth+8;
        }
        if(newSpk && w.p && w.p!==D.mainSpk){
          var sc=' s'+(w.p<=8?w.p:'x');
          var sl=document.createElement('div'); sl.className='spk'+sc;
          sl.textContent='Speaker '+w.p;
          sl.style.left=Math.max(x,lastTsRight)+'px';
          lane.appendChild(sl); lastTsRight=Math.max(x,lastTsRight)+sl.offsetWidth+8;
        }
        var el=document.createElement('span');
        el.className='w'+((w.p&&w.p!==D.mainSpk)?(' s'+(w.p<=8?w.p:'x')):'')
                        +(hlSet[wi]?' hl':'');
        el.textContent=w.t; el.style.left=x+'px';
        el.dataset.s=w.s; el.dataset.e=w.e;
        lane.appendChild(el); els.push(el);
        lastRight=x+el.offsetWidth; prevEnd=w.e; prevSpk=w.p; wi++;
      }
      host.appendChild(row);
      var R={t0:t0,t1:t1,strip:strip,els:els,bars:[]};
      rows.push(R); bindStrip(R);
    }
    built=true;
    renderBars(); styleWords(); movePlayhead();
  }
  function renderBars(){
    rows.forEach(function(R){
      R.strip.innerHTML=''; R.bars=[];
      /* 未決カットの帯とラベルは strip の外（lane）に置くので、ここで消さないと
         「残す」を押しても推奨マークが画面に残り続ける */
      R.strip.parentNode.querySelectorAll('.pend,.pcid').forEach(function(n){ n.remove(); });
      var W=X(R,R.t1);
      /* 1) 土台は発話色で全幅。バーは切っても消さない */
      var base=document.createElement('div'); base.className='barbase';
      base.style.left='0px'; base.style.width=W+'px'; R.strip.appendChild(base);
      /* 2) VAD の無音を黄で塗る */
      D.silence.forEach(function(sv){
        var a=Math.max(sv[0],R.t0), b=Math.min(sv[1],R.t1);
        if(b-a<=0) return;
        var d=document.createElement('div'); d.className='sil';
        d.style.left=X(R,a)+'px'; d.style.width=Math.max(1,X(R,b)-X(R,a))+'px';
        R.strip.appendChild(d);
      });
      /* 3) カット済み（keeps の隙間）を黒で塗る。黒が最優先 */
      var t=D.segStart;
      var ks=keeps.slice().sort(function(a,b){return a[0]-b[0];});
      var cuts=[];
      ks.forEach(function(k){ if(k[0]-t>EPS) cuts.push([t,k[0]]); t=Math.max(t,k[1]); });
      if(D.segEnd-t>EPS) cuts.push([t,D.segEnd]);
      cuts.forEach(function(c){
        var a=Math.max(c[0],R.t0), b=Math.min(c[1],R.t1);
        if(b-a<=0) return;
        var d=document.createElement('div'); d.className='cutz';
        d.style.left=X(R,a)+'px'; d.style.width=Math.max(1,X(R,b)-X(R,a))+'px';
        R.strip.appendChild(d);
      });
      /* 4) スプリット位置に縦線を出す。分割しただけでは両側とも「残す」なので
         線が無いと何も起きていないように見え、端を掴むこともできない。 */
      for(var i2=0;i2+1<ks.length;i2++){
        if(Math.abs(ks[i2][1]-ks[i2+1][0])>EPS) continue;
        var bt=ks[i2][1];
        if(bt<R.t0||bt>R.t1) continue;
        var sp2=document.createElement('div'); sp2.className='splitline';
        sp2.style.left=(X(R,bt)-6)+'px'; R.strip.appendChild(sp2);
      }
      /* 5) ドラッグできる端（keeps の境界）を記録。選択中は枠で示す */
      ks.forEach(function(k){
        var ki=keeps.indexOf(k);
        if(k[1]<=R.t0||k[0]>=R.t1) return;
        var x0=X(R,Math.max(k[0],R.t0)), x1=X(R,Math.min(k[1],R.t1));
        if(ki===selKi){
          var sel=document.createElement('div'); sel.className='edge on';
          sel.style.left=x0+'px'; sel.style.width=Math.max(1,x1-x0)+'px';
          sel.style.background='transparent';
          sel.style.boxShadow='inset 0 0 0 2px #2563eb';
          R.strip.appendChild(sel);
        }
        R.bars.push({ki:ki,x0:x0,x1:x1,edgeS:(k[0]>=R.t0-1e-9),edgeE:(k[1]<=R.t1+1e-9)});
      });
      /* 未決のカット候補をバーの下に細い帯で出す。押すとタイムライン上で黒くなる */
      (D.pend||[]).forEach(function(pd){
        if(pd.done) return;
        var a=Math.max(pd.a,R.t0), b=Math.min(pd.b,R.t1);
        if(b-a<=0) return;
        var pb=document.createElement('div'); pb.className='pend '+pd.cat;
        pb.style.left=X(R,a)+'px'; pb.style.width=Math.max(2,X(R,b)-X(R,a))+'px';
        pb.title=pd.cid+' '+pd.why;
        pb.onclick=function(ev){ ev.stopPropagation(); openPend(pd, ev.clientX, ev.clientY); };
        R.strip.parentNode.appendChild(pb);
        /* 理由を帯の直下に出す（旧 render_transcript の注釈行と同じ考え方）。
           C番号はボタンがあるので出さない。 */
        if(pd.a>=R.t0&&pd.a<R.t1){
          var CAT={gpt:'カット推奨',speaker:'会話相手',fact:'事実確認',other:'その他'};
          var lb=document.createElement('div'); lb.className='pcid '+pd.cat;
          lb.textContent=(CAT[pd.cat]||pd.cat)+(pd.why?('：'+pd.why):'');
          lb.style.left=X(R,pd.a)+'px';
          R.strip.parentNode.appendChild(lb);
        }
      });
      R.edge=document.createElement('div'); R.edge.className='edge'; R.strip.appendChild(R.edge);
      R.hover=document.createElement('div'); R.hover.className='hoverline'; R.strip.appendChild(R.hover);
      R.play=document.createElement('div'); R.play.className='playline'; R.strip.appendChild(R.play);
      R.tlab=document.createElement('div'); R.tlab.className='tlabel'; R.strip.appendChild(R.tlab);
    });
    showDragEdge();
  }
  function showDragEdge(){
    rows.forEach(function(R){ if(R.edge) R.edge.classList.remove('on'); });
    if(!dragging) return;
    var k=keeps[dragging.ki]; if(!k) return;
    var t=dragging.which===0?k[0]:k[1];
    var R=rows.find(function(R){return R.t0<=t&&t<=R.t1;});
    if(R&&R.edge){ R.edge.style.left=X(R,t)+'px'; R.edge.style.width='2px';
      R.edge.style.background='#e8e8e8'; R.edge.classList.add('on'); }
  }
  function styleWords(){
    rows.forEach(function(R){
      R.els.forEach(function(el){
        var mid=(+el.dataset.s + +el.dataset.e)/2;
        el.classList.toggle('cut', !inKeep(mid));
      });
    });
    var kept=keeps.reduce(function(a,k){return a+(k[1]-k[0]);},0);
    var m=Math.floor(kept/60), s=Math.round(kept-m*60);
    if(elKeep) elKeep.textContent='残り尺 '+m+'分'+(s<10?'0':'')+s+'秒';
    /* セグメント見出しの「元→編集後」もライブ更新する（静的なままだとバグに見える） */
    var hd=document.getElementById('dur'+D.index);
    if(hd){ var g=D.segEnd-D.segStart;
      hd.textContent=(g-kept>1)?(fmtJp(g)+'→'+fmtJp(kept)):fmtJp(g); }
  }
  function movePlayhead(){
    rows.forEach(function(R){ if(R.play) R.play.style.display='none'; });
    var R=rows.find(function(R){return R.t0<=playhead&&playhead<R.t1;})||rows[rows.length-1];
    if(R&&R.play){ R.play.style.left=X(R,playhead)+'px'; R.play.style.display='block'; }
    if(elTime) elTime.textContent=fmt(playhead);
  }
  function highlight(t){
    root.querySelectorAll('.w.playing').forEach(function(x){x.classList.remove('playing');});
    var R=rows.find(function(R){return R.t0<=t&&t<R.t1;});
    if(!R) return;
    var best=null;
    R.els.forEach(function(el){ if(+el.dataset.s<=t+0.01&&(!best||+el.dataset.s>+best.dataset.s)) best=el; });
    if(best&&t-(+best.dataset.s)<10) best.classList.add('playing');
  }

  var pbox=null;
  var hoverT=null;   /* マウスが行の上にあるときの時刻。⌘D はここで割る */
  function closePend(){ if(pbox){ pbox.remove(); pbox=null; } }
  function openCtx(R,t,cx,cy){
    /* 右クリックメニュー。即実行は誤操作しやすい（オーナー指示・2026-08-05）ので
       メニューから選んで実行する */
    closePend();
    pbox=document.createElement('div'); pbox.className='pbox';
    pbox.style.left=Math.min(cx,window.innerWidth-260)+'px';
    pbox.style.top=Math.min(cy+8,window.innerHeight-140)+'px';
    pbox.innerHTML='<b>'+fmtAbs(t)+'</b>'+
      '<div class="btns"><button data-a="split">ここでスプリット</button>'+
      '<button data-a="play">ここから再生</button>'+
      '<button data-a="close">閉じる</button></div>';
    document.body.appendChild(pbox);
    pbox.querySelectorAll('button').forEach(function(b){
      b.onclick=function(){
        var act=b.dataset.a; closePend();
        if(act==='split'){ playhead=t; movePlayhead(); splitAt(t); }
        else if(act==='play'){ selectInst(api); playhead=t; movePlayhead(); play(); }
      };
    });
  }
  function openPend(pd,cx,cy){
    closePend();
    var CAT={gpt:'カット推奨',speaker:'会話相手',fact:'事実確認',other:'その他'};
    pbox=document.createElement('div'); pbox.className='pbox';
    pbox.style.left=Math.min(cx,window.innerWidth-440)+'px';
    pbox.style.top=Math.min(cy+12,window.innerHeight-200)+'px';
    var sec=Math.round(pd.b-pd.a);
    pbox.innerHTML='<b>'+pd.cid+'　'+(CAT[pd.cat]||pd.cat)+'</b>　'+sec+'秒<br>'+
      esc(pd.why)+(pd.q?'<br><span class="q">「'+esc(pd.q)+'」</span>':'')+
      '<div class="btns"><button data-a="cut">カットする</button>'+
      '<button data-a="keep">残す</button>'+
      '<button data-a="close">閉じる</button></div>';
    document.body.appendChild(pbox);
    pbox.querySelectorAll('button').forEach(function(b){
      b.onclick=function(){ var act=b.dataset.a;
        if(act==='close'){ closePend(); return; }
        decidePend(pd, act); closePend(); };
    });
  }
  function esc(t){ return String(t).replace(/[&<>]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]; }); }
  function decidePend(pd, action){
    pd.done=true;
    if(action==='cut'){
      pushUndo();
      lastOp='pend-cut:'+pd.cid;
      dropRange(pd.a, pd.b);
      keeps.sort(function(a,b){return a[0]-b[0];});
      selKi=-1; afterEdit();
      setStatus(pd.cid+' をカットしました（端をドラッグして調整できます）');
    }else{
      renderBars();
      setStatus(pd.cid+' は残すことにしました');
    }
    /* cut_decisions.json の status だけ更新する。drops はタイムライン側が
       /edit_save で書くので、ここで両方書くと競合する。 */
    fetch('/decide?id='+encodeURIComponent(D.id)+'&cid='+encodeURIComponent(pd.cid)
          +'&action='+action+'&status_only=1');
  }
  var lastOp='';
  function pushUndo(){ undoStack.push(JSON.stringify(keeps)); if(undoStack.length>200)undoStack.shift(); redoStack=[]; }
  function afterEdit(){ renderBars(); styleWords(); movePlayhead(); scheduleSave(); }
  function setStatus(s){ if(elStat) elStat.textContent=s; }
  function journalNow(){
    /* 操作の瞬間に、手元のローカルへ同期的に履歴を書く。これが唯一の必須処理。
       サーバー送信は後追いで、失敗しても履歴は既にここに残っている */
    try{ var k='tl_journal_'+D.sid, j=JSON.parse(localStorage.getItem(k)||'[]');
         j.push({at:Date.now(),op:lastOp,drops:currentDrops()});
         try{ localStorage.setItem(k,JSON.stringify(j)); }
         catch(qe){ j=j.slice(Math.floor(j.length/2));
                    try{ localStorage.setItem(k,JSON.stringify(j)); }catch(e2){} }
         localStorage.setItem('tl_dirty_'+D.sid,'1');
    }catch(e){}
  }
  function scheduleSave(){ journalNow(); setStatus('未保存'); clearTimeout(saveTimer); saveTimer=setTimeout(doSave,0); }
  function doSave(){
    setStatus('保存中…');
    var rec={id:D.id,index:D.index,sid:D.sid,segStart:D.segStart,segEnd:D.segEnd,
             op:lastOp,drops:currentDrops()};
    lastOp='';
    fetch('/edit_save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(rec)})
    .then(function(r){
      if(r.ok){ setStatus('保存済み'); try{ localStorage.removeItem('tl_dirty_'+D.sid); }catch(e){} }
      else{ setStatus('保存失敗（3秒後に再送します）'); clearTimeout(saveTimer); saveTimer=setTimeout(doSave,3000); }
    })
    .catch(function(){ setStatus('サーバーに接続できません（3秒後に再送します）');
      clearTimeout(saveTimer); saveTimer=setTimeout(doSave,3000); });
  }
  function splitAt(t){
    var ki=keeps.findIndex(function(k){return t>k[0]+MINW&&t<k[1]-MINW;});
    if(ki<0){
      setStatus('その位置では分割できません（バーの上をクリックして位置を決めてください）');
      return;
    }
    pushUndo(); var k=keeps[ki];
    lastOp='split@'+t.toFixed(1);
    keeps.splice(ki,1,[k[0],t],[t,k[1]]); selKi=-1; afterEdit();
    setStatus('分割しました（端をドラッグするとカットできます）');
  }
  function dropRange(a,b){
    var ki=keeps.findIndex(function(k){return k[0]<b-EPS&&a<k[1]-EPS;});
    if(ki<0) return false;
    var k=keeps[ki], parts=[];
    if(a-k[0]>MINW) parts.push([k[0],Math.max(a,k[0])]);
    if(k[1]-b>MINW) parts.push([Math.min(b,k[1]),k[1]]);
    keeps.splice.apply(keeps,[ki,1].concat(parts));
    return true;
  }
  function dropAllSilence(minSec){
    var t=D.silence.filter(function(sv){
      return sv[1]-sv[0]>=minSec && keeps.some(function(k){return k[0]<sv[1]-EPS&&sv[0]<k[1]-EPS;});
    });
    if(!t.length){ setStatus(minSec+'秒以上の無音はありません'); return; }
    pushUndo();
    t.slice().reverse().forEach(function(sv){ dropRange(sv[0],sv[1]); });
    keeps.sort(function(a,b){return a[0]-b[0];});
    selKi=-1; afterEdit(); setStatus(t.length+'箇所の無音を落としました');
  }

  /* ---- 再生。元音源を共有するので、鳴らす前に他を止める ---- */
  function tick(){
    if(active!==api) return;
    var t=audio.currentTime;
    if(t>=D.segEnd){ stop(); return; }
    if(!inKeep(t)){
      var nk=keeps.find(function(k){return k[0]>t;});
      if(!nk){ stop(); return; }
      audio.currentTime=nk[0]+0.001;
    }
    playhead=audio.currentTime; movePlayhead(); highlight(playhead);
    requestAnimationFrame(tick);
  }
  function applyRate(){ try{ audio.playbackRate=parseFloat(localStorage.getItem('tl_rate')||'1'); }catch(e){} }
  function play(){
    applyRate();
    if(!audio){ setStatus('元音源がありません'); return; }
    if(active&&active!==api) active.stop();
    if(!inKeep(playhead)){
      var nk=keeps.find(function(k){return k[0]>=playhead;});
      playhead=nk?nk[0]:(keeps[0]?keeps[0][0]:D.segStart);
    }
    var go=function(){
      try{ audio.currentTime=playhead; }
      catch(err){ setStatus('シークできません: '+err.name); return; }
      audio.play().then(function(){ active=api; if(elBtn) elBtn.textContent='∎ 停止';
        setStatus('再生中'); requestAnimationFrame(tick); })
        .catch(function(err){ setStatus('再生できません: '+err.name+' '+(err.message||'')); });
    };
    /* preload=metadata でも読み終わる前に currentTime を触ると失敗するので待つ */
    if(audio.readyState>=1){ go(); }
    else{
      setStatus('音源を読み込み中…');
      audio.addEventListener('loadedmetadata', go, {once:true});
      audio.addEventListener('error', function(){
        var c=audio.error&&audio.error.code;
        setStatus('音源を読み込めません（code '+c+'）。ブラウザが対応しない形式かもしれません');
      }, {once:true});
      audio.load();
    }
  }
  function stop(){
    if(audio) audio.pause();
    if(active===api) active=null;
    if(elBtn) elBtn.textContent='▶ 再生';
    root.querySelectorAll('.w.playing').forEach(function(x){x.classList.remove('playing');});
  }

  function edgesAt(R,x){
    var out=[];
    R.bars.forEach(function(b){
      if(b.edgeS&&Math.abs(x-b.x0)<8) out.push({ki:b.ki,which:0});
      if(b.edgeE&&Math.abs(x-b.x1)<8) out.push({ki:b.ki,which:1});
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
    var lane=R.strip.parentNode;
    /* 行のどこ（文字の上でも）にマウスがあっても、その時刻を ⌘D 用に覚えておく */
    lane.addEventListener('mousemove',function(ev){
      hoverT=T(R, ev.clientX-R.strip.getBoundingClientRect().left);
      hovered=api;
    });
    lane.addEventListener('mouseleave',function(){ hoverT=null;
      if(hovered===api) hovered=null; });
    /* 右クリック＝メニュー（ここでスプリット／ここから再生）。文字の上でも効く */
    lane.addEventListener('contextmenu',function(ev){
      ev.preventDefault();
      selectInst(api);
      var t=T(R, ev.clientX-R.strip.getBoundingClientRect().left);
      openCtx(R, t, ev.clientX, ev.clientY);
    });
    R.strip.addEventListener('dblclick',function(ev){
      /* 黄（無音）をダブルクリック＝その無音だけ落とす */
      var x=ev.clientX-R.strip.getBoundingClientRect().left, t=T(R,x);
      var sv=D.silence.find(function(v){return v[0]<=t&&t<v[1];});
      if(sv&&R.bars.some(function(b){return x>=b.x0&&x<=b.x1;})){
        ev.preventDefault(); pushUndo(); lastOp='dropSilence@'+sv[0].toFixed(1); dropRange(sv[0],sv[1]); selKi=-1; afterEdit();
      }
    });
    R.strip.addEventListener('mousedown',function(ev){
      ev.preventDefault();
      selectInst(api);
      var x=ev.clientX-R.strip.getBoundingClientRect().left;
      var cand=edgesAt(R,x);
      if(cand.length===1){ pushUndo(); dragging={R:R,ki:cand[0].ki,which:cand[0].which}; }
      else if(cand.length>1){ pendingDrag={R:R,cand:cand,x0:ev.clientX}; }
      else{
        playhead=T(R,x);
        var hit=R.bars.find(function(b){return x>=b.x0&&x<=b.x1;});
        selKi=hit?hit.ki:-1;
        renderBars(); movePlayhead();
        if(active===api) audio.currentTime=playhead;
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
        pick=pick||pendingDrag.cand[0];
        pushUndo(); dragging={R:pendingDrag.R,ki:pick.ki,which:pick.which}; pendingDrag=null;
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
    if(dragging){ dragging=null; lastOp='trim'; scheduleSave(); }
  });
  host.addEventListener('click',function(ev){
    var el=ev.target.closest('.w'); if(!el) return;
    selectInst(api);
    playhead=+el.dataset.s; movePlayhead();
    if(active===api) audio.currentTime=playhead;
  });

  if(elBtn) elBtn.onclick=function(){ selectInst(api); (active===api)?stop():play(); };
  var zi=root.querySelector('.tlzin'), zo=root.querySelector('.tlzout');
  if(zi) zi.onclick=function(){ setZoomAll(pxPerSec*1.4); };
  if(zo) zo.onclick=function(){ setZoomAll(pxPerSec/1.4); };
  /* 「無音を一括で落とす」ボタンは廃止（オーナー指示・2026-08-05。
     一括操作は編集を全部飛ばす危険があるため。黄帯のダブルクリックで1箇所ずつは残す） */
  var sp=root.querySelector('.tlspeed');
  if(sp){
    sp.value=localStorage.getItem('tl_rate')||'1';
    sp.onchange=function(){ localStorage.setItem('tl_rate',sp.value);
      if(audio) audio.playbackRate=parseFloat(sp.value);
      /* 他のタイムラインのプルダウン表示も同期 */
      document.querySelectorAll('.tlspeed').forEach(function(s){ s.value=sp.value; }); };
  }
  var ub=root.querySelector('.tlundo'), rb=root.querySelector('.tlredo');
  if(ub) ub.onclick=function(){ selectInst(api); api.undo(); };
  if(rb) rb.onclick=function(){ selectInst(api); api.redo(); };

  if(hasUnsaved){
    setStatus('未保存の編集があります');
    var rb=document.createElement('button');
    rb.textContent='未保存の編集を復元';
    rb.onclick=function(){
      try{
        var jj=JSON.parse(localStorage.getItem('tl_journal_'+D.sid)||'[]');
        if(!jj.length){ setStatus('復元できる編集がありません'); return; }
        pushUndo(); lastOp='restore-unsaved';
        keeps=complement(jj[jj.length-1].drops||[]);
        selKi=-1; afterEdit(); rb.remove();
      }catch(e){ setStatus('復元に失敗しました'); }
    };
    var bar=root.querySelector('.tlbar');
    if(bar) bar.appendChild(rb);
  }
  var api={ root:root, sid:D.sid,
            state:function(){ return {id:D.id, sid:D.sid, index:D.index,
              segStart:D.segStart, segEnd:D.segEnd, drops:currentDrops()}; },
            build:build, isBuilt:function(){return built;}, rebuild:function(){ if(built) build(); },
            play:play, stop:stop,
            /* ⌘D: マウスが行の上にあればその位置、なければ再生位置で割る */
            splitAt:function(){ var t=(hoverT!=null)?hoverT:playhead;
              playhead=t; movePlayhead(); splitAt(t); },
            undo:function(){ if(!undoStack.length)return; redoStack.push(JSON.stringify(keeps));
              keeps=JSON.parse(undoStack.pop()); selKi=-1; lastOp='undo'; afterEdit(); },
            redo:function(){ if(!redoStack.length)return; undoStack.push(JSON.stringify(keeps));
              keeps=JSON.parse(redoStack.pop()); selKi=-1; lastOp='redo'; afterEdit(); },
            delSel:function(){ if(selKi<0) return; pushUndo(); lastOp='delete'; keeps.splice(selKi,1); selKi=-1; afterEdit(); },
            dropSil:function(){ dropAllSilence(1.0); } };
  return api;
}

var focused=null;
function selectInst(a){
  focused=a;
  insts.forEach(function(x){ x.root.classList.toggle('tlfocus', x===a); });
}
/* クリックしていなくても Space が効くように、画面の中央に一番近いものを対象にする。
   これが無いと focused も active も null のままで、キーが素通りしていた。 */
function pickVisible(){
  var cy=window.innerHeight/2, best=null, bd=1e9;
  insts.forEach(function(a){
    var r=a.root.getBoundingClientRect();
    if(r.bottom<0||r.top>window.innerHeight) return;
    var d=Math.abs((r.top+r.bottom)/2-cy);
    if(d<bd){ bd=d; best=a; }
  });
  return best;
}
function setZoomAll(v){
  pxPerSec=Math.max(20,Math.min(600,v));
  localStorage.setItem('tl_pps',pxPerSec);
  insts.forEach(function(a){ a.rebuild(); });
}

document.addEventListener('keydown',function(e){
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  /* ⌘D はタイムラインが拾えない場合でも先に抑止する。
     さもないとブラウザのブックマーク追加が開き「効かない」ように見える */
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='d') e.preventDefault();
  var a=hovered||active||focused||pickVisible();
  if(!a){ return; }
  if(a!==focused) selectInst(a);
  if(!a.isBuilt()) a.build();
  if(e.code==='Space'){ e.preventDefault(); (active===a)?a.stop():a.play(); }
  else if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='d'){ e.preventDefault(); a.splitAt(); }
  else if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){ e.preventDefault(); e.shiftKey?a.redo():a.undo(); }
  else if((e.metaKey||e.ctrlKey)&&(e.key==='='||e.key==='+')){ e.preventDefault(); setZoomAll(pxPerSec*1.4); }
  else if((e.metaKey||e.ctrlKey)&&e.key==='-'){ e.preventDefault(); setZoomAll(pxPerSec/1.4); }
  else if(e.key==='Delete'||e.key==='Backspace'){ e.preventDefault(); a.delSel(); }
});

/* 画面に入ってから組む。7セグメントぶんの単語を最初に全部DOM化すると重いため */
document.querySelectorAll('.tl').forEach(function(root){
  var a=makeTimeline(root);
  insts.push(a);
  var io=new IntersectionObserver(function(es){
    es.forEach(function(en){
      if(en.isIntersecting&&!a.isBuilt()){ a.build(); io.disconnect(); }
    });
  },{rootMargin:'300px'});
  io.observe(root);
});
/* 書き出しは「ブラウザが今表示している状態」をそのまま使う（オーナー指示 2026-08-08。
   サーバー保存値を参照すると、見ているものと書き出されるものがズレる余地が残るため） */
window.tlState=function(sid){
  for(var i=0;i<insts.length;i++){ if(insts[i].sid===sid) return insts[i].state(); }
  return null;
};
var rsz=null;
window.addEventListener('resize',function(){
  clearTimeout(rsz);
  rsz=setTimeout(function(){ insts.forEach(function(a){ a.rebuild(); }); },200);
});
})();
"""


_QPUNCT = set(" 　、。，．・…！？!?「」『』（）()［］[]〈〉《》\"'\n\t")


def _quote_ranges(words, quotes):
    """highlight_quotes が本文のどの単語範囲にあたるかを返す（[[開始i, 終了i], ...]）。
    GPT/Claude の引用は表記が微妙に違うので、句読点を除いた文字列で最長一致を探す。"""
    from difflib import SequenceMatcher
    if not quotes or not words:
        return []
    idx, buf = [], []
    for i, w in enumerate(words):
        for ch in w["t"]:
            if ch in _QPUNCT:
                continue
            buf.append(ch)
            idx.append(i)
    hay = "".join(buf)
    out = []
    for q in quotes:
        qn = "".join(c for c in str(q) if c not in _QPUNCT)
        if len(qn) < 6:
            continue
        sm = SequenceMatcher(None, hay, qn, autojunk=False)
        m = sm.find_longest_match(0, len(hay), 0, len(qn))
        if m.size < 6:
            continue
        st = max(0, m.a - m.b)
        en = min(len(hay), st + len(qn))
        if en <= st:
            continue
        if SequenceMatcher(None, hay[st:en], qn, autojunk=False).ratio() < 0.6:
            continue
        out.append([idx[st], idx[en - 1]])
    return out


def timeline_block(idv, sg, tsegments, silence, main_spk=1, cutdecs=None, quotes=None):
    """文字起こしの場所に置くタイムライン。別ページは作らない（オーナー指示・2026-08-05）。"""
    idx = sg.get("index")
    s, e = float(sg["start_sec"]), float(sg["end_sec"])
    words = []
    for tseg in tsegments:
        for w in (tseg.get("words") or []):
            st, en = w.get("start"), w.get("end")
            if st is None or en is None or not (s <= st < e):
                continue
            tok = (w.get("word") or "").strip()
            if not tok:
                continue
            spk = w.get("speaker") or tseg.get("speaker") or ""
            try:
                pno = int(str(spk).split("_")[-1])
            except ValueError:
                pno = 0
            words.append({"t": tok, "s": round(float(st), 3),
                          "e": round(float(en), 3), "p": pno})
    words.sort(key=lambda w: w["s"])
    sil = [[max(a, s), min(b, e)] for a, b in silence if b > s and a < e]
    sil = [[round(a, 3), round(b, 3)] for a, b in sil if b - a > 0.01]

    # 未決のカット候補（D-013）。押したらタイムライン上で黒くなり、端をドラッグして調整できる。
    pend = []
    for cd in (cutdecs or []):
        if cd.get("status") != "pending":
            continue
        a, b = float(cd["start_sec"]), float(cd["end_sec"])
        if b <= s or a >= e:
            continue
        cat = cd.get("category") or "gpt"
        pend.append({"cid": cd.get("cid", ""), "a": round(max(a, s), 3), "b": round(min(b, e), 3),
                     "cat": cat if cat in ("gpt", "speaker", "fact") else "other",
                     "why": (cd.get("reason") or cd.get("note") or ""),
                     "q": cd.get("quote") or ""})
    pend.sort(key=lambda x: x["a"])

    # 象徴的セリフ（highlight_quotes）。本文中の該当語を太字にするため、
    # 文字列一致で単語インデックスの範囲を求めておく（表示は太字のみ・色は付けない）。
    hl = _quote_ranges(words, quotes or [])

    data = json.dumps({"id": idv, "index": idx, "sid": sg.get("sid") or "", "segStart": s, "segEnd": e,
                       "drops": sg.get("drops") or [], "words": words, "silence": sil,
                       "mainSpk": main_spk, "pend": pend, "hl": hl},
                      ensure_ascii=False).replace("</", "<\\/")
    vad_note = ("青緑＝発話・黄＝VADが検出した無音（黄をダブルクリックでその無音だけ落ちる）"
                if sil else "VAD 未実行のため無音の塗り分けなし（python scripts/detect_vad.py &lt;ID&gt;）")
    return (
        f"<div class='tl' id='tl{idx}'>"
        "<div class='tlbar'>"
        "<button class='tlplay'>▶ 再生</button>"
        "<span class='tltime'>0:00.00</span>"
        "<span class='tlkeep'></span>"
        "<button class='tlzout'>−</button><button class='tlzin'>＋</button>"
        "<select class='tlspeed'><option value='1'>1x</option>"
        "<option value='1.35'>1.35x</option><option value='1.5'>1.5x</option></select>"
        "<span class='tlzoom'></span>"
        "<button class='tlundo'>↩ 元に戻す</button><button class='tlredo'>↪ やり直す</button>"
        "<span class='tlstat'>保存済み</span>"
        "</div>"
        f"<div class='tlhelp'>文字は時間軸上の位置に置いてあるので、文字間の空白がそのまま無音の長さです。"
        f"バーは常に1本の帯で、{vad_note}、黒＝カット済み。"
        "Space 再生（カット部はスキップ）・<b>⌘D＝マウス位置でスプリット</b>・"
        "右クリック＝メニュー（スプリット/再生）・端をドラッグでトリム・"
        "クリックで選択して Delete で削除・⌘Z 取り消し・⌘± ズーム。自動保存されます。</div>"
        f"<div class='tlrows'><div class='tlwait'>スクロールすると組み上がります（単語 {len(words)}）…</div></div>"
        f"<script type='application/json'>{data}</script>"
        "</div>"
    )


def apply_timeline_save(payload):
    """/edit_save: タイムライン編集の drops を segments.json に保存する。"""
    idv = str(payload.get("id") or "")
    if not idv or "/" in idv or idv.startswith("."):
        return False
    # 受信した保存内容は成否に関わらず全部記録する（復元用の受信箱・2026-08-08）。
    # 古いページの保存が拒否されても、ここに全編集データが残る。
    try:
        import datetime
        inbox = os.path.join(idpaths.edit_dir(os.path.join(DATA_DIR, idv)), "save_inbox.jsonl")
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.datetime.now().isoformat(timespec="milliseconds"),
                                "payload": payload}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())   # ここがジャーナルの正本。適用より先に必ずディスクへ書き切る
    except Exception:
        pass
    base = os.path.join(DATA_DIR, idv)
    seg_path = idpaths.find(base, "segments.json")
    if not os.path.isfile(seg_path):
        return False
    try:
        idx = int(payload.get("index"))
    except (TypeError, ValueError):
        return False
    sid = str(payload.get("sid") or "")
    seg = _load_json(seg_path, {})
    changed = False
    for sg in seg.get("segments", []):
        # 対応づけは sid が正（index は細分化・並べ替えで変わるため。2026-08-08）。
        # sid が無い旧データだけ index で引く。
        if sid and sg.get("sid"):
            if sg["sid"] != sid:
                continue
        elif sg.get("index") != idx:
            continue
        # 保存は受け取ったまま書く。切り詰め・範囲外破棄はしない（オーナー指示 2026-08-08。
        # 整形はデータを壊すだけで意味がない。範囲の解釈は表示・書き出し側が読むときに行う）。
        # sid が無い旧ページの index 指定だけは、誤セグメント書き込み防止に区間一致を要求する。
        if not (sid and sg.get("sid") == sid):
            try:
                ps, pe = float(payload.get("segStart")), float(payload.get("segEnd"))
            except (TypeError, ValueError):
                return False
            if abs(ps - float(sg["start_sec"])) > 0.5 or abs(pe - float(sg["end_sec"])) > 0.5:
                return False
        clean = []
        for d in payload.get("drops") or []:
            try:
                a, b = float(d[0]), float(d[1])
            except (TypeError, ValueError, IndexError):
                return False
            if b > a:
                clean.append([round(a, 3), round(b, 3)])
        sg["drops"] = sorted(clean)
        changed = True
    if not changed:
        return False
    _append_history(base, seg_path)
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(seg, f, ensure_ascii=False, indent=2)
    return True


def _append_history(base, seg_path):
    """segments.json を上書きする前に、直前の内容を履歴へ退避する（保険）。
    edit/segments_history.jsonl に1行1スナップショットで貯める。最新200件だけ残す。"""
    import datetime
    try:
        with open(seg_path, encoding="utf-8") as f:
            prev = f.read()
        hist = os.path.join(idpaths.edit_dir(base), "segments_history.jsonl")
        lines = []
        if os.path.isfile(hist):
            with open(hist, encoding="utf-8") as f:
                lines = f.read().splitlines()
        lines.append(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "segments_json": prev}, ensure_ascii=False))
        with open(hist, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-200:]) + "\n")
    except Exception:
        pass  # 履歴が書けなくても保存自体は続ける


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
        f"<title>{esc(title)}</title><style>{PAGE_CSS}{TIMELINE_CSS}</style>"
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
        # 「この編集で書き出す」: 完了したらそのままダウンロードが落ちてくる
        "function nrToggle(cb){localStorage.setItem('nr_on',cb.checked?'1':'0');"
        "document.querySelectorAll('.nrtoggle').forEach(function(c){c.checked=cb.checked;});}"
        "document.addEventListener('DOMContentLoaded',function(){"
        "var on=localStorage.getItem('nr_on')==='1';"
        "document.querySelectorAll('.nrtoggle').forEach(function(c){c.checked=on;});});"
        "function renderSeg(sid,idx){var idv=new URLSearchParams(location.search).get('id');"
        "var el=document.getElementById('rst'+idx);"
        "var st=window.tlState?window.tlState(sid):null;"
        "if(!st){el.textContent='タイムラインの状態を取得できません（リロードしてください）';return;}"
        "if(localStorage.getItem('nr_on')==='1')st.denoise=true;"
        "fetch('/render_seg',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify(st)}).then(function(r){return r.text();})"
        ".then(function(st){if(st!=='started'&&st!=='already_running'){el.textContent='開始できません: '+st;return;}"
        "el.textContent='書き出し中…（数分かかります。ページを開いたままで）';"
        "var iv=setInterval(function(){"
        "fetch('/render_status?id='+encodeURIComponent(idv)+'&sid='+encodeURIComponent(sid)).then(function(r){return r.text();})"
        ".then(function(s){if(s.indexOf('running:')===0){el.textContent='書き出し中… '+s.slice(8)+'%';}"
        "else if(s.indexOf('done')===0){clearInterval(iv);"
        "var fn=s.length>5?s.slice(5):'';"
        "if(fn){var a=document.createElement('a');"
        "a.href='/media?p='+encodeURIComponent(idv+'/contents/'+fn);"
        "a.download=fn;document.body.appendChild(a);a.click();a.remove();"
        "el.textContent='完了: '+fn;}else{el.textContent='完了';}}"
        "else if(s.indexOf('failed')===0){clearInterval(iv);"
        "el.textContent='書き出し失敗（generated/render_'+sid+'.log を確認）';}});},2000);});}"
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
        f"<script>{TIMELINE_JS}</script>"
        "</body></html>"
    ).encode("utf-8")


# ---------- データ読み込み ----------
def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _main_speaker(tr):
    """最多話者の番号を返す。話者ラベルが無ければ 1 を返す。"""
    import collections
    c = collections.Counter()
    for w in (tr.get("word_segments") or []):
        spk = w.get("speaker")
        if spk:
            c[spk] += 1
    if not c:
        return 1
    try:
        return int(str(c.most_common(1)[0][0]).split("_")[-1])
    except ValueError:
        return 1


def list_ids():
    """data/ 直下の ID をすべて返す（未処理のものも含める）。"""
    out = []
    if not os.path.isdir(DATA_DIR):
        return out
    for name in sorted(os.listdir(DATA_DIR)):
        if name.startswith(".") or name.startswith("_"):
            continue
        if os.path.isdir(os.path.join(DATA_DIR, name)):
            out.append(name)
    return out


def id_status(idv):
    """ID の進み具合を返す (key, ラベル)。
    未処理   … 文字起こしがまだ
    処理済み … 文字起こしはできたが、まだ何も編集していない
    編集中   … カットを入れたが、未決のカット候補が残っている
    編集済み … 未決がなくなった
    """
    base = os.path.join(DATA_DIR, idv)
    if not os.path.exists(idpaths.find(base, "transcript.json")):
        return "none", "未処理"
    segs = _load_json(idpaths.find(base, "segments.json"), {}).get("segments", [])
    cuts = _load_json(idpaths.find(base, "cut_decisions.json"), {}).get("cuts", [])
    pending = sum(1 for c in cuts if c.get("status") == "pending")
    decided = sum(1 for c in cuts if c.get("status") in ("cut", "keep"))
    has_drop = any(sg.get("drops") for sg in segs)
    started = has_drop or decided   # カット記録が最低1つ＝編集に着手（オーナー指示 2026-08-09）
    if not segs or not started:
        return "done0", "処理済み"
    if pending:
        return "wip", "編集中"
    return "done", "編集済み"


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


def seg_audio_names(idv, index):
    """export_audio.py が書く {ID}_{INDEX}_{TITLE}{尺}{yymmddHHMM}.m4a を contents/ 直下から
    新しい順に全部返す（ファイル名でバージョンが分かれる・2026-08-08）。
    macOS はファイル名の Unicode 正規化（NFC/NFD）が混在するので、比較は NFC に揃える。"""
    import unicodedata
    cdir = os.path.join(DATA_DIR, idv, "contents")
    if not os.path.isdir(cdir):
        return []
    prefix = unicodedata.normalize("NFC", f"{idv}_{index}_")
    out = []
    for n in os.listdir(cdir):
        nn = unicodedata.normalize("NFC", n)
        if nn.startswith(prefix) and nn.endswith(".m4a") and not nn.endswith(".part.m4a"):
            out.append(n)
    out.sort(key=lambda n: os.path.getmtime(os.path.join(cdir, n)), reverse=True)
    return out


def load_id_data(idv):
    base = os.path.join(DATA_DIR, idv)
    segments = _load_json(idpaths.find(base, "segments.json"), {}).get("segments", [])
    cands = _load_json(idpaths.find(base, "candidates_raw.json"), [])
    cand_by_title = {c.get("title"): c for c in cands}
    sil = _load_json(idpaths.find(base, "silences.json"), {})
    sil_by_index = {s.get("index"): s for s in sil.get("segments", [])}
    ex = _load_json(idpaths.find(base, "exclude_zones.json"), {})
    tr = _load_json(idpaths.find(base, "transcript.json"), {})
    # カット候補リストは ID ごと（data/<ID>/cutlist.json）。CUTLIST 環境変数で上書き可。
    cutlist_path = os.environ.get("CUTLIST") or idpaths.find(base, "cutlist.json")
    cutlist = _load_json(cutlist_path, {"speakers": [], "manual": []})
    cutdec = _load_json(idpaths.find(base, "cut_decisions.json"), {"cuts": []})
    ratings = _load_json(idpaths.find(base, "ratings.json"), {"ratings": []})
    vad = _load_json(idpaths.find(base, "vad.json"), {})
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
        # VAD の無音区間。バーの中を緑(発話)/黄(無音)で塗り分けるのに使う。
        "silence_spans": [tuple(x) for x in vad.get("silence", [])],
        # メイン話者＝最多話者（docs/編集規則.md「Speaker 1 = 大塚さん（最多話者）」）。
        # この話者だけ既定色、他はオレンジ系にして会話相手を見分けられるようにする。
        "main_speaker": _main_speaker(tr),
    }


def media_url(idv, seg, fname):
    return "/media?p=" + urllib.parse.quote(f"{idv}/contents/{seg}/{fname}")


def trim_applied(idv, segments):
    base = os.path.join(DATA_DIR, idv)
    if os.path.isfile(idpaths.find(base, "trim_plan.json")):
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
    if not ids:
        return page("音源一覧", f"<h1>音源一覧</h1><p class='meta'>data: {esc(DATA_DIR)}</p>")
    rows = []
    for i in ids:
        key, label = id_status(i)
        rows.append(
            f"<li><a href='/id?id={urllib.parse.quote(i)}'>{esc(i)}</a>"
            f"<span class='st st-{key}'>{label}</span></li>")
    return page("音源一覧", f"<h1>音源一覧</h1><ul class='ids'>{''.join(rows)}</ul>")




def render_id(idv):
    if idv not in list_ids():
        return None
    d = load_id_data(idv)
    segments = d["segments"]
    parts = [
        "<div class='crumb'><a href='/'>← 一覧</a></div>",
        f"<h1>{esc(idv)}</h1>",
    ]
    if not segments:
        # まだ処理していない ID。何が足りないかだけ出す
        base = os.path.join(DATA_DIR, idv)
        has_tr = os.path.exists(idpaths.find(base, "transcript.json"))
        parts.append(
            "<p class='meta'>"
            + ("切り出し区間がまだありません（segments.json 未作成）。"
               if has_tr else
               "文字起こしがまだです。<br>bash scripts/transcribe.sh " + esc(idv))
            + "</p>")
        return page(idv, "".join(parts))
    # 元音源（無編集）。カット済み区間のクリック時にここから再生して内容を確認できるようにする
    # 再生用は preview_audio.m4a を最優先。元音源が ALAC だと Chrome / Firefox が
    # 再生できないため（2026-08-05 実測）。作り方: python scripts/make_preview_audio.py <ID>
    _b = os.path.join(DATA_DIR, idv)
    names = sorted(os.listdir(_b))
    _pv = idpaths.find(_b, "preview_audio.m4a")
    src_name = os.path.relpath(_pv, _b) if os.path.exists(_pv) else None
    if not src_name:
        src_name = next((n for n in names if n.lower().endswith(".m4a")), None)
    if not src_name:
        src_name = next((n for n in names if n.lower().endswith(".mp4")), None)
    if src_name:
        # preload='none' だと尺が分からずシークできない。タイムラインは 800秒などの
        # 絶対時刻へ飛ぶので metadata まで読ませる。
        parts.append(f"<audio id='orig' src='/media?p={urllib.parse.quote(idv + '/' + src_name)}'"
                     " preload='metadata' style='display:none'></audio>")
    # 並び順: オーナー評価の★が高い順。未評価は★1.5相当（★2以上の下・★0〜1の上）。同順位は index 順。
    def seg_order(sg):
        rt = d["ratings_by_index"].get(sg.get("index"))
        stars = float(rt["stars"]) if rt and rt.get("stars") is not None else 1.5
        is_full = "全編" in (sg.get("title") or "")
        # 全編を必ず先頭に（オーナー指示 2026-08-09）。残りは★順→番号順
        return (0 if is_full else 1, -stars, sg.get("index", 0))
    ordered = sorted(segments, key=seg_order)

    # 目次: タイトル・尺・オーナー評価(★と根拠)を縦に並べる
    def _jp(sec):
        m, s = divmod(int(round(sec)), 60)
        h, m = divmod(m, 60)
        return f"{h}時間{m}分{s}秒" if h else f"{m}分{s:02d}秒"

    def dur_jp_of(sg):
        """尺は「元→編集後」で出す（例: 49分43秒→25分21秒）。カットが無ければ元だけ。"""
        s0, e0 = sg["start_sec"], sg["end_sec"]
        gross = e0 - s0
        dsec = sum(max(0.0, min(d1, e0) - max(d0, s0)) for d0, d1 in (sg.get("drops") or []))
        if dsec < 1:
            return _jp(gross)
        return f"{_jp(gross)}→{_jp(gross - dsec)}"

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
        _lbl = "＊" if "全編" in (sg.get("title") or "") else str(i)
        toc.append(f"<div class='toc-item'><a href='#seg{i}'>{_lbl} {esc(sg.get('title') or '')}</a>"
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
        drop_sec = sum(max(0.0, min(d1, e) - max(d0, s)) for d0, d1 in drops)
        dur = (e - s) - drop_sec
        gross = e - s

        regions, todo, facts = build_regions(sg, cand, d["fact_checks"], d["exclude_zones"],
                                             d["cut_speakers"], d["cut_manual"], d["tsegments"],
                                             d["cut_decisions"])
        segfolder = seg_dirname(idv, idx, title)
        silseg = d["sil_by_index"].get(idx)
        # 自然詰めが実際に触るギャップ＝ likely_dropped(取りこぼし) を除き 1.5秒以上
        gaps = [g for g in (silseg or {}).get("gaps", [])
                if g.get("flag") != "likely_dropped" and g.get("duration", 0) >= 1.5]

        _full = "全編" in (title or "")
        parts.append(f"<div class='seg{' fullep' if _full else ''}' id='seg{idx}'>")
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
        def _jp2(sec):
            m2, s2 = divmod(int(round(sec)), 60)
            h2, m2 = divmod(m2, 60)
            return f"{h2}時間{m2}分{s2}秒" if h2 else f"{m2}分{s2:02d}秒"
        dur_jp = _jp2(gross) if drop_sec < 1 else f"{_jp2(gross)}→{_jp2(dur)}"
        parts.append(
            "<div class='seghd'>"
            f"<h2><span class='rank'>{'＊' if _full else idx}</span>　{esc(title)}</h2>"
            + rate_html +
            f"<div class='meta'><span id='dur{idx}'>{dur_jp}</span> [{fmt_time(s)}〜{fmt_time(e)}]</div></div>"
        )

        if segfolder and os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, "final.mp4")):
            parts.append(f"<video id='vid{idx}' src='{media_url(idv, segfolder, 'final.mp4')}' controls preload='metadata'></video>")
            links = [f"<a href='{media_url(idv, segfolder, fn)}'>{esc(lb)}</a>"
                     for fn, lb in MEDIA_FILES
                     if os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, fn))]
            if links:
                parts.append("<div class='dl'>" + "".join(links) + "</div>")
        # ボタンは1つ。完了したらブラウザのダウンロードとして自動で落ちてくる
        # （リンク列・プレーヤーは出さない。オーナー指示・2026-08-08）
        _sid = sg.get("sid") or ""
        parts.append(
            f"<p class='meta'><button onclick=\"renderSeg('{_sid}',{idx})\">この編集で書き出す（m4a）</button>"
            f"　<label><input type='checkbox' class='nrtoggle' onchange='nrToggle(this)'> ノイズ除去</label>"
            f"　<span id='rst{idx}' class='meta'></span></p>")

        # 要約: segments.json の summary（現在の切り出し内容から作り直したもの）を優先。
        # レビューは表示しない。見出しラベルも付けず本文だけ。
        summary = sg.get("summary") or (cand or {}).get("summary")
        if summary:
            parts.append(f"<div class='box summary'>{esc(summary)}</div>")

        # 切り出し全文（すべての注釈を本文中に）
        quotes = sg.get("highlight_quotes") or (cand or {}).get("highlight_quotes") or []
        trim_done = bool(segfolder) and os.path.isfile(
            os.path.join(DATA_DIR, idv, "contents", segfolder, "final_orig.mp4"))
        # 文字起こしの場所はタイムラインにする（オーナー指示・2026-08-05）。
        # 別ページを開かず、この画面で切る。
        parts.append("<div class='transcript'>"
                     + timeline_block(idv, sg, d["tsegments"], d["silence_spans"],
                                      d["main_speaker"], d["cut_decisions"], quotes)
                     + "</div>")
        parts.append("</div>")

    return page(f"{idv} 生成物", "".join(parts))


def apply_decision(idv, cid, action, status_only=False):
    """カット/残す ボタンの確定処理。cut_decisions.json の status を更新する。
    status_only=True のときは segments.json に触らない。タイムラインから押された場合は
    drops をタイムライン自身が /edit_save で書くので、二重に書くと競合するため。
    動画への反映は render.py の再実行時。"""
    import datetime
    if idv not in list_ids() or action not in ("cut", "keep"):
        return False
    base = os.path.join(DATA_DIR, idv)
    dec_path = idpaths.find(base, "cut_decisions.json")
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
    if status_only:
        with open(dec_path, "w", encoding="utf-8") as f:
            json.dump(dec, f, ensure_ascii=False, indent=2)
        return True
    seg_path = idpaths.find(base, "segments.json")
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


# 書き出し中のプロセス。key=(ID, index) → subprocess.Popen
RENDERS = {}


def _seg_index_by_sid(idv, sid):
    seg = _load_json(idpaths.find(os.path.join(DATA_DIR, idv), "segments.json"), {})
    for sg in seg.get("segments", []):
        if sg.get("sid") == sid:
            return sg.get("index")
    return None


def start_render_spec(spec):
    """ブラウザが表示している状態（sid・区間・全カット）をそのまま書き出す。
    segments.json は参照しない＝見ているもの以外が書き出されることは構造的にない。"""
    import subprocess, datetime
    idv = str(spec.get("id") or "")
    sid = str(spec.get("sid") or "")
    if idv not in list_ids() or not sid:
        return "bad_id"
    # 何を書き出したかも受信箱へ完全記録
    try:
        inbox = os.path.join(idpaths.edit_dir(os.path.join(DATA_DIR, idv)), "save_inbox.jsonl")
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.datetime.now().isoformat(timespec="milliseconds"),
                                "payload": dict(spec, op="export")}, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
    except Exception:
        pass
    key = (idv, sid)
    p = RENDERS.get(key)
    if p is not None and p.poll() is None:
        return "already_running"
    gen = idpaths.gen_dir(os.path.join(DATA_DIR, idv))
    specp = os.path.join(gen, f"export_spec_{sid}.json")
    with open(specp, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    root = os.path.dirname(HERE)
    py = os.path.join(root, "venv", "bin", "python")
    if not os.path.isfile(py):
        py = _sys.executable
    logf = open(os.path.join(gen, f"render_{sid}.log"), "w", encoding="utf-8")
    cmd = [py, os.path.join(root, "scripts", "export_audio.py"), idv, "--spec", specp]
    if spec.get("denoise"):
        cmd.append("--denoise")
    RENDERS[key] = subprocess.Popen(cmd, cwd=root, stdout=logf, stderr=subprocess.STDOUT)
    return "started"


def start_render(idv, sid):
    """export_audio.py を1セグメントだけバックグラウンドで走らせる。
    対応づけは sid（index は細分化で変わるため。2026-08-08）。"""
    import subprocess
    if idv not in list_ids() or _seg_index_by_sid(idv, sid) is None:
        return "bad_id"
    key = (idv, sid)
    p = RENDERS.get(key)
    if p is not None and p.poll() is None:
        return "already_running"
    root = os.path.dirname(HERE)
    py = os.path.join(root, "venv", "bin", "python")
    if not os.path.isfile(py):
        py = _sys.executable
    logdir = idpaths.gen_dir(os.path.join(DATA_DIR, idv))
    logf = open(os.path.join(logdir, f"render_{sid}.log"), "w", encoding="utf-8")
    RENDERS[key] = subprocess.Popen(
        [py, os.path.join(root, "scripts", "export_audio.py"), idv, "--sid", sid],
        cwd=root, stdout=logf, stderr=subprocess.STDOUT)
    return "started"


def render_status(idv, sid):
    p = RENDERS.get((idv, sid))
    if p is None:
        return "none"
    if p.poll() is None:
        # export_audio.py が書く進捗ファイルから % を返す
        try:
            gen = idpaths.gen_dir(os.path.join(DATA_DIR, idv))
            meta = json.load(open(os.path.join(gen, f"export_progress_{sid}.json")))
            txt = open(os.path.join(gen, f"export_progress_{sid}.txt")).read()
            us = [ln.split("=")[1] for ln in txt.splitlines() if ln.startswith("out_time_us=")]
            done = (int(us[-1]) / 1e6) if us else 0.0
            net = max(0.1, float(meta.get("net") or 0.1))
            stage = meta.get("stage")
            if stage == 1:
                pct = min(45, int(done / net * 45))
            elif stage == 2:
                pct = 55   # ノイズ除去中（進捗が取れないので固定表示）
            else:
                pct = min(99, 70 + int(min(29, done / net * 29)))
            return f"running:{pct}"
        except Exception:
            return "running"
    if p.returncode != 0:
        return f"failed({p.returncode})"
    # 完了したら最新の書き出しファイル名を返す。ページ側はこれで自動ダウンロードさせる
    index = _seg_index_by_sid(idv, sid)
    names = seg_audio_names(idv, index) if index is not None else []
    return "done:" + names[0] if names else "done"


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
            elif route == "/decide":
                ok = apply_decision((qs.get("id") or [""])[0],
                                    (qs.get("cid") or [""])[0],
                                    (qs.get("action") or [""])[0],
                                    (qs.get("status_only") or ["0"])[0] == "1")
                data = (b"ok" if ok else b"ng")
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif route == "/render_status":
                st = render_status((qs.get("id") or [""])[0],
                                   (qs.get("sid") or [""])[0])
                data = st.encode()
                self.send_response(200)
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
        if parsed.path == "/render_seg":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                spec = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                st = start_render_spec(spec)
            except Exception:
                st = "bad_request"
            data = st.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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
