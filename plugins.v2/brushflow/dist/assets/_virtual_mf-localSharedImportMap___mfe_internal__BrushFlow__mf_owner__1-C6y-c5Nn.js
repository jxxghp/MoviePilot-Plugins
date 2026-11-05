import './index-pSqlufH5.js';
import './index-Cezq_yMy.js';

// A consume-only share has no local module: its entry is the same shape for every key, so one helper builds it instead of a literal per key
    const __mfHostOnly = (name) => async () => {
      throw new Error(`[Module Federation] Shared module '${name}' must be provided by host`);
    };
    // Replaced by the lazy consume-only share plugin with the keys that only a dynamic
    // import() reaches, so init() leaves them to that import; an unreplaced string matches no key.
    const __mfLazyShares = "__MF_LAZY_CONSUME_ONLY_SHARES__";
    const __mfIsLazyShare = (name) => Array.isArray(__mfLazyShares) && __mfLazyShares.includes(name);
    const __mfConsumeOnly = (name, version, scope, materialize, shareConfig) => ({
      name,
      version,
      scope: [scope],
      loaded: false,
      materialize: !__mfIsLazyShare(name),
      lazy: __mfIsLazyShare(name),
      eager: shareConfig.eager,
      from: "BrushFlow",
      canLiveRebind: true,
      get: __mfHostOnly(name),
      shareConfig: { ...shareConfig, import: false },
    });
      const usedShared = {
      
          "vue": __mfConsumeOnly("vue", "3.5.44", "default", true, {singleton: true, requiredVersion: false, strictVersion: false, eager: false,  }),
          "vuetify/styles": __mfConsumeOnly("vuetify/styles", "3.7.3", "default", true, {singleton: true, requiredVersion: false, strictVersion: false, eager: false,  }),
          "vuetify": __mfConsumeOnly("vuetify", "3.7.3", "default", true, {singleton: true, requiredVersion: false, strictVersion: false, eager: false,  })
    };
      const usedRemotes = [
      ];

export { usedRemotes, usedShared };
