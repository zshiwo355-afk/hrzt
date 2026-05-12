    function escapeHtml(s) {
      if (s == null) return "";
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    /** 助手气泡 Markdown → 经 DOMPurify 清洗后插入 DOM */
    function markdownToSafeHtml(src) {
      const raw = (src || "").trim();
      if (!raw) return "";
      try {
        if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
          marked.setOptions({ breaks: true, gfm: true });
          const html = marked.parse(raw);
          return DOMPurify.sanitize(html);
        }
      } catch (e) {
        console.warn("[markdown]", e);
      }
      return escapeHtml(src || "").replace(/\n/g, "<br>");
    }

    /** 浏览器维度历史隔离（随请求头带给后端 → history_user_id = browser_{id}） */
    const LS_BROWSER_ID = "huairen_history_browser_id";
    const LS_ACTIVE_ID = "huairen_history_active_conversation_id";
    const LS_CURRENT_TAB = "huairen_history_current_tab";
    /** 会话级 RAG 偏好仅保存在浏览器本地，不写入数据库。 */
    const LS_CHAT_PREFS_STATE = "huairen_chat_prefs_state_v1";
    /** 消息级来源展示缓存仅保存在浏览器本地，不写入数据库。 */
    const LS_MESSAGE_UI_STATE = "huairen_message_ui_state_v1";
    /** 旧版完整会话落盘（仅迁移读一次，不再写入） */
    const LEGACY_LS_CONVERSATIONS = "huairen_ai_conversations";
    const LEGACY_STORAGE_KEY = "huairen_ai_zhongtai_state_v22";
    const RECENT_MESSAGES_LIMIT = 20;
    const TASK_POLL_INTERVAL_MS = 3000;
    const IMAGE_TASK_CLIENT_TIMEOUT_MS = 30 * 60 * 1000 + 15000;
    const IMAGE_EDIT_TASK_CLIENT_TIMEOUT_MS = 500 * 1000 + 15000;

    const MSG_ICON_COPY_SVG =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
    const MSG_ICON_CHECK_SVG =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m20 6-11 11-5-5"/></svg>';
    const MSG_ICON_REGEN_SVG =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 0 6.74 2.74L21 3"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 21"/><path d="M3 21v-5h5"/></svg>';

    const MSG_TOOLTIP_COPY = "复制消息";
    const MSG_TOOLTIP_REGEN = "重新生成";
    const MSG_TOOLTIP_REGEN_WAIT = "生成完成后才能重新生成";
    const MSG_TOOLTIP_EDIT = "编辑消息";

    const DEFAULT_MODEL_PREFERENCES = {
      text: {
        exactIds: [
          "openai/gpt-5.4",
          "openai/gpt-5.5",
          "anthropic/claude-opus-4.7",
          "google/gemini-3.1-pro-preview",
        ],
        keywords: ["gpt-5.4", "gpt-5.5", "opus 4.7", "gemini 3.1 pro preview"],
      },
      image: {
        exactIds: ["openai/gpt-image-2"],
        keywords: ["gpt-image-2", "gpt image 2", "azure openai"],
      },
    };

    const PROMPT_CARDS = {
      text: ["帮我提炼这份文档的核心要点", "将刚才的内容写成一份专业邮件", "帮我写一段Python自动化脚本", "总结这几张图片里的主要信息"],
      image: ["画一只戴着墨镜在冲浪的橘猫", "赛博朋克风格的未来城市街景，8k分辨率", "生成一张适合微信公众号封面的插图，科技感风格"]
    };
    const MARKDOWN_TABLE_SYSTEM_PROMPT =
      "你是表格整理助手。请优先直接输出一个 Markdown 表格。除非用户明确要求，否则不要输出多余解释；如需补充说明，控制在表格前后各一句以内。";
    const REASONING_MODE_LABELS = {
      default: "默认",
      instant: "快速",
      thinking: "思考",
      advanced: "进阶",
    };
    const REASONING_MODE_DESCS = {
      default: "使用模型默认策略",
      instant: "更快，更省推理开销",
      thinking: "更注重多步思考",
      advanced: "更深推理，适合复杂任务",
    };

    const defaultAppState = () => ({
      currentTab: "text",
      activeChatId: null,
      chats: [],
    });

    function normalizeChatTab(tab) {
      return tab === "image" ? "image" : "text";
    }

    function parseApiDateTimeMs(value) {
      if (value == null || value === "") return 0;
      if (typeof value === "number") {
        return Number.isFinite(value) ? value : 0;
      }

      const raw = String(value || "").trim();
      if (!raw) return 0;

      if (/z$/i.test(raw) || /[+-]\d{2}:\d{2}$/.test(raw)) {
        const parsed = Date.parse(raw);
        return Number.isFinite(parsed) ? parsed : 0;
      }

      const m = raw.match(
        /^(\d{4})-(\d{2})-(\d{2})(?:[T\s])(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/
      );
      if (m) {
        const year = Number(m[1]);
        const month = Number(m[2]);
        const day = Number(m[3]);
        const hour = Number(m[4]);
        const minute = Number(m[5]);
        const second = Number(m[6] || 0);
        const millis = Number(String(m[7] || "").padEnd(3, "0") || 0);
        return Date.UTC(year, month - 1, day, hour - 8, minute, second, millis);
      }

      const parsed = Date.parse(raw);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function conversationSidebarTimeMs(conv, fallbackMs) {
      const lastMessageAt = parseApiDateTimeMs(conv && conv.last_message_at);
      if (lastMessageAt) return lastMessageAt;
      const updatedAt = parseApiDateTimeMs(conv && conv.updated_at);
      if (updatedAt) return updatedAt;
      const createdAt = parseApiDateTimeMs(conv && conv.created_at);
      if (createdAt) return createdAt;
      return fallbackMs || Date.now();
    }

    function restoredFailedMessageText(rawText, rawError) {
      const text = (rawText || "").trim();
      if (text) return text;
      const err = (rawError || "").trim();
      if (err && /用户已停止生成|已停止生成|cancelled|canceled/i.test(err)) return "已停止生成。";
      if (err) return formatImageTaskErrorForUser(err);
      return formatImageTaskErrorForUser("");
    }

    window.HRApp.time = Object.assign(window.HRApp.time || {}, {
      parseApiDateTimeMs,
      conversationSidebarTimeMs,
    });

    function messageToStored(m, chat) {
      const hasImg = !!(m.imageUrl);
      const ctype = m.error ? "error" : hasImg ? "image" : "text";
      return {
        id: m.id,
        role: m.role,
        content: m.text || "",
        content_type: ctype,
        error_message: m.error ? (m.text || "") : "",
        image_url: m.imageUrl || null,
        model: m.model != null ? m.model : chat.model || null,
        image_mode: m.image_mode != null ? m.image_mode : chat.image_mode || null,
        attachments: (m.attachments || []).map((a) => ({
          id: a.id,
          name: a.name || "",
          category: a.category || "document",
        })),
        created_at: m.created_at != null ? m.created_at : Date.now(),
        task_id: m.taskId || null,
        note: m.note || null,
        rag_status: m.rag_status || "",
        sources: Array.isArray(m.sources) ? m.sources : [],
        progress_steps: Array.isArray(m.progressSteps) ? m.progressSteps : [],
        sources_expanded: !!m.sourcesExpanded,
        pending: !!m.pending,
      };
    }

    function messageFromStored(st) {
      if (st && st.text !== undefined && st.content_type === undefined) return st;
      const err = st.content_type === "error";
      const inferredType =
        st.content_type ||
        (st.image_url ? "image" : st.role === "assistant" && st.task_id ? "image" : "text");
      return {
        id: st.id,
        role: st.role,
        text: err ? restoredFailedMessageText(st.content, st.error_message) : (st.content != null ? st.content : ""),
        imageUrl: st.image_url || null,
        error: err,
        pending: !!st.pending,
        note: st.note || undefined,
        rag_status: st.rag_status || "",
        sources: Array.isArray(st.sources) ? st.sources : [],
        progressSteps: Array.isArray(st.progress_steps) ? st.progress_steps : [],
        sourcesExpanded: !!st.sources_expanded,
        taskId: st.task_id || undefined,
        attachments: st.attachments || [],
        model: st.model,
        image_mode: st.image_mode,
        created_at: st.created_at,
        content_type: inferredType,
      };
    }

    function pushProgressStep(msg, kind, text) {
      if (!msg) return;
      const cleanText = String(text || "").trim();
      if (!cleanText) return;
      const cleanKind = String(kind || "status").trim() || "status";
      if (!Array.isArray(msg.progressSteps)) msg.progressSteps = [];
      const prev = msg.progressSteps[msg.progressSteps.length - 1];
      if (prev && prev.kind === cleanKind && prev.text === cleanText) return;
      msg.progressSteps.push({ kind: cleanKind, text: cleanText, at: Date.now() });
      if (msg.progressSteps.length > 20) {
        msg.progressSteps = msg.progressSteps.slice(-20);
      }
    }

    const PROCESS_NARRATION_HEADING_RE = /^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*|__)?(Analyzing|Analysing|Exploring|Retrieving|Fetching|Searching|Investigating|Validating|Checking|Reviewing|Identifying|Processing|Gathering|Reading|Scanning|Looking\s+up|Preparing|Understanding|Planning|Thinking|Reasoning|Finding|Discovering|Recommending|Selecting|Curating|Comparing|Ranking|Evaluating|Assessing|Examining|Sifting|Shortlisting)\b/i;
    const PROCESS_NARRATION_SENTENCE_RE = /^(This is your|This week|I'?m|I am|I'?ve|I have|I will|I'll|Let me|Now I'm|Now I am|My focus is|My aim is|This suggests|I need to|We're|We are|These include)\b.*(search|process|analyz|analys|fetch|dig|investigat|validat|check|look|identify|identified|focus|drill|understand|provide|bypass|adapt|organize|gather|retriev|checking|trending|repositories|infrastructure|rewrite|movement|leading|projects|innovative|discussions|illustrat|include|pushing|embodied)/i;
    const LIKELY_ANSWER_START_RE = /^([\u4e00-\u9fff]|#{1,6}\s*[\u4e00-\u9fff]|[-*]\s*[\u4e00-\u9fff]|\d+[.)、]\s*[\u4e00-\u9fff])/;

    function separateLeadingProcessNarration(text) {
      const raw = String(text || "").replace(/\r\n/g, "\n");
      if (!raw.trim()) return { content: raw, steps: [] };
      const lines = raw.split("\n");
      const firstChineseLineIndex = lines.findIndex((line) => LIKELY_ANSWER_START_RE.test(line.trim()));
      if (firstChineseLineIndex > 0) {
        const leading = lines.slice(0, firstChineseLineIndex).map((line) => line.trim()).filter(Boolean);
        const hasEnglishLead = leading.some((line) => /[A-Za-z]/.test(line));
        const hasProcessHint = leading.some((line) =>
          PROCESS_NARRATION_HEADING_RE.test(line) ||
          PROCESS_NARRATION_SENTENCE_RE.test(line) ||
          /\b(focus|analyz|analys|search|identify|discover|explor|recommend|trending|repositories|projects|thinking|examining|shifting|looking|prioritizing|curate|innovative)\b/i.test(line)
        );
        if (hasEnglishLead && hasProcessHint) {
          return {
            content: lines.slice(firstChineseLineIndex).join("\n").trimStart(),
            steps: leading.map((line) => ({ kind: "reasoning", text: line, at: Date.now() })),
          };
        }
      }
      const kept = [];
      const steps = [];
      let skipHead = true;
      let skipProcessParagraph = false;
      let lastHeading = "";
      let skippedBlocks = 0;

      for (const line of lines) {
        const stripped = line.trim();
        if (skipHead) {
          if (skipProcessParagraph) {
            if (!stripped) {
              skipProcessParagraph = false;
              lastHeading = "";
            } else if (!LIKELY_ANSWER_START_RE.test(stripped)) {
              const textPart = lastHeading ? `${lastHeading}：${stripped}` : stripped;
              steps.push({ kind: "reasoning", text: textPart, at: Date.now() });
              lastHeading = "";
            } else {
              kept.push(line);
              skipHead = false;
              skipProcessParagraph = false;
              lastHeading = "";
            }
            continue;
          }
          if (!stripped) continue;
          if (PROCESS_NARRATION_HEADING_RE.test(stripped)) {
            lastHeading = stripped
              .replace(/^#{1,6}\s*/, "")
              .replace(/^[-*]\s*/, "")
              .replace(/^(\*\*|__)/, "")
              .replace(/(\*\*|__)$/, "");
            skipProcessParagraph = true;
            skippedBlocks += 1;
            continue;
          }
          if (skippedBlocks && PROCESS_NARRATION_SENTENCE_RE.test(stripped)) {
            steps.push({ kind: "reasoning", text: stripped, at: Date.now() });
            continue;
          }
          if (!skippedBlocks && PROCESS_NARRATION_SENTENCE_RE.test(stripped)) {
            steps.push({ kind: "reasoning", text: stripped, at: Date.now() });
            skippedBlocks += 1;
            continue;
          }
        }
        kept.push(line);
        if (stripped) skipHead = false;
      }
      return { content: kept.join("\n").trimStart(), steps };
    }

    function finalizeAssistantVisibleContent(msg, finalText) {
      const separated = separateLeadingProcessNarration(finalText);
      if (separated.steps.length) {
        if (!Array.isArray(msg.progressSteps)) msg.progressSteps = [];
        separated.steps.forEach((step) => pushProgressStep(msg, step.kind, step.text));
      }
      return separated.content.trim() || finalText || "未返回内容";
    }

    window.HRApp.processNarration = Object.assign(window.HRApp.processNarration || {}, {
      separateLeadingProcessNarration,
    });

    function conversationToChat(conv) {
      const now = Date.now();
      const ca =
        conv.created_at != null
          ? typeof conv.created_at === "number"
            ? conv.created_at
            : Date.parse(conv.created_at) || now
          : now;
      const ua =
        conv.updated_at != null
          ? typeof conv.updated_at === "number"
            ? conv.updated_at
            : Date.parse(conv.updated_at) || now
          : now;
      const chat = {
        id: conv.id,
        tab: normalizeChatTab(conv.mode || "text"),
        title: conv.title || "新建聊天",
        messages: (conv.messages || []).map(messageFromStored),
        draft: conv.draft != null ? conv.draft : "",
        model: conv.model || "",
        reasoning_mode: conv.reasoning_mode || "default",
        use_rag: !!conv.use_rag,
        use_web_search: !!conv.use_web_search,
        pending: 0,
        attachments: Array.isArray(conv.attachments) ? conv.attachments : [],
        summary: conv.summary || "",
        summaryMessageCount: conv.summaryMessageCount || 0,
        image_mode: conv.image_mode != null && conv.image_mode !== "" ? conv.image_mode : null,
        createdAt: ca,
        updatedAt: ua,
      };
      return applyChatPrefs(chat);
    }

    function chatToConversation(chat) {
      const now = Date.now();
      return {
        id: chat.id,
        title: chat.title || "新建聊天",
        mode: chat.tab,
        image_mode: chat.image_mode != null && chat.image_mode !== "" ? chat.image_mode : null,
        model: chat.model || "",
        reasoning_mode: chat.reasoning_mode || "default",
        draft: chat.draft || "",
        use_rag: !!chat.use_rag,
        use_web_search: !!chat.use_web_search,
        summary: chat.summary || "",
        summaryMessageCount: chat.summaryMessageCount || 0,
        attachments: (chat.attachments || []).map((a) => ({
          id: a.id,
          name: a.name || "",
          category: a.category || "document",
        })),
        messages: (chat.messages || []).map((m) => messageToStored(m, chat)),
        created_at: chat.createdAt != null ? chat.createdAt : now,
        updated_at: chat.updatedAt != null ? chat.updatedAt : now,
      };
    }

    function migrateFromLegacyV22() {
      const raw = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (!raw) return null;
      try {
        const parsed = JSON.parse(raw);
        if (!parsed.chats || !Array.isArray(parsed.chats)) return null;
        const now = Date.now();
        return {
          currentTab: parsed.currentTab || "text",
          activeChatId: parsed.activeChatId,
          chats: parsed.chats.map((c) => ({
            ...c,
            image_mode: c.image_mode || "text_to_image",
            createdAt: c.createdAt != null ? c.createdAt : c.updatedAt || now,
            updatedAt: c.updatedAt != null ? c.updatedAt : now,
          })),
        };
      } catch (e) {
        return null;
      }
    }

    function createNewChatObject(tab) {
      const now = Date.now();
      const normalizedTab = normalizeChatTab(tab);
      return applyChatPrefs({
        id: "chat_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6),
        tab: normalizedTab,
        title: "新建聊天",
        messages: [],
        draft: "",
        model: "",
        reasoning_mode: "default",
        use_rag: false,
        use_web_search: false,
        pending: 0,
        attachments: [],
        summary: "",
        summaryMessageCount: 0,
        image_mode: null,
        createdAt: now,
        updatedAt: now,
      });
    }

    let appState = (function loadShellState() {
      const st = defaultAppState();
      st.currentTab = normalizeChatTab(localStorage.getItem(LS_CURRENT_TAB) || "text");
      st.activeChatId =
        localStorage.getItem(LS_ACTIVE_ID) ||
        localStorage.getItem("huairen_ai_active_conversation_id") ||
        null;
      st.chats = [];
      return st;
    })();
    let modelsCache = { text: [], image: [], all: [] };
    /** 加载失败或 404 的附件 id，避免反复请求同一 URL */
    const staleAttachmentIds = new Set();
    let showAllImageModels = false;
    let dragCounter = 0;
    let isAuthenticated = false;
    let currentUser = null;
    let activeTaskPollers = new Map();
    let activeSseAbort = null;
    let isStreaming = false;
    let _userStopped = false;
    let _historyOssFailed = false;
    let _ossSyncTimer = null;

    let autoFollowBottom = true;
    let lastRenderedChatId = null;
    const SCROLL_BOTTOM_THRESHOLD_PX = 100;
    let inputComposing = false;
    let loginInputComposing = false;

    const sidebar = document.getElementById("sidebar");
    const appShell = document.getElementById("appShell");
    const mobileMenuBtn = document.getElementById("mobileMenuBtn");
    const loginMask = document.getElementById("loginMask");
    const loginBtn = document.getElementById("loginBtn");
    const logoutBtn = document.getElementById("logoutBtn");
    const sidebarUserName = document.getElementById("sidebarUserName");
    const sidebarUserAvatar = document.getElementById("sidebarUserAvatar");
    const usernameInput = document.getElementById("usernameInput");
    const passwordInput = document.getElementById("passwordInput");
    const loginError = document.getElementById("loginError");

    const tabButtons = document.querySelectorAll(".tab-btn");
    const chatListEl = document.getElementById("chatList");
    const newChatBtn = document.getElementById("newChatBtn");
    const clearChatsBtn = document.getElementById("clearChatsBtn");
    
    const modelSelect = document.getElementById("modelSelect");
    const modelSelectFace = document.getElementById("modelSelectFace");
    const reasoningModeWrap = document.getElementById("reasoningModeWrap");
    const reasoningModeFace = document.getElementById("reasoningModeFace");
    const reasoningModeSelect = document.getElementById("reasoningModeSelect");
    const ragToggleWrap = document.getElementById("ragToggleWrap");
    const useRagCb = document.getElementById("useRagCb");
    const webSearchToggleWrap = document.getElementById("webSearchToggleWrap");
    const useWebSearchCb = document.getElementById("useWebSearchCb");
    const imageShowAllWrap = document.getElementById("imageShowAllWrap");
    const showAllImageModelsCb = document.getElementById("showAllImageModelsCb");
    const chatTitle = document.getElementById("chatTitle");
    const chatSub = document.getElementById("chatSub");
    const chatFeed = document.getElementById("chatFeed");
    const scrollToBottomBtn = document.getElementById("scrollToBottomBtn");
    const chatWrap = document.getElementById("chatWrap");
    const statusText = document.getElementById("statusText");
    const modeBadge = document.getElementById("modeBadge");

    const userInput = document.getElementById("userInput");
    const sendBtn = document.getElementById("sendBtn");
    const infoNotice = document.getElementById("infoNotice");
    const errorNotice = document.getElementById("errorNotice");
    const fileInput = document.getElementById("fileInput");
    const attachBtn = document.getElementById("attachBtn");
    const uploadDropZone = document.getElementById("uploadDropZone");
    const uploadList = document.getElementById("uploadList");
    const pageDropOverlay = document.getElementById("pageDropOverlay");

    function syncBootShellTab(tab) {
      const normalizedTab = normalizeChatTab(tab);
      tabButtons.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === normalizedTab);
      });
      if (normalizedTab === "image") {
        chatTitle.textContent = "AI 生图";
        chatSub.textContent = "选择模型并输入提示词，内容将原样提交给模型";
        if (userInput) {
          userInput.placeholder =
            "无参考图：文生图；上传参考图：自动走对应协议（仅 [支持图生图] 的模型可选）。尺寸、比例等请直接写在提示词里。";
        }
        if (ragToggleWrap) ragToggleWrap.style.display = "none";
        if (webSearchToggleWrap) webSearchToggleWrap.style.display = "none";
      } else {
        chatTitle.textContent = "AI 对话";
        chatSub.textContent = "多轮文字问答，适合聊天、分析和写作";
        if (userInput) userInput.placeholder = "请输入你的问题或任务...";
        if (ragToggleWrap) ragToggleWrap.style.display = "flex";
        if (webSearchToggleWrap) webSearchToggleWrap.style.display = "flex";
      }
      if (imageShowAllWrap) imageShowAllWrap.style.display = "none";
    }

    function renderCurrentUser(user) {
      currentUser = user || null;
      const name = String(
        (currentUser && (currentUser.display_name || currentUser.username || currentUser.phone)) || "当前账号"
      ).trim() || "当前账号";
      if (sidebarUserName) sidebarUserName.textContent = name;
      if (sidebarUserAvatar) sidebarUserAvatar.textContent = name.slice(0, 1);
    }

    function showAppShell() {
      if (appShell) appShell.classList.remove("is-auth-hidden");
      if (loginMask) {
        loginMask.classList.remove("show");
        loginMask.style.display = "none";
      }
    }

    function showLoginOnly() {
      if (appShell) appShell.classList.add("is-auth-hidden");
      if (loginMask) {
        loginMask.style.display = "";
        loginMask.classList.add("show");
      }
    }

    syncBootShellTab(appState.currentTab);

    function isDbConversationId(value) {
      return /^[1-9]\d*$/.test(String(value || ""));
    }

    function dragHasFiles(dataTransfer) {
      if (!dataTransfer) return false;
      const types = Array.from(dataTransfer.types || []);
      return types.includes("Files");
    }

    function setPageDropActive(active) {
      if (pageDropOverlay) {
        pageDropOverlay.classList.toggle("show", !!active);
        pageDropOverlay.setAttribute("aria-hidden", active ? "false" : "true");
      }
      if (uploadDropZone) {
        uploadDropZone.classList.toggle("dragover", !!active);
      }
    }

            function dbConversationToChat(conv) {
      const now = Date.now();
      const normalizedTab = normalizeChatTab(conv.mode || "text");
      const chat = {
        id: String(conv.id),
        tab: normalizedTab,
        title: conv.title || "新建聊天",
        messages: [],
        draft: "",
        model: conv.model || "",
        reasoning_mode: "default",
        use_rag: false,
        use_web_search: false,
        pending: 0,
        attachments: [],
        summary: "",
        summaryMessageCount: 0,
        indexMessageCount:
          conv.message_count != null && conv.message_count !== ""
            ? Number(conv.message_count)
            : 0,
        listedInHistoryIndex: true,
        image_mode: null,
        createdAt:
          conv.created_at != null
            ? parseApiDateTimeMs(conv.created_at) || now
            : now,
        updatedAt: conversationSidebarTimeMs(conv, now),
      };
      return applyChatPrefs(chat);
    }

    function dbMessageToChatMessage(msg) {
      const isFailed = msg.status === "failed";
      return {
        id: String(msg.id),
        role: msg.role,
        text: isFailed ? restoredFailedMessageText(msg.content, msg.error_message) : (msg.content || ""),
        imageUrl: msg.image_url || null,
        error: isFailed,
        pending: msg.status === "streaming",
        note: undefined,
        rag_status: "",
        sources: [],
        taskId: msg.task_id || undefined,
        attachments: msg.attachments || [],
        model: msg.model || "",
        image_mode: null,
        created_at:
          msg.created_at != null
            ? typeof msg.created_at === "number"
              ? msg.created_at
              : Date.parse(msg.created_at) || Date.now()
            : Date.now(),
        content_type: "text",
      };
    }

    mobileMenuBtn.addEventListener("click", () => {
      sidebar.classList.toggle("show");
    });
    document.addEventListener("click", (e) => {
      if (window.innerWidth <= 1100 && sidebar.classList.contains("show")) {
        if (!sidebar.contains(e.target) && !mobileMenuBtn.contains(e.target)) {
          sidebar.classList.remove("show");
        }
      }
    });

    window.showLightbox = function(src) {
      document.getElementById("lightboxImg").src = src;
      document.getElementById("lightbox").classList.add("show");
    };

            function loadLegacyAppStateFromLocalStorage() {
      try {
        const rawConv = localStorage.getItem(LEGACY_LS_CONVERSATIONS);
        if (rawConv) {
          const arr = JSON.parse(rawConv);
          if (Array.isArray(arr) && arr.length > 0) {
            const activeId =
              localStorage.getItem(LS_ACTIVE_ID) ||
              localStorage.getItem("huairen_ai_active_conversation_id") ||
              arr[0].id;
            let st = defaultAppState();
            st.chats = arr.map((row) => conversationToChat(row));
            st.activeChatId = activeId;
            const active = st.chats.find((c) => c.id === activeId);
            st.currentTab = active ? active.tab : st.chats[0].tab || "text";
            return st;
          }
        }

        const migrated = migrateFromLegacyV22();
        if (migrated && migrated.chats && migrated.chats.length) {
          if (!migrated.activeChatId || !migrated.chats.find((c) => c.id === migrated.activeChatId)) {
            migrated.activeChatId = migrated.chats[0].id;
          }
          migrated.currentTab =
            migrated.chats.find((c) => c.id === migrated.activeChatId)?.tab || migrated.currentTab;
          try {
            persistAppStateToLs(migrated);
            localStorage.removeItem(LEGACY_STORAGE_KEY);
          } catch (e) {}
          return migrated;
        }

        const rawLegacy = localStorage.getItem(LEGACY_STORAGE_KEY);
        if (rawLegacy) {
          const parsed = JSON.parse(rawLegacy);
          if (parsed.sessions && !parsed.chats) {
            let st = defaultAppState();
            ["text", "image"].forEach((tab) => {
              if (parsed.sessions[tab] && parsed.sessions[tab].messages) {
                let chat = createNewChatObject(tab);
                Object.assign(chat, parsed.sessions[tab]);
                chat.title = "旧版迁移" + tab + "对话";
                st.chats.push(chat);
              }
            });
            if (st.chats.length === 0) st.chats.push(createNewChatObject("text"));
            st.activeChatId = st.chats[0].id;
            st.currentTab = st.chats[0].tab;
            try {
              persistAppStateToLs(st);
              localStorage.removeItem(LEGACY_STORAGE_KEY);
            } catch (e) {}
            return st;
          }
        }

        let st = defaultAppState();
        let initialChat = createNewChatObject("text");
        st.chats.push(initialChat);
        st.activeChatId = initialChat.id;
        try {
          persistAppStateToLs(st);
        } catch (e) {}
        return st;
      } catch (err) {
        let st = defaultAppState();
        let initialChat = createNewChatObject("text");
        st.chats.push(initialChat);
        st.activeChatId = initialChat.id;
        try {
          persistAppStateToLs(st);
        } catch (e) {}
        return st;
      }
    }

    function saveState() {
      try {
        persistAppStateToLs(appState);
      } catch (err) {
        console.warn("本地存储空间已满或受限：", err);
      }
    }

    async function migrateLegacyLocalConversationsToOss() {
      if (!isAuthenticated) return;
      const raw = localStorage.getItem(LEGACY_LS_CONVERSATIONS);
      if (!raw) return;
      let arr;
      try {
        arr = JSON.parse(raw);
      } catch (e) {
        return;
      }
      if (!Array.isArray(arr) || !arr.length) return;
      let migratedOk = false;
      try {
        for (const row of arr) {
          const mode = row.mode || "text";
          const pr = await historyFetch("/api/history/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              mode,
              title: row.title || "新建聊天",
              model: row.model || "",
            }),
          });
          if (!pr.ok) continue;
          const pack = await pr.json().catch(() => ({}));
          const conversation = pack.conversation;
          if (!conversation || !conversation.id) continue;
          const cid = conversation.id;
          const full = Object.assign({}, row, {
            id: cid,
            user_id: conversation.user_id,
            messages: row.messages || [],
          });
          const put = await historyFetch(`/api/history/conversations/${cid}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(full),
          });
          if (put.ok) migratedOk = true;
        }
      } catch (e) {
        console.warn("[history] migrate legacy failed", e);
      }
      if (migratedOk) {
        try {
          localStorage.removeItem(LEGACY_LS_CONVERSATIONS);
        } catch (e2) {}
      }
    }

    async function ensureRemoteConversationForTab(tab) {
      const r = await historyFetch("/api/history/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: tab, title: "新建聊天" }),
      });
      if (!r.ok) return;
      const pack = await r.json().catch(() => ({}));
      if (pack.conversation) {
        appState.chats.push(conversationToChat(pack.conversation));
      }
    }

    async function ensureAtLeastOneChatPerTabRemote() {
      for (const tab of ["text", "image"]) {
        if (!appState.chats.some((c) => c.tab === tab)) {
          await ensureRemoteConversationForTab(tab);
        }
      }
    }

    async function loadConversationDetailFromServer(chatId) {
      if (!chatId) return;
      const chat = appState.chats.find((c) => c.id === chatId);
      if (!chat) return;
      const r = await historyFetch(`/api/history/conversations/${chatId}`);
      if (!r.ok) return;
      const data = await r.json().catch(() => ({}));
      const conv = data.conversation;
      if (!conv) return;
      const loaded = conversationToChat(conv);
      Object.assign(chat, loaded);
      chat.messages = loaded.messages || [];
    }

    async function syncChatToOss(chat) {
      return;
    }

    function scheduleSyncActiveChatToOss() {
      return;
    }

    async function hydrateHistoryFromOss() {
      _historyOssFailed = false;
      await migrateLegacyLocalConversationsToOss();
      const r = await historyFetch("/api/history/conversations");
      if (r.status === 503) {
        _historyOssFailed = true;
        const legacy = loadLegacyAppStateFromLocalStorage();
        appState.chats = legacy.chats;
        appState.activeChatId = legacy.activeChatId;
        appState.currentTab = legacy.currentTab;
        showError("OSS 未配置或不可用，已回退到本地历史（仅本机、不跨刷新同步）。");
        persistLocalMeta();
        return;
      }
      if (r.status === 401) {
        return;
      }
      if (!r.ok) {
        _historyOssFailed = true;
        const legacy = loadLegacyAppStateFromLocalStorage();
        appState.chats = legacy.chats;
        appState.activeChatId = legacy.activeChatId;
        appState.currentTab = legacy.currentTab;
        showError("无法从 OSS 加载历史（HTTP " + r.status + "），已尝试本地回退。");
        persistLocalMeta();
        return;
      }
      const data = await r.json().catch(() => ({}));
      const list = data.conversations || [];
      appState.chats = list.map((row) => ({
        id: row.id,
        tab: row.mode || "text",
        title: row.title || "新建聊天",
        messages: [],
        draft: "",
        model: "",
        pending: 0,
        attachments: [],
        summary: "",
        summaryMessageCount: 0,
        /** 列表索引中的计数（hydrate 时尚未拉取正文，用于侧边栏「是否展示」判断） */
        indexMessageCount:
          row.message_count != null && row.message_count !== ""
            ? Number(row.message_count)
            : null,
        indexHasSummary: !!row.has_summary,
        /** 来自 GET /conversations 全量列表（用于兼容旧 index 无 message_count 字段） */
        listedInHistoryIndex: true,
        image_mode: null,
        createdAt:
          typeof row.created_at === "number"
            ? row.created_at
            : Date.parse(row.created_at) || Date.now(),
        updatedAt:
          typeof row.updated_at === "number" ? row.updated_at : Date.parse(row.updated_at) || Date.now(),
      }));
      await ensureAtLeastOneChatPerTabRemote();
      const preferredTab = normalizeChatTab(appState.currentTab || localStorage.getItem(LS_CURRENT_TAB) || "text");
      const activeChat = appState.chats.find((c) => c.id === appState.activeChatId);
      const latestForPreferredTab = appState.chats
        .filter((c) => c.tab === preferredTab)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
      if (!activeChat || activeChat.tab !== preferredTab) {
        appState.activeChatId = latestForPreferredTab
          ? latestForPreferredTab.id
          : ([...appState.chats].sort((a, b) => b.updatedAt - a.updatedAt)[0] || {}).id || null;
      }
      appState.currentTab = preferredTab;
      persistLocalMeta();
      if (appState.activeChatId) {
        await loadConversationDetailFromServer(appState.activeChatId);
      }
    }

        /** 图片/异步任务失败气泡：仅中文建议；不把 raw 拼进返回值（后端 task.error_message 仍可保留原文）。 */
    const IMG_TASK_ERR_HINT = {
      TIMEOUT:
        "图片编辑处理超时，建议：\n" +
        "1. 改用 GPT Image 1.5\n" +
        "2. 简化编辑要求\n" +
        "3. 降低图片尺寸后重试",
      OVERLOAD:
        "当前图片引擎繁忙，建议：\n" +
        "1. 稍后重试\n" +
        "2. 改用 GPT Image 1.5\n" +
        "3. 错峰再试",
      NO_EDIT:
        "当前模型不支持图生图，建议：\n" +
        "1. 切换到支持图生图的模型\n" +
        "2. 重新上传参考图后再试",
      REF_BAD:
        "参考图已失效，建议：\n" +
        "1. 重新上传图片\n" +
        "2. 再次提交任务",
      SAFETY:
        "图片生成被内容安全系统拦截，建议：\n" +
        "1. 调整提示词，避免裸露、性暗示或敏感场景\n" +
        "2. 使用更日常、非敏感的描述重新生成",
      PARAM_BAD:
        "请求参数异常，建议：\n" +
        "1. 重新选择模型\n" +
        "2. 检查图片和提示词后重试",
      NETWORK:
        "无法连接上游图片服务（网络或 DNS 异常），建议：\n" +
        "1. 检查本机网络、VPN、是否需关闭「仅局域网」\n" +
        "2. 在终端执行：ping api.ofox.ai 或换 DNS（如 8.8.8.8）后重试\n" +
        "3. 确认浏览器能打开 https://api.ofox.ai 后再提交任务",
      CREDIT:
        "图片生成失败：OFOX 账户余额不足。\n" +
        "请先给 OFOX 充值，或切换到仍有额度的图片模型后再试。",
      UNKNOWN:
        "图片处理失败，建议：\n" +
        "1. 稍后重试\n" +
        "2. 简化要求后再试\n" +
        "3. 如多次失败请更换模型",
    };

    const MODE_SIDEBAR_LABEL = { text: "文本", image: "生图" };

    function formatChatRelativeTime(ts) {
      const t = typeof ts === "number" ? ts : parseApiDateTimeMs(ts) || 0;
      if (!t) return "";
      let diff = Date.now() - t;
      if (diff < 0) diff = 0;
      const sec = Math.floor(diff / 1000);
      if (sec < 60) return "刚刚";
      const min = Math.floor(sec / 60);
      if (min < 60) return min + "分钟前";
      const hr = Math.floor(min / 60);
      if (hr < 24) return hr + "小时前";
      const day = Math.floor(hr / 24);
      if (day < 7) return day + "天前";
      const d = new Date(t);
      return d.getMonth() + 1 + "/" + d.getDate();
    }

    function chatListPreview(chat) {
      const s = (chat.summary || "").trim();
      if (s) return s.length > 80 ? s.slice(0, 80) + "…" : s;
      const msgs = chat.messages || [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (!m) continue;
        const raw = m.text != null ? String(m.text).trim() : "";
        if (raw) return raw.length > 80 ? raw.slice(0, 80) + "…" : raw;
        if (m.imageUrl || m.content_type === "image") return "[图片]";
        if (m.role === "assistant" && m.taskId) return "[图片]";
      }
      return "";
    }

    /** 左侧列表是否展示 mode 标签：有实质内容或已改标题时才显示，避免空会话/占位「视频」等 */
    function chatSidebarHasMeaningfulContent(chat) {
      const title = (chat.title || "").trim();
      if (title && title !== "新建聊天") return true;
      const msgs = chat.messages || [];
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i];
        if (!m || m.pending) continue;
        if (m.role === "user") {
          if (String(m.text || "").trim()) return true;
          if ((m.attachments || []).length) return true;
        }
        if (m.role === "assistant") {
          const t = String(m.text || "").trim();
          if (t && t !== "处理中...") return true;
          if (m.imageUrl || m.content_type === "image") return true;
          if (m.taskId) return true;
          if (m.error) return true;
        }
      }
      const s = (chat.summary || "").trim();
      if (s) return true;
      return false;
    }

    function shouldShowSidebarModeTag(chat) {
      if (!chat || !chatSidebarHasMeaningfulContent(chat)) return false;
      const tab = chat.tab || "text";
      return tab === "text" || tab === "image";
    }

    /** 左侧「你的会话」是否列出：空白新建不进列表；索引中有消息/摘要或本地已加载正文也算 */
    function chatAppearsInSidebarHistory(chat) {
      if (!chat) return false;
      if ((chat.summary || "").trim()) return true;
      const msgs = chat.messages || [];
      if (msgs.length > 0) return true;
      if (chat.indexHasSummary) return true;
      const imc = chat.indexMessageCount;
      if (imc != null && !Number.isNaN(Number(imc)) && Number(imc) > 0) return true;
      /* 旧版 index 行可能没有 message_count；只要仍在服务端列表中即可显示 */
      if (chat.listedInHistoryIndex && (imc == null || imc === undefined)) return true;
      return false;
    }

    function formatImageTaskErrorForUser(raw) {
      const hint = raw == null ? "" : String(raw);
      const low = hint.toLowerCase();

      const hitKeyword = (list) => {
        for (const kw of list) {
          if (/[\u4e00-\u9fff]/.test(kw)) {
            if (hint.includes(kw)) return true;
          } else {
            const k = kw.toLowerCase();
            if (k === "408" || k === "429" || k === "503") {
              if (hint.includes(kw)) return true;
            } else if (low.includes(k)) return true;
          }
        }
        return false;
      };

      if (
        hitKeyword([
          "408",
          "timeout",
          "timed out",
          "readtimeout",
          "read timed out",
          "the operation was timeout",
          "上游图片编辑处理超时",
        ])
      ) {
        return IMG_TASK_ERR_HINT.TIMEOUT;
      }
      if (hitKeyword(["429", "503", "overloaded", "engine is overloaded"])) {
        return IMG_TASK_ERR_HINT.OVERLOAD;
      }
      if (hitKeyword(["402", "insufficient credits", "insufficient_credits", "balance", "余额不足"])) {
        return IMG_TASK_ERR_HINT.CREDIT;
      }
      if (
        hitKeyword([
          "safety",
          "sensitive information",
          "safety_violations",
          "sexual",
          "content safety",
          "内容安全",
          "敏感",
        ])
      ) {
        return IMG_TASK_ERR_HINT.SAFETY;
      }
      if (
        hitKeyword([
          "not supported",
          "does not support",
          "不支持图生图",
          "当前模型不支持图生图",
          "image editing is not supported",
        ])
      ) {
        return IMG_TASK_ERR_HINT.NO_EDIT;
      }
      if (
        hitKeyword([
          "attachment file not found",
          "file not found",
          "附件已失效",
          "does not exist",
        ])
      ) {
        return IMG_TASK_ERR_HINT.REF_BAD;
      }
      if (
        hitKeyword([
          "model parameter",
          "invalid request",
          "bad request",
          "you must provide a model parameter",
        ])
      ) {
        return IMG_TASK_ERR_HINT.PARAM_BAD;
      }
      if (
        hitKeyword([
          "connectionerror",
          "connection aborted",
          "max retries exceeded",
          "nameresolutionerror",
          "failed to resolve",
          "nodename nor servname",
          "getaddrinfo",
          "name or service not known",
          "network is unreachable",
          "temporary failure in name resolution",
          "newconnectionerror",
          "无法连接上游",
        ])
      ) {
        return IMG_TASK_ERR_HINT.NETWORK;
      }
      return IMG_TASK_ERR_HINT.UNKNOWN;
    }

    function formatArtifactTaskErrorForUser(raw) {
      const text = String(raw || "").trim();
      if (!text) return "文件生成失败，请稍后重试。";
      const first = text.split(/\n--- traceback|\nTraceback|\n\s+File\s+"/)[0].trim();
      if (/能力询问|普通对话|不应创建文件任务/.test(first)) {
        return "这像是在询问能否生成文件，我不会直接创建文件任务。请直接说“帮我生成一个 Excel/PPT”，我再开始生成。";
      }
      if (/Expecting value|JSONDecodeError|未解析到/.test(first)) {
        return "文件结构生成失败，请换个更明确的要求再试。";
      }
      return first || "文件生成失败，请稍后重试。";
    }

    function getActiveChat() {
      let chat = appState.chats.find((c) => c.id === appState.activeChatId);
      if (!chat) {
        chat = appState.chats.find((c) => c.tab === appState.currentTab);
        if (!chat) {
          chat = appState.chats[0] || null;
        }
        if (!chat) return null;
        appState.activeChatId = chat.id;
        persistLocalMeta();
      }
      return chat;
    }

    async function switchTab(tab) {
      appState.currentTab = normalizeChatTab(tab);
      let recentChat = appState.chats
        .filter((c) => c.tab === appState.currentTab)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
      if (!recentChat) {
        const created = await createConversationOnServer(appState.currentTab, "");
        recentChat = dbConversationToChat(created);
        appState.chats.unshift(recentChat);
      }
      if (!recentChat) return;
      appState.activeChatId = recentChat.id;
      persistLocalMeta();
      const loadPromise = loadConversationMessagesFromDb(recentChat.id);
      updateSidebar();
      updateWorkspace();
      loadPromise
        .then(() => {
          if (appState.activeChatId !== String(recentChat.id)) return;
          updateSidebar();
          updateWorkspace();
        })
        .catch((e) => {
          if (e && e.name === "AbortError") return;
          showError(e && e.message ? e.message : "加载消息失败");
        });

      if (window.innerWidth <= 1100) {
        sidebar.classList.remove("show");
      }
    }

    async function switchChat(chatId) {
      const chat = appState.chats.find((c) => c.id === chatId);
      if (chat) {
        appState.currentTab = chat.tab;
        appState.activeChatId = chat.id;
        persistLocalMeta();
        const loadPromise = loadConversationMessagesFromDb(chat.id);
        updateSidebar();
        updateWorkspace();
        loadPromise
          .then(() => {
            if (appState.activeChatId !== String(chat.id)) return;
            updateSidebar();
            updateWorkspace();
          })
          .catch((e) => {
            if (e && e.name === "AbortError") return;
            showError(e && e.message ? e.message : "加载消息失败");
          });
        if (window.innerWidth <= 1100) sidebar.classList.remove("show");
      }
    }

    async function handleNewChat() {
      try {
        const created = await createConversationOnServer(appState.currentTab, "");
        const newChat = dbConversationToChat(created);
        appState.chats.unshift(newChat);
        appState.activeChatId = newChat.id;
        persistLocalMeta();
      } catch (e) {
        showError(e && e.message ? e.message : "新建会话失败");
        return;
      }
      updateSidebar();
      updateWorkspace();
      if (window.innerWidth <= 1100) sidebar.classList.remove("show");
    }

    async function clearCurrentTabChats() {
      const tab = appState.currentTab;
      const victims = appState.chats.filter((c) => c.tab === tab);
      if (!victims.length) return;
      try {
        for (const c of victims) {
          if (!isDbConversationId(c.id)) continue;
          await deleteConversationOnServer(c.id);
        }
      } catch (e) {
        showError(e && e.message ? e.message : "删除会话失败");
        return;
      }
      appState.chats = appState.chats.filter((c) => c.tab !== tab);
      let next = appState.chats
        .filter((c) => c.tab === tab)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
      if (!next) {
        const created = await createConversationOnServer(tab, "");
        next = dbConversationToChat(created);
        appState.chats.unshift(next);
      }
      appState.activeChatId = next ? next.id : null;
      if (appState.activeChatId) {
        await loadConversationMessagesFromDb(appState.activeChatId);
      }
      persistLocalMeta();
      updateSidebar();
      updateWorkspace();
    }

    async function deleteChat(chatId) {
      const victim = appState.chats.find((c) => c.id === chatId);
      if (!victim) return;
      try {
        if (isDbConversationId(chatId)) {
          await deleteConversationOnServer(chatId);
        }
      } catch (e) {
        showError(e && e.message ? e.message : "删除会话失败");
        return;
      }
      const tab = victim ? victim.tab : appState.currentTab;
      appState.chats = appState.chats.filter((c) => c.id !== chatId);
      if (appState.activeChatId === chatId) {
        let next = appState.chats
          .filter((c) => c.tab === tab)
          .sort((a, b) => b.updatedAt - a.updatedAt)[0];
        if (!next) {
          const created = await createConversationOnServer(tab, "");
          next = dbConversationToChat(created);
          appState.chats.unshift(next);
        }
        appState.activeChatId = next ? next.id : null;
        if (appState.activeChatId) {
          await loadConversationMessagesFromDb(appState.activeChatId);
        }
      }
      persistLocalMeta();
      updateSidebar();
      updateWorkspace();
    }

    async function renameChat(chatId) {
      const chat = appState.chats.find((c) => c.id === chatId);
      if (!chat) return;
      const nextTitle = window.prompt("请输入新的会话标题", chat.title || "新建聊天");
      if (nextTitle == null) return;
      const cleaned = String(nextTitle).trim();
      if (!cleaned) {
        showError("标题不能为空");
        return;
      }
      try {
        const updated = await renameConversationOnServer(chat.id, cleaned);
        chat.title = updated.title || cleaned;
        chat.updatedAt =
          updated.updated_at != null
            ? typeof updated.updated_at === "number"
              ? updated.updated_at
              : Date.parse(updated.updated_at) || Date.now()
            : Date.now();
        saveState();
        updateSidebar();
        updateWorkspace();
      } catch (e) {
        showError(e && e.message ? e.message : "重命名失败");
      }
    }

    function updateSidebar() {
      tabButtons.forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === appState.currentTab);
      });

      chatListEl.innerHTML = "";
      // 统一列表：仅按 updatedAt 倒序；空白会话不进入「你的会话」
      const visibleChats = appState.chats.filter(chatAppearsInSidebarHistory);
      const allChats = [...visibleChats].sort(
        (a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)
      );

      if (allChats.length === 0) {
        chatListEl.innerHTML = `<div style="padding:12px 4px;color:var(--text-muted);font-size:13px;text-align:center;">暂无会话</div>`;
      } else {
        allChats.forEach(chat => {
          const div = document.createElement("div");
          div.className = "chat-item" + (chat.id === appState.activeChatId ? " active" : "");

          const main = document.createElement("div");
          main.className = "chat-item-main";

          const top = document.createElement("div");
          top.className = "chat-item-top";

          const titleSpan = document.createElement("span");
          titleSpan.className = "chat-item-title";
          titleSpan.textContent = chat.title || "新建聊天";
          titleSpan.ondblclick = (e) => {
            e.stopPropagation();
            void renameChat(chat.id);
          };
          top.appendChild(titleSpan);

          if (shouldShowSidebarModeTag(chat)) {
            const modeEl = document.createElement("span");
            modeEl.className = "chat-item-mode";
            const tabKey = chat.tab === "image" || chat.tab === "text" ? chat.tab : "text";
            modeEl.textContent = MODE_SIDEBAR_LABEL[tabKey] || "文本";
            top.appendChild(modeEl);
          }

          main.appendChild(top);

          const prevText = chatListPreview(chat);
          if (prevText) {
            const preview = document.createElement("div");
            preview.className = "chat-item-preview";
            preview.textContent = prevText;
            main.appendChild(preview);
          }

          const right = document.createElement("div");
          right.className = "chat-item-right";

          const timeEl = document.createElement("div");
          timeEl.className = "chat-item-time";
          timeEl.textContent = formatChatRelativeTime(chat.updatedAt);

          const menuBtn = document.createElement("button");
          menuBtn.className = "chat-item-menu";
          menuBtn.textContent = "···";
          menuBtn.onclick = (e) => {
            e.stopPropagation();
            if (confirm("删除这个对话？")) void deleteChat(chat.id);
          };

          right.appendChild(timeEl);
          right.appendChild(menuBtn);

          div.appendChild(main);
          div.appendChild(right);

          div.onclick = () => void switchChat(chat.id);
          chatListEl.appendChild(div);
        });
      }
    }

    function getAcceptByTab(tab){
      return tab === "image" ? ".png,.jpg,.jpeg,.webp" : ".pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.xlsx,.xls,.png,.jpg,.jpeg,.webp";
    }

    /** 与后端 model 目录一致：以 supports_image_to_image 为准，并兼容 adapter/capability。 */
    function modelEntrySupportsImageToImage(m) {
      if (!m || !m.id) return false;
      if (m.supports_image_to_image === true) return true;
      if (m.supports_image_to_image === false) return false;
      const ad = m.adapter;
      if (ad === "openai_images" || ad === "gemini_native") return true;
      const cap = m.capability;
      if (cap === "image-edit" || cap === "image-gemini") return true;
      const ml = String(m.id).toLowerCase();
      if (ml.startsWith("azure-openai/")) return true;
      if (ml === "openai/gpt-image-2") return true;
      if (ml.includes("banana")) return true;
      if (
        ml.includes("gemini") &&
        (ml.includes("image") || ml.includes("flash-image") || ml.includes("pro-image"))
      ) {
        return true;
      }
      return false;
    }

    function imageModelMetaById(modelId) {
      return (modelsCache.image || []).find((x) => x.id === modelId) || null;
    }

    function chatHasImageRefAttachments(chat) {
      return (chat.attachments || []).some((a) => a.category === "image");
    }

    function imageTabModelListForPicker(chat) {
      const allImage = modelsCache.image || [];
      if (chat.tab !== "image") return allImage;
      if (!chatHasImageRefAttachments(chat)) return allImage;
      return allImage.filter(modelEntrySupportsImageToImage);
    }

    function modelCapabilityLabelSuffix(m, tab) {
      if (tab === "image") {
        if (modelEntrySupportsImageToImage(m)) return " [支持图生图]";
        if (m.supports_image_to_image === false) return " [仅文生图]";
        const c = m.capability;
        if (c === "image-gen-only") return " [仅文生图]";
        return "";
      }
      const c = m.capability;
      if (c && c !== tab) return " [" + c + "]";
      if (m.classify) return " [" + m.classify + "]";
      return "";
    }

    /**
     * 带参考图时仅支持图生图的模型可选；自动切换到第一个支持图生图的模型。
     * @param {object} opts quiet：无法切换时不弹错误（如切换会话时避免刷屏）
     * @returns {"ok"|"switched"|"no_i2i_models"}
     */
    function ensureImageEditModelWhenReferenced(chat, opts) {
      const quiet = opts && opts.quiet;
      if (chat.tab !== "image" || !chatHasImageRefAttachments(chat)) return "ok";
      return ensureImageEditModelForReferenceUse(chat, quiet);
    }

    function ensureImageEditModelForReferenceUse(chat, quiet) {
      if (!chat || chat.tab !== "image") return "ok";
      const list = modelsCache.image || [];
      const cur = imageModelMetaById(chat.model);
      if (modelEntrySupportsImageToImage(cur || { id: chat.model })) return "ok";
      const first = list.find(modelEntrySupportsImageToImage);
      if (first) {
        const beforeId = chat.model;
        const metaBefore = cur || { id: beforeId };
        chat.model = first.id;
        saveState();
        console.warn("[huairen image-model-switch]", {
          selectedModelBeforeSwitch: beforeId,
          selectedModelAfterSwitch: first.id,
          hasAttachments: chatHasImageRefAttachments(chat),
          supports_image_to_image_before: metaBefore.supports_image_to_image,
          supports_image_to_image_after: first.supports_image_to_image,
          adapter_before: metaBefore.adapter,
          adapter_after: first.adapter,
          capability_before: metaBefore.capability,
          capability_after: first.capability,
          quiet,
        });
        return "switched";
      }
      if (!quiet) {
        showError(
          "当前账号下没有支持参考图/图生图的模型（如 GPT Image、Gemini 图片系列），无法使用参考图。"
        );
      }
      return "no_i2i_models";
    }

    function updateWorkspace() {
      clearNotice();
      const chat = getActiveChat();
      const tab = chat.tab;

      fileInput.setAttribute("accept", getAcceptByTab(tab));
      modeBadge.textContent = `当前：${tab==="image" ? "图片" : "文本"}`;

      if (tab === "text"){
        chatTitle.textContent = "AI 对话";
        chatSub.textContent = "多轮文字问答，适合聊天、分析和写作";
        userInput.placeholder = "请输入你的问题或任务...";
        if (ragToggleWrap) ragToggleWrap.style.display = "flex";
        if (useRagCb) useRagCb.checked = !!chat.use_rag;
        if (webSearchToggleWrap) webSearchToggleWrap.style.display = "flex";
        if (useWebSearchCb) useWebSearchCb.checked = !!chat.use_web_search;
      } else if (tab === "image"){
        chatTitle.textContent = "AI 生图";
        chatSub.textContent = "选择模型并输入提示词，内容将原样提交给模型";
        userInput.placeholder =
          "无参考图：文生图；上传参考图：自动走对应协议（仅 [支持图生图] 的模型可选）。尺寸、比例等请直接写在提示词里。";
        if (ragToggleWrap) ragToggleWrap.style.display = "none";
        if (useRagCb) useRagCb.checked = false;
        if (webSearchToggleWrap) webSearchToggleWrap.style.display = "none";
        if (useWebSearchCb) useWebSearchCb.checked = false;
      }

      if (tab === "image") {
        imageShowAllWrap.style.display = "none";
        if (showAllImageModelsCb) showAllImageModelsCb.checked = true;
      } else {
        imageShowAllWrap.style.display = "none";
      }

      userInput.value = chat.draft || "";
      if (tab === "image") {
        ensureImageEditModelWhenReferenced(chat, { quiet: true });
      }
      renderModelOptions(chat);
      renderMessages(chat);
      renderUploadList(chat);
      syncComposerPresentation();
      setStreamingUI(isStreaming);
    }

    function syncComposerInputHeight(collapsed) {
      if (!userInput) return;
      userInput.style.height = "auto";
      const minHeight = collapsed ? 24 : 24;
      const next = Math.min(Math.max(userInput.scrollHeight, minHeight), 220);
      userInput.style.height = `${next}px`;
      userInput.style.overflowY = userInput.scrollHeight > 220 ? "auto" : "hidden";
    }

    function syncComposerPresentation() {
      const chat = getActiveChat();
      if (!chat || !uploadDropZone || !userInput) return;
      const hasText = !!String(userInput.value || "").trim();
      const hasAttachments = Array.isArray(chat.attachments) && chat.attachments.length > 0;
      const collapsed = chat.tab === "text" && !hasText && !hasAttachments;
      uploadDropZone.classList.toggle("is-idle", collapsed);
      syncComposerInputHeight(collapsed);
      if (sendBtn) sendBtn.disabled = !hasText && !hasAttachments;
    }

    function normalizeReasoningModeValue(value) {
      const raw = String(value || "").trim().toLowerCase();
      return Object.prototype.hasOwnProperty.call(REASONING_MODE_LABELS, raw) ? raw : "default";
    }

    function currentTextModelMeta(modelId) {
      return (modelsCache.text || []).find((item) => item.id === modelId) || null;
    }

    function currentReasoningModesForChat(chat) {
      if (!chat || chat.tab !== "text") return [];
      const meta = currentTextModelMeta(chat.model);
      if (!meta || !meta.supports_reasoning) return [];
      return Array.isArray(meta.reasoning_modes) ? meta.reasoning_modes.filter((mode) => REASONING_MODE_LABELS[mode]) : [];
    }

    function modelShortLabelForId(tab, modelId, chat) {
      if (!modelId) return "";
      let tabList =
        tab === "image" ? imageTabModelListForPicker(chat) : modelsCache.text || [];
      if (tab === "image" && chatHasImageRefAttachments(chat) && chat.model) {
        const fullRow = imageModelMetaById(chat.model);
        if (modelEntrySupportsImageToImage(fullRow || {}) && !tabList.some((x) => x.id === chat.model)) {
          tabList = [fullRow].concat(tabList.filter((x) => x.id !== chat.model));
        }
      }
      const m = tabList.find((x) => x.id === modelId);
      return m ? String(m.name || m.id) : "";
    }

    function syncModelSelectFace() {
      if (!modelSelectFace || !modelSelect) return;
      const chat = getActiveChat();
      const opt = modelSelect.selectedOptions[0];
      if (!opt) {
        modelSelectFace.textContent = "";
        return;
      }
      if (!opt.value) {
        modelSelectFace.textContent = opt.textContent || "";
        return;
      }
      const short = modelShortLabelForId(chat.tab, opt.value, chat);
      modelSelectFace.textContent =
        short ||
        (opt.textContent || "").split(" · ")[0] ||
        opt.textContent ||
        "";
    }

    function renderModelOptions(chat){
      let tabList =
        chat.tab === "image" ? imageTabModelListForPicker(chat) : modelsCache.text || [];
      if (chat.tab === "image" && chatHasImageRefAttachments(chat) && chat.model) {
        const fullRow = imageModelMetaById(chat.model);
        if (modelEntrySupportsImageToImage(fullRow || {}) && !tabList.some((x) => x.id === chat.model)) {
          tabList = [fullRow].concat(tabList.filter((x) => x.id !== chat.model));
        }
      }
      const items = tabList.map((m) => {
        const shortName = m.name || m.id;
        const fullLabel =
          chat.tab === "text"
            ? `${shortName} · ${m.hint || "通用对话"}`
            : shortName + modelCapabilityLabelSuffix(m, chat.tab);
        return { id: m.id, fullLabel };
      });
      modelSelect.innerHTML = "";
      if (!items.length){
        modelSelect.innerHTML = `<option value="">暂无可用模型</option>`;
        syncModelSelectFace();
        return;
      }

      const currentStillValid = !!chat.model && items.some((i) => i.id === chat.model);

      if (!chat.model || !currentStillValid) {
        const tabPrefs = loadTabPrefs(chat.tab);
        const remembered = String(tabPrefs.model || "").trim();
        if (remembered && items.some((i) => i.id === remembered)) {
          chat.model = remembered;
        }
      }

      if (!chat.model || !items.some((i) => i.id === chat.model)) {
        const pref = DEFAULT_MODEL_PREFERENCES[chat.tab] || { exactIds: [], keywords: [] };
        let matched = items[0].id;
        for (let exactId of pref.exactIds || []) {
          let found = items.find((i) => i.id === exactId);
          if (found) { matched = found.id; break; }
        }
        for (let k of pref.keywords) {
            let found = items.find(i => (`${i.fullLabel} ${i.id}`).toLowerCase().includes(k.toLowerCase()));
            if (found) { matched = found.id; break; }
        }
        if (chat.model !== matched) {
          console.warn("[huairen renderModelOptions reset]", {
            from: chat.model,
            to: matched,
            tab: chat.tab,
            hasImageRefs: chat.tab === "image" ? chatHasImageRefAttachments(chat) : false,
            reason: !chat.model ? "no_model" : "not_in_items",
          });
        }
        chat.model = matched;
        persistChatPrefs(chat);
        saveState();
      }

      items.forEach(item => {
        let op = document.createElement("option");
        op.value = item.id;
        op.textContent = item.fullLabel;
        if (item.id === chat.model) op.selected = true;
        modelSelect.appendChild(op);
      });
      syncModelSelectFace();
      renderReasoningModeOptions(chat);
    }

    function renderReasoningModeOptions(chat) {
      if (!reasoningModeWrap || !reasoningModeSelect) return;
      const modes = currentReasoningModesForChat(chat);
      if (chat.tab !== "text" || !modes.length) {
        reasoningModeWrap.style.display = "none";
        reasoningModeSelect.innerHTML = "";
        if (reasoningModeFace) reasoningModeFace.textContent = "";
        chat.reasoning_mode = "default";
        persistChatPrefs(chat);
        return;
      }

      reasoningModeWrap.style.display = "grid";
      reasoningModeSelect.innerHTML = "";
      const normalizedCurrent = normalizeReasoningModeValue(chat.reasoning_mode);
      const defaultMode = modes.includes(normalizedCurrent) ? normalizedCurrent : (modes[0] || "default");
      if (chat.reasoning_mode !== defaultMode) {
        chat.reasoning_mode = defaultMode;
        persistChatPrefs(chat);
      }
      modes.forEach((mode) => {
        const op = document.createElement("option");
        op.value = mode;
        op.textContent = REASONING_MODE_LABELS[mode] || mode;
        if (mode === chat.reasoning_mode) op.selected = true;
        reasoningModeSelect.appendChild(op);
      });
      if (reasoningModeFace) {
        reasoningModeFace.textContent = REASONING_MODE_LABELS[chat.reasoning_mode] || "";
      }
    }

    window.usePrompt = function(text) {
      userInput.value = text;
      sendMessage();
    };

    function distanceFromBottomPx(el) {
      return el.scrollHeight - el.scrollTop - el.clientHeight;
    }

    function maybeScrollToBottom() {
      if (!autoFollowBottom) return;
      chatFeed.scrollTop = chatFeed.scrollHeight;
      if (scrollToBottomBtn) scrollToBottomBtn.style.display = "none";
    }

    function scrollChatToBottomAndFollow() {
      autoFollowBottom = true;
      chatFeed.scrollTop = chatFeed.scrollHeight;
      if (scrollToBottomBtn) scrollToBottomBtn.style.display = "none";
    }

    function onChatFeedScroll() {
      if (chatFeed.scrollTop <= 24) {
        const chat = getActiveChat();
        if (chat && isDbConversationId(chat.id) && typeof loadOlderConversationMessagesFromDb === "function") {
          const beforeHeight = chatFeed.scrollHeight;
          loadOlderConversationMessagesFromDb(chat.id)
            .then((count) => {
              if (!count) return;
              updateWorkspace();
              chatFeed.scrollTop = chatFeed.scrollHeight - beforeHeight + 24;
            })
            .catch((e) => console.warn("[history] load older failed", e));
        }
      }
      const d = distanceFromBottomPx(chatFeed);
      if (d <= SCROLL_BOTTOM_THRESHOLD_PX) {
        autoFollowBottom = true;
        if (scrollToBottomBtn) scrollToBottomBtn.style.display = "none";
      } else {
        autoFollowBottom = false;
        if (scrollToBottomBtn) scrollToBottomBtn.style.display = "flex";
      }
    }

    function updateScrollBottomBtnOnly() {
      if (!scrollToBottomBtn) return;
      const d = distanceFromBottomPx(chatFeed);
      scrollToBottomBtn.style.display = d <= SCROLL_BOTTOM_THRESHOLD_PX ? "none" : "flex";
    }

    function findPrevUserMessageIndex(messages, assistantIndex) {
      for (let j = assistantIndex - 1; j >= 0; j--) {
        if (messages[j].role === "user") return j;
      }
      return -1;
    }

    function historyMessageToRequestItem(item) {
      const attachments = (item.attachments || [])
        .filter((a) => a && a.id)
        .map((a) => ({
          id: a.id,
          name: a.name,
          category: a.category,
        }));
      const hasGeneratedImageAttachment = (item.attachments || []).some(
        (a) => a && String(a.category || "") === "generated_image"
      );
      return {
        role: item.role,
        text: item.text || "",
        attachments,
        has_image_result: !!item.imageUrl || hasGeneratedImageAttachment,
      };
    }

    function buildHistoryBeforeUserIndex(chat, userIndex) {
      return chat.messages
        .slice(0, userIndex)
        .filter((m) => !m.pending)
        .slice(-RECENT_MESSAGES_LIMIT)
        .map(historyMessageToRequestItem);
    }

    function latestGeneratedImageAttachmentId(chat) {
      const messages = Array.isArray(chat && chat.messages) ? chat.messages : [];
      for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (!msg || msg.role !== "assistant") continue;
        const items = Array.isArray(msg.attachments) ? msg.attachments : [];
        const hit = items.find((a) => a && a.id && String(a.category || "") === "image");
        if (hit) return hit.id;
      }
      return "";
    }

    function classifyImageIntent(chat, text, explicitAttachmentIds) {
      const t = String(text || "").trim();
      const ids = Array.isArray(explicitAttachmentIds) ? explicitAttachmentIds.filter(Boolean) : [];
      const hasUploadedReference = ids.length > 0;
      const hasPreviousReference = !!latestGeneratedImageAttachmentId(chat);
      const noReferenceRe = /(不要参考|不参考|别参考|不用参考|无需参考|从零开始|重新开始|新建一张|新画一张|新生成一张|另起一张|重新画一张)/;
      const explicitPreviousRe = /(上一张|上张|这张|这幅|这张图|刚才|刚生成|刚刚|原图|参考图|参考上一|基于|沿用|继续|照着|按这个|用这张)/;
      const editRe = /(修改|改成|换成|变成|都变|全部变|替换|调整|优化|修一下|微调|保留|加上|添加|增加|去掉|删除|移除|放一个|放上|旁边|左边|右边|背景.*(改|换|替换)|把.*(改|换|变|替换|加|放|添|去掉|删除|移除)|不要.*(草地|背景|颜色|风格|元素))/;
      const variationRe = /(同款|类似|差不多|同风格|这个风格|换个风格|变体|再来一版|再出一版|升级版|更高级|更真实|更可爱|更精致)/;
      const newImageRe = /(重新|新建|新画|新生成|另外|另一个|换一个|生成一个|画一个|做一张|来一张)/;

      if (hasUploadedReference) {
        return {
          action: "edit_uploaded",
          use_previous_image: false,
          reference_source: "uploaded",
          confidence: 0.98,
          reason: "用户已上传参考图，优先使用本次上传图片。",
        };
      }

      if (!t) {
        return {
          action: "new_image",
          use_previous_image: false,
          reference_source: "none",
          confidence: 0.2,
          reason: "没有可判断的提示词。",
        };
      }

      if (noReferenceRe.test(t)) {
        return {
          action: "new_image",
          use_previous_image: false,
          reference_source: "none",
          confidence: 0.95,
          reason: "用户明确表示不参考旧图或从零开始。",
        };
      }

      if (hasPreviousReference && explicitPreviousRe.test(t)) {
        return {
          action: editRe.test(t) ? "edit_previous" : "variation",
          use_previous_image: true,
          reference_source: "previous_generated_image",
          confidence: 0.92,
          reason: "用户明确提到上一张或当前图片。",
        };
      }

      if (hasPreviousReference && editRe.test(t) && !newImageRe.test(t)) {
        return {
          action: "edit_previous",
          use_previous_image: true,
          reference_source: "previous_generated_image",
          confidence: 0.84,
          reason: "用户描述的是对现有画面的局部修改。",
        };
      }

      if (hasPreviousReference && variationRe.test(t) && !newImageRe.test(t)) {
        return {
          action: "variation",
          use_previous_image: true,
          reference_source: "previous_generated_image",
          confidence: 0.78,
          reason: "用户希望延续上一张图片做变体。",
        };
      }

      return {
        action: "new_image",
        use_previous_image: false,
        reference_source: "none",
        confidence: hasPreviousReference ? 0.7 : 0.9,
        reason: hasPreviousReference ? "未检测到明确沿用或修改上一张的意图。" : "当前没有可用的上一张参考图。",
      };
    }

    function shouldUsePreviousImageAsReference(text) {
      return classifyImageIntent(getActiveChat(), text, []).use_previous_image;
    }

    function imageIntentStatusText(intent) {
      const source = intent && intent.reference_source;
      if (source === "uploaded") return "已使用上传参考图，正在排队...";
      if (source === "previous_generated_image") return "已参考上一张图，正在排队...";
      return "本次从零生成，正在排队...";
    }

    let copyToastTimer = null;
    let copyToastFadeTimer = null;
    let copiedMsgButtonTimer = null;
    let copiedMsgButtonEl = null;

    function showCopyToast(message, opts) {
      const el = document.getElementById("copyToast");
      if (!el) return;
      const durationMs = (opts && opts.durationMs) || 2000;
      el.textContent = message || "";
      el.classList.remove("fade-out");
      void el.offsetWidth;
      el.classList.add("show");
      clearTimeout(copyToastTimer);
      clearTimeout(copyToastFadeTimer);
      copyToastTimer = setTimeout(() => {
        el.classList.add("fade-out");
        copyToastFadeTimer = setTimeout(() => {
          el.classList.remove("show", "fade-out");
          el.textContent = "";
        }, 360);
      }, durationMs);
    }

    function clearCopiedMsgButtonState() {
      if (!copiedMsgButtonEl) return;
      copiedMsgButtonEl.innerHTML = MSG_ICON_COPY_SVG;
      copiedMsgButtonEl.classList.remove("is-copied");
      copiedMsgButtonEl.setAttribute("aria-label", MSG_TOOLTIP_COPY);
      copiedMsgButtonEl = null;
    }

    function markMsgButtonCopied(btn) {
      if (!btn) return;
      clearTimeout(copiedMsgButtonTimer);
      clearCopiedMsgButtonState();
      copiedMsgButtonEl = btn;
      btn.innerHTML = MSG_ICON_CHECK_SVG;
      btn.classList.add("is-copied");
      btn.setAttribute("aria-label", "已复制");
      copiedMsgButtonTimer = setTimeout(() => {
        clearCopiedMsgButtonState();
      }, 1600);
    }

    function revertMsgButtonCopied(btn) {
      if (!btn) return;
      if (copiedMsgButtonEl === btn) {
        clearTimeout(copiedMsgButtonTimer);
        clearCopiedMsgButtonState();
        return;
      }
      btn.innerHTML = MSG_ICON_COPY_SVG;
      btn.classList.remove("is-copied");
      btn.setAttribute("aria-label", MSG_TOOLTIP_COPY);
    }

    function copyMessage(msgId, triggerBtn) {
      const chat = getActiveChat();
      const msg = (chat.messages || []).find((m) => m.id === msgId);
      if (!msg) return;
      let payload = (msg.text || "").trim();
      if (msg.role === "user") {
        if (!payload && msg.attachments && msg.attachments.length) {
          payload = msg.attachments.map((a) => a.name || "附件").filter(Boolean).join("\n");
        }
      } else {
        if (!payload && msg.imageUrl) payload = msg.imageUrl;
        if (!payload && msg.note) payload = (msg.note || "").trim();
      }
      if (!payload) {
        showCopyToast("暂无可复制内容", { durationMs: 1800 });
        return;
      }
      markMsgButtonCopied(triggerBtn);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(payload).then(
          () => {},
          () => {
            if (!copyTextWithLegacyFallback(payload)) {
              revertMsgButtonCopied(triggerBtn);
              showCopyToast("复制失败", { durationMs: 2000 });
            }
          }
        );
      } else if (!copyTextWithLegacyFallback(payload)) {
        revertMsgButtonCopied(triggerBtn);
        showCopyToast("当前环境不支持一键复制", { durationMs: 2200 });
      }
    }

    function copyTextWithLegacyFallback(text) {
      const ta = document.createElement("textarea");
      ta.value = text || "";
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      ta.style.top = "0";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, ta.value.length);
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(ta);
      return ok;
    }

    function createMsgIconButton(svgHtml, tooltipText, onClick, disabled, options) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "msg-action-btn";
      b.removeAttribute("title");
      b.setAttribute("aria-label", tooltipText);
      b.innerHTML = svgHtml;
      if (disabled) {
        b.disabled = true;
      }
      b.onclick = (e) => {
        e.stopPropagation();
        onClick(b);
      };
      if (!(options && options.skipTooltip)) {
        bindMsgActionTooltip(b, tooltipText);
      }
      return b;
    }

    let _msgTooltipEl = null;
    let _msgTooltipAnchor = null;
    let _msgTooltipShowTimer = null;
    let _msgTooltipHideTimer = null;
    let activeTaskCancel = null;

    function getMsgTooltipEl() {
      if (!_msgTooltipEl) {
        _msgTooltipEl = document.createElement("div");
        _msgTooltipEl.className = "msg-tooltip";
        _msgTooltipEl.setAttribute("role", "tooltip");
        document.body.appendChild(_msgTooltipEl);
      }
      return _msgTooltipEl;
    }

    function positionMsgTooltip(anchor, tip) {
      tip.style.display = "block";
      tip.style.left = "-9999px";
      tip.style.top = "0";
      tip.style.visibility = "hidden";
      const rect = anchor.getBoundingClientRect();
      const mw = tip.offsetWidth;
      const mh = tip.offsetHeight;
      const gap = 8;
      let left = rect.left + rect.width / 2 - mw / 2;
      let top = rect.bottom + gap;
      if (top + mh > window.innerHeight - 12) {
        top = rect.top - mh - gap;
      }
      if (top < 12) {
        top = rect.bottom + gap;
      }
      left = Math.max(12, Math.min(left, window.innerWidth - mw - 12));
      tip.style.left = Math.round(left) + "px";
      tip.style.top = Math.round(top) + "px";
      tip.style.visibility = "visible";
    }

    function hideMsgTooltip() {
      const el = _msgTooltipEl;
      if (!el) return;
      el.classList.remove("msg-tooltip--visible");
      _msgTooltipAnchor = null;
      clearTimeout(_msgTooltipHideTimer);
      _msgTooltipHideTimer = setTimeout(() => {
        el.textContent = "";
        el.style.display = "";
        el.style.left = "";
        el.style.top = "";
        el.style.visibility = "";
      }, 200);
    }

    /** 预留：若增加「编辑消息」图标，可 bindMsgActionTooltip(btn, MSG_TOOLTIP_EDIT) */
    function bindMsgActionTooltip(anchor, text) {
      if (!anchor || !text) return;
      anchor.removeAttribute("title");

      function onShow() {
        clearTimeout(_msgTooltipHideTimer);
        clearTimeout(_msgTooltipShowTimer);
        _msgTooltipShowTimer = setTimeout(() => {
          const tip = getMsgTooltipEl();
          tip.textContent = text;
          positionMsgTooltip(anchor, tip);
          tip.classList.add("msg-tooltip--visible");
          _msgTooltipAnchor = anchor;
        }, 115);
      }

      function onHide() {
        clearTimeout(_msgTooltipShowTimer);
        hideMsgTooltip();
      }

      anchor.addEventListener("mouseenter", onShow);
      anchor.addEventListener("mouseleave", onHide);
      anchor.addEventListener("focus", onShow);
      anchor.addEventListener("blur", onHide);
    }

    window.bindMsgActionTooltip = bindMsgActionTooltip;
    window.addEventListener(
      "scroll",
      () => {
        if (_msgTooltipAnchor) hideMsgTooltip();
      },
      true
    );
    window.addEventListener("resize", () => {
      if (_msgTooltipAnchor) hideMsgTooltip();
    });

    function regenerateAssistant(assistantMsgId) {
      clearNotice();
      const chat = getActiveChat();
      const aiIdx = chat.messages.findIndex((m) => m.id === assistantMsgId);
      if (aiIdx < 0) return;
      const asst = chat.messages[aiIdx];
      if (asst.role !== "assistant") return;
      if (asst.pending) {
        showError("请等待该条回复生成完成后再试。");
        return;
      }
      if (isStreaming) {
        showError("请等待当前生成结束后再试。");
        return;
      }

      const userIdx = findPrevUserMessageIndex(chat.messages, aiIdx);
      if (userIdx < 0) {
        showCopyToast("这条消息暂时无法重新生成", { durationMs: 2200 });
        return;
      }
      const userMsg = chat.messages[userIdx];
      const text = (userMsg.text || "").trim();
      let attachmentIds = (userMsg.attachments || []).map((a) => a.id).filter(Boolean);
      if (!text && !attachmentIds.length) {
        showCopyToast("这条消息暂时无法重新生成", { durationMs: 2200 });
        return;
      }

      const modelForRequest = asst.model || chat.model;
      if (!modelForRequest) {
        showError("请先选择模型。");
        return;
      }

      autoFollowBottom = true;

      chat.messages.splice(aiIdx);
      const pendingMsg = {
        id: "msg_pending_" + Date.now(),
        role: "assistant",
        text: "处理中...",
        rag_status: "",
        sources: [],
        progressSteps: [{ kind: "status", text: "正在准备请求", at: Date.now() }],
        pending: true,
        created_at: Date.now(),
      };
      chat.messages.push(pendingMsg);
      chat.pending = chat.messages.filter((m) => m.pending).length;
      chat.updatedAt = Date.now();
      saveState();
      void syncChatToOss(chat);
      updateSidebar();
      updateWorkspace();

      const requestHistory = buildHistoryBeforeUserIndex(chat, userIdx);
      const imageIntent =
        chat.tab === "image"
          ? classifyImageIntent(chat, text, attachmentIds)
          : null;
      if (chat.tab === "image" && imageIntent && imageIntent.use_previous_image && !attachmentIds.length) {
        const previousImageAttachmentId = latestGeneratedImageAttachmentId(chat);
        if (previousImageAttachmentId) attachmentIds = [previousImageAttachmentId];
      }

      if (chat.tab === "text") {
        const chatBody = {
          conversation_id: Number(chat.id),
          model: modelForRequest,
          reasoning_mode: chat.reasoning_mode || "default",
          prompt: text,
          system_prompt: "",
          use_rag: !!chat.use_rag,
          use_web_search: !!chat.use_web_search,
          attachment_ids: attachmentIds,
          history_messages: requestHistory,
        };
        sendTextViaSse(chatBody, pendingMsg, chat.id);
      } else {
        (async () => {
          try {
            if (modelSelect) {
              modelSelect.value = modelForRequest;
              syncModelSelectFace();
            }
            chat.model = modelForRequest;
            if (chat.tab === "image" && attachmentIds.length) {
              ensureImageEditModelForReferenceUse(chat, false);
              if (modelSelect) {
                modelSelect.value = chat.model;
                syncModelSelectFace();
              }
            }
            saveState();

            const body = {
              mode: chat.tab,
              model: chat.model,
              reasoning_mode: chat.reasoning_mode || "default",
              prompt: text,
              conversation_id: Number(chat.id),
              attachment_ids: attachmentIds,
              history_messages: requestHistory,
            };
            if (chat.tab === "image") {
              body.n = 1;
              body.image_intent = imageIntent ? imageIntent.action : "new_image";
              body.reference_source = imageIntent ? imageIntent.reference_source : "none";
              body.image_intent_confidence = imageIntent ? imageIntent.confidence : 0;
            }

            const resp = await historyFetch("/api/tasks", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(detailFromApiBody(data) || "任务提交失败");

            pendingMsg.taskId = data.task.id;
            pendingMsg.taskStartedAt = Date.now();
            pendingMsg.attachmentIds = attachmentIds;
            pendingMsg.text = chat.tab === "image" ? imageIntentStatusText(imageIntent) : "任务已提交后台排队...";
            scheduleTaskPoll(chat.id, pendingMsg.id, pendingMsg.taskId);
            setStreamingUI(isStreaming);
          } catch (err) {
            pendingMsg.pending = false;
            pendingMsg.error = true;
            pendingMsg.text = formatImageTaskErrorForUser(err && err.message ? err.message : "");
            setStreamingUI(isStreaming);
          }
          finishSend(chat.id);
        })();
      }
    }

        function renderUploadList(chat){
      uploadList.innerHTML = "";
      const items = chat.attachments || [];
        if (!items.length){
          uploadList.style.display = "none";
          syncComposerPresentation();
          return;
      }
      uploadList.style.display = "flex";
      items.forEach(item => {
        const chip = document.createElement("div");
        chip.className = `file-chip`;
        if (item.category === "image"){
          if (staleAttachmentIds.has(item.id)) {
            const span = document.createElement("span");
            span.className = "attachment-stale-label";
            span.textContent = "附件已失效";
            span.style.margin = "4px";
            chip.appendChild(span);
          } else {
            const thumb = document.createElement("img");
            thumb.className = "file-thumb";
            thumb.src = `/api/attachments/${item.id}`;
            bindAttachmentImageFallback(thumb, item.id);
            chip.appendChild(thumb);
          }
        } else {
          chip.innerHTML = `<div class="file-doc-icon">文档</div>`;
        }
        chip.insertAdjacentHTML("beforeend", `
          <div class="file-meta">
            <div class="file-name">${item.name}</div>
            <div class="file-type">已挂载</div>
          </div>
          <button class="file-remove" onclick="removeAttachment('${item.id}')">×</button>
        `);
        uploadList.appendChild(chip);
      });
      syncComposerPresentation();
    }

    window.removeAttachment = function(id){
      let chat = getActiveChat();
      chat.attachments = chat.attachments.filter(i => i.id !== id);
      saveState();
      renderUploadList(chat);
      if (chat.tab === "image") {
        ensureImageEditModelWhenReferenced(chat, { quiet: true });
        renderModelOptions(chat);
      }
    };

    function bindAttachmentImageFallback(img, attachmentId) {
      img.addEventListener(
        "error",
        function onAttImgErr() {
          img.removeEventListener("error", onAttImgErr);
          if (attachmentId) staleAttachmentIds.add(attachmentId);
          const span = document.createElement("span");
          span.className = "attachment-stale-label";
          span.textContent = "附件已失效";
          img.replaceWith(span);
        },
        { once: true }
      );
    }

    let infoNoticeHideTimer = null;
    let infoNoticeFadeEndTimer = null;

    /** opts 同 showError；不传则常驻（如「文件上传中…」） */
    function showInfo(msg, opts){
      const autoHideMs = opts && opts.autoHideMs;
      const fadeMs = opts && opts.fadeMs != null ? opts.fadeMs : 1500;

      clearTimeout(infoNoticeHideTimer);
      clearTimeout(infoNoticeFadeEndTimer);
      infoNoticeHideTimer = null;
      infoNoticeFadeEndTimer = null;
      clearTimeout(errorNoticeHideTimer);
      clearTimeout(errorNoticeFadeEndTimer);
      errorNoticeHideTimer = null;
      errorNoticeFadeEndTimer = null;

      infoNotice.textContent = msg || "";
      infoNotice.classList.remove("fade-out");
      errorNotice.className = "notice error";
      errorNotice.textContent = "";
      errorNotice.classList.remove("fade-out");
      void infoNotice.offsetWidth;
      infoNotice.className = "notice info show";

      if (autoHideMs != null && autoHideMs > 0) {
        infoNoticeHideTimer = setTimeout(() => {
          infoNotice.classList.add("fade-out");
          infoNoticeFadeEndTimer = setTimeout(() => {
            infoNotice.className = "notice info";
            infoNotice.textContent = "";
            infoNotice.classList.remove("fade-out");
          }, fadeMs);
        }, autoHideMs);
      }
    }

    let errorNoticeHideTimer = null;
    let errorNoticeFadeEndTimer = null;

    /** opts.autoHideMs：停留多久后开始淡出；opts.fadeMs：淡出时长（需与 .notice.error 的 transition 一致，默认 1500） */
    function showError(msg, opts){
      const autoHideMs = opts && opts.autoHideMs;
      const fadeMs = opts && opts.fadeMs != null ? opts.fadeMs : 1500;

      clearTimeout(errorNoticeHideTimer);
      clearTimeout(errorNoticeFadeEndTimer);
      errorNoticeHideTimer = null;
      errorNoticeFadeEndTimer = null;
      clearTimeout(infoNoticeHideTimer);
      clearTimeout(infoNoticeFadeEndTimer);
      infoNoticeHideTimer = null;
      infoNoticeFadeEndTimer = null;

      errorNotice.textContent = msg || "";
      errorNotice.classList.remove("fade-out");
      infoNotice.className = "notice info";
      infoNotice.textContent = "";
      infoNotice.classList.remove("fade-out");
      void errorNotice.offsetWidth;
      errorNotice.className = "notice error show";

      if (autoHideMs != null && autoHideMs > 0) {
        errorNoticeHideTimer = setTimeout(() => {
          errorNotice.classList.add("fade-out");
          errorNoticeFadeEndTimer = setTimeout(() => {
            errorNotice.className = "notice error";
            errorNotice.textContent = "";
            errorNotice.classList.remove("fade-out");
          }, fadeMs);
        }, autoHideMs);
      }
    }

    function clearNotice(){
      clearTimeout(errorNoticeHideTimer);
      clearTimeout(errorNoticeFadeEndTimer);
      clearTimeout(infoNoticeHideTimer);
      clearTimeout(infoNoticeFadeEndTimer);
      errorNoticeHideTimer = null;
      errorNoticeFadeEndTimer = null;
      infoNoticeHideTimer = null;
      infoNoticeFadeEndTimer = null;
      errorNotice.classList.remove("fade-out");
      infoNotice.classList.remove("fade-out");
      infoNotice.className = "notice info";
      errorNotice.className = "notice error";
    }

    const PASTE_IMAGE_MIME = new Set(["image/png", "image/jpeg", "image/jpg", "image/webp"]);

    function handleComposerPaste(e) {
      const chat = getActiveChat();
      if (chat.tab !== "text" && chat.tab !== "image") return;

      const items = e.clipboardData && e.clipboardData.items;
      if (!items || !items.length) return;

      const imageFiles = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind !== "file") continue;
        const mime = (item.type || "").toLowerCase();
        if (!PASTE_IMAGE_MIME.has(mime)) continue;
        const blob = item.getAsFile();
        if (!blob) continue;
        let name = (blob.name || "").trim();
        if (!name || name === "image.png" || name === "blob") {
          const ext = mime === "image/jpeg" || mime === "image/jpg" ? "jpg" : mime.split("/")[1] || "png";
          name = `粘贴图片_${Date.now()}.${ext}`;
        }
        imageFiles.push(new File([blob], name, { type: blob.type || mime }));
      }
      if (!imageFiles.length) return;
      e.preventDefault();
      e.stopPropagation();
      uploadSelectedFiles(imageFiles);
    }

    async function uploadSelectedFiles(fileList){
      const files = Array.from(fileList || []);
      if (!files.length) return;

      /** 上传开始时的会话 id；await 期间若切换会话，闭包里的 chat 会与新 active 不一致，必须把附件写回该 id 对应的对象。 */
      const uploadChatSnap = getActiveChat();
      const uploadChatId = uploadChatSnap.id;
      const uploadTab = uploadChatSnap.tab;

      const fd = new FormData();
      fd.append("mode", uploadTab);
      files.forEach(file => fd.append("files", file));

      showInfo("文件上传中...");
      try{
        const resp = await fetch("/api/upload", { method: "POST", body: fd });
        const data = await resp.json();
        if (!resp.ok) throw new Error(detailFromApiBody(data) || "上传失败");

        const chat = appState.chats.find((c) => c.id === uploadChatId);
        if (!chat) {
          showError("上传完成但该会话已不存在，请重新上传。");
          return;
        }
        chat.attachments = [...(chat.attachments || []), ...(data.attachments || [])];
        saveState();
        const addedImage = (data.attachments || []).some((a) => a.category === "image");
        const n = data.attachments.length;
        let editState = "ok";
        if (chat.tab === "image" && addedImage) {
          editState = ensureImageEditModelWhenReferenced(chat, { quiet: false });
        }
        if (appState.activeChatId === uploadChatId) {
          renderUploadList(chat);
          if (chat.tab === "image") renderModelOptions(chat);
        }
        if (editState === "switched") {
          showInfo(
            `已成功挂载 ${n} 个附件。当前已上传参考图，已自动切换到支持图生图的模型。`,
            { autoHideMs: 800, fadeMs: 1500 }
          );
        } else {
          showInfo(`已成功挂载 ${n} 个附件。`, { autoHideMs: 800, fadeMs: 1500 });
        }
      }catch(err){
        clearNotice();
        showError(err.message || "上传失败", { autoHideMs: 800, fadeMs: 1500 });
      } finally {
        fileInput.value = "";
      }
    }

    function setStreamingUI(streaming) {
      const chat = getActiveChat();
      const hasTaskPending =
        !!chat && (chat.messages || []).some((m) => !!m.pending && !!m.taskId);
      isStreaming = !!streaming;
      const stopBtn = document.getElementById("stopBtn");
      const sendBtn = document.getElementById("sendBtn");
      const busy = !!streaming || hasTaskPending;
      if (busy) {
        stopBtn.style.display = "block";
        sendBtn.disabled = true;
      } else {
        stopBtn.style.display = "none";
        sendBtn.disabled = false;
      }
    }

    function stopGeneration() {
      _userStopped = true;
      if (activeSseAbort) {
        try { activeSseAbort.abort(); } catch(e) {}
        activeSseAbort = null;
      }

      for (const msgId of Object.keys(_typewriterState)) {
        const tw = _typewriterState[msgId];
        if (tw) {
          tw.abort(tw.displayed + "\n\n（已停止生成）", null);
        }
      }

      stopActiveTaskGeneration();
      setStreamingUI(false);
    }

    async function stopActiveTaskGeneration() {
      const chat = getActiveChat();
      if (!chat) return;
      const pendingTasks = (chat.messages || []).filter((m) => m.pending && m.taskId);
      if (!pendingTasks.length) return;
      activeTaskCancel = { chatId: chat.id, taskIds: pendingTasks.map((m) => m.taskId) };
      for (const msg of pendingTasks) {
        msg.pending = false;
        msg.error = true;
        msg.text = "已停止生成。";
        msg._taskPollSig = "";
        msg.taskStatus = undefined;
        try {
          await historyFetch(`/api/tasks/${msg.taskId}/cancel`, { method: "POST" });
        } catch (e) {}
      }
      chat.pending = chat.messages.filter((m) => m.pending).length;
      chat.updatedAt = Date.now();
      saveState();
      void syncChatToOss(chat);
      updateSidebar();
      updateWorkspace();
      activeTaskCancel = null;
    }

    const _typewriterState = {};
    const TYPEWRITER_INTERVAL_MS = 30;

    function _ensureTypewriter(msgId, pendingMsg) {
      if (_typewriterState[msgId]) return _typewriterState[msgId];
      const state = { queue: "", displayed: "", timer: null, done: false, onFinish: null };
      _typewriterState[msgId] = state;

      function tick() {
        if (state.queue.length > 0) {
          const char = state.queue[0];
          state.queue = state.queue.slice(1);
          state.displayed += char;
          pendingMsg.text = state.displayed;
          _renderBubbleText(msgId, pendingMsg);
          state.timer = setTimeout(tick, TYPEWRITER_INTERVAL_MS);
        } else if (state.done) {
          state.timer = null;
          delete _typewriterState[msgId];
          _renderBubbleText(msgId, pendingMsg);
          if (state.onFinish) state.onFinish();
        } else {
          state.timer = null;
        }
      }

      state.push = function(text) {
        state.queue += text;
        if (!state.timer) { state.timer = setTimeout(tick, TYPEWRITER_INTERVAL_MS); }
      };

      state.flush = function(cb) {
        state.done = true;
        state.onFinish = cb;
        if (!state.timer && state.queue.length === 0) {
          delete _typewriterState[msgId];
          if (cb) cb();
        } else if (!state.timer) {
          state.timer = setTimeout(tick, TYPEWRITER_INTERVAL_MS);
        }
      };

      state.abort = function(finalText, cb) {
        if (state.timer) { clearTimeout(state.timer); state.timer = null; }
        state.queue = "";
        state.displayed = finalText;
        pendingMsg.text = finalText;
        delete _typewriterState[msgId];
        _renderBubbleText(msgId, pendingMsg);
        if (cb) cb();
      };

      return state;
    }

    async function sendTextViaSse(chatBody, pendingMsg, chatId) {
      _userStopped = false;
      const ac = new AbortController();
      activeSseAbort = ac;
      setStreamingUI(true);
      let fullText = "";
      let streamCompleted = false;

      const applyAssistantMeta = (data) => {
        const prevMsgId = pendingMsg.id;
        if (data.message_id != null && data.message_id !== "") {
          pendingMsg.id = String(data.message_id);
        }
        if (data.image_url) pendingMsg.imageUrl = data.image_url;
        pendingMsg.rag_status = data.rag_status || "";
        pendingMsg.note = ragStatusNote(pendingMsg.rag_status, data.note || "");
        if (Array.isArray(data.sources)) pendingMsg.sources = data.sources;
        const c = appState.chats.find((x) => x.id === chatId);
        if (c) {
          pendingMsg.model = c.model;
          pendingMsg.image_mode = c.image_mode || null;
        }
        if (String(prevMsgId || "") !== String(pendingMsg.id || "")) {
          replaceMessageUiStateKey(chatId, prevMsgId, pendingMsg.id, pendingMsg);
        } else {
          persistMessageUiState(chatId, pendingMsg);
        }
      };

      try {
        const resp = await historyFetch("/api/chat/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify(chatBody),
          signal: ac.signal,
        });
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          throw new Error(detailFromApiBody(data) || resp.statusText || "请求失败");
        }
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let sep;
          while ((sep = buf.indexOf("\n\n")) !== -1) {
            const rawEvent = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            let dataLine = null;
            for (const line of rawEvent.split("\n")) {
              if (line.startsWith("data:")) {
                dataLine = line.slice(5).trimStart();
                break;
              }
            }
            if (dataLine === null || dataLine === "") continue;
            let data;
            try { data = JSON.parse(dataLine); } catch { continue; }
            if (data.type === "token") {
              fullText += data.text;
              const tw = _ensureTypewriter(pendingMsg.id, pendingMsg);
              tw.push(data.text);
            } else if (data.type === "status" || data.type === "search" || data.type === "reasoning") {
              pushProgressStep(pendingMsg, data.type, data.text);
              if (!fullText) {
                const last = pendingMsg.progressSteps[pendingMsg.progressSteps.length - 1];
                pendingMsg.text = last ? last.text : "处理中...";
              }
              updatePendingBubble(pendingMsg);
            } else if (data.type === "done") {
              streamCompleted = true;
              const finalText = finalizeAssistantVisibleContent(pendingMsg, data.content || fullText || "未返回内容");
              applyAssistantMeta(data);
              const tw = _typewriterState[pendingMsg.id];
              if (tw) {
                tw.abort(finalText, () => {
                  pendingMsg.pending = false;
                  finishSend(chatId);
                });
              } else {
                pendingMsg.pending = false;
                pendingMsg.text = finalText;
                updatePendingBubble(pendingMsg);
                finishSend(chatId);
              }
            } else if (data.type === "stopped") {
              streamCompleted = true;
              const finalText = finalizeAssistantVisibleContent(pendingMsg, data.content || fullText || "") + "\n\n（已停止生成）";
              applyAssistantMeta(data);
              const tw = _typewriterState[pendingMsg.id];
              if (tw) {
                tw.abort(finalText, () => {
                  pendingMsg.pending = false;
                  finishSend(chatId);
                });
              } else {
                pendingMsg.pending = false;
                pendingMsg.text = finalText;
                updatePendingBubble(pendingMsg);
                finishSend(chatId);
              }
            } else if (data.type === "error") {
              streamCompleted = true;
              const tw = _typewriterState[pendingMsg.id];
              if (tw) { tw.abort("", null); }
              pendingMsg.pending = false;
              pendingMsg.error = true;
              pendingMsg.text = data.detail || "请求失败";
              updatePendingBubble(pendingMsg);
              finishSend(chatId);
            }
          }
        }
      } catch (err) {
        if (pendingMsg.pending && err && err.name === "AbortError" && _userStopped) {
          _userStopped = false;
          pendingMsg.pending = false;
          finishSend(chatId);
          return;
        }
        if (pendingMsg.pending) {
          fallbackToHttp(chatBody, pendingMsg, chatId);
          return;
        }
      } finally {
        activeSseAbort = null;
        setStreamingUI(false);
      }

      if (!streamCompleted && pendingMsg.pending) {
        fallbackToHttp(chatBody, pendingMsg, chatId);
      }
    }

    async function fallbackToHttp(chatBody, pendingMsg, chatId) {
      try {
        const resp = await fetch("/api/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(chatBody)
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(detailFromApiBody(data) || data.message || "请求失败");
        pendingMsg.pending = false;
        pendingMsg.text = data.content || "未返回内容";
        const prevMsgId = pendingMsg.id;
        if (data.message_id != null && data.message_id !== "") {
          pendingMsg.id = String(data.message_id);
        }
        if (data.image_url) pendingMsg.imageUrl = data.image_url;
        pendingMsg.rag_status = data.rag_status || "";
        pendingMsg.note = ragStatusNote(pendingMsg.rag_status, data.note || "");
        if (Array.isArray(data.sources)) pendingMsg.sources = data.sources;
        const c = appState.chats.find((x) => x.id === chatId);
        if (c) {
          pendingMsg.model = c.model;
          pendingMsg.image_mode = c.image_mode || null;
        }
        if (String(prevMsgId || "") !== String(pendingMsg.id || "")) {
          replaceMessageUiStateKey(chatId, prevMsgId, pendingMsg.id, pendingMsg);
        } else {
          persistMessageUiState(chatId, pendingMsg);
        }
      } catch(err) {
        pendingMsg.pending = false;
        pendingMsg.error = true;
        pendingMsg.text = err.message || "请求异常";
      }
      finishSend(chatId);
    }

    function latestArtifactTypeForChat(chat) {
      const messages = Array.isArray(chat && chat.messages) ? chat.messages : [];
      for (let i = messages.length - 1; i >= 0; i -= 1) {
        const msg = messages[i] || {};
        if (String(msg.role || "") !== "assistant") continue;
        const direct = String(msg.artifactType || "").trim().toLowerCase();
        if (direct === "docx" || direct === "xlsx" || direct === "pptx" || direct === "pdf" || direct === "txt" || direct === "md" || direct === "csv") return direct;
        const text = String(msg.text || "").toLowerCase();
        if (!text) continue;
        if (text.includes(".pptx") || text.includes("ppt演示文稿")) return "pptx";
        if (text.includes(".xlsx") || text.includes("excel 文件")) return "xlsx";
        if (text.includes(".pdf") || text.includes("pdf 文档")) return "pdf";
        if (text.includes(".csv") || text.includes("csv 文件")) return "csv";
        if (text.includes(".md") || text.includes("markdown 文件")) return "md";
        if (text.includes(".txt") || text.includes("txt 文本文件")) return "txt";
        if (text.includes(".docx") || text.includes("word 文档")) return "docx";
      }
      return null;
    }

    function shouldFollowArtifactContext(text) {
      const normalized = String(text || "").trim();
      if (!normalized) return false;
      const genericRetryOnly = /^(重新|重来|重答|重新回答|重新生成|再来|再生成|换一个|换个|不满意.*重|不满意.*再|重新来一版|再来一版)[。.!！?？\s]*$/i;
      if (genericRetryOnly.test(normalized)) return false;
      const discussionLikeWords = /(了解|介绍|讲讲|说说|解释|是什么|什么意思|功能|能力|支持|日报|周报|月报|今天做了什么|完成了|已完成|已经完成|实现了|可以生成)/i;
      if (discussionLikeWords.test(normalized)) return false;
      const directArtifactWords = /(word|docx|excel|xlsx|ppt|pptx|pdf|txt|markdown|md|csv|演示文稿|幻灯片|表格|文档|文本文件)/i;
      if (directArtifactWords.test(normalized)) return false;
      return /(修改后|更新后|加上|补上|改成|调整|优化|换成|转成|变成|转为)/.test(normalized);
    }

    function maybePromoteArtifactFollowupIntent(chat, text, intent) {
      if (intent && intent.should_use_task) return intent;
      if (!shouldFollowArtifactContext(text)) return intent;
      const artifactType = latestArtifactTypeForChat(chat);
      if (!artifactType) return intent;
      return {
        output_mode: artifactType,
        confidence: 0.72,
        should_use_task: true,
        artifact_type: artifactType,
        reason: "沿用当前会话最近一次文件生成类型",
      };
    }

    function isCapabilityQuestionText(text) {
      const normalized = String(text || "").trim();
      return /(能不能|能否|可以吗|可不可以|能帮我|可以帮我|能不能帮我|是否可以|会不会|支持不支持|能不能够|可否).{0,40}(生成|做|制作|导出|转成|转为|写|创建)/i.test(normalized);
    }

    async function requestOutputIntent(prompt) {
      try {
        const resp = await fetch("/api/output-intent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt: prompt || "",
            mode: "text",
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(detailFromApiBody(data) || "识别失败");
        return data || {};
      } catch (e) {
        return {
          output_mode: "chat",
          confidence: 0,
          should_use_task: false,
          artifact_type: null,
          reason: e && e.message ? e.message : "识别失败，回落普通聊天",
        };
      }
    }

    async function submitArtifactTask(chat, pendingMsg, userMsg, requestHistory, intent) {
      const attachmentIds = (userMsg.attachments || []).map((i) => i.id).filter(Boolean);
      const body = {
        mode: "artifact",
        artifact_type: intent.artifact_type,
        conversation_id: Number(chat.id),
        model: chat.model,
        reasoning_mode: chat.reasoning_mode || "default",
        prompt: userMsg.text || "",
        attachment_ids: attachmentIds,
        history_messages: requestHistory,
        use_rag: !!chat.use_rag,
        use_web_search: !!chat.use_web_search,
      };
      const displayLabel =
        intent.artifact_type === "txt"
          ? "TXT 文本文件"
          : intent.artifact_type === "md"
          ? "Markdown 文件"
          : intent.artifact_type === "csv"
          ? "CSV 文件"
          :
        intent.artifact_type === "xlsx"
          ? "Excel 文件"
          : intent.artifact_type === "pptx"
          ? "PPT 演示文稿"
          : intent.artifact_type === "pdf"
          ? "PDF 文档"
          : "Word 文档";
      pendingMsg.text = `正在生成${displayLabel}…`;
      pendingMsg.taskKind = "artifact";
      pendingMsg.artifactType = intent.artifact_type || null;
      updateWorkspace();

      try {
        const resp = await historyFetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(detailFromApiBody(data) || "任务提交失败");

        const prevMsgId = pendingMsg.id;
        pendingMsg.taskId = data.task.id;
        pendingMsg.taskKind = data.task.mode || "artifact";
        pendingMsg.artifactType = data.task.artifact_type || intent.artifact_type || null;
        pendingMsg.text = data.task.progress_text || pendingMsg.text;
        if (data.task.message_id != null && data.task.message_id !== "") {
          pendingMsg.id = String(data.task.message_id);
          replaceMessageUiStateKey(chat.id, prevMsgId, pendingMsg.id, pendingMsg);
        } else {
          persistMessageUiState(chat.id, pendingMsg);
        }
        scheduleTaskPoll(chat.id, pendingMsg.id, pendingMsg.taskId);
      } catch (err) {
        pendingMsg.pending = false;
        pendingMsg.error = true;
        pendingMsg.text = (err && err.message) || "文件任务提交失败";
      }
      finishSend(chat.id);
    }

    function finishSend(chatId) {
      const chat = appState.chats.find(c => c.id === chatId);
      if (!chat) return;
      chat.pending = chat.messages.filter(m => m.pending).length;
      chat.updatedAt = Date.now();
      saveState();
      void syncChatToOss(chat);
      updateSidebar();
      updateWorkspace();
      setStreamingUI(isStreaming);
    }

    async function sendMessage(){
      clearNotice();
      const chat = getActiveChat();
      const text = userInput.value.trim();

      if (!chat.model) { showError("请先选择模型。"); return; }
      if (chat.tab === "text" && !allowedTextModelIds().has(String(chat.model || ""))) {
        showError("当前模型不在白名单中，请重新选择。");
        return;
      }
      if (!text && !(chat.attachments || []).length) {
        showError("请输入内容，或先上传文件。", { autoHideMs: 800, fadeMs: 1500 });
        return;
      }
      if (isStreaming) { return; }

      autoFollowBottom = true;

      const priorUserCount = chat.messages.filter((m) => m.role === "user").length;
      if (priorUserCount === 0 && text) {
        chat.title = text.substring(0, 20);
      }

      const userMsg = {
        id: "msg_" + Date.now(),
        role: "user",
        text,
        attachments: [...(chat.attachments || [])],
        created_at: Date.now(),
      };
      userMsg.image_mode =
        chat.tab === "image" || (chat.tab === "text" && userMsg.attachments.some((a) => a.category === "image"))
          ? (chat.image_mode != null && chat.image_mode !== "" ? chat.image_mode : null)
          : null;

      const pendingMsg = {
        id: "msg_pending_" + Date.now(),
        role: "assistant",
        text: "处理中...",
        rag_status: "",
        sources: [],
        progressSteps: [{ kind: "status", text: "正在准备请求", at: Date.now() }],
        pending: true,
        created_at: Date.now(),
      };

      chat.messages.push(userMsg, pendingMsg);
      chat.pending = (chat.pending || 0) + 1;
      chat.draft = "";
      chat.attachments = [];
      chat.updatedAt = Date.now();
      saveState();
      void syncChatToOss(chat);
      updateSidebar();
      updateWorkspace();

      userInput.value = "";
      renderUploadList(chat);

      const requestHistory = chat.messages
        .filter((m) => !m.pending)
        .slice(-RECENT_MESSAGES_LIMIT)
        .map(historyMessageToRequestItem)
        .slice(0, -1);

      let attachmentIds = userMsg.attachments.map((i) => i.id).filter(Boolean);
      const imageIntent =
        chat.tab === "image"
          ? classifyImageIntent(chat, text, attachmentIds)
          : null;
      if (chat.tab === "image" && !attachmentIds.length && imageIntent && imageIntent.use_previous_image) {
        const previousImageAttachmentId = latestGeneratedImageAttachmentId(chat);
        if (previousImageAttachmentId) {
          attachmentIds = [previousImageAttachmentId];
        }
      }
      if (chat.tab === "image") {
        pendingMsg.attachmentIds = attachmentIds;
      }
      if (!isDbConversationId(chat.id)) {
        showError("当前会话未绑定数据库 id，请重新新建会话后再试。");
        pendingMsg.pending = false;
        pendingMsg.error = true;
        pendingMsg.text = "当前会话未绑定数据库 id，请重新新建会话后再试。";
        finishSend(chat.id);
        return;
      }

      if (chat.tab === "image" && modelSelect && modelSelect.value) {
        chat.model = modelSelect.value;
        if (attachmentIds.length) {
          ensureImageEditModelForReferenceUse(chat, false);
          if (modelSelect) modelSelect.value = chat.model;
          syncModelSelectFace();
        }
        persistChatPrefs(chat);
        saveState();
      }

      if (chat.tab === "text") {
        const rawIntent = await requestOutputIntent(text);
        const intent = isCapabilityQuestionText(text)
          ? { output_mode: "chat", confidence: 0, should_use_task: false, artifact_type: null, reason: "能力询问，走普通聊天" }
          : maybePromoteArtifactFollowupIntent(chat, text, rawIntent);
        if (intent && intent.should_use_task && (intent.artifact_type === "docx" || intent.artifact_type === "xlsx" || intent.artifact_type === "pptx" || intent.artifact_type === "pdf" || intent.artifact_type === "txt" || intent.artifact_type === "md" || intent.artifact_type === "csv")) {
          await submitArtifactTask(chat, pendingMsg, userMsg, requestHistory, intent);
        } else {
          const chatBody = {
            conversation_id: Number(chat.id),
            model: chat.model,
            reasoning_mode: chat.reasoning_mode || "default",
            prompt: text,
            system_prompt: intent && intent.output_mode === "markdown_table" ? MARKDOWN_TABLE_SYSTEM_PROMPT : "",
            use_rag: !!chat.use_rag,
            use_web_search: !!chat.use_web_search,
            attachment_ids: attachmentIds,
            history_messages: requestHistory,
          };
          console.info("[huairen send]", {
            tab: chat.tab,
            model: chatBody.model,
            attachment_ids: attachmentIds,
            output_mode: intent && intent.output_mode ? intent.output_mode : "chat",
          });
          sendTextViaSse(chatBody, pendingMsg, chat.id);
        }
      } else {
        try {
          const body = {
            mode: chat.tab,
            model: chat.model,
            reasoning_mode: chat.reasoning_mode || "default",
            prompt: text,
            conversation_id: Number(chat.id),
            attachment_ids: attachmentIds,
            history_messages: requestHistory,
          };
          if (chat.tab === "image") {
            body.n = 1;
            body.image_intent = imageIntent ? imageIntent.action : "new_image";
            body.reference_source = imageIntent ? imageIntent.reference_source : "none";
            body.image_intent_confidence = imageIntent ? imageIntent.confidence : 0;
          }

          console.info("[huairen /api/tasks preflight]", {
            activeChatId: chat.id,
            currentModel: body.model,
            modelSelectValue: modelSelect ? modelSelect.value : "",
            userMsgAttachments: (userMsg.attachments || []).map((a) => ({
              id: a.id,
              name: a.name,
              category: a.category,
            })),
            attachment_ids: attachmentIds,
            requestBodyAttachmentIds: body.attachment_ids,
          });

          console.info("[huairen send]", {
            tab: chat.tab,
            model: body.model,
            attachment_ids: attachmentIds,
          });

          const resp = await historyFetch("/api/tasks", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
          });
          const data = await resp.json().catch(() => ({}));
          if(!resp.ok) throw new Error(detailFromApiBody(data) || "任务提交失败");

          pendingMsg.taskId = data.task.id;
          pendingMsg.taskStartedAt = Date.now();
          pendingMsg.attachmentIds = attachmentIds;
          pendingMsg.text = chat.tab === "image" ? imageIntentStatusText(imageIntent) : "任务已提交后台排队...";
          scheduleTaskPoll(chat.id, pendingMsg.id, pendingMsg.taskId);
          setStreamingUI(isStreaming);
        } catch(err) {
          pendingMsg.pending = false;
          pendingMsg.error = true;
          pendingMsg.text = formatImageTaskErrorForUser(err && err.message ? err.message : "");
          setStreamingUI(isStreaming);
        }
        finishSend(chat.id);
      }
    }

    async function pollTaskStatus(chatId, messageId, taskId){
      const chat = appState.chats.find(c => c.id === chatId);
      if(!chat) return;
      const msg = chat.messages.find(m => m.id === messageId);
      if(!msg || !msg.pending) return;
      if (activeTaskCancel && activeTaskCancel.chatId === chatId && activeTaskCancel.taskIds.includes(taskId)) return;
      try {
        const resp = await historyFetch(`/api/tasks/${taskId}`);
        const data = await resp.json().catch(() => ({}));
        if(!resp.ok) throw new Error(detailFromApiBody(data) || "查询失败");

        const task = data.task || {};
        const taskStartedAt =
          parseApiDateTimeMs(task.started_at) ||
          parseApiDateTimeMs(task.created_at) ||
          Number(msg.taskStartedAt || 0) ||
          Date.now();
        msg.taskStartedAt = taskStartedAt;
        const hasImageRefs =
          chat.tab === "image" &&
          (
            (Array.isArray(msg.attachmentIds) && msg.attachmentIds.length) ||
            (Array.isArray(task.attachment_ids) && task.attachment_ids.length) ||
            task.reference_source === "uploaded" ||
            task.reference_source === "previous_generated_image"
          );
        const timeoutMs = hasImageRefs ? IMAGE_EDIT_TASK_CLIENT_TIMEOUT_MS : IMAGE_TASK_CLIENT_TIMEOUT_MS;
        if (
          (task.status === "queued" || task.status === "running") &&
          Date.now() - taskStartedAt > timeoutMs
        ) {
          msg._taskPollSig = "";
          msg.taskStatus = undefined;
          msg.pending = false;
          msg.error = true;
          msg.text = formatImageTaskErrorForUser("timeout");
          try {
            await historyFetch(`/api/tasks/${taskId}/cancel`, { method: "POST" });
          } catch (e) {}
          chat.pending = chat.messages.filter((m) => m.pending).length;
          chat.updatedAt = Date.now();
          saveState();
          void syncChatToOss(chat);
          updateSidebar();
          if (appState.activeChatId === chatId) {
            if (!patchTaskMessageDom(msg, chat)) updateWorkspace();
            else updateScrollBottomBtnOnly();
          }
          return;
        }
        msg.taskKind = task.mode || msg.taskKind;
        msg.artifactType = task.artifact_type || msg.artifactType;
        if(task.status === "queued" || task.status === "running"){
          const display =
            (task.progress_text && String(task.progress_text).trim()) ||
            (task.mode === "artifact"
              ? (
                  task.artifact_type === "xlsx"
                    ? "正在生成 Excel 文件…"
                    : task.artifact_type === "pptx"
                    ? "正在生成 PPT 演示文稿…"
                    : task.artifact_type === "pdf"
                    ? "正在生成 PDF 文档…"
                    : task.artifact_type === "txt"
                    ? "正在生成 TXT 文本文件…"
                    : task.artifact_type === "md"
                    ? "正在生成 Markdown 文件…"
                    : task.artifact_type === "csv"
                    ? "正在生成 CSV 文件…"
                    : "正在生成 Word 文档…"
                )
              : (task.status === "queued" ? "任务排队中…" : "正在生成图片…"));
          const sig = `${task.status}|${display}`;
          if (msg._taskPollSig === sig) {
            scheduleTaskPoll(chatId, messageId, taskId);
            if (appState.activeChatId === chatId) {
              setStreamingUI(isStreaming);
              updateScrollBottomBtnOnly();
            }
            return;
          }
          msg._taskPollSig = sig;
          msg.taskStatus = task.status;
          msg.text = display;
          chat.updatedAt = Date.now();
          scheduleTaskPoll(chatId, messageId, taskId);
          saveState();
          void syncChatToOss(chat);
          if (appState.activeChatId === chatId) {
            if (patchTaskMessageDom(msg, chat)) updateScrollBottomBtnOnly();
            else updateWorkspace();
            setStreamingUI(isStreaming);
          }
          return;
        }

        msg._taskPollSig = "";
        msg.taskStatus = undefined;

        if(task.status === "succeeded"){
           msg.pending = false;
           msg.text = task.result.text || "完成";
           msg.imageUrl = task.result.image_url;
           if (task.result.attachment && task.result.attachment.id) {
             msg.attachments = [{
               id: task.result.attachment.id,
               name: task.result.attachment.name || "生成图片",
               category: task.result.attachment.category || "image",
             }];
           }
           msg.rag_status = task.result.rag_status || "";
           msg.note = ragStatusNote(msg.rag_status, task.result.note || "");
           msg.sources = Array.isArray(task.result.sources) ? task.result.sources : [];
           msg.model = chat.model;
           msg.image_mode = chat.image_mode || null;
        } else if (task.status === "cancelled") {
           msg.pending = false;
           msg.error = true;
           msg.text = "已停止生成。";
        } else {
           msg.pending = false; msg.error = true;
           const rawHint = [task.error_message, detailFromApiBody(data)].filter(Boolean).join("\n");
           msg.text =
             task.mode === "artifact"
               ? formatArtifactTaskErrorForUser(rawHint)
               : formatImageTaskErrorForUser(rawHint);
        }
      }catch(err){
        msg._taskPollSig = "";
        msg.taskStatus = undefined;
        msg.pending = false; msg.error = true;
        msg.text = formatImageTaskErrorForUser(err && err.message ? err.message : "");
      }

      chat.pending = chat.messages.filter(m=>m.pending).length;
      chat.updatedAt = Date.now();
      saveState();
      void syncChatToOss(chat);
      updateSidebar();

      if(appState.activeChatId === chatId) {
        if (!patchTaskMessageDom(msg, chat)) {
          updateWorkspace();
        } else {
          if (autoFollowBottom) maybeScrollToBottom();
          updateScrollBottomBtnOnly();
        }
        setStreamingUI(isStreaming);
      }
    }

    function scheduleTaskPoll(chatId, messageId, taskId){
      setTimeout(() => pollTaskStatus(chatId, messageId, taskId), TASK_POLL_INTERVAL_MS);
    }

    function reviveTaskPollers(){
      appState.chats.forEach(chat => {
        chat.messages.forEach(msg => {
          if (msg.pending && msg.taskId) scheduleTaskPoll(chat.id, msg.id, msg.taskId);
        });
        chat.pending = chat.messages.filter(m=>m.pending).length;
      });
      saveState();
      updateSidebar();
      setStreamingUI(isStreaming);
    }

    loginBtn.onclick = async () => {
      loginError.className = "login-error";
      try{
        const resp = await fetch("/api/auth/login", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            username: (usernameInput && usernameInput.value ? usernameInput.value : "admin").trim(),
            password: passwordInput.value,
          })
        });
        const data = await resp.json().catch(() => ({}));
        if(!resp.ok) throw new Error(detailFromApiBody(data) || "用户名或密码错误");
        isAuthenticated = true;
        renderCurrentUser(data.user);
        showAppShell();
        await initApp();
      }catch(e){
        loginError.textContent = e.message; loginError.className = "login-error show";
      }
    };

    async function handleLogout() {
      if (isStreaming && activeSseAbort) {
        try {
          _userStopped = true;
          activeSseAbort.abort();
        } catch (e) {}
      }
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } catch (e) {}

      isAuthenticated = false;
      renderCurrentUser(null);
      appState = defaultAppState();
      appState.currentTab = normalizeChatTab(localStorage.getItem(LS_CURRENT_TAB) || "text");
      appState.activeChatId = null;
      appState.chats = [];
      if (passwordInput) passwordInput.value = "";
      if (loginError) loginError.className = "login-error";
      showLoginOnly();
    }

    if (logoutBtn) {
      logoutBtn.onclick = () => void handleLogout();
    }

    if (usernameInput) {
      usernameInput.addEventListener("compositionstart", () => { loginInputComposing = true; });
      usernameInput.addEventListener("compositionend", () => { loginInputComposing = false; });
    }
    if (passwordInput) {
      passwordInput.addEventListener("compositionstart", () => { loginInputComposing = true; });
      passwordInput.addEventListener("compositionend", () => { loginInputComposing = false; });
    }
    passwordInput.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      if (e.isComposing || loginInputComposing || e.keyCode === 229) return;
      loginBtn.onclick();
    };
    if (usernameInput) {
      usernameInput.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        if (e.isComposing || loginInputComposing || e.keyCode === 229) return;
        loginBtn.onclick();
      };
    }

    tabButtons.forEach((btn) => (btn.onclick = () => void switchTab(btn.dataset.tab)));
    newChatBtn.onclick = () => void handleNewChat();
    clearChatsBtn.onclick = () => {
      if (confirm("清空当前模式下的所有对话？")) void clearCurrentTabChats();
    };
    if (chatTitle) {
      chatTitle.ondblclick = () => {
        const chat = getActiveChat();
        if (chat) void renameChat(chat.id);
      };
      chatTitle.title = "双击可重命名当前会话";
    }
    modelSelect.onchange = () => {
      const chat = getActiveChat();
      chat.model = modelSelect.value;
      persistChatPrefs(chat);
      saveState();
      syncModelSelectFace();
      renderReasoningModeOptions(chat);
    };
    if (reasoningModeSelect) {
      reasoningModeSelect.onchange = () => {
        const chat = getActiveChat();
        chat.reasoning_mode = normalizeReasoningModeValue(reasoningModeSelect.value);
        if (reasoningModeFace) {
          reasoningModeFace.textContent = REASONING_MODE_LABELS[chat.reasoning_mode] || "";
        }
        persistChatPrefs(chat);
        saveState();
      };
    }
    if (useRagCb) {
      useRagCb.onchange = () => {
        const chat = getActiveChat();
        chat.use_rag = !!useRagCb.checked && chat.tab === "text";
        persistChatPrefs(chat);
        saveState();
      };
    }
    if (useWebSearchCb) {
      useWebSearchCb.onchange = () => {
        const chat = getActiveChat();
        chat.use_web_search = !!useWebSearchCb.checked && chat.tab === "text";
        persistChatPrefs(chat);
        saveState();
      };
    }
    if (showAllImageModelsCb) {
      showAllImageModelsCb.onchange = () => {
        showAllImageModels = !!showAllImageModelsCb.checked;
        renderModelOptions(getActiveChat());
      };
    }
    userInput.oninput = () => {
      const chat = getActiveChat();
      if (!chat) return;
      chat.draft = userInput.value;
      saveState();
      syncComposerPresentation();
    };
    userInput.addEventListener("compositionstart", () => { inputComposing = true; });
    userInput.addEventListener("compositionend", () => { inputComposing = false; });
    userInput.addEventListener("focus", () => { syncComposerPresentation(); });
    userInput.addEventListener("blur", () => { setTimeout(syncComposerPresentation, 0); });
    userInput.onkeydown = (e) => {
      if (e.key !== "Enter" || e.shiftKey) return;
      if (e.isComposing || inputComposing || e.keyCode === 229) return;
      e.preventDefault();
      sendMessage();
    };
    if (chatFeed) chatFeed.addEventListener("scroll", onChatFeedScroll, { passive: true });
    if (scrollToBottomBtn) scrollToBottomBtn.onclick = () => scrollChatToBottomAndFollow();
    if (scrollToBottomBtn) bindMsgActionTooltip(scrollToBottomBtn, "回到底部");
    sendBtn.onclick = sendMessage;
    document.getElementById("stopBtn").onclick = stopGeneration;
    attachBtn.onclick = () => fileInput.click();
    fileInput.onchange = (e) => uploadSelectedFiles(e.target.files);
    chatWrap.addEventListener("paste", handleComposerPaste, true);

    uploadDropZone.ondragover = (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      setPageDropActive(true);
    };
    uploadDropZone.ondragleave = (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
    };
    uploadDropZone.ondrop = (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      dragCounter = 0;
      setPageDropActive(false);
      uploadSelectedFiles(e.dataTransfer.files);
    };

    window.addEventListener("dragenter", (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      dragCounter += 1;
      setPageDropActive(true);
    });
    window.addEventListener("dragover", (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      setPageDropActive(true);
    });
    window.addEventListener("dragleave", (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      dragCounter = Math.max(0, dragCounter - 1);
      if (dragCounter === 0) setPageDropActive(false);
    });
    window.addEventListener("drop", (e) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      dragCounter = 0;
      setPageDropActive(false);
      uploadSelectedFiles(e.dataTransfer.files);
    });

    syncComposerPresentation();

    async function initApp(){
      try {
        const loaded = await hydrateConversationsFromDb();
        if (!loaded) return;
      } catch (e) {
        showError("加载数据库会话失败：" + (e && e.message ? e.message : String(e)));
        return;
      }
      updateSidebar();
      const initialMessagesPromise = appState.activeChatId
        ? loadConversationMessagesFromDb(appState.activeChatId)
        : null;
      updateWorkspace();
      reviveTaskPollers();
      if (appState.activeChatId) {
        initialMessagesPromise
          .then(() => {
            if (!appState.activeChatId) return;
            updateSidebar();
            updateWorkspace();
            reviveTaskPollers();
          })
          .catch((e) => {
            if (e && e.name === "AbortError") return;
            showError("加载消息失败：" + (e && e.message ? e.message : String(e)));
          });
      }
      try {
        const resp = await fetch("/api/models");
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          const msg = detailFromApiBody(data) || "HTTP " + resp.status;
          showError("加载模型列表失败：" + msg);
          modelsCache = { text: [], image: [], all: [] };
        } else {
          modelsCache = {
            text: data.text || [],
            image: data.image || [],
            all: data.all || [],
          };
          const n =
            modelsCache.text.length +
            modelsCache.image.length +
            (modelsCache.all || []).length;
          if (n === 0) {
            showError(
              "模型列表为空。请检查 OFOX_API_KEY、本机网络，以及上游 GET /v1/models 是否返回了模型。"
            );
          }
        }
      } catch (e) {
        showError("加载模型列表失败：" + (e && e.message ? e.message : String(e)));
        modelsCache = { text: [], image: [], all: [] };
      }
      updateSidebar();
      updateWorkspace();
      reviveTaskPollers();
    }

    fetch("/api/auth/status")
      .then(async (r) => {
        if (!r.ok) return { authenticated: false };
        return r.json().catch(() => ({ authenticated: false }));
      })
      .catch(() => ({ authenticated: false }))
      .then(async (data) => {
        if (data && data.authenticated) {
          isAuthenticated = true;
          renderCurrentUser(data.user);
          showAppShell();
          await initApp();
          return;
        }
        isAuthenticated = false;
        renderCurrentUser(null);
        showLoginOnly();
      });
