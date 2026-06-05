let sessionId = null;
const messages = document.getElementById("messages");
const traceEl = document.getElementById("trace");

function add(role, text) {
  const d = document.createElement("div");
  d.className = "msg " + (role === "user" ? "user" : "bot");
  d.textContent = text;
  messages.appendChild(d);
  messages.scrollTop = messages.scrollHeight;
}

document.getElementById("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("input");
  const text = input.value.trim();
  if (!text) return;
  add("user", text); input.value = "";
  const res = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message: text }),
  });
  const data = await res.json();
  sessionId = data.session_id;
  add("bot", data.reply);
  traceEl.textContent = JSON.stringify(data.trace, null, 2);
});
