/*
 * Chatbot embed loader. Add to any page of an allowed site:
 *
 *   <script src="https://chat.example.com/embed.js" defer
 *           data-color="#0B5FFF" data-position="right" data-label="Hỏi đáp"></script>
 *
 * It adds a launcher button and loads the chat (an iframe served from the
 * same origin as this script) the first time the visitor opens it. The page
 * itself never talks to the chat API, so no key is ever exposed here.
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
  window.addEventListener("message", function (event) {
    if (event.origin !== origin || !event.data || event.data.type !== "chatbot:close") return;
    close();
  });
  window.matchMedia(MOBILE_QUERY).addEventListener("change", function () {
    if (!panel.hidden) layoutPanel();
  });

  root.appendChild(panel);
  root.appendChild(button);
  document.body.appendChild(root);
})();
