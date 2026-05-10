(() => {
  const canvas = document.getElementById("grid");
  const ctx = canvas.getContext("2d");
  const buildList = document.getElementById("buildlist");
  const toastEl = document.getElementById("toast");
  const nextDayBtn = document.getElementById("next-day");

  const els = {
    day: document.getElementById("day"),
    treasury: document.getElementById("treasury"),
    population: document.getElementById("population"),
    happiness: document.getElementById("happiness"),
    balance: document.getElementById("balance"),
  };

  const TILE_COLORS = {
    town_hall: "#d4a72c",
    road: "#6e7177",
    house: "#4ea3ff",
    commercial: "#9d6cff",
    industrial: "#ff7a59",
    park: "#3fbf7f",
    pipeline: "#bdb6a8",
    solar_farm: "#f5d76e",
    wind_turbine: "#6dd5ed",
    coal_plant: "#c97676",
    gas_peaker: "#d09bff",
  };

  const PLANT_TYPES = ["solar_farm", "wind_turbine", "coal_plant", "gas_peaker"];

  let cols = 32;
  let rows = 32;
  let tiles = [];
  let treasury = 0;
  let catalog = null;
  let selectedType = null;
  let hoverCell = null;

  function showToast(msg, kind = "error") {
    toastEl.textContent = msg;
    toastEl.className = `toast show ${kind}`;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      toastEl.className = "toast";
    }, 1800);
  }

  function cellSize() {
    return { cw: canvas.width / cols, ch: canvas.height / rows };
  }

  function drawGrid() {
    const w = canvas.width;
    const h = canvas.height;
    const { cw, ch } = cellSize();
    ctx.clearRect(0, 0, w, h);

    for (const t of tiles) {
      ctx.fillStyle = TILE_COLORS[t.type] || "#888";
      ctx.fillRect(t.x * cw, t.y * ch, cw, ch);
      if (t.type === "town_hall") {
        ctx.fillStyle = "#1a1c22";
        ctx.font = `${Math.floor(ch * 0.6)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("⌂", t.x * cw + cw / 2, t.y * ch + ch / 2);
      }
    }

    ctx.strokeStyle = "#2a2d34";
    ctx.lineWidth = 1;
    for (let i = 0; i <= cols; i++) {
      const x = Math.round(i * cw) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let j = 0; j <= rows; j++) {
      const y = Math.round(j * ch) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    if (selectedType && hoverCell) {
      const valid = isPlacementValid(hoverCell.x, hoverCell.y, selectedType);
      ctx.fillStyle = valid ? "rgba(63,191,127,0.35)" : "rgba(255,80,80,0.35)";
      ctx.fillRect(hoverCell.x * cw, hoverCell.y * ch, cw, ch);
    }
  }

  function tileAt(x, y) {
    return tiles.find((t) => t.x === x && t.y === y) || null;
  }

  function roadNetwork() {
    const start = tiles.find((t) => t.type === "town_hall");
    if (!start) return new Set();
    const isRoad = new Map();
    for (const t of tiles) {
      if (t.type === "road" || t.type === "town_hall") {
        isRoad.set(`${t.x},${t.y}`, t);
      }
    }
    const seen = new Set([`${start.x},${start.y}`]);
    const stack = [[start.x, start.y]];
    while (stack.length) {
      const [x, y] = stack.pop();
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = x + dx;
        const ny = y + dy;
        const key = `${nx},${ny}`;
        if (seen.has(key)) continue;
        if (!isRoad.has(key)) continue;
        seen.add(key);
        stack.push([nx, ny]);
      }
    }
    return seen;
  }

  function isPlacementValid(x, y, tileType) {
    if (!catalog) return false;
    if (x < 0 || y < 0 || x >= cols || y >= rows) return false;
    if (tileAt(x, y)) return false;
    const spec = catalog[tileType];
    if (!spec) return false;
    if (treasury < spec.capex) return false;
    if (spec.requires_road) {
      const net = roadNetwork();
      const adj = [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]];
      if (!adj.some(([ax, ay]) => net.has(`${ax},${ay}`))) return false;
    }
    return true;
  }

  async function loadCatalog() {
    try {
      const res = await fetch("/catalog");
      const data = await res.json();
      catalog = {};
      for (const entry of data.tiles) {
        if (entry.buildable) catalog[entry.tile_type] = entry;
      }
      renderBuildMenu();
    } catch (err) {
      console.error("catalog load failed", err);
    }
  }

  function renderBuildMenu() {
    if (!catalog) return;
    buildList.innerHTML = "";
    const order = [
      "road",
      "house",
      "commercial",
      "industrial",
      "park",
      "pipeline",
      "solar_farm",
      "wind_turbine",
      "gas_peaker",
      "coal_plant",
    ];
    for (const tt of order) {
      const spec = catalog[tt];
      if (!spec) continue;
      const li = document.createElement("li");
      li.dataset.type = tt;
      li.className = "buildItem";
      li.innerHTML = `
        <span class="swatch" style="background:${TILE_COLORS[tt] || "#888"}"></span>
        <div class="bi-text">
          <div class="bi-name">${tt}</div>
          <div class="bi-desc">${spec.description}</div>
          <div class="bi-cost">$${spec.capex.toLocaleString()} · $${spec.opex_per_day}/day</div>
        </div>
      `;
      li.addEventListener("click", () => {
        selectedType = selectedType === tt ? null : tt;
        for (const node of buildList.children) node.classList.remove("selected");
        if (selectedType) li.classList.add("selected");
        drawGrid();
      });
      buildList.appendChild(li);
    }
  }

  function gridCellFromEvent(ev) {
    const rect = canvas.getBoundingClientRect();
    const px = ev.clientX - rect.left;
    const py = ev.clientY - rect.top;
    return {
      x: Math.floor((px / rect.width) * cols),
      y: Math.floor((py / rect.height) * rows),
    };
  }

  canvas.addEventListener("mousemove", (ev) => {
    const cell = gridCellFromEvent(ev);
    if (!hoverCell || hoverCell.x !== cell.x || hoverCell.y !== cell.y) {
      hoverCell = cell;
      drawGrid();
    }
  });
  canvas.addEventListener("mouseleave", () => {
    hoverCell = null;
    drawGrid();
  });

  canvas.addEventListener("click", async (ev) => {
    if (!selectedType) return;
    const { x, y } = gridCellFromEvent(ev);
    try {
      const res = await fetch("/build", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tile_type: selectedType, x, y }),
      });
      const body = await res.json();
      if (body.ok) showToast(`built ${selectedType} at (${x}, ${y})`, "ok");
      else showToast(`build rejected: ${body.error}`, "error");
      tick();
    } catch (err) {
      showToast(`network error: ${err}`, "error");
    }
  });

  canvas.addEventListener("contextmenu", async (ev) => {
    ev.preventDefault();
    const { x, y } = gridCellFromEvent(ev);
    try {
      const res = await fetch("/demolish", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ x, y }),
      });
      const body = await res.json();
      if (body.ok) showToast(`demolished at (${x}, ${y})`, "ok");
      else showToast(`demolish rejected: ${body.error}`, "error");
      tick();
    } catch (err) {
      showToast(`network error: ${err}`, "error");
    }
  });

  nextDayBtn.addEventListener("click", async () => {
    nextDayBtn.disabled = true;
    try {
      await fetch("/step", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ days: 1 }),
      });
      tick();
    } finally {
      nextDayBtn.disabled = false;
    }
  });

  // Tab switching ---------------------------------------------------------
  const tabButtons = document.querySelectorAll(".tab");
  const tabPanels = document.querySelectorAll(".tabpanel");
  for (const btn of tabButtons) {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      for (const b of tabButtons) b.classList.toggle("active", b === btn);
      for (const p of tabPanels) p.classList.toggle("active", p.id === `tab-${target}`);
    });
  }

  // Power tab rendering ---------------------------------------------------
  const chartEl = document.getElementById("powerchart");
  const plantListEl = document.getElementById("plantlist");

  function renderPowerChart(supply, demand) {
    if (!chartEl) return;
    chartEl.innerHTML = "";
    if (!supply || !demand || supply.length === 0) {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", "50%");
      t.setAttribute("y", "50%");
      t.setAttribute("fill", "#5a5d65");
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("font-size", "12");
      t.textContent = "no data — step a day to see hourly trace";
      chartEl.appendChild(t);
      return;
    }
    const W = 480;
    const H = 200;
    const padX = 28;
    const padY = 8;
    const maxY = Math.max(...supply, ...demand, 1) * 1.1;
    const path = (series, color) => {
      const pts = series.map((v, i) => {
        const x = padX + (i / (series.length - 1)) * (W - padX * 2);
        const y = H - padY - (v / maxY) * (H - padY * 2);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      });
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", pts.join(" "));
      p.setAttribute("stroke", color);
      p.setAttribute("stroke-width", "2");
      p.setAttribute("fill", "none");
      chartEl.appendChild(p);
    };
    // Y-axis label (max).
    const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lbl.setAttribute("x", "4");
    lbl.setAttribute("y", "14");
    lbl.setAttribute("fill", "#5a5d65");
    lbl.setAttribute("font-size", "10");
    lbl.textContent = `${Math.round(maxY)} kW`;
    chartEl.appendChild(lbl);
    path(demand, "#ff7a59");
    path(supply, "#4ea3ff");
  }

  function renderPlantList(allTiles) {
    if (!plantListEl) return;
    plantListEl.innerHTML = "";
    const plants = allTiles.filter((t) => PLANT_TYPES.includes(t.type));
    if (plants.length === 0) {
      const li = document.createElement("li");
      li.style.color = "#5a5d65";
      li.style.fontSize = "0.8rem";
      li.textContent = "no plants built";
      plantListEl.appendChild(li);
      return;
    }
    const caps = (catalog && Object.fromEntries(Object.entries(catalog).map(([k, v]) => [k, v.capacity_kw || 1]))) || {};
    for (const p of plants) {
      const cap = caps[p.type] || 1;
      const out = p.current_output_kw || 0;
      const pct = Math.min(100, (out / cap) * 100);
      const li = document.createElement("li");
      li.className = `plantrow ${p.type}`;
      li.innerHTML = `
        <span class="pl-name">${p.type} (${p.x},${p.y})</span>
        <div class="pl-bar"><div class="pl-bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
        <span class="pl-val">${Math.round(out)}/${cap} kW</span>
      `;
      plantListEl.appendChild(li);
    }
  }

  async function tick() {
    try {
      const res = await fetch("/state");
      if (!res.ok) return;
      const s = await res.json();
      cols = s.config.world_w;
      rows = s.config.world_h;
      tiles = s.tiles || [];
      treasury = s.treasury;
      els.day.textContent = s.day;
      els.treasury.textContent = Math.round(s.treasury).toLocaleString();
      els.population.textContent = s.population;
      els.happiness.textContent = s.happiness.toFixed(2);
      const balanceState = (s.power_now && s.power_now.balance_state) || "—";
      els.balance.textContent = balanceState;
      els.balance.className = `balance-badge ${balanceState}`;
      renderPowerChart(s.last_day_supply_kw_by_hour, s.last_day_demand_kw_by_hour);
      renderPlantList(tiles);
      drawGrid();
    } catch (err) {
      // Server may not be up yet during boot — keep polling.
    }
  }

  loadCatalog();
  drawGrid();
  tick();
  setInterval(tick, 500);
})();
