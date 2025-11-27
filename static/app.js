const form = document.getElementById("chatForm");
const userMessageInput = document.getElementById("userMessage");
const toolSelect = document.getElementById("toolSelect");
const maxResultsInput = document.getElementById("maxResults");
const regionInput = document.getElementById("regionInput");
const safesearchSelect = document.getElementById("safesearchSelect");
const formatSelect = document.getElementById("formatSelect");
const urlField = document.getElementById("urlField");
const urlInput = document.getElementById("urlInput");
const messagesContainer = document.getElementById("messages");
const historyList = document.getElementById("historyList");
const thinkingIndicator = document.getElementById("thinking");
const baseUrlLabel = document.getElementById("baseUrl");
const openapiLink = document.getElementById("openapiLink");
const dailyNewsletterBtn = document.getElementById("dailyNewsletterBtn");
const automationCommand = document.getElementById("automationCommand");
const copyAutomationBtn = document.getElementById("copyAutomation");
const newsletterSection = document.getElementById("newsletterSection");
const newsletterHtml = document.getElementById("newsletterHtml");
const newsletterText = document.getElementById("newsletterText");
const copyNewsletterBtn = document.getElementById("copyNewsletter");

const BASE_URL = window.location.origin;
const DEFAULT_DAILY_QUERY = "What is the most latest AI news in the past 24 hours?";
openapiLink.href = `${BASE_URL}/openapi.json`;
baseUrlLabel.textContent = BASE_URL.replace(/\/$/, "");
automationCommand.textContent = `curl -s ${BASE_URL}/newsletter/daily`;

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

function toggleNewsletter(show) {
  if (show) {
    newsletterSection.classList.remove("hidden");
  } else {
    newsletterSection.classList.add("hidden");
    newsletterHtml.innerHTML = "";
    newsletterText.value = "";
  }
}

function renderSupplementalData(payload, assistantMessage) {
  if (!payload || !assistantMessage) return;

  if (payload.results?.length) {
    const list = document.createElement("ul");
    payload.results.forEach((result) => {
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

  if (payload.url_content) {
    const meta = document.createElement("div");
    meta.innerHTML = `
      <p><strong>URL:</strong> <a href="${payload.url_content.url}" target="_blank" rel="noreferrer">${payload.url_content.url}</a></p>
      ${payload.url_content.title ? `<p><strong>Title:</strong> ${payload.url_content.title}</p>` : ""}
      ${payload.url_content.preview ? `<p>${payload.url_content.preview}</p>` : ""}
    `;
    assistantMessage.appendChild(meta);
  }

  if (payload.newsletter_html || payload.newsletter_text) {
    toggleNewsletter(true);
    newsletterHtml.innerHTML =
      payload.newsletter_html || "<p>No HTML preview available.</p>";
    newsletterText.value =
      payload.newsletter_text || "No plain-text newsletter available.";
  } else {
    toggleNewsletter(false);
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

  renderSupplementalData(finalPayload, assistantMessage);
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
    response_format: formatSelect.value || "default",
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

  toggleNewsletter(false);

  try {
    await streamChat(payload, assistantMessage);
  } catch (error) {
    assistantMessage.querySelector(".message-content").textContent = `Error: ${error.message}`;
    console.error(error);
  } finally {
    showThinking(false);
  }
});

dailyNewsletterBtn.addEventListener("click", async () => {
  appendHistoryEntry(`[Daily Subscription] ${DEFAULT_DAILY_QUERY}`);
  appendMessage("user", DEFAULT_DAILY_QUERY);
  const assistantMessage = appendMessage("assistant", "");
  showThinking(true);
  toggleNewsletter(false);

  try {
    const response = await fetch("/newsletter/daily");
    if (!response.ok) {
      throw new Error("Failed to fetch daily newsletter.");
    }
    const payload = await response.json();
    assistantMessage.querySelector(".message-content").textContent = payload.reply;
    renderSupplementalData(payload, assistantMessage);
  } catch (error) {
    assistantMessage.querySelector(".message-content").textContent = `Error: ${error.message}`;
    console.error(error);
  } finally {
    showThinking(false);
  }
});

copyNewsletterBtn.addEventListener("click", async () => {
  if (!newsletterSection.classList.contains("hidden") && newsletterText.value) {
    try {
      await navigator.clipboard.writeText(newsletterText.value);
      copyNewsletterBtn.textContent = "Copied!";
      setTimeout(() => (copyNewsletterBtn.textContent = "Copy Text"), 2000);
    } catch (error) {
      console.error("Failed to copy newsletter", error);
    }
  }
});

copyAutomationBtn.addEventListener("click", async () => {
  const command = automationCommand.textContent;
  if (!command) return;
  try {
    await navigator.clipboard.writeText(command);
    copyAutomationBtn.textContent = "Copied!";
    setTimeout(() => (copyAutomationBtn.textContent = "Copy Command"), 2000);
  } catch (error) {
    console.error("Failed to copy automation command", error);
  }
});

