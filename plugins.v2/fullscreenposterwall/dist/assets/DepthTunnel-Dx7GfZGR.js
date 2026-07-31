import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

function pickImageUrl(item, type, domain) {
  return pickImageCandidates(item, type, domain)[0] || "";
}
function pickImageCandidates(item, type, domain) {
  if (!item) return [];
  const paths = type === "poster" ? [item.poster_path, item.backdrop_path] : type === "logo" ? [item.thumb_path, item.fanart_poster_path, item.backdrop_path, item.poster_path] : [item.backdrop_path, item.poster_path];
  const base = domain || "https://image.tmdb.org/t/p/original";
  const urls = paths.filter((p) => !!p).map((p) => /^https?:\/\//.test(p) ? p : p.startsWith("/") ? base + p : base + "/" + p);
  return [...new Set(urls)];
}
const hostFailCount = /* @__PURE__ */ new Map();
const deadHosts = /* @__PURE__ */ new Set();
function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}
function noteHostFail(url) {
  const h = hostOf(url);
  if (!h) return;
  const n = (hostFailCount.get(h) || 0) + 1;
  hostFailCount.set(h, n);
  if (n >= 2) deadHosts.add(h);
}
function loadImageWithFallback(urls, timeoutMs = 1500) {
  const live = urls.filter((u) => !deadHosts.has(hostOf(u)));
  const list = live.length ? live : [...urls];
  return new Promise((resolve) => {
    const tryAt = (i) => {
      if (i >= list.length) return resolve("");
      const url = list[i];
      let settled = false;
      const img = new Image();
      const fail = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        img.src = "";
        noteHostFail(url);
        tryAt(i + 1);
      };
      const timer = setTimeout(fail, timeoutMs);
      img.onload = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(url);
      };
      img.onerror = fail;
      img.src = url;
    };
    tryAt(0);
  });
}
function hasNativeLogoImage(item) {
  return !!(item.thumb_path || item.fanart_poster_path);
}
function pickLogoUrl(item, domain) {
  const path = item.logo_path;
  if (!path) return "";
  if (/^https?:\/\//.test(path)) return path;
  if (path.startsWith("/")) return domain + path;
  return domain + "/" + path;
}

const {defineComponent:_defineComponent$7} = await importShared('vue');

const {createElementVNode:_createElementVNode$6,unref:_unref$6,openBlock:_openBlock$7,createElementBlock:_createElementBlock$7,createCommentVNode:_createCommentVNode$7,toDisplayString:_toDisplayString$6,createTextVNode:_createTextVNode$3,normalizeClass:_normalizeClass$4,Transition:_Transition$1,withCtx:_withCtx$1,createVNode:_createVNode$1} = await importShared('vue');

const _hoisted_1$7 = { class: "photos-root" };
const _hoisted_2$7 = ["src"];
const _hoisted_3$7 = { class: "photo-overlay" };
const _hoisted_4$7 = ["src"];
const _hoisted_5$7 = { key: 1 };
const _hoisted_6$5 = {
  key: 2,
  class: "photo-sub"
};
const _hoisted_7$5 = { key: 0 };
const _hoisted_8$2 = {
  key: 3,
  class: "photo-overview"
};
const {computed: computed$3,onMounted: onMounted$7,onBeforeUnmount: onBeforeUnmount$7,ref: ref$7,watch: watch$6} = await importShared('vue');
const _sfc_main$7 = /* @__PURE__ */ _defineComponent$7({
  __name: "PhotosSlideshow",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$7({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const currentIndex = ref$7(0);
    let timer;
    const current = computed$3(() => props.items[currentIndex.value] || null);
    const logoWide = ref$7(false);
    function onLogoLoad(e) {
      const i = e.target;
      logoWide.value = i.naturalWidth >= i.naturalHeight;
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function trimOverview(s, max = 160) {
      return s.length > max ? s.slice(0, max) + "…" : s;
    }
    function next() {
      if (!props.items.length) return;
      currentIndex.value = (currentIndex.value + 1) % props.items.length;
    }
    function startTimer() {
      if (timer) {
        clearInterval(timer);
        timer = void 0;
      }
      if (props.autoplay) {
        timer = window.setInterval(next, Math.max(2e3, props.interval * 1e3));
      }
    }
    onMounted$7(() => {
      startTimer();
    });
    onBeforeUnmount$7(() => {
      if (timer) clearInterval(timer);
    });
    watch$6(() => props.interval, () => startTimer());
    watch$6(() => props.items?.length, (n, old) => {
      if (!old || n !== old) startTimer();
    });
    return (_ctx, _cache) => {
      return _openBlock$7(), _createElementBlock$7("div", _hoisted_1$7, [
        _createVNode$1(_Transition$1, {
          name: "fade",
          mode: "out-in"
        }, {
          default: _withCtx$1(() => [
            current.value ? (_openBlock$7(), _createElementBlock$7("div", {
              key: currentIndex.value,
              class: "photo-frame"
            }, [
              _createElementVNode$6("img", {
                src: imageUrl(current.value),
                class: "photo-img",
                alt: ""
              }, null, 8, _hoisted_2$7),
              _createElementVNode$6("div", _hoisted_3$7, [
                _createElementVNode$6("div", {
                  class: _normalizeClass$4(["photo-meta", { "meta-center": logoWide.value }])
                }, [
                  __props.imageType === "logo" && !_unref$6(hasNativeLogoImage)(current.value) && logoUrl(current.value) ? (_openBlock$7(), _createElementBlock$7("img", {
                    key: 0,
                    src: logoUrl(current.value),
                    class: "meta-logo",
                    alt: "",
                    onLoad: onLogoLoad
                  }, null, 40, _hoisted_4$7)) : (_openBlock$7(), _createElementBlock$7("h1", _hoisted_5$7, _toDisplayString$6(current.value.title), 1)),
                  current.value.year || current.value.type ? (_openBlock$7(), _createElementBlock$7("p", _hoisted_6$5, [
                    _createTextVNode$3(_toDisplayString$6(current.value.year) + " ", 1),
                    current.value.year && current.value.type ? (_openBlock$7(), _createElementBlock$7("span", _hoisted_7$5, "·")) : _createCommentVNode$7("", true),
                    _createTextVNode$3(" " + _toDisplayString$6(current.value.type), 1)
                  ])) : _createCommentVNode$7("", true),
                  current.value.overview ? (_openBlock$7(), _createElementBlock$7("p", _hoisted_8$2, _toDisplayString$6(trimOverview(current.value.overview)), 1)) : _createCommentVNode$7("", true)
                ], 2)
              ])
            ])) : _createCommentVNode$7("", true)
          ]),
          _: 1
        })
      ]);
    };
  }
});

const PhotosSlideshow = /* @__PURE__ */ _export_sfc(_sfc_main$7, [["__scopeId", "data-v-5f839bc4"]]);

const {defineComponent:_defineComponent$6} = await importShared('vue');

const {renderList:_renderList$5,Fragment:_Fragment$5,openBlock:_openBlock$6,createElementBlock:_createElementBlock$6,createElementVNode:_createElementVNode$5,unref:_unref$5,createCommentVNode:_createCommentVNode$6,toDisplayString:_toDisplayString$5,normalizeStyle:_normalizeStyle$6} = await importShared('vue');

const _hoisted_1$6 = ["src", "alt"];
const _hoisted_2$6 = { class: "float-caption" };
const _hoisted_3$6 = ["src"];
const _hoisted_4$6 = {
  key: 1,
  class: "float-caption-title"
};
const _hoisted_5$6 = {
  key: 2,
  class: "float-caption-overview"
};
const {ref: ref$6,onMounted: onMounted$6,onBeforeUnmount: onBeforeUnmount$6} = await importShared('vue');
const MAX = 16;
const _sfc_main$6 = /* @__PURE__ */ _defineComponent$6({
  __name: "Floating",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$6({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const root = ref$6(null);
    const moving = ref$6([]);
    let raf;
    let lastSpawn = 0;
    let lastSwap = 0;
    let cursor = 0;
    let initialized = false;
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function trimOverview(s, max = 70) {
      return s && s.length > max ? s.slice(0, max) + "…" : s || "";
    }
    function spawn() {
      if (!props.items.length) return null;
      if (cursor >= props.items.length) cursor = 0;
      const item = props.items[cursor++];
      const w = window.innerWidth, h = window.innerHeight;
      const size = 240 + Math.random() * 300;
      const speed = 0.15 + Math.random() * 0.4;
      const angle = Math.random() * Math.PI * 2;
      return {
        item,
        x: Math.random() * (w - size),
        y: Math.random() * (h - size),
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size,
        rot: (Math.random() - 0.5) * 6,
        z: Math.random(),
        fade: 0
      };
    }
    function cardStyle(m) {
      return {
        transform: `translate(${m.x}px, ${m.y}px) rotate(${m.rot}deg)`,
        width: `${m.size}px`,
        height: `${m.size * 1.5}px`,
        zIndex: String(Math.floor(m.z * 100)),
        opacity: String(m.fade)
      };
    }
    function step(now) {
      const w = window.innerWidth, h = window.innerHeight;
      if (props.autoplay) {
        if (now - lastSwap > props.interval * 1e3) {
          const oldest = moving.value.reduce((a, b) => a.fade > b.fade ? b : a, moving.value[0]);
          if (oldest) {
            const fresh = spawn();
            if (fresh) {
              Object.assign(oldest, fresh);
            }
          }
          lastSwap = now;
        }
        if (moving.value.length < MAX && now - lastSpawn > 800) {
          const m = spawn();
          if (m) moving.value.push(m);
          lastSpawn = now;
        }
      } else if (!initialized) {
        while (moving.value.length < Math.min(MAX, props.items.length)) {
          const m = spawn();
          if (!m) break;
          moving.value.push(m);
        }
      }
      initialized = true;
      for (const m of moving.value) {
        m.x += m.vx;
        m.y += m.vy;
        if (m.x < -m.size * 0.3) {
          m.x = -m.size * 0.3;
          m.vx = Math.abs(m.vx);
        }
        if (m.x > w - m.size * 0.7) {
          m.x = w - m.size * 0.7;
          m.vx = -Math.abs(m.vx);
        }
        if (m.y < -m.size * 0.3) {
          m.y = -m.size * 0.3;
          m.vy = Math.abs(m.vy);
        }
        if (m.y > h - m.size * 0.5) {
          m.y = h - m.size * 0.5;
          m.vy = -Math.abs(m.vy);
        }
        m.fade = Math.min(1, m.fade + 0.02);
        m.rot += Math.sin((now / 1e3 + m.x) * 3e-4) * 0.02;
      }
      raf = requestAnimationFrame(step);
    }
    onMounted$6(() => {
      raf = requestAnimationFrame(step);
    });
    onBeforeUnmount$6(() => {
      if (raf) cancelAnimationFrame(raf);
    });
    return (_ctx, _cache) => {
      return _openBlock$6(), _createElementBlock$6("div", {
        ref_key: "root",
        ref: root,
        class: "float-root"
      }, [
        (_openBlock$6(true), _createElementBlock$6(_Fragment$5, null, _renderList$5(moving.value, (m, i) => {
          return _openBlock$6(), _createElementBlock$6("div", {
            key: m.item.tmdb_id || m.item.title,
            class: "float-card",
            style: _normalizeStyle$6(cardStyle(m))
          }, [
            _createElementVNode$5("img", {
              src: imageUrl(m.item),
              alt: m.item.title
            }, null, 8, _hoisted_1$6),
            _createElementVNode$5("div", _hoisted_2$6, [
              __props.imageType === "logo" && !_unref$5(hasNativeLogoImage)(m.item) && logoUrl(m.item) ? (_openBlock$6(), _createElementBlock$6("img", {
                key: 0,
                src: logoUrl(m.item),
                class: "meta-logo meta-logo-sm",
                alt: ""
              }, null, 8, _hoisted_3$6)) : (_openBlock$6(), _createElementBlock$6("div", _hoisted_4$6, _toDisplayString$5(m.item.title), 1)),
              m.item.overview ? (_openBlock$6(), _createElementBlock$6("div", _hoisted_5$6, _toDisplayString$5(trimOverview(m.item.overview, 70)), 1)) : _createCommentVNode$6("", true)
            ])
          ], 4);
        }), 128))
      ], 512);
    };
  }
});

const Floating = /* @__PURE__ */ _export_sfc(_sfc_main$6, [["__scopeId", "data-v-b43f3d57"]]);

const {defineComponent:_defineComponent$5} = await importShared('vue');

const {normalizeStyle:_normalizeStyle$5,createElementVNode:_createElementVNode$4,unref:_unref$4,openBlock:_openBlock$5,createElementBlock:_createElementBlock$5,createCommentVNode:_createCommentVNode$5,toDisplayString:_toDisplayString$4,normalizeClass:_normalizeClass$3,Transition:_Transition,withCtx:_withCtx,createVNode:_createVNode} = await importShared('vue');

const _hoisted_1$5 = { class: "vintage-root" };
const _hoisted_2$5 = ["src"];
const _hoisted_3$5 = { class: "vintage-frame" };
const _hoisted_4$5 = ["src"];
const _hoisted_5$5 = {
  key: 1,
  class: "vintage-title"
};
const _hoisted_6$4 = { class: "vintage-year" };
const _hoisted_7$4 = {
  key: 2,
  class: "vintage-overview"
};
const {computed: computed$2,onMounted: onMounted$5,onBeforeUnmount: onBeforeUnmount$5,ref: ref$5,watch: watch$5,nextTick} = await importShared('vue');
const _sfc_main$5 = /* @__PURE__ */ _defineComponent$5({
  __name: "VintagePrints",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$5({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const currentIndex = ref$5(0);
    const canvasRef = ref$5(null);
    const current = computed$2(() => props.items[currentIndex.value] || null);
    const imgStyle = ref$5({});
    const logoWide = ref$5(false);
    function onLogoLoad(e) {
      const i = e.target;
      logoWide.value = i.naturalWidth >= i.naturalHeight;
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function next() {
      if (props.items.length) currentIndex.value = (currentIndex.value + 1) % props.items.length;
    }
    function trimOverview(s, max = 120) {
      return s && s.length > max ? s.slice(0, max) + "…" : s || "";
    }
    let timer;
    watch$5(current, async () => {
      await nextTick();
      imgStyle.value = {
        filter: "sepia(0.55) saturate(0.85) contrast(1.05) brightness(0.95) hue-rotate(-8deg)"
      };
      drawGrain();
    });
    function drawGrain() {
      const c = canvasRef.value;
      if (!c) return;
      c.width = window.innerWidth;
      c.height = window.innerHeight;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, c.width, c.height);
      const grad = ctx.createRadialGradient(
        c.width / 2,
        c.height / 2,
        Math.min(c.width, c.height) * 0.4,
        c.width / 2,
        c.height / 2,
        Math.max(c.width, c.height) * 0.7
      );
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(1, "rgba(0,0,0,0.55)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, c.width, c.height);
      const id = ctx.getImageData(0, 0, c.width, c.height);
      const d = id.data;
      for (let i = 0; i < d.length; i += 4) {
        const n = (Math.random() - 0.5) * 38;
        d[i] = Math.max(0, Math.min(255, d[i] + n));
        d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + n));
        d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + n));
      }
      ctx.putImageData(id, 0, 0);
    }
    onMounted$5(() => {
      if (props.autoplay) timer = window.setInterval(next, Math.max(2500, props.interval * 1e3));
      window.addEventListener("resize", drawGrain);
    });
    onBeforeUnmount$5(() => {
      if (timer) clearInterval(timer);
      window.removeEventListener("resize", drawGrain);
    });
    return (_ctx, _cache) => {
      return _openBlock$5(), _createElementBlock$5("div", _hoisted_1$5, [
        _createVNode(_Transition, {
          name: "vintage-fade",
          mode: "out-in"
        }, {
          default: _withCtx(() => [
            current.value ? (_openBlock$5(), _createElementBlock$5("div", {
              key: currentIndex.value,
              class: "vintage-stage"
            }, [
              _createElementVNode$4("img", {
                src: imageUrl(current.value),
                class: "vintage-img",
                style: _normalizeStyle$5(imgStyle.value)
              }, null, 12, _hoisted_2$5),
              _createElementVNode$4("canvas", {
                ref_key: "canvasRef",
                ref: canvasRef,
                class: "vintage-canvas"
              }, null, 512),
              _createElementVNode$4("div", _hoisted_3$5, [
                _createElementVNode$4("div", {
                  class: _normalizeClass$3(["vintage-meta", { "meta-center": logoWide.value }])
                }, [
                  __props.imageType === "logo" && !_unref$4(hasNativeLogoImage)(current.value) && logoUrl(current.value) ? (_openBlock$5(), _createElementBlock$5("img", {
                    key: 0,
                    src: logoUrl(current.value),
                    class: "meta-logo",
                    alt: "",
                    onLoad: onLogoLoad
                  }, null, 40, _hoisted_4$5)) : (_openBlock$5(), _createElementBlock$5("div", _hoisted_5$5, _toDisplayString$4(current.value.title), 1)),
                  _createElementVNode$4("div", _hoisted_6$4, _toDisplayString$4(current.value.year), 1),
                  current.value.overview ? (_openBlock$5(), _createElementBlock$5("div", _hoisted_7$4, _toDisplayString$4(trimOverview(current.value.overview)), 1)) : _createCommentVNode$5("", true)
                ], 2)
              ])
            ])) : _createCommentVNode$5("", true)
          ]),
          _: 1
        })
      ]);
    };
  }
});

const VintagePrints = /* @__PURE__ */ _export_sfc(_sfc_main$5, [["__scopeId", "data-v-5c0e3850"]]);

const {defineComponent:_defineComponent$4} = await importShared('vue');

const {openBlock:_openBlock$4,createElementBlock:_createElementBlock$4,createCommentVNode:_createCommentVNode$4,createElementVNode:_createElementVNode$3,renderList:_renderList$4,Fragment:_Fragment$4,normalizeStyle:_normalizeStyle$4,unref:_unref$3,toDisplayString:_toDisplayString$3,createTextVNode:_createTextVNode$2,normalizeClass:_normalizeClass$2} = await importShared('vue');

const _hoisted_1$4 = ["src"];
const _hoisted_2$4 = { class: "light-orbs" };
const _hoisted_3$4 = ["src"];
const _hoisted_4$4 = {
  key: 1,
  class: "light-title"
};
const _hoisted_5$4 = { class: "light-sub" };
const _hoisted_6$3 = { key: 0 };
const _hoisted_7$3 = {
  key: 2,
  class: "light-overview"
};
const {ref: ref$4,onMounted: onMounted$4,onBeforeUnmount: onBeforeUnmount$4,computed: computed$1,watch: watch$4} = await importShared('vue');
const ORB_COUNT = 12;
const _sfc_main$4 = /* @__PURE__ */ _defineComponent$4({
  __name: "LightDance",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$4({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const currentIndex = ref$4(0);
    const current = computed$1(() => props.items[currentIndex.value] || null);
    const orbs = ref$4([]);
    const root = ref$4(null);
    let timer;
    let raf;
    const logoWide = ref$4(false);
    function onLogoLoad(e) {
      const i = e.target;
      logoWide.value = i.naturalWidth >= i.naturalHeight;
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function trimOverview(s, max = 120) {
      return s && s.length > max ? s.slice(0, max) + "…" : s || "";
    }
    function orbStyle(o) {
      return {
        transform: `translate(${o.x}px, ${o.y}px)`,
        width: `${o.size}px`,
        height: `${o.size}px`,
        background: `radial-gradient(circle, hsla(${o.hue}, 90%, 70%, 0.85), hsla(${o.hue}, 90%, 50%, 0.0) 70%)`
      };
    }
    function step(now) {
      const t = now / 1e3;
      const w = window.innerWidth, h = window.innerHeight;
      for (const o of orbs.value) {
        o.x = w * 0.5 + Math.cos(t * 0.4 + o.phase) * w * 0.45;
        o.y = h * 0.5 + Math.sin(t * 0.35 + o.phase * 1.7) * h * 0.45;
      }
      raf = requestAnimationFrame(step);
    }
    function next() {
      if (!props.items.length) return;
      currentIndex.value = (currentIndex.value + 1) % props.items.length;
      for (const o of orbs.value) {
        o.hue = (o.hue + 35 + Math.random() * 40) % 360;
        o.size = 200 + Math.random() * 280;
      }
    }
    function startTimer() {
      if (timer) {
        clearInterval(timer);
        timer = void 0;
      }
      if (props.autoplay) timer = window.setInterval(next, Math.max(3e3, props.interval * 1e3));
    }
    onMounted$4(() => {
      for (let i = 0; i < ORB_COUNT; i++) {
        orbs.value.push({
          id: i,
          x: 0,
          y: 0,
          size: 200 + Math.random() * 200,
          hue: Math.random() * 360,
          phase: Math.random() * Math.PI * 2
        });
      }
      raf = requestAnimationFrame(step);
      startTimer();
    });
    onBeforeUnmount$4(() => {
      if (timer) clearInterval(timer);
      if (raf) cancelAnimationFrame(raf);
    });
    watch$4(() => props.interval, () => startTimer());
    return (_ctx, _cache) => {
      return _openBlock$4(), _createElementBlock$4("div", {
        ref_key: "root",
        ref: root,
        class: "light-root"
      }, [
        current.value ? (_openBlock$4(), _createElementBlock$4("img", {
          key: currentIndex.value,
          src: imageUrl(current.value),
          class: "light-img"
        }, null, 8, _hoisted_1$4)) : _createCommentVNode$4("", true),
        _cache[0] || (_cache[0] = _createElementVNode$3("div", { class: "light-rays" }, null, -1)),
        _createElementVNode$3("div", _hoisted_2$4, [
          (_openBlock$4(true), _createElementBlock$4(_Fragment$4, null, _renderList$4(orbs.value, (o) => {
            return _openBlock$4(), _createElementBlock$4("div", {
              key: o.id,
              class: "orb",
              style: _normalizeStyle$4(orbStyle(o))
            }, null, 4);
          }), 128))
        ]),
        _cache[1] || (_cache[1] = _createElementVNode$3("div", { class: "light-vignette" }, null, -1)),
        current.value ? (_openBlock$4(), _createElementBlock$4("div", {
          key: 1,
          class: _normalizeClass$2(["light-meta", { "meta-center": logoWide.value }])
        }, [
          __props.imageType === "logo" && !_unref$3(hasNativeLogoImage)(current.value) && logoUrl(current.value) ? (_openBlock$4(), _createElementBlock$4("img", {
            key: 0,
            src: logoUrl(current.value),
            class: "meta-logo",
            alt: "",
            onLoad: onLogoLoad
          }, null, 40, _hoisted_3$4)) : (_openBlock$4(), _createElementBlock$4("div", _hoisted_4$4, _toDisplayString$3(current.value.title), 1)),
          _createElementVNode$3("div", _hoisted_5$4, [
            _createTextVNode$2(_toDisplayString$3(current.value.year) + " ", 1),
            current.value.type ? (_openBlock$4(), _createElementBlock$4("span", _hoisted_6$3, "· " + _toDisplayString$3(current.value.type), 1)) : _createCommentVNode$4("", true)
          ]),
          current.value.overview ? (_openBlock$4(), _createElementBlock$4("div", _hoisted_7$3, _toDisplayString$3(trimOverview(current.value.overview)), 1)) : _createCommentVNode$4("", true)
        ], 2)) : _createCommentVNode$4("", true)
      ], 512);
    };
  }
});

const LightDance = /* @__PURE__ */ _export_sfc(_sfc_main$4, [["__scopeId", "data-v-2392aa20"]]);

const {defineComponent:_defineComponent$3} = await importShared('vue');

const {renderList:_renderList$3,Fragment:_Fragment$3,openBlock:_openBlock$3,createElementBlock:_createElementBlock$3,createCommentVNode:_createCommentVNode$3,createElementVNode:_createElementVNode$2,normalizeStyle:_normalizeStyle$3} = await importShared('vue');

const _hoisted_1$3 = { class: "collage-root" };
const _hoisted_2$3 = { class: "ctile-half" };
const _hoisted_3$3 = ["src"];
const _hoisted_4$3 = { class: "ctile-half" };
const _hoisted_5$3 = ["src"];
const _hoisted_6$2 = ["src"];
const _hoisted_7$2 = ["src"];
const {onMounted: onMounted$3,onBeforeUnmount: onBeforeUnmount$3,ref: ref$3,watch: watch$3} = await importShared('vue');
const ANIM_MS = 1100;
const STACKED_PROB = 0.25;
const PRELOAD_COUNT = 8;
const _sfc_main$3 = /* @__PURE__ */ _defineComponent$3({
  __name: "ShiftingTiles",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$3({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const rows = ref$3([]);
    let uid = 0;
    let timer;
    let busy = false;
    let queue = [];
    let cursor = 0;
    function reshuffle() {
      queue = [...props.items];
      for (let i = queue.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [queue[i], queue[j]] = [queue[j], queue[i]];
      }
      cursor = 0;
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function onTileLogoLoad(e) {
      const i = e.target;
      i.classList.toggle("logo-wide", i.naturalWidth >= i.naturalHeight);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function nextPhoto() {
      return new Promise(async (resolve) => {
        if (!props.items.length) return resolve({ url: "", logo: "" });
        let guard = 0;
        while (guard++ <= props.items.length) {
          if (cursor >= queue.length) reshuffle();
          const it = queue[cursor++];
          const cands = it ? pickImageCandidates(it, props.imageType, cfg.value.tmdb_image_domain) : [];
          if (!cands.length) continue;
          const url = await loadImageWithFallback(cands);
          if (!url) continue;
          return resolve({ url, logo: it && !hasNativeLogoImage(it) ? logoUrl(it) : "" });
        }
        resolve({ url: "", logo: "" });
      });
    }
    function preloadAhead() {
      let c = cursor;
      for (let k = 0; k < PRELOAD_COUNT && k < queue.length; k++) {
        const it = queue[(c + k) % queue.length];
        if (it) {
          const im = new Image();
          im.src = imageUrl(it);
        }
      }
    }
    function genWidth() {
      const r = Math.random();
      if (r < 0.25) return 0.3 + Math.random() * 0.08;
      if (r < 0.75) return 0.2 + Math.random() * 0.08;
      return 0.14 + Math.random() * 0.06;
    }
    async function makeTile(w) {
      const stacked = Math.random() < STACKED_PROB;
      const p = await nextPhoto();
      const t = { id: ++uid, w, url: p.url, logo: p.logo, stacked };
      if (stacked) t.url2 = (await nextPhoto()).url;
      return t;
    }
    async function makeRow(count) {
      const ws = Array.from({ length: count }, genWidth);
      const sum = ws.reduce((a, b) => a + b, 0);
      return Promise.all(ws.map((w) => makeTile(w / sum)));
    }
    async function buildLayout() {
      reshuffle();
      const nRows = window.innerWidth < window.innerHeight ? 3 : 2;
      const counts = nRows === 2 ? [4, 4] : [3, 3, 3];
      counts[0] = 3 + Math.floor(Math.random() * 3);
      counts[1] = 3 + Math.floor(Math.random() * 3);
      const out = await Promise.all(counts.map((c) => makeRow(c)));
      rows.value = out;
      preloadAhead();
    }
    async function shiftOnce() {
      if (busy || !rows.value.length) return;
      busy = true;
      const ri = Math.floor(Math.random() * rows.value.length);
      const row = rows.value[ri];
      if (row.length < 3) {
        busy = false;
        return;
      }
      const ti = Math.floor(Math.random() * row.length);
      const victim = row[ti];
      const freed = victim.w;
      const ni = ti > 0 ? ti - 1 : ti + 1;
      victim.w = 0;
      row[ni].w += freed;
      window.setTimeout(async () => {
        const idx = row.indexOf(victim);
        if (idx >= 0) row.splice(idx, 1);
        const t = await makeTile(0);
        const pos = Math.floor(Math.random() * (row.length + 1));
        row.splice(pos, 0, t);
        requestAnimationFrame(() => {
          const w = genWidth();
          const others = row.filter((x) => x !== t);
          const sum = others.reduce((a, b) => a + b.w, 0) || 1;
          others.forEach((x) => {
            x.w = x.w / sum * (1 - w);
          });
          t.w = w;
          window.setTimeout(() => {
            busy = false;
          }, ANIM_MS);
        });
      }, ANIM_MS * 0.55);
    }
    function schedule() {
      if (timer) {
        clearTimeout(timer);
        timer = void 0;
      }
      if (!props.autoplay) return;
      const base = Math.min(5e3, Math.max(3e3, props.interval * 1e3));
      const wait = base - 1e3 + Math.random() * 2e3;
      timer = window.setTimeout(async () => {
        await shiftOnce();
        schedule();
      }, wait);
    }
    function onVis() {
      if (document.hidden) {
        if (timer) {
          clearTimeout(timer);
          timer = void 0;
        }
      } else {
        schedule();
      }
    }
    let resizeTimer;
    function onResize() {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        const want = window.innerWidth < window.innerHeight ? 3 : 2;
        if (rows.value.length !== want) buildLayout();
      }, 300);
    }
    onMounted$3(async () => {
      await buildLayout();
      schedule();
      document.addEventListener("visibilitychange", onVis);
      window.addEventListener("resize", onResize);
    });
    onBeforeUnmount$3(() => {
      if (timer) clearTimeout(timer);
      if (resizeTimer) clearTimeout(resizeTimer);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("resize", onResize);
    });
    watch$3(() => props.interval, () => schedule());
    watch$3(() => props.items?.length, async (n, old) => {
      if (!old || n !== old) {
        await buildLayout();
        schedule();
      }
    });
    return (_ctx, _cache) => {
      return _openBlock$3(), _createElementBlock$3("div", _hoisted_1$3, [
        (_openBlock$3(true), _createElementBlock$3(_Fragment$3, null, _renderList$3(rows.value, (row, ri) => {
          return _openBlock$3(), _createElementBlock$3("div", {
            key: ri,
            class: "collage-row"
          }, [
            (_openBlock$3(true), _createElementBlock$3(_Fragment$3, null, _renderList$3(row, (t) => {
              return _openBlock$3(), _createElementBlock$3("div", {
                key: t.id,
                class: "ctile",
                style: _normalizeStyle$3({ flexBasis: (t.w * 100).toFixed(3) + "%" })
              }, [
                t.stacked ? (_openBlock$3(), _createElementBlock$3(_Fragment$3, { key: 0 }, [
                  _createElementVNode$2("div", _hoisted_2$3, [
                    t.url ? (_openBlock$3(), _createElementBlock$3("img", {
                      key: 0,
                      src: t.url,
                      alt: ""
                    }, null, 8, _hoisted_3$3)) : _createCommentVNode$3("", true)
                  ]),
                  _createElementVNode$2("div", _hoisted_4$3, [
                    t.url2 ? (_openBlock$3(), _createElementBlock$3("img", {
                      key: 0,
                      src: t.url2,
                      alt: ""
                    }, null, 8, _hoisted_5$3)) : _createCommentVNode$3("", true)
                  ])
                ], 64)) : t.url ? (_openBlock$3(), _createElementBlock$3("img", {
                  key: 1,
                  src: t.url,
                  class: "ctile-img",
                  alt: ""
                }, null, 8, _hoisted_6$2)) : _createCommentVNode$3("", true),
                __props.imageType === "logo" && t.logo ? (_openBlock$3(), _createElementBlock$3("img", {
                  key: 2,
                  src: t.logo,
                  class: "ctile-logo",
                  alt: "",
                  onLoad: onTileLogoLoad
                }, null, 40, _hoisted_7$2)) : _createCommentVNode$3("", true)
              ], 4);
            }), 128))
          ]);
        }), 128))
      ]);
    };
  }
});

const ShiftingTiles = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["__scopeId", "data-v-cba878f0"]]);

const {defineComponent:_defineComponent$2} = await importShared('vue');

const {renderList:_renderList$2,Fragment:_Fragment$2,openBlock:_openBlock$2,createElementBlock:_createElementBlock$2,createCommentVNode:_createCommentVNode$2,unref:_unref$2,toDisplayString:_toDisplayString$2,normalizeClass:_normalizeClass$1,normalizeStyle:_normalizeStyle$2} = await importShared('vue');

const _hoisted_1$2 = { class: "panels-root" };
const _hoisted_2$2 = ["src"];
const _hoisted_3$2 = {
  key: 1,
  class: "panel-cap"
};
const _hoisted_4$2 = ["src"];
const _hoisted_5$2 = {
  key: 1,
  class: "cap-title"
};
const {onMounted: onMounted$2,onBeforeUnmount: onBeforeUnmount$2,ref: ref$2,watch: watch$2} = await importShared('vue');
const _sfc_main$2 = /* @__PURE__ */ _defineComponent$2({
  __name: "SlidingPanels",
  props: {
    items: {},
    interval: {},
    imageType: {},
    autoplay: { type: Boolean }
  },
  emits: ["exit"],
  setup(__props) {
    const props = __props;
    const cfg = ref$2({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    const LAYOUTS = [
      [0.31, 0.19, 0.1, 0.4],
      [0.25, 0.25, 0.25, 0.25],
      [0.4, 0.2, 0.4],
      [0.2, 0.3, 0.3, 0.2]
    ];
    const panels = ref$2([]);
    const layoutIdx = ref$2(0);
    let timer;
    let cursor = 0;
    let busy = false;
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function nextItem() {
      if (!props.items.length) return null;
      const it = props.items[cursor % props.items.length];
      cursor++;
      return it;
    }
    function buildPanels(li) {
      const layout = LAYOUTS[li % LAYOUTS.length];
      panels.value = layout.map((w, i) => {
        const it = nextItem();
        return {
          url: it ? imageUrl(it) : "",
          width: w,
          // Apple：相邻面板滑动方向交错
          dir: i % 2 === 0 ? "up" : "down",
          exiting: false,
          entering: false,
          item: it,
          logo: it && !hasNativeLogoImage(it) ? logoUrl(it) : ""
        };
      });
    }
    function rotatePanels() {
      if (!props.items.length || busy) return;
      busy = true;
      const SLIDE_MS = 750, STAGGER = 110;
      const n = panels.value.length;
      panels.value.forEach((p, i) => {
        window.setTimeout(() => {
          p.exiting = true;
        }, i * STAGGER);
      });
      window.setTimeout(() => {
        layoutIdx.value = (layoutIdx.value + 1) % LAYOUTS.length;
        const layout = LAYOUTS[layoutIdx.value];
        panels.value = layout.map((w, i) => {
          const it = nextItem();
          return {
            url: it ? imageUrl(it) : "",
            width: w,
            dir: i % 2 === 0 ? "up" : "down",
            exiting: false,
            entering: true,
            item: it,
            logo: it && !hasNativeLogoImage(it) ? logoUrl(it) : ""
          };
        });
        window.setTimeout(() => {
          panels.value.forEach((p) => {
            p.entering = false;
          });
          busy = false;
        }, SLIDE_MS + 80);
      }, n * STAGGER + SLIDE_MS);
    }
    function startTimer() {
      if (timer) {
        clearInterval(timer);
        timer = void 0;
      }
      if (props.autoplay) {
        timer = window.setInterval(rotatePanels, Math.max(3e3, props.interval * 1e3));
      }
    }
    onMounted$2(() => {
      buildPanels(0);
      startTimer();
    });
    onBeforeUnmount$2(() => {
      if (timer) clearInterval(timer);
    });
    watch$2(() => props.interval, () => startTimer());
    watch$2(() => props.items?.length, (n, old) => {
      if (!old || n !== old) {
        buildPanels(0);
        startTimer();
      }
    });
    return (_ctx, _cache) => {
      return _openBlock$2(), _createElementBlock$2("div", _hoisted_1$2, [
        (_openBlock$2(true), _createElementBlock$2(_Fragment$2, null, _renderList$2(panels.value, (p, i) => {
          return _openBlock$2(), _createElementBlock$2("div", {
            key: `${layoutIdx.value}-${i}`,
            class: _normalizeClass$1(["panel-col", [`dir-${p.dir}`, { exiting: p.exiting, entering: p.entering }]]),
            style: _normalizeStyle$2({ flexBasis: p.width * 100 + "%" })
          }, [
            p.url ? (_openBlock$2(), _createElementBlock$2("img", {
              key: 0,
              src: p.url,
              alt: ""
            }, null, 8, _hoisted_2$2)) : _createCommentVNode$2("", true),
            p.item ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_3$2, [
              __props.imageType === "logo" && !_unref$2(hasNativeLogoImage)(p.item) && p.logo ? (_openBlock$2(), _createElementBlock$2("img", {
                key: 0,
                src: p.logo,
                class: "cap-logo",
                alt: ""
              }, null, 8, _hoisted_4$2)) : (_openBlock$2(), _createElementBlock$2("div", _hoisted_5$2, _toDisplayString$2(p.item.title), 1))
            ])) : _createCommentVNode$2("", true)
          ], 6);
        }), 128))
      ]);
    };
  }
});

const SlidingPanels = /* @__PURE__ */ _export_sfc(_sfc_main$2, [["__scopeId", "data-v-fe4d8124"]]);

const {defineComponent:_defineComponent$1} = await importShared('vue');

const {createElementVNode:_createElementVNode$1,renderList:_renderList$1,Fragment:_Fragment$1,openBlock:_openBlock$1,createElementBlock:_createElementBlock$1,createCommentVNode:_createCommentVNode$1,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle$1,unref:_unref$1,toDisplayString:_toDisplayString$1,createTextVNode:_createTextVNode$1} = await importShared('vue');

const _hoisted_1$1 = { class: "ring-root" };
const _hoisted_2$1 = { class: "ring-stage" };
const _hoisted_3$1 = ["src"];
const _hoisted_4$1 = ["src"];
const _hoisted_5$1 = {
  key: 0,
  class: "ring-meta"
};
const _hoisted_6$1 = ["src"];
const _hoisted_7$1 = { class: "ring-title" };
const _hoisted_8$1 = { class: "ring-sub" };
const _hoisted_9$1 = { key: 0 };
const _hoisted_10$1 = {
  key: 2,
  class: "ring-overview"
};
const {ref: ref$1,computed,watch: watch$1,onMounted: onMounted$1,onBeforeUnmount: onBeforeUnmount$1} = await importShared('vue');
const N = 10;
const _sfc_main$1 = /* @__PURE__ */ _defineComponent$1({
  __name: "RingGallery",
  props: {
    items: {},
    imageType: { default: "backdrop" },
    active: { type: Boolean, default: true }
  },
  setup(__props) {
    const props = __props;
    const cfg = ref$1({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    fetch("/api/v1/plugin/FullScreenPosterWall/config").then((r) => r.json()).then((d) => {
      if (d?.data) {
        cfg.value = d.data;
        if (timer && !document.hidden) startTimer();
      }
    }).catch(() => {
    });
    const imageType = ref$1(props.imageType);
    watch$1(() => props.imageType, (v) => {
      imageType.value = v || "backdrop";
    });
    const cards = ref$1([]);
    const rotation = ref$1(0);
    const step = 360 / N;
    const radius = ref$1(600);
    const frontIndex = ref$1(0);
    let cursor = 0;
    let timer = null;
    const logoWide = ref$1(false);
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function onLogoLoad(e) {
      const i = e.target;
      i.classList.toggle("logo-wide", i.naturalWidth >= i.naturalHeight);
      logoWide.value = i.naturalWidth >= i.naturalHeight;
    }
    function trimOverview(s, max = 160) {
      return s && s.length > max ? s.slice(0, max) + "…" : s || "";
    }
    const front = computed(() => cards.value[frontIndex.value]?.item || null);
    const ringStyle = computed(() => ({
      transform: `translateZ(${-radius.value}px) rotateX(-6deg) rotateY(${rotation.value}deg)`
    }));
    function cardStyle(i) {
      const s = i === frontIndex.value ? " scale(1.18)" : "";
      return { transform: `rotateY(${i * step}deg) translateZ(${radius.value}px)${s}` };
    }
    function computeRadius() {
      const cardW = Math.min(window.innerWidth * 0.5, 730);
      radius.value = Math.round(cardW / 2 / Math.tan(Math.PI / N)) + 40;
    }
    function build() {
      const list = props.items || [];
      cards.value = Array.from({ length: N }, (_, i) => {
        const it = list[cursor++ % Math.max(1, list.length)] || null;
        return {
          url: it ? imageUrl(it) : "",
          logo: it && !hasNativeLogoImage(it) ? logoUrl(it) : "",
          item: it
        };
      });
      rotation.value = 0;
      frontIndex.value = 0;
    }
    function rotate() {
      rotation.value -= step;
      frontIndex.value = (frontIndex.value + 1) % N;
      const backIdx = (frontIndex.value + Math.floor(N / 2)) % N;
      const list = props.items || [];
      if (list.length) {
        const it = list[cursor++ % list.length];
        const c = cards.value[backIdx];
        if (c) {
          c.url = imageUrl(it);
          c.logo = !hasNativeLogoImage(it) ? logoUrl(it) : "";
          c.item = it;
        }
      }
    }
    function onResize() {
      computeRadius();
    }
    function currentInterval() {
      return Math.max(4, cfg.value.interval || 8) * 1e3;
    }
    function startTimer() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      timer = setInterval(rotate, currentInterval());
    }
    onMounted$1(() => {
      computeRadius();
      build();
      window.addEventListener("resize", onResize);
      startTimer();
      document.addEventListener("visibilitychange", vis);
    });
    function vis() {
      if (document.hidden && timer) {
        clearInterval(timer);
        timer = null;
      } else if (!document.hidden && !timer) startTimer();
    }
    onBeforeUnmount$1(() => {
      if (timer) clearInterval(timer);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", vis);
    });
    watch$1(() => props.items, build, { deep: true });
    return (_ctx, _cache) => {
      return _openBlock$1(), _createElementBlock$1("div", _hoisted_1$1, [
        _cache[0] || (_cache[0] = _createElementVNode$1("div", { class: "rg-aurora a1" }, null, -1)),
        _cache[1] || (_cache[1] = _createElementVNode$1("div", { class: "rg-aurora a2" }, null, -1)),
        _cache[2] || (_cache[2] = _createElementVNode$1("div", { class: "rg-dust d1" }, null, -1)),
        _cache[3] || (_cache[3] = _createElementVNode$1("div", { class: "rg-dust d2" }, null, -1)),
        _createElementVNode$1("div", _hoisted_2$1, [
          _createElementVNode$1("div", {
            class: "ring",
            style: _normalizeStyle$1(ringStyle.value)
          }, [
            (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(cards.value, (c, i) => {
              return _openBlock$1(), _createElementBlock$1("div", {
                key: i,
                class: _normalizeClass(["ring-card", { front: i === frontIndex.value }]),
                style: _normalizeStyle$1(cardStyle(i))
              }, [
                c.url ? (_openBlock$1(), _createElementBlock$1("img", {
                  key: 0,
                  src: c.url,
                  alt: "",
                  draggable: "false"
                }, null, 8, _hoisted_3$1)) : _createCommentVNode$1("", true),
                imageType.value === "logo" && c.logo ? (_openBlock$1(), _createElementBlock$1("img", {
                  key: 1,
                  src: c.logo,
                  class: "rg-logo",
                  alt: "",
                  onLoad: onLogoLoad
                }, null, 40, _hoisted_4$1)) : _createCommentVNode$1("", true)
              ], 6);
            }), 128))
          ], 4)
        ]),
        _cache[4] || (_cache[4] = _createElementVNode$1("div", { class: "ring-floor" }, null, -1)),
        front.value ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_5$1, [
          imageType.value === "logo" && !_unref$1(hasNativeLogoImage)(front.value) && logoUrl(front.value) ? (_openBlock$1(), _createElementBlock$1("img", {
            key: 0,
            src: logoUrl(front.value),
            class: _normalizeClass(["meta-logo", { "meta-center": logoWide.value }]),
            alt: "",
            onLoad: onLogoLoad
          }, null, 42, _hoisted_6$1)) : (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 1 }, [
            _createElementVNode$1("div", _hoisted_7$1, _toDisplayString$1(front.value.title), 1),
            _createElementVNode$1("div", _hoisted_8$1, [
              _createTextVNode$1(_toDisplayString$1(front.value.year), 1),
              front.value.year && front.value.type ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_9$1, " · ")) : _createCommentVNode$1("", true),
              _createTextVNode$1(_toDisplayString$1(front.value.type), 1)
            ])
          ], 64)),
          front.value.overview ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_10$1, _toDisplayString$1(trimOverview(front.value.overview, 110)), 1)) : _createCommentVNode$1("", true)
        ])) : _createCommentVNode$1("", true),
        _cache[5] || (_cache[5] = _createElementVNode$1("div", { class: "ring-vignette" }, null, -1))
      ]);
    };
  }
});

const RingGallery = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["__scopeId", "data-v-3abb1908"]]);

const {defineComponent:_defineComponent} = await importShared('vue');

const {createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,normalizeStyle:_normalizeStyle,unref:_unref,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode} = await importShared('vue');

const _hoisted_1 = { class: "dt-root" };
const _hoisted_2 = ["src"];
const _hoisted_3 = ["src"];
const _hoisted_4 = { class: "dt-thumbs" };
const _hoisted_5 = ["src"];
const _hoisted_6 = {
  key: 0,
  class: "dt-meta"
};
const _hoisted_7 = ["src"];
const _hoisted_8 = { class: "dt-title" };
const _hoisted_9 = { class: "dt-sub" };
const _hoisted_10 = { key: 0 };
const {ref,watch,onMounted,onBeforeUnmount} = await importShared('vue');
const THUMBS_N = 9;
const _sfc_main = /* @__PURE__ */ _defineComponent({
  __name: "DepthTunnel",
  props: {
    items: {},
    imageType: { default: "backdrop" },
    active: { type: Boolean, default: true }
  },
  setup(__props) {
    const props = __props;
    const cfg = ref({ tmdb_image_domain: "https://image.tmdb.org/t/p/original" });
    fetch("/api/v1/plugin/FullScreenPosterWall/config").then((r) => r.json()).then((d) => {
      if (d?.data) cfg.value = d.data;
    }).catch(() => {
    });
    const imageType = ref(props.imageType);
    watch(() => props.imageType, (v) => {
      imageType.value = v || "backdrop";
    });
    let zSeq = 0;
    const flyers = ref([]);
    const thumbs = ref([]);
    const current = ref(null);
    let uid = 0;
    let queue = [];
    let cursor = 0;
    let timer = null;
    let gcTimer = null;
    let warming = false;
    function imageUrl(item) {
      return pickImageUrl(item, props.imageType, cfg.value.tmdb_image_domain);
    }
    function logoUrl(item) {
      return pickLogoUrl(item, cfg.value.tmdb_image_domain);
    }
    function onLogoLoad(e) {
      const i = e.target;
      i.classList.toggle("logo-wide", i.naturalWidth >= i.naturalHeight);
    }
    function reshuffle() {
      queue = [...props.items];
      for (let i = queue.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [queue[i], queue[j]] = [queue[j], queue[i]];
      }
      cursor = 0;
    }
    function nextItem() {
      if (!props.items.length) return null;
      if (cursor >= queue.length) reshuffle();
      return queue[cursor++] || null;
    }
    function fillThumbs() {
      const limit = Math.max(props.items.length, 1);
      let misses = 0;
      while (thumbs.value.length < THUMBS_N && misses < limit) {
        const it = nextItem();
        if (!it) break;
        const url = imageUrl(it);
        if (!url) {
          misses++;
          continue;
        }
        misses = 0;
        const depth = 0.35 + Math.random() * 0.65;
        thumbs.value.push({
          id: ++uid,
          url,
          item: it,
          x: 4 + Math.random() * 88,
          y: 6 + Math.random() * 80,
          w: Math.round(56 + depth * 56),
          dur: 7 + Math.random() * 9,
          delay: -Math.random() * 10,
          depth
        });
      }
    }
    function thumbStyle(t) {
      return {
        left: t.x + "%",
        top: t.y + "%",
        width: t.w + "px",
        height: Math.round(t.w * 0.66) + "px",
        opacity: (0.3 + t.depth * 0.35).toFixed(2),
        filter: "blur(" + ((1 - t.depth) * 1.6).toFixed(1) + "px)",
        animationDuration: t.dur.toFixed(1) + "s",
        animationDelay: t.delay.toFixed(1) + "s"
      };
    }
    function flyerStyle(f) {
      return {
        "--dx": f.dx + "vw",
        "--dy": f.dy + "vh",
        animationDuration: f.dur + "ms",
        zIndex: f.z
      };
    }
    async function spawn() {
      if (warming || !thumbs.value.length) return;
      warming = true;
      const t = thumbs.value[0];
      const url = await loadImageWithFallback(pickImageCandidates(t.item, props.imageType, cfg.value.tmdb_image_domain));
      if (!url) {
        thumbs.value.shift();
        fillThumbs();
        warming = false;
        return;
      }
      thumbs.value.shift();
      fillThumbs();
      current.value = t.item;
      const iv = Math.max(4, cfg.value.interval || 8) * 1e3;
      flyers.value.push({
        id: ++uid,
        url,
        logo: !hasNativeLogoImage(t.item) ? logoUrl(t.item) : "",
        dx: (Math.random() - 0.5) * 30,
        dy: (Math.random() - 0.5) * 20,
        dur: Math.round(iv * (0.92 + Math.random() * 0.1)),
        born: Date.now(),
        z: 5 + ++zSeq % 40
        // 图层递增：放大时压在所有旧图上
      });
      warming = false;
    }
    onMounted(() => {
      reshuffle();
      fillThumbs();
      spawn();
      const iv = Math.max(4, cfg.value.interval || 8) * 1e3;
      timer = setInterval(spawn, iv);
      gcTimer = setInterval(() => {
        const now = Date.now();
        flyers.value = flyers.value.filter((f) => now - f.born < f.dur + 800);
      }, 3e3);
      document.addEventListener("visibilitychange", vis);
    });
    function vis() {
      if (document.hidden) {
        if (timer) {
          clearInterval(timer);
          timer = null;
        }
      } else if (!timer) {
        timer = setInterval(spawn, Math.max(4, cfg.value.interval || 8) * 1e3);
      }
    }
    onBeforeUnmount(() => {
      if (timer) clearInterval(timer);
      if (gcTimer) clearInterval(gcTimer);
      document.removeEventListener("visibilitychange", vis);
    });
    watch(() => props.items, () => {
      reshuffle();
      thumbs.value = [];
      fillThumbs();
    }, { deep: true });
    return (_ctx, _cache) => {
      return _openBlock(), _createElementBlock("div", _hoisted_1, [
        _cache[0] || (_cache[0] = _createElementVNode("div", { class: "dt-streaks" }, null, -1)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(flyers.value, (f) => {
          return _openBlock(), _createElementBlock("div", {
            key: f.id,
            class: "dt-flyer",
            style: _normalizeStyle(flyerStyle(f))
          }, [
            f.url ? (_openBlock(), _createElementBlock("img", {
              key: 0,
              src: f.url,
              alt: "",
              draggable: "false"
            }, null, 8, _hoisted_2)) : _createCommentVNode("", true),
            imageType.value === "logo" && f.logo ? (_openBlock(), _createElementBlock("img", {
              key: 1,
              src: f.logo,
              class: "dt-logo",
              alt: "",
              onLoad: onLogoLoad
            }, null, 40, _hoisted_3)) : _createCommentVNode("", true)
          ], 4);
        }), 128)),
        _createElementVNode("div", _hoisted_4, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(thumbs.value, (t) => {
            return _openBlock(), _createElementBlock("div", {
              key: t.id,
              class: "dt-thumb",
              style: _normalizeStyle(thumbStyle(t))
            }, [
              t.url ? (_openBlock(), _createElementBlock("img", {
                key: 0,
                src: t.url,
                alt: "",
                draggable: "false"
              }, null, 8, _hoisted_5)) : _createCommentVNode("", true)
            ], 4);
          }), 128))
        ]),
        current.value ? (_openBlock(), _createElementBlock("div", _hoisted_6, [
          imageType.value === "logo" && !_unref(hasNativeLogoImage)(current.value) && logoUrl(current.value) ? (_openBlock(), _createElementBlock("img", {
            key: 0,
            src: logoUrl(current.value),
            class: "meta-logo",
            alt: "",
            onLoad: onLogoLoad
          }, null, 40, _hoisted_7)) : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
            _createElementVNode("div", _hoisted_8, _toDisplayString(current.value.title), 1),
            _createElementVNode("div", _hoisted_9, [
              _createTextVNode(_toDisplayString(current.value.year), 1),
              current.value.year && current.value.type ? (_openBlock(), _createElementBlock("span", _hoisted_10, " · ")) : _createCommentVNode("", true),
              _createTextVNode(_toDisplayString(current.value.type), 1)
            ])
          ], 64))
        ])) : _createCommentVNode("", true),
        _cache[1] || (_cache[1] = _createElementVNode("div", { class: "dt-vignette" }, null, -1))
      ]);
    };
  }
});

const DepthTunnel = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-16eb2c8c"]]);

export { DepthTunnel as D, Floating as F, LightDance as L, PhotosSlideshow as P, RingGallery as R, SlidingPanels as S, VintagePrints as V, ShiftingTiles as a };
