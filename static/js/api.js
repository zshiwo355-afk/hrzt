window.HRApp = window.HRApp || {};

    const INITIAL_MESSAGE_PAGE_LIMIT = 30;
    const IMAGE_INITIAL_MESSAGE_PAGE_LIMIT = 12;
    const OLDER_MESSAGE_PAGE_LIMIT = 50;
    let activeMessagesAbort = null;
    let activeMessagesRequestSeq = 0;

async function createConversationOnServer(tab, model) {
      const normalizedTab = normalizeChatTab(tab);
      const resp = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: normalizedTab,
          title: "新建聊天",
          model: model || "",
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.conversation) {
        throw new Error(detailFromApiBody(data) || "新建会话失败");
      }
      return data.conversation;
    }

    function parseApiDateTimeMs(value) {
      const helper = window.HRApp && window.HRApp.time && window.HRApp.time.parseApiDateTimeMs;
      if (typeof helper === "function") return helper(value);
      if (value == null || value === "") return 0;
      if (typeof value === "number") return Number.isFinite(value) ? value : 0;
      const parsed = Date.parse(String(value || "").trim());
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function conversationSidebarTimeMs(conv, fallbackMs) {
      const helper =
        window.HRApp && window.HRApp.time && window.HRApp.time.conversationSidebarTimeMs;
      if (typeof helper === "function") return helper(conv, fallbackMs);
      return (
        parseApiDateTimeMs(conv && conv.last_message_at) ||
        parseApiDateTimeMs(conv && conv.updated_at) ||
        parseApiDateTimeMs(conv && conv.created_at) ||
        fallbackMs ||
        Date.now()
      );
    }

    function markChatMessagesLoading(chat, active) {
      if (!chat) return;
      chat.messagesLoading = !!active;
    }

    async function loadConversationMessagesFromDb(chatId, opts) {
      if (!chatId) return;
      const chat = appState.chats.find((c) => c.id === String(chatId));
      if (!chat) return;
      const options = opts || {};
      const initialLimit =
        options.limit ||
        (chat.tab === "image" ? IMAGE_INITIAL_MESSAGE_PAGE_LIMIT : INITIAL_MESSAGE_PAGE_LIMIT);
      const abortPrevious = options.abortPrevious !== false;
      const markLoading = options.markLoading !== false;
      if (abortPrevious && activeMessagesAbort) {
        try {
          activeMessagesAbort.abort();
        } catch (e) {}
      }
      const controller =
        typeof AbortController !== "undefined" ? new AbortController() : null;
      const requestSeq = ++activeMessagesRequestSeq;
      if (abortPrevious) activeMessagesAbort = controller;
      if (markLoading) markChatMessagesLoading(chat, true);
      try {
        const resp = await fetch(
          `/api/conversations/${chatId}/messages?limit=${initialLimit}`,
          { signal: controller ? controller.signal : undefined }
        );
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          throw new Error(detailFromApiBody(data) || "加载消息失败");
        }
        if (requestSeq !== activeMessagesRequestSeq || appState.activeChatId !== String(chatId)) {
          return;
        }
        const conv = data.conversation || {};
        chat.title = conv.title || chat.title;
        chat.model = conv.model || chat.model || "";
        chat.messages = (data.messages || []).map(dbMessageToChatMessage);
        applyMessageUiStateToChat(chat);
        chat.updatedAt = conversationSidebarTimeMs(conv, chat.updatedAt);
        chat.createdAt =
          conv.created_at != null
            ? parseApiDateTimeMs(conv.created_at) || chat.createdAt
            : chat.createdAt;
        appState.currentTab = chat.tab || appState.currentTab || "text";
      } finally {
        if (requestSeq === activeMessagesRequestSeq) markChatMessagesLoading(chat, false);
      }
    }

    async function loadOlderConversationMessagesFromDb(chatId) {
      if (!chatId) return 0;
      const chat = appState.chats.find((c) => c.id === String(chatId));
      if (!chat || chat.loadingOlderMessages || chat.noMoreOlderMessages) return 0;
      const first = (chat.messages || []).find((m) => m && m.id && !String(m.id).startsWith("msg_"));
      if (!first) {
        chat.noMoreOlderMessages = true;
        return 0;
      }
      chat.loadingOlderMessages = true;
      try {
        const resp = await fetch(`/api/conversations/${chatId}/messages?limit=${OLDER_MESSAGE_PAGE_LIMIT}&before_id=${encodeURIComponent(first.id)}`);
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(detailFromApiBody(data) || "加载更早消息失败");
        const older = (data.messages || []).map(dbMessageToChatMessage);
        if (!older.length) {
          chat.noMoreOlderMessages = true;
          return 0;
        }
        chat.messages = older.concat(chat.messages || []);
        applyMessageUiStateToChat(chat);
        return older.length;
      } finally {
        chat.loadingOlderMessages = false;
      }
    }

    async function hydrateConversationsFromDb() {
      const resp = await fetch("/api/conversations?limit=100");
      if (resp.status === 401) {
        return false;
      }
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(detailFromApiBody(data) || "加载会话失败");
      }

      let chats = (data.conversations || []).map(dbConversationToChat);
      if (!chats.length) {
        const preferredTab = normalizeChatTab(appState.currentTab || localStorage.getItem(LS_CURRENT_TAB) || "text");
        const created = await createConversationOnServer(preferredTab, "");
        chats = [dbConversationToChat(created)];
      }

      appState.chats = chats.filter((chat) => isDbConversationId(chat.id));
      const preferredTab = normalizeChatTab(appState.currentTab || localStorage.getItem(LS_CURRENT_TAB) || "text");
      const activeChat = appState.chats.find((c) => c.id === appState.activeChatId);
      const latestForPreferredTab = appState.chats
        .filter((c) => c.tab === preferredTab)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
      if (!activeChat || activeChat.tab !== preferredTab) {
        appState.activeChatId = (latestForPreferredTab && latestForPreferredTab.id) || appState.chats[0].id;
      }
      appState.currentTab = preferredTab;
      persistLocalMeta();
      return true;
    }

    function allowedTextModelIds() {
      return new Set((modelsCache.text || []).map((m) => String(m.id || "")));
    }

    async function renameConversationOnServer(chatId, title) {
      const resp = await fetch(`/api/conversations/${chatId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.conversation) {
        throw new Error(detailFromApiBody(data) || "重命名失败");
      }
      return data.conversation;
    }

    async function deleteConversationOnServer(chatId) {
      const resp = await fetch(`/api/conversations/${chatId}`, {
        method: "DELETE",
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(detailFromApiBody(data) || "删除失败");
      }
      return data;
    }

function getOrCreateBrowserId() {
      let id = localStorage.getItem(LS_BROWSER_ID);
      if (!id) {
        id =
          typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
                const r = (Math.random() * 16) | 0;
                const v = c === "x" ? r : (r & 0x3) | 0x8;
                return v.toString(16);
              });
        localStorage.setItem(LS_BROWSER_ID, id);
      }
      return id;
    }

    function historyFetch(url, opts) {
      const o = opts || {};
      const headers = Object.assign({}, o.headers || {}, {
        "X-History-Browser-Id": getOrCreateBrowserId(),
      });
      return fetch(url, Object.assign({}, o, { headers }));
    }

function detailFromApiBody(data) {
      if (!data) return null;
      const d = data.detail;
      if (d == null) return null;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) {
        return d
          .map((x) => (typeof x === "object" && x && x.msg ? x.msg : JSON.stringify(x)))
          .join("; ");
      }
      return JSON.stringify(d);
    }

window.HRApp.api = Object.assign(window.HRApp.api || {}, {
  createConversationOnServer,
  loadConversationMessagesFromDb,
  loadOlderConversationMessagesFromDb,
  hydrateConversationsFromDb,
  allowedTextModelIds,
  renameConversationOnServer,
  deleteConversationOnServer,
  getOrCreateBrowserId,
  historyFetch,
  detailFromApiBody,
});
