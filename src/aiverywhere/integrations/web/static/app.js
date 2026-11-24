"use strict";

const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="session"]').content;
const titles = {chat: "对话与工作", overview: "实例概览", memory: "记忆与技能", agent: "Agent 定义", sessions: "会话与任务", logs: "运行日志"};
const labels = {completed: "已完成", partial: "部分完成", failed: "失败", cancelled: "已取消", interrupted: "已中断", running: "运行中"};
const kindName = (kind) => kind === "skill" ? "技能" : kind === "clue" ? "线索" : "记忆";
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const date = (seconds) => seconds ? new Date(seconds * 1000).toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}) : "—";
let workspace, page, editing, agentDraft;
let agentSelected = "SKILL.md";
let logRows = [], logBefore = null;
let filter = "all", query = "", toastTimer;
let workspaceTag, refreshNumber = 0;

async function api(path, method = "GET", data) {
  const headers = {"X-Aiverywhere-Token": token};
  if (data) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method, headers, body: data ? JSON.stringify(data) : undefined});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败");
  return result;
}

function toast(message, error = false) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, error ? 6500 : 3000);
}

function empty(icon, title, detail) {
  return `<div class="empty"><i class="ico ${icon}"></i><strong>${title}</strong><span>${detail}</span></div>`;
}

function memoryTable(items, filtered = false) {
  if (!items.length) return filtered ? empty("layers", "没有匹配的条目", "试试其他标题或类型。") :
    empty("layers", "还没有记忆或技能", "点击“新建条目”，或在任务中让 agent 保存经验。");
  const rows = items.map(i => `<tr><td><button class="link" data-action="edit" data-id="${esc(i.id)}">${esc(i.title)}</button></td>
    <td><span class="kind ${i.kind === "skill" ? "skill" : "fact"}">${kindName(i.kind)}</span></td>
    <td class="meta">r${esc(i.revision)}</td><td class="meta">${date(i.updated)}</td></tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr><th>标题</th><th>类型</th><th>修订</th><th>更新时间</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function agentPreview() {
  const agent = workspace.agent;
  const lines = agent.text.split("\n").slice(0, 6).map((line, i) => {
    const css = line.startsWith("---") || line.startsWith("#") ? "comment" : "syntax";
    return `<div class="code-line"><b>${i + 1}</b><span class="${css}">${esc(line)}</span></div>`;
  }).join("");
  return `<section class="panel"><div class="panel-head"><h2>Agent 定义</h2><a class="text-button" href="#agent">查看文件</a></div>
    <div class="filebar"><span class="filename">SKILL.md</span><span class="badge">${agent.local ? "本地版本" : "默认模板"}</span></div>
    <div class="source" tabindex="0" aria-label="文件预览">${lines}</div>
    <div class="panel-foot"><span>内容修订</span><span class="revision">${esc(agent.revision.slice(0,12))}</span></div></section>`;
}

function activity() {
  const logs = workspace.logs.rows;
  const days = Array.from({length: 7}, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - 6 + i);
    const count = logs.filter(row => new Date(row.time * 1000).toDateString() === d.toDateString()).length;
    return {label: (d.getMonth() + 1) + "/" + d.getDate(), count};
  });
  const peak = Math.max(1, ...days.map(day => day.count));
  const bars = days.map(day => `<div class="day" title="${day.label} · ${day.count} 次"><span class="level-${Math.ceil(day.count / peak * 10)}"></span></div>`).join("");
  return `<section class="panel"><div class="panel-head"><h2>运行活动</h2><a class="text-button" href="#logs">运行记录</a></div>
    <div class="chart-wrap"><div class="chart" role="img" aria-label="${days.map(d => d.label + '：' + d.count + ' 次').join('，')}">${bars}</div>
    <div class="axis">${days.map(d => `<span>${d.label}</span>`).join("")}</div></div>
    <div class="activity-note">${logs.length ? "最近一次运行 · " + date(logs[0].time) : "本项目还没有运行记录"}</div>
    <div class="panel-foot"><span>${workspace.logs.before ? "基于最近 50 条日志" : "来自项目日志"}</span><a class="text-button" href="#logs">查看日志</a></div></section>`;
}

function bridgesPanel() {
  const bridges = workspace.bridges || [];
  const rows = bridges.map(item => {
    const health = item.health ? (item.health.ok ? "在线" : "不可达") : (item.enabled ? "已登记" : "未启用");
    return `<tr><td><b>${esc(item.name)}</b><div class="meta mono">${esc(item.id)}</div></td>
      <td><span class="kind">${esc(item.channel)}</span></td>
      <td>${item.channel_configured ? '<span class="badge">已配置</span>' : '<span class="faint">未配置</span>'}</td>
      <td>${esc(health)}</td><td class="meta mono" title="${esc(item.path)}">${esc(item.command.join(" ") || "—")}</td></tr>`;
  }).join("");
  return `<section class="panel"><div class="panel-head"><h2>Bridge 插件</h2><small>${bridges.length} 个</small></div>
    ${bridges.length ? `<div class="table-wrap"><table><thead><tr><th>Bridge</th><th>Channel</th><th>配置</th><th>健康</th><th>启动命令</th></tr></thead><tbody>${rows}</tbody></table></div>` :
      empty("layers", "还没有 bridge", "把 bridge 目录放到项目的 bridges/，编写 bridge.json 后刷新。")}
    <div class="panel-foot"><span>核心只读取 manifest，不导入 bridge 代码</span><a class="text-button" href="https://github.com/ChanX96/aiverywhere/blob/main/bridges/README.md" target="_blank" rel="noreferrer">开发说明</a></div></section>`;
}

function overview() {
  const facts = workspace.memory.filter(i => i.kind === "fact").length;
  const stats = [["layers","项目记忆",facts,"#memory"],["spark","已学技能",workspace.memory.length - facts,"#memory"],
    ["terminal","近期运行",String(workspace.logs.rows.length) + (workspace.logs.before ? "+" : ""),"#logs"]];
  return `<div class="stats">${stats.map(([icon,label,value,href]) => `<a class="stat" href="${href}"><div class="stat-label"><i class="ico ${icon}"></i>${label}</div><strong class="stat-number">${value}</strong></a>`).join("")}</div>
    <div class="split">${agentPreview()}${activity()}</div>${bridgesPanel()}<section class="panel">
    <div class="panel-head"><h2>最近更新</h2><a class="text-button" href="#memory">全部条目</a></div>${memoryTable(workspace.memory.slice(0,5))}</section>`;
}

function filterMemory() {
  const needle = query.trim().toLocaleLowerCase();
  const items = workspace.memory.filter(i => (filter === "all" || i.kind === filter) && i.title.toLocaleLowerCase().includes(needle));
  $("#memory-table").innerHTML = memoryTable(items, Boolean(needle || filter !== "all"));
}

function memoryView() {
  return `<section class="panel"><div class="filterbar"><div class="segmented" aria-label="类型筛选">
    ${[["all","全部"],["fact","记忆"],["skill","技能"]].map(([key,label]) => `<button class="pill-button" data-filter="${key}" aria-pressed="${filter === key}">${label}</button>`).join("")}</div>
    <input class="search" type="search" id="search" value="${esc(query)}" placeholder="搜索标题" aria-label="搜索标题"></div><div id="memory-table"></div></section>`;
}

function agentView() {
  const agent = workspace.agent;
  const files = agent.files || [{path:"SKILL.md"}];
  const selected = agentDraft?.path || agentSelected;
  const current = files.find(item => item.path === selected) || files[0];
  const text = agentDraft?.text ?? (selected === "SKILL.md" ? agent.text : "");
  const local = selected === "SKILL.md" ? agent.local : true;
  const list = files.map(item => `<button class="agent-file ${item.path === selected ? "active" : ""}" data-action="agent-file" data-path="${esc(item.path)}">
    <span>${esc(item.path)}</span><small>${Math.ceil(item.size / 1024)} KiB</small></button>`).join("");
  return `<section class="panel agent-panel"><div class="agent-layout">
    <aside class="agent-files" aria-label="Agent bundle 文件"><div class="agent-files-head">Bundle 文件</div>${list}</aside>
    <div class="agent-main"><div class="filebar"><span class="filename">${esc(current?.path || "SKILL.md")}</span><span class="badge">${local ? "本地版本" : "默认模板"}</span></div>
    <textarea spellcheck="false" id="agent-text" class="agent-editor" aria-label="Agent 文件正文">${esc(text)}</textarea>
    <div class="agent-actions"><button class="danger" data-action="delete-agent" ${selected === "SKILL.md" && agent.local ? "" : "disabled"}>删除本地版本</button>
    <button class="secondary" data-action="discard" ${agentDraft ? "" : "disabled"}>撤销编辑</button>
    <button class="primary" data-action="save-agent">${local ? "保存修订" : "保存为本地版本"}</button></div></div></section>`;
}

function logsView() {
  const items = logRows.map((i, index) => `<tr><td class="meta">${date(i.time)}</td><td class="meta task-id"><button class="link mono" data-action="log-detail" data-index="${index}" title="${esc(i.task_id)}">${esc(i.task_id)}</button></td>
    <td><span class="status ${Object.hasOwn(labels,i.status) ? i.status : ""}">${esc(labels[i.status] || i.status)}</span></td><td class="meta">${esc(i.tool_calls)}</td></tr>`).join("");
  const table = `<div class="table-wrap"><table><thead><tr><th>时间</th><th>任务 ID</th><th>状态</th><th>工具调用</th></tr></thead><tbody>${items}</tbody></table></div>`;
  return `<section class="panel"><div class="filebar"><span class="filename">data/events.jsonl</span><span class="badge">只读</span></div>
    ${logRows.length ? table : empty("terminal","暂无运行日志","CLI、计划或 Dream 完成后，记录会出现在这里。")}
    <div class="panel-foot"><span>已显示 ${logRows.length} 条</span>${logBefore ? '<button class="text-button" data-action="more">加载更早记录</button>' : ""}</div></section>`;
}


function projectPanel() {
  return `<section class="panel"><div class="panel-head"><h2>项目空间</h2><span class="badge">当前实例</span></div>
    <div class="project-card"><code>${esc(workspace.project)}</code><p>这个 Web 绑定当前项目实例。切换项目时，在目标项目目录启动另一个 supervisor：</p>
    <pre class="command">cd /目标项目
aiverywhere</pre><p class="fine">项目本地实例位于目标项目的 <code>.aiverywhere/</code>。一个用户级实例同一时间绑定一个项目；不要在一个 Web 中任意切换到未登记路径。</p></div></section>`;
}

function sessionsView() {
  const rows = (workspace.sessions || []).map(item => `<tr><td><b>${esc(item.name || "未命名")}</b><div class="meta mono">${esc(item.id)}</div></td><td>${item.turns}</td>
    <td>${item.summary ? "已压实" : "原始"}</td><td class="meta">${date(item.updated)}</td>
    <td><button class="link" data-action="session-rename" data-id="${esc(item.id)}" data-name="${esc(item.name || "")}">重命名</button>
    <button class="link" data-action="session-detail" data-id="${esc(item.id)}">查看</button></td></tr>`).join("");
  return `<section class="panel"><div class="panel-head"><h2>会话与任务</h2><small>${(workspace.sessions || []).length} 个 CLI session</small></div>
    <div class="session-explain"><strong>Session 是持久对话，Task 是一次执行。</strong>
      <p>CLI 每轮任务写入 session；Web 对话是当前 supervisor 进程内的临时会话，刷新或重启后不保证恢复。要长期保留和继续，请使用 CLI session。</p></div>
    ${rows ? `<div class="table-wrap"><table><thead><tr><th>Session</th><th>回合</th><th>上下文</th><th>更新</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : empty("spark","还没有 CLI session","运行 aiverywhere chat 并完成一轮对话后，session 会持久化到 data/sessions/。")}
    <div class="panel-foot"><span>恢复：<code>aiverywhere chat --resume &lt;id&gt;</code></span></div></section>${projectPanel()}`;
}

const newSessionId = () => (typeof crypto !== "undefined" && crypto.randomUUID)
  ? crypto.randomUUID()
  : "web-" + Math.random().toString(36).slice(2) + Date.now().toString(36);

let chat = {
  session: newSessionId(), messages: [], running: false, writable: false, exec: false, network: true,
  speed: "normal", nextMessage: "", started: 0, task: null, receipts: [], status: null, timer: null, hadSession: false,
};

const webCommands = [
  ["/help", "查看 Web 命令和快捷键"],
  ["/new", "开始新的 Web 会话"],
  ["/status", "当前 Web session、task 和权限模式"],
  ["/sessions", "查看持久 CLI session，获取恢复命令"],
  ["/logs", "查看运行记录和任务详情"],
  ["/agent", "编辑 Agent bundle 文件"],
  ["/memory", "管理记忆与技能"],
  ["/overview", "返回实例概览"],
  ["/resume", "如何从历史会话继续"],
];
let slashIndex = 0, slashMatches = [], slashPrefix = null;

const chatElapsed = () => Math.max(0, Math.round((Date.now() - (chat.started || Date.now())) / 1000));

function autoGrow(input) {
  if (!input) return;
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
}

function setChatSend() {
  const send = $("#chat-send"), input = $("#chat-input");
  if (send) send.disabled = !input?.value.trim();
}

function chatReceipts(list, detailed = false) {
  if (!list?.length) return "";
  return `<div class="receipts">${list.map(item => {
    const label = [item.tool, item.path].filter(Boolean).join(" · ") || "tool";
    const title = item.error || label;
    return `<span class="receipt ${item.ok === false ? "err" : ""}" title="${esc(title)}">${esc(label)}</span>`;
  }).join("")}</div>`;
}

// Markdown is rendered locally: escape all source text first, then add only
// the tags produced here. Raw HTML and unsafe link protocols are never emitted.
function safeHref(value) {
  const href = String(value || "").trim();
  if (href.startsWith("//")) return "#";
  return /^(https?:\/\/|mailto:|\/|#|\.\.?\/)/i.test(href) ? esc(href) : "#";
}

function inlineMarkdown(text) {
  const codes = [];
  let output = text.replace(/`([^`\n]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`);
    return `\u0000I${codes.length - 1}\u0000`;
  });
  const links = [];
  output = output.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    links.push(`<a href="${safeHref(href)}" target="_blank" rel="noreferrer noopener">` +
      `${inlineMarkdown(label)}</a>`);
    return `\u0000L${links.length - 1}\u0000`;
  });
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  output = output.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  output = output.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
  output = output.replace(/\u0000L(\d+)\u0000/g, (_, index) => links[Number(index)]);
  return output.replace(/\u0000I(\d+)\u0000/g, (_, index) => codes[Number(index)]);
}

function codeBlockHtml(block) {
  const language = block.language ? esc(block.language) : "code";
  return `<div class="code-block"><div class="code-head"><span>${language}</span>` +
    `<button type="button" class="code-copy">复制</button></div>` +
    `<pre><code>${esc(block.body)}</code></pre></div>`;
}

function renderMarkdown(value) {
  const source = String(value ?? "").replace(/\r\n?/g, "\n");
  const fences = [];
  const tokens = source.replace(/```([^\n`]*)\n([\s\S]*?)(?:```|$)/g, (_, language, body) => {
    const name = language.trim().split(/\s+/)[0].replace(/[^\w+#.-]/g, "");
    fences.push({language: name, body: body.replace(/^\n+|\n+$/g, "")});
    return `\u0000F${fences.length - 1}\u0000`;
  });
  const lines = esc(tokens).split("\n");
  const output = [];
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (!paragraph.length) return;
    output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };
  for (const line of lines) {
    const fence = line.match(/^\u0000F(\d+)\u0000$/);
    if (fence) {
      flushParagraph();
      closeList();
      output.push(codeBlockHtml(fences[Number(fence[1])]));
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(heading[1].length, 4);
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      flushParagraph();
      closeList();
      output.push("<hr>");
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const tag = unordered ? "ul" : "ol";
      if (list !== tag) {
        closeList();
        list = tag;
        output.push(`<${tag}>`);
      }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }
    closeList();
    paragraph.push(line);
  }
  flushParagraph();
  closeList();
  return output.join("\n");
}

function richAnswer(value) {
  return renderMarkdown(value);
}

function thinkingHtml(value, key) {
  if (!value) return "";
  return `<details class="reasoning" data-key="${key}">` +
    `<summary>思考过程 <small>模型返回的推理文本</small></summary>` +
    `<div class="reasoning-body">${renderMarkdown(value)}</div></details>`;
}

const activityNames = {tool: "工具", skill: "Skill", mcp: "MCP", worker: "Worker"};
const activityStates = {running: "运行中", ok: "完成", error: "失败", cancelled: "已取消"};

function activityHtml(item, key) {
  const label = item.label || item.name || "调用";
  const kind = activityNames[item.kind] || "工具";
  const state = activityStates[item.status] || item.status || "";
  const duration = Number.isFinite(Number(item.duration)) && item.duration != null
    ? ` · ${Number(item.duration).toFixed(2)}s` : "";
  const input = item.input ? `<pre>${esc(item.input)}</pre>` : "";
  const output = item.output ? `<pre>${esc(item.output)}</pre>` : "";
  const error = item.error ? `<p class="activity-error">${esc(item.error)}</p>` : "";
  return `<details class="activity ${esc(item.status || "")}" data-key="${key}">` +
    `<summary><span class="activity-kind">${kind}</span><b>${esc(label)}</b>` +
    `<span class="activity-state">${esc(state)}${duration}</span></summary>` +
    `<div class="activity-body">${error}${input}${output}</div></details>`;
}

function todosHtml(todos, key) {
  if (!todos?.length) return "";
  const completed = todos.filter(item => item.status === "completed").length;
  const rows = todos.map(item => {
    const mark = item.status === "completed" ? "[x]" : item.status === "in_progress" ? "[>]" : "[ ]";
    return `<li class="${esc(item.status || "pending")}"><span>${mark}</span>${esc(item.text)}</li>`;
  }).join("");
  return `<details class="todo-panel" data-key="${key}" open>` +
    `<summary>任务清单 <small>${completed}/${todos.length} 完成</small></summary>` +
    `<ul>${rows}</ul></details>`;
}

function processHtml(message, index) {
  const activities = Array.isArray(message.activities) ? message.activities : [];
  const todos = Array.isArray(message.todos) ? message.todos : [];
  const thinking = thinkingHtml(message.thinking || "", `${index}-thinking`);
  const rows = activities.map((item, position) =>
    activityHtml(item, `${index}-activity-${position}`)).join("");
  const process = `${thinking}${rows}`;
  const summary = `过程${activities.length ? ` · ${activities.length} 次调用` : ""}${thinking ? " · 思考" : ""}`;
  return `${todosHtml(todos, `${index}-todos`)}` +
    (process ? `<details class="process" data-key="${index}-process"><summary>${summary}</summary>` +
      `<div class="process-body">${process}</div></details>` : "");
}

function chatEmpty() {
  const suggestions = [
    ["读取 README，告诉我项目入口和依据。", "读取 README，告诉我这个项目的入口，并指出依据。"],
    ["检查当前项目最近的改动并总结。", "检查当前项目最近的改动，按风险从高到低总结。"],
    ["运行测试，分析失败原因。", "运行项目测试，分析失败原因并给出最小修复建议。"],
    ["整理一条值得保存的技能。", "从当前项目里找一条可复用做法，整理成带适用条件的技能。"],
  ];
  return `<div class="chat-empty"><div class="chat-orbit"><i class="ico spark"></i></div>
    <h2>从一个可验证的任务开始</h2>
    <p>模型会使用当前实例的工作约定、记忆与工具。默认只读；需要写项目时在右侧开启工作模式。每个任务保留会话上下文，完成后可以在右侧查看工具回执。</p>
    <div class="chat-suggestions">${suggestions.map(([label, prompt]) =>
      `<button class="chat-suggestion" data-action="chat-suggest" data-prompt="${esc(prompt)}">${esc(label)}</button>`).join("")}</div></div>`;
}

function chatThread() {
  if (!chat.messages.length) return chatEmpty();
  return chat.messages.map((message, index) => {
    if (message.role === "system") {
      return `<div class="message system"><div class="bubble">${esc(message.text)}</div></div>`;
    }
    if (message.role === "user") {
      return `<div class="message user"><div class="avatar">你</div><div class="bubble">${esc(message.text)}</div></div>`;
    }
    if (message.pending) {
      const streamed = message.text
        ? `<div class="stream-answer">${richAnswer(message.text)}<span class="stream-cursor"></span></div>`
        : `<div class="thinking"><i></i><i></i><i></i><span>处理中 · ${chatElapsed()}s</span></div>`;
      const question = message.question
        ? `<div class="decision-card"><p>${esc(message.question.question)}</p>` +
          `<div class="decision-actions">${(message.question.options || []).map(option =>
            `<button type="button" data-action="chat-answer" data-answer="${esc(option)}">${esc(option)}</button>`).join("")}</div>` +
          `<small>也可以直接在下方输入你的决定</small></div>`
        : "";
      return `<div class="message assistant"><div class="avatar">AI</div><div class="bubble">
        ${processHtml(message, index)}${question}${streamed}
        <p class="faint">${question ? "等待你的决定" : "本地模型正在选择工具并核实结果"}</p></div></div>`;
    }
    const body = message.error
      ? `<span class="error">${esc(message.error)}</span>`
      : richAnswer(message.text || "（空答复）");
    return `<div class="message assistant"><div class="avatar">AI</div><div class="bubble">${processHtml(message, index)}${body}${chatReceipts(message.receipts)}</div></div>`;
  }).join("");
}

function chatView() {
  const model = workspace.model || {};
  const modelName = model.name || (model.configured ? "自定义执行器" : "未配置");
  const executor = model.executor === "native" ? "原生执行器" : "Messages";
  return `<div class="chat-layout">
    <section class="chat-panel">
      <header class="chat-head">
        <div class="chat-head-main"><span class="live-dot"></span><strong>对话与工作</strong><small>${esc(modelName)} · ${chat.writable ? "工作模式" : "只读"}</small></div>
        <div class="chat-head-actions"><span class="badge ${chat.writable ? "warn" : ""}" id="chat-mode-badge">${chat.writable ? "工作模式" : "只读"}</span>
          <button class="secondary" data-action="chat-new">新会话</button></div>
      </header>
      <div class="chat-stream" id="chat-stream"></div>
      <form class="chat-composer" id="chat-form">
        <div class="slash-menu" id="chat-slash" role="listbox" aria-label="Web 命令" hidden></div>
        <textarea id="chat-input" rows="2" maxlength="32000" placeholder="${chat.running ? "补充当前任务，或回答等待中的决定…" : "输入任务，或输入 / 查看命令…"}" aria-label="任务内容" autocomplete="off"></textarea>
        <div class="chat-composer-foot"><span>Enter 发送 · Shift+Enter 换行 · 输入 / 查看命令</span>
          <button class="send" id="chat-send" type="submit" aria-label="发送任务">↑</button></div>
      </form>
    </section>
    <aside class="chat-side">
      <section class="panel">
        <p class="eyebrow">SESSION</p>
        <div class="meta-row"><span>模型</span><b>${esc(modelName)}</b></div>
        <div class="meta-row"><span>执行</span><b>${esc(executor)}</b></div>
        <div class="meta-row"><span>Agent</span><b class="mono">${esc(workspace.agent.revision.slice(0, 8))}</b></div>
        <div class="meta-row"><span>模式</span><b id="chat-mode-label">${chat.writable ? "可写项目" : "只读"}${chat.exec ? " · 可执行" : ""}${chat.network ? "" : " · 无网络"}</b></div>
        <div class="meta-row"><span>会话</span><b class="mono" id="chat-session">${esc(chat.session.slice(0, 8))}</b></div>
      </section>
      <section class="panel">
        <p class="eyebrow">WORK MODE</p>
        <label class="switch-row"><span><b>允许修改项目文件</b><small>仅当前浏览器会话</small></span>
          <input type="checkbox" id="chat-writable" ${chat.writable ? "checked" : ""} aria-label="允许修改项目文件"></label>
        <label class="switch-row"><span><b>允许执行项目命令</b><small>仅当前浏览器会话</small></span>
          <input type="checkbox" id="chat-exec" ${chat.exec ? "checked" : ""} aria-label="允许执行项目命令"></label>
        <label class="switch-row"><span><b>允许联网搜索/抓取</b><small>仅当前浏览器会话</small></span>
          <input type="checkbox" id="chat-network" ${chat.network ? "checked" : ""} aria-label="允许联网"></label>
        <label class="switch-row"><span><b>流式速度</b><small>只影响文字显示，不改变模型</small></span>
          <select id="chat-speed" class="speed-select" aria-label="流式速度">
            <option value="slow" ${chat.speed === "slow" ? "selected" : ""}>慢</option>
            <option value="normal" ${chat.speed === "normal" ? "selected" : ""}>标准</option>
            <option value="fast" ${chat.speed === "fast" ? "selected" : ""}>快</option>
          </select></label>
        <p class="faint">关闭时只读。开启后模型可以写入项目或执行命令；切换模式会开始新的上下文。</p>
      </section>
      <section class="panel">
        <p class="eyebrow">LAST RECEIPTS</p>
        <div id="chat-receipts"><span class="faint">尚无工具调用</span></div>
      </section>
    </aside>
  </div>`;
}

function paintChat() {
  const stream = $("#chat-stream");
  if (!stream) return;
  const stick = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 90;
  // Re-rendering for streaming must not collapse a panel the user just opened.
  const details = new Map([...stream.querySelectorAll("details[data-key]")].map(item =>
    [item.dataset.key, item.open]));
  stream.innerHTML = chatThread();
  stream.querySelectorAll("details[data-key]").forEach(item => {
    if (details.has(item.dataset.key)) item.open = details.get(item.dataset.key);
  });
  const receipts = $("#chat-receipts");
  if (receipts) receipts.innerHTML = chat.receipts.length
    ? chat.receipts.map(item => `<span class="receipt ${item.ok === false ? "err" : ""}" title="${esc(item.error || item.tool || "tool")}">${esc([item.tool, item.path].filter(Boolean).join(" · ") || "tool")}</span>`).join("")
    : '<span class="faint">尚无工具调用</span>';
  const mode = $("#chat-mode-label");
  if (mode) mode.textContent = (chat.writable ? "可写项目" : "只读") + (chat.exec ? " · 可执行" : "") + (chat.network ? "" : " · 无网络");
  const badge = $("#chat-mode-badge");
  if (badge) { badge.textContent = chat.writable ? "工作模式" : "只读"; badge.classList.toggle("warn", chat.writable); }
  const input = $("#chat-input");
  if (input) input.placeholder = chat.running
    ? "补充当前任务，或回答等待中的决定…" : "输入任务，或输入 / 查看命令…";
  setChatSend();
  autoGrow(input);
  if (stick) stream.scrollTop = stream.scrollHeight;
}

const STREAM_SPEEDS = {
  slow: {tick: 80, base: 1, max: 1},
  normal: {tick: 45, base: 1, max: 2},
  fast: {tick: 30, base: 2, max: 6},
};

// Polling may deliver a large delta at once. Drain it through a small
// typewriter buffer so the text remains readable without changing the model.
function pumpStream(message) {
  if (message.streamTimer) return;
  const speed = STREAM_SPEEDS[chat.speed] || STREAM_SPEEDS.normal;
  message.streamTarget = message.streamTarget || message.text || "";
  message.streamTimer = setInterval(() => {
    const target = message.streamTarget || "";
    if (message.text.length < target.length) {
      const backlog = target.length - message.text.length;
      const take = Math.min(speed.max, Math.max(speed.base, Math.ceil(backlog / 80)));
      message.text = target.slice(0, message.text.length + take);
      paintChat();
      return;
    }
    if (message.streamDone) {
      message.streamDone = false;
      message.pending = false;
      clearInterval(message.streamTimer);
      message.streamTimer = null;
      paintChat();
      if (chat.nextMessage) {
        const next = chat.nextMessage;
        chat.nextMessage = "";
        const input = $("#chat-input");
        if (input) {
          input.value = next;
          sendChat();
        }
      }
    }
  }, speed.tick);
}

function stopStream(message) {
  if (message?.streamTimer) clearInterval(message.streamTimer);
  if (message) message.streamTimer = null;
}

async function pollChat() {
  if (!chat.running) return;
  const session = chat.session;
  try {
    const state = await api("/api/chat?session=" + encodeURIComponent(session));
    if (session !== chat.session) return;
    chat.status = state;
    const assistant = chat.messages[chat.messages.length - 1];
    if (assistant?.role === "assistant" && assistant.pending) {
      assistant.thinking = state.thinking || assistant.thinking || "";
      assistant.activities = Array.isArray(state.activities) ? state.activities : assistant.activities;
      assistant.todos = Array.isArray(state.todos) ? state.todos : assistant.todos;
      assistant.question = state.question || null;
      if (state.status === "running") {
        assistant.streamTarget = state.stream_text || assistant.streamTarget || "";
        assistant.streamDone = false;
        pumpStream(assistant);
      } else {
        assistant.error = state.error || (state.status === "idle" ? "会话状态已重置，请开始新会话。" : "");
        assistant.receipts = Array.isArray(state.receipts) ? state.receipts : [];
        const answer = state.answer || "";
        if (answer) {
          if (assistant.text && !answer.startsWith(assistant.text)) assistant.text = "";
          assistant.streamTarget = answer;
          assistant.streamDone = true;
          pumpStream(assistant);
        } else {
          stopStream(assistant);
          assistant.pending = false;
        }
      }
    }
    if (state.status !== "running") {
      chat.receipts = Array.isArray(state.receipts) ? state.receipts : [];
      chat.running = false;
      paintChat();
      if (assistant?.error) toast(assistant.error, true);
      return;
    }
    paintChat();
    chat.timer = setTimeout(pollChat, 250);
  } catch (error) {
    const assistant = chat.messages[chat.messages.length - 1];
    if (assistant?.role === "assistant") {
      stopStream(assistant);
      assistant.pending = false;
      assistant.error = error.message;
    }
    chat.running = false;
    paintChat();
    toast(error.message, true);
  }
}

function hideSlash() {
  slashPrefix = null;
  slashMatches = [];
  const menu = $("#chat-slash");
  if (menu) menu.hidden = true;
}

function paintSlash() {
  const menu = $("#chat-slash"), input = $("#chat-input");
  if (!menu || !input) return;
  const value = input.value;
  if (!value.startsWith("/") || value.startsWith("//") || value.includes(" ") || value.includes("\n")) {
    hideSlash();
    return;
  }
  if (value !== slashPrefix) slashIndex = 0;
  slashPrefix = value;
  slashMatches = webCommands.filter(([command]) => command.startsWith(value));
  if (!slashMatches.length) { hideSlash(); return; }
  slashIndex = Math.min(slashIndex, slashMatches.length - 1);
  menu.innerHTML = `<div class="slash-menu-head">Web 命令 <small>↑↓ 选择 · Tab/Enter 执行 · Esc 关闭</small></div>` +
    slashMatches.map(([command, detail], index) => `<button type="button" class="slash-item ${index === slashIndex ? "active" : ""}"
      role="option" aria-selected="${index === slashIndex}" data-command="${esc(command)}"><b>${esc(command)}</b><span>${esc(detail)}</span></button>`).join("");
  menu.hidden = false;
}

function systemMessage(text) {
  chat.messages.push({role: "system", text});
  paintChat();
}

async function runWebCommand(raw) {
  const command = raw.trim().split(/\s+/, 1)[0];
  hideSlash();
  if (command === "/help") {
    systemMessage("Web 命令：\n" + webCommands.map(([name, detail]) => `${name}  ${detail}`).join("\n") +
      "\n\n键盘：/ 打开菜单，↑↓ 选择，Tab 或 Enter 执行，Esc 关闭。");
    return;
  }
  if (command === "/new") { await resetChat(); return; }
  if (command === "/status") {
    systemMessage(`Web session: ${chat.session}\n` +
      `task: ${chat.task || "—"}\n` +
      `状态: ${chat.running ? "运行中" : "空闲"}\n` +
      `模式: ${chat.writable ? "可写" : "只读"} / ${chat.exec ? "可执行" : "只读命令"} / ${chat.network ? "联网" : "无网络"}\n` +
      "说明：Web 对话是 supervisor 进程内上下文；持久历史请用 /sessions。");
    return;
  }
  if (command === "/sessions" || command === "/logs" || command === "/agent" || command === "/memory" || command === "/overview") {
    location.hash = command.slice(1);
    return;
  }
  if (command === "/resume") {
    systemMessage("Web 不能直接续写 CLI session。打开“会话与任务”查看 session，复制恢复命令：\n" +
      "aiverywhere chat --resume <session-id>\n" +
      "或在终端输入 aiverywhere，再用 /sessions 和 /resume。");
    return;
  }
  systemMessage(`未知命令：${command}\n输入 /help 查看 Web 命令。`);
}

// While a task is running, plain input supplements the current task; /next
// queues a separate task for after the current one finishes.
async function sendRunningInput(text) {
  const result = await api("/api/chat/input", "POST", {session: chat.session, text});
  toast(result.outcome === "answer" ? "决定已提交" : "已收到，将并入当前任务");
  return result;
}

async function sendChat() {
  const input = $("#chat-input");
  let message = input?.value.trim();
  if (!message) return;
  if (message.startsWith("/") && !message.startsWith("//")) {
    input.value = "";
    hideSlash();
    await runWebCommand(message);
    return;
  }
  if (chat.running && message.startsWith("/next ")) {
    chat.nextMessage = message.slice(6).trim();
    input.value = "";
    setChatSend();
    toast(chat.nextMessage ? "已排入下一任务" : "下一任务为空");
    return;
  }
  if (chat.running) {
    try {
      const result = await api("/api/chat/input", "POST", {session: chat.session, text: message});
      input.value = "";
      setChatSend();
      toast(result.outcome === "answer" ? "决定已提交" : "已收到，将并入当前任务");
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  if (message.startsWith("//")) message = message.slice(1);
  input.value = "";
  hideSlash();
  chat.messages.push({role: "user", text: message});
  chat.messages.push({role: "assistant", pending: true, text: "", thinking: "",
    activities: [], todos: [], question: null, streamTarget: "", streamDone: false, streamTimer: null,
    error: "", receipts: []});
  chat.running = true;
  chat.started = Date.now();
  chat.receipts = [];
  chat.status = {status: "running"};
  paintChat();
  try {
    const started = await api("/api/chat", "POST", {session: chat.session, message, writable: chat.writable, exec: chat.exec, network: chat.network});
    if (started.new_session && chat.hadSession) {
      chat.messages.splice(chat.messages.length - 2, 0,
        {role: "system", text: "服务端会话已重置；模型上下文从本条消息开始。"});
    }
    chat.hadSession = true;
    chat.task = started.task_id;
    if (started.started) chat.started = started.started * 1000;
    paintChat();
    pollChat();
  } catch (error) {
    const assistant = chat.messages[chat.messages.length - 1];
    if (assistant?.role === "assistant") {
      assistant.pending = false;
      assistant.error = error.message;
    }
    chat.running = false;
    paintChat();
    toast(error.message, true);
  }
}

async function resetChat() {
  if (chat.running) {
    toast("当前任务仍在处理，完成后再开始新会话。", true);
    return false;
  }
  chat.messages.forEach(stopStream);
  const previous = chat.session;
  try {
    await api("/api/chat/reset", "POST", {session: previous});
  } catch (error) {
    toast(error.message, true);
    return false;
  }
  chat = {
    ...chat, session: newSessionId(), messages: [], running: false, started: 0,
    nextMessage: "", task: null, receipts: [], status: null, timer: null, hadSession: false,
  };
  if (page === "chat") render(); else paintChat();
  return true;
}

async function setChatNetwork(value) {
  if (chat.running) {
    toast("当前任务仍在处理，完成后再切换模式。", true);
    if (page === "chat") render();
    return;
  }
  if (value === chat.network) return;
  if (chat.messages.length) {
    if (!confirm("切换网络模式会开始新会话并清空当前上下文，继续吗？")) {
      if (page === "chat") render();
      return;
    }
    if (!(await resetChat())) return;
  }
  chat.network = value;
  if (page === "chat") render();
}

async function setChatExec(value) {
  if (chat.running) {
    toast("当前任务仍在处理，完成后再切换模式。", true);
    if (page === "chat") render();
    return;
  }
  if (value === chat.exec) return;
  if (chat.messages.length) {
    if (!confirm("切换执行模式会开始新会话并清空当前上下文，继续吗？")) {
      if (page === "chat") render();
      return;
    }
    if (!(await resetChat())) return;
  }
  chat.exec = value;
  if (page === "chat") render();
}

async function setChatWritable(value) {
  if (chat.running) {
    toast("当前任务仍在处理，完成后再切换模式。", true);
    if (page === "chat") render();
    return;
  }
  if (value === chat.writable) return;
  if (chat.messages.length) {
    if (!confirm("切换工作模式会开始新会话并清空当前上下文，继续吗？")) {
      if (page === "chat") render();
      return;
    }
    if (!(await resetChat())) return;
  }
  chat.writable = value;
  if (page === "chat") render();
}

function render() {
  if (!workspace) return;
  const hash = location.hash.slice(1);
  page = Object.hasOwn(titles, hash) ? hash : "overview";
  document.title = titles[page] + " · aiverywhere";
  $("#title").textContent = $("#crumb").textContent = titles[page];
  $("#subtitle").textContent = page === "overview" ? workspace.project : workspace.directory;
  $("#create").hidden = !["overview","memory"].includes(page);
  document.querySelectorAll("[data-page]").forEach(link => {
    const current = link.dataset.page === page;
    link.classList.toggle("active", current);
    if (current) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  $("#view").innerHTML = {chat:chatView, overview, memory:memoryView, agent:agentView, sessions:sessionsView, logs:logsView}[page]();
  $("#view").setAttribute("aria-busy", "false");
  if (page === "chat") paintChat();
  if (page === "memory") filterMemory();
}

async function reload() {
  const number = ++refreshNumber;
  try {
    const headers = {"X-Aiverywhere-Token": token};
    if (workspaceTag) headers["If-None-Match"] = workspaceTag;
    const response = await fetch("/api/workspace", {headers});
    if (number !== refreshNumber) return;
    if (!response.ok && response.status !== 304) throw new Error((await response.json()).error || "读取失败");
    $("#connection").textContent = "已连接";
    $("#connection").classList.add("online");
    if (response.status === 304) return;
    const updated = await response.json();
    if (number !== refreshNumber) return;
    const previous = workspace;
    workspace = updated;
    workspaceTag = response.headers.get("ETag");
    logRows = [...workspace.logs.rows];
    logBefore = workspace.logs.before;
    if (page === "chat") return;
    if (page === "agent" && agentDraft) {
      if (previous?.agent.revision !== updated.agent.revision) {
        toast("Agent 文件已有新修订。草稿已保留，撤销编辑可查看现行版本。", true);
      }
      return;
    }
    const searchFocused = document.activeElement?.id === "search";
    const cursor = searchFocused ? $("#search").selectionStart : 0;
    render();
    if (searchFocused) {
      $("#search").focus();
      $("#search").setSelectionRange(cursor, cursor);
    }
  } catch (err) {
    if (number !== refreshNumber) return;
    $("#connection").textContent = "连接异常";
    $("#connection").classList.remove("online");
    if (!workspace) $("#view").textContent = "读取失败，点击右上角刷新重试。";
    throw err;
  }
}

function openEditor(item = null) {
  editing = item;
  $("#editor-title").textContent = item ? "编辑条目" : "新建条目";
  $("#entry-title").value = item?.title ?? "";
  $("#entry-text").value = item?.text ?? "";
  $("#entry-kind").value = item?.kind ?? (filter === "skill" ? "skill" : "fact");
  $("#entry-kind").disabled = Boolean(item);
  $("#delete-entry").hidden = !item;
  $("#entry-error").textContent = "";
  $("#editor").showModal();
  $("#entry-title").focus();
}

function confirmDelete(text) {
  const box = $("#confirm");
  $("#confirm-info").textContent = text;
  box.returnValue = "";
  box.showModal();
  return new Promise(resolve => box.addEventListener("close", () => resolve(box.returnValue === "delete"), {once:true}));
}

async function action(name, button) {
  switch (name) {
    case "edit":
      openEditor(await api("/api/memory/" + button.dataset.id));
      break;
    case "chat-new":
      await resetChat();
      break;
    case "chat-suggest": {
      const input = $("#chat-input");
      if (input) {
        input.value = button.dataset.prompt || "";
        input.focus();
        setChatSend();
        autoGrow(input);
      }
      break;
    }
    case "agent-file": {
      const path = button.dataset.path;
      const content = await api("/api/agent/file?path=" + encodeURIComponent(path));
      agentSelected = path;
      agentDraft = {path, text:content.text, revision:content.revision};
      render();
      break;
    }
    case "discard":
      agentDraft = null;
      agentSelected = "SKILL.md";
      render();
      break;
    case "save-agent": {
      const path = agentDraft?.path || agentSelected;
      const revision = agentDraft?.revision || (path === "SKILL.md" ? workspace.agent.revision :
        (workspace.agent.files || []).find(item => item.path === path)?.revision);
      await api("/api/agent/file", "PUT", {path, revision, text:$("#agent-text").value});
      agentDraft = null;
      agentSelected = "SKILL.md";
      await reload();
      toast("Agent 文件已保存");
      break;
    }
    case "delete-agent":
      if (agentSelected !== "SKILL.md" || !await confirmDelete("删除活动的 SKILL.md？新任务将使用项目模板。")) return;
      await api("/api/agent", "DELETE", {revision:workspace.agent.revision});
      agentDraft = null;
      agentSelected = "SKILL.md";
      await reload();
      toast("本地版本已删除");
      break;
    case "log-detail": {
      const row = logRows[Number(button.dataset.index)];
      if (!row) return;
      const runId = row.run_id || row.task_id;
      let detail = null;
      try { detail = await api("/api/runs/" + encodeURIComponent(runId)); }
      catch (error) { detail = null; }
      $("#detail-title").textContent = "运行记录";
      if (!detail) {
        $("#detail-body").textContent = JSON.stringify(row, null, 2) +
          "\n\n（旧任务只有摘要，没有详细 trace。新任务会记录提示词、工具输入/输出和答复。）";
      } else {
        const tools = (detail.trace || []).map((item, index) => {
          const input = typeof item.input === "string" ? item.input : JSON.stringify(item.input ?? {}, null, 2);
          const output = item.output || item.error || "";
          return `#${index + 1} ${item.tool} ${item.ok === false ? "失败" : "成功"}\n参数：\n${input}\n结果：\n${output}`;
        }).join("\n\n");
        $("#detail-body").textContent = [
          `task:   ${detail.task_id}`,
          `run:    ${detail.run_id}`,
          `status: ${detail.status}`,
          `entry:  ${detail.entry || "—"}`,
          `time:   ${date(detail.time)}`,
          `duration: ${detail.started && detail.finished ? Math.max(0, detail.finished - detail.started).toFixed(2) + "s" : "—"}`,
          "", "## Prompt", detail.prompt || "（无）",
          "", "## Answer", detail.answer || "（无）",
          detail.error ? `\n## Error\n${detail.error}` : "",
          "", "## Tools", tools || "（没有工具调用）"
        ].join("\n");
      }
      $("#detail").showModal();
      break;
    }
    case "session-rename": {
      const name = prompt("新的 session 名称（1–80 个字符）", button.dataset.name || "");
      if (name === null) break;
      try {
        await api("/api/sessions/" + button.dataset.id + "/rename", "POST", {name});
        await reload();
        toast("session 已重命名");
      } catch (error) { toast(error.message, true); }
      break;
    }
    case "session-detail": {
      const data = await api("/api/sessions/" + button.dataset.id);
      $("#detail-title").textContent = (data.name || "未命名") + " · " + data.id.slice(0, 12);
      const transcript = (data.history || []).map(message => {
        const role = message.role || "message";
        const content = typeof message.content === "string" ? message.content : JSON.stringify(message.content);
        return `[${role}]\n${content}`;
      }).join("\n\n");
      $("#detail-body").textContent = `恢复命令：\naiverywhere chat --resume ${data.id}\n\n${transcript || "（暂无对话记录）"}`;
      $("#detail").showModal();
      break;
    }
    case "more": {
      button.disabled = true;
      try {
        const older = await api("/api/logs?before=" + logBefore);
        logRows.push(...older.rows);
        logBefore = older.before;
        render();
      } finally { button.disabled = false; }
      break;
    }
  }
}

$("#address").textContent = location.host;
$("#create").onclick = () => { if (workspace) openEditor(); };
$("#refresh").onclick = () => reload().catch(e => toast(e.message, true));
$("#confirm-no").onclick = () => $("#confirm").close();
$("#confirm-yes").onclick = () => $("#confirm").close("delete");
document.querySelectorAll("#editor .close, #detail .close").forEach(button => button.onclick = () => button.closest("dialog").close());
$("#entry-form").onsubmit = async event => {
  event.preventDefault();
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    const fields = {title:$("#entry-title").value, text:$("#entry-text").value, kind:$("#entry-kind").value};
    if (editing) fields.revision = editing.revision;
    await api(editing ? "/api/memory/" + editing.id : "/api/memory", editing ? "PUT" : "POST", fields);
    $("#editor").close();
    await reload();
    toast("条目已保存");
  } catch (err) { $("#entry-error").textContent = err.message; }
  finally { if (button) button.disabled = false; }
};
$("#delete-entry").onclick = async () => {
  if (!editing || !await confirmDelete("删除“" + editing.title + "”？该条目将从项目记忆中移除。")) return;
  try {
    await api("/api/memory/" + editing.id, "DELETE", {revision:editing.revision});
    $("#editor").close();
    await reload();
    toast("条目已删除");
  } catch (err) { $("#entry-error").textContent = err.message; }
};
$("#view").addEventListener("input", event => {
  if (event.target.id === "search") { query = event.target.value; filterMemory(); }
  if (event.target.id === "agent-text") {
    const path = agentDraft?.path || agentSelected;
    const revision = agentDraft?.revision || (path === "SKILL.md" ? workspace.agent.revision :
      (workspace.agent.files || []).find(item => item.path === path)?.revision);
    agentDraft = {path, text:event.target.value, revision};
    $('[data-action="discard"]').disabled = false;
  }
  if (event.target.id === "chat-input") { setChatSend(); autoGrow(event.target); paintSlash(); }
});
$("#view").addEventListener("change", event => {
  if (event.target.id === "chat-writable") setChatWritable(event.target.checked).catch(e => toast(e.message, true));
  if (event.target.id === "chat-exec") setChatExec(event.target.checked).catch(e => toast(e.message, true));
  if (event.target.id === "chat-network") setChatNetwork(event.target.checked).catch(e => toast(e.message, true));
  if (event.target.id === "chat-speed") {
    chat.speed = event.target.value;
    for (const message of chat.messages) {
      if (message.streamTimer) {
        clearInterval(message.streamTimer);
        message.streamTimer = null;
        pumpStream(message);
      }
    }
  }
});
$("#view").addEventListener("submit", event => {
  if (event.target.id === "chat-form") { event.preventDefault(); sendChat(); }
});
document.addEventListener("keydown", event => {
  if (event.target.id !== "chat-input") return;
  const menu = $("#chat-slash");
  const open = menu && !menu.hidden;
  if (open && ["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    slashIndex = (slashIndex + (event.key === "ArrowDown" ? 1 : -1) + slashMatches.length) % slashMatches.length;
    paintSlash();
    return;
  }
  if (open && ["Tab", "Enter"].includes(event.key) && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    const command = slashMatches[slashIndex]?.[0];
    if (command) {
      $("#chat-input").value = command;
      sendChat();
    }
    return;
  }
  if (open && event.key === "Escape") { event.preventDefault(); hideSlash(); return; }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendChat();
  }
});
$("#view").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.action === "chat-answer") {
    sendRunningInput(button.dataset.answer).catch(error => toast(error.message, true));
    return;
  }
  if (button.classList.contains("code-copy")) {
    const code = button.closest(".code-block")?.querySelector("code");
    if (code && navigator.clipboard) {
      navigator.clipboard.writeText(code.innerText).then(() => toast("代码已复制")).catch(() => toast("复制失败", true));
    }
    return;
  }
  if (button.dataset.command) {
    $("#chat-input").value = button.dataset.command;
    sendChat();
    return;
  }
  if (button.dataset.filter) { filter = button.dataset.filter; render(); }
  if (button.dataset.action) action(button.dataset.action, button).catch(e => toast(e.message, true));
});
window.addEventListener("hashchange", render);
function syncVisible() {
  if (!document.hidden) reload().catch(() => {});
}
document.addEventListener("visibilitychange", syncVisible);
window.setInterval(syncVisible, 3000);
reload().catch(e => toast(e.message, true));
