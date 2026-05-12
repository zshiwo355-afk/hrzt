window.HRApp = window.HRApp || {};

let messagesRenderSeq = 0;
const INITIAL_RENDER_BATCH_SIZE = 8;
const NEXT_RENDER_BATCH_SIZE = 6;

function tuneHistoryImage(img) {
      if (!img) return img;
      img.loading = "lazy";
      img.decoding = "async";
      return img;
    }

function ensureMessageSourcesExpanded(msg) {
      if (!msg || typeof msg !== "object") return false;
      if (typeof msg.sourcesExpanded !== "boolean") {
        msg.sourcesExpanded = false;
      }
      return msg.sourcesExpanded;
    }

    function renderMessageSourcesHtml(sources) {
      const rows = Array.isArray(sources) ? sources.filter(Boolean) : [];
      if (!rows.length) return "";
      const items = rows.map((src) => {
        const sourceType = String(src.source_type || "").trim().toLowerCase();
        const isWeb = sourceType === "web";
        const title = escapeHtml(src.title || (isWeb ? "网页来源" : "知识库来源"));
        const snippet = escapeHtml(src.snippet || "");
        const webMeta = src.meta_label
          ? [src.meta_label]
          : [src.domain, src.published_at].filter(Boolean);
        const ragMeta = [src.page_label, ...(src.pdf_report_titles || [])].filter(Boolean);
        const meta = escapeHtml((isWeb ? webMeta : ragMeta).join(" · "));
        const links = [];

        if (isWeb) {
          const sourceUrl = src.url ? String(src.url) : "";
          if (sourceUrl) {
            links.push(
              `<a class="message-source-link message-source-link--primary" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">打开来源</a>`
            );
          }
        } else {
          const imageUrl = src.best_image_url ? String(src.best_image_url) : "";
          const bestPdfUrl = src.best_pdf_url ? String(src.best_pdf_url) : "";
          const pdfReports = Array.isArray(src.pdf_reports) ? src.pdf_reports.filter(Boolean) : [];
          const seenPdfUrls = new Set();
          if (bestPdfUrl) {
            seenPdfUrls.add(bestPdfUrl);
            links.push(
              `<a class="message-source-link message-source-link--primary" href="${escapeHtml(bestPdfUrl)}" target="_blank" rel="noreferrer">查看质检报告</a>`
            );
          }
          pdfReports.forEach((report, idx) => {
            const pdfUrl = report && report.pdf_url ? String(report.pdf_url) : "";
            if (!pdfUrl || seenPdfUrls.has(pdfUrl)) return;
            seenPdfUrls.add(pdfUrl);
            const reportTitle =
              report.supplement_title ||
              report.source_file ||
              `报告 ${idx + 1}`;
            links.push(
              `<a class="message-source-link" href="${escapeHtml(pdfUrl)}" target="_blank" rel="noreferrer">${escapeHtml(reportTitle)}</a>`
            );
          });
          if (imageUrl) {
            links.push(
              `<a class="message-source-image" href="${escapeHtml(imageUrl)}" target="_blank" rel="noreferrer">查看配图</a>`
            );
          }
        }
        return `
          <div class="message-source-item">
            <div class="message-source-name">${title}</div>
            ${meta ? `<div class="message-source-meta">${meta}</div>` : ""}
            ${snippet ? `<div class="message-source-snippet">${snippet}</div>` : ""}
            ${links.length ? `<div class="message-source-links">${links.join("")}</div>` : ""}
          </div>
        `;
      }).join("");
      return `
        <div class="message-sources">
          <div class="message-sources-title">来源</div>
          ${items}
        </div>
      `;
    }

    function syncMessageSourcesSection(bubble, msg) {
      if (!bubble || !msg) return;
      let wrap = bubble.querySelector(".message-sources-wrap");
      if (wrap) wrap.remove();

      const rows = Array.isArray(msg.sources) ? msg.sources.filter(Boolean) : [];
      if (!rows.length) return;

      const expanded = ensureMessageSourcesExpanded(msg);
      wrap = document.createElement("div");
      wrap.className = "message-sources-wrap";

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "message-sources-toggle";
      toggle.innerHTML = `
        <span>来源（${rows.length}）</span>
        <span class="message-sources-toggle-caret">${expanded ? "▾" : "▸"}</span>
      `;
      toggle.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        msg.sourcesExpanded = !ensureMessageSourcesExpanded(msg);
        const row = bubble.closest(".msg-row");
        const chatId = row && row.getAttribute("data-chat-id");
        persistMessageUiState(chatId, msg);
        syncMessageSourcesSection(bubble, msg);
      };
      wrap.appendChild(toggle);

      if (expanded) {
        const detailWrap = document.createElement("div");
        detailWrap.innerHTML = renderMessageSourcesHtml(rows);
        if (detailWrap.firstElementChild) {
          wrap.appendChild(detailWrap.firstElementChild);
        }
      }

      const anchor = bubble.querySelector(".msg-actions");
      if (anchor) bubble.insertBefore(wrap, anchor);
      else bubble.appendChild(wrap);
    }

    function ragStatusNote(status, fallbackNote) {
      if (status === "empty") return "未检索到相关知识库内容";
      if (status === "timeout") return "知识库连接超时，请稍后重试";
      if (status === "error") return "知识库服务暂不可用";
      return fallbackNote || "";
    }

function _escapeMsgIdForSelector(id) {
      if (typeof id !== "string") return "";
      return typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(id) : id.replace(/"/g, '\\"');
    }

function imageTaskPhaseTitle(msg) {
      const st = msg.taskStatus;
      const taskKind = String(msg.taskKind || "").trim().toLowerCase();
      const artifactType = String(msg.artifactType || "").trim().toLowerCase();
      if (taskKind === "artifact") {
        if (st === "queued") return "任务排队中";
        if (artifactType === "pptx") return "正在生成 PPT 演示文稿";
        if (artifactType === "xlsx") return "正在生成 Excel 文件";
        if (artifactType === "pdf") return "正在生成 PDF 文档";
        if (artifactType === "txt") return "正在生成 TXT 文本文件";
        if (artifactType === "md") return "正在生成 Markdown 文件";
        if (artifactType === "csv") return "正在生成 CSV 文件";
        return "正在生成 Word 文档";
      }
      if (st === "queued") return "任务排队中";
      if (st === "running") return "正在生成图片";
      const t = (msg.text || "").trim();
      if (t.includes("提交") || t.includes("排队") || t.includes("后台")) return "正在提交任务";
    return "正在生成图片";
    }

    function fillTextWaitFromMsg(waitEl, msg) {
      if (!waitEl) return;
      const titleEl = waitEl.querySelector(".text-wait-title");
      if (titleEl) {
        const raw = (msg && msg.text ? String(msg.text) : "").trim();
        const steps = Array.isArray(msg && msg.progressSteps) ? msg.progressSteps : [];
        const lastStep = steps.length ? steps[steps.length - 1] : null;
        titleEl.textContent = (lastStep && lastStep.text) || raw || "处理中...";
      }
      syncMessageProgressSection(waitEl, msg, { insideWait: true });
    }

    function buildTextWaitElement(msg) {
      const wrap = document.createElement("div");
      wrap.className = "text-wait";
      wrap.setAttribute("aria-live", "polite");
      const titleEl = document.createElement("div");
      titleEl.className = "text-wait-title";
      const dots = document.createElement("div");
      dots.className = "text-wait-dots";
      dots.setAttribute("aria-hidden", "true");
      [0, 1, 2].forEach(() => dots.appendChild(document.createElement("span")));
      wrap.appendChild(titleEl);
      wrap.appendChild(dots);
      fillTextWaitFromMsg(wrap, msg);
      return wrap;
    }

    function fillImageTaskWaitFromMsg(waitEl, msg) {
      if (!waitEl) return;
      const titleEl = waitEl.querySelector(".image-task-wait-title");
      const subEl = waitEl.querySelector(".image-task-wait-sub");
      if (titleEl) titleEl.textContent = imageTaskPhaseTitle(msg);
      if (subEl) subEl.textContent = (msg.text && String(msg.text).trim()) || " ";
    }

    function buildImageTaskWaitElement(msg) {
      const wrap = document.createElement("div");
      wrap.className = "image-task-wait";
      wrap.setAttribute("aria-live", "polite");
      const titleEl = document.createElement("div");
      titleEl.className = "image-task-wait-title";
      const dots = document.createElement("div");
      dots.className = "image-task-wait-dots";
      dots.setAttribute("aria-hidden", "true");
      [0, 1, 2].forEach(() => dots.appendChild(document.createElement("span")));
      const subEl = document.createElement("div");
      subEl.className = "image-task-wait-sub";
      wrap.appendChild(titleEl);
      wrap.appendChild(dots);
      wrap.appendChild(subEl);
      fillImageTaskWaitFromMsg(wrap, msg);
      return wrap;
    }

    function normalizeProgressKind(kind) {
      const raw = String(kind || "").trim().toLowerCase();
      if (raw === "search") return "检索";
      if (raw === "reasoning") return "分析";
      if (raw === "status") return "状态";
      return "过程";
    }

    function progressStepText(step) {
      if (!step || typeof step !== "object") return "";
      return String(step.text || "").trim();
    }

    function foldProcessNarrationForRender(msg) {
      if (!msg || msg.role !== "assistant" || msg.pending || msg.error) return msg;
      const helper = window.HRApp && window.HRApp.processNarration && window.HRApp.processNarration.separateLeadingProcessNarration;
      if (typeof helper !== "function") return msg;
      const original = String(msg.text || "");
      if (!original.trim()) return msg;
      const separated = helper(original);
      if (!separated || !Array.isArray(separated.steps) || !separated.steps.length) return msg;
      msg.text = String(separated.content || "").trim() || original;
      if (!Array.isArray(msg.progressSteps)) msg.progressSteps = [];
      separated.steps.forEach((step) => {
        const text = progressStepText(step);
        if (!text) return;
        const prev = msg.progressSteps[msg.progressSteps.length - 1];
        if (prev && prev.kind === "reasoning" && prev.text === text) return;
        msg.progressSteps.push({ kind: "reasoning", text, at: Date.now() });
      });
      return msg;
    }

    function syncMessageProgressSection(container, msg, options) {
      if (!container || !msg) return;
      const steps = (Array.isArray(msg.progressSteps) ? msg.progressSteps : [])
        .filter((step) => progressStepText(step));
      let panel = container.querySelector(".message-progress");
      if (!steps.length) {
        if (panel) panel.remove();
        return;
      }
      if (!panel) {
        panel = document.createElement("details");
        panel.className = "message-progress";
        panel.open = !!msg.pending;
        const summary = document.createElement("summary");
        summary.className = "message-progress-title";
        const title = document.createElement("span");
        title.className = "message-progress-title-text";
        summary.appendChild(title);
        panel.appendChild(summary);
        const list = document.createElement("div");
        list.className = "message-progress-list";
        panel.appendChild(list);
        const anchor = container.querySelector(".msg-actions");
        if (anchor) container.insertBefore(panel, anchor);
        else container.appendChild(panel);
      }
      const titleText = panel.querySelector(".message-progress-title-text");
      if (titleText) titleText.textContent = msg.pending ? "生成过程" : "查看生成过程";
      if (!msg.pending && panel.open) panel.open = false;
      const list = panel.querySelector(".message-progress-list");
      if (!list) return;
      list.innerHTML = "";
      steps.slice(-8).forEach((step, idx, arr) => {
        const item = document.createElement("div");
        item.className = "message-progress-item";
        if (idx === arr.length - 1 && msg.pending) item.classList.add("active");
        const dot = document.createElement("span");
        dot.className = "message-progress-dot";
        const body = document.createElement("span");
        body.className = "message-progress-body";
        const kind = document.createElement("span");
        kind.className = "message-progress-kind";
        kind.textContent = normalizeProgressKind(step.kind);
        const text = document.createElement("span");
        text.className = "message-progress-text";
        text.textContent = progressStepText(step);
        body.appendChild(kind);
        body.appendChild(text);
        item.appendChild(dot);
        item.appendChild(body);
        list.appendChild(item);
      });
    }

    /**
     * 任务轮询专用：仅更新对应气泡 DOM，避免整表 chatFeed.innerHTML 清空造成的抖动。
     */
    function patchTaskMessageDom(msg, chat) {
      if (!chat || appState.activeChatId !== chat.id) return false;
      const sel = `[data-msg-id="${_escapeMsgIdForSelector(msg.id)}"]`;
      const row = chatFeed.querySelector(sel);
      if (!row) return false;
      const bubble = row.querySelector(".bubble");
      if (!bubble) return false;
      const actions = bubble.querySelector(".msg-actions");

      if (msg.pending && msg.taskId) {
        bubble.classList.add("pending", "image-task-pending");
        bubble.classList.remove("error");
        let wait = bubble.querySelector(".image-task-wait");
        if (!wait) {
          while (bubble.firstChild && bubble.firstChild !== actions) {
            bubble.removeChild(bubble.firstChild);
          }
          wait = buildImageTaskWaitElement(msg);
          if (actions) bubble.insertBefore(wait, actions);
          else bubble.appendChild(wait);
        }
        fillImageTaskWaitFromMsg(wait, msg);
        const btns = actions && actions.querySelectorAll(".msg-action-btn");
        if (btns && btns.length > 1) btns[1].disabled = true;
        return true;
      }

      bubble.classList.remove("pending", "image-task-pending");
      while (bubble.firstChild && bubble.firstChild !== actions) {
        bubble.removeChild(bubble.firstChild);
      }

      const bubbleText = document.createElement(msg.error ? "span" : "div");
      bubbleText.className = msg.error ? "bubble-text" : "bubble-text bubble-md";
      if (msg.error) bubbleText.textContent = msg.text || "";
      else bubbleText.innerHTML = markdownToSafeHtml(msg.text || "");
      if (actions) bubble.insertBefore(bubbleText, actions);
      else bubble.appendChild(bubbleText);

      if (msg.imageUrl) {
        const img = document.createElement("img");
        img.className = "generated-image image-reveal";
        img.src = msg.imageUrl;
        const reveal = () => img.classList.add("image-reveal-visible");
        img.onload = () => requestAnimationFrame(reveal);
        if (img.complete) requestAnimationFrame(reveal);
        img.onclick = () => window.showLightbox(msg.imageUrl);
        if (actions) bubble.insertBefore(img, actions);
        else bubble.appendChild(img);
      }

      if (msg.note) {
        const note = document.createElement("div");
        note.className = "message-note";
        note.textContent = msg.note;
        if (actions) bubble.insertBefore(note, actions);
        else bubble.appendChild(note);
      }

      if (msg.error) bubble.classList.add("error");
      else bubble.classList.remove("error");

      const btns = actions && actions.querySelectorAll(".msg-action-btn");
      if (btns && btns.length > 1) btns[1].disabled = false;

      return true;
    }

    function appendRenderedMessageRow(chat, msg) {
      msg = foldProcessNarrationForRender(msg);
      const row = document.createElement("div");
      row.className = `msg-row ${msg.role === "user" ? "user" : "assistant"}`;
      row.setAttribute("data-msg-id", msg.id);
      row.setAttribute("data-chat-id", chat.id);

      const avatar = document.createElement("div");
      avatar.className = `avatar ${msg.role === "user" ? "user" : "assistant"}`;
      avatar.textContent = msg.role === "user" ? "你" : "怀小仁";

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      if (msg.pending) bubble.classList.add("pending");
      if (msg.error) bubble.classList.add("error");

      if (msg.role === "assistant" && msg.pending && msg.taskId) {
        bubble.classList.add("image-task-pending");
        bubble.appendChild(buildImageTaskWaitElement(msg));
      } else if (msg.role === "assistant" && msg.pending && !msg.taskId && !msg.error) {
        bubble.classList.add("text-task-pending");
        bubble.appendChild(buildTextWaitElement(msg));
      } else {
        let bubbleText;
        if (msg.role === "assistant" && !msg.error) {
          bubbleText = document.createElement("div");
          bubbleText.className = "bubble-text bubble-md";
          bubbleText.innerHTML = markdownToSafeHtml(msg.text || "");
        } else {
          bubbleText = document.createElement("span");
          bubbleText.className = "bubble-text";
          bubbleText.textContent = msg.text || "";
        }
        bubble.appendChild(bubbleText);
        if (msg.role === "assistant") {
          syncMessageProgressSection(bubble, msg);
        }
      }

      if (msg.imageUrl && !(msg.pending && msg.taskId)){
        const img = tuneHistoryImage(document.createElement("img"));
        img.className = "generated-image";
        img.src = msg.imageThumbUrl || msg.imageUrl;
        if (msg.imageThumbUrl && msg.imageThumbUrl !== msg.imageUrl) {
          img.onerror = () => {
            img.onerror = null;
            img.src = msg.imageUrl;
          };
        }
        img.onclick = () => window.showLightbox(msg.imageUrl);
        bubble.appendChild(img);
      }

      if (msg.note){
        const note = document.createElement("div");
        note.className = "message-note";
        note.textContent = msg.note;
        bubble.appendChild(note);
      }

      syncMessageSourcesSection(bubble, msg);

      if (msg.attachments && msg.attachments.length > 0) {
         const wrap = document.createElement("div");
         wrap.className = "msg-attachments";
         msg.attachments.forEach(item => {
           if (msg.role === "assistant" && msg.imageUrl && item.category === "image") return;
           if (item.category === "image"){
             if (staleAttachmentIds.has(item.id)) {
               const span = document.createElement("span");
               span.className = "attachment-stale-label";
               span.textContent = "附件已失效";
               wrap.appendChild(span);
             } else {
               let img = tuneHistoryImage(document.createElement("img"));
               img.className = "msg-attachment-thumb";
               img.src = `/api/attachments/${item.id}/thumb`;
               img.addEventListener(
                 "error",
                 function onThumbErr() {
                   img.removeEventListener("error", onThumbErr);
                   img.src = `/api/attachments/${item.id}`;
                   bindAttachmentImageFallback(img, item.id);
                 },
                 { once: true }
               );
               wrap.appendChild(img);
             }
           } else {
             let doc = document.createElement("div");
             doc.className = "msg-attachment-doc";
             doc.textContent = item.name;
             wrap.appendChild(doc);
           }
         });
         if (wrap.childNodes.length) bubble.appendChild(wrap);
      }

      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.appendChild(
        createMsgIconButton(MSG_ICON_COPY_SVG, MSG_TOOLTIP_COPY, (btn) => copyMessage(msg.id, btn), false, { skipTooltip: true })
      );
      if (msg.role === "assistant") {
        const regenTip = msg.pending ? MSG_TOOLTIP_REGEN_WAIT : MSG_TOOLTIP_REGEN;
        actions.appendChild(
          createMsgIconButton(
            MSG_ICON_REGEN_SVG,
            regenTip,
            () => regenerateAssistant(msg.id),
            !!msg.pending
          )
        );
      }
      bubble.appendChild(actions);

      if (msg.role === "user"){
        row.appendChild(bubble);
        row.appendChild(avatar);
      } else {
        row.appendChild(avatar);
        row.appendChild(bubble);
      }
      chatFeed.appendChild(row);
    }

    function finishRenderedMessages(scrollAnchor) {
      if (autoFollowBottom) {
        maybeScrollToBottom();
      } else if (scrollAnchor) {
        const nh = chatFeed.scrollHeight;
        chatFeed.scrollTop = scrollAnchor.top + (nh - scrollAnchor.height);
      }
      updateScrollBottomBtnOnly();
    }

    function renderMessages(chat){
      const renderSeq = ++messagesRenderSeq;
      if (lastRenderedChatId !== chat.id) {
        lastRenderedChatId = chat.id;
        autoFollowBottom = true;
      }

      const scrollAnchor =
        !autoFollowBottom && chat.messages && chat.messages.length
          ? { top: chatFeed.scrollTop, height: chatFeed.scrollHeight }
          : null;

      chatFeed.innerHTML = "";

      if (chat.messagesLoading && (!chat.messages || !chat.messages.length)) {
        chatFeed.innerHTML = `
          <div class="empty">
            <div class="empty-card">
              <h2 class="empty-title">正在加载会话</h2>
              <p class="empty-desc">请稍候</p>
            </div>
          </div>
        `;
        if (scrollToBottomBtn) scrollToBottomBtn.style.display = "none";
        return;
      }

      if (!chat.messages || !chat.messages.length){
        let cardsHtml = (PROMPT_CARDS[chat.tab] || []).map(txt => 
          `<div class="prompt-card" onclick="usePrompt('${txt}')">${txt}</div>`
        ).join("");

        const tabNames = { text: "AI 对话", image: "AI 生图" };
        const welcomeText = `今天想让${tabNames[chat.tab] || "AI"}帮你做什么？`;

        chatFeed.innerHTML = `
          <div class="empty">
            <div class="empty-card">
              <h2 class="empty-title">${welcomeText}</h2>
              <p class="empty-desc">你可以直接输入需求，或试试下面的快捷指令</p>
              <div class="prompt-cards">${cardsHtml}</div>
            </div>
          </div>
        `;
        if (scrollToBottomBtn) scrollToBottomBtn.style.display = "none";
        return;
      }

      const messages = chat.messages || [];
      let index = 0;
      const renderBatch = (size) => {
        if (renderSeq !== messagesRenderSeq) return;
        const end = Math.min(messages.length, index + size);
        for (; index < end; index += 1) {
          appendRenderedMessageRow(chat, messages[index]);
        }
        finishRenderedMessages(scrollAnchor);
        if (index < messages.length) {
          setTimeout(() => renderBatch(NEXT_RENDER_BATCH_SIZE), 0);
        }
      };
      renderBatch(INITIAL_RENDER_BATCH_SIZE);
    }

    function _renderBubbleText(msgId, pendingMsg) {
      const row = document.querySelector(`[data-msg-id="${msgId}"]`);
      if (!row) return;
      const bubble = row.querySelector(".bubble");
      if (!bubble) return;
      const actions = bubble.querySelector(".msg-actions");
      const showTextWait =
        !!pendingMsg &&
        pendingMsg.role === "assistant" &&
        !!pendingMsg.pending &&
        !pendingMsg.taskId &&
        !pendingMsg.error &&
        !_typewriterState[msgId];
      if (showTextWait) {
        bubble.classList.add("pending", "text-task-pending");
        bubble.classList.remove("error");
        let wait = bubble.querySelector(".text-wait");
        if (!wait) {
          const oldText = bubble.querySelector(".bubble-text");
          if (oldText) oldText.remove();
          wait = buildTextWaitElement(pendingMsg);
          if (actions) bubble.insertBefore(wait, actions);
          else bubble.appendChild(wait);
        }
        fillTextWaitFromMsg(wait, pendingMsg);
        maybeScrollToBottom();
        return;
      }
      const existingWait = bubble.querySelector(".text-wait");
      if (existingWait) existingWait.remove();
      bubble.classList.remove("text-task-pending");
      const isAssistant = pendingMsg.role === "assistant" || row.classList.contains("assistant");
      const isTyping = !!_typewriterState[msgId];
      const useMd = isAssistant && !pendingMsg.error && !isTyping;
      let textNode = bubble.querySelector(".bubble-text");

      if (useMd) {
        if (!textNode || !textNode.classList.contains("bubble-md")) {
          if (textNode) textNode.remove();
          textNode = document.createElement("div");
          textNode.className = "bubble-text bubble-md";
          if (actions) bubble.insertBefore(textNode, actions);
          else bubble.appendChild(textNode);
        }
        textNode.innerHTML = markdownToSafeHtml(pendingMsg.text || "");
        textNode.classList.remove("typing-cursor");
      } else {
        if (!textNode || textNode.classList.contains("bubble-md")) {
          if (textNode) textNode.remove();
          textNode = document.createElement("span");
          textNode.className = "bubble-text";
          if (actions) bubble.insertBefore(textNode, actions);
          else bubble.appendChild(textNode);
        }
        textNode.textContent = pendingMsg.text || "";
        if (isTyping) textNode.classList.add("typing-cursor");
        else textNode.classList.remove("typing-cursor");
      }
      if (pendingMsg.imageUrl) {
        let existing = bubble.querySelector(".generated-image");
        if (!existing) {
          const img = document.createElement("img");
          img.className = "generated-image";
          img.src = pendingMsg.imageUrl;
          img.onclick = () => window.showLightbox(pendingMsg.imageUrl);
          const anchor = bubble.querySelector(".msg-actions");
          if (anchor) bubble.insertBefore(img, anchor);
          else bubble.appendChild(img);
        }
      }
      if (pendingMsg.note) {
        let noteEl = bubble.querySelector(".message-note");
        if (!noteEl) {
          noteEl = document.createElement("div");
          noteEl.className = "message-note";
          const anchor = bubble.querySelector(".msg-actions");
          if (anchor) bubble.insertBefore(noteEl, anchor);
          else bubble.appendChild(noteEl);
        }
        noteEl.textContent = pendingMsg.note;
      }
      syncMessageProgressSection(bubble, pendingMsg);
      syncMessageSourcesSection(bubble, pendingMsg);
      maybeScrollToBottom();
    }

    function updatePendingBubble(pendingMsg) {
      _renderBubbleText(pendingMsg.id, pendingMsg);
    }

window.HRApp.renderers = Object.assign(window.HRApp.renderers || {}, {
  ensureMessageSourcesExpanded,
  renderMessageSourcesHtml,
  syncMessageSourcesSection,
  ragStatusNote,
  _escapeMsgIdForSelector,
  imageTaskPhaseTitle,
  fillTextWaitFromMsg,
  buildTextWaitElement,
  syncMessageProgressSection,
  fillImageTaskWaitFromMsg,
  buildImageTaskWaitElement,
  patchTaskMessageDom,
  renderMessages,
  _renderBubbleText,
  updatePendingBubble,
});
