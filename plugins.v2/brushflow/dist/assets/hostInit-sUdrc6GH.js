import { _ as __vitePreload } from './vite-preload-helper-BelkbqnE.js';
import { s as share } from './helpers-_Ccnm3rP.js';
import './index-Cezq_yMy.js';

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

    let hostInitPromise;
    async function initHost() {
      if (!hostInitPromise) {
        hostInitPromise = (async () => {
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
            cache[__mfSharedCacheOwnersKey];
            {
              __mfGetSharedCacheOwners(cache)[descriptor.canonical] = owner;
            }
            const listeners = cache[__mfSharedCacheListenersKey]?.[descriptor.canonical];
            if (listeners) {
              for (const listener of listeners) listener(value);
            }
            return value;
          };
          
          const remoteEntry = await __vitePreload(() => import('./remoteEntry.js'),true?[]:void 0);
          const runtime = await remoteEntry.init();
          const {usedShared} = await __vitePreload(async () => { const {usedShared} = await import('./_virtual_mf-localSharedImportMap___mfe_internal__BrushFlow__mf_owner__1-C6y-c5Nn.js');return {usedShared}},true?[]:void 0);
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
          
          const __mfHasAlternativeSharedVersion = (pkg, share) =>
            __mfGetShareScopeNames(share).some(
              (scopeName) => Object.keys(runtime.shareScopeMap?.[scopeName]?.[pkg] || {}).some(
                (version) => version !== share.version
              )
            );
          const __mfHostInitShareBatches = [["vue"],["vuetify/styles"],["vuetify"]];
          // The baked batches are generated before the build has seen every import, so a
          // share first used later in the graph, such as react-dom/client, is missing from
          // them. Negotiate those after the baked batches, once their package roots have
          // settled (#1503).
          {
            const bakedKeys = new Set(__mfHostInitShareBatches.flat());
            const lateKeys = Object.keys(usedShared).filter((pkg) => !bakedKeys.has(pkg));
            if (lateKeys.length) __mfHostInitShareBatches.push(lateKeys);
          }
          
          const __mfOriginalProviderKey = Symbol("mf.originalSharedProvider");
          const __mfResolveShareHook = { emit: (params) => params };
          const __mfGetShareScopeNames = (share) =>
            Array.isArray(share.scope) ? share.scope : [share.scope || "default"];
          const __mfCreateProviderSelectionVersions = (versions, strategy) => {
            const selectionVersions = {};
            for (const [version, provider] of Object.entries(versions)) {
              selectionVersions[version] = Object.assign({}, provider, {
                [__mfOriginalProviderKey]: provider
              });
            }
            return selectionVersions;
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
            const selectionVersions = __mfCreateProviderSelectionVersions(candidates);
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
          const __mfHasUsableProvider = (versions, pkg, share, scopeName) => {
            // Keep runtime singleton negotiation unchanged. A singleton already
            // registered in this scope is authoritative, even when runtime-core
            // reports a version mismatch.
            if (share.shareConfig?.singleton) {
              return Object.values(versions || {}).some(
                (provider) => provider?.shareConfig?.import !== false
              );
            }
            return Boolean(__mfSelectSharedProvider(
              versions,
              pkg,
              { ...share, scope: [scopeName] },
              "version-first"
            ));
          };
          // Hosts on one page share the module cache. Negotiate one host at a time so
          // none adopts another's half-upgraded set of singletons.
          const __mfPinnedShareOwners = (__mfModuleCache.pinnedShareOwners ||= new Set());
          const __mfPreviousHostShareInit = __mfModuleCache.hostShareInit;
          let __mfReleaseHostShareInit;
          __mfModuleCache.hostShareInit = new Promise((resolve) => {
            __mfReleaseHostShareInit = resolve;
          });
          await __mfPreviousHostShareInit;
          try {
          for (const __mfHostInitShareBatch of __mfHostInitShareBatches) {
            await Promise.all(__mfHostInitShareBatch.map(async (pkg) => {
              const share = usedShared[pkg];
              // A standalone container has no dynamic-import boundary to load a lazy share behind.
              if (!share || (share.materialize === false && !share.lazy)) return;
              // remoteEntry.init resolves tree-enabled shares into the
              // coverage-aware cache. Never republish that selected partial under
              // a generic full-module key here.
              if (share.treeShaking) return;
              const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
              // Another host on the page may hold this singleton in the module cache. Its
              // app, e.g. its react-dom, is bound to that copy, so this host adopts it and
              // pins that host's seeds: re-negotiation may then no longer upgrade them.
              const __mfKeepsCachedSingleton = () => {
                if (!share.shareConfig?.singleton) return false;
                if (__mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) === undefined) return false;
                const owner = __mfReadSharedCacheOwner(__mfModuleCache.share, cacheDescriptor);
                if (owner === undefined) return false;
                if (owner === "BrushFlow") return __mfPinnedShareOwners.has(owner);
                if ((runtime.options?.remotes || []).some((remote) => remote.name === owner)) return false;
                __mfPinnedShareOwners.add(owner);
                return true;
              };
              if (__mfKeepsCachedSingleton()) return;
              if (
                __mfReadSharedCache(__mfModuleCache.share, cacheDescriptor) !== undefined &&
                (
                        !__mfHasAlternativeSharedVersion(pkg, share) &&
                        (share.shareConfig?.singleton ||
                          __mfReadSharedCacheOwner(__mfModuleCache.share, cacheDescriptor) === "BrushFlow")
                      )
              ) return;
              // An import:false share has nothing to load until a foreign provider
              // registers: its own stub getter throws by construction. A standalone
              // container initialized on the same page keeps its providers in its
              // own runtime scope (#1307), so adopt those before giving up.
              if (share.shareConfig?.import === false) {
                const __mfScopeNames = __mfGetShareScopeNames(share);
                const __mfNeedsSiblingProvider = (scopeName) =>
                  !__mfHasUsableProvider(
                    runtime.shareScopeMap?.[scopeName]?.[pkg],
                    pkg,
                    share,
                    scopeName
                  );
                if (__mfScopeNames.some(__mfNeedsSiblingProvider)) {
                  // loadShare() re-runs initializeSharing(), which re-registers this
                  // container's own stub and lets it displace an unloaded adopted
                  // provider whenever this container's name sorts after the provider's
                  // (#1311). Put the provider back: a stub never outranks a provider.
                  if (!runtime.__mfKeepAdoptedProviders) {
      runtime.__mfKeepAdoptedProviders = true;
      runtime.sharedHandler?.hooks?.lifecycle?.afterRegisterShare?.on?.((args) => {
        const { shared, previousShared, registeredShared } = args || {};
        const versions = runtime.shareScopeMap?.[args.scope]?.[args.pkgName];
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
                  for (const instance of globalThis.__FEDERATION__?.__INSTANCES__ || []) {
                    for (const scopeName of __mfScopeNames) {
                      const versions = instance?.shareScopeMap?.[scopeName]?.[pkg];
                      if (!__mfHasUsableProvider(versions, pkg, share, scopeName)) continue;
                      if (!__mfNeedsSiblingProvider(scopeName)) continue;
                      const target = (runtime.shareScopeMap[scopeName] ||= {})[pkg] ||= {};
                      for (const [version, provider] of Object.entries(versions)) {
                        if (provider?.shareConfig?.import === false) continue;
                        if (target[version] && target[version].shareConfig?.import !== false) continue;
                        target[version] = provider;
                      }
                    }
                  }
                }
                if (__mfScopeNames.every(__mfNeedsSiblingProvider)) return;
              }
              await runtime.loadShare(pkg, {
                customShareInfo: { shareConfig: share.shareConfig }
              }).then(async (factory) => {
                if (factory === false) return;
                if (__mfKeepsCachedSingleton()) return;
                const mod = typeof factory === "function" ? factory() : factory;
                let resolved = __mfNormalizeRuntimeShare(await Promise.resolve(mod));
                
                __mfWriteSharedCache(
                  __mfModuleCache.share,
                  cacheDescriptor,
                  resolved,
                  "BrushFlow"
                );
              });
            }));
          }
          } finally {
            __mfReleaseHostShareInit();
          }
          
          // The seed called this container's get() directly, so the Runtime's
          // provider never learned it is in use and a remote could load its own
          // copy (#1396). Mark it once the host is bound to the local copy.
          for (const [pkg, share] of Object.entries(usedShared)) {
            if (!share.lib || share.treeShaking || share.shareConfig?.import === false) continue;
            const cacheDescriptor = __mfGetSharedCacheDescriptor(pkg, share.shareConfig?.singleton, share.version, share.scope);
            if (__mfReadSharedCacheOwner(__mfModuleCache.share, cacheDescriptor) !== "BrushFlow") continue;
            for (const scopeName of Array.isArray(share.scope) ? share.scope : [share.scope || "default"]) {
              const versions = runtime.shareScopeMap?.[scopeName]?.[pkg];
              const provider = versions?.[share.version];
              if (!provider || provider.get !== share.get || provider.lib) continue;
              if (Object.values(versions).some((other) => other !== provider && (other?.lib || other?.loaded))) continue;
              provider.lib = share.lib;
              provider.loaded = true;
            }
          }
          return runtime;
        })();
      }
      return hostInitPromise;
    }
    hostInitPromise = initHost();

export { hostInitPromise, initHost };
