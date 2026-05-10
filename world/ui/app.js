(() => {
  const canvas = document.getElementById("grid");
  const ctx = canvas.getContext("2d");

  const els = {
    day: document.getElementById("day"),
    treasury: document.getElementById("treasury"),
    population: document.getElementById("population"),
    happiness: document.getElementById("happiness"),
    balance: document.getElementById("balance"),
  };

  let cols = 32;
  let rows = 32;

  function drawGrid() {
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#2a2d34";
    ctx.lineWidth = 1;
    const cw = w / cols;
    const ch = h / rows;
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
  }

  async function tick() {
    try {
      const res = await fetch("/state");
      if (!res.ok) return;
      const s = await res.json();
      cols = s.config.world_w;
      rows = s.config.world_h;
      els.day.textContent = s.day;
      els.treasury.textContent = Math.round(s.treasury).toLocaleString();
      els.population.textContent = s.population;
      els.happiness.textContent = s.happiness.toFixed(2);
      els.balance.textContent = (s.power_now && s.power_now.balance_state) || "—";
      drawGrid();
    } catch (err) {
      // Server may not be up yet during boot — keep polling.
    }
  }

  drawGrid();
  tick();
  setInterval(tick, 500);
})();
