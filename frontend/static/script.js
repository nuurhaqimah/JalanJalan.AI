document.addEventListener("DOMContentLoaded", () => {
  const chatInput = document.getElementById("chatInput");
  const sendChatBtn = document.getElementById("sendChatBtn");
  const chatBox = document.getElementById("chatBox");
  const itineraryOutput = document.getElementById("itinerary-output");
  const form = document.getElementById("destinationForm");
  const table = document.getElementById("destinationsTable");

  let userId = "demo-user"; // later replace with logged-in user ID
  let typingIndicator;
  let map, markers = [];
  let destinations = [
        {
          id: 1,
          name: "Pantai Jerudong",
          category: "alam",
          budget_level: "cheap",
          travel_style: "relaxing",
          location: "Brunei",
          description: "Beautiful beach for sunsets.",
        },
        {
          id: 2,
          name: "Kampong Ayer",
          category: "sejarah",
          budget_level: "moderate",
          travel_style: "cultural",
          location: "Bandar Seri Begawan",
          description: "Historic water village.",
        },
      ];

      function renderTable() {
        table.innerHTML = "";
        destinations.forEach((dest) => {
          const row = document.createElement("tr");
          row.innerHTML = `
          <td>${dest.name}</td>
          <td>${dest.category}</td>
          <td>${dest.budget_level}</td>
          <td>${dest.travel_style}</td>
          <td>${dest.location}</td>
          <td class="actions">
            <button class="edit-btn" onclick="editDestination(${dest.id})">Edit</button>
            <button class="delete-btn" onclick="deleteDestination(${dest.id})">Delete</button>
          </td>
        `;
          table.appendChild(row);
        });
      }

      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const id = document.getElementById("destinationId").value;
        const newDest = {
          id: id ? parseInt(id) : Date.now(),
          name: document.getElementById("name").value,
          category: document.getElementById("category").value,
          budget_level: document.getElementById("budget_level").value,
          travel_style: document.getElementById("travel_style").value,
          location: document.getElementById("location").value,
          description: document.getElementById("description").value,
        };

        if (id) {
          destinations = destinations.map((d) =>
            d.id === parseInt(id) ? newDest : d
          );
        } else {
          destinations.push(newDest);
        }

        form.reset();
        document.getElementById("destinationId").value = "";
        renderTable();
      });

      function editDestination(id) {
        const dest = destinations.find((d) => d.id === id);
        document.getElementById("destinationId").value = dest.id;
        document.getElementById("name").value = dest.name;
        document.getElementById("category").value = dest.category;
        document.getElementById("budget_level").value = dest.budget_level;
        document.getElementById("travel_style").value = dest.travel_style;
        document.getElementById("location").value = dest.location;
        document.getElementById("description").value = dest.description;
      }

      function deleteDestination(id) {
        destinations = destinations.filter((d) => d.id !== id);
        renderTable();
      }

      renderTable();

  // === Map setup ===
  function initMap() {
    if (document.getElementById("map")) {
      map = L.map("map").setView([51.505, -0.09], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors"
      }).addTo(map);
    }
  }

  // === Chat with backend ===
  async function sendChat(message, prefs = {}) {
    if (!message) return;
    addChatMessage("user", message);
    chatInput.value = "";
    removeOptions();
    showTypingIndicator();

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, user_id: userId, prefs })
      });

      const data = await res.json();
      hideTypingIndicator();

      if (data.reply) addChatMessage("bot", data.reply);
      if (data.options && data.next) renderOptions(data.options, data.next);

      if (data.itinerary) renderItinerary(data.itinerary);
      if (data.flights) renderFlights(data.flights);
      if (data.hotels) renderHotels(data.hotels);

    } catch (err) {
      hideTypingIndicator();
      addChatMessage("bot", "⚠️ Error: could not connect to backend.");
    }
  }

  // === Quick-reply option buttons ===
  function removeOptions() {
    const existing = document.getElementById("chat-options");
    if (existing) existing.remove();
  }

  function renderOptions(options, next) {
    removeOptions();

    const container = document.createElement("div");
    container.id = "chat-options";
    container.className = "chat-options";

    if (next === "interests") {
      // Multi-select: user picks 1 or 2, then confirms
      let selected = [];

      options.forEach(opt => {
        const btn = document.createElement("button");
        btn.className = "chat-option-btn";
        btn.textContent = opt;
        btn.onclick = () => {
          if (btn.classList.contains("selected")) {
            btn.classList.remove("selected");
            selected = selected.filter(s => s !== opt);
          } else if (selected.length < 2) {
            btn.classList.add("selected");
            selected.push(opt);
          }
          confirmBtn.disabled = selected.length === 0;
        };
        container.appendChild(btn);
      });

      const confirmBtn = document.createElement("button");
      confirmBtn.className = "chat-option-confirm";
      confirmBtn.textContent = "Confirm";
      confirmBtn.disabled = true;
      confirmBtn.onclick = () => {
        const label = selected.join(" & ");
        sendChat(label, { interests: selected });
      };
      container.appendChild(confirmBtn);

    } else {
      // Single-select: clicking sends immediately
      options.forEach(opt => {
        const btn = document.createElement("button");
        btn.className = "chat-option-btn";
        btn.textContent = opt;
        btn.onclick = () => sendChat(opt);
        container.appendChild(btn);
      });
    }

    chatBox.appendChild(container);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  // === Helpers ===
  function addChatMessage(sender, text) {
    const msg = document.createElement("div");
    msg.className = sender === "user" ? "chat-user" : "chat-bot";
    msg.innerHTML = text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    chatBox.appendChild(msg);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  function showTypingIndicator() {
    typingIndicator = document.createElement("div");
    typingIndicator.className = "chat-bot typing";
    typingIndicator.textContent = "JalanJalan.AI is thinking...";
    chatBox.appendChild(typingIndicator);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  function hideTypingIndicator() {
    if (typingIndicator) {
      chatBox.removeChild(typingIndicator);
      typingIndicator = null;
    }
  }

  // === Render itinerary ===
  function renderItinerary(itinerary) {
    let html = "<h2>Your Itinerary</h2>";
    itinerary.forEach(item => {
      html += `
        <div class="activity-card">
          <div class="activity-info">
            <div style="font-weight:600">${item.time || ""}</div>
            <h3>${item.title || "Activity"}</h3>
            <p>${item.poi_name || ""}</p>
            <p>${item.description || ""}</p>
          </div>
        </div>
      `;
    });
    itineraryOutput.innerHTML = html;
    renderMap(itinerary);
  }

  // === Render flights from API ===
  function renderFlights(flights) {
    let html = "<h2>Flight Options</h2>";
    flights.forEach(f => {
      html += `
        <div class="activity-card">
          <div class="activity-info">
            <h3>${f.airline} ${f.flight_number}</h3>
            <p>${f.departure} → ${f.arrival}</p>
            <p>Price: ${f.price} ${f.currency}</p>
          </div>
        </div>
      `;
    });
    itineraryOutput.innerHTML += html;
  }

  // === Render hotels from API ===
  function renderHotels(hotels) {
    let html = "<h2>Hotel Options</h2>";
    hotels.forEach(h => {
      html += `
        <div class="hotel-card">
          <img src="${h.image || '/static/assets/hotel1.jpg'}" class="hotel-image"/>
          <div class="hotel-info">
            <h3>${h.name}</h3>
            <p>${h.address}</p>
            <p>Price: ${h.price} ${h.currency}</p>
            <p>Rating: ${h.rating || "N/A"}</p>
          </div>
        </div>
      `;
    });
    itineraryOutput.innerHTML += html;
  }

  // === Map render ===
  function renderMap(itinerary) {
    if (!map) initMap();
    clearMarkers();
    const locations = itinerary.filter(i => i.lat && i.lon);
    if (locations.length) {
      locations.forEach(i => {
        const marker = L.marker([i.lat, i.lon]).addTo(map)
          .bindPopup(`<b>${i.title}</b><br>${i.description}`);
        markers.push(marker);
      });
      const group = L.featureGroup(markers);
      map.fitBounds(group.getBounds().pad(0.5));
    }
  }

  function clearMarkers() {
    markers.forEach(m => map.removeLayer(m));
    markers = [];
  }

  // === PDF Generation ===
  let lastItineraryId = null;

  document.getElementById("generateBtn").onclick = async () => {
    const res = await fetch("/generate", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + localStorage.getItem("token")
        },
        body: JSON.stringify({
            prefs: { budget: "medium", interests: ["food", "history"] },
            days: 2
        })
    });
    const data = await res.json();
    lastItineraryId = data.id;
    alert("Itinerary generated!");
    document.getElementById("pdfBtn").style.display = "inline-block";
};

  document.getElementById("pdfBtn").onclick = () => {
    if (lastItineraryId) {
        window.location.href = "/export/" + lastItineraryId + "?Authorization=Bearer " + localStorage.getItem("token");
    }
};


  // === Event Listeners ===
  chatInput.addEventListener("keypress", e => {
    if (e.key === "Enter") sendChat(chatInput.value.trim());
  });
  sendChatBtn.addEventListener("click", () => sendChat(chatInput.value.trim()));

  initMap();
});
