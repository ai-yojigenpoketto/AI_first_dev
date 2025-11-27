const form = document.getElementById("chatForm");
const userMessageInput = document.getElementById("userMessage");
const toolSelect = document.getElementById("toolSelect");
const maxResultsInput = document.getElementById("maxResults");
const regionInput = document.getElementById("regionInput");
const safesearchSelect = document.getElementById("safesearchSelect");
const urlField = document.getElementById("urlField");
const urlInput = document.getElementById("urlInput");
const messagesContainer = document.getElementById("messages");
const historyList = document.getElementById("historyList");
const thinkingIndicator = document.getElementById("thinking");
const baseUrlLabel = document.getElementById("baseUrl");
const openapiLink = document.getElementById("openapiLink");

const BASE_URL = window.location.origin;
openapiLink.href = `${BASE_URL}/openapi.json`;
baseUrlLabel.textContent = BASE_URL.replace(/\/$/, "");

toolSelect.addEventListener("change", () => {
  if (toolSelect.value === "fetch_url") {
    urlField.classList.remove("hidden");
    urlInput.setAttribute("required", "required");
  } else {
    urlField.classList.add("hidden");
    urlInput.removeAttribute("required");
    urlInput.value = "";
  }
});

function appendMessage(role, content) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const label = document.createElement("strong");
  label.textContent = role === "user" ? "You" : "Assistant";
  wrapper.appendChild(label);

  const body = document.createElement("div");
  body.className = "message-content";
  body.textContent = content;
  wrapper.appendChild(body);

  messagesContainer.appendChild(wrapper);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return wrapper;
}

function appendHistoryEntry(message) {
  const item = document.createElement("li");
  item.textContent = message.length > 80 ? `${message.slice(0, 77)}…` : message;
  historyList.prepend(item);
}

function showThinking(show) {
  if (show) {
    thinkingIndicator.classList.remove("hidden");
  } else {
    thinkingIndicator.classList.add("hidden");
  }
}

async function streamChat(payload, assistantMessage) {
  const response = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    throw new Error("Streaming request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalPayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      if (!event.startsWith("data:")) continue;
      const payloadString = event.slice(5).trim();
      if (!payloadString) continue;

      const data = JSON.parse(payloadString);
      if (data.type === "token") {
        assistantMessage.querySelector(".message-content").textContent += data.value;
      } else if (data.type === "message") {
        finalPayload = data.value;
      }
    }
  }

  if (finalPayload?.results?.length) {
    const list = document.createElement("ul");
    finalPayload.results.forEach((result) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = result.href;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = result.title || "View result";
      li.appendChild(link);
      if (result.body) {
        const snippet = document.createElement("p");
        snippet.textContent = result.body;
        li.appendChild(snippet);
      }
      list.appendChild(li);
    });
    assistantMessage.appendChild(list);
  }

  if (finalPayload?.url_content) {
    const meta = document.createElement("div");
    meta.innerHTML = `
      <p><strong>URL:</strong> <a href="${finalPayload.url_content.url}" target="_blank" rel="noreferrer">${finalPayload.url_content.url}</a></p>
      ${finalPayload.url_content.title ? `<p><strong>Title:</strong> ${finalPayload.url_content.title}</p>` : ""}
      ${finalPayload.url_content.preview ? `<p>${finalPayload.url_content.preview}</p>` : ""}
    `;
    assistantMessage.appendChild(meta);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = userMessageInput.value.trim();
  if (!message) return;

  const payload = {
    message,
    tool: toolSelect.value || null,
    max_results: Number(maxResultsInput.value) || 3,
    region: regionInput.value || "wt-wt",
    safesearch: safesearchSelect.value || "moderate",
  };

  if (payload.tool === "fetch_url") {
    payload.url = urlInput.value.trim();
  }

  appendHistoryEntry(message);
  appendMessage("user", message);
  const assistantMessage = appendMessage("assistant", "");
  showThinking(true);
  form.reset();
  toolSelect.value = "";
  urlField.classList.add("hidden");
  urlInput.removeAttribute("required");

  try {
    await streamChat(payload, assistantMessage);
  } catch (error) {
    assistantMessage.querySelector(".message-content").textContent = `Error: ${error.message}`;
    console.error(error);
  } finally {
    showThinking(false);
  }
});

