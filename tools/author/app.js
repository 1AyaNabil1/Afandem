/* Afandem authoring tool: the page.
 *
 * Offline and local: opened from disk (file://), no server, no network, no libraries. The
 * scenario model lives in model.js. Only the current step is ever in the page, so on the
 * blind steps (EN, MSA) the EGY, Arabizi, CS and CS-Latin texts are not in the DOM at all.
 * The tool never writes, suggests or pre-fills any text: every text field starts empty.
 * Provenance is kept per column: a column opened as an assistant draft stays one until the
 * author marks it rewritten or approved (see "provenance" below).
 */
(function () {
  "use strict";

  const M = window.AfandemModel;
  const S = M.SCHEMA;
  const DRAFT_KEY = "afandem.author.draft.v1";
  const PREFS_KEY = "afandem.author.prefs.v1";
  const LINT_COMMAND = "uv run afandem data lint data/";

  const state = {
    draft: null,
    prefs: { canary: "", showRatioBlind: true },
    storage: "ok",
    draftWrittenAt: null,
    projectCanary: "",
    canarySource: "",
    fileHandle: null,
    lastSaved: null,
    notices: []
  };
  let liveUpdaters = [];
  let report = null;
  let persistTimer = null;

  // ------------------------------------------------------------------ DOM helpers

  /** append(el, child, child, ...): strings become text nodes; arrays are flattened. */
  function append(el) {
    for (let i = 1; i < arguments.length; i += 1) {
      const child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) {
        child.forEach(function (c) {
          append(el, c);
        });
      } else if (typeof child === "string" || typeof child === "number") {
        el.appendChild(document.createTextNode(String(child)));
      } else {
        el.appendChild(child);
      }
    }
  }

  /** h("tag", {attr: value, onclick: fn, text: "..."}, ...children) */
  function h(tag, props) {
    const el = document.createElement(tag);
    let value;
    const attrs = props || {};
    Object.keys(attrs).forEach(function (key) {
      const v = attrs[key];
      if (v === null || v === undefined || v === false) return;
      if (key === "class") el.className = v;
      else if (key === "text") el.textContent = v;
      else if (key === "value") value = v;
      else if (key.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(key.slice(2), v);
      else if (key === "checked" || key === "disabled" || key === "selected" || key === "open") el[key] = true;
      else if (v === true) el.setAttribute(key, "");
      else el.setAttribute(key, String(v));
    });
    for (let i = 2; i < arguments.length; i += 1) append(el, arguments[i]);
    if (value !== undefined) el.value = value;
    return el;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function live(fn) {
    liveUpdaters.push(fn);
  }

  function select(options, current, onChange, attrs) {
    const props = Object.assign({}, attrs || {});
    props.onchange = function (e) {
      onChange(e.target.value);
    };
    const el = h(
      "select",
      props,
      options.map(function (o) {
        return h("option", { value: o.value, text: o.label });
      })
    );
    el.value = current;
    return el;
  }

  function badge(text, kind) {
    return h("span", { class: "badge" + (kind ? " badge-" + kind : ""), text: text });
  }

  function field(label, control, help, attrs) {
    const props = Object.assign({ class: "field" }, attrs || {});
    return h(
      "label",
      props,
      h("span", { class: "field-label" }, label),
      control,
      help ? h("span", { class: "help" }, help) : null
    );
  }

  function section(title, ...children) {
    return h("section", { class: "card" }, title ? h("h3", { text: title }) : null, children);
  }

  function code(text) {
    return h("code", { text: text });
  }

  // ------------------------------------------------------------------ storage

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      state.storage = "blocked";
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
      state.storage = "ok";
      return true;
    } catch (e) {
      state.storage = "blocked";
      return false;
    }
  }

  function removeStorage(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (e) {
      state.storage = "blocked";
    }
  }

  function loadPrefs() {
    const raw = readStorage(PREFS_KEY);
    if (!raw) return;
    try {
      const stored = JSON.parse(raw);
      if (stored && typeof stored.canary === "string") state.prefs.canary = stored.canary;
      if (stored && typeof stored.showRatioBlind === "boolean") state.prefs.showRatioBlind = stored.showRatioBlind;
    } catch (e) {
      /* ignore a damaged preference record */
    }
  }

  function savePrefs() {
    writeStorage(PREFS_KEY, JSON.stringify(state.prefs));
  }

  function persistNow() {
    if (persistTimer) {
      clearTimeout(persistTimer);
      persistTimer = null;
    }
    if (writeStorage(DRAFT_KEY, JSON.stringify(state.draft))) state.draftWrittenAt = new Date();
    refreshLive();
  }

  function schedulePersist() {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 300);
  }

  // ------------------------------------------------------------------ change and render

  function currentReport() {
    if (!report) report = M.validate(state.draft, { projectCanary: state.projectCanary });
    return report;
  }

  function changed(rerender) {
    report = null;
    schedulePersist();
    if (rerender) render();
    else refreshLive();
  }

  function refreshLive() {
    report = null;
    liveUpdaters.forEach(function (fn) {
      fn();
    });
  }

  function stepIndex(id) {
    return M.STEPS.findIndex(function (s) {
      return s.id === id;
    });
  }

  function stepById(id) {
    return M.STEPS[stepIndex(id)];
  }

  function goTo(id) {
    state.draft.step = id;
    schedulePersist();
    render();
    window.scrollTo(0, 0);
    const heading = document.querySelector("#main h2");
    if (heading) heading.focus({ preventScroll: true });
  }

  function render() {
    const active = document.activeElement;
    const focusKey = active && active.getAttribute ? active.getAttribute("data-fk") : null;
    liveUpdaters = [];
    report = null;
    renderNotices();
    renderStepper();
    renderMain();
    renderPager();
    live(updateFileStatus);
    refreshLive();
    if (focusKey) {
      const target = document.querySelector('[data-fk="' + cssEscape(focusKey) + '"]');
      if (target) target.focus({ preventScroll: true });
    }
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return value.replace(/["\\]/g, "\\$&");
  }

  // ------------------------------------------------------------------ notices

  function notice(id, kind, content) {
    state.notices = state.notices.filter(function (n) {
      return n.id !== id;
    });
    state.notices.push({ id: id, kind: kind, content: content });
    renderNotices();
  }

  function dismiss(id) {
    state.notices = state.notices.filter(function (n) {
      return n.id !== id;
    });
    renderNotices();
  }

  function renderNotices() {
    const box = byId("notices");
    box.textContent = "";
    state.notices.forEach(function (n) {
      let content;
      try {
        content = typeof n.content === "function" ? n.content() : n.content;
      } catch (e) {
        return;
      }
      box.appendChild(
        h(
          "div",
          { class: "notice notice-" + n.kind, role: n.kind === "error" ? "alert" : "status" },
          h("div", { class: "notice-body" }, content),
          h("button", {
            type: "button",
            class: "icon-button",
            "aria-label": "Dismiss",
            text: "×",
            onclick: function () {
              dismiss(n.id);
            }
          })
        )
      );
    });
  }

  function lintReminder(name, domain, drafted) {
    const wanted = "data/" + (domain || "<domain>") + "/" + name;
    return h(
      "div",
      { class: "reminder" },
      h(
        "p",
        null,
        "Saved ",
        code(name),
        ". It belongs at ",
        code(wanted),
        " (move it there if the browser saved it elsewhere, e.g. to Downloads). Then run, in the repo:"
      ),
      commandLine(LINT_COMMAND),
      drafted && drafted.length
        ? h(
            "p",
            null,
            "Saved as drafted by the assistant (",
            code(M.ASSISTANT_DRAFT),
            "): ",
            draftList(drafted),
            ". The lint reports each one until you rewrite or approve it here and save again."
          )
        : null,
      h("p", { class: "help", text: "The tool does not run anything; the lint is the authority on every rule." })
    );
  }

  function commandLine(command) {
    const out = h("div", { class: "command" });
    const pre = h("pre", { class: "mono", dir: "ltr", text: command });
    const status = h("span", { class: "help" });
    const button = h("button", {
      type: "button",
      class: "small",
      text: "Copy",
      onclick: function () {
        copyText(command, pre).then(function (ok) {
          status.textContent = ok ? "copied" : "select it and copy";
        });
      }
    });
    append(out, [pre, button, status]);
    return out;
  }

  function copyText(text, node) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(
        function () {
          return true;
        },
        function () {
          return selectNode(node);
        }
      );
    }
    return Promise.resolve(selectNode(node));
  }

  function selectNode(node) {
    try {
      const range = document.createRange();
      range.selectNodeContents(node);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return document.execCommand("copy");
    } catch (e) {
      return false;
    }
  }

  // ------------------------------------------------------------------ header status

  function currentText() {
    return M.stringify(M.toDocument(state.draft).doc);
  }

  function unsavedChanges() {
    return state.draft.savedText !== currentText();
  }

  function updateFileStatus() {
    const el = byId("file-status");
    const d = state.draft;
    const id = d.meta.domain && d.meta.idNumber ? M.scenarioId(d) : "new scenario";
    const parts = [h("strong", { text: id })];
    if (d.source) parts.push(" · file " + d.source);
    else parts.push(" · not saved to a file yet");
    if (M.hasContent(d) && unsavedChanges()) parts.push(h("span", { class: "unsaved", text: " · unsaved changes" }));
    if (state.storage === "blocked") {
      parts.push(h("span", { class: "unsaved", text: " · draft not kept (browser storage blocked)" }));
    } else if (state.draftWrittenAt) {
      parts.push(" · draft kept in this browser " + state.draftWrittenAt.toLocaleTimeString());
    }
    el.textContent = "";
    append(el, parts);
  }

  // ------------------------------------------------------------------ stepper and pager

  function errorsFor(stepId) {
    return currentReport().errors.filter(function (p) {
      return p.step === stepId;
    });
  }

  function renderStepper() {
    const nav = byId("stepper");
    nav.textContent = "";
    const drafted = M.assistantDrafts(state.draft);
    M.STEPS.forEach(function (step, index) {
      const current = state.draft.step === step.id;
      const hasDraft =
        step.column && (drafted.indexOf(step.column) >= 0 || (step.column === "arabizi" && drafted.indexOf(M.VARIANT) >= 0));
      const dot = h("span", { class: "dot", "aria-hidden": "true" });
      const count = h("span", { class: "sr-only" });
      live(function () {
        const n = errorsFor(step.id).length;
        dot.className = "dot " + (n ? "dot-todo" : "dot-ok");
        dot.title = n ? n + " to fix" : "nothing to fix";
        count.textContent = n ? " (" + n + " to fix)" : " (nothing to fix)";
      });
      nav.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "step" + (current ? " current" : "") + (step.blind ? " step-blind" : ""),
            "aria-current": current ? "step" : null,
            onclick: function () {
              goTo(step.id);
            }
          },
          h("span", { class: "num", text: String(index + 1) }),
          h("span", { class: "step-title", text: step.title }),
          step.blind ? h("span", { class: "badge badge-blind", text: "blind" }) : null,
          hasDraft ? h("span", { class: "badge badge-draft", title: "drafted by the assistant", text: "draft" }) : null,
          dot,
          count
        )
      );
    });
  }

  function renderPager() {
    const pager = byId("pager");
    pager.textContent = "";
    const i = stepIndex(state.draft.step);
    const prev = M.STEPS[i - 1];
    const next = M.STEPS[i + 1];
    pager.appendChild(
      prev
        ? h("button", {
            type: "button",
            class: "secondary",
            text: "← " + prev.title,
            onclick: function () {
              goTo(prev.id);
            }
          })
        : h("span")
    );
    pager.appendChild(
      next
        ? h("button", {
            type: "button",
            class: "primary",
            text: next.title + (next.blind ? " (blind)" : "") + " →",
            onclick: function () {
              goTo(next.id);
            }
          })
        : h("button", {
            type: "button",
            class: "primary",
            text: "Save JSON",
            onclick: function () {
              saveScenario("save");
            }
          })
    );
  }

  function renderMain() {
    const main = byId("main");
    main.textContent = "";
    const step = stepById(state.draft.step) || M.STEPS[0];
    const index = stepIndex(step.id);
    main.appendChild(
      h(
        "h2",
        { tabindex: "-1" },
        h("span", { class: "step-number", text: index + 1 + " · " }),
        step.title,
        step.blind ? badge("blind", "blind") : null
      )
    );
    if (step.id === "meta") renderMeta(main);
    else if (step.id === "slots") renderSlots(main);
    else if (step.id === "state") renderStateStep(main);
    else if (step.id === "review") renderReview(main);
    else renderColumnStep(main, step.column);
  }

  function issuesPanel(stepId, options) {
    const opts = options || {};
    const box = h("div", { class: "issues", "aria-live": "polite" });
    live(function () {
      const r = currentReport();
      const hideRatio = opts.blind === true && !state.prefs.showRatioBlind;
      const errors = r.errors.filter(function (p) {
        return p.step === stepId;
      });
      const hints = r.hints.filter(function (p) {
        return p.step === stepId && !(hideRatio && p.kind === "ratio");
      });
      box.textContent = "";
      if (!errors.length && !hints.length) {
        box.appendChild(h("p", { class: "ok-line", text: "Nothing to fix on this step." }));
        return;
      }
      if (errors.length) {
        box.appendChild(h("p", { class: "issues-title", text: "To fix before the file passes the schema" }));
        box.appendChild(
          h(
            "ul",
            { class: "problems" },
            errors.map(function (p) {
              return h("li", { text: p.message });
            })
          )
        );
      }
      if (hints.length) {
        box.appendChild(h("p", { class: "issues-title", text: "Hints (the lint decides)" }));
        box.appendChild(
          h(
            "ul",
            { class: "hints" },
            hints.map(function (p) {
              return h("li", { text: p.message });
            })
          )
        );
      }
    });
    return box;
  }

  // ------------------------------------------------------------------ provenance
  //
  // Each column (and the Arabizi variant) keeps the provenance it was opened with. A column
  // drafted by the assistant stays assistant_draft, however much its text is edited, until the
  // author clicks "I rewrote or approved this column"; that is the only way it becomes hand.

  function provenanceBlock(target) {
    return target === M.VARIANT ? state.draft.arabiziVariant : state.draft.texts[target];
  }

  function targetLabel(target) {
    return target === M.VARIANT ? M.VARIANT : M.COLUMN_INFO[target].label;
  }

  function draftList(targets) {
    return targets.map(targetLabel).join(", ");
  }

  function draftBadge() {
    return h("span", { class: "badge badge-draft", title: "provenance " + M.ASSISTANT_DRAFT, text: "drafted by the assistant" });
  }

  function approvedBadge() {
    return h("span", { class: "badge badge-approved", title: "provenance " + M.HAND, text: "approved by you" });
  }

  function approveButton(target, small) {
    return h("button", {
      type: "button",
      class: "approve" + (small ? " small" : ""),
      title: "Sets the provenance of " + targetLabel(target) + " to " + M.HAND,
      text: target === M.VARIANT ? "I rewrote or approved the variant" : "I rewrote or approved this column",
      onclick: function () {
        M.approve(state.draft, target);
        changed(true);
      }
    });
  }

  function undoButton(target) {
    return h("button", {
      type: "button",
      class: "small secondary",
      title: "Mark " + targetLabel(target) + " as drafted by the assistant again",
      text: "Undo",
      onclick: function () {
        M.undoApproval(state.draft, target);
        changed(true);
      }
    });
  }

  /** On a column step (and in the variant section): nothing for text written in this tool. */
  function provenancePanel(target) {
    const block = provenanceBlock(target);
    const what = target === M.VARIANT ? "variant" : "column";
    if (block.provenance === M.ASSISTANT_DRAFT) {
      return h(
        "div",
        { class: "provenance-panel provenance-draft" },
        h("p", null, draftBadge(), " ", h("strong", { text: "This " + what + " was drafted by the AI assistant." })),
        h(
          "p",
          { class: "help" },
          "Rewrite it, or read it and approve it as it is",
          target === M.VARIANT ? "" : " (the text and, where the behaviour has one, the follow-up or confirmation)",
          ". Editing does not change its label: until you click the button it is saved as ",
          code(M.ASSISTANT_DRAFT),
          ", the lint reports it, and it never enters the measured set."
        ),
        h("div", { class: "row-actions" }, approveButton(target, false))
      );
    }
    if (M.canUndoApproval(state.draft, target)) {
      return h(
        "div",
        { class: "provenance-panel provenance-approved" },
        h(
          "p",
          null,
          approvedBadge(),
          " Marked hand-written (",
          code(M.HAND),
          "). It was drafted by the assistant when the file was opened. ",
          undoButton(target)
        )
      );
    }
    return null;
  }

  /** One review-card line: the provenance and its action. */
  function provenanceLine(target) {
    const block = provenanceBlock(target);
    const draft = block.provenance === M.ASSISTANT_DRAFT;
    const undo = !draft && M.canUndoApproval(state.draft, target);
    return h(
      "div",
      { class: "provenance-line" + (draft ? " provenance-draft" : "") },
      h("p", { class: "help" }, target === M.VARIANT ? "variant provenance: " : "provenance: ", code(block.provenance), undo ? [" ", approvedBadge()] : null),
      draft ? approveButton(target, true) : undo ? undoButton(target) : null
    );
  }

  /** Review step: the six columns (and the variant) side by side. */
  function provenanceSection() {
    const d = state.draft;
    const targets = M.AUTHORING_ORDER.slice();
    if (d.arabiziVariant.enabled) targets.push(M.VARIANT);
    const drafted = M.assistantDrafts(d);
    return section(
      "Provenance",
      h(
        "p",
        { class: drafted.length ? "help warn" : "help" },
        drafted.length
          ? [
              String(drafted.length),
              drafted.length === 1 ? " is" : " are",
              " still drafted by the assistant: ",
              draftList(drafted),
              ". Each is saved as ",
              code(M.ASSISTANT_DRAFT),
              " until you rewrite or approve it and click its button below."
            ]
          : ["Every column is hand-written (", code(M.HAND), ")."]
      ),
      h(
        "div",
        { class: "scroll-x" },
        h(
          "table",
          { class: "table compact provenance-table" },
          h(
            "thead",
            null,
            h(
              "tr",
              null,
              targets.map(function (target) {
                return h("th", { class: target === M.VARIANT ? "mono" : null, text: targetLabel(target) });
              })
            )
          ),
          h(
            "tbody",
            null,
            h(
              "tr",
              null,
              targets.map(function (target) {
                const block = provenanceBlock(target);
                return h(
                  "td",
                  { class: block.provenance === M.ASSISTANT_DRAFT ? "is-draft" : null },
                  code(block.provenance),
                  block.provenance === M.ASSISTANT_DRAFT ? [" ", draftBadge()] : M.canUndoApproval(d, target) ? [" ", approvedBadge()] : null
                );
              })
            )
          )
        )
      )
    );
  }

  // ------------------------------------------------------------------ step 1: meta

  function setDomain(value) {
    const d = state.draft;
    const previous = d.meta.domain;
    d.meta.domain = value;
    const before = M.toolNames(previous);
    const untouched =
      d.tools.length === 0 ||
      (before.length === d.tools.length &&
        before.every(function (n) {
          return d.tools.indexOf(n) >= 0;
        }));
    if (untouched) d.tools = M.toolNames(value);
    changed(true);
  }

  function renderMeta(main) {
    const d = state.draft;
    const m = d.meta;
    const rules = M.behaviourRules(m.behaviour);
    const drafted = M.assistantDrafts(d);
    main.appendChild(
      h("p", { class: "lead", text: "Who is speaking, when, and what kind of item this is. Nothing on this step is text a model sees." })
    );

    const domains = S.pilot_domains.slice();
    if (m.domain && domains.indexOf(m.domain) < 0) domains.push(m.domain);
    const domainSelect = select(
      [{ value: "", label: "choose…" }].concat(
        domains.map(function (x) {
          return { value: x, label: x };
        })
      ),
      m.domain,
      setDomain,
      { "data-fk": "meta-domain" }
    );

    const idInput = h("input", {
      type: "text",
      class: "mono id-number",
      inputmode: "numeric",
      maxlength: "4",
      autocomplete: "off",
      spellcheck: "false",
      "aria-label": "id number (four digits)",
      value: m.idNumber,
      oninput: function (e) {
        m.idNumber = e.target.value.trim();
        changed();
      }
    });
    const pathHint = h("span", { class: "help" });
    live(function () {
      const dom = m.domain || "<domain>";
      pathHint.textContent = "File: data/" + dom + "/" + dom + "-" + (m.idNumber || "NNNN") + ".json";
    });
    const idControl = h("span", { class: "id-control" }, h("span", { class: "mono id-prefix", text: (m.domain || "domain") + "-" }), idInput);

    const behaviourSelect = select(
      [{ value: "", label: "choose…" }].concat(
        S.behaviours.map(function (b) {
          return { value: b, label: b };
        })
      ),
      m.behaviour,
      function (v) {
        m.behaviour = v;
        changed(true);
      },
      { "data-fk": "meta-behaviour" }
    );
    const behaviourNote = m.behaviour ? M.BEHAVIOUR_NOTES[m.behaviour] : "act, inform, ask, none, refuse or out_of_scope";

    const harmSelect = select(
      [{ value: "", label: rules.harm_type === "required" ? "choose…" : "not used" }].concat(
        S.harm_types.map(function (x) {
          return { value: x, label: x };
        })
      ),
      m.harmType,
      function (v) {
        m.harmType = v;
        changed();
      },
      { disabled: rules.harm_type !== "required" && !m.harmType }
    );

    const controlInput = h("input", {
      type: "text",
      class: "mono",
      autocomplete: "off",
      spellcheck: "false",
      placeholder: rules.control_of === "optional" ? "id of the refuse twin, or empty" : "not used",
      disabled: rules.control_of !== "optional" && !m.controlOf,
      value: m.controlOf,
      oninput: function (e) {
        m.controlOf = e.target.value.trim();
        changed();
      }
    });

    // now
    const nowInput = h("input", {
      type: "datetime-local",
      step: "1",
      value: m.nowLocal,
      "aria-label": "now (Cairo wall-clock time)",
      oninput: function (e) {
        m.nowLocal = e.target.value;
        changed();
      },
      onchange: function (e) {
        m.nowLocal = e.target.value;
        changed();
      }
    });
    const offsetSelect = select(
      [
        { value: "", label: "no offset" },
        { value: "+02:00", label: "+02:00" },
        { value: "+03:00", label: "+03:00" }
      ],
      m.nowOffset,
      function (v) {
        m.nowOffset = v;
        changed();
      },
      { "aria-label": "UTC offset (only for the repeated autumn hour)" }
    );
    const nowStatus = h("span", { class: "now-status" });
    live(function () {
      const info = M.nowInfo(m.nowLocal, m.nowOffset);
      nowStatus.textContent = "";
      if (m.nowLocal && !nowInput.value) {
        append(nowStatus, h("span", { class: "bad", text: "The stored value " + m.nowLocal + " cannot be shown in the picker; pick the time again. " }));
      }
      if (info.weekday) append(nowStatus, h("strong", { text: info.weekday }));
      if (info.offsets && info.offsets.length === 1) append(nowStatus, " · Cairo " + info.offsets[0] + (info.offsets[0] === "+03:00" ? " (summer time)" : " (winter time)"));
      if (info.error && m.nowLocal) append(nowStatus, h("span", { class: "bad", text: " · " + info.error }));
      if (info.note) append(nowStatus, h("span", { class: "help", text: " · " + info.note }));
    });

    const genderField = h(
      "fieldset",
      { class: "field radios" },
      h("legend", { class: "field-label", text: "Speaker gender (constant across the six texts)" }),
      S.genders.map(function (g) {
        return h(
          "label",
          { class: "radio" },
          h("input", {
            type: "radio",
            name: "gender",
            value: g,
            checked: m.gender === g,
            "data-fk": "meta-gender-" + g,
            onchange: function () {
              m.gender = g;
              changed();
            }
          }),
          g === "f" ? "f (female)" : "m (male)"
        );
      })
    );

    const registerSelect = select(
      [{ value: "", label: "choose…" }].concat(
        S.registers.map(function (r) {
          return { value: r, label: r };
        })
      ),
      m.register,
      function (v) {
        m.register = v;
        changed();
      }
    );

    const batchSelect = select(
      S.authoring_batches.map(function (b) {
        return { value: b, label: b };
      }),
      m.authoringBatch,
      function (v) {
        m.authoringBatch = v;
        if (v !== "pilot") m.fixedAfterPilot = false;
        changed(true);
      }
    );
    const fixedBox = h("input", {
      type: "checkbox",
      checked: m.fixedAfterPilot,
      disabled: m.authoringBatch !== "pilot",
      onchange: function (e) {
        m.fixedAfterPilot = e.target.checked;
        changed();
      }
    });

    main.appendChild(
      section(
        "Scenario",
        h(
          "div",
          { class: "grid-2" },
          field("Domain", domainSelect, "Pilot domains: clinic and banking."),
          field("ID", idControl, pathHint),
          field("Behaviour", behaviourSelect, behaviourNote),
          field("harm_type", harmSelect, "refuse items only."),
          field("control_of", controlInput, "act or inform controls only: the refuse twin they mirror."),
          field("Register", registerSelect, null),
          h(
            "div",
            { class: "field field-wide" },
            h("span", { class: "field-label", text: "now (Africa/Cairo wall-clock time, with seconds)" }),
            h("span", { class: "now-control" }, nowInput, offsetSelect),
            nowStatus,
            h("span", { class: "help", text: "The weekday is computed. Give an offset only for the repeated hour when summer time ends." })
          ),
          genderField,
          field("Authoring batch", batchSelect, null),
          h(
            "label",
            { class: "field check" },
            fixedBox,
            h("span", null, "fixed_after_pilot ", h("span", { class: "help", text: "(pilot items changed after the pilot)" }))
          )
        ),
        h(
          "p",
          { class: "fixed-values" },
          "Fixed: schema_version ",
          code(S.schema_version),
          " · reply_language ",
          code(S.reply_language),
          " · provenance ",
          code(M.HAND),
          " on every column of a new scenario",
          drafted.length
            ? [" · ", drafted.length + " drafted by the assistant (", code(M.ASSISTANT_DRAFT), "): ", draftList(drafted)]
            : null
        )
      )
    );

    main.appendChild(
      section(
        "What this behaviour requires",
        h(
          "ul",
          { class: "rules" },
          M.behaviourSummary(m.behaviour).map(function (line) {
            return h("li", { text: line });
          })
        )
      )
    );

    main.appendChild(changelogSection());
    main.appendChild(culturalTagsSection());
    main.appendChild(issuesPanel("meta"));
  }

  function changelogSection() {
    const m = state.draft.meta;
    const rows = m.changelog.map(function (entry, index) {
      return h(
        "tr",
        null,
        h("td", { class: "mono", text: String(entry.revision) }),
        h(
          "td",
          null,
          h("input", {
            type: "date",
            value: entry.date,
            "aria-label": "date of revision " + entry.revision,
            onchange: function (e) {
              entry.date = e.target.value;
              changed();
            }
          })
        ),
        h(
          "td",
          { class: "wide" },
          h("input", {
            type: "text",
            dir: "auto",
            autocomplete: "off",
            placeholder: "type the changelog note",
            "aria-label": "note of revision " + entry.revision,
            "data-fk": "changelog-note-" + index,
            value: entry.note,
            oninput: function (e) {
              entry.note = e.target.value;
              changed();
            }
          })
        )
      );
    });
    return section(
      "Revision and changelog",
      h("p", { class: "help" }, "Current revision: ", h("strong", { text: String(m.revision) }), ". Each change to a saved scenario adds an entry."),
      h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", { text: "rev." }), h("th", { text: "date" }), h("th", { text: "note" }))), h("tbody", null, rows)),
      h(
        "div",
        { class: "row-actions" },
        h("button", {
          type: "button",
          class: "small",
          text: "Add revision",
          onclick: function () {
            const next = Number(m.revision) + 1;
            m.changelog.push({ revision: next, date: M.todayIso(), note: "" });
            m.revision = next;
            changed(true);
          }
        }),
        h("button", {
          type: "button",
          class: "small secondary",
          text: "Remove last entry",
          disabled: m.changelog.length <= 1,
          onclick: function () {
            const last = m.changelog[m.changelog.length - 1];
            if (last.note && !window.confirm("Remove revision " + last.revision + " and its note?")) return;
            m.changelog.pop();
            m.revision = m.changelog.length ? m.changelog[m.changelog.length - 1].revision : 1;
            changed(true);
          }
        })
      )
    );
  }

  function culturalTagsSection() {
    const d = state.draft;
    const count = h("span", { class: "help" });
    live(function () {
      count.textContent = d.phenomena.length + " chosen (a scenario usually carries 2-3; ★ = the six core tags)";
    });
    return section(
      "Cultural phenomena (scenario tags)",
      count,
      h(
        "div",
        { class: "tag-grid" },
        S.cultural_tags.map(function (tag) {
          const on = d.phenomena.indexOf(tag) >= 0;
          return h(
            "label",
            { class: "tag" + (on ? " on" : "") },
            h("input", {
              type: "checkbox",
              checked: on,
              "data-fk": "ctag-" + tag,
              onchange: function (e) {
                if (e.target.checked) {
                  if (d.phenomena.indexOf(tag) < 0) d.phenomena.push(tag);
                } else {
                  d.phenomena = d.phenomena.filter(function (t) {
                    return t !== tag;
                  });
                }
                changed(true);
              }
            }),
            h("span", { class: "mono", text: tag }),
            M.CORE_TAGS.indexOf(tag) >= 0 ? h("span", { class: "core", title: "core tag", text: " ★" }) : null
          );
        })
      ),
      h("p", { class: "help", text: "Whether each tag is realised in each column is ticked on the review step." })
    );
  }

  // ------------------------------------------------------------------ step 2: slots

  function renderSlots(main) {
    const d = state.draft;
    const rules = M.behaviourRules(d.meta.behaviour);
    main.appendChild(
      h(
        "p",
        { class: "lead" },
        "The normalised meaning all six texts carry: ISO dates (YYYY-MM-DD), HH:MM, E.164 phones, integer EGP, record ids, enum values. A field that admits several values is a list. ",
        code("intent"),
        " is required."
      )
    );

    const body = h("tbody");
    d.slots.forEach(function (row, index) {
      body.appendChild(slotRowView(row, index));
    });

    main.appendChild(
      section(
        "Slot table",
        h(
          "table",
          { class: "table slots" },
          h("thead", null, h("tr", null, h("th", { text: "key" }), h("th", { text: "type" }), h("th", { text: "value" }), h("th", { text: "note" }), h("th", { text: "" }))),
          body
        ),
        h(
          "div",
          { class: "row-actions" },
          h("button", {
            type: "button",
            class: "small",
            text: "Add slot",
            "data-fk": "slot-add",
            onclick: function () {
              d.slots.push({ key: "", type: "string", value: "" });
              changed(true);
              const keys = document.querySelectorAll(".slot-key");
              if (keys.length) keys[keys.length - 1].focus();
            }
          })
        )
      )
    );

    const clarify = h("select", {
      disabled: rules.expected_clarification !== "required" && !d.expectedClarification,
      onchange: function (e) {
        d.expectedClarification = e.target.value;
        changed();
      }
    });
    live(function () {
      const keys = d.slots
        .map(function (r) {
          return r.key;
        })
        .filter(function (k, i, all) {
          return k && all.indexOf(k) === i;
        });
      const wanted = [""].concat(keys);
      if (d.expectedClarification && wanted.indexOf(d.expectedClarification) < 0) wanted.push(d.expectedClarification);
      const signature = wanted.join("\u0000");
      if (clarify.getAttribute("data-sig") !== signature) {
        clarify.textContent = "";
        wanted.forEach(function (k) {
          clarify.appendChild(h("option", { value: k, text: k || (rules.expected_clarification === "required" ? "choose a slot…" : "not used") }));
        });
        clarify.setAttribute("data-sig", signature);
      }
      clarify.value = d.expectedClarification;
    });
    main.appendChild(
      section(
        "Expected clarification",
        field(
          "expected.expected_clarification",
          clarify,
          rules.expected_clarification === "required"
            ? "ask items: the slot the clarifying question must be about."
            : "Only ask items have one" + (d.meta.behaviour ? " (this is " + d.meta.behaviour + ")." : "; choose the behaviour on step 1.")
        )
      )
    );
    main.appendChild(issuesPanel("slots"));
  }

  function slotRowView(row, index) {
    const d = state.draft;
    const keyInput = h("input", {
      type: "text",
      class: "mono slot-key",
      dir: "ltr",
      autocomplete: "off",
      spellcheck: "false",
      placeholder: "key",
      "aria-label": "slot key",
      "data-fk": "slot-key-" + index,
      value: row.key,
      oninput: function (e) {
        row.key = e.target.value.trim();
        changed();
      }
    });
    const typeSelect = select(
      M.SLOT_TYPES.map(function (t) {
        return { value: t, label: t };
      }),
      row.type,
      function (v) {
        row.type = v;
        changed(true);
      },
      { "aria-label": "slot type", "data-fk": "slot-type-" + index }
    );
    let valueControl;
    const valueProps = {
      "aria-label": "slot value",
      "data-fk": "slot-value-" + index,
      autocomplete: "off",
      spellcheck: "false",
      oninput: function (e) {
        row.value = e.target.value;
        changed();
      }
    };
    if (row.type === "boolean") {
      valueControl = select(
        [
          { value: "", label: "choose…" },
          { value: "true", label: "true" },
          { value: "false", label: "false" }
        ],
        row.value,
        function (v) {
          row.value = v;
          changed();
        },
        { "aria-label": "slot value", "data-fk": "slot-value-" + index }
      );
    } else if (row.type === "null") {
      valueControl = h("span", { class: "mono muted", text: "null" });
    } else if (row.type === "list") {
      valueControl = h("input", Object.assign({ type: "text", class: "mono", dir: "ltr", placeholder: "JSON array", value: row.value }, valueProps));
    } else if (row.type === "integer") {
      valueControl = h("input", Object.assign({ type: "text", class: "mono", dir: "ltr", inputmode: "numeric", placeholder: "integer", value: row.value }, valueProps));
    } else {
      valueControl = h("input", Object.assign({ type: "text", class: "mono", dir: "auto", placeholder: "type the value", value: row.value }, valueProps));
    }
    const note = h("span", { class: "slot-note" });
    live(function () {
      const value = M.slotValue(row);
      note.textContent = "";
      note.className = "slot-note";
      if (!value.ok) {
        note.className = "slot-note bad";
        note.textContent = value.error;
        return;
      }
      const items = Array.isArray(value.value) ? value.value : [value.value];
      const hints = [];
      items.forEach(function (item) {
        const info = typeof item === "string" ? M.dateHint(item, d.meta.nowLocal) : null;
        if (info) hints.push(info.weekday + (info.days === null ? "" : " · " + relativeDays(info.days)));
      });
      note.textContent = hints.join("; ");
    });
    const move = function (delta) {
      const target = index + delta;
      if (target < 0 || target >= d.slots.length) return;
      const tmp = d.slots[target];
      d.slots[target] = d.slots[index];
      d.slots[index] = tmp;
      changed(true);
    };
    return h(
      "tr",
      null,
      h("td", null, keyInput),
      h("td", null, typeSelect),
      h("td", { class: "wide" }, valueControl),
      h("td", null, note),
      h(
        "td",
        { class: "nowrap" },
        h("button", { type: "button", class: "icon-button", "aria-label": "move up", title: "move up", text: "↑", disabled: index === 0, onclick: function () { move(-1); } }),
        h("button", { type: "button", class: "icon-button", "aria-label": "move down", title: "move down", text: "↓", disabled: index === d.slots.length - 1, onclick: function () { move(1); } }),
        h("button", {
          type: "button",
          class: "icon-button",
          "aria-label": "remove slot",
          title: "remove slot",
          text: "×",
          onclick: function () {
            if ((row.key || row.value) && !window.confirm("Remove the slot " + (row.key || "(no key)") + "?")) return;
            d.slots.splice(index, 1);
            changed(true);
          }
        })
      )
    );
  }

  function relativeDays(days) {
    if (days === 0) return "the day of now";
    if (days === 1) return "1 day after now";
    if (days === -1) return "1 day before now";
    return days > 0 ? days + " days after now" : -days + " days before now";
  }

  // ------------------------------------------------------------------ step 3: state and expectations

  function ruleBadge(rule) {
    const labels = {
      required: ["required", "required"],
      optional: ["optional", "optional"],
      unused: ["not used for this behaviour", "unused"],
      empty: ["must be empty for this behaviour", "unused"],
      patch: ["the changes after a successful episode", "optional"]
    };
    const l = labels[rule];
    return l ? badge(l[0], l[1]) : null;
  }

  function jsonArea(fieldName, options) {
    const d = state.draft;
    const opts = options || {};
    const rule = opts.rule || null;
    const id = "json-" + fieldName;
    const unusedEmpty = rule === "unused" && !d.json[fieldName].trim();
    const area = h("textarea", {
      id: id,
      class: "json mono",
      dir: "ltr",
      rows: String(opts.rows || 6),
      spellcheck: "false",
      autocomplete: "off",
      autocorrect: "off",
      autocapitalize: "off",
      disabled: unusedEmpty,
      placeholder: unusedEmpty ? "not used for this behaviour" : opts.placeholder || "",
      "data-fk": id,
      value: d.json[fieldName],
      oninput: function (e) {
        d.json[fieldName] = e.target.value;
        changed();
      }
    });
    const status = h("div", { class: "json-status" });
    live(function () {
      const r = M.parseJsonText(d.json[fieldName]);
      if (!r.ok) {
        status.className = "json-status bad";
        status.textContent = "JSON error: " + r.error;
      } else {
        status.className = "json-status good";
        status.textContent = r.empty ? "empty (saved as null)" : "valid JSON";
      }
      if (rule === "unused" && d.json[fieldName].trim()) {
        status.textContent += " · kept in the draft, saved as null for this behaviour";
      }
    });
    const format = h("button", {
      type: "button",
      class: "small secondary",
      text: "Format",
      disabled: unusedEmpty,
      onclick: function () {
        const r = M.parseJsonText(d.json[fieldName]);
        if (r.ok && !r.empty) {
          d.json[fieldName] = M.prettyJson(r.value);
          area.value = d.json[fieldName];
          changed();
        }
      }
    });
    return h(
      "div",
      { class: "json-field" },
      h("div", { class: "json-head" }, h("label", { for: id, class: "mono field-label", text: M.JSON_PATHS[fieldName] }), ruleBadge(rule), format),
      opts.help ? h("p", { class: "help" }, opts.help) : null,
      area,
      status,
      opts.after || null
    );
  }

  function renderStateStep(main) {
    const d = state.draft;
    const domain = d.meta.domain;
    const rules = M.behaviourRules(d.meta.behaviour);
    main.appendChild(
      h("p", { class: "lead", text: "JSON, written before any text: the state the episode starts from and the outcome that counts as success." })
    );

    // tools
    let toolsBody;
    if (!domain) {
      toolsBody = h("p", { class: "help", text: "Choose the domain on step 1 first." });
    } else {
      const known = M.domainTools(domain);
      const names = Object.keys(known);
      const extras = d.tools.filter(function (n) {
        return names.indexOf(n) < 0;
      });
      toolsBody = h(
        "div",
        null,
        h(
          "div",
          { class: "tag-grid" },
          names.map(function (name) {
            const on = d.tools.indexOf(name) >= 0;
            return h(
              "label",
              { class: "tag" + (on ? " on" : "") },
              h("input", {
                type: "checkbox",
                checked: on,
                "data-fk": "tool-" + name,
                onchange: function (e) {
                  const chosen = new Set(d.tools);
                  if (e.target.checked) chosen.add(name);
                  else chosen.delete(name);
                  d.tools = names
                    .filter(function (n) {
                      return chosen.has(n);
                    })
                    .concat(
                      d.tools.filter(function (n) {
                        return names.indexOf(n) < 0;
                      })
                    );
                  changed(true);
                }
              }),
              h("span", { class: "mono", text: name }),
              badge(known[name] ? "writes" : "reads", known[name] ? "write" : "read")
            );
          })
        ),
        extras.length ? h("p", { class: "bad", text: "Not " + domain + " tools: " + extras.join(", ") }) : null,
        h("p", { class: "help", text: "The full " + domain + " tool set is offered in every scenario." })
      );
    }
    main.appendChild(section("Tools offered", toolsBody));

    const identityKeys = { clinic: "patient_id, phone (optional)", banking: "customer_id, phone (optional)" };
    main.appendChild(
      section(
        "Authenticated user",
        jsonArea("user_identity", {
          rows: 4,
          rule: "required",
          help: domain && identityKeys[domain] ? "Keys for " + domain + ": " + identityKeys[domain] + "; string values." : "A JSON object of strings."
        })
      )
    );

    const skeleton = M.STATE_SKELETONS[domain];
    const parsedState = M.parseJsonText(d.json.initial_state);
    const stateIsEmpty = parsedState.ok && (parsedState.empty || (parsedState.value && typeof parsedState.value === "object" && Object.keys(parsedState.value).length === 0));
    const stateExtras = h(
      "div",
      { class: "row-actions" },
      skeleton
        ? h("button", {
            type: "button",
            class: "small secondary",
            text: "Insert the empty " + domain + " keys",
            disabled: !stateIsEmpty,
            title: "Keys only, every value empty; you fill them in.",
            onclick: function () {
              d.json.initial_state = M.prettyJson(skeleton);
              changed(true);
            }
          })
        : null,
      domain
        ? h(
            "details",
            { class: "shape" },
            h("summary", { text: "Record fields (" + domain + ")" }),
            h(
              "ul",
              { class: "mono small-list" },
              (M.STATE_SHAPES[domain] || []).map(function (line) {
                return h("li", { text: line });
              })
            )
          )
        : null
    );
    main.appendChild(
      section(
        "Initial state",
        jsonArea("initial_state", {
          rows: 18,
          help: "The domain state at turn 1 (clinic: with its calendar). user_identity is injected by the harness; do not repeat it here.",
          after: stateExtras
        })
      )
    );

    const writes = domain
      ? Object.keys(M.domainTools(domain)).filter(function (n) {
          return M.domainTools(domain)[n];
        })
      : [];
    const reads = domain
      ? Object.keys(M.domainTools(domain)).filter(function (n) {
          return !M.domainTools(domain)[n];
        })
      : [];
    main.appendChild(
      section(
        "Expected outcome",
        domain ? h("p", { class: "help" }, "Writes: ", code(writes.join(", ")), " · reads: ", code(reads.join(", "))) : null,
        jsonArea("end_state_patch", {
          rows: 6,
          rule: rules.end_state_patch === "empty" ? "empty" : "patch",
          help: "{\"<path>\": <value>}: the changes to initial_state after a successful episode; {} = unchanged."
        }),
        jsonArea("tool_calls", {
          rows: 6,
          rule: rules.tool_calls === "required" ? "required" : "empty",
          help: "[{\"name\": <write tool>, \"args\": {…}}]: normalised arguments; a list holds the acceptable values for a field."
        }),
        jsonArea("must_not_call", { rows: 3, help: "[<tool>, …]: tools never to call, reads included." }),
        jsonArea("read_calls", {
          rows: 4,
          rule: rules.read_calls,
          help: "inform items: [{\"name\": <read tool>, \"args\": {…}}]. Empty = null."
        }),
        jsonArea("answer_must_contain", {
          rows: 6,
          rule: rules.answer_must_contain,
          help: "[{\"value\": <normalised value>, \"forms\": [surface forms per column]}]. Empty = null."
        }),
        h("p", { class: "fixed-values" }, "expected.reply_language: ", code(S.reply_language), " (fixed)")
      )
    );
    main.appendChild(issuesPanel("state"));
  }

  // ------------------------------------------------------------------ steps 4-9: the six texts

  function textClass(column) {
    return M.COLUMN_INFO[column].script === "arabic" ? "text text-arabic" : "text text-latin";
  }

  function textView(column, value, extraClass) {
    const info = M.COLUMN_INFO[column];
    if (!value) return h("p", { class: "missing", text: "(empty)" });
    return h("div", { class: textClass(column) + " text-view" + (extraClass ? " " + extraClass : ""), dir: info.dir, lang: info.lang, text: value });
  }

  function referenceText(column) {
    const d = state.draft;
    const block = d.texts[column];
    const rules = M.behaviourRules(d.meta.behaviour);
    const info = M.COLUMN_INFO[column];
    return h(
      "div",
      { class: "ref-text" },
      h("h4", { text: info.label }),
      textView(column, block.text),
      rules.follow_up === "required" ? [h("p", { class: "sub-label", text: "follow_up" }), textView(column, block.follow_up)] : null,
      rules.confirm_yes === "required" ? [h("p", { class: "sub-label", text: "confirm_yes" }), textView(column, block.confirm_yes)] : null,
      M.isCs(column) && block.insertions.length
        ? h(
            "p",
            { class: "help" },
            "insertions: ",
            block.insertions.map(function (i, n) {
              return [n ? ", " : "", h("span", { class: "mono", dir: "ltr", text: i.text }), i.tool_cue ? " (tool cue)" : ""];
            })
          )
        : null
    );
  }

  function summaryList(blind) {
    const d = state.draft;
    const m = d.meta;
    const now = M.nowInfo(m.nowLocal, m.nowOffset);
    const rows = [
      ["domain", m.domain || "—"],
      ["behaviour", m.behaviour || "—"],
      ["register", m.register || "—"],
      ["speaker", m.gender === "f" ? "female" : m.gender === "m" ? "male" : "—"],
      ["now", now.error ? m.nowLocal || "—" : now.date + " " + now.local.slice(11, 16) + " (" + now.weekday + ")"],
      ["cultural tags", d.phenomena.length ? d.phenomena.join(", ") : "—"]
    ];
    if (blind) rows.push(["realise", "the same hedges, idioms and register as the scenario carries"]);
    return h(
      "dl",
      { class: "summary" },
      rows.map(function (r) {
        return [h("dt", { text: r[0] }), h("dd", { class: r[0] === "cultural tags" ? "mono" : null, text: r[1] })];
      })
    );
  }

  function slotTableView() {
    const d = state.draft;
    if (!d.slots.length) return h("p", { class: "help", text: "No slots yet." });
    return h(
      "table",
      { class: "table compact" },
      h(
        "tbody",
        null,
        d.slots.map(function (row) {
          const value = M.slotValue(row);
          const shown = row.type === "null" ? "null" : row.type === "string" ? row.value : value.ok ? JSON.stringify(value.value) : row.value;
          const items = value.ok ? (Array.isArray(value.value) ? value.value : [value.value]) : [];
          const dates = items
            .map(function (item) {
              const info = typeof item === "string" ? M.dateHint(item, d.meta.nowLocal) : null;
              return info ? info.weekday : null;
            })
            .filter(Boolean);
          return h(
            "tr",
            null,
            h("th", { class: "mono", text: row.key || "(no key)" }),
            h("td", { class: "mono", dir: "auto", text: shown }),
            h("td", { class: "help", text: dates.join(", ") })
          );
        })
      )
    );
  }

  function jsonView(fieldName, transform) {
    const d = state.draft;
    const raw = d.json[fieldName];
    const r = M.parseJsonText(raw);
    let text;
    if (!r.ok) text = raw + "\n(invalid JSON)";
    else if (r.empty) text = "null";
    else text = M.prettyJson(transform ? transform(r.value) : r.value);
    return h("div", { class: "json-view" }, h("p", { class: "sub-label mono", text: M.JSON_PATHS[fieldName] }), h("pre", { class: "mono", dir: "ltr", text: text }));
  }

  function expectationsView(blind) {
    const d = state.draft;
    const rules = M.behaviourRules(d.meta.behaviour);
    const parts = [];
    if (rules.expected_clarification === "required") {
      parts.push(h("p", null, "expected_clarification: ", code(d.expectedClarification || "—")));
    }
    parts.push(jsonView("tool_calls"));
    parts.push(jsonView("end_state_patch"));
    parts.push(jsonView("must_not_call"));
    if (rules.read_calls === "required") parts.push(jsonView("read_calls"));
    if (rules.answer_must_contain !== "unused") {
      if (blind) {
        parts.push(
          jsonView("answer_must_contain", function (value) {
            return Array.isArray(value)
              ? value.map(function (item) {
                  return item && typeof item === "object" && "value" in item ? { value: item.value } : item;
                })
              : value;
          })
        );
        parts.push(h("p", { class: "help", text: "Surface forms are hidden on the blind steps; only the values are shown." }));
      } else {
        parts.push(jsonView("answer_must_contain"));
      }
    }
    return parts;
  }

  function contextPane(column) {
    const blind = M.BLIND_COLUMNS.indexOf(column) >= 0;
    const references = { egy: [], arabizi: ["egy"], cs: ["egy"], cs_latin: ["arabizi", "cs"], en: [], msa: [] }[column];
    const pane = h("aside", { class: "context", "aria-label": "Reference" });
    if (blind) {
      pane.appendChild(
        h(
          "div",
          { class: "blind-banner" },
          h("strong", { text: "Blind step." }),
          " The EGY, Arabizi, CS and CS-Latin texts are not on this page. Write from the slot table and the expectations: adaptation, never translation."
        )
      );
    }
    if (references.length) {
      pane.appendChild(
        h(
          "div",
          { class: "card ref" },
          h("h3", { text: column === "cs_latin" ? "Derive from the Arabizi wording and the CS insertions" : "Derive from the EGY wording" }),
          references.map(referenceText)
        )
      );
    }
    pane.appendChild(h("div", { class: "card ref" }, h("h3", { text: "Scenario" }), summaryList(blind)));
    pane.appendChild(h("div", { class: "card ref" }, h("h3", { text: "Slot table" }), slotTableView()));
    if (references.length) {
      pane.appendChild(h("details", { class: "card ref" }, h("summary", { text: "Expectations" }), expectationsView(blind)));
    } else {
      pane.appendChild(h("div", { class: "card ref" }, h("h3", { text: "Expectations" }), expectationsView(blind)));
    }
    pane.appendChild(
      h(
        "details",
        { class: "card ref" },
        h("summary", { text: "Initial state and user identity" }),
        jsonView("user_identity"),
        jsonView("initial_state")
      )
    );
    return pane;
  }

  function meter(column, fieldName, withRatio) {
    const d = state.draft;
    const el = h("div", { class: "meter" });
    const blind = M.BLIND_COLUMNS.indexOf(column) >= 0;
    live(function () {
      const text = d.texts[column][fieldName];
      const words = M.countWords(text);
      el.textContent = "";
      append(el, words + (words === 1 ? " word" : " words"));
      if (!withRatio || column === "egy") return;
      if (blind && !state.prefs.showRatioBlind) return;
      const info = M.lengthInfo(d, column);
      if (info.ratio === null) {
        append(el, h("span", { class: "muted", text: info.egyWords ? "" : " · ratio to EGY appears once EGY has text" }));
        return;
      }
      append(
        el,
        " · ",
        h("span", { class: info.inBand ? "good" : "warn", text: "ratio to EGY " + info.ratio.toFixed(2) }),
        h("span", { class: "muted", text: " (band " + S.length_ratio[0] + "–" + S.length_ratio[1] + ", a hint)" })
      );
      if (info.charRatio !== null) {
        append(el, " · ", h("span", { class: info.charInBand ? "muted" : "warn", text: "characters " + info.charRatio.toFixed(2) }));
      }
    });
    return el;
  }

  function textField(column, fieldName, options) {
    const d = state.draft;
    const block = d.texts[column];
    const info = M.COLUMN_INFO[column];
    const id = "text-" + column + "-" + fieldName;
    const unused = options.rule === "unused";
    const area = h("textarea", {
      id: id,
      class: textClass(column) + (unused ? " unused" : ""),
      dir: info.dir,
      lang: info.lang,
      rows: String(options.rows || 3),
      placeholder: options.placeholder,
      spellcheck: column === "en" ? "true" : "false",
      autocorrect: "off",
      autocapitalize: "off",
      autocomplete: "off",
      "data-fk": id,
      value: block[fieldName],
      oninput: function (e) {
        block[fieldName] = e.target.value;
        changed();
      }
    });
    return h(
      "div",
      { class: "text-field" },
      h(
        "div",
        { class: "json-head" },
        h("label", { for: id, class: "field-label" }, options.label),
        options.rule === "required" ? badge("required for " + d.meta.behaviour, "required") : null,
        unused ? badge("kept in the draft, not saved for " + (d.meta.behaviour || "this behaviour"), "unused") : null
      ),
      area,
      meter(column, fieldName, options.ratio === true)
    );
  }

  function insertionsEditor(column) {
    const d = state.draft;
    const list = d.texts[column].insertions;
    const count = h("p", { class: "help" });
    live(function () {
      const n = list.length;
      const ok = n >= S.insertions[0] && n <= S.insertions[1];
      count.className = ok ? "help" : "help warn";
      count.textContent = n + " declared · CS needs " + S.insertions[0] + "-" + S.insertions[1] + " English content insertions (a phrase counts as one; ok, please, thanks do not count)";
    });
    const rows = list.map(function (item, index) {
      return h(
        "div",
        { class: "insertion-row" },
        h("input", {
          type: "text",
          class: "text-latin",
          dir: "ltr",
          lang: "en",
          autocomplete: "off",
          spellcheck: "false",
          placeholder: "type the inserted English word or phrase",
          "aria-label": "insertion " + (index + 1),
          "data-fk": "ins-" + column + "-" + index,
          value: item.text,
          oninput: function (e) {
            item.text = e.target.value;
            changed();
          }
        }),
        h(
          "label",
          { class: "check" },
          h("input", {
            type: "checkbox",
            checked: item.tool_cue,
            "data-fk": "ins-cue-" + column + "-" + index,
            onchange: function (e) {
              item.tool_cue = e.target.checked;
              changed();
            }
          }),
          " tool_cue"
        ),
        h("button", {
          type: "button",
          class: "icon-button",
          "aria-label": "remove insertion " + (index + 1),
          text: "×",
          onclick: function () {
            list.splice(index, 1);
            changed(true);
          }
        })
      );
    });
    const source = d.texts.cs.insertions;
    return section(
      "Insertions (" + M.COLUMN_INFO[column].label + ")",
      count,
      rows,
      h(
        "div",
        { class: "row-actions" },
        h("button", {
          type: "button",
          class: "small",
          text: "Add insertion",
          onclick: function () {
            list.push({ text: "", tool_cue: false });
            changed(true);
          }
        }),
        column === "cs_latin"
          ? h("button", {
              type: "button",
              class: "small secondary",
              text: "Copy your CS insertion list",
              disabled: source.length === 0,
              title: "CS-Latin carries the same insertions as CS, in order.",
              onclick: function () {
                if (list.length && !window.confirm("Replace the CS-Latin insertions with the CS list?")) return;
                d.texts.cs_latin.insertions = source.map(function (i) {
                  return { text: i.text, tool_cue: i.tool_cue };
                });
                changed(true);
              }
            })
          : null
      ),
      h("p", { class: "help", text: "tool_cue: the insertion names or nearly names a tool." })
    );
  }

  function renderColumnStep(main, column) {
    const d = state.draft;
    const block = d.texts[column];
    const info = M.COLUMN_INFO[column];
    const rules = M.behaviourRules(d.meta.behaviour);
    const blind = M.BLIND_COLUMNS.indexOf(column) >= 0;
    const editor = h("section", { class: "editor" });

    const origin = provenancePanel(column);
    if (origin) editor.appendChild(origin);
    editor.appendChild(
      textField(column, "text", {
        label: info.label + " text",
        placeholder: "type the " + info.name + " text",
        rows: 5,
        ratio: true
      })
    );
    if (rules.follow_up === "required" || block.follow_up) {
      editor.appendChild(
        textField(column, "follow_up", {
          label: "follow_up",
          placeholder: "type the " + info.name + " follow-up",
          rule: rules.follow_up
        })
      );
    }
    if (rules.confirm_yes === "required" || block.confirm_yes) {
      editor.appendChild(
        textField(column, "confirm_yes", {
          label: "confirm_yes",
          placeholder: "type the " + info.name + " confirmation",
          rule: rules.confirm_yes
        })
      );
    }
    if (!d.meta.behaviour) {
      editor.appendChild(h("p", { class: "help", text: "Choose the behaviour on step 1 to see whether this column needs a follow-up or a confirmation." }));
    } else if (rules.follow_up !== "required" && rules.confirm_yes !== "required") {
      editor.appendChild(h("p", { class: "help", text: d.meta.behaviour + " items have no follow-up and no confirmation." }));
    } else if (rules.follow_up === "required") {
      editor.appendChild(h("p", { class: "help", text: "follow_up: the answer to the expected clarification plus a confirmation." }));
    }

    if (M.isCs(column)) editor.appendChild(insertionsEditor(column));
    if (M.isLatinArabizi(column)) {
      editor.appendChild(
        h(
          "label",
          { class: "field check" },
          h("input", {
            type: "checkbox",
            checked: block.arabizi_profile === "house",
            onchange: function (e) {
              block.arabizi_profile = e.target.checked ? "house" : null;
              changed();
            }
          }),
          h("span", null, "arabizi_profile: ", code("house"), h("span", { class: "help", text: " (all headline Arabizi is house profile)" }))
        )
      );
    }
    if (column === "arabizi") editor.appendChild(variantSection());
    if (blind) {
      editor.appendChild(
        h(
          "label",
          { class: "field check" },
          h("input", {
            type: "checkbox",
            checked: state.prefs.showRatioBlind,
            onchange: function (e) {
              state.prefs.showRatioBlind = e.target.checked;
              savePrefs();
              refreshLive();
            }
          }),
          h("span", null, "Show the length ratio to EGY while writing blind ", h("span", { class: "help", text: "(a number only; untick for stricter blindness)" }))
        )
      );
    }
    editor.appendChild(issuesPanel(column, { blind: blind }));

    main.appendChild(h("div", { class: "split" }, contextPane(column), editor));
  }

  function variantSection() {
    const v = state.draft.arabiziVariant;
    const area = v.enabled
      ? h("textarea", {
          id: "text-arabizi-variant",
          class: "text text-latin",
          dir: "ltr",
          lang: "arz-Latn",
          rows: "3",
          placeholder: "type the Arabizi variant text",
          spellcheck: "false",
          autocorrect: "off",
          autocapitalize: "off",
          autocomplete: "off",
          "data-fk": "text-arabizi-variant",
          value: v.text,
          oninput: function (e) {
            v.text = e.target.value;
            changed();
          }
        })
      : null;
    const count = h("div", { class: "meter" });
    if (v.enabled) {
      live(function () {
        count.textContent = M.countWords(v.text) + " words";
      });
    }
    return section(
      "arabizi_variant (20 scenarios)",
      h(
        "label",
        { class: "field check" },
        h("input", {
          type: "checkbox",
          checked: v.enabled,
          "data-fk": "variant-enabled",
          onchange: function (e) {
            if (!e.target.checked && v.text && !window.confirm("Leave out the variant? Its text stays in the draft but is not saved.")) {
              e.target.checked = true;
              return;
            }
            v.enabled = e.target.checked;
            changed(true);
          }
        }),
        h("span", null, "This scenario carries an Arabizi variant (the house text re-spelled under the variant profile; profile ", code("variant"), ", provenance ", code(v.provenance), ")")
      ),
      v.enabled ? provenancePanel(M.VARIANT) : null,
      area,
      v.enabled ? count : null
    );
  }

  // ------------------------------------------------------------------ step 10: review

  function reviewCard(column) {
    const d = state.draft;
    const block = d.texts[column];
    const info = M.COLUMN_INFO[column];
    const rules = M.behaviourRules(d.meta.behaviour);
    const blind = M.BLIND_COLUMNS.indexOf(column) >= 0;
    const ratio = h("div", { class: "meter" });
    live(function () {
      const l = M.lengthInfo(d, column);
      ratio.textContent = "";
      append(ratio, l.words + " words");
      if (l.ratio !== null) {
        append(ratio, " · ", h("span", { class: l.inBand ? "good" : "warn", text: "ratio " + l.ratio.toFixed(2) }));
      }
      if (l.charRatio !== null) append(ratio, " · ", h("span", { class: l.charInBand ? "muted" : "warn", text: "chars " + l.charRatio.toFixed(2) }));
    });

    const natural = h(
      "fieldset",
      { class: "natural" },
      h("legend", { text: "natural (1-5)" }),
      [1, 2, 3, 4, 5].map(function (n) {
        return h(
          "label",
          { class: "radio" },
          h("input", {
            type: "radio",
            name: "natural-" + column,
            value: String(n),
            checked: block.natural === n,
            "data-fk": "natural-" + column + "-" + n,
            onchange: function () {
              block.natural = n;
              changed();
            }
          }),
          String(n)
        );
      })
    );

    const required = M.requiredOrthographic(column);
    const tags = h(
      "fieldset",
      { class: "ortho" },
      h("legend", { text: "orthographic tags" }),
      M.allowedOrthographic(column).map(function (tag) {
        return h(
          "label",
          { class: "check small-check" },
          h("input", {
            type: "checkbox",
            checked: block.phenomena.indexOf(tag) >= 0,
            "data-fk": "otag-" + column + "-" + tag,
            onchange: function (e) {
              if (e.target.checked) {
                if (block.phenomena.indexOf(tag) < 0) block.phenomena.push(tag);
              } else {
                block.phenomena = block.phenomena.filter(function (t) {
                  return t !== tag;
                });
              }
              changed();
            }
          }),
          h("span", { class: "mono", text: tag }),
          required.indexOf(tag) >= 0 ? h("span", { class: "help", text: " required" }) : null,
          S.noise_tags.indexOf(tag) >= 0 ? h("span", { class: "help", text: " noise" }) : null
        );
      })
    );

    return h(
      "article",
      { class: "col-card" },
      h(
        "header",
        null,
        h("h3", { text: info.label }),
        blind ? badge("written blind", "blind") : null,
        block.provenance === M.ASSISTANT_DRAFT ? draftBadge() : null,
        h("button", {
          type: "button",
          class: "small secondary",
          text: "Edit",
          onclick: function () {
            goTo(column);
          }
        })
      ),
      textView(column, block.text),
      rules.follow_up === "required" ? [h("p", { class: "sub-label", text: "follow_up" }), textView(column, block.follow_up)] : null,
      rules.confirm_yes === "required" ? [h("p", { class: "sub-label", text: "confirm_yes" }), textView(column, block.confirm_yes)] : null,
      M.isCs(column)
        ? h(
            "p",
            { class: "help" },
            "insertions: ",
            block.insertions.length
              ? block.insertions.map(function (i, n) {
                  return [n ? ", " : "", h("span", { class: "mono", dir: "ltr", text: i.text || "(empty)" }), i.tool_cue ? " (tool cue)" : ""];
                })
              : "none"
          )
        : null,
      M.isLatinArabizi(column) ? h("p", { class: "help" }, "arabizi_profile: ", code(block.arabizi_profile || "none")) : null,
      column === "arabizi" && d.arabiziVariant.enabled
        ? [
            h(
              "p",
              { class: "sub-label" },
              "arabizi_variant",
              d.arabiziVariant.provenance === M.ASSISTANT_DRAFT ? [" ", draftBadge()] : null
            ),
            textView("arabizi", d.arabiziVariant.text),
            provenanceLine(M.VARIANT)
          ]
        : null,
      ratio,
      natural,
      tags,
      provenanceLine(column)
    );
  }

  function realisedSection() {
    const d = state.draft;
    if (!d.phenomena.length) {
      return section("phenomenon_realised", h("p", { class: "help", text: "No cultural tags chosen. Tick them below or on step 1." }));
    }
    const head = h(
      "tr",
      null,
      h("th", { text: "tag" }),
      M.AUTHORING_ORDER.map(function (column) {
        return h("th", { text: M.COLUMN_INFO[column].label });
      }),
      h("th", { text: "" })
    );
    const rows = d.phenomena.map(function (tag) {
      const cells = M.AUTHORING_ORDER.map(function (column) {
        const realised = d.texts[column].realised;
        return h(
          "td",
          { class: "center" },
          h("input", {
            type: "checkbox",
            checked: realised[tag] === true,
            "aria-label": tag + " realised in " + M.COLUMN_INFO[column].label,
            "data-fk": "real-" + tag + "-" + column,
            onchange: function (e) {
              realised[tag] = e.target.checked;
              changed();
            }
          })
        );
      });
      return h(
        "tr",
        null,
        h("th", { class: "mono", text: tag }),
        cells,
        h(
          "td",
          null,
          h("button", {
            type: "button",
            class: "small secondary",
            text: "all / none",
            onclick: function () {
              const all = M.AUTHORING_ORDER.every(function (c) {
                return d.texts[c].realised[tag] === true;
              });
              M.AUTHORING_ORDER.forEach(function (c) {
                d.texts[c].realised[tag] = !all;
              });
              changed(true);
            }
          })
        )
      );
    });
    return section(
      "phenomenon_realised",
      h("p", { class: "help", text: "Is the feature present in this text? An unticked box is saved as false." }),
      h("div", { class: "scroll-x" }, h("table", { class: "table realised" }, h("thead", null, head), h("tbody", null, rows)))
    );
  }

  function canarySection() {
    const d = state.draft;
    const input = h("input", {
      type: "text",
      class: "mono canary",
      dir: "ltr",
      autocomplete: "off",
      spellcheck: "false",
      placeholder: "load canary.txt or paste the project canary",
      "aria-label": "canary",
      "data-fk": "canary",
      value: d.canary,
      oninput: function (e) {
        d.canary = e.target.value.trim();
        changed();
      }
    });
    const status = h("p", { class: "help" });
    live(function () {
      const guid = M.canaryGuid(d.canary);
      status.textContent = "";
      if (!d.canary) append(status, h("span", { class: "warn", text: "Empty. " }));
      else if (!guid) append(status, h("span", { class: "warn", text: "Not in the canary format (prefix + lowercase uuid4). " }));
      else if (state.projectCanary && d.canary === state.projectCanary) append(status, h("span", { class: "good", text: "Matches canary.txt. " }));
      else if (state.projectCanary) append(status, h("span", { class: "warn", text: "Differs from canary.txt. " }));
      else append(status, "Well formed. ");
      append(status, state.projectCanary ? "canary.txt: " + (state.canarySource || "remembered") + "." : "canary.txt not loaded yet.");
    });
    return section(
      "Canary",
      input,
      status,
      h(
        "div",
        { class: "row-actions" },
        h("button", {
          type: "button",
          class: "small secondary",
          text: "Load canary.txt…",
          onclick: function () {
            byId("canary-input").click();
          }
        }),
        state.projectCanary && d.canary !== state.projectCanary
          ? h("button", {
              type: "button",
              class: "small",
              text: "Use the canary.txt value",
              onclick: function () {
                d.canary = state.projectCanary;
                changed(true);
              }
            })
          : null
      ),
      h("p", { class: "help", text: "Browsers do not let a page opened from disk read files next to it, so the first time, load tools/author/canary.txt here; the tool remembers it." })
    );
  }

  function checksSection() {
    const box = h("div");
    live(function () {
      const r = currentReport();
      box.textContent = "";
      if (!r.errors.length) {
        box.appendChild(h("p", { class: "ok-line", text: "No schema problems found. The lint still checks the language rules." }));
      } else {
        box.appendChild(h("p", { class: "issues-title", text: r.errors.length + " to fix before the file passes the schema" }));
        box.appendChild(
          h(
            "ul",
            { class: "problems" },
            r.errors.map(function (p) {
              return h("li", null, stepLink(p.step), " ", p.message);
            })
          )
        );
      }
      if (r.hints.length) {
        box.appendChild(h("p", { class: "issues-title", text: "Hints (the lint decides)" }));
        box.appendChild(
          h(
            "ul",
            { class: "hints" },
            r.hints.map(function (p) {
              return h("li", null, stepLink(p.step), " ", p.message);
            })
          )
        );
      }
    });
    return section("Checks", box);
  }

  function stepLink(stepId) {
    const step = stepById(stepId);
    if (!step) return null;
    return h("button", {
      type: "button",
      class: "step-link",
      text: stepIndex(stepId) + 1 + " " + step.title,
      onclick: function () {
        goTo(stepId);
      }
    });
  }

  function saveSection() {
    const d = state.draft;
    const target = h("p", { class: "help" });
    live(function () {
      const dom = d.meta.domain || "<domain>";
      target.textContent = "";
      append(target, "Save it as ", code("data/" + dom + "/" + M.fileName(d)), ". Chrome and Edge open a save dialog; other browsers download it.");
    });
    return section(
      "Save",
      target,
      h(
        "div",
        { class: "row-actions" },
        h("button", {
          type: "button",
          class: "primary",
          text: "Save JSON",
          onclick: function () {
            saveScenario("save");
          }
        }),
        h("button", {
          type: "button",
          class: "secondary",
          text: "Download a copy",
          onclick: function () {
            saveScenario("download");
          }
        })
      ),
      state.lastSaved
        ? lintReminder(state.lastSaved.name, state.lastSaved.domain, state.lastSaved.drafted)
        : h("p", { class: "help" }, "After saving, run ", code(LINT_COMMAND), " in the repo.")
    );
  }

  function previewSection() {
    const pre = h("pre", { class: "mono preview", dir: "ltr" });
    const details = h("details", { class: "card" }, h("summary", { text: "JSON preview" }), pre);
    live(function () {
      if (!details.open) return;
      const r = M.toDocument(state.draft);
      pre.textContent = r.blockers.length ? "Fix the JSON syntax on step 3 first." : M.stringify(r.doc);
    });
    details.addEventListener("toggle", refreshLive);
    return details;
  }

  function renderReview(main) {
    main.appendChild(h("p", { class: "lead", text: "All six columns side by side. Rate each one, tag it, tick what is realised, then save." }));
    main.appendChild(provenanceSection());
    main.appendChild(
      h(
        "div",
        { class: "columns-grid" },
        M.AUTHORING_ORDER.map(function (column) {
          return reviewCard(column);
        })
      )
    );
    main.appendChild(culturalTagsSection());
    main.appendChild(realisedSection());
    main.appendChild(canarySection());
    main.appendChild(checksSection());
    main.appendChild(saveSection());
    main.appendChild(previewSection());
  }

  // ------------------------------------------------------------------ files

  function canUseSavePicker() {
    return window.isSecureContext && typeof window.showSaveFilePicker === "function";
  }

  function canUseOpenPicker() {
    return window.isSecureContext && typeof window.showOpenFilePicker === "function";
  }

  const PICKER_TYPES = [{ description: "Scenario JSON", accept: { "application/json": [".json"] } }];

  function download(text, name) {
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 2000);
  }

  async function writableHandle(handle) {
    if (!handle || typeof handle.queryPermission !== "function") return handle;
    const options = { mode: "readwrite" };
    if ((await handle.queryPermission(options)) === "granted") return handle;
    if ((await handle.requestPermission(options)) === "granted") return handle;
    return null;
  }

  async function saveScenario(mode, anyway) {
    const r = M.validate(state.draft, { projectCanary: state.projectCanary });
    if (r.blocked) {
      notice("save", "error", "Not saved: fix the JSON syntax on step 3 first (" + r.errors[0].message + ").");
      return;
    }
    if (r.errors.length && !anyway) {
      // A fresh click is needed for the save dialog, so ask on the page, not with confirm().
      notice(
        "save",
        "warn",
        h(
          "div",
          null,
          h("p", null, r.errors.length + " problem(s) would make the schema reject this file, e.g. ", code(r.errors[0].message), ". The list is on the review step."),
          h(
            "div",
            { class: "row-actions" },
            h("button", {
              type: "button",
              class: "small",
              text: "Save anyway (work in progress)",
              onclick: function () {
                saveScenario(mode, true);
              }
            }),
            state.draft.step !== "review"
              ? h("button", {
                  type: "button",
                  class: "small secondary",
                  text: "Show the problems",
                  onclick: function () {
                    dismiss("save");
                    goTo("review");
                  }
                })
              : null
          )
        )
      );
      window.scrollTo(0, 0);
      return;
    }
    const text = M.stringify(r.doc);
    const name = M.fileName(state.draft);
    let savedName = null;
    if (mode === "save" && canUseSavePicker()) {
      try {
        let handle = state.fileHandle && state.fileHandle.name === name ? await writableHandle(state.fileHandle) : null;
        if (!handle) {
          handle = await window.showSaveFilePicker({ suggestedName: name, id: "afandem-scenarios", types: PICKER_TYPES });
        }
        const writable = await handle.createWritable();
        await writable.write(text);
        await writable.close();
        state.fileHandle = handle;
        savedName = handle.name;
      } catch (e) {
        if (e && e.name === "AbortError") return;
        savedName = null;
      }
    }
    if (!savedName) {
      download(text, name);
      savedName = name;
    }
    state.draft.savedText = text;
    state.draft.source = savedName;
    const saved = { name: savedName, domain: state.draft.meta.domain, drafted: M.assistantDrafts(state.draft) };
    state.lastSaved = saved;
    persistNow();
    notice("save", "ok", function () {
      return lintReminder(saved.name, saved.domain, saved.drafted);
    });
    render();
  }

  function decodeUtf8(buffer) {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  }

  function confirmReplace(action) {
    const d = state.draft;
    if (!M.hasContent(d) || !unsavedChanges()) return true;
    return window.confirm(action + " The current draft has changes that are not saved to a file; they will be lost.");
  }

  function loadText(text, name, handle) {
    if (!confirmReplace("Open " + name + "?")) return;
    const parsed = M.parseJsonText(text);
    if (!parsed.ok || parsed.empty) {
      notice("open", "error", name + " is not valid JSON" + (parsed.error ? ": " + parsed.error : "") + ".");
      return;
    }
    let loaded;
    try {
      loaded = M.fromDocument(parsed.value);
    } catch (e) {
      notice("open", "error", "Not opened: " + e.message + ".");
      return;
    }
    const draft = loaded.draft;
    const normalised = M.stringify(M.toDocument(draft).doc);
    draft.source = name;
    draft.savedText = normalised;
    draft.opened = { text: normalised, revision: draft.meta.revision };
    draft.step = "review";
    state.draft = draft;
    state.fileHandle = handle || null;
    state.lastSaved = null;
    dismiss("save");
    persistNow();
    const drafted = M.assistantDrafts(draft);
    const draftNote = drafted.length
      ? h(
          "p",
          null,
          "Drafted by the assistant (",
          code(M.ASSISTANT_DRAFT),
          "): ",
          draftList(drafted),
          ". They keep that label, however much you edit them, until you click “I rewrote or approved this column” for each."
        )
      : null;
    if (loaded.warnings.length) {
      notice(
        "open",
        "warn",
        h(
          "div",
          null,
          h("p", null, "Opened ", code(name), " with notes:"),
          h(
            "ul",
            null,
            loaded.warnings.map(function (w) {
              return h("li", { text: w });
            })
          ),
          draftNote
        )
      );
    } else {
      notice("open", drafted.length ? "info" : "ok", h("div", null, h("p", null, "Opened ", code(name), "."), draftNote));
    }
    render();
    window.scrollTo(0, 0);
  }

  async function openScenario() {
    if (canUseOpenPicker()) {
      try {
        const handles = await window.showOpenFilePicker({ id: "afandem-scenarios", types: PICKER_TYPES, multiple: false });
        const file = await handles[0].getFile();
        loadText(decodeUtf8(await file.arrayBuffer()), file.name, handles[0]);
        return;
      } catch (e) {
        if (e && e.name === "AbortError") return;
        if (e && e.name === "TypeError") {
          notice("open", "error", "Not opened: the file is not valid UTF-8.");
          return;
        }
      }
    }
    byId("open-input").click();
  }

  function onOpenInput(e) {
    const input = e.target;
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    file.arrayBuffer().then(
      function (buffer) {
        let text;
        try {
          text = decodeUtf8(buffer);
        } catch (err) {
          notice("open", "error", "Not opened: " + file.name + " is not valid UTF-8.");
          return;
        }
        loadText(text, file.name, null);
      },
      function () {
        notice("open", "error", "Could not read " + file.name + ".");
      }
    );
  }

  function freshDraft() {
    const d = M.emptyDraft(M.todayIso());
    d.canary = state.projectCanary || "";
    return d;
  }

  function newScenario() {
    if (!confirmReplace("Start a new scenario?")) return;
    state.draft = freshDraft();
    state.fileHandle = null;
    state.lastSaved = null;
    dismiss("save");
    dismiss("open");
    persistNow();
    render();
    window.scrollTo(0, 0);
  }

  function discardDraft() {
    if (!window.confirm("Discard this draft? Everything typed since the last file save is lost.")) return;
    removeStorage(DRAFT_KEY);
    state.draft = freshDraft();
    state.fileHandle = null;
    state.lastSaved = null;
    state.draftWrittenAt = null;
    state.notices = [];
    notice("discard", "info", "Draft discarded. This is a new, empty scenario.");
    render();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------------ canary.txt

  function setProjectCanary(text, source, ask) {
    const value = M.normaliseCanary(text);
    if (!value) return;
    state.projectCanary = value;
    state.canarySource = source;
    state.prefs.canary = value;
    savePrefs();
    const d = state.draft;
    if (!d.canary) {
      d.canary = value;
      schedulePersist();
    } else if (ask && d.canary !== value && window.confirm("Replace this scenario's canary with the canary.txt value?")) {
      d.canary = value;
      schedulePersist();
    }
    render();
  }

  function tryCanaryFile() {
    let xhr;
    try {
      xhr = new XMLHttpRequest();
      xhr.open("GET", "canary.txt", true);
      xhr.overrideMimeType("text/plain; charset=utf-8");
    } catch (e) {
      return;
    }
    xhr.onload = function () {
      if ((xhr.status === 200 || xhr.status === 0) && xhr.responseText && xhr.responseText.trim()) {
        setProjectCanary(xhr.responseText, "read from canary.txt", false);
      }
    };
    xhr.onerror = function () {
      /* file:// reads are usually blocked; the Load canary.txt button covers it */
    };
    try {
      xhr.send();
    } catch (e) {
      /* same */
    }
  }

  function onCanaryInput(e) {
    const input = e.target;
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    file.text().then(
      function (text) {
        setProjectCanary(text, "loaded from " + file.name, true);
      },
      function () {
        notice("canary", "error", "Could not read " + file.name + ".");
      }
    );
  }

  // ------------------------------------------------------------------ start

  function start() {
    loadPrefs();
    state.projectCanary = state.prefs.canary || "";
    if (state.projectCanary) state.canarySource = "remembered from an earlier load";
    const raw = readStorage(DRAFT_KEY);
    let restored = null;
    if (raw) {
      try {
        restored = M.reviveDraft(JSON.parse(raw));
      } catch (e) {
        restored = null;
      }
    }
    if (restored) {
      state.draft = restored;
      if (!restored.canary && state.projectCanary) restored.canary = state.projectCanary;
      if (M.hasContent(restored)) notice("restored", "info", "Your draft was restored from this browser.");
    } else {
      state.draft = freshDraft();
      if (raw) notice("restored", "warn", "A stored draft could not be read and was set aside; this is a new scenario.");
    }
    if (state.storage === "blocked") {
      notice("storage", "warn", "This browser blocks local storage for this page, so drafts are not kept. Save the JSON often.");
    }

    byId("btn-new").addEventListener("click", newScenario);
    byId("btn-open").addEventListener("click", openScenario);
    byId("btn-save").addEventListener("click", function () {
      saveScenario("save");
    });
    byId("btn-discard").addEventListener("click", discardDraft);
    byId("open-input").addEventListener("change", onOpenInput);
    byId("canary-input").addEventListener("change", onCanaryInput);
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        saveScenario("save");
      }
    });
    window.addEventListener("pagehide", function () {
      if (persistTimer) persistNow();
    });
    window.addEventListener("beforeunload", function (e) {
      if (persistTimer) persistNow();
      if (state.storage === "blocked" && M.hasContent(state.draft) && unsavedChanges()) {
        e.preventDefault();
        e.returnValue = "";
      }
    });
    window.addEventListener("storage", function (e) {
      if (e.key === DRAFT_KEY) {
        notice("other-tab", "warn", "The draft was changed in another tab of this tool. Keep one tab open; the last one to type wins.");
      }
    });

    render();
    tryCanaryFile();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
