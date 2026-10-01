'use strict';
/* 数字经济与管理学院综合管理平台 - 前端逻辑 */

let ME = null, META = null, calendarData = null;
let dayEntries = {};              // 当日台账缓存 {部门: [行]}
let view = { year: 2026, month: 10 };
let selectedDate = null;          // 当前选中日期 YYYY-MM-DD
let editingEntry = null;          // null=新增; {office,id}=编辑
let pendingUploads = [];          // 待随台账保存的新附件相对路径
let removeAttachments = [];       // 编辑时勾选移除的旧附件

const OFFICE_CLS = { '综合办': 'zhb', '教学办': 'jxb', '学生办': 'xsb' };
const ROLE_LABELS = { admin: '管理员', leader: '院领导', office: '部门负责人' };
const STATUS_CLS = { '待接收': 'gray', '进行中': 'blue', '已完成': 'green', '已延期': 'red' };

function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function todayStr() {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
}

let toastTimer = null;
function toast(msg, type) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), 3200);
}

async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  if (r.status === 401 && !path.startsWith('/api/login')) { location.href = '/login'; throw new Error('未登录'); }
  let d;
  try { d = await r.json(); } catch (e) { throw new Error('服务无响应,请稍后重试。'); }
  if (!d.ok) throw new Error(d.error || '操作失败。');
  return d;
}

/* ================= 初始化 ================= */

document.addEventListener('DOMContentLoaded', init);

async function init() {
  try {
    const me = await api('/api/me');
    ME = me.user;
  } catch (e) { return; }
  META = await api('/api/meta');
  const t = new Date();
  view = { year: t.getFullYear(), month: t.getMonth() + 1 };
  bindStatic();
  applyRole();
  await loadCalendar();
  loadTasks();          // 同时刷新角标
  if (META.is_admin) loadUsers();
}

function bindStatic() {
  $('logout-btn').onclick = async () => { await api('/api/logout', { method: 'POST' }); location.href = '/login'; };

  document.querySelectorAll('#tabs .tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('#tabs .tab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.tabpane').forEach(x => x.classList.remove('active'));
      tab.classList.add('active');
      $('tab-' + tab.dataset.tab).classList.add('active');
    };
  });

  $('prev-month').onclick = () => shiftMonth(-1);
  $('next-month').onclick = () => shiftMonth(1);
  $('today-btn').onclick = () => { const t = new Date(); view = { year: t.getFullYear(), month: t.getMonth() + 1 }; loadCalendar(); };

  $('ai-daily-btn').onclick = () => runAi('daily');
  $('ai-month-btn').onclick = () => runAi('monthly');
  $('ai-copy').onclick = copyAiResult;

  ['task-filter-status', 'task-filter-dept', 'task-filter-coord'].forEach(id => {
    $(id).addEventListener('change', loadTasks);
  });
  $('task-new-btn').onclick = openTaskForm;
  $('t-save').onclick = saveTask;

  $('entry-add-btn').onclick = () => openEntryForm('add');
  $('e-save').onclick = saveEntry;

  document.querySelectorAll('.modal-close').forEach(b => { b.onclick = () => closeModal(b.dataset.close); });
  document.querySelectorAll('.modal').forEach(m => {
    m.addEventListener('mousedown', e => { if (e.target === m) m.classList.add('hidden'); });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
  });

  // 日详情弹窗内的事件委托(编辑/作废按钮)
  $('day-modal-body').addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'edit') openEntryForm('edit', btn.dataset.office, btn.dataset.id);
    if (btn.dataset.action === 'void') voidEntry(btn.dataset.office, btn.dataset.id);
  });

  $('user-add-form').addEventListener('submit', addUser);
  $('nu-role').addEventListener('change', () => {
    $('nu-office-line').style.display = $('nu-role').value === 'office' ? '' : 'none';
  });
}

function applyRole() {
  $('user-name').textContent = ME.name;
  $('user-role').textContent = ROLE_LABELS[ME.role] + (ME.office ? ' · ' + ME.office : '');
  document.querySelectorAll('.admin-tab').forEach(x => x.classList.toggle('hidden', !META.is_admin));
  $('ai-bar').classList.toggle('hidden', !META.can_ai);
  $('task-new-btn').classList.toggle('hidden', !META.can_publish);
  const deptSel = $('task-filter-dept');
  if (META.is_leader) {
    deptSel.classList.remove('hidden');
    deptSel.innerHTML = '<option value="">全部部门</option><option>综合办</option><option>教学办</option><option>学生办</option>';
  }
  $('nu-office-line').style.display = 'none';
}

/* ================= 月度日历 ================= */

function shiftMonth(n) {
  let m = view.month + n, y = view.year;
  if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
  view = { year: y, month: m };
  loadCalendar();
}

async function loadCalendar() {
  calendarData = await api(`/api/calendar?year=${view.year}&month=${view.month}`);
  renderCalendar();
  updateAiLabels();
}

function renderCalendar() {
  $('month-label').textContent = `${view.year}年${String(view.month).padStart(2, '0')}月`;
  $('legend').innerHTML = META.offices_visible.map(o =>
    `<span><i class="dot dot-${OFFICE_CLS[o]}"></i>${o}</span>`).join('');

  const grid = $('cal-grid');
  grid.innerHTML = '';
  const first = new Date(view.year, view.month - 1, 1);
  const lead = (first.getDay() + 6) % 7;                 // 周一为第一列
  const daysInMonth = new Date(view.year, view.month, 0).getDate();
  for (let i = 0; i < lead; i++) {
    const b = document.createElement('div'); b.className = 'cal-cell blank'; grid.appendChild(b);
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = `${view.year}-${String(view.month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const cell = document.createElement('div');
    const dow = (new Date(view.year, view.month - 1, d).getDay() + 6) % 7;
    cell.className = 'cal-cell' + (dow >= 5 ? ' wend' : '')
      + (ds === calendarData.today ? ' today' : '') + (ds === selectedDate ? ' selected' : '');
    let inner = `<div class="cal-day">${d}</div><div class="cal-dots">`;
    for (const o of META.offices_visible) {
      const n = (calendarData.days[o] || {})[String(d)];
      if (n) inner += `<span class="dot dot-${OFFICE_CLS[o]}" title="${o} ${n}条">${n}</span>`;
    }
    inner += '</div>';
    const tk = (calendarData.task_days || {})[String(d)];
    if (tk) {
      inner += `<div class="cal-task"><span class="tag-task">任${tk.total}</span>`
        + (tk.coord ? '<span class="tag-coord">协</span>' : '') + '</div>';
    }
    cell.innerHTML = inner;
    cell.onclick = () => { selectedDate = ds; openDay(ds); };
    grid.appendChild(cell);
  }
}

function updateAiLabels() {
  const d = selectedDate || calendarData.today;
  $('ai-daily-date').textContent = `(${Number(d.slice(5, 7))}月${Number(d.slice(8, 10))}日)`;
  $('ai-month-date').textContent = `(${view.year}年${String(view.month).padStart(2, '0')}月)`;
}

/* ================= 日期详情与台账 ================= */

function tagOf(text, cls) { return `<span class="tag tag-${cls}">${esc(text)}</span>`; }

async function openDay(date) {
  const d = await api('/api/ledger/day?date=' + date);
  dayEntries = d.entries || {};
  const dt = new Date(date + 'T00:00:00');
  $('day-modal-title').textContent = `${dt.getMonth() + 1}月${dt.getDate()}日 工作详情`;
  let html = '';
  for (const office of META.offices_visible) {
    const rows = (d.entries || {})[office] || [];
    html += `<div class="office-block"><div class="office-title office-${OFFICE_CLS[office]}">${esc(office)}(${rows.length}条)</div>`;
    html += rows.map(r => entryCard(office, r)).join('') || '<div class="empty">当日暂无工作记录</div>';
    html += '</div>';
  }
  // 当日截止任务
  const td = await api('/api/tasks?due=' + date);
  if (td.tasks.length) {
    html += `<div class="office-block"><div class="office-title" style="background:#5A6B8C">当日截止任务(${td.tasks.length})</div>`;
    html += '<div class="day-task-list">' + td.tasks.map(t =>
      `<div class="tt"><span>${esc(t['任务标题'])}</span><span>${esc(t['指派部门'])} · ${tagOf(t['状态'], STATUS_CLS[t['状态']] || 'gray')}</span></div>`
    ).join('') + '</div></div>';
  }
  $('day-modal-body').innerHTML = html;
  $('entry-add-btn').classList.toggle('hidden', ME.role !== 'office');
  openModal('day-modal');
}

function entryCard(office, r) {
  const mine = ME.role === 'office' && ME.office === office;
  const files = (r['附件'] || '').split(';').filter(Boolean)
    .map(p => `<a href="/files/${encodeURIComponent(p)}" target="_blank">📎 ${esc(p.split('/').pop())}</a>`).join('');
  const sens = r['敏感事项'] === '是' ? tagOf('敏感', 'secret') : '';
  return `<div class="entry-card${r['敏感事项'] === '是' ? ' sensitive' : ''}">
    <div class="entry-top">
      ${tagOf(r['工作大类'] || '其他', 'cat')}
      ${tagOf(r['完成情况'] || '', STATUS_CLS[r['完成情况']] === 'green' ? 'green' : STATUS_CLS[r['完成情况']] === 'red' ? 'red' : 'blue')}
      ${sens}
    </div>
    <div class="entry-content">${esc(r['工作内容'])}</div>
    ${files ? `<div class="entry-files">${files}</div>` : ''}
    <div class="entry-meta">
      ${r['参与人员'] ? '参与:' + esc(r['参与人员']) + ' ' : ''}
      ${r['备注'] ? '备注:' + esc(r['备注']) : ''}
    </div>
    <div class="entry-foot">${esc(r['编号'])} · 录入:${esc(r['录入人'])} ${esc(r['录入时间'])}
      ${mine ? `<button class="btn" data-action="edit" data-office="${esc(office)}" data-id="${esc(r['编号'])}">修改</button>
      <button class="btn" data-action="void" data-office="${esc(office)}" data-id="${esc(r['编号'])}">作废</button>` : ''}
    </div>
  </div>`;
}

function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(id) { $(id).classList.add('hidden'); }

function openEntryForm(mode, office, entryId) {
  editingEntry = null;
  pendingUploads = [];
  removeAttachments = [];
  $('e-upload-status').textContent = '';
  $('e-files').value = '';
  let targetOffice = ME.office;
  let row = null;

  if (mode === 'edit') {
    targetOffice = office;
    row = findEntry(office, entryId);
    if (!row) { toast('未找到该条台账', 'err'); return; }
    editingEntry = { office, id: entryId };
  }
  const cats = META.categories[targetOffice] || ['其他'];
  $('e-category').innerHTML = cats.map(c => `<option${row && row['工作大类'] === c ? ' selected' : ''}>${esc(c)}</option>`).join('');
  $('e-completion').innerHTML = META.completion.map(c =>
    `<option${row && row['完成情况'] === c ? ' selected' : ''}>${esc(c)}</option>`).join('');
  $('e-date').textContent = `${selectedDate}(${targetOffice})`;
  $('e-content').value = row ? row['工作内容'] : '';
  $('e-participants').value = row ? row['参与人员'] : '';
  $('e-remark').value = row ? row['备注'] : '';
  $('e-sensitive').checked = row ? row['敏感事项'] === '是' : false;
  $('entry-modal-title').textContent = mode === 'edit' ? '修改工作台账' : '登记本办工作';

  let attHtml = '';
  if (row) {
    const files = (row['附件'] || '').split(';').filter(Boolean);
    if (files.length) {
      attHtml = '<div class="field">已有附件(勾选=从本条移除,不删除归档文件)<div class="attach-list">' +
        files.map(p => `<label class="att-item"><input type="checkbox" data-att="${esc(p)}">
          <a href="/files/${encodeURIComponent(p)}" target="_blank">📎 ${esc(p.split('/').pop())}</a></label>`).join('') + '</div></div>';
    }
  }
  $('e-attachments').innerHTML = attHtml;
  $('e-attachments').querySelectorAll('input[data-att]').forEach(cb => {
    cb.addEventListener('change', () => {
      const p = cb.dataset.att;
      if (cb.checked) { if (!removeAttachments.includes(p)) removeAttachments.push(p); }
      else removeAttachments = removeAttachments.filter(x => x !== p);
    });
  });
  openModal('entry-modal');
}

function findEntry(office, entryId) {
  return ((dayEntries[office] || []).find(r => r['编号'] === entryId)) || null;
}

async function saveEntry() {
  const content = $('e-content').value.trim();
  if (!content) { toast('工作内容不能为空', 'err'); return; }
  const st = $('e-upload-status');
  const files = $('e-files').files;
  try {
    for (let i = 0; i < files.length; i++) {
      st.className = 'ai-status';
      st.textContent = `正在上传附件 ${i + 1}/${files.length} …`;
      const fd = new FormData();
      fd.append('file', files[i]);
      fd.append('date', selectedDate);
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || '附件上传失败。');
      pendingUploads.push(d.path);
    }
    st.textContent = '正在保存台账 …';
    const body = {
      office: ME.office, date: selectedDate,
      category: $('e-category').value, content,
      completion: $('e-completion').value,
      participants: $('e-participants').value,
      remark: $('e-remark').value,
      sensitive: $('e-sensitive').checked,
      attachments: pendingUploads,
      remove_attachments: removeAttachments
    };
    if (editingEntry) {
      body.entry_id = editingEntry.id;
      await api('/api/ledger/update', { method: 'POST', body: JSON.stringify(body) });
      toast('台账已修改', 'ok');
    } else {
      await api('/api/ledger/add', { method: 'POST', body: JSON.stringify(body) });
      toast('台账已登记', 'ok');
    }
    closeModal('entry-modal');
    await loadCalendar();
    openDay(selectedDate);
  } catch (e) {
    st.className = 'ai-status err';
    st.textContent = e.message;
  }
}

async function voidEntry(office, entryId) {
  if (!confirm(`确定作废台账 ${entryId} ?\n作废后前台不再显示,记录仍保留于 Excel 归档,可追溯。`)) return;
  try {
    await api('/api/ledger/void', { method: 'POST', body: JSON.stringify({ office, entry_id: entryId }) });
    toast('已作废', 'ok');
    await loadCalendar();
    openDay(selectedDate);
  } catch (e) { toast(e.message, 'err'); }
}

/* ================= 工作安排 ================= */

function badgeFromTasks(list) {
  let n = 0;
  if (ME.role === 'office') {
    n = list.filter(t => t['指派部门'] === ME.office && (t['状态'] === '待接收' || t['状态'] === '进行中')).length;
  } else {
    n = list.filter(t => t['需协调资源'] === '是' && t['状态'] !== '已完成').length;
  }
  const b = $('task-badge');
  b.classList.toggle('hidden', n === 0);
  b.textContent = n;
}

async function loadTasks() {
  const params = new URLSearchParams();
  if ($('task-filter-status').value) params.set('status', $('task-filter-status').value);
  if ($('task-filter-dept').value) params.set('dept', $('task-filter-dept').value);
  if ($('task-filter-coord').checked) params.set('coord', '1');
  const d = await api('/api/tasks?' + params.toString());
  badgeFromTasks(d.tasks);
  const tb = $('task-tbody');
  tb.innerHTML = d.tasks.map(t => {
    const overdue = t['截止日期'] < todayStr() && t['状态'] !== '已完成';
    return `<tr>
      <td>${esc(t['任务编号'])}</td>
      <td><a class="link" href="javascript:void(0)" onclick="openTask('${esc(t['任务编号'])}')">${esc(t['任务标题'])}</a></td>
      <td>${esc(t['指派部门'])}</td>
      <td>${esc(t['责任人'] || '—')}</td>
      <td class="${overdue ? 'tag-due' : ''}">${esc(t['截止日期'])}${overdue ? ' 已逾期' : ''}</td>
      <td>${t['优先级'] === '高' ? tagOf('高', 'red') : t['优先级'] === '低' ? tagOf('低', 'gray') : tagOf('中', 'blue')}</td>
      <td>${tagOf(t['状态'], STATUS_CLS[t['状态']] || 'gray')}</td>
      <td>${t['需协调资源'] === '是' ? tagOf('需协调', 'red') : '—'}</td>
      <td>${esc(t['发布人'])}</td>
      <td><button class="btn btn-sm" onclick="openTask('${esc(t['任务编号'])}')">详情</button></td>
    </tr>`;
  }).join('');
  $('task-empty').classList.toggle('hidden', d.tasks.length > 0);
}

function openTaskForm() {
  $('t-title').value = ''; $('t-owner').value = ''; $('t-desc').value = '';
  $('t-due').value = selectedDate || todayStr();
  openModal('task-form-modal');
}

async function saveTask() {
  const body = {
    title: $('t-title').value, dept: $('t-dept').value, owner: $('t-owner').value,
    due: $('t-due').value, priority: $('t-priority').value, desc: $('t-desc').value
  };
  try {
    await api('/api/tasks', { method: 'POST', body: JSON.stringify(body) });
    toast('任务已发布', 'ok');
    closeModal('task-form-modal');
    loadTasks();
  } catch (e) { toast(e.message, 'err'); }
}

window.openTask = async function (id) {
  const d = await api('/api/tasks/' + encodeURIComponent(id));
  const t = d.task;
  $('task-detail-title').textContent = `${t['任务编号']} ${t['任务标题']}`;
  const overdue = t['截止日期'] < todayStr() && t['状态'] !== '已完成';
  let html = `<div class="task-info">
    <span class="k">指派部门</span><span>${esc(t['指派部门'])}</span>
    <span class="k">责任人</span><span>${esc(t['责任人'] || '—')}</span>
    <span class="k">截止日期</span><span class="${overdue ? 'tag-due' : ''}">${esc(t['截止日期'])}${overdue ? '(已逾期)' : ''}</span>
    <span class="k">优先级</span><span>${esc(t['优先级'])}</span>
    <span class="k">当前状态</span><span>${tagOf(t['状态'], STATUS_CLS[t['状态']] || 'gray')}
      ${t['需协调资源'] === '是' ? tagOf('需协调资源', 'red') : ''}</span>
    <span class="k">工作说明</span><span>${esc(t['工作说明'] || '—')}</span>
    <span class="k">发布人</span><span>${esc(t['发布人'])} · ${esc(t['发布时间'])}</span>
    ${t['办结时间'] ? `<span class="k">办结时间</span><span>${esc(t['办结时间'])}</span>` : ''}
  </div>
  <div class="replies"><b>跟进记录(${d.replies.length})</b><div style="margin-top:8px">`;

  html += d.replies.map(r => `<div class="reply-item${r['申请协调'] === '是' ? ' coord' : ''}">
      <div class="reply-head">${esc(r['回复人'])} · ${esc(r['回复时间'])} · ${tagOf(r['进度状态'], STATUS_CLS[r['进度状态']] || 'gray')}
        ${r['申请协调'] === '是' ? tagOf('申请协调资源', 'red') : ''}</div>
      <div class="reply-content">${esc(r['回复内容'])}</div>
    </div>`).join('') || '<div class="empty">暂无跟进记录</div>';
  html += '</div>';

  if (d.flags.can_reply) {
    html += `<div class="reply-form">
      <textarea id="reply-content" rows="3" placeholder="填写进度反馈、下一步安排或需协调的事项…"></textarea>
      <div class="row2">
        <label>进度状态
          <select id="reply-progress"><option>进行中</option><option>待接收</option><option>已完成</option><option>已延期</option></select>
        </label>
        <label class="check-line warn"><input type="checkbox" id="reply-coord"> 需要学院协调资源</label>
        <button class="btn btn-red btn-sm" id="reply-submit">提交跟进</button>
      </div>
    </div>`;
  }
  if (d.flags.can_manage) {
    html += `<div class="reply-form">
      <div class="row2">
        <label>管理层操作
          <select id="mgr-status"><option>进行中</option><option>待接收</option><option>已延期</option><option>已完成(办结)</option></select>
        </label>
        <label class="check-line"><input type="checkbox" id="mgr-resolve"> 同步解除协调标记</label>
        <button class="btn btn-blue btn-sm" id="mgr-submit">更新状态</button>
      </div>
    </div>`;
  }
  html += '</div>';
  $('task-detail-body').innerHTML = html;

  const rs = $('reply-submit');
  if (rs) rs.onclick = async () => {
    try {
      await api(`/api/tasks/${encodeURIComponent(id)}/reply`, {
        method: 'POST', body: JSON.stringify({
          content: $('reply-content').value,
          progress: $('reply-progress').value,
          need_coord: $('reply-coord').checked
        })
      });
      toast('跟进已提交', 'ok');
      openTask(id); loadTasks();
    } catch (e) { toast(e.message, 'err'); }
  };
  const ms = $('mgr-submit');
  if (ms) ms.onclick = async () => {
    try {
      await api(`/api/tasks/${encodeURIComponent(id)}/status`, {
        method: 'POST', body: JSON.stringify({
          status: $('mgr-status').value.replace('(办结)', ''),
          resolve_coord: $('mgr-resolve').checked
        })
      });
      toast('状态已更新', 'ok');
      openTask(id); loadTasks();
    } catch (e) { toast(e.message, 'err'); }
  };
  openModal('task-detail-modal');
};

/* ================= AI 智能生成 ================= */

async function runAi(kind) {
  const btns = [$('ai-daily-btn'), $('ai-month-btn')];
  btns.forEach(b => b.disabled = true);
  const st = $('ai-status');
  st.className = 'ai-status';
  st.textContent = kind === 'daily'
    ? '正在读取当日台账并生成简讯,最长约 1 分钟,请稍候…'
    : '正在读取本月台账并生成总结初稿,最长约 1 分钟,请稍候…';
  $('ai-result-wrap').classList.add('hidden');
  try {
    const body = kind === 'daily'
      ? { date: selectedDate || calendarData.today }
      : { year: view.year, month: view.month };
    const d = await api(kind === 'daily' ? '/api/ai/daily' : '/api/ai/month',
      { method: 'POST', body: JSON.stringify(body) });
    st.className = 'ai-status ok';
    st.textContent = '生成完成。以下为初稿,可直接编辑后使用:';
    $('ai-result').value = d.text;
    $('ai-filtered').textContent = d.filtered.length
      ? `已自动过滤敏感条目 ${d.filtered.length} 条:${d.filtered.map(f => f.编号).join('、')}`
      : '未发现需过滤的敏感条目';
    $('ai-result-wrap').classList.remove('hidden');
  } catch (e) {
    st.className = 'ai-status err';
    st.textContent = e.message;
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

function copyAiResult() {
  const ta = $('ai-result');
  ta.select();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value).then(() => toast('已复制到剪贴板', 'ok'));
  } else {
    document.execCommand('copy');
    toast('已复制到剪贴板', 'ok');
  }
}

/* ================= 系统管理 ================= */

async function loadUsers() {
  try {
    const d = await api('/api/users');
    $('user-tbody').innerHTML = d.users.map(u => `<tr>
      <td>${esc(u.username)}</td><td>${esc(u.name)}</td>
      <td>${ROLE_LABELS[u.role] || u.role}</td><td>${esc(u.office || '—')}</td>
      <td>${u.active ? tagOf('正常', 'green') : tagOf('已停用', 'red')}</td>
      <td>
        <button class="btn btn-sm" onclick="resetPwd('${esc(u.username)}')">重置密码</button>
        <button class="btn btn-sm" onclick="toggleUser('${esc(u.username)}')">${u.active ? '停用' : '启用'}</button>
      </td></tr>`).join('');
  } catch (e) { /* 非管理员忽略 */ }
}

window.resetPwd = async function (username) {
  const p = prompt(`为账号 ${username} 设置新密码(至少6位):`);
  if (!p) return;
  try {
    await api('/api/users/reset', { method: 'POST', body: JSON.stringify({ username, password: p }) });
    toast('密码已重置', 'ok');
  } catch (e) { toast(e.message, 'err'); }
};

window.toggleUser = async function (username) {
  try {
    await api('/api/users/toggle', { method: 'POST', body: JSON.stringify({ username }) });
    loadUsers();
  } catch (e) { toast(e.message, 'err'); }
};

async function addUser(e) {
  e.preventDefault();
  try {
    await api('/api/users/add', {
      method: 'POST', body: JSON.stringify({
        username: $('nu-username').value, name: $('nu-name').value,
        role: $('nu-role').value, office: $('nu-office').value,
        password: $('nu-password').value
      })
    });
    toast('账号已添加', 'ok');
    $('user-add-form').reset();
    loadUsers();
  } catch (err) { toast(err.message, 'err'); }
}
