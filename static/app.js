'use strict';

// Интерфейс ничего не вычисляет сам: он отправляет тексты файлов на сервер
// и показывает готовый отчёт. Тексты хранятся только в памяти страницы.
const state = {
  files: [],           // [{name, text}]
  report: null,        // ответ /api/analyze
  openDocName: null,   // документ, открытый в панели «Исходный текст»
  highlight: null,     // источник, к которому перешли: {doc_name, paragraph, quote}
  beforeTouched: false,
  qContract: null,
  qField: 'delivery_date',
  requestNo: 0,
};

const ROLE = {
  contract: ['Договор', ''],
  applied: ['Учтено', 'ok'],
  not_in_force: ['Ещё не действует', 'warn'],
  proposal: ['Не согласовано', 'warn'],
  review: ['Требует проверки', 'bad'],
};

const $ = (id) => document.getElementById(id);

// Создаёт элемент. Текст всегда вставляется как текст, а не как HTML:
// содержимое загруженных файлов не может исполниться на странице.
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function badge(role) {
  const [label, tone] = ROLE[role] || ROLE.review;
  return el('span', { class: 'badge ' + tone }, label);
}

function showError(message) {
  $('error').textContent = message || '';
  $('error').hidden = !message;
}

// ---------- Загрузка файлов ----------

async function readFile(file) {
  const buffer = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  } catch (e) {
    return new TextDecoder('windows-1251').decode(buffer);   // старые файлы из Windows
  }
}

function putFile(name, text) {
  const index = state.files.findIndex((f) => f.name === name);
  if (index >= 0) state.files[index] = { name, text };   // повторная загрузка заменяет файл
  else state.files.push({ name, text });
}

async function addFiles(fileList) {
  const skipped = [];
  for (const file of fileList) {
    if (!/\.txt$/i.test(file.name)) { skipped.push(file.name); continue; }
    putFile(file.name, await readFile(file));
  }
  await analyze();
  if (skipped.length) showError('Пропущены файлы не в формате TXT: ' + skipped.join(', '));
}

async function loadSamples() {
  try {
    const response = await fetch('/api/samples');
    const data = await response.json();
    data.files.forEach((f) => putFile(f.name, f.text));
    await analyze();
  } catch (e) {
    showError('Не удалось загрузить учебные файлы: сервер не отвечает.');
  }
}

function removeFile(name) {
  state.files = state.files.filter((f) => f.name !== name);
  if (state.openDocName === name) { state.openDocName = null; state.highlight = null; }
  analyze();
}

// ---------- Запрос отчёта ----------

function defaultBefore(checkIso) {
  // По умолчанию — первое число месяца, следующего за датой проверки.
  const [year, month] = checkIso.split('-').map(Number);
  return month === 12 ? `${year + 1}-01-01` : `${year}-${String(month + 1).padStart(2, '0')}-01`;
}

async function analyze() {
  showError('');
  const checkDate = $('checkDate').value;
  if (!state.files.length) { state.report = null; state.openDocName = null; state.highlight = null; render(); return; }
  if (!checkDate) { showError('Укажите дату проверки.'); return; }
  const requestNo = ++state.requestNo;
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ check_date: checkDate, before_date: $('beforeDate').value || null, files: state.files }),
    });
    const data = await response.json();
    if (requestNo !== state.requestNo) return;          // пришёл ответ на устаревший запрос
    if (!response.ok) { showError(data.error || 'Ошибка обработки.'); return; }
    state.report = data;
    render();
  } catch (e) {
    showError('Сервер не отвечает. Проверьте, что приложение запущено.');
  }
}

// ---------- Общие элементы: источник, значение поля ----------

function openSource(source) {
  state.openDocName = source.doc_name;
  state.highlight = source;
  renderViewer();
}

function sourceButton(source) {
  return el('button', { class: 'src', type: 'button', onclick: () => openSource(source) },
    `${source.doc_name}, абз. ${source.paragraph}`);
}

function pendingBox(p) {
  return el('div', { class: 'fld-pending' + (p.role === 'review' ? ' review' : '') },
    `${ROLE[p.role][0]}: ${p.display} — ${p.title} (${p.reason}). `, sourceButton(p.source));
}

// Значение поля с основанием: цитата, файл и абзац, чем изменено, что не учтено.
function fieldBox(f, options = {}) {
  const box = el('div', { class: 'fld' + (options.small ? ' fld-small' : '') });
  if (!options.hideValue) box.append(el('div', { class: 'fld-value ' + f.status }, f.display));
  if (f.status === 'review') box.append(badge('review'));
  if (f.changed_by) {
    box.append(el('div', { class: 'fld-changed' },
      `Изменено: ${f.changed_by.title}, действует с ${f.changed_by.effective_display}. Было: ${f.original.display}`,
      f.original.source ? [' — ', sourceButton(f.original.source)] : null));
  }
  if (f.source) box.append(el('blockquote', { class: 'quote' }, f.source.quote), sourceButton(f.source));
  for (const note of f.notes) box.append(el('div', { class: 'fld-note' + (f.status === 'review' ? ' review' : '') }, note));
  for (const p of f.pending) box.append(pendingBox(p));
  return box;
}

// ---------- Разделы страницы ----------

function renderDocs() {
  const list = $('docs');
  list.replaceChildren();
  const docs = state.report ? state.report.documents : [];
  for (const d of docs) {
    const meta = d.kind === 'contract'
      ? `${d.title} · ${d.status_label}`
      : [d.title, d.linked_to && `к договору ${d.linked_to}`, d.reason].filter(Boolean).join(' · ');
    list.append(el('li', { class: 'doc' },
      el('div', {},
        el('button', { class: 'src doc-name', type: 'button', onclick: () => openSource({ doc_name: d.name }) }, d.name),
        el('div', { class: 'doc-meta' }, meta)),
      badge(d.role),
      el('button', { class: 'icon-btn', type: 'button', title: 'Убрать файл', 'aria-label': `Убрать ${d.name}`,
        onclick: () => removeFile(d.name) }, '×')));
  }
  $('clearBtn').hidden = !state.files.length;
}

function renderTable() {
  const report = state.report;
  $('tableCard').hidden = !report;
  if (!report) return;
  $('tableTitle').textContent = `Условия договоров на ${report.check_date_display}`;
  // Колонки берём из отчёта: поле, добавленное в правила на сервере, появится здесь само.
  $('tableHead').replaceChildren(el('th', {}, 'Договор'), ...report.fields.map((f) => el('th', {}, f.label)));
  const body = $('table').tBodies[0];
  body.replaceChildren();
  if (!report.contracts.length) {
    body.append(el('tr', {}, el('td', { colspan: report.fields.length + 1, class: 'muted' },
      'Среди загруженных файлов нет договоров.')));
    return;
  }
  for (const row of report.contracts) {
    body.append(el('tr', {},
      el('td', {},
        el('div', { class: 'num' }, row.number),
        el('button', { class: 'src', type: 'button', onclick: () => openSource({ doc_name: row.doc_name }) }, row.doc_name),
        row.flags.map((flag) => el('div', { class: 'flag' }, flag)),
        el('ul', { class: 'related' }, row.related.map((r) => el('li', {}, badge(r.role), ' ', r.title)))),
      report.fields.map((f) => el('td', {}, fieldBox(row[f.key], { small: f.key === 'supplier' })))));
  }
}

function valueFields() {
  return state.report.fields.filter((f) => f.key !== 'supplier');
}

function renderPending() {
  const list = $('pending');
  list.replaceChildren();
  if (state.report) {
    for (const row of state.report.contracts) {
      for (const field of valueFields()) {
        const f = row[field.key];
        for (const p of f.pending) {
          list.append(el('li', {},
            el('div', { class: 'head' }, badge(p.role),
              el('strong', {}, `${row.number} · ${field.label}: ${p.display}`),
              el('span', { class: 'muted' }, `действует сейчас: ${f.display}`)),
            el('div', {}, `${p.title} — ${p.reason}`),
            el('blockquote', { class: 'quote' }, p.source.quote),
            sourceButton(p.source)));
        }
      }
    }
  }
  $('pendingCard').hidden = !list.children.length;
}

function renderReview() {
  const list = $('review');
  list.replaceChildren();
  for (const u of (state.report ? state.report.unlinked : [])) {
    list.append(el('li', {},
      el('div', { class: 'head' }, badge('review'), el('strong', {}, u.doc_name)),
      el('div', {}, `${u.reason}. Документ не учтён.`),
      el('button', { class: 'src', type: 'button', onclick: () => openSource({ doc_name: u.doc_name }) }, 'Открыть текст')));
  }
  $('reviewCard').hidden = !list.children.length;
}

function renderQuestions() {
  const report = state.report;
  $('questionsCard').hidden = !report || !report.contracts.length;
  if (!report || !report.contracts.length) return;

  // Вопрос 1: значение выбранного поля по выбранному договору.
  if (!report.contracts.some((r) => r.id === state.qContract)) state.qContract = report.contracts[0].id;
  $('qContract').replaceChildren(...report.contracts.map((r) =>
    el('option', { value: r.id, selected: r.id === state.qContract }, `${r.number} — ${r.supplier.display}`)));
  $('qField').replaceChildren(...report.fields.map((f) =>
    el('option', { value: f.key, selected: f.key === state.qField }, f.label)));
  const row = report.contracts.find((r) => r.id === state.qContract);
  const field = report.fields.find((f) => f.key === state.qField);
  $('qAnswer').replaceChildren(
    el('div', { class: 'answer-line' }, `${field.label} — договор ${row.number}, на ${report.check_date_display}: `,
      el('strong', {}, row[field.key].display)),
    fieldBox(row[field.key], { hideValue: true }));

  // Вопрос 2: поставка раньше даты и неучтённые изменения срока.
  const answer = $('beforeAnswer');
  answer.replaceChildren();
  const before = report.delivery_before;
  if (!before) { answer.append(el('div', { class: 'muted' }, 'Укажите дату.')); return; }
  const byId = (id) => report.contracts.find((r) => r.id === id);
  const deliveryItem = (r) => el('li', {},
    el('strong', {}, `${r.number} — ${r.delivery_date.display}`), ` · ${r.supplier.display} · `,
    r.delivery_date.source ? sourceButton(r.delivery_date.source) : null,
    r.delivery_date.pending.map(pendingBox));
  const earlier = before.earlier.map(byId);
  answer.append(el('div', { class: 'answer-line' }, earlier.length
    ? `Раньше ${before.display} поставка запланирована по договорам: ${earlier.length} из ${report.contracts.length}.`
    : `Раньше ${before.display} поставок не запланировано.`));
  if (earlier.length) {
    answer.append(el('ul', {}, earlier.map(deliveryItem)));
    const changed = earlier.filter((r) => r.delivery_date.pending.length).map((r) => r.number);
    answer.append(el('div', {}, changed.length
      ? `Неучтённые изменения срока по этим договорам: есть (${changed.join(', ')}).`
      : 'Неучтённых изменений срока по этим договорам нет.'));
  }
  if (before.other_pending.length) {
    answer.append(el('div', { class: 'muted' }, 'По остальным договорам тоже есть неучтённые изменения срока:'),
      el('ul', {}, before.other_pending.map(byId).map(deliveryItem)));
  }
  if (before.unknown.length) {
    answer.append(el('div', { class: 'fld-note review' },
      'Срок поставки не определён, сравнить с датой нельзя: ' + before.unknown.map((id) => byId(id).number).join(', ')));
  }
}

function renderViewer() {
  const docs = state.report ? state.report.documents : [];
  const select = $('viewerDoc');
  const body = $('viewerBody');
  select.hidden = !docs.length;
  const doc = docs.find((d) => d.name === state.openDocName);
  select.replaceChildren(
    el('option', { value: '', selected: !doc }, 'Выберите документ'),
    ...docs.map((d) => el('option', { value: d.name, selected: doc && d.name === doc.name }, d.name)));
  body.replaceChildren();
  if (!doc) {
    body.append(el('p', { class: 'muted' }, docs.length
      ? 'Нажмите на источник рядом со значением — здесь откроется нужный абзац.'
      : 'Загрузите документы и нажмите на источник рядом со значением — здесь откроется нужный абзац.'));
    return;
  }
  body.append(el('p', { class: 'viewer-meta' }, badge(doc.role), ' ',
    [doc.title, doc.linked_to && doc.kind !== 'contract' && `к договору ${doc.linked_to}`, doc.reason || doc.status_label]
      .filter(Boolean).join(' · ')));
  const hl = state.highlight && state.highlight.doc_name === doc.name ? state.highlight : null;
  let target = null;
  for (const p of doc.paragraphs) {
    const isTarget = hl && hl.paragraph === p.n;
    const text = el('div', { class: 'par-text' });
    const at = isTarget && hl.quote ? p.text.indexOf(hl.quote) : -1;
    if (at >= 0) {
      text.append(p.text.slice(0, at), el('mark', {}, hl.quote), p.text.slice(at + hl.quote.length));
    } else {
      text.append(p.text);
    }
    const par = el('div', { class: 'par' + (isTarget ? ' target' : ''), id: `par-${p.n}` },
      el('div', { class: 'par-n' }, p.n), text);
    if (isTarget) target = par;
    body.append(par);
  }
  if (!target) { body.scrollTop = 0; return; }
  if (getComputedStyle($('viewer')).position === 'sticky') {
    body.scrollTop = target.offsetTop - (body.clientHeight - target.offsetHeight) / 2;   // панель сбоку
  } else {
    target.scrollIntoView({ block: 'center' });                                           // панель под таблицей
  }
}

function render() {
  renderDocs();
  renderTable();
  renderPending();
  renderReview();
  renderQuestions();
  renderViewer();
}

// ---------- События ----------

$('fileInput').addEventListener('change', async (event) => {
  await addFiles([...event.target.files]);
  event.target.value = '';     // чтобы тот же файл можно было выбрать повторно после правки
});

const dropzone = $('dropzone');
dropzone.addEventListener('dragover', (event) => { event.preventDefault(); dropzone.classList.add('over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('over'));
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropzone.classList.remove('over');
  addFiles([...event.dataTransfer.files]);
});

// Файл, брошенный мимо области загрузки, не должен открыться вместо страницы.
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('drop', (event) => event.preventDefault());

$('samplesBtn').addEventListener('click', loadSamples);
$('clearBtn').addEventListener('click', () => { state.files = []; analyze(); });

$('checkDate').addEventListener('change', () => {
  if (!state.beforeTouched && $('checkDate').value) $('beforeDate').value = defaultBefore($('checkDate').value);
  analyze();
});
$('beforeDate').addEventListener('change', () => { state.beforeTouched = true; analyze(); });
$('qContract').addEventListener('change', (event) => { state.qContract = event.target.value; renderQuestions(); });
$('qField').addEventListener('change', (event) => { state.qField = event.target.value; renderQuestions(); });
$('viewerDoc').addEventListener('change', (event) => {
  state.openDocName = event.target.value || null;
  state.highlight = null;
  renderViewer();
});

$('beforeDate').value = defaultBefore($('checkDate').value);
render();
