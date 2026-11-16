const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/BrushFlowWorkbench-BEWjZIOj.css","assets/Dashboard--DrqsysV.css"])))=>i.map(i=>d[i]);
import { _ as __vitePreload } from './vite-preload-helper-BelkbqnE.js';
import { i as init$1 } from './index-pSqlufH5.js';
import { s as share } from './helpers-_Ccnm3rP.js';
import './index-Cezq_yMy.js';

const cssAssetMap = {};
    const injectedCssHrefs = new Set();
    const exposeLoadPromises = new Map();

    // Shared and remote readiness is handled by explicit Promise barriers below
    // and by remoteEntry's pendingShareLoads barrier. Keep this map scoped to a
    // single expose: unrelated exposes must stay independent and load in parallel.
    function loadExposedModule(exposeKey, loader) {
      let load = exposeLoadPromises.get(exposeKey);
      if (!load) {
        load = Promise.resolve()
          .then(loader)
          .catch((error) => {
            exposeLoadPromises.delete(exposeKey);
            throw error;
          });
        exposeLoadPromises.set(exposeKey, load);
      }
      return load;
    }

    async function injectCssAssets(exposeKey) {
      if (typeof document === "undefined") {
        return;
      }

      // Replaced at build time with expose -> css asset paths.
      const cssAssets = cssAssetMap[exposeKey] || [];

      await Promise.all(
        cssAssets.map((cssAsset) => {
          const href = new URL(cssAsset, import.meta.url).href;

          // Same expose can be resolved multiple times in one page.
          if (injectedCssHrefs.has(href)) {
            return Promise.resolve();
          }
          injectedCssHrefs.add(href);

          // Check for any existing stylesheet with the same href, not just
          // MF-injected ones. This prevents duplicate <link> tags when Vite's
          // own CSS module injection or MF runtime's createLink has already
          // created a <link rel="stylesheet"> for the same URL.
          const existingLink = document.querySelector(
            `link[rel="stylesheet"][href="${href}"]`
          );
          if (existingLink) {
            return Promise.resolve();
          }

          return new Promise((resolve, reject) => {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = href;
            link.onload = () => resolve();
            link.onerror = () => {
              injectedCssHrefs.delete(href);
              link.remove();
              reject(new Error(`[Module Federation] Failed to load CSS asset: ${href}`));
            };
            document.head.appendChild(link);
          });
        })
      );
    }

    const __mfExposesMap = {
    
        "./Page": async () => {
          await injectCssAssets("./Page");
          await Promise.all([]);
          const importModule = await loadExposedModule(
            "./Page",
            () => __vitePreload(() => import('./Page-DMKwnZMl.js'),true?__vite__mapDeps([0]):void 0)
          );
          const dependencyPending = importModule && importModule.__mf_remote_dependency_pending;
          if (dependencyPending && typeof dependencyPending.then === "function") {
            await dependencyPending;
          }
          const exportModule = {};
          Object.assign(exportModule, importModule);
          
          Object.defineProperty(exportModule, "__esModule", {
            value: true,
            enumerable: false
          });
          return exportModule
        }
      ,
        "./Config": async () => {
          await injectCssAssets("./Config");
          await Promise.all([]);
          const importModule = await loadExposedModule(
            "./Config",
            () => __vitePreload(() => import('./Config-BPfgyFXT.js'),true?__vite__mapDeps([0]):void 0)
          );
          const dependencyPending = importModule && importModule.__mf_remote_dependency_pending;
          if (dependencyPending && typeof dependencyPending.then === "function") {
            await dependencyPending;
          }
          const exportModule = {};
          Object.assign(exportModule, importModule);
          
          Object.defineProperty(exportModule, "__esModule", {
            value: true,
            enumerable: false
          });
          return exportModule
        }
      ,
        "./Dashboard": async () => {
          await injectCssAssets("./Dashboard");
          await Promise.all([]);
          const importModule = await loadExposedModule(
            "./Dashboard",
            () => __vitePreload(() => import('./Dashboard-VZGlafLj.js'),true?__vite__mapDeps([1]):void 0)
          );
          const dependencyPending = importModule && importModule.__mf_remote_dependency_pending;
          if (dependencyPending && typeof dependencyPending.then === "function") {
            await dependencyPending;
          }
          const exportModule = {};
          Object.assign(exportModule, importModule);
          
          Object.defineProperty(exportModule, "__esModule", {
            value: true,
            enumerable: false
          });
          return exportModule
        }
      ,
        "./AppPage": async () => {
          await injectCssAssets("./AppPage");
          await Promise.all([]);
          const importModule = await loadExposedModule(
            "./AppPage",
            () => __vitePreload(() => import('./AppPage-C4bLrGg2.js'),true?__vite__mapDeps([0]):void 0)
          );
          const dependencyPending = importModule && importModule.__mf_remote_dependency_pending;
          if (dependencyPending && typeof dependencyPending.then === "function") {
            await dependencyPending;
          }
          const exportModule = {};
          Object.assign(exportModule, importModule);
          
          Object.defineProperty(exportModule, "__esModule", {
            value: true,
            enumerable: false
          });
          return exportModule
        }
      
  };

// Shim Vue HMR runtime for dev-compiled components loaded by a non-Vite host.
  // When a remote is served by a Vite dev server, Vue's SFC compiler injects HMR
  // hooks that reference __VUE_HMR_RUNTIME__. This global only exists on pages
  // served by Vite's client runtime. When a production host loads the remote,
  // the HMR calls would throw. This no-op shim prevents that.
  if (typeof __VUE_HMR_RUNTIME__ === 'undefined') {
    globalThis.__VUE_HMR_RUNTIME__ = { createRecord() {}, rerender() {}, reload() {} };
  }
  
const __mfResolveGlobalKey = "__mf_init__virtual:mf:__mfe_internal__BrushFlow__mf_owner__217245097701611__mf_v__runtimeInit__mf_v__.js__";
let __mfResolveState = globalThis[__mfResolveGlobalKey];
if (!__mfResolveState) {
  let initResolve, initReject;
  const initPromise = new Promise((re, rj) => {
    initResolve = re;
    initReject = rj;
  });
  __mfResolveState = globalThis[__mfResolveGlobalKey] = {
    initPromise,
    initResolve,
    initReject,
  };
  
}
const initResolve = __mfResolveState.initResolve;

  const { initReject } = __mfResolveState;
  // A failed seed must settle initPromise, or every pending share load hangs forever.
  const __mfRejectInit = (err) => {
    initReject(err);
    throw err;
  };
  
const __mfCacheGlobalKey = "__mf_module_cache__";
globalThis[__mfCacheGlobalKey] ||= { share: {}, remote: {} };
globalThis[__mfCacheGlobalKey].share ||= {};
globalThis[__mfCacheGlobalKey].remote ||= {};
const __mfModuleCache = globalThis[__mfCacheGlobalKey];
for (const __mfShareKey of Object.keys(__mfModuleCache.share)) {
  if (__mfShareKey.startsWith("default:")) {
    const __mfLegacyShareKey = __mfShareKey.slice("default:".length);
    if (__mfModuleCache.share[__mfLegacyShareKey] === undefined) {
      __mfModuleCache.share[__mfLegacyShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  } else if (!__mfShareKey.includes(":")) {
    const __mfDefaultShareKey = "default:" + __mfShareKey;
    if (__mfModuleCache.share[__mfDefaultShareKey] === undefined) {
      __mfModuleCache.share[__mfDefaultShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  }
}

  const initTokens = {};
  const shareScopeNames = Array.isArray("default") ? "default" : ["default"];
  const shareScopeName = "default";
  const mfName = "BrushFlow";
  const __mfMaterializedShareBatches = [["vue"],["vuetify/styles"],["vuetify"]];
  let localSharedImportMapPromise;
  let __mfLateBridgeShared;
  async function retrySharedInit(fn) {
    for (let attempt = 0; ; attempt++) {
      try {
        return await fn();
      } catch (e) {
        throw e;
      }
    }
  }
  
  const __mfOriginalProviderKey = Symbol("mf.originalSharedProvider");
          const __mfResolveShareHook = { emit: (params) => params };
          const __mfGetShareScopeNames = (share) =>
            Array.isArray(share.scope) ? share.scope : [share.scope || "default"];
          const __mfCreateProviderSelectionVersions = (versions, strategy) => {
            if (strategy !== "version-first") return versions;
            const selectionVersions = {};
            for (const [version, provider] of Object.entries(versions)) {
              selectionVersions[version] = Object.assign({}, provider, {
                [__mfOriginalProviderKey]: provider
              });
            }
            return selectionVersions;
          };
          const __mfFindSharedProviderEntry = (versions, provider) => {
            if (!provider) return undefined;
            const entries = Object.entries(versions || {});
            const registeredEntry = entries.find(([, candidate]) => candidate === provider);
            if (registeredEntry) {
              return { version: registeredEntry[0], provider, registered: true };
            }
            if (typeof provider.version === "string" && provider.version) {
              return { version: provider.version, provider, registered: false };
            }
            const provenanceEntries = entries.filter(([, candidate]) =>
              candidate === provider || Boolean(provider.from && candidate?.from === provider.from)
            );
            if (provenanceEntries.length !== 1) return undefined;
            return { version: provenanceEntries[0][0], provider, registered: false };
          };
          const __mfSelectSharedProvider = (
            versions,
            pkg,
            share$1,
            strategy
          ) => {
            if (!versions || !share$1) return undefined;
            // import:false stubs provide nothing, so they are never a selectable
            // provider and must not be satisfy-checked. Skip the runtime entirely
            // when nothing remains: it treats an empty map as version "0" and
            // warns that it fails even a "*" requirement.
            const candidates = Object.fromEntries(
              Object.entries(versions).filter(([, provider]) => provider?.shareConfig?.import !== false)
            );
            if (Object.keys(candidates).length === 0) return undefined;
            const scopes = __mfGetShareScopeNames(share$1);
            const selectionVersions = __mfCreateProviderSelectionVersions(candidates, strategy);
            const shareScopeMap = {};
            for (const scope of scopes) {
              shareScopeMap[scope || "default"] = { [pkg]: selectionVersions };
            }
            const selected = share.getRegisteredShare(
              shareScopeMap,
              pkg,
              { ...share$1, scope: scopes, strategy },
              __mfResolveShareHook
            )?.shared;
            return selected?.[__mfOriginalProviderKey] || selected;
          };
  const __mfSelectExternalSharedProvider = (
            versions,
            pkg,
            localShare,
            strategy
          ) => {
            const isLocalProvider = (provider) => __mfMatchesSharedProvider(provider, localShare);
            const candidates = Object.fromEntries(
              Object.entries(versions || {}).filter(([, provider]) =>
                !isLocalProvider(provider) && provider?.shareConfig?.import !== false
              )
            );
            if (localShare?.version && localShare.shareConfig?.import !== false) {
              const sameVersionProvider = candidates[localShare.version];
              // Runtime registration keeps an existing same-version record,
              // even when it has only a getter and is not loaded yet. Model
              // that retained provider here so pre-init seeding cannot choose
              // the local module while loadShare() later chooses the parent.
              if (!sameVersionProvider) {
                candidates[localShare.version] = localShare;
              }
            }
            const provider = __mfSelectSharedProvider(
              candidates,
              pkg,
              localShare,
              strategy
            );
            return isLocalProvider(provider) ? undefined : provider;
          };
          const __mfMatchesSharedProvider = (provider, expected) => provider === expected || Boolean(
            expected?.from && provider?.from === expected.from
          );
          const __mfGetScopeRootProvider = (
            instances,
            scopeRoot,
            shared,
            scopeName,
            pkg,
            version,
            provider,
            passedProvider,
            strategy
          ) => {
            if (!passedProvider) return undefined;
            const scopeRootProviders = scopeRoot?.options?.shared?.[pkg];
            const configuredScopeRootProvider = Array.isArray(scopeRootProviders)
              ? scopeRootProviders.find((candidate) => candidate?.version === version)
              : undefined;
            const registeredScopeRootProvider = passedProvider?.from === scopeRoot?.options?.name
              ? passedProvider
              : undefined;
            const scopeRootProvider = registeredScopeRootProvider || (
              __mfMatchesSharedProvider(configuredScopeRootProvider, passedProvider)
                ? configuredScopeRootProvider
                // A plain Webpack/Rspack host has no enhanced-runtime instance.
                // Its pre-init snapshot is still authoritative when this remote's
                // registration rewrites the same-version provider in-place.
                : scopeRoot ? undefined : passedProvider
            );
            if (!scopeRootProvider) return undefined;
            const selectedFromLaterInstance = instances.some((instance) =>
              instance !== scopeRoot &&
              instance?.options?.name === provider?.from &&
              instance?.shareScopeMap?.[scopeName] === shared
            );
            return selectedFromLaterInstance ? scopeRootProvider : undefined;
          };
          const __mfResolveExternalSharedProvider = (
            instances,
            scopeRoot,
            shared,
            scopeName,
            pkg,
            providerEntry,
            selectedExternalProvider,
            passedProvider,
            strategy
          ) => {
            const scopeRootProvider = providerEntry.registered ? __mfGetScopeRootProvider(
              instances,
              scopeRoot,
              shared,
              scopeName,
              pkg,
              providerEntry.version,
              providerEntry.provider,
              passedProvider) : undefined;
            const provider = scopeRootProvider || selectedExternalProvider;
            if (!provider) return undefined;
            if (
              providerEntry.registered &&
              !__mfMatchesSharedProvider(provider, passedProvider)
            ) return undefined;
            return { provider, scopeRootProvider };
          };

  async function getLocalSharedImportMap() {
    if (!localSharedImportMapPromise) {
      localSharedImportMapPromise = retrySharedInit(() => __vitePreload(() => import('./_virtual_mf-localSharedImportMap___mfe_internal__BrushFlow__mf_owner__1-C6y-c5Nn.js'),true?[]:void 0))
        .catch((e) => { localSharedImportMapPromise = undefined; throw e; });
    }
    return localSharedImportMapPromise
  }

  async function getExposesMap() {
    return __mfExposesMap
  }

  // Hosts that call get() without awaiting init() must still see the shares that
  // init binds asynchronously: get() waits until no init() call is in flight.
  let __mfInitsInFlight = 0;
  let __mfInitsSettled = Promise.resolve();
  let __mfSettleInits = () => {};
  async function init(shared = {}, initScope = [], remoteEntryInitOptions = {}) {
    if (__mfInitsInFlight++ === 0) __mfInitsSettled = new Promise((resolve) => (__mfSettleInits = resolve));
    try {
    const __mfGetSharedCacheDescriptor = function createSharedCacheDescriptor(pkg, singleton, version, scope) {
	const scopeName = (Array.isArray(scope) ? scope[0] : scope) || "default";
	const id = singleton || !version ? pkg : pkg + "@" + version;
	const descriptor = { canonical: scopeName + ":" + id };
	if (scopeName === "default") descriptor.aliases = [id];
	return descriptor;
};
          const __mfReadSharedCache = (cache, descriptor) => {
            const value = cache[descriptor.canonical];
            if (value !== undefined) return value;
            const aliases = descriptor.aliases || [];
            for (const alias of aliases) {
              if (!Object.prototype.hasOwnProperty.call(cache, alias)) continue;
              const aliasValue = cache[alias];
              if (aliasValue !== undefined) {
                cache[descriptor.canonical] = aliasValue;
                return aliasValue;
              }
            }
            return undefined;
          };
          const __mfSharedCacheListenersKey = Symbol.for("module-federation.shared-cache-listeners");
          const __mfGetSharedCacheListeners = (cache) => {
            let listeners = cache[__mfSharedCacheListenersKey];
            if (listeners === undefined) {
              listeners = Object.create(null);
              Object.defineProperty(cache, __mfSharedCacheListenersKey, {
                value: listeners,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return listeners;
          };
          const __mfSubscribeSharedCache = (cache, descriptor, listener) => {
            const listeners = __mfGetSharedCacheListeners(cache);
            (listeners[descriptor.canonical] ||= new Set()).add(listener);
          };
          const __mfSharedCacheOwnersKey = Symbol.for("module-federation.shared-cache-owners");
          const __mfGetSharedCacheOwners = (cache) => {
            let owners = cache[__mfSharedCacheOwnersKey];
            if (owners === undefined) {
              owners = Object.create(null);
              Object.defineProperty(cache, __mfSharedCacheOwnersKey, {
                value: owners,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return owners;
          };
          const __mfReadSharedCacheOwner = (cache, descriptor) =>
            cache[__mfSharedCacheOwnersKey]?.[descriptor.canonical];
          const __mfGetSharedModuleIdentity = (value) => {
            const candidates = [value, value?.default];
            for (const candidate of candidates) {
              if (!candidate || typeof candidate !== "object") continue;
              for (const key of ["__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE","__TEST_INTERNALS","__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED"]) {
                const internals = candidate[key];
                if (internals && typeof internals === "object") {
                  return { internals };
                }
              }
              if (typeof candidate.useState === "function") return { hook: candidate.useState };
            }
            return undefined;
          };
          const __mfIsSameSharedModule = (current, next) => {
            if (current === next) return true;
            const currentIdentity = __mfGetSharedModuleIdentity(current);
            const nextIdentity = __mfGetSharedModuleIdentity(next);
            if (!currentIdentity || !nextIdentity) return false;
            const currentInternals = currentIdentity.internals;
            const nextInternals = nextIdentity.internals;
            // Internals identity is authoritative when either side exposes it.
            // Never treat absent fields as equal (undefined === undefined).
            if (currentInternals !== undefined || nextInternals !== undefined) {
              return (
                currentInternals !== undefined &&
                currentInternals === nextInternals
              );
            }
            // Hook identity is only a fallback when neither side exposes internals.
            return (
              typeof currentIdentity.hook === "function" &&
              currentIdentity.hook === nextIdentity.hook
            );
          };
          const __mfWriteSharedCache = (cache, descriptor, value, owner) => {
            // Rewriting the same instance is a no-op on purpose: the first
            // provider keeps ownership and subscribers are not re-notified, so
            // an already-bound renderer never sees its React rebound.
            const current = __mfReadSharedCache(cache, descriptor);
            if (current !== undefined && __mfIsSameSharedModule(current, value)) return value;
            cache[descriptor.canonical] = value;
            const aliases = descriptor.aliases || [];
            for (const alias of aliases) {
              Object.defineProperty(cache, alias, {
                value,
                enumerable: true,
                configurable: true,
                writable: true
              });
            }
            const owners = cache[__mfSharedCacheOwnersKey];
            if (owner === undefined) {
              if (owners) delete owners[descriptor.canonical];
            } else {
              __mfGetSharedCacheOwners(cache)[descriptor.canonical] = owner;
            }
            const listeners = cache[__mfSharedCacheListenersKey]?.[descriptor.canonical];
            if (listeners) {
              for (const listener of listeners) listener(value);
            }
            return value;
          };
          const __mfTreeShakingSharedCacheKey = Symbol.for("module-federation.tree-shaking-shared-cache");
          const __mfGetTreeShakingSharedCache = (cache) => {
            let metadata = cache[__mfTreeShakingSharedCacheKey];
            if (metadata === undefined) {
              metadata = Object.create(null);
              Object.defineProperty(cache, __mfTreeShakingSharedCacheKey, {
                value: metadata,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return metadata;
          };
          const __mfReadTreeShakingSharedCache = (cache, descriptor, requiredExports) => {
            const fullModule = __mfReadSharedCache(cache, descriptor);
            if (fullModule !== undefined) return fullModule;
            if (!Array.isArray(requiredExports)) return undefined;
            const metadata = cache[__mfTreeShakingSharedCacheKey];
            const entries = metadata?.[descriptor.canonical] || [];
            let compatibleEntry;
            for (const entry of entries) {
              if (!requiredExports.every((name) => entry.providedExports.includes(name))) continue;
              if (!compatibleEntry || entry.providedExports.length < compatibleEntry.providedExports.length) {
                compatibleEntry = entry;
              }
            }
            return compatibleEntry?.value;
          };
          const __mfWriteTreeShakingSharedCache = (cache, descriptor, providedExports, value) => {
            if (!Array.isArray(providedExports)) return value;
            const normalizedExports = [...new Set(providedExports)].sort();
            const metadata = __mfGetTreeShakingSharedCache(cache);
            const entries = (metadata[descriptor.canonical] ||= []);
            const existing = entries.find((entry) =>
              entry.providedExports.length === normalizedExports.length &&
              entry.providedExports.every((name, index) => name === normalizedExports[index])
            );
            if (existing) existing.value = value;
            else entries.push({ providedExports: normalizedExports, value });
            return value;
          };
          const __mfTreeShakingSelectionCacheKey = Symbol.for("module-federation.tree-shaking-shared-selection-cache");
          const __mfGetTreeShakingSelectionCache = (cache) => {
            let selections = cache[__mfTreeShakingSelectionCacheKey];
            if (selections === undefined) {
              selections = Object.create(null);
              Object.defineProperty(cache, __mfTreeShakingSelectionCacheKey, {
                value: selections,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return selections;
          };
          const __mfReadTreeShakingSharedSelection = (cache, descriptor, consumer) => {
            const fullModule = __mfReadSharedCache(cache, descriptor);
            if (fullModule !== undefined) return fullModule;
            return cache[__mfTreeShakingSelectionCacheKey]?.[descriptor.canonical]?.[consumer];
          };
          const __mfWriteTreeShakingSharedSelection = (cache, descriptor, consumer, value) => {
            const selections = __mfGetTreeShakingSelectionCache(cache);
            const byConsumer = (selections[descriptor.canonical] ||= Object.create(null));
            byConsumer[consumer] = value;
            return value;
          };
    const getShareScope = (scopeName) => remoteEntryInitOptions.shareScopeMap?.[scopeName] ?? (false ? (shared?.[scopeName] || {}) : shared);
    const getShareScopeNames = (share) => {
      const configuredScopes = Array.isArray(share?.scope) ? share.scope : [share?.scope || shareScopeName];
      if (!false) return configuredScopes;
      return [...new Set([...configuredScopes, ...shareScopeNames])];
    };
    const getShareScopeName = (pkg, share) => {
      for (const scopeName of getShareScopeNames(share)) {
        if (getShareScope(scopeName)?.[pkg]) return scopeName;
      }
      return shareScopeName;
    };
    const getShareVersions = (pkg, share) => {
      for (const scopeName of getShareScopeNames(share)) {
        const versions = getShareScope(scopeName)?.[pkg];
        if (versions) return versions;
      }
      return getShareScope(shareScopeName)?.[pkg];
    };
    const federationInstances = globalThis.__FEDERATION__?.__INSTANCES__ || [];
    const initRootName = initScope.find((token) => token?.from)?.from;
    const scopeRoot = federationInstances.find((instance) =>
      instance?.options?.name === initRootName &&
      instance?.shareScopeMap?.['default'] === shared
    ) || federationInstances.find((instance) =>
      instance?.options?.name !== mfName &&
      instance?.shareScopeMap?.['default'] === shared
    );
    const __mfRuntimeShareScopes = Object.create(null);
    const __mfCloneShareScope = (hostScope) => {
      const runtimeScope = Object.create(null);
      for (const [pkg, versions] of Object.entries(hostScope || {})) {
        runtimeScope[pkg] = Object.assign(Object.create(null), versions);
      }
      return runtimeScope;
    };
    // runtimeInit() lets runtime plugins register providers (public
    // registerShared) before initShareScopeMap() replaces the runtime's own
    // scope map. Carry those registrations over; the runtime's own copies of
    // usedShared keep registering lazily through loadShare().
    const __mfKeepRegisteredShares = (scopeName, scope) => {
      for (const [pkg, versions] of Object.entries(initRes.shareScopeMap?.[scopeName] || {})) {
        for (const [version, provider] of Object.entries(versions || {})) {
          if (!provider || provider.get === usedShared[pkg]?.get) continue;
          const target = scope[pkg] ||= {};
          if (target[version] === undefined) target[version] = provider;
        }
      }
    };
    const __mfGetRuntimeShareScope = (scopeName, hostScope) => {
      __mfKeepRegisteredShares(scopeName, hostScope);
      const isWebpackScope = !scopeRoot && Object.values(hostScope || {}).some((versions) =>
        Object.values(versions || {}).some(isWebpackProvider)
      );
      const runtimeScope = isWebpackScope ? __mfCloneShareScope(hostScope) : hostScope;
      __mfRuntimeShareScopes[scopeName] = {
        host: hostScope,
        runtime: runtimeScope,
        isWebpackScope
      };
      return runtimeScope;
    };
    const __mfRestoreForeignSharedProviders = () => {
      const webpackScopes = Object.values(__mfRuntimeShareScopes).filter(
        ({ isWebpackScope }) => isWebpackScope
      );
      if (webpackScopes.length === 0) return;
      for (const { host, runtime } of webpackScopes) {
        for (const [pkg, versions] of Object.entries(host || {})) {
          const runtimeVersions = runtime[pkg] ||= Object.create(null);
          for (const [version, provider] of Object.entries(versions || {})) {
            runtimeVersions[version] = provider;
          }
        }
      }
    };
    const initialShared = Object.create(null);
    for (const [pkg, versions] of Object.entries(shared)) {
      const initialVersions = initialShared[pkg] = Object.create(null);
      for (const [version, provider] of Object.entries(versions)) {
        // Runtime registration mutates provider records in-place, notably their origin.
        // Preserve the parent-visible provider and its original provenance.
        initialVersions[version] = Object.assign({}, provider);
      }
    }
    const {usedShared, usedRemotes} = await getLocalSharedImportMap();
    function isWebpackProvider(provider) {
      if (typeof provider?.get !== 'function') return false;
      const source = Function.prototype.toString.call(provider.get);
      // Production minification renames __webpack_require__, but preserves
      // Webpack's lazy chunk-loading .e(...).then(...) shape.
      return (
        source.includes('__webpack_require__') ||
        /\.\s*e\s*\([^)]*\)\s*\.then\s*\(/.test(source)
      );
    }
    const __mfUsesWebpackShareScope = Object.values(initialShared).some((versions) =>
      Object.values(versions || {}).some(isWebpackProvider)
    );
    const __mfGetSharePackageName = (pkg) => {
      const parts = pkg.split('/');
      return pkg.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
    };
    const __mfGetExternalSharedProvider = (pkg, share, versionMap, includePackage) => {
      if (typeof __mfSelectExternalSharedProvider !== 'function') return undefined;
      const packageName = __mfGetSharePackageName(pkg);
      const candidates = !includePackage || packageName === pkg
        ? [[pkg, share]]
        : [[pkg, share], [packageName, usedShared[packageName]]];
      for (const [candidatePkg, candidateShare] of candidates) {
        if (!candidateShare) continue;
        const candidateVersionMap = versionMap
          ? (candidatePkg === pkg ? versionMap : initialShared[candidatePkg])
          : (initialShared[candidatePkg] ?? shared[candidatePkg]);
        const provider = __mfSelectExternalSharedProvider(
          candidateVersionMap,
          candidatePkg,
          candidateShare,
          'version-first'
        );
        if (provider) return provider;
      }
      return undefined;
    };
    const __mfGetPendingExternalSharedProvider = (pkg, share, versionMap) => {
      const provider = __mfGetExternalSharedProvider(pkg, share, versionMap, true);
      return provider && isWebpackProvider(provider) && !provider.lib && !provider.loaded
        ? provider
        : undefined;
    };
    // handling circular init calls before an external provider can re-enter this container
    var initToken = initTokens[shareScopeName];
    if (!initToken)
      initToken = initTokens[shareScopeName] = { from: mfName };
    if (initScope.indexOf(initToken) >= 0) return;
    initScope.push(initToken);
    const __mfNormalizeRuntimeShare = (mod) => {
            let current = mod;
            for (let i = 0; i < 5; i++) {
              const defaultExport = current?.default;
              if (!defaultExport || typeof defaultExport !== "object" || Object.keys(defaultExport).length === 0) break;
              // Only unwrap plain CJS namespaces; spreading a class instance would drop its prototype.
              const proto = Object.getPrototypeOf(defaultExport);
              if (proto !== null && proto !== Object.prototype) break;
              const namedValues = Object.keys(current).filter((key) => key !== "default").map((key) => current[key]);
              if (namedValues.length > 0 && namedValues.some((value) => value !== undefined)) break;
              current = defaultExport;
            }
            return current;
          };
    const __browserPlugins = [];
    const __ssrPlugins = typeof globalThis.window === 'undefined'
      ? await Promise.all([])
      : [];
    const __mfRuntimeShareLoadIdKey = "__mf_vite_runtime_share_load_id__";
    let __mfRuntimeShareLoadId = 0;
    const __mfRuntimeShareSelections = new Map();
    const __mfRuntimeShareLifecycles = new Map();
    const initRes = init$1({
      name: mfName,
      remotes: usedRemotes,
      shared: usedShared,
      plugins: [__mfSharePinLifecyclePlugin(), __mfRealNameSnapshotPlugin(),  ...__browserPlugins, ...__ssrPlugins],
      shareStrategy: 'version-first'
    });
    initRes.initShareScopeMap(
      'default',
      __mfGetRuntimeShareScope('default', shared)
    );
    function __mfSharePinLifecyclePlugin() {
      return {
        name: "vite-share-pin-lifecycle-plugin",
        resolveShare(args) {
          const loadId = args.shareInfo?.[__mfRuntimeShareLoadIdKey];
          const lifecycle = loadId === undefined
            ? undefined
            : __mfRuntimeShareLifecycles.get(loadId);
          if (!lifecycle) return args;
          const defaultResolver = args.resolver;
          args.resolver = (...resolverArgs) => {
            lifecycle.pinned.reapply();
            return defaultResolver(...resolverArgs);
          };
          lifecycle.pinned.reveal();
          return args;
        }
      };
    }
    function __mfRealNameSnapshotPlugin() {
      return {
        name: "vite-real-name-snapshot-plugin",
        afterLoadSnapshot(args) {
          // Remotes are registered under an owner-scoped runtime name, so the
          // global snapshot only ever holds that name. Containers built by other
          // bundlers ask for the same remote by its real container name, miss, and
          // fall back to that container's own entry, whose remoteEntry is empty
          // (RUNTIME-011). Mirroring the resolved snapshot under the real name
          // keeps the primary lookup off that fallback.
          const snapshot = args && args.remoteSnapshot;
          const globalName = snapshot && snapshot.globalName;
          const version = snapshot && snapshot.version;
          if (!globalName || !version || !snapshot.remoteEntry) return args;
          const moduleInfo = globalThis.__FEDERATION__ && globalThis.__FEDERATION__.moduleInfo;
          const realNameKey = globalName + ":" + version;
          // Stores the same object, not a copy, so a later mutation (e.g. runtime-core
          // normalizing fields) stays consistent across both keys. Never overwrites an
          // existing entry: a different owner may have already resolved this real name
          // to its own snapshot, and this mirror must not shadow that one.
          if (moduleInfo && !moduleInfo[realNameKey]) {
            moduleInfo[realNameKey] = snapshot;
          }
          return args;
        }
      };
    }
    const runtimeResolveShareHook = initRes.sharedHandler.hooks.lifecycle.resolveShare;
    // Registering this container's shares lets its consume-only stub displace the parent's
    // unloaded same-version provider whenever this container's name sorts after the parent's
    // (the Runtime keeps the higher name). Nothing can be loaded from a stub, so put the
    // provider back; a share bridged later, e.g. from a lazy import(), still finds it.
    if (!initRes.__mfKeepAdoptedProviders) {
      initRes.__mfKeepAdoptedProviders = true;
      initRes.sharedHandler?.hooks?.lifecycle?.afterRegisterShare?.on?.((args) => {
        const { shared, previousShared, registeredShared } = args || {};
        const versions = initRes.shareScopeMap?.[args.scope]?.[args.pkgName];
        if (!shared || !versions) return;
        // The reverse: a stub already in the slot (e.g. a loaded-first parent's) keeps a provider
        // out, and a webpack consumer reading the scope then falls back to its own copy.
        if (shared.shareConfig?.import !== false) {
          if (
            registeredShared !== shared &&
            registeredShared?.shareConfig?.import === false &&
            !registeredShared.loaded &&
            versions[shared.version] === registeredShared
          ) versions[shared.version] = shared;
          return;
        }
        if (
          registeredShared !== shared ||
          !previousShared ||
          previousShared.shareConfig?.import === false
        ) return;
        if (versions[shared.version] === shared) versions[shared.version] = previousShared;
      });
    }
    const __mfRuntimeProviderOrigins = new WeakMap();
    runtimeResolveShareHook.on((args) => {
      const loadId = args.shareInfo?.[__mfRuntimeShareLoadIdKey];
      const resolver = args.resolver;
      if (typeof resolver !== "function") return args;
      const instrumentedResolver = (...resolverArgs) => {
        let resolved = resolver(...resolverArgs);
        // A consume-only stub can never be loaded. The Runtime still settles on one when
        // it carries the highest version, e.g. a parent that registers its provider under
        // "0.0.0"; hand back the provider this container selects for itself instead.
        if (
          resolved?.shared?.shareConfig?.import === false &&
          typeof __mfSelectSharedProvider === "function" &&
          usedShared[args.pkgName]
        ) {
          const provider = __mfSelectSharedProvider(
            args.shareScopeMap?.[args.scope]?.[args.pkgName],
            args.pkgName,
            usedShared[args.pkgName],
            'version-first'
          );
          if (provider && provider.shareConfig?.import !== false) {
            resolved = { shared: provider, useTreesShaking: resolved.useTreesShaking };
          }
        }
        const selectedProvider = resolved?.shared;
        if (
          selectedProvider &&
          (typeof selectedProvider === "object" || typeof selectedProvider === "function") &&
          !__mfRuntimeProviderOrigins.has(selectedProvider)
        ) {
          __mfRuntimeProviderOrigins.set(selectedProvider, { from: selectedProvider.from });
        }
        if (loadId !== undefined && selectedProvider) {
          __mfRuntimeShareSelections.set(loadId, selectedProvider);
        }
        return resolved;
      };
      args.resolver = instrumentedResolver;
      return args;
    });
    const __mfPinSharedProvider = (versionMap, version, currentProvider, provider) => {
      if (!versionMap || versionMap[version] !== currentProvider) return undefined;
      const pinnedProvider = Object.assign({}, provider, {
        version: provider.version ?? version,
        scope: provider.scope ?? currentProvider?.scope ?? ["default"],
        strategy: 'loaded-first'
      });
      const providerFrom = provider.from;
      versionMap[version] = pinnedProvider;
      const isCurrentProviderActive = () => currentProvider === undefined
        ? versionMap[version] === undefined
        : versionMap[version] === currentProvider;
      return {
        provider: pinnedProvider,
        reveal() {
          if (versionMap[version] !== pinnedProvider) return false;
          if (currentProvider === undefined) delete versionMap[version];
          else versionMap[version] = currentProvider;
          return true;
        },
        reapply() {
          if (!isCurrentProviderActive()) return false;
          versionMap[version] = pinnedProvider;
          return true;
        },
        release(loaded, selected = true) {
          provider.from = providerFrom;
          if (versionMap[version] !== pinnedProvider) {
            return !selected && isCurrentProviderActive();
          }
          if (!selected) {
            if (currentProvider === undefined) delete versionMap[version];
            else versionMap[version] = currentProvider;
            return true;
          }
          if (!loaded) {
            if (currentProvider === undefined) delete versionMap[version];
            else versionMap[version] = currentProvider;
            return false;
          }
          pinnedProvider.from = providerFrom;
          if (loaded && pinnedProvider.lib) pinnedProvider.loaded = true;
          if (provider.strategy === undefined) delete pinnedProvider.strategy;
          else pinnedProvider.strategy = provider.strategy;
          return true;
        }
      };
    };
    const __mfSnapshotSharedProviders = (versionMap) => (
      Object.entries(versionMap || {}).map(([version, provider]) => ({
        provider,
        version,
        from: provider.from,
        registered: true
      }))
    );
    const __mfMatchLoadedSharedProvider = (providerSelections, factory) => {
      if (factory === undefined) return undefined;
      let match;
      for (const selection of providerSelections) {
        const provider = selection.provider;
        const directProvider = provider.treeShaking || provider;
        if (
          selection.loadedFactory !== factory &&
          provider.lib !== factory &&
          directProvider.lib !== factory
        ) continue;
        if (match) return undefined;
        match = selection;
      }
      return match;
    };
    const __mfLoadRuntimeShare = async (pkg, shareConfig, pinned) => {
      const loadId = ++__mfRuntimeShareLoadId;
      __mfRuntimeShareLifecycles.set(loadId, {
        pinned
      });
      try {
        const factory = await initRes.loadShare(pkg, {
          customShareInfo: {
            shareConfig,
            [__mfRuntimeShareLoadIdKey]: loadId
          }
        });
        return {
          factory: factory === false ? undefined : factory,
          selectedProvider: __mfRuntimeShareSelections.get(loadId)
        };
      } finally {
        __mfRuntimeShareSelections.delete(loadId);
        __mfRuntimeShareLifecycles.delete(loadId);
      }
    };
    const __mfLoadPinnedRuntimeShare = async (
      pkg,
      shareConfig,
      versionMap,
      version,
      currentProvider,
      provider,
      providerRegistered = true
    ) => {
      const providerFrom = provider.from;
      const pinned = __mfPinSharedProvider(
        versionMap,
        version,
        currentProvider,
        provider
      );
      if (!pinned) return undefined;
      let runtimeLoad;
      try {
        runtimeLoad = await __mfLoadRuntimeShare(pkg, shareConfig, pinned);
      } catch (error) {
        pinned.release(false);
        throw error;
      }
      const factory = runtimeLoad?.factory;
      if (factory === undefined) {
        pinned.release(false);
        return undefined;
      }
      const providerSelections = __mfSnapshotSharedProviders(versionMap);
      const directPinnedProvider = pinned.provider.treeShaking || pinned.provider;
      const pinnedMatchesFactory =
        pinned.provider.lib === factory || directPinnedProvider.lib === factory;
      if (!providerRegistered && pinnedMatchesFactory) {
        const pinnedSelectionIndex = providerSelections.findIndex(
          (selection) => selection.provider === pinned.provider
        );
        if (pinnedSelectionIndex !== -1) providerSelections.splice(pinnedSelectionIndex, 1);
      }
      if (!providerRegistered && !providerSelections.some((selection) => selection.provider === provider)) {
        providerSelections.push({
          provider,
          version,
          from: providerFrom,
          registered: false,
          loadedFactory: pinnedMatchesFactory ? factory : undefined
        });
      }
      const runtimeSelectedProvider =
        !providerRegistered &&
        runtimeLoad.selectedProvider === pinned.provider &&
        pinnedMatchesFactory
          ? provider
          : runtimeLoad.selectedProvider;
      if (
        runtimeSelectedProvider &&
        !providerSelections.some((selection) => selection.provider === runtimeSelectedProvider)
      ) {
        const runtimeProviderOrigin = __mfRuntimeProviderOrigins.get(runtimeSelectedProvider);
        const selectedVersion = typeof runtimeSelectedProvider.version === "string" && runtimeSelectedProvider.version
          ? runtimeSelectedProvider.version
          : version;
        providerSelections.push({
          provider: runtimeSelectedProvider,
          version: selectedVersion,
          from: runtimeProviderOrigin ? runtimeProviderOrigin.from : runtimeSelectedProvider.from,
          registered: versionMap?.[selectedVersion] === runtimeSelectedProvider,
          loadedFactory: factory
        });
      }
      const selection = providerSelections.find(
        (candidate) => candidate.provider === runtimeSelectedProvider
      ) ?? __mfMatchLoadedSharedProvider(providerSelections, factory);
      const providerStayedActive = pinned.release(
        true,
        selection?.provider === pinned.provider
      );
      if (!providerStayedActive || !selection) return undefined;
      const runtimeProviderOrigin = __mfRuntimeProviderOrigins.get(selection.provider);
      selection.from = selection.provider === provider
        ? providerFrom
        : runtimeProviderOrigin
          ? runtimeProviderOrigin.from
          : selection.provider.from;
      if (runtimeProviderOrigin) selection.provider.from = runtimeProviderOrigin.from;
      const mod = typeof factory === "function" ? factory() : factory;
      const resolved = await Promise.resolve(mod);
      if (selection.registered && versionMap?.[selection.version] !== selection.provider) return undefined;
      return { provider: selection.provider, selection, resolved };
    };
    const bridgedProviders = new Set();
    const bridgeSelections = new Map();
    const __mfBridgeMaterializedProvider = async (pkg, usedShare, versionMap) => {
      const singleton = Boolean(usedShare.shareConfig?.singleton);
      if (singleton && 'version-first' !== 'loaded-first') return;
      if (usedShare.canLiveRebind === false) return;
      try {
        const provider = __mfSelectExternalSharedProvider(
          versionMap,
          pkg,
          usedShare,
          'version-first'
        );
        const providerEntry = __mfFindSharedProviderEntry(versionMap, provider);
        if (!providerEntry) return;
        if (usedShare.shareConfig?.import === false && __mfMatchesSharedProvider(provider, usedShare)) return;
        // Another container's consume-only stub has nothing to bridge to: its get() throws by construction.
        if (provider?.shareConfig?.import === false) return;
        const { version } = providerEntry;
        if (!singleton && version !== usedShare.version) return;
        if (
          !provider.lib &&
          !provider.loading &&
          !(provider.loaded && typeof provider.get === 'function')
        ) return;
        const usedCacheDescriptor = __mfGetSharedCacheDescriptor(
          pkg,
          singleton,
          usedShare.version,
          usedShare.scope
        );
        if (__mfReadSharedCache(__mfModuleCache.share, usedCacheDescriptor) !== undefined) return;
        const liveVersionMap = shared[pkg];
        const liveProvider = liveVersionMap?.[version];
        if (providerEntry.registered && !__mfMatchesSharedProvider(liveProvider, provider)) return;
        let loadedShare;
        // Runtime loadShare() implicitly initializes version-first remotes without
          // this container's outer initScope. Materialized providers are already active,
          // so resolve them directly and keep remote initialization on the guarded path.
          let directFactory = provider.lib;
          if (!directFactory && isWebpackProvider(provider)) return;
          if (!directFactory && provider.loading) directFactory = await provider.loading;
          if (!directFactory && provider.loaded && typeof provider.get === 'function') {
            directFactory = await provider.get();
          }
          if (!directFactory) return;
          const directModule = typeof directFactory === "function" ? directFactory() : directFactory;
          const directResolved = await Promise.resolve(directModule);
          const directProvider = providerEntry.registered ? liveProvider : provider;
          loadedShare = {
            provider: directProvider,
            selection: {
              provider: directProvider,
              version,
              from: provider.from,
              registered: providerEntry.registered
            },
            resolved: directResolved
          };
        const actualProvider = loadedShare?.provider;
        const actualSelection = loadedShare?.selection;
        if (!actualSelection) return;
        const resolved = loadedShare?.resolved;
        if (resolved === undefined) return;
        if (__mfReadSharedCache(__mfModuleCache.share, usedCacheDescriptor) !== undefined) return;
        if (
          actualSelection.registered &&
          liveVersionMap?.[actualSelection.version] !== actualProvider
        ) return;
        __mfWriteSharedCache(
          __mfModuleCache.share,
          usedCacheDescriptor,
          __mfNormalizeRuntimeShare(resolved),
          actualSelection.from
        );
        bridgedProviders.add(actualProvider);
      } catch (e) {
        console.error('[Module Federation] Failed to bridge materialized shared module "' + pkg + '"', e);
      }
    };
    const __mfBridgeExternalSharedProvider = async (
      pkg,
      usedShare,
      versionMap,
      passedVersionMap,
      expectedSelection
    ) => {
      try {
        const usedCacheDescriptor = __mfGetSharedCacheDescriptor(pkg, usedShare.shareConfig?.singleton, usedShare.version, usedShare.scope);
        const cachedShare = __mfReadSharedCache(__mfModuleCache.share, usedCacheDescriptor);
        const cachedShareOwner = __mfReadSharedCacheOwner(__mfModuleCache.share, usedCacheDescriptor);
        const selectedExternalProvider = __mfSelectExternalSharedProvider(
          versionMap,
          pkg,
          usedShare,
          'version-first'
        );
        const selectedRuntimeProvider = selectedExternalProvider ||
          __mfSelectSharedProvider(versionMap, pkg, usedShare, 'version-first') ||
          usedShare;
        const providerEntry = __mfFindSharedProviderEntry(versionMap, selectedRuntimeProvider);
        if (!providerEntry) return;
        const selectedLocalProvider = __mfMatchesSharedProvider(selectedRuntimeProvider, usedShare);
        const { version } = providerEntry;
        if (!usedShare.shareConfig?.singleton && version !== usedShare.version) return;
        const passedProvider = passedVersionMap?.[version];
        const resolvedExternalProvider = __mfResolveExternalSharedProvider(
          federationInstances,
          scopeRoot,
          shared,
          'default',
          pkg,
          providerEntry,
          selectedExternalProvider,
          passedProvider,
          'version-first'
        );
        if (!resolvedExternalProvider && !selectedLocalProvider) return;
        const { provider, scopeRootProvider } = resolvedExternalProvider || {
          provider: selectedRuntimeProvider,
          scopeRootProvider: undefined
        };
        if (usedShare.canLiveRebind === false) return;
        if (usedShare.shareConfig?.import === false && __mfMatchesSharedProvider(provider, usedShare)) return;
        // Another container's consume-only stub has nothing to bridge to: its get() throws by construction.
        if (provider?.shareConfig?.import === false) return;
        // Preserve a singleton already selected by another container. The bridge may
        // only replace the provisional local fallback seeded by this container.
        if (cachedShare !== undefined && cachedShareOwner !== mfName) return;
        // Registration can replace an unloaded same-version root provider in-place.
        // Pin the chosen provider while loadShare() runs its implicit registration.
        const liveVersionMap = shared[pkg];
        const liveProvider = liveVersionMap?.[version];
        if (
          providerEntry.registered &&
          !scopeRootProvider &&
          !__mfMatchesSharedProvider(liveProvider, provider)
        ) return;
        const loadedShare = await __mfLoadPinnedRuntimeShare(
          pkg,
          usedShare.shareConfig,
          liveVersionMap,
          version,
          liveProvider,
          provider,
          providerEntry.registered && !selectedLocalProvider
        );
        const actualProvider = loadedShare?.provider;
        const actualSelection = loadedShare?.selection;
        if (!actualSelection) return;
        if (__mfMatchesSharedProvider(actualProvider, usedShare)) return;
        if (expectedSelection) {
          if (
            expectedSelection.version !== actualSelection.version ||
            !__mfMatchesSharedProvider({ from: actualSelection.from }, expectedSelection.provider)
          ) return;
        }
        if (bridgedProviders.has(actualProvider)) return;
        const resolved = loadedShare?.resolved;
        if (resolved === undefined) return;
        const latestCachedShare = __mfReadSharedCache(__mfModuleCache.share, usedCacheDescriptor);
        const latestCachedShareOwner = __mfReadSharedCacheOwner(__mfModuleCache.share, usedCacheDescriptor);
        if (latestCachedShare !== undefined && latestCachedShareOwner !== mfName) return;
        if (
          actualSelection.registered &&
          liveVersionMap?.[actualSelection.version] !== actualProvider
        ) return;
        if (!expectedSelection) {
          bridgeSelections.set(pkg, {
            version: actualSelection.version,
            provider: { from: actualSelection.from }
          });
        }
        bridgedProviders.add(actualProvider);
        const normalized = __mfNormalizeRuntimeShare(resolved);
        __mfWriteSharedCache(
          __mfModuleCache.share,
          usedCacheDescriptor,
          normalized,
          actualSelection.from
        );
      } catch (e) {
        console.error('[Module Federation] Failed to bridge external shared module "' + pkg + '"', e);
      }
    };
    for (const batch of __mfMaterializedShareBatches) await Promise.all(batch.map(async (pkg) => {
      const usedShare = usedShared[pkg];
      if (!usedShare || usedShare.materialize === false || usedShare.treeShaking) return;
      await __mfBridgeMaterializedProvider(pkg, usedShare, initialShared[pkg]);
    }));
    for (const [pkg, share] of Object.entries(usedShared)) {
      if (share.treeShaking) continue;
      const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
      if (__mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) !== undefined) continue;
      const singletonCacheDescriptor = __mfGetSharedCacheDescriptor(pkg, true, share.version, share.scope);
      const singletonModule = __mfReadSharedCache(__mfModuleCache.share, singletonCacheDescriptor);
      if (singletonModule !== undefined) {
        __mfWriteSharedCache(
          __mfModuleCache.share,
          cacheDescriptor,
          singletonModule,
          __mfReadSharedCacheOwner(__mfModuleCache.share, singletonCacheDescriptor)
        );
      }
    }
    
    const __mfSeedOrder = ["vue","vuetify/styles","vuetify"];
    const __mfVersionFirstDeferredSeeds = new Set([]);
    const __mfSeedBatches = [["vue"],["vuetify/styles"],["vuetify"]];
    const __mfSeedIndex = new Map(__mfSeedOrder.map((pkg, index) => [pkg, index]));
    const __mfSeedPrerequisites = {"1":[0],"2":[0,1]};
    // A share is normally skipped here until the dev scanner has observed a real
    // import and set materialize. An import:false share has no local fallback
    // though, so on a cold request (materialize not set yet) it must still be
    // attempted here, or it is never seeded and its consumer reads it undefined.
    const __mfSeedKeys = __mfSeedOrder.filter((pkg) => usedShared[pkg] && (usedShared[pkg].materialize !== false || (usedShared[pkg].shareConfig?.import === false && !usedShared[pkg].lazy)));
    __mfModuleCache.providerInit ||= new Map();
    const __mfInitializeProviderOnce = (key, initialize) => {
      const existing = __mfModuleCache.providerInit.get(key);
      if (existing) return existing;
      const pending = Promise.resolve().then(initialize);
      __mfModuleCache.providerInit.set(key, pending);
      pending.catch(() => __mfModuleCache.providerInit.delete(key));
      return pending;
    };
    var __mfSeedLocalShared = async (seedKeys) => {
      const requested = new Set(seedKeys);
      // A dependent of a share left to the late bridge would evaluate against an empty
      // wrapper (#1541); leave it to its wrapper's own fallback load instead.
      const skipped = new Set();
      for (const batch of __mfSeedBatches) await Promise.all(batch.filter((pkg) => requested.has(pkg)).map(async (pkg) => {
        const share = usedShared[pkg];
        const seedIndex = __mfSeedIndex.get(pkg);
        if ((__mfSeedPrerequisites[seedIndex] || []).some((dependency) => skipped.has(dependency))) {
          skipped.add(seedIndex);
          return;
        }
        const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
        if (
          share.shareConfig?.import === false ||
          Boolean(share.treeShaking) ||
          __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) !== undefined
        ) {
          return;
        }
        const singletonCacheDescriptor = __mfGetSharedCacheDescriptor(pkg, true, share.version, share.scope);
        const singletonModule = __mfReadSharedCache(__mfModuleCache.share, singletonCacheDescriptor);
        if (singletonModule !== undefined) {
          __mfWriteSharedCache(
            __mfModuleCache.share,
            cacheDescriptor,
            singletonModule,
            __mfReadSharedCacheOwner(__mfModuleCache.share, singletonCacheDescriptor)
          );
          return;
        }
        
        const externalProvider = typeof __mfGetExternalSharedProvider === 'function'
          ? __mfGetExternalSharedProvider(pkg, share)
          : undefined;
        if (externalProvider) {
          let externalFactory = externalProvider.lib;
          if (!externalFactory && externalProvider.loading) externalFactory = await externalProvider.loading;
          if (!externalFactory && externalProvider.loaded && typeof externalProvider.get === 'function') {
            externalFactory = await externalProvider.get();
          }
          if (externalFactory) {
            const externalModule = typeof externalFactory === "function" ? externalFactory() : externalFactory;
            const externalResolved = await Promise.resolve(externalModule);
            const __mfNormalizeRuntimeShare = (mod) => {
            let current = mod;
            for (let i = 0; i < 5; i++) {
              const defaultExport = current?.default;
              if (!defaultExport || typeof defaultExport !== "object" || Object.keys(defaultExport).length === 0) break;
              // Only unwrap plain CJS namespaces; spreading a class instance would drop its prototype.
              const proto = Object.getPrototypeOf(defaultExport);
              if (proto !== null && proto !== Object.prototype) break;
              const namedValues = Object.keys(current).filter((key) => key !== "default").map((key) => current[key]);
              if (namedValues.length > 0 && namedValues.some((value) => value !== undefined)) break;
              current = defaultExport;
            }
            return current;
          };
            __mfWriteSharedCache(
              __mfModuleCache.share,
              cacheDescriptor,
              __mfNormalizeRuntimeShare(externalResolved),
              externalProvider.from
            );
            return;
          }
          // A Vite container seeds its own copy into the module cache before the Runtime
          // marks its provider loaded. A non-singleton is cached under its version, so
          // look the selected provider's copy up under that version, not this share's.
          if (!share.shareConfig?.singleton && typeof externalProvider.version === 'string') {
            const externalCached = __mfReadSharedCache(
              __mfModuleCache.share,
              __mfGetSharedCacheDescriptor(pkg, false, externalProvider.version, share.scope)
            );
            if (externalCached !== undefined) {
              __mfWriteSharedCache(__mfModuleCache.share, cacheDescriptor, externalCached, externalProvider.from);
              return;
            }
          }
          // Leave an unloaded webpack provider to the late bridge, which only takes a
          // non-singleton of this share's own version; any other version seeds locally.
          if (
            typeof isWebpackProvider === 'function' &&
            isWebpackProvider(externalProvider) &&
            (share.shareConfig?.singleton ||
              __mfFindSharedProviderEntry(initialShared[pkg], externalProvider)?.version === share.version)
          ) {
            skipped.add(seedIndex);
            return;
          }
        }
        const providerKey = cacheDescriptor.canonical;
        const resolved = await __mfInitializeProviderOnce(providerKey, async () => {
          const factory = await share.get();
          const mod = typeof factory === "function" ? factory() : factory;
          return Promise.resolve(mod);
        });
        // The seeded local copy is what this container's consumers are bound to.
        // Flag the Runtime's provider as eager so a same-version sibling cannot
        // take over the share scope slot via the Runtime's name tie-break.
        for (const provider of initRes.options.shared?.[pkg] || []) {
          if (provider.get === share.get) provider.eager = true;
        }
        const __mfNormalizeRuntimeShare = (mod) => {
            let current = mod;
            for (let i = 0; i < 5; i++) {
              const defaultExport = current?.default;
              if (!defaultExport || typeof defaultExport !== "object" || Object.keys(defaultExport).length === 0) break;
              // Only unwrap plain CJS namespaces; spreading a class instance would drop its prototype.
              const proto = Object.getPrototypeOf(defaultExport);
              if (proto !== null && proto !== Object.prototype) break;
              const namedValues = Object.keys(current).filter((key) => key !== "default").map((key) => current[key]);
              if (namedValues.length > 0 && namedValues.some((value) => value !== undefined)) break;
              current = defaultExport;
            }
            return current;
          };
        const normalizedModule = __mfNormalizeRuntimeShare(resolved);
        const exportModule = normalizedModule === resolved ? {...resolved} : normalizedModule;
        if (exportModule.__esModule !== true) Object.defineProperty(exportModule, "__esModule", {
          value: true,
          enumerable: false
        });
        // The init map is page-wide: another container may have run this provider
        // init and seeded the result under its own name. Keep that owner, or this
        // container would later treat a sibling's copy as its own provisional seed.
        if (__mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) !== undefined) return;
        __mfWriteSharedCache(__mfModuleCache.share, cacheDescriptor, exportModule, mfName);
      }));
    };
    const __mfIsRuntimeOnlySharePending = (pkg) => {
      const share = usedShared[pkg];
      if (!share.treeShaking && share.shareConfig?.import !== false) return false;
      const cacheDescriptor = __mfGetSharedCacheDescriptor(
        pkg,
        share.shareConfig?.singleton,
        share.version,
        share.scope
      );
      return share.treeShaking
        ? (
            __mfReadTreeShakingSharedSelection(
              __mfModuleCache.share,
              cacheDescriptor,
              mfName
            ) === undefined &&
            __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) === undefined
          )
        : __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) === undefined;
    };
    const __mfNeedsPreInitSeedBarrier = (pkg) => {
      const share = usedShared[pkg];
      const cacheDescriptor = __mfGetSharedCacheDescriptor(
        pkg,
        share.shareConfig?.singleton,
        share.version,
        share.scope
      );
      const cachedShare = share.treeShaking
        ? (
            __mfReadTreeShakingSharedSelection(
              __mfModuleCache.share,
              cacheDescriptor,
              mfName
            ) ?? __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor)
          )
        : __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor);
      if (cachedShare !== undefined) return false;
      if (share.treeShaking || share.shareConfig?.import === false) return true;
      // version-first negotiates a singleton against this container's remotes, which only
      // register during initializeSharing(). Seeding the local copy before that evaluates it
      // even when a remote's higher version is selected, so a package with top-level side
      // effects (custom element registration, polyfills) runs twice (#1527). Wait for the
      // remotes; the deferred pass seeds the local copy only when no remote outranks it.
      // The React family keeps the eager seed its synchronous wrappers rely on.
      if (__mfVersionFirstDeferredSeeds.has(pkg) && share.shareConfig?.singleton) return true;
      if (typeof __mfSelectExternalSharedProvider !== 'function') return false;
      return Boolean(__mfSelectExternalSharedProvider(
        initialShared[pkg],
        pkg,
        share,
        "version-first"
      ));
    };
    const __mfExpandBlockedSeedKeys = (blocked) => {
      let changed = true;
      while (changed) {
        changed = false;
        for (const pkg of __mfSeedKeys) {
          const seedIndex = __mfSeedIndex.get(pkg);
          if (blocked.has(seedIndex)) continue;
          if ((__mfSeedPrerequisites[seedIndex] || []).some((dependency) => blocked.has(dependency))) {
            blocked.add(seedIndex);
            changed = true;
          }
        }
      }
      return blocked;
    };
    const __mfPreInitBlockedSeedKeys = __mfExpandBlockedSeedKeys(new Set(
      __mfSeedKeys.filter(__mfNeedsPreInitSeedBarrier).map((pkg) => __mfSeedIndex.get(pkg))
    ));
    const __mfImmediateSeedKeys = __mfSeedKeys.filter(
      (pkg) => !__mfPreInitBlockedSeedKeys.has(__mfSeedIndex.get(pkg))
    );
    var __mfDeferredSeedKeys = __mfSeedKeys.filter(
      (pkg) => __mfPreInitBlockedSeedKeys.has(__mfSeedIndex.get(pkg))
    );
    await __mfSeedLocalShared(__mfImmediateSeedKeys).catch(__mfRejectInit);
    try {
      await retrySharedInit(async () => {
        await Promise.all(await initRes.initializeSharing('default', {
          strategy: 'version-first',
          from: "build",
          initScope
        }));
      });
    } catch (e) {
      console.error('[Module Federation]', e);
    }
    __mfRestoreForeignSharedProviders();
    // Calling provider.get() marks a provider as loaded. Wait until the Runtime has
    // finalized normal same-version precedence before materializing an external share.
    const __mfBridgeSharedProviders = async () => {
      for (const batch of __mfMaterializedShareBatches) await Promise.all(batch.map(async (pkg) => {
        const usedShare = usedShared[pkg];
        if (!usedShare || usedShare.materialize === false || usedShare.treeShaking) return;
        await __mfBridgeExternalSharedProvider(
          pkg,
          usedShare,
          shared[pkg],
          initialShared[pkg],
          undefined
        );
      }));
    };
    if (__mfUsesWebpackShareScope) {
      // A webpack host's loadShare() awaits initializeSharing(), which awaits this
      // init(). Bridging here would call the host's provider.get() and re-enter
      // loadShare(), so both promises wait on each other forever (#1326).
      __mfLateBridgeShared = __mfBridgeSharedProviders;
    } else {
      await __mfBridgeSharedProviders();
    }
    try {
      const allInstances = globalThis.__FEDERATION__?.__SHARE__;
      const globalVersionsByPackage = Object.create(null);
      if (allInstances) {
        for (const [, scopes] of Object.entries(allInstances)) {
          for (const scopeName of shareScopeNames) {
            const scopeShare = scopes?.[scopeName];
            if (!scopeShare) continue;
            for (const [pkg, versionMap] of Object.entries(scopeShare)) {
            const usedShare = usedShared?.[pkg];
            const passedVersions = initialShared[pkg];
            const bridgeSelection = bridgeSelections.get(pkg);
            if (!usedShare) continue;
            if (!passedVersions) continue;
            if (!bridgeSelection) continue;
            if (usedShare.treeShaking) continue;
            const globalVersions = globalVersionsByPackage[pkg] || (globalVersionsByPackage[pkg] = Object.create(null));
            for (const [version, provider] of Object.entries(versionMap)) {
              if (!provider.lib) continue;
              if (bridgeSelection.version !== version) continue;
              if (!__mfMatchesSharedProvider(provider, bridgeSelection.provider)) continue;
              const passedProvider = passedVersions[version];
              const matchesPassedProvider = provider === passedProvider || (
                passedProvider?.from && provider.from === passedProvider.from
              );
              if (!matchesPassedProvider) continue;
              if (provider === usedShare || (usedShare.from && provider.from === usedShare.from)) continue;
              if (globalVersions[version] === undefined) globalVersions[version] = provider;
            }
            }
          }
        }
      }
      for (const batch of __mfMaterializedShareBatches) await Promise.all(batch.map(async (pkg) => {
        const versionMap = globalVersionsByPackage[pkg];
        if (!versionMap) return;
        await __mfBridgeExternalSharedProvider(
          pkg,
          usedShared[pkg],
          versionMap,
          initialShared[pkg],
          bridgeSelections.get(pkg)
        );
      }));
    } catch (e) {
      console.error('[Module Federation] Failed to bridge external shared modules', e);
    }
    const __mfResolveTreeShakingShared = async () => {};
    const __mfResolveImportFalseShared = async (pkg, share) => {
      const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
      const cachedShare = share.treeShaking
        ? __mfReadTreeShakingSharedSelection(__mfModuleCache.share, cacheDescriptor, mfName)
        : __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor);
      if (share.shareConfig?.import !== false || cachedShare !== undefined) return;
      if (__mfGetPendingExternalSharedProvider(pkg, share, initialShared[pkg])) return;
      const __mfNormalizeRuntimeShare = (mod) => {
            let current = mod;
            for (let i = 0; i < 5; i++) {
              const defaultExport = current?.default;
              if (!defaultExport || typeof defaultExport !== "object" || Object.keys(defaultExport).length === 0) break;
              // Only unwrap plain CJS namespaces; spreading a class instance would drop its prototype.
              const proto = Object.getPrototypeOf(defaultExport);
              if (proto !== null && proto !== Object.prototype) break;
              const namedValues = Object.keys(current).filter((key) => key !== "default").map((key) => current[key]);
              if (namedValues.length > 0 && namedValues.some((value) => value !== undefined)) break;
              current = defaultExport;
            }
            return current;
          };
      const versionMap = shared?.[pkg];
      const provider = __mfSelectSharedProvider(
        versionMap,
        pkg,
        share,
        'version-first'
      ) || share;
      const providerEntry = __mfFindSharedProviderEntry(versionMap, provider);
      if (!providerEntry) return;
      // A provider registered on this instance through the public registerShared
      // API carries this container's own name, so tell the own stub apart by its
      // import:false config rather than by provenance.
      const __mfIsOwnStub = (candidate) => candidate === share || candidate?.shareConfig?.import === false;
      if (__mfIsOwnStub(provider)) return;
      const { version } = providerEntry;
      const currentProvider = versionMap?.[version];
      const loadedShare = await __mfLoadPinnedRuntimeShare(
        pkg,
        share.shareConfig,
        versionMap,
        version,
        currentProvider,
        provider,
        providerEntry.registered
      );
      const providerSelection = loadedShare?.selection;
      const actualProvider = loadedShare?.provider;
      const resolved = loadedShare?.resolved;
      if (!providerSelection) return;
      if (__mfIsOwnStub(actualProvider)) return;
      if (resolved === undefined) return;
      const latestCachedShare = share.treeShaking
        ? __mfReadTreeShakingSharedSelection(__mfModuleCache.share, cacheDescriptor, mfName)
        : __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor);
      if (latestCachedShare !== undefined) return;
      if (
        providerSelection.registered &&
        versionMap?.[providerSelection.version] !== actualProvider
      ) return;
      const normalizedShared = __mfNormalizeRuntimeShare(resolved);
      if (share.treeShaking) {
        const providedExports = share.treeShaking.providedExports ?? share.treeShaking.usedExports ?? [];
        __mfWriteTreeShakingSharedCache(
          __mfModuleCache.share,
          cacheDescriptor,
          providedExports,
          normalizedShared
        );
        __mfWriteTreeShakingSharedSelection(
          __mfModuleCache.share,
          cacheDescriptor,
          mfName,
          normalizedShared
        );
      } else {
        __mfWriteSharedCache(
          __mfModuleCache.share,
          cacheDescriptor,
          normalizedShared,
          providerSelection.from
        );
      }
    };
    // Resolve runtime-only dependencies and seed local fallbacks in dependency
    // order. An unresolved provider blocks its consumers, which would otherwise
    // capture an undefined or provisional singleton; unrelated shares still seed.
    const __mfReadyDeferredSeedKeys = [];
    const __mfBlockedSeedKeys = new Set();
    for (const pkg of __mfDeferredSeedKeys) {
      const share = usedShared[pkg];
      const seedIndex = __mfSeedIndex.get(pkg);
      if (__mfIsRuntimeOnlySharePending(pkg)) {
        try {
          if (share.treeShaking) {
            await __mfResolveTreeShakingShared(pkg, share);
          } else if (share.shareConfig?.import === false) {
            await __mfResolveImportFalseShared(pkg, share);
          }
        } catch (err) {
          // A rejected provider is an unresolved provider: block its consumers as the
          // comment above prescribes, instead of escalating to a container-wide init() failure.
          console.error(
            `[Module Federation] Failed to resolve runtime-only shared module "${pkg}"`,
            err
          );
        }
      }
      if (__mfIsRuntimeOnlySharePending(pkg)) {
        __mfBlockedSeedKeys.add(seedIndex);
      }
    }
    __mfExpandBlockedSeedKeys(__mfBlockedSeedKeys);
    __mfReadyDeferredSeedKeys.push(...__mfDeferredSeedKeys.filter(
      (pkg) => !__mfBlockedSeedKeys.has(__mfSeedIndex.get(pkg))
    ));
    await __mfSeedLocalShared(__mfReadyDeferredSeedKeys).catch(__mfRejectInit);
    // A consume-only share reached only through import() is bridged when that import runs
    // (see pluginLazyConsumeOnlyShares), through the same provider selection init() uses.
    const __mfLazyShareLoads = new Map();
    __mfResolveState.loadLazyShares = async (names) => {
      const requested = new Set(names);
      for (const batch of __mfMaterializedShareBatches) await Promise.all(batch.filter((pkg) => requested.has(pkg)).map((pkg) => {
        const share = usedShared[pkg];
        if (!share || !share.lazy || !__mfIsRuntimeOnlySharePending(pkg)) return;
        let load = __mfLazyShareLoads.get(pkg);
        if (!load) {
          load = __mfBridgeExternalSharedProvider(
            pkg,
            share,
            shared[pkg],
            initialShared[pkg],
            undefined
          ).then(() => __mfIsRuntimeOnlySharePending(pkg) ? __mfResolveImportFalseShared(pkg, share) : undefined);
          load.catch(() => __mfLazyShareLoads.delete(pkg));
          __mfLazyShareLoads.set(pkg, load);
        }
        return load;
      }));
    };
    initResolve(initRes);
    return initRes
    } finally {
      if (--__mfInitsInFlight === 0) __mfSettleInits();
    }
  }

  async function getExposes(moduleName) {
    // init() failures surface from init() itself; get() only waits for it to settle.
    if (__mfInitsInFlight) await __mfInitsSettled;
    const exposesMap = await getExposesMap();
    if (!(moduleName in exposesMap)) throw new Error(`[Module Federation] Module ${moduleName} does not exist in container.`)
    if (__mfLateBridgeShared) await __mfLateBridgeShared();
    if (__mfModuleCache.pendingShareLoads) {
      await Promise.all(__mfModuleCache.pendingShareLoads);
    }
    const res = await exposesMap[moduleName]();
    // Wrappers evaluated by the expose import may queue share loads only now (#1535).
    if (__mfModuleCache.pendingShareLoads) {
      await Promise.all(__mfModuleCache.pendingShareLoads);
    }
    return () => res
  }

export { getExposes as get, init };

if (typeof document !== 'undefined' && document.head) {
  try {
    for (const __mfWarmupPath of ["./_virtual_mf-localSharedImportMap___mfe_internal__BrushFlow__mf_owner__1-C6y-c5Nn.js","./index-pSqlufH5.js","./index-Cezq_yMy.js"]) {
      const __mfWarmupLink = document.createElement('link');
      __mfWarmupLink.rel = 'modulepreload';
      __mfWarmupLink.crossOrigin = '';
      __mfWarmupLink.href = new URL(__mfWarmupPath, import.meta.url).href;
      document.head.appendChild(__mfWarmupLink);
    }
  } catch (__mfWarmupError) {}
}
