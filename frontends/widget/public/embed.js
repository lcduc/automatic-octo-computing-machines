/*
 * Chatbot embed loader. Add to any page of an allowed site:
 *
 *   <script src="https://chat.example.com/embed.js" defer
 *           data-color="#0B5FFF" data-position="right" data-label="Hỏi đáp"></script>
 *
 * It adds a launcher button and loads the chat (an iframe served from the
 * same origin as this script) the first time the visitor opens it. The page
 * itself never talks to the chat API, so no key is ever exposed here.
 *
 * Signed-in users: give the chat a way to get a short-lived token from your
 * backend (see host-sdk/), before or after this script loads:
 *
 *   window.ChatbotConfig = { getToken: () => fetch("/chatbot-token").then(r => r.ok ? r.text() : null),
 *                            onLoginRequest: () => showYourLoginDialog() };
 *   // or, once loaded: Chatbot.configure({ getToken, onLoginRequest })
 *   Chatbot.login();   // after your user signs in
 *   Chatbot.logout();  // when they sign out (their private chat history disappears at once)
 *
 * Messages to the chat iframe always target its exact origin, and only
 * messages from that iframe are accepted.
 */
(function () {
  "use strict";
  if (window.__chatbotEmbedLoaded) return;
  window.__chatbotEmbedLoaded = true;

  var script = document.currentScript;
  if (!script || !script.src) return;
  var origin = new URL(script.src).origin;
  var color = /^#[0-9a-fA-F]{6}$/.test(script.dataset.color || "") ? script.dataset.color : "#0B5FFF";
  var side = script.dataset.position === "left" ? "left" : "right";
  var label = script.dataset.label || "Hỏi đáp";
  var MOBILE_QUERY = "(max-width: 480px)";

  var root = document.createElement("div");
  root.setAttribute("data-chatbot-embed", "");
  root.style.cssText = "position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;font-family:system-ui,sans-serif;";

  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", "chatbot-embed-panel");
  button.textContent = label;
  button.style.cssText =
    "background:" + color + ";color:#fff;border:0;border-radius:24px;padding:12px 18px;font-size:15px;" +
    "font-weight:600;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2);";

  var panel = document.createElement("div");
  panel.id = "chatbot-embed-panel";
  panel.hidden = true;

  var iframe = null;

  function layoutPanel() {
    var mobile = window.matchMedia(MOBILE_QUERY).matches;
    panel.style.cssText = mobile
      ? "position:fixed;inset:0;background:#fff;"
      : "position:absolute;bottom:60px;" + side + ":0;width:380px;height:600px;max-height:calc(100vh - 100px);" +
        "border-radius:12px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.25);background:#fff;";
  }

  function open() {
    if (!iframe) {
      iframe = document.createElement("iframe");
      iframe.src = origin + "/widget";
      iframe.title = label;
      iframe.setAttribute("allow", "clipboard-write");
      iframe.style.cssText = "width:100%;height:100%;border:0;";
      panel.appendChild(iframe);
    }
    layoutPanel();
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    iframe.focus();
  }

  function close() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    button.focus();
  }

  button.addEventListener("click", function () {
    if (panel.hidden) open();
    else close();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) close();
  });
  // --- Host page <-> chat iframe ------------------------------------------------
  var initial = window.ChatbotConfig || {};
  var hooks = { getToken: initial.getToken || null, onLoginRequest: initial.onLoginRequest || null };

  function send(message) {
    if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(message, origin);
  }

  /** Ask the host backend for a token and hand it to the chat (null = nobody signed in). */
  function sendToken(type) {
    if (typeof hooks.getToken !== "function") {
      send({ type: "host:hello" });
      return;
    }
    Promise.resolve()
      .then(function () { return hooks.getToken(); })
      .then(
        function (token) { send({ type: type, token: typeof token === "string" && token ? token : null }); },
        function () { send({ type: type, token: null }); }
      );
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== origin || !iframe || event.source !== iframe.contentWindow || !event.data) return;
    var type = event.data.type;
    if (type === "chatbot:close") close();
    else if (type === "chatbot:ready") sendToken("host:login");
    else if (type === "chatbot:request_token") sendToken("host:token_refresh");
    else if (type === "chatbot:login_request" && typeof hooks.onLoginRequest === "function") hooks.onLoginRequest();
  });

  var api = window.Chatbot || {};
  api.configure = function (options) {
    hooks.getToken = (options && options.getToken) || null;
    hooks.onLoginRequest = (options && options.onLoginRequest) || null;
    sendToken("host:login");
  };
  api.login = function () { sendToken("host:login"); };
  api.logout = function () { send({ type: "host:logout" }); };
  api.open = open;
  api.close = close;
  window.Chatbot = api;
  window.matchMedia(MOBILE_QUERY).addEventListener("change", function () {
    if (!panel.hidden) layoutPanel();
  });

  root.appendChild(panel);
  root.appendChild(button);
  document.body.appendChild(root);
})();
