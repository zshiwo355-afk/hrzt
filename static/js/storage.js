window.HRApp = window.HRApp || {};

function loadChatPrefsMap() {
      try {
        const raw = localStorage.getItem(LS_CHAT_PREFS_STATE);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (err) {
        return {};
      }
    }

    function saveChatPrefsMap(stateMap) {
      try {
        localStorage.setItem(LS_CHAT_PREFS_STATE, JSON.stringify(stateMap || {}));
      } catch (err) {
        console.warn("会话偏好写入失败：", err);
      }
    }

    function tabPrefsKey(tab) {
      return `__tab__:${normalizeChatTab(tab || "text")}`;
    }

    function loadTabPrefs(tab) {
      const stateMap = loadChatPrefsMap();
      const row = stateMap[tabPrefsKey(tab)];
      return row && typeof row === "object" ? row : {};
    }

    function persistTabPrefs(chat) {
      if (!chat) return;
      const tab = normalizeChatTab(chat.tab || appState.currentTab || "text");
      const stateMap = loadChatPrefsMap();
      const prev = stateMap[tabPrefsKey(tab)] && typeof stateMap[tabPrefsKey(tab)] === "object"
        ? stateMap[tabPrefsKey(tab)]
        : {};
      stateMap[tabPrefsKey(tab)] = Object.assign({}, prev, {
        model: String(chat.model || ""),
        reasoning_mode: String(chat.reasoning_mode || "default"),
      });
      saveChatPrefsMap(stateMap);
    }

    function persistChatPrefs(chat) {
      if (!chat || !chat.id) return;
      const stateMap = loadChatPrefsMap();
      stateMap[String(chat.id)] = {
        model: String(chat.model || ""),
        use_rag: !!chat.use_rag,
        use_web_search: !!chat.use_web_search,
        reasoning_mode: String(chat.reasoning_mode || "default"),
      };
      saveChatPrefsMap(stateMap);
      persistTabPrefs(chat);
    }

    function applyChatPrefs(chat) {
      if (!chat || !chat.id) return chat;
      const stateMap = loadChatPrefsMap();
      const tabRow = loadTabPrefs(chat.tab);
      const row = stateMap[String(chat.id)];
      if (row && typeof row === "object") {
        if (typeof row.model === "string" && row.model.trim()) {
          chat.model = row.model.trim();
        } else if (typeof tabRow.model === "string" && tabRow.model.trim()) {
          chat.model = tabRow.model.trim();
        }
        chat.use_rag = !!row.use_rag;
        chat.use_web_search = !!row.use_web_search;
        chat.reasoning_mode =
          typeof row.reasoning_mode === "string" && row.reasoning_mode.trim()
            ? row.reasoning_mode.trim()
            : typeof tabRow.reasoning_mode === "string" && tabRow.reasoning_mode.trim()
            ? tabRow.reasoning_mode.trim()
            : (chat.reasoning_mode || "default");
      } else {
        if (typeof tabRow.model === "string" && tabRow.model.trim()) {
          chat.model = tabRow.model.trim();
        }
        chat.use_rag = !!chat.use_rag;
        chat.use_web_search = !!chat.use_web_search;
        chat.reasoning_mode =
          typeof tabRow.reasoning_mode === "string" && tabRow.reasoning_mode.trim()
            ? tabRow.reasoning_mode.trim()
            : (chat.reasoning_mode || "default");
      }
      return chat;
    }

function messageUiStateKey(chatId, msgId) {
      return `${String(chatId || "")}::${String(msgId || "")}`;
    }

    function loadMessageUiStateMap() {
      try {
        const raw = localStorage.getItem(LS_MESSAGE_UI_STATE);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (err) {
        return {};
      }
    }

    function saveMessageUiStateMap(stateMap) {
      try {
        localStorage.setItem(LS_MESSAGE_UI_STATE, JSON.stringify(stateMap || {}));
      } catch (err) {
        console.warn("消息 UI 状态写入失败：", err);
      }
    }

    function persistMessageUiState(chatId, msg) {
      if (!chatId || !msg || !msg.id) return;
      const stateMap = loadMessageUiStateMap();
      const key = messageUiStateKey(chatId, msg.id);
      stateMap[key] = {
        sourcesExpanded: !!msg.sourcesExpanded,
        note: msg.note || "",
        rag_status: msg.rag_status || "",
        sources: Array.isArray(msg.sources) ? msg.sources : [],
        progressSteps: Array.isArray(msg.progressSteps) ? msg.progressSteps : [],
      };
      saveMessageUiStateMap(stateMap);
    }

    function replaceMessageUiStateKey(chatId, fromMsgId, toMsgId, msg) {
      if (!chatId || !fromMsgId || !toMsgId) return;
      const stateMap = loadMessageUiStateMap();
      const oldKey = messageUiStateKey(chatId, fromMsgId);
      const newKey = messageUiStateKey(chatId, toMsgId);
      const oldRow = stateMap[oldKey] && typeof stateMap[oldKey] === "object" ? stateMap[oldKey] : {};
      stateMap[newKey] = {
        sourcesExpanded: msg ? !!msg.sourcesExpanded : !!oldRow.sourcesExpanded,
        note: msg ? (msg.note || "") : (oldRow.note || ""),
        rag_status: msg ? (msg.rag_status || "") : (oldRow.rag_status || ""),
        sources: msg && Array.isArray(msg.sources) ? msg.sources : (Array.isArray(oldRow.sources) ? oldRow.sources : []),
        progressSteps: msg && Array.isArray(msg.progressSteps) ? msg.progressSteps : (Array.isArray(oldRow.progressSteps) ? oldRow.progressSteps : []),
      };
      if (oldKey !== newKey) {
        delete stateMap[oldKey];
      }
      saveMessageUiStateMap(stateMap);
    }

    function applyMessageUiState(chatId, msg) {
      if (!chatId || !msg || !msg.id) return msg;
      const stateMap = loadMessageUiStateMap();
      const row = stateMap[messageUiStateKey(chatId, msg.id)];
      if (row && typeof row === "object") {
        if (typeof row.sourcesExpanded === "boolean") {
          msg.sourcesExpanded = row.sourcesExpanded;
        }
        if ((!msg.note || !String(msg.note).trim()) && row.note) {
          msg.note = row.note;
        }
        if ((!msg.rag_status || !String(msg.rag_status).trim()) && row.rag_status) {
          msg.rag_status = row.rag_status;
        }
        if ((!Array.isArray(msg.sources) || msg.sources.length === 0) && Array.isArray(row.sources)) {
          msg.sources = row.sources;
        }
        if ((!Array.isArray(msg.progressSteps) || msg.progressSteps.length === 0) && Array.isArray(row.progressSteps)) {
          msg.progressSteps = row.progressSteps;
        }
      }
      return msg;
    }

    function applyMessageUiStateToChat(chat) {
      if (!chat || !chat.id || !Array.isArray(chat.messages)) return;
      chat.messages.forEach((msg) => applyMessageUiState(chat.id, msg));
    }

function persistLocalMeta() {
      try {
        localStorage.setItem(LS_ACTIVE_ID, appState.activeChatId || "");
        localStorage.setItem(LS_CURRENT_TAB, appState.currentTab || "text");
        localStorage.setItem(LS_ACTIVE_PROJECT_ID, appState.activeProjectId || "");
      } catch (err) {
        console.warn("本地 meta 写入失败：", err);
      }
    }

    function persistAppStateToLs(st) {
      void st;
      persistLocalMeta();
    }

window.HRApp.storage = Object.assign(window.HRApp.storage || {}, {
  loadChatPrefsMap,
  saveChatPrefsMap,
  loadTabPrefs,
  persistTabPrefs,
  persistChatPrefs,
  applyChatPrefs,
  messageUiStateKey,
  loadMessageUiStateMap,
  saveMessageUiStateMap,
  persistMessageUiState,
  replaceMessageUiStateKey,
  applyMessageUiState,
  applyMessageUiStateToChat,
  persistLocalMeta,
  persistAppStateToLs,
});
