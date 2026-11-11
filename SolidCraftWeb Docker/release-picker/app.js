"use strict";

const state = {
  builds: [],
  activeVersion: null,
  selectedVersion: null,
  filter: "all",
  query: "",
  sortKey: "published_at",
  sortDirection: -1,
  publishing: false,
};

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const elements = {
  activeVersion: document.querySelector("#active-version"),
  totalCount: document.querySelector("#total-count"),
  typeCount: document.querySelector("#type-count"),
  resultCount: document.querySelector("#result-count"),
  search: document.querySelector("#search"),
  rows: document.querySelector("#release-rows"),
  emptyState: document.querySelector("#empty-state"),
  loadError: document.querySelector("#load-error"),
  selectionBar: document.querySelector("#selection-bar"),
  selectedVersion: document.querySelector("#selected-version"),
  selectionHint: document.querySelector("#selection-hint"),
  publishButton: document.querySelector("#publish-button"),
  dialog: document.querySelector("#publish-dialog"),
  dialogVersion: document.querySelector("#dialog-version"),
  dialogType: document.querySelector("#dialog-type"),
  confirmPublish: document.querySelector("#confirm-publish"),
  cancelPublish: document.querySelector("#cancel-publish"),
  publishError: document.querySelector("#publish-error"),
  toast: document.querySelector("#toast"),
};

function typeGroup(type) {
  if (type === "stable" || type === "release candidate" || type === "nightly") return type;
  return "other";
}

function updateCounts() {
  const counts = { all: state.builds.length, stable: 0, "release candidate": 0, nightly: 0, other: 0 };
  for (const build of state.builds) counts[typeGroup(build.type)] += 1;
  document.querySelector("#count-all").textContent = counts.all;
  document.querySelector("#count-stable").textContent = counts.stable;
  document.querySelector("#count-rc").textContent = counts["release candidate"];
  document.querySelector("#count-nightly").textContent = counts.nightly;
  document.querySelector("#count-other").textContent = counts.other;
  elements.totalCount.textContent = counts.all;
  elements.typeCount.textContent = Object.values(counts).slice(1).filter((count) => count > 0).length;
}

function formatBuildDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    const time = document.createElement("time");
    time.textContent = "Date unavailable";
    return time;
  }
  const time = document.createElement("time");
  time.dateTime = date.toISOString();
  const utcDate = date.toISOString();
  time.title = `UTC ${utcDate.replace("T", " ").replace(/\.\d{3}Z$/, "Z")}`;
  time.setAttribute("aria-label", `Build date in your local time: ${dateFormatter.format(date)}. UTC: ${date.toISOString()}`);
  time.textContent = dateFormatter.format(date);
  const relative = document.createElement("span");
  relative.textContent = `UTC ${utcDate.replace("T", " ").replace(/\.\d{3}Z$/, "Z")}`;
  const wrapper = document.createElement("span");
  wrapper.className = "build-date";
  wrapper.append(time, relative);
  return wrapper;
}

function createTypeBadge(type) {
  const badge = document.createElement("span");
  badge.className = `type-badge type-${typeGroup(type).replaceAll(" ", "-")}`;
  badge.textContent = type;
  return badge;
}

function matchesFilter(build) {
  return state.filter === "all" || typeGroup(build.type) === state.filter;
}

function visibleBuilds() {
  const query = state.query.trim().toLocaleLowerCase();
  return state.builds
    .filter((build) => matchesFilter(build))
    .filter((build) => !query || `${build.name} ${build.version} ${build.type} ${build.available ? "web bundle available" : "web bundle unavailable"}`.toLocaleLowerCase().includes(query))
    .sort((left, right) => {
      const a = left[state.sortKey];
      const b = right[state.sortKey];
      let comparison;
      if (state.sortKey === "published_at") {
        comparison = new Date(a).getTime() - new Date(b).getTime();
      } else {
        comparison = collator.compare(a, b);
      }
      return comparison * state.sortDirection;
    });
}

function updateSortIndicators() {
  document.querySelectorAll(".sort-button").forEach((button) => {
    const active = button.dataset.sort === state.sortKey;
    const indicator = button.querySelector(".sort-indicator");
    indicator.textContent = active ? (state.sortDirection === 1 ? "↑" : "↓") : "";
    button.closest("th").setAttribute("aria-sort", active ? (state.sortDirection === 1 ? "ascending" : "descending") : "none");
  });
}

function renderRows() {
  const builds = visibleBuilds();
  const fragment = document.createDocumentFragment();
  elements.rows.replaceChildren();
  elements.emptyState.hidden = builds.length > 0;
  elements.resultCount.textContent = `Showing ${builds.length} of ${state.builds.length} builds`;

  for (const build of builds) {
    const row = document.createElement("tr");
    row.className = `release-row${state.selectedVersion === build.version ? " is-selected" : ""}${build.available ? "" : " is-unavailable"}`;
    row.tabIndex = build.available ? 0 : -1;
    row.dataset.version = build.version;
    row.setAttribute("aria-selected", String(state.selectedVersion === build.version));
    row.setAttribute("aria-disabled", String(!build.available));

    const releaseCell = document.createElement("td");
    const releaseName = document.createElement("div");
    releaseName.className = "release-name";
    const glyph = document.createElement("span");
    glyph.className = "release-glyph";
    glyph.textContent = "SC";
    glyph.setAttribute("aria-hidden", "true");
    const title = document.createElement("span");
    title.className = "release-title";
    const name = document.createElement("strong");
    name.textContent = build.name;
    const version = document.createElement("span");
    version.textContent = build.version;
    title.append(name, version);
    releaseName.append(glyph, title);
    releaseCell.append(releaseName);

    const typeCell = document.createElement("td");
    typeCell.append(createTypeBadge(build.type));
    const dateCell = document.createElement("td");
    dateCell.append(formatBuildDate(build.published_at));
    const statusCell = document.createElement("td");
    if (build.version === state.activeVersion) {
      const active = document.createElement("span");
      active.className = "active-badge";
      active.textContent = "Live";
      statusCell.append(active);
    } else if (build.available) {
      statusCell.textContent = "Available";
    } else {
      const unavailable = document.createElement("span");
      unavailable.className = "unavailable-label";
      unavailable.textContent = "No web bundle";
      statusCell.append(unavailable);
    }

    const selectCell = document.createElement("td");
    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "select-build";
    selectButton.setAttribute("aria-label", `Select ${build.name} ${build.version}`);
    selectButton.setAttribute("aria-pressed", String(state.selectedVersion === build.version));
    selectButton.disabled = !build.available;
    if (!build.available) selectButton.title = "This release does not include a SolidCraft web bundle and checksum.";
    selectButton.innerHTML = build.available
      ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3.2 3.2L13 4.5"></path></svg>'
      : '<span aria-hidden="true">—</span>';
    selectCell.append(selectButton);

    row.append(releaseCell, typeCell, dateCell, statusCell, selectCell);
    fragment.append(row);
  }
  elements.rows.append(fragment);
  updateSortIndicators();
  updateSelection();
}

function updateSelection() {
  const selected = state.builds.find((build) => build.version === state.selectedVersion);
  elements.selectionBar.hidden = !selected;
  if (!selected) return;
  elements.selectedVersion.textContent = selected.version;
  const isLive = selected.version === state.activeVersion;
  elements.selectionHint.textContent = isLive ? "This build is already live" : `Ready to publish · ${selected.type}`;
  elements.publishButton.disabled = isLive || state.publishing;
  elements.publishButton.innerHTML = state.publishing
    ? 'Publishing… <span class="loader" aria-hidden="true"></span>'
    : isLive
      ? "Build is live"
      : 'Publish selected build <span aria-hidden="true">→</span>';
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  window.setTimeout(() => elements.toast.classList.remove("is-visible"), 4000);
}

function selectBuild(version) {
  const build = state.builds.find((candidate) => candidate.version === version);
  if (!build || !build.available) return;
  state.selectedVersion = version;
  renderRows();
}

async function loadCatalog() {
  try {
    const response = await fetch("/_admin/releases", { headers: { Accept: "application/json" } });
    const catalog = await response.json();
    if (!response.ok) throw new Error(catalog.error || `Could not load releases (${response.status})`);
    if (!Array.isArray(catalog.builds)) throw new Error("The release catalog response was invalid.");
    state.builds = catalog.builds;
    state.activeVersion = catalog.active_version;
    state.selectedVersion = catalog.active_version;
    elements.activeVersion.textContent = catalog.active_version ? `LIVE ${catalog.active_version}` : "NO LIVE BUILD";
    elements.loadError.hidden = true;
    updateCounts();
    renderRows();
  } catch (error) {
    elements.resultCount.textContent = "Release library unavailable";
    elements.rows.replaceChildren();
    elements.loadError.textContent = `Could not load the SolidCraft release library. ${error.message}`;
    elements.loadError.hidden = false;
  }
}

function openPublishDialog() {
  const selected = state.builds.find((build) => build.version === state.selectedVersion);
  if (!selected || selected.version === state.activeVersion || state.publishing) return;
  elements.dialogVersion.textContent = selected.version;
  elements.dialogType.textContent = selected.type;
  elements.publishError.hidden = true;
  elements.dialog.showModal();
}

async function publishSelectedBuild() {
  const selected = state.builds.find((build) => build.version === state.selectedVersion);
  if (!selected || state.publishing) return;
  state.publishing = true;
  elements.confirmPublish.disabled = true;
  elements.confirmPublish.textContent = "Publishing build…";
  elements.publishError.hidden = true;
  updateSelection();
  try {
    const response = await fetch(`/_admin/update?version=${encodeURIComponent(selected.version)}`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(`The update endpoint returned an unreadable response (${response.status}).`);
    }
    if (!response.ok) throw new Error(result.error || `The update failed (${response.status}).`);
    state.activeVersion = result.version;
    elements.activeVersion.textContent = `LIVE ${result.version}`;
    elements.dialog.close();
    renderRows();
    showToast(result.updated ? `${result.version} is now live.` : `${result.version} was already live.`);
  } catch (error) {
    elements.publishError.textContent = error.message;
    elements.publishError.hidden = false;
  } finally {
    state.publishing = false;
    elements.confirmPublish.disabled = false;
    elements.confirmPublish.innerHTML = 'Publish build <span aria-hidden="true">→</span>';
    updateSelection();
  }
}

elements.search.addEventListener("input", () => {
  state.query = elements.search.value;
  renderRows();
});

elements.search.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    elements.search.value = "";
    state.query = "";
    renderRows();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== elements.search && !elements.dialog.open) {
    event.preventDefault();
    elements.search.focus();
  }
});

document.querySelectorAll(".filter-chip").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll(".filter-chip").forEach((chip) => {
      const active = chip === button;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", String(active));
    });
    renderRows();
  });
});

document.querySelectorAll(".sort-button").forEach((button) => {
  button.addEventListener("click", () => {
    const nextKey = button.dataset.sort;
    if (state.sortKey === nextKey) state.sortDirection *= -1;
    else {
      state.sortKey = nextKey;
      state.sortDirection = nextKey === "published_at" ? -1 : 1;
    }
    renderRows();
  });
});

elements.rows.addEventListener("click", (event) => {
  const row = event.target.closest(".release-row");
  if (row) selectBuild(row.dataset.version);
});

elements.rows.addEventListener("keydown", (event) => {
  const row = event.target.closest(".release-row");
  if (row && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    selectBuild(row.dataset.version);
  }
});

elements.publishButton.addEventListener("click", openPublishDialog);
elements.confirmPublish.addEventListener("click", publishSelectedBuild);
elements.cancelPublish.addEventListener("click", () => elements.dialog.close());

loadCatalog();
