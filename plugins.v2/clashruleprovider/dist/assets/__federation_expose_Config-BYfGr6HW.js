import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { V as VAceEditor } from './theme-monokai-CF_yROe-.js';
import { f as isValidUrl, v as validateIPs, _ as _export_sfc } from './_plugin-vue_export-helper-D32QZFxh.js';

const {defineComponent:_defineComponent} = await importShared('vue');

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,withModifiers:_withModifiers,normalizeClass:_normalizeClass,unref:_unref,mergeProps:_mergeProps,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');

const _hoisted_1 = { class: "plugin-config-wrapper" };
const _hoisted_2 = { class: "config-hero-header pa-5 pa-md-6 d-flex flex-wrap align-center justify-space-between gap-4" };
const _hoisted_3 = { class: "d-flex align-center gap-4" };
const _hoisted_4 = { class: "hero-icon-avatar rounded-lg d-flex align-center justify-center" };
const _hoisted_5 = { class: "d-flex align-center gap-2" };
const _hoisted_6 = { class: "d-flex align-center gap-2" };
const _hoisted_7 = { class: "font-weight-medium" };
const _hoisted_8 = { class: "mb-6" };
const _hoisted_9 = { class: "text-subtitle-2 font-weight-bold text-uppercase text-medium-emphasis mb-3 d-flex align-center" };
const _hoisted_10 = { class: "d-flex align-center gap-3" };
const _hoisted_11 = { class: "card-icon-avatar rounded-circle d-flex align-center justify-center" };
const _hoisted_12 = { class: "d-flex align-center gap-3" };
const _hoisted_13 = { class: "card-icon-avatar rounded-circle d-flex align-center justify-center" };
const _hoisted_14 = { class: "d-flex align-center gap-3" };
const _hoisted_15 = { class: "card-icon-avatar rounded-circle d-flex align-center justify-center" };
const _hoisted_16 = { class: "d-flex align-center gap-3" };
const _hoisted_17 = { class: "card-icon-avatar rounded-circle d-flex align-center justify-center" };
const _hoisted_18 = { class: "text-subtitle-2 font-weight-bold text-uppercase text-medium-emphasis mb-3 d-flex align-center" };
const _hoisted_19 = { class: "tabs-container mb-4" };
const _hoisted_20 = { class: "mb-4" };
const _hoisted_21 = { class: "d-flex align-center gap-2" };
const _hoisted_22 = { class: "d-flex align-center gap-2" };
const _hoisted_23 = { class: "d-flex align-center justify-space-between mb-4" };
const _hoisted_24 = { class: "text-subtitle-1 font-weight-bold d-flex align-center" };
const _hoisted_25 = { class: "d-flex align-center gap-2" };
const _hoisted_26 = {
  key: 0,
  class: "empty-box rounded-xl pa-8 text-center border-dashed"
};
const _hoisted_27 = { class: "d-flex align-center gap-3 w-100" };
const _hoisted_28 = {
  class: "text-subtitle-2 font-weight-bold text-truncate",
  style: { "max-width": "320px" }
};
const _hoisted_29 = ["onClick"];
const _hoisted_30 = ["onClick"];
const _hoisted_31 = ["onClick"];
const _hoisted_32 = ["onClick"];
const _hoisted_33 = { class: "d-flex align-center gap-1 flex-wrap mb-4" };
const _hoisted_34 = { class: "d-flex align-center gap-2" };
const _hoisted_35 = { class: "d-flex align-center gap-2" };
const _hoisted_36 = { class: "pa-4 bg-surface d-flex flex-wrap align-center justify-space-between gap-3" };
const _hoisted_37 = { class: "d-flex align-center text-caption text-medium-emphasis" };
const _hoisted_38 = {
  href: "https://github.com/wumode/MoviePilot-Plugins/tree/main/plugins.v2/clashruleprovider/README.md",
  target: "_blank",
  class: "text-primary font-weight-bold text-decoration-none ml-1"
};
const _hoisted_39 = { class: "d-flex align-center gap-2" };
const _hoisted_40 = { class: "d-flex align-center gap-3" };
const _hoisted_41 = { class: "font-weight-bold text-subtitle-2" };
const _hoisted_42 = { class: "text-caption" };
const _hoisted_43 = { class: "d-flex align-center gap-2" };
const _hoisted_44 = { class: "ace-editor-wrapper border rounded-lg overflow-hidden mb-3" };
const {ref,reactive,onMounted,computed} = await importShared('vue');
const _sfc_main = /* @__PURE__ */ _defineComponent({
  __name: "Config",
  props: {
    initialConfig: {
      type: Object,
      default: () => ({})
    },
    api: {
      type: Object,
      default: () => {
      }
    }
  },
  emits: ["save", "close", "switch"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const activeTab = ref("subscription");
    const editorOptions = {
      enableBasicAutocompletion: true,
      enableSnippets: true,
      enableLiveAutocompletion: true,
      showLineNumbers: true,
      tabSize: 2
    };
    const configPlaceholder = ref(
      `profile:
  store-selected: true
mode: rule
log-level: silent`
    );
    const clashTemplateDialog = ref(false);
    const clashTemplateType = ref("YAML");
    const clashTemplateContent = ref("");
    const form = ref(null);
    const isFormValid = ref(true);
    const error = ref("");
    const saving = ref(false);
    const testing = ref(false);
    const dashboardComponents = ["Clash Info", "Traffic Stats"];
    const showSecrets = ref({ 0: false });
    const cronPresets = [
      { label: "每 6 小时", value: "0 */6 * * *" },
      { label: "每 12 小时", value: "0 */12 * * *" },
      { label: "每日 04:00", value: "0 4 * * *" },
      { label: "每日零点", value: "0 0 * * *" }
    ];
    const testResult = reactive({
      show: false,
      success: false,
      title: "",
      message: ""
    });
    const defaultConfig = {
      enabled: false,
      subscriptions_config: [],
      filter_keywords: ["公益性", "高延迟", "域名", "官网", "重启", "过期时间", "系统代理"],
      clash_dashboards: [{ url: "", secret: "" }],
      movie_pilot_url: "",
      cron_string: "0 */6 * * *",
      timeout: 10,
      retry_times: 3,
      proxy: false,
      notify: false,
      auto_update_subscriptions: true,
      ruleset_prefix: "📂<=",
      acl4ssr_prefix: "🗂️=>",
      group_by_region: false,
      group_by_country: false,
      refresh_delay: 5,
      enable_acl4ssr: false,
      dashboard_components: [],
      clash_template: "",
      hint_geo_dat: false,
      best_cf_ip: [],
      active_dashboard: 0,
      apikey: null,
      identifiers: [],
      cache_ttl: 3600
    };
    const config = reactive({ ...defaultConfig });
    onMounted(() => {
      if (props.initialConfig) {
        Object.keys(props.initialConfig).forEach((key) => {
          if (key in config) {
            config[key] = props.initialConfig[key];
          }
        });
      }
    });
    const sub_links = computed(() => {
      if (!config.subscriptions_config) {
        return [];
      }
      return config.subscriptions_config.map((item) => item.url);
    });
    const activeOptionsCount = (item) => {
      let count = 0;
      if (item.rules) count++;
      if (item["rule-providers"]) count++;
      if (item["proxy-groups"]) count++;
      if (item["proxy-providers"]) count++;
      return count;
    };
    const getUrlHostname = (urlStr) => {
      if (!urlStr) return "未配置订阅 URL";
      try {
        const parsed = new URL(urlStr);
        return parsed.hostname;
      } catch {
        return urlStr.length > 30 ? urlStr.substring(0, 30) + "..." : urlStr;
      }
    };
    const generateApiKey = () => {
      const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
      let key = "";
      for (let i = 0; i < 32; i++) {
        key += chars.charAt(Math.floor(Math.random() * chars.length));
      }
      config.apikey = key;
    };
    function showError(title, msg) {
      testResult.title = title;
      testResult.success = false;
      testResult.message = msg;
      testResult.show = true;
    }
    async function testConnection() {
      testing.value = true;
      error.value = "";
      testResult.show = false;
      try {
        if (sub_links.value.length === 0) {
          showError("连接测试失败", "请先配置至少一个订阅链接");
          return;
        }
        const testParams = {
          clash_apis: config.clash_dashboards,
          sub_links: sub_links.value
        };
        const result = await props.api.post("/plugin/ClashRuleProvider/connectivity", testParams);
        if (result.success) {
          testResult.success = true;
          testResult.title = "连接测试成功！";
          testResult.message = "Clash 面板和订阅链接连接正常，配置验证通过";
          testResult.show = true;
          setTimeout(() => {
            testResult.show = false;
          }, 5e3);
        } else {
          showError("连接测试失败", result.message || "连接测试失败，请检查配置");
        }
      } catch (err) {
        if (err instanceof Error) showError("连接测试失败", err.message);
      } finally {
        testing.value = false;
      }
    }
    async function saveConfig() {
      for (let i = 0; i < config.subscriptions_config.length; i++) {
        const sub = config.subscriptions_config[i];
        if (!sub.url || !isValidUrl(sub.url)) {
          error.value = `订阅配置 ${i + 1} 中的 URL 无效或为空`;
          return;
        }
      }
      if (!isFormValid.value) {
        error.value = "请修正表单中的错误";
        return;
      }
      saving.value = true;
      error.value = "";
      try {
        await new Promise((resolve) => setTimeout(resolve, 800));
        emit("save", { ...config });
      } catch (err) {
        if (err instanceof Error) error.value = err.message || "保存配置失败";
      } finally {
        saving.value = false;
      }
    }
    const toggleSecret = (index) => {
      showSecrets.value[index] = !showSecrets.value[index];
    };
    const addClashConfig = () => {
      const newIndex = config.clash_dashboards.length;
      config.clash_dashboards.push({ url: "", secret: "" });
      showSecrets.value[newIndex] = false;
    };
    const removeClashConfig = (index) => {
      config.clash_dashboards.splice(index, 1);
      delete showSecrets.value[index];
      if (config.active_dashboard === index) {
        config.active_dashboard = config.clash_dashboards.length > 0 ? 0 : null;
      }
    };
    const addSubscriptionConfig = () => {
      config.subscriptions_config.push({
        url: "",
        rules: false,
        proxies: true,
        "proxy-groups": false,
        "rule-providers": false,
        "proxy-providers": false
      });
    };
    const removeSubscriptionConfig = (index) => {
      config.subscriptions_config.splice(index, 1);
    };
    function openClashTemplateDialog() {
      clashTemplateContent.value = config.clash_template;
      clashTemplateDialog.value = true;
    }
    function saveClashTemplate() {
      config.clash_template = clashTemplateContent.value;
      clashTemplateDialog.value = false;
    }
    function resetForm() {
      Object.assign(config, JSON.parse(JSON.stringify(defaultConfig)));
      if (form.value) {
        form.value.resetValidation();
      }
    }
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent("v-icon");
      const _component_v_chip = _resolveComponent("v-chip");
      const _component_v_btn = _resolveComponent("v-btn");
      const _component_v_divider = _resolveComponent("v-divider");
      const _component_v_alert = _resolveComponent("v-alert");
      const _component_v_switch = _resolveComponent("v-switch");
      const _component_v_col = _resolveComponent("v-col");
      const _component_v_row = _resolveComponent("v-row");
      const _component_v_text_field = _resolveComponent("v-text-field");
      const _component_v_tooltip = _resolveComponent("v-tooltip");
      const _component_v_select = _resolveComponent("v-select");
      const _component_v_card = _resolveComponent("v-card");
      const _component_v_badge = _resolveComponent("v-badge");
      const _component_v_tab = _resolveComponent("v-tab");
      const _component_v_tabs = _resolveComponent("v-tabs");
      const _component_v_combobox = _resolveComponent("v-combobox");
      const _component_v_spacer = _resolveComponent("v-spacer");
      const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
      const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
      const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
      const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
      const _component_v_window_item = _resolveComponent("v-window-item");
      const _component_v_radio = _resolveComponent("v-radio");
      const _component_v_radio_group = _resolveComponent("v-radio-group");
      const _component_v_window = _resolveComponent("v-window");
      const _component_v_form = _resolveComponent("v-form");
      const _component_v_card_text = _resolveComponent("v-card-text");
      const _component_v_snackbar = _resolveComponent("v-snackbar");
      const _component_v_card_title = _resolveComponent("v-card-title");
      const _component_v_card_actions = _resolveComponent("v-card-actions");
      const _component_v_dialog = _resolveComponent("v-dialog");
      return _openBlock(), _createElementBlock("div", _hoisted_1, [
        _createVNode(_component_v_card, { class: "modern-config-card border elevation-3 rounded-xl overflow-hidden" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _createElementVNode("div", _hoisted_3, [
                _createElementVNode("div", _hoisted_4, [
                  _createVNode(_component_v_icon, {
                    size: "28",
                    color: "white"
                  }, {
                    default: _withCtx(() => _cache[55] || (_cache[55] = [
                      _createTextVNode("mdi-tune-variant")
                    ])),
                    _: 1
                  })
                ]),
                _createElementVNode("div", null, [
                  _createElementVNode("div", _hoisted_5, [
                    _cache[56] || (_cache[56] = _createElementVNode("h2", { class: "text-h6 text-md-h5 font-weight-bold text-gradient" }, " Clash Rule Provider ", -1)),
                    _createVNode(_component_v_chip, {
                      color: config.enabled ? "success" : "grey",
                      size: "small",
                      variant: "tonal",
                      class: "font-weight-bold ml-2"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_icon, {
                          start: "",
                          size: "14"
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(config.enabled ? "mdi-check-circle" : "mdi-pause-circle"), 1)
                          ]),
                          _: 1
                        }),
                        _createTextVNode(" " + _toDisplayString(config.enabled ? "已启用" : "未启用"), 1)
                      ]),
                      _: 1
                    }, 8, ["color"])
                  ]),
                  _cache[57] || (_cache[57] = _createElementVNode("p", { class: "text-body-2 text-medium-emphasis mt-1 mb-0" }, " 随时为 Clash 添加一些额外的规则 ", -1))
                ])
              ]),
              _createElementVNode("div", _hoisted_6, [
                _createVNode(_component_v_btn, {
                  color: "primary",
                  variant: "tonal",
                  size: "small",
                  class: "rounded-lg text-none",
                  onClick: _cache[0] || (_cache[0] = ($event) => emit("switch"))
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { start: "" }, {
                      default: _withCtx(() => _cache[58] || (_cache[58] = [
                        _createTextVNode("mdi-view-dashboard-edit")
                      ])),
                      _: 1
                    }),
                    _cache[59] || (_cache[59] = _createTextVNode(" 切换至规则 "))
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  icon: "",
                  variant: "text",
                  color: "grey-darken-1",
                  density: "comfortable",
                  onClick: _cache[1] || (_cache[1] = ($event) => emit("close"))
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, null, {
                      default: _withCtx(() => _cache[60] || (_cache[60] = [
                        _createTextVNode("mdi-close")
                      ])),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ])
            ]),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_text, { class: "pa-4 pa-md-6" }, {
              default: _withCtx(() => [
                error.value ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "error",
                  variant: "tonal",
                  closable: "",
                  class: "mb-6 rounded-lg border-error",
                  "onClick:close": _cache[2] || (_cache[2] = ($event) => error.value = "")
                }, {
                  prepend: _withCtx(() => [
                    _createVNode(_component_v_icon, { color: "error" }, {
                      default: _withCtx(() => _cache[61] || (_cache[61] = [
                        _createTextVNode("mdi-alert-circle")
                      ])),
                      _: 1
                    })
                  ]),
                  default: _withCtx(() => [
                    _createElementVNode("span", _hoisted_7, _toDisplayString(error.value), 1)
                  ]),
                  _: 1
                })) : _createCommentVNode("", true),
                _createVNode(_component_v_form, {
                  ref_key: "form",
                  ref: form,
                  modelValue: isFormValid.value,
                  "onUpdate:modelValue": _cache[47] || (_cache[47] = ($event) => isFormValid.value = $event),
                  onSubmit: _withModifiers(saveConfig, ["prevent"])
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_8, [
                      _createElementVNode("div", _hoisted_9, [
                        _createVNode(_component_v_icon, {
                          size: "16",
                          class: "mr-2",
                          color: "primary"
                        }, {
                          default: _withCtx(() => _cache[62] || (_cache[62] = [
                            _createTextVNode("mdi-lightning-bolt")
                          ])),
                          _: 1
                        }),
                        _cache[63] || (_cache[63] = _createTextVNode(" 核心功能开关 "))
                      ]),
                      _createVNode(_component_v_row, { dense: "" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            md: "3"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", {
                                class: _normalizeClass(["switch-card switch-card--primary rounded-lg pa-3 pa-md-4 d-flex align-center justify-space-between transition-all cursor-pointer select-none", { "switch-card--active": config.enabled }]),
                                onClick: _cache[5] || (_cache[5] = ($event) => config.enabled = !config.enabled)
                              }, [
                                _createElementVNode("div", _hoisted_10, [
                                  _createElementVNode("div", _hoisted_11, [
                                    _createVNode(_component_v_icon, {
                                      color: config.enabled ? "primary" : "grey-darken-1"
                                    }, {
                                      default: _withCtx(() => _cache[64] || (_cache[64] = [
                                        _createTextVNode("mdi-power")
                                      ])),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _cache[65] || (_cache[65] = _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用插件"),
                                    _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "运行插件服务")
                                  ], -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.enabled,
                                  "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => config.enabled = $event),
                                  color: "primary",
                                  "hide-details": "",
                                  inset: "",
                                  density: "compact",
                                  onClick: _cache[4] || (_cache[4] = _withModifiers(() => {
                                  }, ["stop"]))
                                }, null, 8, ["modelValue"])
                              ], 2)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            md: "3"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", {
                                class: _normalizeClass(["switch-card switch-card--info rounded-lg pa-3 pa-md-4 d-flex align-center justify-space-between transition-all cursor-pointer select-none", { "switch-card--active": config.proxy }]),
                                onClick: _cache[8] || (_cache[8] = ($event) => config.proxy = !config.proxy)
                              }, [
                                _createElementVNode("div", _hoisted_12, [
                                  _createElementVNode("div", _hoisted_13, [
                                    _createVNode(_component_v_icon, {
                                      color: config.proxy ? "info" : "grey-darken-1"
                                    }, {
                                      default: _withCtx(() => _cache[66] || (_cache[66] = [
                                        _createTextVNode("mdi-lan-connect")
                                      ])),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _cache[67] || (_cache[67] = _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用代理"),
                                    _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "网络请求代理")
                                  ], -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.proxy,
                                  "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => config.proxy = $event),
                                  color: "info",
                                  "hide-details": "",
                                  inset: "",
                                  density: "compact",
                                  onClick: _cache[7] || (_cache[7] = _withModifiers(() => {
                                  }, ["stop"]))
                                }, null, 8, ["modelValue"])
                              ], 2)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            md: "3"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", {
                                class: _normalizeClass(["switch-card switch-card--warning rounded-lg pa-3 pa-md-4 d-flex align-center justify-space-between transition-all cursor-pointer select-none", { "switch-card--active": config.notify }]),
                                onClick: _cache[11] || (_cache[11] = ($event) => config.notify = !config.notify)
                              }, [
                                _createElementVNode("div", _hoisted_14, [
                                  _createElementVNode("div", _hoisted_15, [
                                    _createVNode(_component_v_icon, {
                                      color: config.notify ? "warning" : "grey-darken-1"
                                    }, {
                                      default: _withCtx(() => _cache[68] || (_cache[68] = [
                                        _createTextVNode("mdi-bell-outline")
                                      ])),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _cache[69] || (_cache[69] = _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "运行通知"),
                                    _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "发送消息推送")
                                  ], -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.notify,
                                  "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => config.notify = $event),
                                  color: "warning",
                                  "hide-details": "",
                                  inset: "",
                                  density: "compact",
                                  onClick: _cache[10] || (_cache[10] = _withModifiers(() => {
                                  }, ["stop"]))
                                }, null, 8, ["modelValue"])
                              ], 2)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            md: "3"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", {
                                class: _normalizeClass(["switch-card switch-card--success rounded-lg pa-3 pa-md-4 d-flex align-center justify-space-between transition-all cursor-pointer select-none", { "switch-card--active": config.auto_update_subscriptions }]),
                                onClick: _cache[14] || (_cache[14] = ($event) => config.auto_update_subscriptions = !config.auto_update_subscriptions)
                              }, [
                                _createElementVNode("div", _hoisted_16, [
                                  _createElementVNode("div", _hoisted_17, [
                                    _createVNode(_component_v_icon, {
                                      color: config.auto_update_subscriptions ? "success" : "grey-darken-1"
                                    }, {
                                      default: _withCtx(() => _cache[70] || (_cache[70] = [
                                        _createTextVNode(" mdi-sync ")
                                      ])),
                                      _: 1
                                    }, 8, ["color"])
                                  ]),
                                  _cache[71] || (_cache[71] = _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "自动更新"),
                                    _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "定时同步订阅")
                                  ], -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.auto_update_subscriptions,
                                  "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => config.auto_update_subscriptions = $event),
                                  color: "success",
                                  "hide-details": "",
                                  inset: "",
                                  density: "compact",
                                  onClick: _cache[13] || (_cache[13] = _withModifiers(() => {
                                  }, ["stop"]))
                                }, null, 8, ["modelValue"])
                              ], 2)
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _createVNode(_component_v_card, {
                      variant: "outlined",
                      class: "section-card border rounded-xl pa-4 mb-6 bg-surface"
                    }, {
                      default: _withCtx(() => [
                        _createElementVNode("div", _hoisted_18, [
                          _createVNode(_component_v_icon, {
                            size: "16",
                            class: "mr-2",
                            color: "primary"
                          }, {
                            default: _withCtx(() => _cache[72] || (_cache[72] = [
                              _createTextVNode("mdi-server-network")
                            ])),
                            _: 1
                          }),
                          _cache[73] || (_cache[73] = _createTextVNode(" 基础配置 "))
                        ]),
                        _createVNode(_component_v_row, { dense: "" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "4"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_text_field, {
                                  modelValue: config.movie_pilot_url,
                                  "onUpdate:modelValue": _cache[15] || (_cache[15] = ($event) => config.movie_pilot_url = $event),
                                  label: "MoviePilot URL",
                                  variant: "outlined",
                                  density: "comfortable",
                                  placeholder: "http://localhost:3001",
                                  hint: "MoviePilot 服务访问地址",
                                  "persistent-hint": "",
                                  class: "custom-input",
                                  rules: [
                                    (v) => !!v || "MoviePilot URL 不能为空",
                                    (v) => _unref(isValidUrl)(v) || "请输入有效的 URL 地址"
                                  ]
                                }, {
                                  "prepend-inner": _withCtx(() => [
                                    _createVNode(_component_v_icon, {
                                      color: "primary",
                                      size: "20"
                                    }, {
                                      default: _withCtx(() => _cache[74] || (_cache[74] = [
                                        _createTextVNode("mdi-movie-open")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }, 8, ["modelValue", "rules"])
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "4"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_text_field, {
                                  modelValue: config.apikey,
                                  "onUpdate:modelValue": _cache[16] || (_cache[16] = ($event) => config.apikey = $event),
                                  label: "API Key",
                                  variant: "outlined",
                                  density: "comfortable",
                                  placeholder: "留空使用系统 API Key",
                                  hint: "服务鉴权凭证",
                                  "persistent-hint": "",
                                  class: "custom-input"
                                }, {
                                  "prepend-inner": _withCtx(() => [
                                    _createVNode(_component_v_icon, {
                                      color: "warning",
                                      size: "20"
                                    }, {
                                      default: _withCtx(() => _cache[75] || (_cache[75] = [
                                        _createTextVNode("mdi-key-variant")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  "append-inner": _withCtx(() => [
                                    _createVNode(_component_v_tooltip, {
                                      location: "top",
                                      text: "自动生成随机 Key"
                                    }, {
                                      activator: _withCtx(({ props: slotProps }) => [
                                        _createVNode(_component_v_btn, _mergeProps(slotProps, {
                                          icon: "mdi-autorenew",
                                          size: "x-small",
                                          variant: "text",
                                          color: "primary",
                                          class: "rotate-on-hover",
                                          onClick: generateApiKey
                                        }), null, 16)
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }, 8, ["modelValue"])
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "4"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_select, {
                                  modelValue: config.dashboard_components,
                                  "onUpdate:modelValue": _cache[17] || (_cache[17] = ($event) => config.dashboard_components = $event),
                                  items: dashboardComponents,
                                  label: "仪表盘组件",
                                  variant: "outlined",
                                  density: "comfortable",
                                  multiple: "",
                                  chips: "",
                                  "closable-chips": "",
                                  hint: "选中的组件将在仪表盘中展示",
                                  "persistent-hint": "",
                                  class: "custom-input"
                                }, {
                                  "prepend-inner": _withCtx(() => [
                                    _createVNode(_component_v_icon, {
                                      color: "info",
                                      size: "20"
                                    }, {
                                      default: _withCtx(() => _cache[76] || (_cache[76] = [
                                        _createTextVNode("mdi-view-dashboard-outline")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  chip: _withCtx(({ props: slotProps, item }) => [
                                    _createVNode(_component_v_chip, _mergeProps(slotProps, {
                                      size: "small",
                                      color: "info",
                                      variant: "tonal",
                                      class: "font-weight-medium"
                                    }), {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(item.value), 1)
                                      ]),
                                      _: 2
                                    }, 1040)
                                  ]),
                                  _: 1
                                }, 8, ["modelValue"])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createElementVNode("div", _hoisted_19, [
                      _createVNode(_component_v_tabs, {
                        modelValue: activeTab.value,
                        "onUpdate:modelValue": _cache[18] || (_cache[18] = ($event) => activeTab.value = $event),
                        color: "primary",
                        "align-tabs": "start",
                        class: "custom-modern-tabs"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_tab, {
                            value: "subscription",
                            class: "rounded-lg text-none px-4 py-2 font-weight-bold"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, {
                                start: "",
                                size: "18"
                              }, {
                                default: _withCtx(() => _cache[77] || (_cache[77] = [
                                  _createTextVNode("mdi-link-variant")
                                ])),
                                _: 1
                              }),
                              _cache[78] || (_cache[78] = _createTextVNode(" 订阅配置 ")),
                              config.subscriptions_config?.length ? (_openBlock(), _createBlock(_component_v_badge, {
                                key: 0,
                                content: config.subscriptions_config.length,
                                color: "primary",
                                inline: "",
                                class: "ml-2"
                              }, null, 8, ["content"])) : _createCommentVNode("", true)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_tab, {
                            value: "clash",
                            class: "rounded-lg text-none px-4 py-2 font-weight-bold"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, {
                                start: "",
                                size: "18"
                              }, {
                                default: _withCtx(() => _cache[79] || (_cache[79] = [
                                  _createTextVNode("mdi-application-brackets-outline")
                                ])),
                                _: 1
                              }),
                              _cache[80] || (_cache[80] = _createTextVNode(" Clash API 配置 ")),
                              config.clash_dashboards?.length ? (_openBlock(), _createBlock(_component_v_badge, {
                                key: 0,
                                content: config.clash_dashboards.length,
                                color: "info",
                                inline: "",
                                class: "ml-2"
                              }, null, 8, ["content"])) : _createCommentVNode("", true)
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_tab, {
                            value: "execution",
                            class: "rounded-lg text-none px-4 py-2 font-weight-bold"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, {
                                start: "",
                                size: "18"
                              }, {
                                default: _withCtx(() => _cache[81] || (_cache[81] = [
                                  _createTextVNode("mdi-clock-time-four-outline")
                                ])),
                                _: 1
                              }),
                              _cache[82] || (_cache[82] = _createTextVNode(" 执行与定时 "))
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_tab, {
                            value: "settings",
                            class: "rounded-lg text-none px-4 py-2 font-weight-bold"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, {
                                start: "",
                                size: "18"
                              }, {
                                default: _withCtx(() => _cache[83] || (_cache[83] = [
                                  _createTextVNode("mdi-tune")
                                ])),
                                _: 1
                              }),
                              _cache[84] || (_cache[84] = _createTextVNode(" 高级与规则集 "))
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }, 8, ["modelValue"])
                    ]),
                    _createVNode(_component_v_window, {
                      modelValue: activeTab.value,
                      "onUpdate:modelValue": _cache[46] || (_cache[46] = ($event) => activeTab.value = $event),
                      class: "tab-window-content"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_window_item, { value: "subscription" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_card, {
                              variant: "flat",
                              class: "pa-4 border rounded-xl bg-surface"
                            }, {
                              default: _withCtx(() => [
                                _createElementVNode("div", _hoisted_20, [
                                  _cache[89] || (_cache[89] = _createElementVNode("div", { class: "text-subtitle-2 font-weight-bold mb-2" }, "节点分组与过滤设置", -1)),
                                  _createVNode(_component_v_row, { dense: "" }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx(() => [
                                          _createElementVNode("div", {
                                            class: "feature-toggle-item d-flex align-center justify-space-between border rounded-lg pa-3 cursor-pointer select-none transition-all",
                                            onClick: _cache[21] || (_cache[21] = ($event) => config.group_by_country = !config.group_by_country)
                                          }, [
                                            _createElementVNode("div", _hoisted_21, [
                                              _createVNode(_component_v_icon, {
                                                color: "primary",
                                                size: "20"
                                              }, {
                                                default: _withCtx(() => _cache[85] || (_cache[85] = [
                                                  _createTextVNode("mdi-flag-outline")
                                                ])),
                                                _: 1
                                              }),
                                              _cache[86] || (_cache[86] = _createElementVNode("div", null, [
                                                _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "按国家/地区分组节点"),
                                                _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 根据节点名称自动归类国家代理组 ")
                                              ], -1))
                                            ]),
                                            _createVNode(_component_v_switch, {
                                              modelValue: config.group_by_country,
                                              "onUpdate:modelValue": _cache[19] || (_cache[19] = ($event) => config.group_by_country = $event),
                                              color: "primary",
                                              "hide-details": "",
                                              inset: "",
                                              density: "compact",
                                              onClick: _cache[20] || (_cache[20] = _withModifiers(() => {
                                              }, ["stop"]))
                                            }, null, 8, ["modelValue"])
                                          ])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx(() => [
                                          _createElementVNode("div", {
                                            class: "feature-toggle-item d-flex align-center justify-space-between border rounded-lg pa-3 cursor-pointer select-none transition-all",
                                            onClick: _cache[24] || (_cache[24] = ($event) => config.group_by_region = !config.group_by_region)
                                          }, [
                                            _createElementVNode("div", _hoisted_22, [
                                              _createVNode(_component_v_icon, {
                                                color: "primary",
                                                size: "20"
                                              }, {
                                                default: _withCtx(() => _cache[87] || (_cache[87] = [
                                                  _createTextVNode("mdi-earth")
                                                ])),
                                                _: 1
                                              }),
                                              _cache[88] || (_cache[88] = _createElementVNode("div", null, [
                                                _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "按大洲/区域分组节点"),
                                                _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 根据节点名称自动归类大洲代理组 ")
                                              ], -1))
                                            ]),
                                            _createVNode(_component_v_switch, {
                                              modelValue: config.group_by_region,
                                              "onUpdate:modelValue": _cache[22] || (_cache[22] = ($event) => config.group_by_region = $event),
                                              color: "primary",
                                              "hide-details": "",
                                              inset: "",
                                              density: "compact",
                                              onClick: _cache[23] || (_cache[23] = _withModifiers(() => {
                                              }, ["stop"]))
                                            }, null, 8, ["modelValue"])
                                          ])
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _createVNode(_component_v_combobox, {
                                  modelValue: config.filter_keywords,
                                  "onUpdate:modelValue": _cache[25] || (_cache[25] = ($event) => config.filter_keywords = $event),
                                  label: "节点过滤关键词",
                                  variant: "outlined",
                                  density: "comfortable",
                                  multiple: "",
                                  chips: "",
                                  "closable-chips": "",
                                  clearable: "",
                                  hint: "按 Enter 添加无需导入的节点过滤关键字",
                                  "persistent-hint": "",
                                  class: "mb-6"
                                }, {
                                  "prepend-inner": _withCtx(() => [
                                    _createVNode(_component_v_icon, {
                                      color: "info",
                                      size: "20"
                                    }, {
                                      default: _withCtx(() => _cache[90] || (_cache[90] = [
                                        _createTextVNode("mdi-filter-variant")
                                      ])),
                                      _: 1
                                    })
                                  ]),
                                  chip: _withCtx(({ props: slotProps, item }) => [
                                    _createVNode(_component_v_chip, _mergeProps(slotProps, {
                                      closable: "",
                                      size: "small",
                                      color: "info",
                                      variant: "tonal",
                                      class: "font-weight-medium"
                                    }), {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(item.value), 1)
                                      ]),
                                      _: 2
                                    }, 1040)
                                  ]),
                                  _: 1
                                }, 8, ["modelValue"]),
                                _createVNode(_component_v_divider, { class: "my-4" }),
                                _createElementVNode("div", _hoisted_23, [
                                  _createElementVNode("div", _hoisted_24, [
                                    _createVNode(_component_v_icon, {
                                      color: "primary",
                                      class: "mr-2"
                                    }, {
                                      default: _withCtx(() => _cache[91] || (_cache[91] = [
                                        _createTextVNode("mdi-link-box-variant-outline")
                                      ])),
                                      _: 1
                                    }),
                                    _cache[92] || (_cache[92] = _createTextVNode(" 订阅链接配置列表 "))
                                  ]),
                                  _createElementVNode("div", _hoisted_25, [
                                    _createVNode(_component_v_btn, {
                                      size: "small",
                                      color: "primary",
                                      variant: "tonal",
                                      class: "rounded-lg",
                                      onClick: addSubscriptionConfig
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_icon, { start: "" }, {
                                          default: _withCtx(() => _cache[93] || (_cache[93] = [
                                            _createTextVNode("mdi-plus")
                                          ])),
                                          _: 1
                                        }),
                                        _cache[94] || (_cache[94] = _createTextVNode(" 添加订阅 "))
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_btn, {
                                      size: "small",
                                      color: "secondary",
                                      variant: "outlined",
                                      class: "rounded-lg",
                                      onClick: openClashTemplateDialog
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_icon, { start: "" }, {
                                          default: _withCtx(() => _cache[95] || (_cache[95] = [
                                            _createTextVNode("mdi-file-code-outline")
                                          ])),
                                          _: 1
                                        }),
                                        _cache[96] || (_cache[96] = _createTextVNode(" 配置模板 "))
                                      ]),
                                      _: 1
                                    })
                                  ])
                                ]),
                                !config.subscriptions_config || config.subscriptions_config.length === 0 ? (_openBlock(), _createElementBlock("div", _hoisted_26, [
                                  _createVNode(_component_v_icon, {
                                    size: "48",
                                    color: "grey-lighten-1",
                                    class: "mb-2"
                                  }, {
                                    default: _withCtx(() => _cache[97] || (_cache[97] = [
                                      _createTextVNode("mdi-link-off")
                                    ])),
                                    _: 1
                                  }),
                                  _cache[100] || (_cache[100] = _createElementVNode("div", { class: "text-body-1 font-weight-medium text-medium-emphasis" }, " 暂未配置任何订阅链接 ", -1)),
                                  _cache[101] || (_cache[101] = _createElementVNode("div", { class: "text-caption text-disabled mb-4" }, " 点击上方“添加订阅”按钮以配置 Clash 规则订阅 ", -1)),
                                  _createVNode(_component_v_btn, {
                                    size: "small",
                                    color: "primary",
                                    variant: "flat",
                                    onClick: addSubscriptionConfig
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_icon, { start: "" }, {
                                        default: _withCtx(() => _cache[98] || (_cache[98] = [
                                          _createTextVNode("mdi-plus")
                                        ])),
                                        _: 1
                                      }),
                                      _cache[99] || (_cache[99] = _createTextVNode(" 立即添加 "))
                                    ]),
                                    _: 1
                                  })
                                ])) : (_openBlock(), _createBlock(_component_v_expansion_panels, {
                                  key: 1,
                                  multiple: "",
                                  class: "sub-panels"
                                }, {
                                  default: _withCtx(() => [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.subscriptions_config, (item, index) => {
                                      return _openBlock(), _createBlock(_component_v_expansion_panel, {
                                        key: index,
                                        class: "border rounded-xl mb-3 overflow-hidden",
                                        elevation: "0"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_expansion_panel_title, { class: "py-3 px-4" }, {
                                            default: _withCtx(() => [
                                              _createElementVNode("div", _hoisted_27, [
                                                _createVNode(_component_v_chip, {
                                                  color: "primary",
                                                  size: "small",
                                                  variant: "flat",
                                                  class: "font-weight-bold"
                                                }, {
                                                  default: _withCtx(() => [
                                                    _createTextVNode(" #" + _toDisplayString(index + 1), 1)
                                                  ]),
                                                  _: 2
                                                }, 1024),
                                                _createElementVNode("div", _hoisted_28, _toDisplayString(getUrlHostname(item.url)), 1),
                                                activeOptionsCount(item) > 0 ? (_openBlock(), _createBlock(_component_v_chip, {
                                                  key: 0,
                                                  size: "x-small",
                                                  color: "success",
                                                  variant: "tonal",
                                                  class: "ml-2"
                                                }, {
                                                  default: _withCtx(() => [
                                                    _createTextVNode(" 已勾选 " + _toDisplayString(activeOptionsCount(item)) + " 项保留 ", 1)
                                                  ]),
                                                  _: 2
                                                }, 1024)) : _createCommentVNode("", true),
                                                _createVNode(_component_v_spacer),
                                                _createVNode(_component_v_btn, {
                                                  icon: "mdi-delete-outline",
                                                  size: "small",
                                                  color: "error",
                                                  variant: "text",
                                                  class: "mr-2",
                                                  onClick: _withModifiers(($event) => removeSubscriptionConfig(index), ["stop"])
                                                }, null, 8, ["onClick"])
                                              ])
                                            ]),
                                            _: 2
                                          }, 1024),
                                          _createVNode(_component_v_expansion_panel_text, { class: "pa-4" }, {
                                            default: _withCtx(() => [
                                              _createVNode(_component_v_text_field, {
                                                modelValue: item.url,
                                                "onUpdate:modelValue": ($event) => item.url = $event,
                                                label: "订阅 URL 链接",
                                                variant: "outlined",
                                                density: "comfortable",
                                                placeholder: "https://example.com/clash/config.yaml",
                                                class: "mb-4",
                                                rules: [
                                                  (v) => !!v || "订阅链接不能为空",
                                                  (v) => _unref(isValidUrl)(v) || "请输入有效的 URL 地址"
                                                ]
                                              }, {
                                                "prepend-inner": _withCtx(() => [
                                                  _createVNode(_component_v_icon, {
                                                    color: "primary",
                                                    size: "20"
                                                  }, {
                                                    default: _withCtx(() => _cache[102] || (_cache[102] = [
                                                      _createTextVNode("mdi-link")
                                                    ])),
                                                    _: 1
                                                  })
                                                ]),
                                                _: 2
                                              }, 1032, ["modelValue", "onUpdate:modelValue", "rules"]),
                                              _cache[107] || (_cache[107] = _createElementVNode("div", { class: "text-caption text-medium-emphasis font-weight-bold mb-2" }, " 保留选项设置 ", -1)),
                                              _createVNode(_component_v_row, { dense: "" }, {
                                                default: _withCtx(() => [
                                                  _createVNode(_component_v_col, {
                                                    cols: "12",
                                                    sm: "6",
                                                    md: "3"
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createElementVNode("div", {
                                                        class: "option-toggle-box rounded-lg pa-2 border d-flex align-center justify-space-between cursor-pointer select-none",
                                                        onClick: ($event) => item.rules = !item.rules
                                                      }, [
                                                        _cache[103] || (_cache[103] = _createElementVNode("span", { class: "text-caption font-weight-medium" }, "保留规则", -1)),
                                                        _createVNode(_component_v_switch, {
                                                          modelValue: item.rules,
                                                          "onUpdate:modelValue": ($event) => item.rules = $event,
                                                          color: "primary",
                                                          "hide-details": "",
                                                          density: "compact",
                                                          onClick: _cache[26] || (_cache[26] = _withModifiers(() => {
                                                          }, ["stop"]))
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                      ], 8, _hoisted_29)
                                                    ]),
                                                    _: 2
                                                  }, 1024),
                                                  _createVNode(_component_v_col, {
                                                    cols: "12",
                                                    sm: "6",
                                                    md: "3"
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createElementVNode("div", {
                                                        class: "option-toggle-box rounded-lg pa-2 border d-flex align-center justify-space-between cursor-pointer select-none",
                                                        onClick: ($event) => item["rule-providers"] = !item["rule-providers"]
                                                      }, [
                                                        _cache[104] || (_cache[104] = _createElementVNode("span", { class: "text-caption font-weight-medium" }, "保留规则集合", -1)),
                                                        _createVNode(_component_v_switch, {
                                                          modelValue: item["rule-providers"],
                                                          "onUpdate:modelValue": ($event) => item["rule-providers"] = $event,
                                                          color: "primary",
                                                          "hide-details": "",
                                                          density: "compact",
                                                          onClick: _cache[27] || (_cache[27] = _withModifiers(() => {
                                                          }, ["stop"]))
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                      ], 8, _hoisted_30)
                                                    ]),
                                                    _: 2
                                                  }, 1024),
                                                  _createVNode(_component_v_col, {
                                                    cols: "12",
                                                    sm: "6",
                                                    md: "3"
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createElementVNode("div", {
                                                        class: "option-toggle-box rounded-lg pa-2 border d-flex align-center justify-space-between cursor-pointer select-none",
                                                        onClick: ($event) => item["proxy-groups"] = !item["proxy-groups"]
                                                      }, [
                                                        _cache[105] || (_cache[105] = _createElementVNode("span", { class: "text-caption font-weight-medium" }, "保留代理组", -1)),
                                                        _createVNode(_component_v_switch, {
                                                          modelValue: item["proxy-groups"],
                                                          "onUpdate:modelValue": ($event) => item["proxy-groups"] = $event,
                                                          color: "primary",
                                                          "hide-details": "",
                                                          density: "compact",
                                                          onClick: _cache[28] || (_cache[28] = _withModifiers(() => {
                                                          }, ["stop"]))
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                      ], 8, _hoisted_31)
                                                    ]),
                                                    _: 2
                                                  }, 1024),
                                                  _createVNode(_component_v_col, {
                                                    cols: "12",
                                                    sm: "6",
                                                    md: "3"
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createElementVNode("div", {
                                                        class: "option-toggle-box rounded-lg pa-2 border d-flex align-center justify-space-between cursor-pointer select-none",
                                                        onClick: ($event) => item["proxy-providers"] = !item["proxy-providers"]
                                                      }, [
                                                        _cache[106] || (_cache[106] = _createElementVNode("span", { class: "text-caption font-weight-medium" }, "保留代理集合", -1)),
                                                        _createVNode(_component_v_switch, {
                                                          modelValue: item["proxy-providers"],
                                                          "onUpdate:modelValue": ($event) => item["proxy-providers"] = $event,
                                                          color: "primary",
                                                          "hide-details": "",
                                                          density: "compact",
                                                          onClick: _cache[29] || (_cache[29] = _withModifiers(() => {
                                                          }, ["stop"]))
                                                        }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                                      ], 8, _hoisted_32)
                                                    ]),
                                                    _: 2
                                                  }, 1024)
                                                ]),
                                                _: 2
                                              }, 1024)
                                            ]),
                                            _: 2
                                          }, 1024)
                                        ]),
                                        _: 2
                                      }, 1024);
                                    }), 128))
                                  ]),
                                  _: 1
                                }))
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_window_item, { value: "clash" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_card, {
                              variant: "flat",
                              class: "pa-4 border rounded-lg bg-surface"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_alert, {
                                  type: "info",
                                  variant: "tonal",
                                  density: "comfortable",
                                  class: "mb-4 rounded-lg",
                                  icon: "mdi-information-outline"
                                }, {
                                  default: _withCtx(() => _cache[108] || (_cache[108] = [
                                    _createElementVNode("div", { class: "text-caption font-weight-medium" }, " Clash API 用于通知 Clash 更新规则集；选中的活动面板将作为小组件展示。 ", -1)
                                  ])),
                                  _: 1
                                }),
                                _createVNode(_component_v_radio_group, {
                                  modelValue: config.active_dashboard,
                                  "onUpdate:modelValue": _cache[30] || (_cache[30] = ($event) => config.active_dashboard = $event),
                                  "hide-details": "",
                                  class: "w-100"
                                }, {
                                  default: _withCtx(() => [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.clash_dashboards, (item, index) => {
                                      return _openBlock(), _createElementBlock("div", {
                                        key: index,
                                        class: _normalizeClass(["api-endpoint-card border rounded-lg pa-3 pa-md-4 mb-3 transition-all", { "api-endpoint-card--active": config.active_dashboard === index }])
                                      }, [
                                        _createVNode(_component_v_row, {
                                          dense: "",
                                          align: "center"
                                        }, {
                                          default: _withCtx(() => [
                                            _createVNode(_component_v_col, {
                                              cols: "12",
                                              sm: "1",
                                              class: "d-flex align-center justify-start justify-sm-center"
                                            }, {
                                              default: _withCtx(() => [
                                                _createVNode(_component_v_radio, {
                                                  value: index,
                                                  color: "primary",
                                                  "hide-details": ""
                                                }, null, 8, ["value"]),
                                                _cache[109] || (_cache[109] = _createElementVNode("span", { class: "text-caption font-weight-bold ml-1 d-sm-none" }, "设为活动面板", -1))
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_v_col, {
                                              cols: "12",
                                              sm: "5"
                                            }, {
                                              default: _withCtx(() => [
                                                _createVNode(_component_v_text_field, {
                                                  modelValue: item.url,
                                                  "onUpdate:modelValue": ($event) => item.url = $event,
                                                  label: "API 访问 URL",
                                                  variant: "outlined",
                                                  density: "comfortable",
                                                  placeholder: "http://localhost:9090",
                                                  "hide-details": "auto",
                                                  rules: [(v) => !v || _unref(isValidUrl)(v) || "请输入有效的 URL"]
                                                }, {
                                                  "prepend-inner": _withCtx(() => [
                                                    _createVNode(_component_v_icon, {
                                                      color: "primary",
                                                      size: "20"
                                                    }, {
                                                      default: _withCtx(() => _cache[110] || (_cache[110] = [
                                                        _createTextVNode("mdi-web")
                                                      ])),
                                                      _: 1
                                                    })
                                                  ]),
                                                  _: 2
                                                }, 1032, ["modelValue", "onUpdate:modelValue", "rules"])
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_v_col, {
                                              cols: "12",
                                              sm: "5"
                                            }, {
                                              default: _withCtx(() => [
                                                _createVNode(_component_v_text_field, {
                                                  modelValue: item.secret,
                                                  "onUpdate:modelValue": ($event) => item.secret = $event,
                                                  label: "API 密钥 (Secret)",
                                                  variant: "outlined",
                                                  density: "comfortable",
                                                  placeholder: "your-clash-secret",
                                                  "hide-details": "auto",
                                                  type: showSecrets.value[index] ? "text" : "password",
                                                  "append-inner-icon": showSecrets.value[index] ? "mdi-eye-off-outline" : "mdi-eye-outline",
                                                  "onClick:appendInner": ($event) => toggleSecret(index)
                                                }, {
                                                  "prepend-inner": _withCtx(() => [
                                                    _createVNode(_component_v_icon, {
                                                      color: "warning",
                                                      size: "20"
                                                    }, {
                                                      default: _withCtx(() => _cache[111] || (_cache[111] = [
                                                        _createTextVNode("mdi-shield-key-outline")
                                                      ])),
                                                      _: 1
                                                    })
                                                  ]),
                                                  _: 2
                                                }, 1032, ["modelValue", "onUpdate:modelValue", "type", "append-inner-icon", "onClick:appendInner"])
                                              ]),
                                              _: 2
                                            }, 1024),
                                            _createVNode(_component_v_col, {
                                              cols: "12",
                                              sm: "1",
                                              class: "d-flex align-center justify-end"
                                            }, {
                                              default: _withCtx(() => [
                                                _createVNode(_component_v_btn, {
                                                  icon: "mdi-delete-outline",
                                                  color: "error",
                                                  variant: "text",
                                                  size: "small",
                                                  onClick: ($event) => removeClashConfig(index)
                                                }, null, 8, ["onClick"])
                                              ]),
                                              _: 2
                                            }, 1024)
                                          ]),
                                          _: 2
                                        }, 1024)
                                      ], 2);
                                    }), 128))
                                  ]),
                                  _: 1
                                }, 8, ["modelValue"]),
                                _createVNode(_component_v_btn, {
                                  size: "small",
                                  color: "primary",
                                  variant: "tonal",
                                  class: "rounded-lg mt-2",
                                  onClick: addClashConfig
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, { start: "" }, {
                                      default: _withCtx(() => _cache[112] || (_cache[112] = [
                                        _createTextVNode("mdi-plus")
                                      ])),
                                      _: 1
                                    }),
                                    _cache[113] || (_cache[113] = _createTextVNode(" 添加 Clash API 地址 "))
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_window_item, { value: "execution" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_card, {
                              variant: "flat",
                              class: "pa-4 border rounded-xl bg-surface"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_row, { dense: "" }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.cron_string,
                                          "onUpdate:modelValue": _cache[31] || (_cache[31] = ($event) => config.cron_string = $event),
                                          label: "执行周期 (Cron 表达式)",
                                          variant: "outlined",
                                          density: "comfortable",
                                          placeholder: "0 */6 * * *",
                                          hint: "标准 Cron 表达式格式 (分 时 日 月 周)",
                                          "persistent-hint": "",
                                          class: "mb-3"
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "info",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[114] || (_cache[114] = [
                                                _createTextVNode("mdi-clock-outline")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue"]),
                                        _createElementVNode("div", _hoisted_33, [
                                          _cache[115] || (_cache[115] = _createElementVNode("span", { class: "text-caption text-medium-emphasis mr-1" }, "快捷预设:", -1)),
                                          (_openBlock(), _createElementBlock(_Fragment, null, _renderList(cronPresets, (preset) => {
                                            return _createVNode(_component_v_chip, {
                                              key: preset.value,
                                              size: "x-small",
                                              color: "info",
                                              variant: "tonal",
                                              class: "cursor-pointer font-weight-medium",
                                              onClick: ($event) => config.cron_string = preset.value
                                            }, {
                                              default: _withCtx(() => [
                                                _createTextVNode(_toDisplayString(preset.label), 1)
                                              ]),
                                              _: 2
                                            }, 1032, ["onClick"]);
                                          }), 64))
                                        ])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.timeout,
                                          "onUpdate:modelValue": _cache[32] || (_cache[32] = ($event) => config.timeout = $event),
                                          modelModifiers: { number: true },
                                          label: "请求超时时间",
                                          variant: "outlined",
                                          density: "comfortable",
                                          type: "number",
                                          min: "1",
                                          max: "300",
                                          suffix: "秒",
                                          hint: "网络请求及订阅下载的超时时长",
                                          "persistent-hint": "",
                                          class: "mb-4",
                                          rules: [(v) => v > 0 || "超时时间必须大于 0"]
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "warning",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[116] || (_cache[116] = [
                                                _createTextVNode("mdi-timer-sand")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue", "rules"])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.retry_times,
                                          "onUpdate:modelValue": _cache[33] || (_cache[33] = ($event) => config.retry_times = $event),
                                          modelModifiers: { number: true },
                                          label: "失败重试次数",
                                          variant: "outlined",
                                          density: "comfortable",
                                          type: "number",
                                          min: "0",
                                          max: "10",
                                          hint: "请求失败时的自动重试次数",
                                          "persistent-hint": "",
                                          rules: [(v) => v >= 0 || "重试次数不能为负数"]
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "info",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[117] || (_cache[117] = [
                                                _createTextVNode("mdi-refresh")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue", "rules"])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.refresh_delay,
                                          "onUpdate:modelValue": _cache[34] || (_cache[34] = ($event) => config.refresh_delay = $event),
                                          modelModifiers: { number: true },
                                          label: "刷新延迟",
                                          variant: "outlined",
                                          density: "comfortable",
                                          type: "number",
                                          min: "1",
                                          max: "30",
                                          suffix: "秒",
                                          hint: "通知 Clash 刷新规则集的延迟秒数",
                                          "persistent-hint": "",
                                          rules: [(v) => v >= 0 || "刷新延迟不能为负数"]
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "primary",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[118] || (_cache[118] = [
                                                _createTextVNode("mdi-clock-fast")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue", "rules"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_window_item, { value: "settings" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_card, {
                              variant: "flat",
                              class: "pa-4 border rounded-xl bg-surface"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_row, {
                                  dense: "",
                                  class: "mb-4"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createElementVNode("div", {
                                          class: "feature-toggle-item d-flex align-center justify-space-between border rounded-lg pa-3 cursor-pointer select-none transition-all",
                                          onClick: _cache[37] || (_cache[37] = ($event) => config.hint_geo_dat = !config.hint_geo_dat)
                                        }, [
                                          _createElementVNode("div", _hoisted_34, [
                                            _createVNode(_component_v_icon, {
                                              color: "primary",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[119] || (_cache[119] = [
                                                _createTextVNode("mdi-database-search-outline")
                                              ])),
                                              _: 1
                                            }),
                                            _cache[120] || (_cache[120] = _createElementVNode("div", null, [
                                              _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "Geo 规则补全"),
                                              _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 自动获取 GeoIP / GeoSite 官方库补全 ")
                                            ], -1))
                                          ]),
                                          _createVNode(_component_v_switch, {
                                            modelValue: config.hint_geo_dat,
                                            "onUpdate:modelValue": _cache[35] || (_cache[35] = ($event) => config.hint_geo_dat = $event),
                                            color: "primary",
                                            "hide-details": "",
                                            inset: "",
                                            density: "compact",
                                            onClick: _cache[36] || (_cache[36] = _withModifiers(() => {
                                            }, ["stop"]))
                                          }, null, 8, ["modelValue"])
                                        ])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "6"
                                    }, {
                                      default: _withCtx(() => [
                                        _createElementVNode("div", {
                                          class: "feature-toggle-item d-flex align-center justify-space-between border rounded-lg pa-3 cursor-pointer select-none transition-all",
                                          onClick: _cache[40] || (_cache[40] = ($event) => config.enable_acl4ssr = !config.enable_acl4ssr)
                                        }, [
                                          _createElementVNode("div", _hoisted_35, [
                                            _createVNode(_component_v_icon, {
                                              color: "primary",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[121] || (_cache[121] = [
                                                _createTextVNode("mdi-shield-crown-outline")
                                              ])),
                                              _: 1
                                            }),
                                            _cache[122] || (_cache[122] = _createElementVNode("div", null, [
                                              _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "ACL4SSR 规则集"),
                                              _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 启用 ACL4SSR 规则集扩展支持 ")
                                            ], -1))
                                          ]),
                                          _createVNode(_component_v_switch, {
                                            modelValue: config.enable_acl4ssr,
                                            "onUpdate:modelValue": _cache[38] || (_cache[38] = ($event) => config.enable_acl4ssr = $event),
                                            color: "primary",
                                            "hide-details": "",
                                            inset: "",
                                            density: "compact",
                                            onClick: _cache[39] || (_cache[39] = _withModifiers(() => {
                                            }, ["stop"]))
                                          }, null, 8, ["modelValue"])
                                        ])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_row, {
                                  dense: "",
                                  class: "mb-2"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "4"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.ruleset_prefix,
                                          "onUpdate:modelValue": _cache[41] || (_cache[41] = ($event) => config.ruleset_prefix = $event),
                                          label: "规则集前缀",
                                          variant: "outlined",
                                          density: "comfortable",
                                          placeholder: "📂<=",
                                          hint: "生成规则集名称的前缀标识",
                                          "persistent-hint": ""
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "info",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[123] || (_cache[123] = [
                                                _createTextVNode("mdi-format-title")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "4"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.acl4ssr_prefix,
                                          "onUpdate:modelValue": _cache[42] || (_cache[42] = ($event) => config.acl4ssr_prefix = $event),
                                          label: "ACL4SSR 前缀",
                                          variant: "outlined",
                                          density: "comfortable",
                                          placeholder: "🗂️=>",
                                          hint: "ACL4SSR 规则集的前缀标识",
                                          "persistent-hint": ""
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "primary",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[124] || (_cache[124] = [
                                                _createTextVNode("mdi-tag-outline")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      md: "4"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_text_field, {
                                          modelValue: config.cache_ttl,
                                          "onUpdate:modelValue": _cache[43] || (_cache[43] = ($event) => config.cache_ttl = $event),
                                          modelModifiers: { number: true },
                                          label: "缓存 TTL",
                                          variant: "outlined",
                                          density: "comfortable",
                                          type: "number",
                                          min: "600",
                                          suffix: "秒",
                                          hint: "缓存超时时长",
                                          "persistent-hint": ""
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "warning",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[125] || (_cache[125] = [
                                                _createTextVNode("mdi-cached")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_row, { dense: "" }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_col, {
                                      cols: "12",
                                      class: "mb-3"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_combobox, {
                                          modelValue: config.best_cf_ip,
                                          "onUpdate:modelValue": _cache[44] || (_cache[44] = ($event) => config.best_cf_ip = $event),
                                          label: "Cloudflare CDN 优选 IPs",
                                          variant: "outlined",
                                          density: "comfortable",
                                          multiple: "",
                                          chips: "",
                                          "closable-chips": "",
                                          clearable: "",
                                          hint: "用于 Hosts 中关联的 Cloudflare CDN 优化 IP",
                                          "persistent-hint": "",
                                          rules: [_unref(validateIPs)]
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "warning",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[126] || (_cache[126] = [
                                                _createTextVNode("mdi-cloud-check-outline")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          chip: _withCtx(({ props: slotProps, item }) => [
                                            _createVNode(_component_v_chip, _mergeProps(slotProps, {
                                              closable: "",
                                              size: "small",
                                              color: "warning",
                                              variant: "tonal"
                                            }), {
                                              default: _withCtx(() => [
                                                _createTextVNode(_toDisplayString(item.value), 1)
                                              ]),
                                              _: 2
                                            }, 1040)
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue", "rules"])
                                      ]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_col, { cols: "12" }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_combobox, {
                                          modelValue: config.identifiers,
                                          "onUpdate:modelValue": _cache[45] || (_cache[45] = ($event) => config.identifiers = $event),
                                          label: "预设设备标识 (Identifiers)",
                                          variant: "outlined",
                                          density: "comfortable",
                                          multiple: "",
                                          chips: "",
                                          "closable-chips": "",
                                          clearable: "",
                                          hint: "获取配置时的额外 identifier 查询参数",
                                          "persistent-hint": ""
                                        }, {
                                          "prepend-inner": _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              color: "info",
                                              size: "20"
                                            }, {
                                              default: _withCtx(() => _cache[127] || (_cache[127] = [
                                                _createTextVNode("mdi-cellphone-link")
                                              ])),
                                              _: 1
                                            })
                                          ]),
                                          chip: _withCtx(({ props: slotProps, item }) => [
                                            _createVNode(_component_v_chip, _mergeProps(slotProps, {
                                              closable: "",
                                              size: "small",
                                              color: "info",
                                              variant: "tonal"
                                            }), {
                                              default: _withCtx(() => [
                                                _createTextVNode(_toDisplayString(item.value), 1)
                                              ]),
                                              _: 2
                                            }, 1040)
                                          ]),
                                          _: 1
                                        }, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }, 8, ["modelValue"])
                  ]),
                  _: 1
                }, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createElementVNode("div", _hoisted_36, [
              _createElementVNode("div", _hoisted_37, [
                _createVNode(_component_v_icon, {
                  color: "info",
                  size: "18",
                  class: "mr-1"
                }, {
                  default: _withCtx(() => _cache[128] || (_cache[128] = [
                    _createTextVNode("mdi-help-circle-outline")
                  ])),
                  _: 1
                }),
                _cache[131] || (_cache[131] = _createTextVNode(" 配置文档参考: ")),
                _createElementVNode("a", _hoisted_38, [
                  _cache[130] || (_cache[130] = _createTextVNode(" GitHub README ")),
                  _createVNode(_component_v_icon, { size: "12" }, {
                    default: _withCtx(() => _cache[129] || (_cache[129] = [
                      _createTextVNode("mdi-open-in-new")
                    ])),
                    _: 1
                  })
                ])
              ]),
              _createElementVNode("div", _hoisted_39, [
                _createVNode(_component_v_btn, {
                  color: "grey-darken-1",
                  variant: "outlined",
                  size: "small",
                  class: "rounded-lg text-none",
                  onClick: resetForm
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { start: "" }, {
                      default: _withCtx(() => _cache[132] || (_cache[132] = [
                        _createTextVNode("mdi-refresh")
                      ])),
                      _: 1
                    }),
                    _cache[133] || (_cache[133] = _createTextVNode(" 重置 "))
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "info",
                  variant: "tonal",
                  size: "small",
                  class: "rounded-lg text-none",
                  loading: testing.value,
                  onClick: testConnection
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { start: "" }, {
                      default: _withCtx(() => _cache[134] || (_cache[134] = [
                        _createTextVNode("mdi-lan-check")
                      ])),
                      _: 1
                    }),
                    _cache[135] || (_cache[135] = _createTextVNode(" 测试连接 "))
                  ]),
                  _: 1
                }, 8, ["loading"]),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  variant: "elevated",
                  size: "small",
                  class: "rounded-lg text-none font-weight-bold px-4",
                  disabled: !isFormValid.value,
                  loading: saving.value,
                  onClick: saveConfig
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { start: "" }, {
                      default: _withCtx(() => _cache[136] || (_cache[136] = [
                        _createTextVNode("mdi-content-save-outline")
                      ])),
                      _: 1
                    }),
                    _cache[137] || (_cache[137] = _createTextVNode(" 保存配置 "))
                  ]),
                  _: 1
                }, 8, ["disabled", "loading"])
              ])
            ]),
            _createVNode(_component_v_snackbar, {
              modelValue: testResult.show,
              "onUpdate:modelValue": _cache[49] || (_cache[49] = ($event) => testResult.show = $event),
              color: testResult.success ? "success" : "error",
              location: "top",
              timeout: "5000",
              class: "test-result-snackbar"
            }, {
              actions: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  variant: "text",
                  icon: "mdi-close",
                  color: "white",
                  size: "small",
                  onClick: _cache[48] || (_cache[48] = ($event) => testResult.show = false)
                })
              ]),
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_40, [
                  _createVNode(_component_v_icon, {
                    size: "24",
                    color: "white"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(testResult.success ? "mdi-check-circle-outline" : "mdi-alert-circle-outline"), 1)
                    ]),
                    _: 1
                  }),
                  _createElementVNode("div", null, [
                    _createElementVNode("div", _hoisted_41, _toDisplayString(testResult.title), 1),
                    _createElementVNode("div", _hoisted_42, _toDisplayString(testResult.message), 1)
                  ])
                ])
              ]),
              _: 1
            }, 8, ["modelValue", "color"])
          ]),
          _: 1
        }),
        _createVNode(_component_v_dialog, {
          modelValue: clashTemplateDialog.value,
          "onUpdate:modelValue": _cache[54] || (_cache[54] = ($event) => clashTemplateDialog.value = $event),
          "max-width": "680"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card, { class: "rounded-xl overflow-hidden" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, { class: "pa-4 bg-surface d-flex align-center justify-space-between" }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_43, [
                      _createVNode(_component_v_icon, { color: "primary" }, {
                        default: _withCtx(() => _cache[138] || (_cache[138] = [
                          _createTextVNode("mdi-file-code-outline")
                        ])),
                        _: 1
                      }),
                      _cache[139] || (_cache[139] = _createElementVNode("span", { class: "font-weight-bold text-h6" }, "Clash 配置模板编辑", -1))
                    ]),
                    _createVNode(_component_v_btn, {
                      icon: "mdi-close",
                      variant: "text",
                      size: "small",
                      onClick: _cache[50] || (_cache[50] = ($event) => clashTemplateDialog.value = false)
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_divider),
                _createVNode(_component_v_card_text, { class: "pa-4" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_select, {
                      modelValue: clashTemplateType.value,
                      "onUpdate:modelValue": _cache[51] || (_cache[51] = ($event) => clashTemplateType.value = $event),
                      items: ["YAML"],
                      label: "配置格式",
                      variant: "outlined",
                      density: "comfortable",
                      class: "mb-3"
                    }, null, 8, ["modelValue"]),
                    _createElementVNode("div", _hoisted_44, [
                      _createVNode(_unref(VAceEditor), {
                        value: clashTemplateContent.value,
                        "onUpdate:value": _cache[52] || (_cache[52] = ($event) => clashTemplateContent.value = $event),
                        lang: "yaml",
                        theme: "monokai",
                        options: editorOptions,
                        placeholder: configPlaceholder.value,
                        style: { "height": "24rem", "width": "100%" }
                      }, null, 8, ["value", "placeholder"])
                    ]),
                    _createVNode(_component_v_alert, {
                      type: "info",
                      variant: "tonal",
                      density: "compact",
                      class: "rounded-lg mb-0"
                    }, {
                      prepend: _withCtx(() => [
                        _createVNode(_component_v_icon, { size: "18" }, {
                          default: _withCtx(() => _cache[140] || (_cache[140] = [
                            _createTextVNode("mdi-information-outline")
                          ])),
                          _: 1
                        })
                      ]),
                      default: _withCtx(() => [
                        _cache[141] || (_cache[141] = _createElementVNode("span", { class: "text-caption" }, "规则与出站代理会自动附加在配置模板之上", -1))
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_divider),
                _createVNode(_component_v_card_actions, { class: "pa-4 bg-surface" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_spacer),
                    _createVNode(_component_v_btn, {
                      color: "grey-darken-1",
                      variant: "text",
                      class: "rounded-lg",
                      onClick: _cache[53] || (_cache[53] = ($event) => clashTemplateDialog.value = false)
                    }, {
                      default: _withCtx(() => _cache[142] || (_cache[142] = [
                        _createTextVNode(" 取消 ")
                      ])),
                      _: 1
                    }),
                    _createVNode(_component_v_btn, {
                      color: "primary",
                      variant: "flat",
                      class: "rounded-lg font-weight-bold",
                      onClick: saveClashTemplate
                    }, {
                      default: _withCtx(() => _cache[143] || (_cache[143] = [
                        _createTextVNode(" 保存模板 ")
                      ])),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue"])
      ]);
    };
  }
});

const ConfigComponent = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-23e5f79c"]]);

export { ConfigComponent as default };
