(function () {
  let threadId = sessionStorage.getItem("woodpetra_session_id");
  if (!threadId) {
    threadId = "session_" + crypto.randomUUID();
    sessionStorage.setItem("woodpetra_session_id", threadId);
  }

  const style = document.createElement("style");
  style.innerHTML = `
    .chat-widget-button {
      position: fixed;
      top: 25px;
      right: 25px;
      width: 60px;
      height: 60px;
      background-color: #111827;
      color: #ffffff;
      border-radius: 50%;
      border: none;
      box-shadow: 0 10px 25px rgba(0,0,0,0.2);
      cursor: pointer;
      z-index: 99999;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 26px;
      transition: transform 0.2s ease;
    }
    .chat-widget-button:hover { transform: scale(1.08); }

    .chat-widget-window {
      position: fixed;
      top: 90px;
      right: 25px;
      width: 400px;
      height: 620px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 12px 35px rgba(0,0,0,0.18);
      border: 1px solid #e5e7eb;
      display: none;
      flex-direction: column;
      z-index: 99999;
      overflow: hidden;
      font-family: system-ui, -apple-system, sans-serif;
    }

    .chat-header {
      background: #111827;
      color: #fff;
      padding: 14px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: 600;
      flex-shrink: 0;
    }

    .chat-body {
      flex: 1;
      padding: 14px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #f9fafb;
      scroll-behavior: smooth;
    }

    .chat-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.45;
      white-space: pre-wrap;
      flex-shrink: 0;
    }
    .chat-msg.user {
      align-self: flex-end;
      background: #2563eb;
      color: #fff;
      border-bottom-right-radius: 2px;
    }
    .chat-msg.bot {
      align-self: flex-start;
      background: #ffffff;
      color: #1f2937;
      border: 1px solid #e5e7eb;
      border-bottom-left-radius: 2px;
    }

    .horizontal-scroll-container {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding: 4px 2px 10px 2px;
      scroll-behavior: smooth;
      flex-shrink: 0;
    }
    .horizontal-scroll-container::-webkit-scrollbar {
      height: 5px;
    }
    .horizontal-scroll-container::-webkit-scrollbar-thumb {
      background: #cbd5e1;
      border-radius: 10px;
    }

    /* COMPACT, PROPERLY SIZED CARDS */
    .product-card-horizontal {
      flex: 0 0 145px;
      width: 145px;
      height: 200px;
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 8px;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      box-shadow: 0 2px 6px rgba(0,0,0,0.04);
      box-sizing: border-box;
    }
    .product-card-horizontal img {
      width: 100%;
      height: 70px;
      object-fit: cover;
      border-radius: 4px;
      background: #f3f4f6;
      margin-bottom: 6px;
    }
    .card-title {
      font-size: 11.5px;
      font-weight: 600;
      color: #111827;
      line-height: 1.2;
      height: 28px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      margin-bottom: 2px;
    }
    .card-meta {
      font-size: 10px;
      color: #6b7280;
      margin-bottom: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      width: 100%;
    }
    .card-price {
      font-size: 12.5px;
      font-weight: 700;
      color: #059669;
      margin-bottom: 6px;
    }
    .card-btn {
      width: 100%;
      padding: 5px 0;
      background: #111827;
      color: #ffffff;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      text-decoration: none;
      display: block;
      margin-top: auto;
      transition: background 0.2s ease;
    }
    .card-btn:hover { background: #2563eb; }

    .section-divider {
      font-size: 11.5px;
      font-weight: 700;
      color: #6b7280;
      margin: 6px 0 2px 0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      flex-shrink: 0;
    }

    .chat-footer {
      padding: 12px;
      padding-right: 50px;
      background: #fff;
      border-top: 1px solid #e5e7eb;
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }
    .chat-input {
      flex: 1;
      border: 1px solid #d1d5db;
      padding: 8px 12px;
      border-radius: 20px;
      outline: none;
      font-size: 13.5px;
    }
    .chat-send {
      background: #111827;
      color: #fff;
      border: none;
      padding: 8px 14px;
      border-radius: 20px;
      cursor: pointer;
      font-size: 13px;
    }
  `;
  document.head.appendChild(style);

  const button = document.createElement("button");
  button.className = "chat-widget-button";
  button.innerHTML = "💬";

  const windowDiv = document.createElement("div");
  windowDiv.className = "chat-widget-window";
  windowDiv.innerHTML = `
    <div class="chat-header">
      <span>Shubham Fashion Assistant</span>
      <span class="close-btn" style="cursor:pointer;" id="chatClose">✕</span>
    </div>
    <div class="chat-body" id="chatBody">
      <div class="chat-msg bot">Hello! Welcome to Shubham Fashion. How can I help you find the perfect outfit today?</div>
    </div>
    <div class="chat-footer">
      <input type="text" class="chat-input" id="chatInput" placeholder="Ask about hoodies, prices, sizes..." />
      <button class="chat-send" id="chatSend">Send</button>
    </div>
  `;

  document.body.appendChild(button);
  document.body.appendChild(windowDiv);

  button.onclick = () => {
    windowDiv.style.display = windowDiv.style.display === "flex" ? "none" : "flex";
  };
  document.getElementById("chatClose").onclick = () => {
    windowDiv.style.display = "none";
  };

  const chatBody = document.getElementById("chatBody");
  const chatInput = document.getElementById("chatInput");
  const chatSend = document.getElementById("chatSend");

  function cleanMarkdownLinks(text) {
    return text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").trim();
  }

  // Anchor the view to the top of the user's message
  function scrollToElement(elem) {
    setTimeout(() => {
      elem.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  async function handleSend() {
    const query = chatInput.value.trim();
    if (!query) return;

    // Track the user message element to use it as our scroll anchor
    const userMsgElem = appendMessage(query, "user");
    chatInput.value = "";

    const typingElem = appendMessage("Thinking...", "bot");

    // Scroll to user query while typing
    scrollToElement(userMsgElem);

    try {
      const res = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, thread_id: threadId }),
      });

      const data = await res.json();
      typingElem.remove();

      const cleanResponseText = cleanMarkdownLinks(data.response);
      appendMessage(cleanResponseText, "bot");

      if (data.displayed_products && data.displayed_products.length > 0) {
        renderProductCarousel(data.displayed_products);
      }

      if (data.similar_products && data.similar_products.length > 0) {
        renderSimilarSection(data.similar_products);
      }

      // Re-pin scroll position to the user's message so text stays fully visible
      scrollToElement(userMsgElem);
    } catch (err) {
      typingElem.innerText = "Error connecting to server. Please try again.";
    }
  }

  function appendMessage(text, sender) {
    const msg = document.createElement("div");
    msg.className = `chat-msg ${sender}`;
    msg.innerText = text;
    chatBody.appendChild(msg);
    return msg;
  }

  function createCardHTML(p) {
    // Compact formatting: Grey • M • In Stock
    const color = p.color || "";
    const size = p.size ? p.size : "";
    const stock = "In Stock"; // Or map to p.stock if your backend returns dynamic stock
    
    const metaArr = [color, size, stock].filter(Boolean);
    const metaText = metaArr.join(" • ");

    return `
      <div class="product-card-horizontal">
        <img src="${p.image_url || "https://via.placeholder.com/100"}" alt="${p.name}" />
        <div class="card-title">${p.name}</div>
        <div class="card-meta" title="${metaText}">${metaText}</div>
        <div class="card-price">₹${p.price}</div>
        <a href="${p.product_url || "#"}" target="_blank" class="card-btn">View Item</a>
      </div>
    `;
  }

  function renderProductCarousel(products) {
    const container = document.createElement("div");
    container.className = "horizontal-scroll-container";
    products.forEach((p) => {
      container.innerHTML += createCardHTML(p);
    });
    chatBody.appendChild(container);
  }

  function renderSimilarSection(similarProducts) {
    const title = document.createElement("div");
    title.className = "section-divider";
    title.innerText = "You might also like:";

    const container = document.createElement("div");
    container.className = "horizontal-scroll-container";
    similarProducts.forEach((p) => {
      container.innerHTML += createCardHTML(p);
    });
    
    chatBody.appendChild(title);
    chatBody.appendChild(container);
  }

  chatSend.onclick = handleSend;
  chatInput.onkeypress = (e) => { if (e.key === "Enter") handleSend(); };
})();