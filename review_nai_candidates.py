#!/usr/bin/env python3
"""Serve a local Keep/Delete review website for NAI candidate frames."""

from __future__ import annotations

import csv
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from nai_shared import NAI_ISSUES, OUTPUT_ROOT


HOST = "127.0.0.1"
PORT = 8765
INDEX_PATH = OUTPUT_ROOT / "candidates_index.json"
STATE_PATH = OUTPUT_ROOT / "review_state.json"
EXPORT_PATH = OUTPUT_ROOT / "review_decisions.csv"


def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text())


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def item_key(item: dict) -> str:
    return item.get("png_path") or item.get("file_stem", "")


def app_summary(items: list[dict], state: dict) -> list[dict]:
    apps: dict[str, dict] = {}
    for item in items:
        app = item.get("app_name", "Unknown app")
        row = apps.setdefault(app, {"app_name": app, "total": 0, "keep": 0, "discard": 0, "unsure": 0, "unlabeled": 0})
        row["total"] += 1
        decision = state.get(item_key(item), {}).get("decision", "")
        if decision == "keep":
            row["keep"] += 1
        elif decision in {"discard", "delete"}:
            row["discard"] += 1
        elif decision == "unsure":
            row["unsure"] += 1
        else:
            row["unlabeled"] += 1
    return list(apps.values())


def export_csv() -> None:
    items = load_index()
    state = load_state()
    with EXPORT_PATH.open("w", newline="") as fh:
        fieldnames = [
            "file_stem",
            "app_name",
            "package_name",
            "png_path",
            "xml_path",
            "metadata_path",
            "decision",
            "issue",
            "notes",
            "suspected_issue",
            "confidence",
            "action_path",
            "issue_definition",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            saved = state.get(item_key(item), {})
            writer.writerow(
                {
                    "file_stem": item["file_stem"],
                    "app_name": item["app_name"],
                    "package_name": item["package_name"],
                    "png_path": item["png_path"],
                    "xml_path": item.get("xml_path", ""),
                    "metadata_path": item.get("metadata_path", ""),
                    "decision": saved.get("decision", ""),
                    "issue": saved.get("issue", item.get("suspected_issue", "")),
                    "notes": saved.get("notes", ""),
                    "suspected_issue": item.get("suspected_issue", ""),
                    "confidence": item.get("confidence", ""),
                    "action_path": item.get("action_path", ""),
                    "issue_definition": item.get("issue_definition", ""),
                }
            )


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAI Frame Review</title>
<style>
:root { --ink:#182230; --muted:#667085; --line:#d0d5dd; --panel:#ffffff; --bg:#eef2f6; }
* { box-sizing:border-box; }
body { margin:0; font-family: Arial, sans-serif; background:var(--bg); color:var(--ink); }
header { height:60px; display:flex; align-items:center; gap:16px; padding:0 18px; background:#101828; color:white; }
header strong { font-size:16px; }
main { display:grid; grid-template-columns:260px minmax(360px, 1fr) 420px; gap:14px; padding:14px; }
button, select, textarea, input { font:inherit; }
button { border:0; border-radius:6px; padding:10px 12px; cursor:pointer; }
select, textarea, input { width:100%; border:1px solid var(--line); border-radius:6px; padding:8px; background:white; }
textarea { min-height:92px; resize:vertical; }
.sidebar, .panel { background:var(--panel); border-radius:8px; padding:14px; box-shadow:0 1px 3px rgba(16,24,40,.12); overflow:auto; max-height:calc(100vh - 88px); }
.viewer { background:#0b1220; min-height:calc(100vh - 88px); display:flex; align-items:center; justify-content:center; border-radius:8px; overflow:hidden; }
.viewer img { max-width:100%; max-height:calc(100vh - 112px); object-fit:contain; }
.label { font-size:12px; text-transform:uppercase; color:var(--muted); letter-spacing:.04em; margin-bottom:5px; }
.value { font-size:14px; line-height:1.35; overflow-wrap:anywhere; }
.row { margin-bottom:13px; }
.pill { display:inline-block; padding:4px 8px; border-radius:999px; background:#eaecf0; color:#344054; font-size:12px; margin-right:5px; }
.decision-keep { background:#dcfae6; color:#067647; }
.decision-discard { background:#fee4e2; color:#b42318; }
.decision-unsure { background:#fef0c7; color:#93370d; }
.actions { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin:12px 0; }
.keep { background:#067647; color:white; }
.discard { background:#b42318; color:white; }
.unsure { background:#b54708; color:white; }
.nav { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:12px 0; }
.nav button, .secondary { background:#e4e7ec; color:#182230; }
.export { background:#155eef; color:white; width:100%; margin-top:8px; }
.definition { border-left:4px solid #7a5af8; padding-left:10px; color:#344054; }
.app-list { display:flex; flex-direction:column; gap:7px; }
.app-btn { text-align:left; background:#f8fafc; border:1px solid #e4e7ec; color:#182230; padding:9px; }
.app-btn.active { border-color:#155eef; background:#eff4ff; }
.app-name { font-weight:700; display:block; margin-bottom:4px; }
.app-counts { font-size:12px; color:#667085; line-height:1.35; }
.toolbar { display:grid; gap:8px; margin-bottom:12px; }
pre { white-space:pre-wrap; word-break:break-word; background:#f8fafc; border:1px solid #e4e7ec; border-radius:6px; padding:8px; max-height:220px; overflow:auto; }
@media (max-width: 1100px) { main { grid-template-columns:1fr; } .sidebar, .panel { max-height:none; } }
</style>
</head>
<body>
<header>
  <strong>NAI Frame Review</strong>
  <span id="counter" class="pill"></span>
  <span id="appCounter" class="pill"></span>
  <span id="saved" class="pill">unlabeled</span>
</header>
<main>
  <aside class="sidebar">
    <div class="toolbar">
      <div>
        <div class="label">Filter App</div>
        <select id="appFilter" onchange="setAppFilter(this.value)"></select>
      </div>
      <button class="secondary" onclick="nextUnlabeled()">Next unlabeled</button>
      <button class="secondary" onclick="showAll()">Show all apps</button>
    </div>
    <div class="label">App Progress</div>
    <div id="appList" class="app-list"></div>
  </aside>
  <section class="viewer"><img id="image" alt="candidate frame"></section>
  <aside class="panel">
    <div class="row"><div class="label">App</div><div id="app" class="value"></div></div>
    <div class="row"><div class="label">Decision Key</div><div id="key" class="value"></div></div>
    <div class="row"><div class="label">Action Path</div><div id="action" class="value"></div></div>
    <div class="row"><div class="label">Current Activity</div><div id="activity" class="value"></div></div>
    <div class="row"><div class="label">Suggested Issue</div><div id="suggested" class="value"></div></div>
    <div class="row definition"><div class="label">Short Definition</div><div id="definition" class="value"></div></div>
    <div class="row"><div class="label">Manual Issue Label</div><select id="issue"></select></div>
    <div class="actions">
      <button class="keep" onclick="saveDecision('keep', true)">Keep</button>
      <button class="discard" onclick="saveDecision('discard', true)">Discard</button>
      <button class="unsure" onclick="saveDecision('unsure', true)">Unsure</button>
    </div>
    <div class="row"><div class="label">Notes</div><textarea id="notes" placeholder="Optional notes for this frame"></textarea></div>
    <div class="nav">
      <button onclick="move(-1)">Previous</button>
      <button onclick="move(1)">Next</button>
    </div>
    <button class="export" onclick="exportCsv()">Export review_decisions.csv</button>
    <hr>
    <div class="row"><div class="label">Metadata</div><pre id="meta" class="value"></pre></div>
  </aside>
</main>
<script>
let allItems = [];
let items = [];
let state = {};
let issues = [];
let summaries = [];
let i = 0;
let appFilter = 'ALL';

function keyFor(item) { return item.png_path || item.file_stem; }
function savedFor(item) { return state[keyFor(item)] || state[item.file_stem] || {}; }

async function init() {
  const data = await fetch('/api/data').then(r => r.json());
  allItems = data.items;
  state = data.state;
  issues = data.issues;
  summaries = data.apps;
  const issueSelect = document.getElementById('issue');
  issues.forEach(issue => {
    const opt = document.createElement('option');
    opt.value = issue;
    opt.textContent = issue;
    issueSelect.appendChild(opt);
  });
  renderAppFilter();
  const params = new URLSearchParams(location.search);
  appFilter = params.get('app') || 'ALL';
  applyFilter(false);
  i = Math.max(0, Math.min(items.length - 1, Number(params.get('i') || 0)));
  render();
}

function renderAppFilter() {
  const select = document.getElementById('appFilter');
  const apps = ['ALL', ...Array.from(new Set(allItems.map(x => x.app_name)))];
  select.innerHTML = '';
  apps.forEach(app => {
    const opt = document.createElement('option');
    opt.value = app;
    opt.textContent = app === 'ALL' ? 'All apps' : app;
    select.appendChild(opt);
  });
}

function applyFilter(resetIndex=true) {
  items = appFilter === 'ALL' ? allItems.slice() : allItems.filter(x => x.app_name === appFilter);
  document.getElementById('appFilter').value = appFilter;
  if (resetIndex) i = 0;
  if (i >= items.length) i = Math.max(0, items.length - 1);
  renderAppList();
}

function appStats(appName) {
  const appItems = allItems.filter(x => x.app_name === appName);
  const stats = {total: appItems.length, keep:0, discard:0, unsure:0, unlabeled:0};
  appItems.forEach(item => {
    const d = savedFor(item).decision;
    if (d === 'keep') stats.keep++;
    else if (d === 'discard' || d === 'delete') stats.discard++;
    else if (d === 'unsure') stats.unsure++;
    else stats.unlabeled++;
  });
  return stats;
}

function renderAppList() {
  const list = document.getElementById('appList');
  list.innerHTML = '';
  Array.from(new Set(allItems.map(x => x.app_name))).forEach(app => {
    const s = appStats(app);
    const btn = document.createElement('button');
    btn.className = 'app-btn' + (appFilter === app ? ' active' : '');
    btn.onclick = () => setAppFilter(app);
    btn.innerHTML = `<span class="app-name">${app}</span><span class="app-counts">${s.total} total · ${s.keep} keep · ${s.discard} discard · ${s.unsure} unsure · ${s.unlabeled} unlabeled</span>`;
    list.appendChild(btn);
  });
}

function render() {
  if (!items.length) {
    document.querySelector('.viewer').innerHTML = '<p style="color:white">No frames match this filter.</p>';
    return;
  }
  const item = items[i];
  const saved = savedFor(item);
  const decision = saved.decision || 'unlabeled';
  const appItems = allItems.filter(x => x.app_name === item.app_name);
  const appIndex = appItems.findIndex(x => keyFor(x) === keyFor(item)) + 1;
  document.getElementById('image').src = '/frames/' + encodeURIComponent(item.png_path);
  document.getElementById('counter').textContent = `${i + 1} / ${items.length}`;
  document.getElementById('appCounter').textContent = `${item.app_name}: ${appIndex} / ${appItems.length}`;
  document.getElementById('saved').textContent = decision;
  document.getElementById('saved').className = 'pill decision-' + decision;
  document.getElementById('app').textContent = item.app_name;
  document.getElementById('key').textContent = keyFor(item);
  document.getElementById('action').textContent = item.action_path;
  document.getElementById('activity').textContent = `${item.current_package}/${item.current_activity}`;
  document.getElementById('suggested').textContent = `${item.suspected_issue} (${item.confidence})`;
  document.getElementById('definition').textContent = item.issue_definition;
  document.getElementById('issue').value = saved.issue || item.suspected_issue;
  document.getElementById('notes').value = saved.notes || '';
  document.getElementById('meta').textContent = JSON.stringify(item, null, 2);
  history.replaceState(null, '', '?app=' + encodeURIComponent(appFilter) + '&i=' + i);
}

function setAppFilter(app) {
  autosaveSoft();
  appFilter = app;
  applyFilter(true);
  render();
}

function showAll() { setAppFilter('ALL'); }

function move(delta) {
  autosaveSoft();
  i = Math.max(0, Math.min(items.length - 1, i + delta));
  render();
}

function nextUnlabeled() {
  autosaveSoft();
  const start = i + 1;
  let found = items.findIndex((item, idx) => idx >= start && !savedFor(item).decision);
  if (found < 0) found = items.findIndex(item => !savedFor(item).decision);
  if (found >= 0) {
    i = found;
    render();
  }
}

function autosaveSoft() {
  if (!items.length) return;
  const item = items[i];
  const existing = savedFor(item);
  if (existing.decision) {
    existing.issue = document.getElementById('issue').value;
    existing.notes = document.getElementById('notes').value;
    state[keyFor(item)] = existing;
    fetch('/api/save', {method:'POST', body:JSON.stringify({key:keyFor(item), ...existing})});
  }
}

async function saveDecision(decision, advance=false) {
  const item = items[i];
  const payload = {
    key: keyFor(item),
    decision,
    issue: document.getElementById('issue').value,
    notes: document.getElementById('notes').value
  };
  await fetch('/api/save', {method:'POST', body:JSON.stringify(payload)});
  state[keyFor(item)] = {decision:payload.decision, issue:payload.issue, notes:payload.notes};
  renderAppList();
  if (advance && i < items.length - 1) i += 1;
  render();
}

async function exportCsv() {
  autosaveSoft();
  await fetch('/api/export', {method:'POST'});
  alert('Exported nai_candidate_frames/review_decisions.csv');
}

document.addEventListener('keydown', e => {
  const active = document.activeElement.tagName.toLowerCase();
  if (active === 'textarea' || active === 'input' || active === 'select') return;
  if (e.key === 'ArrowRight') move(1);
  if (e.key === 'ArrowLeft') move(-1);
  if (e.key.toLowerCase() === 'k') saveDecision('keep', true);
  if (e.key.toLowerCase() === 'd') saveDecision('discard', true);
  if (e.key.toLowerCase() === 'u') saveDecision('unsure', true);
  if (e.key.toLowerCase() === 'n') nextUnlabeled();
});
init();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def send_text(self, text: str, content_type: str = "text/html", status: int = 200) -> None:
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_text(json.dumps(payload), "application/json", status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(HTML)
            return
        if parsed.path == "/api/data":
            items = load_index()
            state = load_state()
            self.send_json(
                {
                    "items": items,
                    "state": state,
                    "issues": list(NAI_ISSUES.keys()),
                    "apps": app_summary(items, state),
                }
            )
            return
        if parsed.path.startswith("/frames/"):
            rel = unquote(parsed.path.removeprefix("/frames/"))
            path = (OUTPUT_ROOT / rel).resolve()
            if not str(path).startswith(str(OUTPUT_ROOT.resolve())) or not path.exists():
                self.send_text("Not found", "text/plain", 404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_text("Not found", "text/plain", 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode() if length else "{}"
        if parsed.path == "/api/save":
            payload = json.loads(raw)
            key = payload.pop("key", None) or payload.pop("file_stem")
            state = load_state()
            state[key] = payload
            save_state(state)
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/export":
            export_csv()
            self.send_json({"ok": True, "path": str(EXPORT_PATH)})
            return
        self.send_text("Not found", "text/plain", 404)


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Review site: http://{HOST}:{PORT}")
    print(f"Index: {INDEX_PATH}")
    print(f"State: {STATE_PATH}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
