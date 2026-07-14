(function () {
  "use strict";

  var surfaces = {
    live: {
      name: "Live Dashboard",
      url: "/qader_live_dashboard.html",
      healthUrl: "/api/state"
    },
    depth: {
      name: "Market Depth",
      url: "/market_depth.html",
      healthUrl: "/market_depth.html"
    },
    flow: {
      name: "Agent Flow",
      url: "/agent_flow_diagram.html",
      healthUrl: "/agent_flow_diagram.html"
    },
    service8866: {
      name: "Local Service 8866",
      url: "http://127.0.0.1:8866/",
      healthUrl: "http://127.0.0.1:8866/api/runner_state"
    },
    service8833: {
      name: "Local Service 8833",
      url: "http://127.0.0.1:8833/",
      healthUrl: "http://127.0.0.1:8833/api/overview"
    }
  };

  var els = {
    loopState: document.getElementById("loopState"),
    loopReason: document.getElementById("loopReason"),
    symbolValue: document.getElementById("symbolValue"),
    sessionValue: document.getElementById("sessionValue"),
    decisionValue: document.getElementById("decisionValue"),
    signalValue: document.getElementById("signalValue"),
    learningValue: document.getElementById("learningValue"),
    learningReason: document.getElementById("learningReason"),
    riskValue: document.getElementById("riskValue"),
    positionsValue: document.getElementById("positionsValue"),
    priceValue: document.getElementById("priceValue"),
    spreadValue: document.getElementById("spreadValue"),
    refreshValue: document.getElementById("refreshValue"),
    timestampValue: document.getElementById("timestampValue"),
    frame: document.getElementById("surfaceFrame"),
    activeName: document.getElementById("activeSurfaceName"),
    activeUrl: document.getElementById("activeSurfaceUrl"),
    activeLink: document.getElementById("activeSurfaceLink")
  };

  function valueOrDash(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    return String(value);
  }

  function numberOrDash(value, digits) {
    var num = Number(value);
    if (!Number.isFinite(num)) {
      return "-";
    }
    return num.toFixed(digits);
  }

  function formatTime(value) {
    if (!value) {
      return "-";
    }
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value).slice(0, 19).replace("T", " ");
    }
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
  }

  function setTone(el, tone) {
    el.classList.remove("tone-ok", "tone-warn", "tone-bad");
    if (tone) {
      el.classList.add(tone);
    }
  }

  function updateState(data) {
    var loop = data.loop || {};
    var latest = data.latest_record || {};
    if (data.display_record) {
      latest = data.display_record;
    } else if (data.latest_decision_record) {
      latest = data.latest_decision_record;
    }
    var learning = data.learning_state || {};
    var application = learning.application || {};
    var state = valueOrDash(loop.state || latest.loop_state);
    var risk = valueOrDash(latest.risk_status || latest.execution_status || latest.blocked_reason);
    var decision = valueOrDash(latest.final_action || loop.last_decision);
    var signal = valueOrDash(latest.arbiter_result || loop.last_signal);
    var flipState = latest.signal_flip ? "flip active" : latest.intra_bar_cycle ? "intra-bar fast" : "new bar";
    var learningStatus = application.applied
      ? "APPLIED"
      : learning.error
        ? "ERROR"
        : valueOrDash(application.reason || learning.strategy_dna_modification || learning.source_event);
    var bid = numberOrDash(latest.bid, 3);
    var ask = numberOrDash(latest.ask, 3);
    var spread = valueOrDash(latest.spread);

    els.loopState.textContent = state;
    els.loopReason.textContent = valueOrDash(loop.reason || latest.reason);
    els.symbolValue.textContent = valueOrDash(latest.symbol);
    els.sessionValue.textContent = [
      valueOrDash(latest.timeframe),
      valueOrDash(latest.session)
    ].filter(function (item) { return item !== "-"; }).join(" / ") || "-";
    els.decisionValue.textContent = decision;
    els.signalValue.textContent = "Signal " + signal + " / confidence " + numberOrDash(latest.confidence, 3) + " / " + flipState;
    els.learningValue.textContent = learningStatus;
    els.learningReason.textContent = "Samples " + valueOrDash((learning.summary || {}).count) + " / " + valueOrDash(application.proposal || "");
    els.riskValue.textContent = risk;
    els.positionsValue.textContent = "Open positions " + valueOrDash(latest.open_positions_total || latest.open_positions);
    els.priceValue.textContent = bid + " / " + ask;
    els.spreadValue.textContent = "Spread " + spread + " (" + valueOrDash(latest.spread_quality) + ")";
    els.refreshValue.textContent = "Cycle " + valueOrDash(latest.cycle_number || loop.cycle_count);
    els.timestampValue.textContent = formatTime(data.timestamp || latest.timestamp || loop.last_cycle_time);

    setTone(els.loopState, state === "RUNNING" ? "tone-ok" : "tone-warn");
    setTone(els.decisionValue, decision === "HOLD" ? "tone-warn" : "tone-ok");
    setTone(els.learningValue, application.applied ? "tone-ok" : /disabled|error/i.test(learningStatus) ? "tone-bad" : "tone-warn");
    setTone(els.riskValue, /blocked|error|loss/i.test(risk) ? "tone-bad" : "tone-ok");
  }

  function updateStateFailure(error) {
    els.loopState.textContent = "State unavailable";
    els.loopReason.textContent = error && error.message ? error.message : "Fetch failed";
    setTone(els.loopState, "tone-bad");
    els.refreshValue.textContent = "No state";
    els.timestampValue.textContent = formatTime(new Date().toISOString());
  }

  function fetchState() {
    fetch("/api/state", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(updateState)
      .catch(function () {
        fetch("/qader_live_state.json", { cache: "no-store" })
          .then(function (response) {
            if (!response.ok) {
              throw new Error("HTTP " + response.status);
            }
            return response.json();
          })
          .then(updateState)
          .catch(updateStateFailure);
      });
  }

  function setHealth(key, status) {
    var card = document.querySelector('[data-health-card="' + key + '"]');
    if (!card) {
      return;
    }
    card.classList.remove("online", "offline");
    card.classList.add(status);
  }

  function probeSurface(key, surface) {
    var options = { method: "GET", cache: "no-store" };
    if (/^https?:\/\//.test(surface.healthUrl) && !surface.healthUrl.startsWith(location.origin)) {
      options.mode = "no-cors";
    }
    fetch(surface.healthUrl, options)
      .then(function () {
        setHealth(key, "online");
      })
      .catch(function () {
        setHealth(key, "offline");
      });
  }

  function probeHealth() {
    Object.keys(surfaces).forEach(function (key) {
      probeSurface(key, surfaces[key]);
    });
  }

  function activateSurface(key) {
    var surface = surfaces[key];
    if (!surface) {
      return;
    }

    els.frame.src = surface.url;
    els.activeName.textContent = surface.name;
    els.activeUrl.textContent = surface.url;
    els.activeLink.href = surface.url;

    document.querySelectorAll("[data-target]").forEach(function (node) {
      node.classList.toggle("active", node.getAttribute("data-target") === key);
    });
  }

  document.querySelectorAll("[data-target]").forEach(function (node) {
    node.addEventListener("click", function () {
      activateSurface(node.getAttribute("data-target"));
    });
  });

  fetchState();
  probeHealth();
  setInterval(fetchState, 3000);
  setInterval(probeHealth, 15000);
})();
