//#region src/constant.ts
const MANIFEST_EXT = ".json";
const BROWSER_LOG_KEY = "FEDERATION_DEBUG";
const SEPARATOR = ":";
let TreeShakingStatus = /* @__PURE__ */ function(TreeShakingStatus) {
	/**
	* Not handled by deploy server, needs to infer by the real runtime period.
	*/
	TreeShakingStatus[TreeShakingStatus["UNKNOWN"] = 1] = "UNKNOWN";
	/**
	* It means the shared has been calculated , runtime should take this shared as first choice.
	*/
	TreeShakingStatus[TreeShakingStatus["CALCULATED"] = 2] = "CALCULATED";
	/**
	* It means the shared has been calculated, and marked as no used
	*/
	TreeShakingStatus[TreeShakingStatus["NO_USE"] = 0] = "NO_USE";
	return TreeShakingStatus;
}({});

var define_process_env_default = {};
const isBrowserEnvValue = true ;
function isBrowserEnv() {
  return isBrowserEnvValue;
}
function isBrowserDebug() {
  try {
    if (isBrowserEnv() && window.localStorage) return Boolean(localStorage.getItem(BROWSER_LOG_KEY));
  } catch (error) {
    return false;
  }
  return false;
}
function isDebugMode() {
  if (typeof process !== "undefined" && define_process_env_default && define_process_env_default["FEDERATION_DEBUG"]) return Boolean(define_process_env_default["FEDERATION_DEBUG"]);
  if (typeof FEDERATION_DEBUG !== "undefined" && Boolean(FEDERATION_DEBUG)) return true;
  return isBrowserDebug();
}

//#region src/utils.ts
const LOG_CATEGORY$1 = "[ Federation Runtime ]";
const composeKeyWithSeparator = function(...args) {
	if (!args.length) return "";
	return args.reduce((sum, cur) => {
		if (!cur) return sum;
		if (!sum) return cur;
		return `${sum}${SEPARATOR}${cur}`;
	}, "");
};
function getResourceUrl(module, sourceUrl) {
	if ("getPublicPath" in module) {
		let publicPath;
		if (!module.getPublicPath.startsWith("function")) publicPath = new Function(module.getPublicPath)();
		else publicPath = new Function("return " + module.getPublicPath)()();
		return `${publicPath}${sourceUrl}`;
	} else if ("publicPath" in module) {
		return `${module.publicPath}${sourceUrl}`;
	} else {
		console.warn("Cannot get resource URL. If in debug mode, please ignore.", module, sourceUrl);
		return "";
	}
}
const warn = (msg) => {
	console.warn(`${LOG_CATEGORY$1}: ${msg}`);
};
function safeToString(info) {
	try {
		return JSON.stringify(info, null, 2);
	} catch (e) {
		return "";
	}
}

//#region src/generateSnapshotFromManifest.ts
const simpleJoinRemoteEntry = (rPath, rName) => {
	if (!rPath) return rName;
	const transformPath = (str) => {
		if (str === ".") return "";
		if (str.startsWith("./")) return str.replace("./", "");
		if (str.startsWith("/")) {
			const strWithoutSlash = str.slice(1);
			if (strWithoutSlash.endsWith("/")) return strWithoutSlash.slice(0, -1);
			return strWithoutSlash;
		}
		return str;
	};
	const transformedPath = transformPath(rPath);
	if (!transformedPath) return rName;
	if (transformedPath.endsWith("/")) return `${transformedPath}${rName}`;
	return `${transformedPath}/${rName}`;
};
function inferAutoPublicPath(url) {
	return url.replace(/#.*$/, "").replace(/\?.*$/, "").replace(/\/[^\/]+$/, "/");
}
function generateSnapshotFromManifest(manifest, options = {}) {
	const { remotes = {}, overrides = {}, version } = options;
	let remoteSnapshot;
	const getPublicPath = () => {
		if ("publicPath" in manifest.metaData) {
			if ((manifest.metaData.publicPath === "auto" || manifest.metaData.publicPath === "") && version) return inferAutoPublicPath(version);
			return manifest.metaData.publicPath;
		} else return manifest.metaData.getPublicPath;
	};
	const overridesKeys = Object.keys(overrides);
	let remotesInfo = {};
	if (!Object.keys(remotes).length) remotesInfo = manifest.remotes?.reduce((res, next) => {
		let matchedVersion;
		const name = next.federationContainerName;
		if (overridesKeys.includes(name)) matchedVersion = overrides[name];
		else if ("version" in next) matchedVersion = next.version;
		else matchedVersion = next.entry;
		res[name] = { matchedVersion };
		return res;
	}, {}) || {};
	Object.keys(remotes).forEach((key) => remotesInfo[key] = { matchedVersion: overridesKeys.includes(key) ? overrides[key] : remotes[key] });
	const { remoteEntry: { path: remoteEntryPath, name: remoteEntryName, type: remoteEntryType }, types: remoteTypes = {
		path: "",
		name: "",
		zip: "",
		api: ""
	}, buildInfo: { buildVersion }, globalName, ssrRemoteEntry } = manifest.metaData;
	const { exposes } = manifest;
	let basicRemoteSnapshot = {
		version: version ? version : "",
		buildVersion,
		globalName,
		remoteEntry: simpleJoinRemoteEntry(remoteEntryPath, remoteEntryName),
		remoteEntryType,
		remoteTypes: simpleJoinRemoteEntry(remoteTypes.path, remoteTypes.name),
		remoteTypesZip: remoteTypes.zip || "",
		remoteTypesAPI: remoteTypes.api || "",
		remotesInfo,
		shared: manifest?.shared.map((item) => ({
			assets: item.assets,
			sharedName: item.name,
			version: item.version,
			usedExports: item.referenceExports || []
		})),
		modules: exposes?.map((expose) => ({
			moduleName: expose.name,
			modulePath: expose.path,
			assets: expose.assets
		}))
	};
	if ("publicPath" in manifest.metaData) {
		remoteSnapshot = {
			...basicRemoteSnapshot,
			publicPath: getPublicPath()
		};
		if (typeof manifest.metaData.ssrPublicPath === "string") remoteSnapshot.ssrPublicPath = manifest.metaData.ssrPublicPath;
	} else remoteSnapshot = {
		...basicRemoteSnapshot,
		getPublicPath: getPublicPath()
	};
	if (ssrRemoteEntry) {
		const fullSSRRemoteEntry = simpleJoinRemoteEntry(ssrRemoteEntry.path, ssrRemoteEntry.name);
		remoteSnapshot.ssrRemoteEntry = fullSSRRemoteEntry;
		remoteSnapshot.ssrRemoteEntryType = ssrRemoteEntry.type || "commonjs-module";
	}
	return remoteSnapshot;
}
function isManifestProvider(moduleInfo) {
	if ("remoteEntry" in moduleInfo && moduleInfo.remoteEntry.includes(MANIFEST_EXT)) return true;
	else return false;
}

//#region src/logger.ts
const PREFIX = "[ Module Federation ]";
const DEFAULT_DELEGATE = console;
const LOGGER_STACK_SKIP_TOKENS = [
	"logger.ts",
	"logger.js",
	"captureStackTrace",
	"Logger.emit",
	"Logger.log",
	"Logger.info",
	"Logger.warn",
	"Logger.error",
	"Logger.debug"
];
function captureStackTrace() {
	try {
		const stack = (/* @__PURE__ */ new Error()).stack;
		if (!stack) return;
		const [, ...rawLines] = stack.split("\n");
		const filtered = rawLines.filter((line) => !LOGGER_STACK_SKIP_TOKENS.some((token) => line.includes(token)));
		if (!filtered.length) return;
		return `Stack trace:\n${filtered.slice(0, 5).join("\n")}`;
	} catch {
		return;
	}
}
var Logger = class {
	constructor(prefix, delegate = DEFAULT_DELEGATE) {
		this.prefix = prefix;
		this.delegate = delegate ?? DEFAULT_DELEGATE;
	}
	setPrefix(prefix) {
		this.prefix = prefix;
	}
	setDelegate(delegate) {
		this.delegate = delegate ?? DEFAULT_DELEGATE;
	}
	emit(method, args) {
		const delegate = this.delegate;
		const stackTrace = isDebugMode() ? captureStackTrace() : void 0;
		const enrichedArgs = stackTrace ? [...args, stackTrace] : args;
		const order = (() => {
			switch (method) {
				case "log": return ["log", "info"];
				case "info": return ["info", "log"];
				case "warn": return [
					"warn",
					"info",
					"log"
				];
				case "error": return [
					"error",
					"warn",
					"log"
				];
				default: return ["debug", "log"];
			}
		})();
		for (const candidate of order) {
			const handler = delegate[candidate];
			if (typeof handler === "function") {
				handler.call(delegate, this.prefix, ...enrichedArgs);
				return;
			}
		}
		for (const candidate of order) {
			const handler = DEFAULT_DELEGATE[candidate];
			if (typeof handler === "function") {
				handler.call(DEFAULT_DELEGATE, this.prefix, ...enrichedArgs);
				return;
			}
		}
	}
	log(...args) {
		this.emit("log", args);
	}
	warn(...args) {
		this.emit("warn", args);
	}
	error(...args) {
		this.emit("error", args);
	}
	success(...args) {
		this.emit("info", args);
	}
	info(...args) {
		this.emit("info", args);
	}
	ready(...args) {
		this.emit("info", args);
	}
	debug(...args) {
		if (isDebugMode()) this.emit("debug", args);
	}
};
function createLogger(prefix) {
	return new Logger(prefix);
}
function createInfrastructureLogger(prefix) {
	const infrastructureLogger = new Logger(prefix);
	Object.defineProperty(infrastructureLogger, "__mf_infrastructure_logger__", {
		value: true,
		enumerable: false,
		configurable: false
	});
	return infrastructureLogger;
}
createInfrastructureLogger(PREFIX);

//#region src/dom.ts
async function safeWrapper(callback, disableWarn) {
	try {
		return await callback();
	} catch (e) {
		warn(e);
		return;
	}
}
function isStaticResourcesEqual(url1, url2) {
	const REG_EXP = /^(https?:)?\/\//i;
	return url1.replace(REG_EXP, "").replace(/\/$/, "") === url2.replace(REG_EXP, "").replace(/\/$/, "");
}
function createScript(info) {
	let script = null;
	let needAttach = true;
	let timeout = 2e4;
	let timeoutId;
	const scripts = document.getElementsByTagName("script");
	for (let i = 0; i < scripts.length; i++) {
		const s = scripts[i];
		const scriptSrc = s.getAttribute("src");
		if (scriptSrc && isStaticResourcesEqual(scriptSrc, info.url)) {
			script = s;
			needAttach = false;
			break;
		}
	}
	if (!script) {
		const attrs = info.attrs;
		script = document.createElement("script");
		script.type = attrs?.["type"] === "module" ? "module" : "text/javascript";
		let createScriptRes = void 0;
		if (info.createScriptHook) {
			createScriptRes = info.createScriptHook(info.url, info.attrs);
			if (createScriptRes instanceof HTMLScriptElement) script = createScriptRes;
			else if (typeof createScriptRes === "object") {
				if ("script" in createScriptRes && createScriptRes.script) script = createScriptRes.script;
				if ("timeout" in createScriptRes && createScriptRes.timeout) timeout = createScriptRes.timeout;
			}
		}
		if (!script.src) script.src = info.url;
		if (attrs && !createScriptRes) Object.keys(attrs).forEach((name) => {
			if (script) {
				if (name === "async" || name === "defer") script[name] = attrs[name];
				else if (!script.getAttribute(name)) script.setAttribute(name, attrs[name]);
			}
		});
	}
	let executionError = null;
	const executionErrorHandler = typeof window !== "undefined" ? (evt) => {
		if (evt.filename && isStaticResourcesEqual(evt.filename, info.url)) {
			const err = /* @__PURE__ */ new Error(`ScriptExecutionError: Script "${info.url}" loaded but threw a runtime error during execution: ${evt.message} (${evt.filename}:${evt.lineno}:${evt.colno})`);
			err.name = "ScriptExecutionError";
			executionError = err;
		}
	} : null;
	if (executionErrorHandler) window.addEventListener("error", executionErrorHandler);
	const onScriptComplete = async (prev, event) => {
		clearTimeout(timeoutId);
		if (executionErrorHandler) window.removeEventListener("error", executionErrorHandler);
		const onScriptCompleteCallback = () => {
			if (event?.type === "error") {
				const networkError = /* @__PURE__ */ new Error(event?.isTimeout ? `ScriptNetworkError: Script "${info.url}" timed out.` : `ScriptNetworkError: Failed to load script "${info.url}" - the script URL is unreachable or the server returned an error (network failure, 404, CORS, etc.)`);
				networkError.name = "ScriptNetworkError";
				info?.onErrorCallback && info?.onErrorCallback(networkError);
			} else if (executionError) info?.onErrorCallback && info?.onErrorCallback(executionError);
			else info?.cb && info?.cb();
		};
		if (script) {
			script.onerror = null;
			script.onload = null;
			safeWrapper(() => {
				const { needDeleteScript = true } = info;
				if (needDeleteScript) script?.parentNode && script.parentNode.removeChild(script);
			});
			if (prev && typeof prev === "function") {
				const result = prev(event);
				if (result instanceof Promise) {
					const res = await result;
					onScriptCompleteCallback();
					return res;
				}
				onScriptCompleteCallback();
				return result;
			}
		}
		onScriptCompleteCallback();
	};
	script.onerror = onScriptComplete.bind(null, script.onerror);
	script.onload = onScriptComplete.bind(null, script.onload);
	timeoutId = setTimeout(() => {
		onScriptComplete(null, {
			type: "error",
			isTimeout: true
		});
	}, timeout);
	return {
		script,
		needAttach
	};
}
function createLink(info) {
	let link = null;
	let needAttach = true;
	let timeout = 2e4;
	let timeoutId;
	const links = document.getElementsByTagName("link");
	for (let i = 0; i < links.length; i++) {
		const l = links[i];
		const linkHref = l.getAttribute("href");
		const linkRel = l.getAttribute("rel");
		if (linkHref && isStaticResourcesEqual(linkHref, info.url) && linkRel === info.attrs["rel"]) {
			link = l;
			needAttach = false;
			break;
		}
	}
	if (!link) {
		link = document.createElement("link");
		link.setAttribute("href", info.url);
		let createLinkRes = void 0;
		let shouldApplyAttrs = true;
		const attrs = info.attrs;
		if (info.createLinkHook) {
			createLinkRes = info.createLinkHook(info.url, attrs);
			if (createLinkRes instanceof HTMLLinkElement) {
				link = createLinkRes;
				shouldApplyAttrs = false;
			} else if (typeof createLinkRes === "object") {
				if ("link" in createLinkRes && createLinkRes.link) {
					link = createLinkRes.link;
					shouldApplyAttrs = false;
				}
				if ("timeout" in createLinkRes && createLinkRes.timeout) timeout = createLinkRes.timeout;
			}
		}
		if (attrs && shouldApplyAttrs) Object.keys(attrs).forEach((name) => {
			if (link && !link.getAttribute(name)) link.setAttribute(name, attrs[name]);
		});
	}
	if (!needAttach) {
		Promise.resolve().then(() => {
			info?.cb && info?.cb();
		});
		return {
			link,
			needAttach
		};
	}
	const onLinkComplete = (prev, event) => {
		if (timeoutId) clearTimeout(timeoutId);
		const onLinkCompleteCallback = () => {
			if (event?.type === "error") {
				const linkError = /* @__PURE__ */ new Error(event?.isTimeout ? `LinkNetworkError: Link "${info.url}" timed out.` : `LinkNetworkError: Failed to load link "${info.url}" - the URL is unreachable or the server returned an error.`);
				linkError.name = "LinkNetworkError";
				info?.onErrorCallback && info?.onErrorCallback(linkError);
			} else info?.cb && info?.cb();
		};
		if (link) {
			link.onerror = null;
			link.onload = null;
			safeWrapper(() => {
				const { needDeleteLink = true } = info;
				if (needDeleteLink) link?.parentNode && link.parentNode.removeChild(link);
			});
			if (prev) {
				const res = prev(event);
				onLinkCompleteCallback();
				return res;
			}
		}
		onLinkCompleteCallback();
	};
	link.onerror = onLinkComplete.bind(null, link.onerror);
	link.onload = onLinkComplete.bind(null, link.onload);
	timeoutId = setTimeout(() => {
		onLinkComplete(null, {
			type: "error",
			isTimeout: true
		});
	}, timeout);
	return {
		link,
		needAttach
	};
}
function loadScript(url, info) {
	const { attrs = {}, createScriptHook } = info;
	return new Promise((resolve, reject) => {
		const { script, needAttach } = createScript({
			url,
			cb: resolve,
			onErrorCallback: reject,
			attrs: {
				fetchpriority: "high",
				...attrs
			},
			createScriptHook,
			needDeleteScript: true
		});
		needAttach && document.head.appendChild(script);
	});
}

//#region src/getShortErrorMsg.ts
const getDocsUrl = (errorCode) => {
	return `View the docs to see how to solve: https://module-federation.io/guide/troubleshooting/${errorCode.split("-")[0].toLowerCase()}#${errorCode.toLowerCase()}`;
};
const getShortErrorMsg = (errorCode, errorDescMap, args, originalErrorMsg) => {
	const msg = [`${[errorDescMap[errorCode]]} #${errorCode}`];
	args && msg.push(`args: ${JSON.stringify(args)}`);
	msg.push(getDocsUrl(errorCode));
	originalErrorMsg && msg.push(`Original Error Message:\n ${originalErrorMsg}`);
	return msg.join("\n");
};

//#region src/browser.ts
function logAndReport(code, descMap, args, logger, originalErrorMsg, context) {
	return logger(getShortErrorMsg(code, descMap, args, originalErrorMsg));
}

//#region src/utils/logger.ts
const LOG_CATEGORY = "[ Federation Runtime ]";
const logger = createLogger(LOG_CATEGORY);
function assert(condition, msgOrCode, descMap, args, context) {
	if (!condition) error(msgOrCode);
}
function error(msgOrCode, descMap, args, originalErrorMsg, context) {
	if (descMap !== void 0) return logAndReport(msgOrCode, descMap, args ?? {}, (msg) => {
		throw new Error(`${LOG_CATEGORY}: ${msg}`);
	}, originalErrorMsg);
	const msg = msgOrCode;
	if (msg instanceof Error) {
		if (!msg.message.startsWith(LOG_CATEGORY)) msg.message = `${LOG_CATEGORY}: ${msg.message}`;
		throw msg;
	}
	throw new Error(`${LOG_CATEGORY}: ${msg}`);
}
function warn$1(msg) {
	if (msg instanceof Error) {
		if (!msg.message.startsWith(LOG_CATEGORY)) msg.message = `${LOG_CATEGORY}: ${msg.message}`;
		logger.warn(msg);
	} else logger.warn(msg);
}

//#region src/utils/tool.ts
function addUniqueItem(arr, item) {
	if (arr.findIndex((name) => name === item) === -1) arr.push(item);
	return arr;
}
function getFMId(remoteInfo) {
	if ("version" in remoteInfo && remoteInfo.version) return `${remoteInfo.name}:${remoteInfo.version}`;
	else if ("entry" in remoteInfo && remoteInfo.entry) return `${remoteInfo.name}:${remoteInfo.entry}`;
	else return `${remoteInfo.name}`;
}
function isRemoteInfoWithEntry(remote) {
	return typeof remote.entry !== "undefined";
}
function isPureRemoteEntry(remote) {
	return !remote.entry.includes(".json");
}
function isObject(val) {
	return val && typeof val === "object";
}
const objectToString = Object.prototype.toString;
function isPlainObject(val) {
	return objectToString.call(val) === "[object Object]";
}
function arrayOptions(options) {
	return Array.isArray(options) ? options : [options];
}
function getRemoteEntryInfoFromSnapshot(snapshot) {
	const defaultRemoteEntryInfo = {
		url: "",
		type: "global",
		globalName: ""
	};
	return "remoteEntry" in snapshot ? {
		url: snapshot.remoteEntry,
		type: snapshot.remoteEntryType,
		globalName: snapshot.globalName
	} : defaultRemoteEntryInfo;
}
const processModuleAlias = (name, subPath) => {
	let moduleName;
	if (name.endsWith("/")) moduleName = name.slice(0, -1);
	else moduleName = name;
	if (subPath.startsWith(".")) subPath = subPath.slice(1);
	moduleName = moduleName + subPath;
	return moduleName;
};

//#region src/global.ts
const MAX_PRELOADED_ASSETS = 2e3;
const CurrentGlobal = typeof globalThis === "object" ? globalThis : window;
const nativeGlobal = (() => {
	try {
		return document.defaultView;
	} catch {
		return CurrentGlobal;
	}
})();
const Global = nativeGlobal;
function definePropertyGlobalVal(target, key, val) {
	Object.defineProperty(target, key, {
		value: val,
		configurable: false,
		writable: true
	});
}
function includeOwnProperty(target, key) {
	return Object.hasOwnProperty.call(target, key);
}
if (!includeOwnProperty(CurrentGlobal, "__GLOBAL_LOADING_REMOTE_ENTRY__")) definePropertyGlobalVal(CurrentGlobal, "__GLOBAL_LOADING_REMOTE_ENTRY__", {});
const globalLoading = CurrentGlobal.__GLOBAL_LOADING_REMOTE_ENTRY__;
function setGlobalDefaultVal(target) {
	if (includeOwnProperty(target, "__VMOK__") && !includeOwnProperty(target, "__FEDERATION__")) definePropertyGlobalVal(target, "__FEDERATION__", target.__VMOK__);
	if (!includeOwnProperty(target, "__FEDERATION__")) {
		definePropertyGlobalVal(target, "__FEDERATION__", {
			__GLOBAL_PLUGIN__: [],
			__INSTANCES__: [],
			moduleInfo: {},
			__SHARE__: {},
			__MANIFEST_LOADING__: {},
			__PRELOADED_MAP__: /* @__PURE__ */ new Map(),
			__PRELOADED_ASSETS__: /* @__PURE__ */ new Set()
		});
		definePropertyGlobalVal(target, "__VMOK__", target.__FEDERATION__);
	}
	target.__FEDERATION__.__GLOBAL_PLUGIN__ ??= [];
	target.__FEDERATION__.__INSTANCES__ ??= [];
	target.__FEDERATION__.moduleInfo ??= {};
	target.__FEDERATION__.__SHARE__ ??= {};
	target.__FEDERATION__.__MANIFEST_LOADING__ ??= {};
	target.__FEDERATION__.__PRELOADED_MAP__ ??= /* @__PURE__ */ new Map();
	target.__FEDERATION__.__PRELOADED_ASSETS__ ??= /* @__PURE__ */ new Set();
}
setGlobalDefaultVal(CurrentGlobal);
setGlobalDefaultVal(nativeGlobal);
function setGlobalFederationInstance(FederationInstance) {
	CurrentGlobal.__FEDERATION__.__INSTANCES__.push(FederationInstance);
}
function getGlobalFederationConstructor() {
	return CurrentGlobal.__FEDERATION__.__DEBUG_CONSTRUCTOR__;
}
function setGlobalFederationConstructor(FederationConstructor, isDebug = isDebugMode()) {
	if (isDebug) {
		CurrentGlobal.__FEDERATION__.__DEBUG_CONSTRUCTOR__ = FederationConstructor;
		CurrentGlobal.__FEDERATION__.__DEBUG_CONSTRUCTOR_VERSION__ = "2.9.3";
	}
}
function getInfoWithoutType(target, key) {
	if (typeof key === "string") if (target[key]) return {
		value: target[key],
		key
	};
	else {
		const targetKeys = Object.keys(target);
		for (const targetKey of targetKeys) {
			const [targetTypeOrName, _] = targetKey.split(":");
			const nKey = `${targetTypeOrName}:${key}`;
			const typeWithKeyRes = target[nKey];
			if (typeWithKeyRes) return {
				value: typeWithKeyRes,
				key: nKey
			};
		}
		return {
			value: void 0,
			key
		};
	}
	else error(`getInfoWithoutType: "key" must be a string, got ${typeof key} (${JSON.stringify(key)}).`);
}
const getGlobalSnapshot = () => nativeGlobal.__FEDERATION__.moduleInfo;
const getTargetSnapshotInfoByModuleInfo = (moduleInfo, snapshot) => {
	const getModuleInfo = getInfoWithoutType(snapshot, getFMId(moduleInfo)).value;
	if (getModuleInfo && !getModuleInfo.version && "version" in moduleInfo && moduleInfo["version"]) getModuleInfo.version = moduleInfo["version"];
	if (getModuleInfo) return getModuleInfo;
	if ("version" in moduleInfo && moduleInfo["version"]) {
		const { version, ...resModuleInfo } = moduleInfo;
		const moduleKeyWithoutVersion = getFMId(resModuleInfo);
		const getModuleInfoWithoutVersion = getInfoWithoutType(nativeGlobal.__FEDERATION__.moduleInfo, moduleKeyWithoutVersion).value;
		if (getModuleInfoWithoutVersion?.version === version) return getModuleInfoWithoutVersion;
	}
};
const getGlobalSnapshotInfoByModuleInfo = (moduleInfo) => getTargetSnapshotInfoByModuleInfo(moduleInfo, nativeGlobal.__FEDERATION__.moduleInfo);
const setGlobalSnapshotInfoByModuleInfo = (remoteInfo, moduleDetailInfo) => {
	const moduleKey = getFMId(remoteInfo);
	nativeGlobal.__FEDERATION__.moduleInfo[moduleKey] = moduleDetailInfo;
	return nativeGlobal.__FEDERATION__.moduleInfo;
};
const addGlobalSnapshot = (moduleInfos) => {
	nativeGlobal.__FEDERATION__.moduleInfo = {
		...nativeGlobal.__FEDERATION__.moduleInfo,
		...moduleInfos
	};
	return () => {
		const keys = Object.keys(moduleInfos);
		for (const key of keys) delete nativeGlobal.__FEDERATION__.moduleInfo[key];
	};
};
const getRemoteEntryExports = (name, globalName) => {
	const remoteEntryKey = globalName || `__FEDERATION_${name}:custom__`;
	return {
		remoteEntryKey,
		entryExports: CurrentGlobal[remoteEntryKey]
	};
};
const getGlobalHostPlugins = () => nativeGlobal.__FEDERATION__.__GLOBAL_PLUGIN__;
const getPreloaded = (id) => CurrentGlobal.__FEDERATION__.__PRELOADED_MAP__.get(id);
const setPreloaded = (id) => CurrentGlobal.__FEDERATION__.__PRELOADED_MAP__.set(id, true);
const getPreloadedAsset = (url) => CurrentGlobal.__FEDERATION__.__PRELOADED_ASSETS__.has(url);
const setPreloadedAsset = (url) => {
	const preloadedAssets = CurrentGlobal.__FEDERATION__.__PRELOADED_ASSETS__;
	preloadedAssets.add(url);
	if (preloadedAssets.size > MAX_PRELOADED_ASSETS) {
		const oldestUrl = preloadedAssets.values().next().value;
		if (oldestUrl !== void 0) preloadedAssets.delete(oldestUrl);
	}
};

//#region src/utils/semver/constants.ts
const buildIdentifier = "[0-9A-Za-z-]+";
const build = `(?:\\+(${buildIdentifier}(?:\\.${buildIdentifier})*))`;
const numericIdentifier = "0|[1-9]\\d*";
const numericIdentifierLoose = "[0-9]+";
const nonNumericIdentifier = "\\d*[a-zA-Z-][a-zA-Z0-9-]*";
const preReleaseIdentifierLoose = `(?:${numericIdentifierLoose}|${nonNumericIdentifier})`;
const preReleaseLoose = `(?:-?(${preReleaseIdentifierLoose}(?:\\.${preReleaseIdentifierLoose})*))`;
const preReleaseIdentifier = `(?:${numericIdentifier}|${nonNumericIdentifier})`;
const preRelease = `(?:-(${preReleaseIdentifier}(?:\\.${preReleaseIdentifier})*))`;
const xRangeIdentifier = `${numericIdentifier}|x|X|\\*`;
const xRangePlain = `[v=\\s]*(${xRangeIdentifier})(?:\\.(${xRangeIdentifier})(?:\\.(${xRangeIdentifier})(?:${preRelease})?${build}?)?)?`;
const hyphenRange = `^\\s*(${xRangePlain})\\s+-\\s+(${xRangePlain})\\s*$`;
const loosePlain = `[v=\\s]*${`(${numericIdentifierLoose})\\.(${numericIdentifierLoose})\\.(${numericIdentifierLoose})`}${preReleaseLoose}?${build}?`;
const gtlt = "((?:<|>)?=?)";
const comparatorTrim = `(\\s*)${gtlt}\\s*(${loosePlain}|${xRangePlain})`;
const loneTilde = "(?:~>?)";
const tildeTrim = `(\\s*)${loneTilde}\\s+`;
const loneCaret = "(?:\\^)";
const caretTrim = `(\\s*)${loneCaret}\\s+`;
const star = "(<|>)?=?\\s*\\*";
const caret = `^${loneCaret}${xRangePlain}$`;
const fullPlain = `v?${`(${numericIdentifier})\\.(${numericIdentifier})\\.(${numericIdentifier})`}${preRelease}?${build}?`;
const tilde = `^${loneTilde}${xRangePlain}$`;
const xRange = `^${gtlt}\\s*${xRangePlain}$`;
const comparator = `^${gtlt}\\s*(${fullPlain})$|^$`;
const gte0 = "^\\s*>=\\s*0.0.0\\s*$";

//#region src/utils/semver/utils.ts
function parseRegex(source) {
	return new RegExp(source);
}
function isXVersion(version) {
	return !version || version.toLowerCase() === "x" || version === "*";
}
function pipe(...fns) {
	return (x) => fns.reduce((v, f) => f(v), x);
}
function extractComparator(comparatorString) {
	return comparatorString.match(parseRegex(comparator));
}
function combineVersion(major, minor, patch, preRelease) {
	const mainVersion = `${major}.${minor}.${patch}`;
	if (preRelease) return `${mainVersion}-${preRelease}`;
	return mainVersion;
}

//#region src/utils/semver/parser.ts
function parseHyphen(range) {
	return range.replace(parseRegex(hyphenRange), (_range, from, fromMajor, fromMinor, fromPatch, _fromPreRelease, _fromBuild, to, toMajor, toMinor, toPatch, toPreRelease) => {
		if (isXVersion(fromMajor)) from = "";
		else if (isXVersion(fromMinor)) from = `>=${fromMajor}.0.0`;
		else if (isXVersion(fromPatch)) from = `>=${fromMajor}.${fromMinor}.0`;
		else from = `>=${from}`;
		if (isXVersion(toMajor)) to = "";
		else if (isXVersion(toMinor)) to = `<${Number(toMajor) + 1}.0.0-0`;
		else if (isXVersion(toPatch)) to = `<${toMajor}.${Number(toMinor) + 1}.0-0`;
		else if (toPreRelease) to = `<=${toMajor}.${toMinor}.${toPatch}-${toPreRelease}`;
		else to = `<=${to}`;
		return `${from} ${to}`.trim();
	});
}
function parseComparatorTrim(range) {
	return range.replace(parseRegex(comparatorTrim), "$1$2$3");
}
function parseTildeTrim(range) {
	return range.replace(parseRegex(tildeTrim), "$1~");
}
function parseCaretTrim(range) {
	return range.replace(parseRegex(caretTrim), "$1^");
}
function parseCarets(range) {
	return range.trim().split(/\s+/).map((rangeVersion) => rangeVersion.replace(parseRegex(caret), (_, major, minor, patch, preRelease) => {
		if (isXVersion(major)) return "";
		else if (isXVersion(minor)) return `>=${major}.0.0 <${Number(major) + 1}.0.0-0`;
		else if (isXVersion(patch)) if (major === "0") return `>=${major}.${minor}.0 <${major}.${Number(minor) + 1}.0-0`;
		else return `>=${major}.${minor}.0 <${Number(major) + 1}.0.0-0`;
		else if (preRelease) if (major === "0") if (minor === "0") return `>=${major}.${minor}.${patch}-${preRelease} <${major}.${minor}.${Number(patch) + 1}-0`;
		else return `>=${major}.${minor}.${patch}-${preRelease} <${major}.${Number(minor) + 1}.0-0`;
		else return `>=${major}.${minor}.${patch}-${preRelease} <${Number(major) + 1}.0.0-0`;
		else {
			if (major === "0") if (minor === "0") return `>=${major}.${minor}.${patch} <${major}.${minor}.${Number(patch) + 1}-0`;
			else return `>=${major}.${minor}.${patch} <${major}.${Number(minor) + 1}.0-0`;
			return `>=${major}.${minor}.${patch} <${Number(major) + 1}.0.0-0`;
		}
	})).join(" ");
}
function parseTildes(range) {
	return range.trim().split(/\s+/).map((rangeVersion) => rangeVersion.replace(parseRegex(tilde), (_, major, minor, patch, preRelease) => {
		if (isXVersion(major)) return "";
		else if (isXVersion(minor)) return `>=${major}.0.0 <${Number(major) + 1}.0.0-0`;
		else if (isXVersion(patch)) return `>=${major}.${minor}.0 <${major}.${Number(minor) + 1}.0-0`;
		else if (preRelease) return `>=${major}.${minor}.${patch}-${preRelease} <${major}.${Number(minor) + 1}.0-0`;
		return `>=${major}.${minor}.${patch} <${major}.${Number(minor) + 1}.0-0`;
	})).join(" ");
}
function parseXRanges(range) {
	return range.split(/\s+/).map((rangeVersion) => rangeVersion.trim().replace(parseRegex(xRange), (ret, gtlt, major, minor, patch, preRelease) => {
		const isXMajor = isXVersion(major);
		const isXMinor = isXMajor || isXVersion(minor);
		const isXPatch = isXMinor || isXVersion(patch);
		if (gtlt === "=" && isXPatch) gtlt = "";
		preRelease = "";
		if (isXMajor) if (gtlt === ">" || gtlt === "<") return "<0.0.0-0";
		else return "*";
		else if (gtlt && isXPatch) {
			if (isXMinor) minor = 0;
			patch = 0;
			if (gtlt === ">") {
				gtlt = ">=";
				if (isXMinor) {
					major = Number(major) + 1;
					minor = 0;
					patch = 0;
				} else {
					minor = Number(minor) + 1;
					patch = 0;
				}
			} else if (gtlt === "<=") {
				gtlt = "<";
				if (isXMinor) major = Number(major) + 1;
				else minor = Number(minor) + 1;
			}
			if (gtlt === "<") preRelease = "-0";
			return `${gtlt + major}.${minor}.${patch}${preRelease}`;
		} else if (isXMinor) return `>=${major}.0.0${preRelease} <${Number(major) + 1}.0.0-0`;
		else if (isXPatch) return `>=${major}.${minor}.0${preRelease} <${major}.${Number(minor) + 1}.0-0`;
		return ret;
	})).join(" ");
}
function parseStar(range) {
	return range.trim().replace(parseRegex(star), "");
}
function parseGTE0(comparatorString) {
	return comparatorString.trim().replace(parseRegex(gte0), "");
}

//#region src/utils/semver/compare.ts
function compareAtom(rangeAtom, versionAtom) {
	rangeAtom = Number(rangeAtom) || rangeAtom;
	versionAtom = Number(versionAtom) || versionAtom;
	if (rangeAtom > versionAtom) return 1;
	if (rangeAtom === versionAtom) return 0;
	return -1;
}
function comparePreRelease(rangeAtom, versionAtom) {
	const { preRelease: rangePreRelease } = rangeAtom;
	const { preRelease: versionPreRelease } = versionAtom;
	if (rangePreRelease === void 0 && Boolean(versionPreRelease)) return 1;
	if (Boolean(rangePreRelease) && versionPreRelease === void 0) return -1;
	if (rangePreRelease === void 0 && versionPreRelease === void 0) return 0;
	for (let i = 0, n = rangePreRelease.length; i <= n; i++) {
		const rangeElement = rangePreRelease[i];
		const versionElement = versionPreRelease[i];
		if (rangeElement === versionElement) continue;
		if (rangeElement === void 0 && versionElement === void 0) return 0;
		if (!rangeElement) return 1;
		if (!versionElement) return -1;
		return compareAtom(rangeElement, versionElement);
	}
	return 0;
}
function compareVersion(rangeAtom, versionAtom) {
	return compareAtom(rangeAtom.major, versionAtom.major) || compareAtom(rangeAtom.minor, versionAtom.minor) || compareAtom(rangeAtom.patch, versionAtom.patch) || comparePreRelease(rangeAtom, versionAtom);
}
function eq(rangeAtom, versionAtom) {
	return rangeAtom.version === versionAtom.version;
}
function compare(rangeAtom, versionAtom) {
	switch (rangeAtom.operator) {
		case "":
		case "=": return eq(rangeAtom, versionAtom);
		case ">": return compareVersion(rangeAtom, versionAtom) < 0;
		case ">=": return eq(rangeAtom, versionAtom) || compareVersion(rangeAtom, versionAtom) < 0;
		case "<": return compareVersion(rangeAtom, versionAtom) > 0;
		case "<=": return eq(rangeAtom, versionAtom) || compareVersion(rangeAtom, versionAtom) > 0;
		case void 0: return true;
		default: return false;
	}
}

//#region src/utils/semver/index.ts
function parseComparatorString(range) {
	return pipe(parseCarets, parseTildes, parseXRanges, parseStar)(range);
}
function parseRange(range) {
	return pipe(parseHyphen, parseComparatorTrim, parseTildeTrim, parseCaretTrim)(range.trim()).split(/\s+/).join(" ");
}
function satisfy(version, range) {
	if (!version) return false;
	const extractedVersion = extractComparator(version);
	if (!extractedVersion) return false;
	const [, versionOperator, , versionMajor, versionMinor, versionPatch, versionPreRelease] = extractedVersion;
	const versionAtom = {
		operator: versionOperator,
		version: combineVersion(versionMajor, versionMinor, versionPatch, versionPreRelease),
		major: versionMajor,
		minor: versionMinor,
		patch: versionPatch,
		preRelease: versionPreRelease?.split(".")
	};
	const orRanges = range.split("||");
	for (const orRange of orRanges) {
		const trimmedOrRange = orRange.trim();
		if (!trimmedOrRange) return true;
		if (trimmedOrRange === "*" || trimmedOrRange === "x") return true;
		try {
			const parsedSubRange = parseRange(trimmedOrRange);
			if (!parsedSubRange.trim()) return true;
			const parsedComparatorString = parsedSubRange.split(" ").map((rangeVersion) => parseComparatorString(rangeVersion)).join(" ");
			if (!parsedComparatorString.trim()) return true;
			const comparators = parsedComparatorString.split(/\s+/).map((comparator) => parseGTE0(comparator)).filter(Boolean);
			if (comparators.length === 0) continue;
			let subRangeSatisfied = true;
			for (const comparator of comparators) {
				const extractedComparator = extractComparator(comparator);
				if (!extractedComparator) {
					subRangeSatisfied = false;
					break;
				}
				const [, rangeOperator, , rangeMajor, rangeMinor, rangePatch, rangePreRelease] = extractedComparator;
				if (!compare({
					operator: rangeOperator,
					version: combineVersion(rangeMajor, rangeMinor, rangePatch, rangePreRelease),
					major: rangeMajor,
					minor: rangeMinor,
					patch: rangePatch,
					preRelease: rangePreRelease?.split(".")
				}, versionAtom)) {
					subRangeSatisfied = false;
					break;
				}
			}
			if (subRangeSatisfied) return true;
		} catch (e) {
			console.error(`[semver] Error processing range part "${trimmedOrRange}":`, e);
			continue;
		}
	}
	return false;
}

//#region src/constant.ts
const DEFAULT_SCOPE = "default";
const DEFAULT_REMOTE_TYPE = "global";

//#region src/utils/share.ts
function formatShare(shareArgs, from, name, shareStrategy) {
	let get;
	if ("get" in shareArgs) get = shareArgs.get;
	else if ("lib" in shareArgs) get = () => Promise.resolve(shareArgs.lib);
	else get = () => Promise.resolve(() => {
		error(`Cannot get shared "${name}" from "${from}": neither "get" nor "lib" is provided in the share config.`);
	});
	if (shareArgs.shareConfig?.eager && shareArgs.treeShaking?.mode) error(`Invalid shared config for "${name}" from "${from}": cannot use both "eager: true" and "treeShaking.mode" simultaneously. Choose one strategy.`);
	return {
		deps: [],
		useIn: [],
		from,
		loading: null,
		...shareArgs,
		shareConfig: {
			requiredVersion: `^${shareArgs.version}`,
			singleton: false,
			eager: false,
			strictVersion: false,
			...shareArgs.shareConfig
		},
		get,
		loaded: shareArgs?.loaded || "lib" in shareArgs ? true : void 0,
		version: shareArgs.version ?? "0",
		scope: Array.isArray(shareArgs.scope) ? shareArgs.scope : [shareArgs.scope ?? "default"],
		strategy: (shareArgs.strategy ?? shareStrategy) || "version-first",
		treeShaking: shareArgs.treeShaking ? {
			...shareArgs.treeShaking,
			mode: shareArgs.treeShaking.mode ?? "server-calc",
			status: shareArgs.treeShaking.status ?? TreeShakingStatus.UNKNOWN,
			useIn: []
		} : void 0
	};
}
function formatShareConfigs(prevOptions, newOptions) {
	const shareArgs = newOptions.shared || {};
	const from = newOptions.name;
	const newShareInfos = Object.keys(shareArgs).reduce((res, pkgName) => {
		const arrayShareArgs = arrayOptions(shareArgs[pkgName]);
		res[pkgName] = res[pkgName] || [];
		arrayShareArgs.forEach((shareConfig) => {
			res[pkgName].push(formatShare(shareConfig, from, pkgName, newOptions.shareStrategy));
		});
		return res;
	}, {});
	const allShareInfos = { ...prevOptions.shared };
	Object.keys(newShareInfos).forEach((shareKey) => {
		if (!allShareInfos[shareKey]) allShareInfos[shareKey] = newShareInfos[shareKey];
		else newShareInfos[shareKey].forEach((newUserSharedOptions) => {
			if (!allShareInfos[shareKey].find((sharedVal) => sharedVal.version === newUserSharedOptions.version)) allShareInfos[shareKey].push(newUserSharedOptions);
		});
	});
	return {
		allShareInfos,
		newShareInfos
	};
}
function shouldUseTreeShaking(treeShaking, usedExports) {
	if (!treeShaking) return false;
	const { status, mode } = treeShaking;
	if (status === TreeShakingStatus.NO_USE) return false;
	if (status === TreeShakingStatus.CALCULATED) return true;
	if (mode === "runtime-infer") {
		if (!usedExports) return true;
		return isMatchUsedExports(treeShaking, usedExports);
	}
	return false;
}
/**
* compare version a and b, return true if a is less than b
*/
function versionLt(a, b) {
	const transformInvalidVersion = (version) => {
		if (!Number.isNaN(Number(version))) {
			const splitArr = version.split(".");
			let validVersion = version;
			for (let i = 0; i < 3 - splitArr.length; i++) validVersion += ".0";
			return validVersion;
		}
		return version;
	};
	if (satisfy(transformInvalidVersion(a), `<=${transformInvalidVersion(b)}`)) return true;
	else return false;
}
const findVersion = (shareVersionMap, cb) => {
	const callback = cb || function(prev, cur) {
		return versionLt(prev, cur);
	};
	return Object.keys(shareVersionMap).reduce((prev, cur) => {
		if (!prev) return cur;
		if (callback(prev, cur)) return cur;
		if (prev === "0") return cur;
		return prev;
	}, 0);
};
const isLoaded = (shared) => {
	return Boolean(shared.loaded) || typeof shared.lib === "function";
};
const isLoading = (shared) => {
	return Boolean(shared.loading);
};
const isMatchUsedExports = (treeShaking, usedExports) => {
	if (!treeShaking || !usedExports) return false;
	const { usedExports: treeShakingUsedExports } = treeShaking;
	if (!treeShakingUsedExports) return false;
	if (usedExports.every((e) => treeShakingUsedExports.includes(e))) return true;
	return false;
};
function findSingletonVersionOrderByVersion(shareScopeMap, scope, pkgName, treeShaking) {
	const versions = shareScopeMap[scope][pkgName];
	let version = "";
	let useTreesShaking = shouldUseTreeShaking(treeShaking);
	const callback = function(prev, cur) {
		if (useTreesShaking) {
			if (!versions[prev].treeShaking) return true;
			if (!versions[cur].treeShaking) return false;
			return !isLoaded(versions[prev].treeShaking) && versionLt(prev, cur);
		}
		return !isLoaded(versions[prev]) && versionLt(prev, cur);
	};
	if (useTreesShaking) {
		version = findVersion(shareScopeMap[scope][pkgName], callback);
		if (version) return {
			version,
			useTreesShaking
		};
		useTreesShaking = false;
	}
	return {
		version: findVersion(shareScopeMap[scope][pkgName], callback),
		useTreesShaking
	};
}
const isLoadingOrLoaded = (shared) => {
	return isLoaded(shared) || isLoading(shared);
};
function findSingletonVersionOrderByLoaded(shareScopeMap, scope, pkgName, treeShaking) {
	const versions = shareScopeMap[scope][pkgName];
	let version = "";
	let useTreesShaking = shouldUseTreeShaking(treeShaking);
	const callback = function(prev, cur) {
		if (useTreesShaking) {
			if (!versions[prev].treeShaking) return true;
			if (!versions[cur].treeShaking) return false;
			if (isLoadingOrLoaded(versions[cur].treeShaking)) if (isLoadingOrLoaded(versions[prev].treeShaking)) return Boolean(versionLt(prev, cur));
			else return true;
			if (isLoadingOrLoaded(versions[prev].treeShaking)) return false;
		}
		if (isLoadingOrLoaded(versions[cur])) if (isLoadingOrLoaded(versions[prev])) return Boolean(versionLt(prev, cur));
		else return true;
		if (isLoadingOrLoaded(versions[prev])) return false;
		return versionLt(prev, cur);
	};
	if (useTreesShaking) {
		version = findVersion(shareScopeMap[scope][pkgName], callback);
		if (version) return {
			version,
			useTreesShaking
		};
		useTreesShaking = false;
	}
	return {
		version: findVersion(shareScopeMap[scope][pkgName], callback),
		useTreesShaking
	};
}
function getFindShareFunction(strategy) {
	if (strategy === "loaded-first") return findSingletonVersionOrderByLoaded;
	return findSingletonVersionOrderByVersion;
}
function getRegisteredShare(localShareScopeMap, pkgName, shareInfo, resolveShare, loadContext) {
	if (!localShareScopeMap) return;
	const { shareConfig, scope = DEFAULT_SCOPE, strategy, treeShaking } = shareInfo;
	const scopes = Array.isArray(scope) ? scope : [scope];
	for (const sc of scopes) if (shareConfig && localShareScopeMap[sc] && localShareScopeMap[sc][pkgName]) {
		const { requiredVersion } = shareConfig;
		const { version: maxOrSingletonVersion, useTreesShaking } = getFindShareFunction(strategy)(localShareScopeMap, sc, pkgName, treeShaking);
		const defaultResolver = () => {
			const shared = localShareScopeMap[sc][pkgName][maxOrSingletonVersion];
			if (shareConfig.singleton) {
				if (typeof requiredVersion === "string" && !satisfy(maxOrSingletonVersion, requiredVersion)) {
					const msg = `Version ${maxOrSingletonVersion} from ${maxOrSingletonVersion && shared.from} of shared singleton module ${pkgName} does not satisfy the requirement of ${shareInfo.from} which needs ${requiredVersion})`;
					if (shareConfig.strictVersion) error(msg);
					else warn$1(msg);
				}
				return {
					shared,
					useTreesShaking
				};
			} else {
				if (requiredVersion === false || requiredVersion === "*") return {
					shared,
					useTreesShaking
				};
				if (satisfy(maxOrSingletonVersion, requiredVersion)) return {
					shared,
					useTreesShaking
				};
				const _usedTreeShaking = shouldUseTreeShaking(treeShaking);
				if (_usedTreeShaking) for (const [versionKey, versionValue] of Object.entries(localShareScopeMap[sc][pkgName])) {
					if (!shouldUseTreeShaking(versionValue.treeShaking, treeShaking?.usedExports)) continue;
					if (satisfy(versionKey, requiredVersion)) return {
						shared: versionValue,
						useTreesShaking: _usedTreeShaking
					};
				}
				for (const [versionKey, versionValue] of Object.entries(localShareScopeMap[sc][pkgName])) if (satisfy(versionKey, requiredVersion)) return {
					shared: versionValue,
					useTreesShaking: false
				};
			}
		};
		const params = {
			shareScopeMap: localShareScopeMap,
			scope: sc,
			pkgName,
			version: maxOrSingletonVersion,
			GlobalFederation: Global.__FEDERATION__,
			shareInfo,
			resolver: defaultResolver,
			loadContext
		};
		return (resolveShare.emit(params) || params).resolver();
	}
}
function getGlobalShareScope() {
	return Global.__FEDERATION__.__SHARE__;
}
function getTargetSharedOptions(options) {
	const { pkgName, extraOptions, shareInfos } = options;
	const defaultResolver = (sharedOptions) => {
		if (!sharedOptions) return;
		const shareVersionMap = {};
		sharedOptions.forEach((shared) => {
			shareVersionMap[shared.version] = shared;
		});
		const callback = function(prev, cur) {
			return !isLoaded(shareVersionMap[prev]) && versionLt(prev, cur);
		};
		return shareVersionMap[findVersion(shareVersionMap, callback)];
	};
	const resolver = extraOptions?.resolver ?? defaultResolver;
	const isPlainObject = (val) => {
		return val !== null && typeof val === "object" && !Array.isArray(val);
	};
	const merge = (...sources) => {
		const out = {};
		for (const src of sources) {
			if (!src) continue;
			for (const [key, value] of Object.entries(src)) {
				const prev = out[key];
				if (isPlainObject(prev) && isPlainObject(value)) out[key] = merge(prev, value);
				else if (value !== void 0) out[key] = value;
			}
		}
		return out;
	};
	return merge(resolver(shareInfos[pkgName]), extraOptions?.customShareInfo);
}
const addUseIn = (shared, from) => {
	if (!shared.useIn) shared.useIn = [];
	addUniqueItem(shared.useIn, from);
};
function directShare(shared, useTreesShaking) {
	if (useTreesShaking && shared.treeShaking) return shared.treeShaking;
	return shared;
}

//#region src/utils/manifest.ts
function composeRemoteRequestId(remoteName, expose) {
	if (!expose || expose === ".") return remoteName;
	return `${remoteName}/${expose.replace(/^\.\//, "")}`;
}
function matchRemoteWithNameAndExpose(remotes, id) {
	for (const remote of remotes) {
		const isNameMatched = id.startsWith(remote.name);
		let expose = id.replace(remote.name, "");
		if (isNameMatched) {
			if (expose.startsWith("/")) {
				const pkgNameOrAlias = remote.name;
				expose = `.${expose}`;
				return {
					pkgNameOrAlias,
					expose,
					remote
				};
			} else if (expose === "") return {
				pkgNameOrAlias: remote.name,
				expose: ".",
				remote
			};
		}
		const isAliasMatched = remote.alias && id.startsWith(remote.alias);
		let exposeWithAlias = remote.alias && id.replace(remote.alias, "");
		if (remote.alias && isAliasMatched) {
			if (exposeWithAlias && exposeWithAlias.startsWith("/")) {
				const pkgNameOrAlias = remote.alias;
				exposeWithAlias = `.${exposeWithAlias}`;
				return {
					pkgNameOrAlias,
					expose: exposeWithAlias,
					remote
				};
			} else if (exposeWithAlias === "") return {
				pkgNameOrAlias: remote.alias,
				expose: ".",
				remote
			};
		}
	}
}
function matchRemote(remotes, nameOrAlias) {
	for (const remote of remotes) {
		if (nameOrAlias === remote.name) return remote;
		if (remote.alias && nameOrAlias === remote.alias) return remote;
	}
}

//#region src/error-codes.ts
const RUNTIME_001 = "RUNTIME-001";
const RUNTIME_002 = "RUNTIME-002";
const RUNTIME_003 = "RUNTIME-003";
const RUNTIME_004 = "RUNTIME-004";
const RUNTIME_005 = "RUNTIME-005";
const RUNTIME_006 = "RUNTIME-006";
const RUNTIME_007 = "RUNTIME-007";
const RUNTIME_008 = "RUNTIME-008";
const RUNTIME_009 = "RUNTIME-009";
const RUNTIME_010 = "RUNTIME-010";
const RUNTIME_011 = "RUNTIME-011";
const RUNTIME_012 = "RUNTIME-012";
const RUNTIME_013 = "RUNTIME-013";
const RUNTIME_014 = "RUNTIME-014";
const RUNTIME_015 = "RUNTIME-015";

//#region src/desc.ts
const runtimeDescMap = {
	[RUNTIME_001]: "Failed to get remoteEntry exports.",
	[RUNTIME_002]: "The remote entry interface does not contain \"init\"",
	[RUNTIME_003]: "Failed to get manifest.",
	[RUNTIME_004]: "Failed to locate remote.",
	[RUNTIME_005]: "Invalid loadShareSync function call from bundler runtime",
	[RUNTIME_006]: "Invalid loadShareSync function call from runtime",
	[RUNTIME_007]: "Failed to get remote snapshot.",
	[RUNTIME_008]: "Failed to load script resources.",
	[RUNTIME_009]: "Please call createInstance first.",
	[RUNTIME_010]: "The name option cannot be changed after initialization. If you want to create a new instance with a different name, please use \"createInstance\" api.",
	[RUNTIME_011]: "The remoteEntry URL is missing from the remote snapshot.",
	[RUNTIME_012]: "The getter for the shared module is not a function. This may be caused by setting \"shared.import: false\" without the host providing the corresponding lib.",
	[RUNTIME_013]: "The manifest is not a valid Module Federation manifest.",
	[RUNTIME_014]: "The remote does not expose the requested module.",
	[RUNTIME_015]: "Remote container initialization failed."
};
({
	...runtimeDescMap});

const importCallback = ".then(callbacks[0]).catch(callbacks[1])";
const remoteEntryLoadingOrigins = /* @__PURE__ */ new WeakMap();
const esmRemoteEntryLoadErrorMessages = [
  "Failed to fetch dynamically imported module",
  "Importing a module script failed",
  "error loading dynamically imported module"
];
function isEsmRemoteEntryLoadError(err) {
  if (!(err instanceof TypeError)) return false;
  return esmRemoteEntryLoadErrorMessages.some((loadErrorMessage) => err.message.includes(loadErrorMessage));
}
function isEsmRemoteType(type) {
  return type === "esm" || type === "module";
}
async function loadEsmEntry({ entry, remoteEntryExports, name, getEntryUrl }) {
  return new Promise((resolve, reject) => {
    const rejectEntry = (loadError) => {
      if (isEsmRemoteEntryLoadError(loadError)) {
        const originalMsg = loadError instanceof Error ? loadError.message : String(loadError);
        try {
          error(RUNTIME_008, runtimeDescMap, {
            remoteName: name,
            resourceUrl: url
          }, originalMsg);
        } catch (runtimeError) {
          reject(runtimeError);
          return;
        }
      }
      reject(loadError);
    };
    const url = getEntryUrl ? getEntryUrl(entry) : entry;
    try {
      if (!remoteEntryExports) if (typeof FEDERATION_ALLOW_NEW_FUNCTION !== "undefined") new Function("callbacks", `import("${url}")${importCallback}`)([resolve, rejectEntry]);
      else import(
        /* webpackIgnore: true */
        /* @vite-ignore */
        url
      ).then(resolve).catch(rejectEntry);
      else resolve(remoteEntryExports);
    } catch (e) {
      error(`Failed to load ESM entry from "${url}". ${e instanceof Error ? e.message : String(e)}`);
    }
  });
}
async function loadSystemJsEntry({ entry, remoteEntryExports }) {
  return new Promise((resolve, reject) => {
    try {
      if (!remoteEntryExports) if (typeof __system_context__ === "undefined") System.import(entry).then(resolve).catch(reject);
      else new Function("callbacks", `System.import("${entry}")${importCallback}`)([resolve, reject]);
      else resolve(remoteEntryExports);
    } catch (e) {
      error(`Failed to load SystemJS entry from "${entry}". ${e instanceof Error ? e.message : String(e)}`);
    }
  });
}
function handleRemoteEntryLoaded(name, globalName, entry) {
  const { remoteEntryKey, entryExports } = getRemoteEntryExports(name, globalName);
  if (!entryExports) error(RUNTIME_001, runtimeDescMap, {
    remoteName: name,
    remoteEntryUrl: entry,
    remoteEntryKey
  });
  return entryExports;
}
async function loadEntryScript({ name, globalName, entry, remoteInfo, loaderHook, getEntryUrl, resourceContext }) {
  const { entryExports: remoteEntryExports } = getRemoteEntryExports(name, globalName);
  if (remoteEntryExports) return remoteEntryExports;
  const url = getEntryUrl ? getEntryUrl(entry) : entry;
  return loadScript(url, {
    attrs: {},
    createScriptHook: (url2, attrs) => {
      const res = loaderHook.lifecycle.createScript.emit({
        url: url2,
        attrs,
        remoteInfo,
        resourceContext: resourceContext ? {
          ...resourceContext,
          url: url2
        } : void 0
      });
      if (!res) return;
      if (res instanceof HTMLScriptElement) return res;
      if ("script" in res || "timeout" in res) return res;
    }
  }).then(() => {
    return handleRemoteEntryLoaded(name, globalName, entry);
  }, (loadError) => {
    const originalMsg = loadError instanceof Error ? loadError.message : String(loadError);
    error(RUNTIME_008, runtimeDescMap, {
      remoteName: name,
      resourceUrl: url
    }, originalMsg);
  });
}
async function loadEntryDom({ remoteInfo, remoteEntryExports, loaderHook, getEntryUrl, resourceContext }) {
  const { entry, entryGlobalName: globalName, name, type } = remoteInfo;
  if (isEsmRemoteType(type)) return loadEsmEntry({
    entry,
    remoteEntryExports,
    name,
    getEntryUrl
  });
  if (type === "system") return loadSystemJsEntry({
    entry,
    remoteEntryExports
  });
  return loadEntryScript({
    entry,
    globalName,
    name,
    remoteInfo,
    loaderHook,
    getEntryUrl,
    resourceContext
  });
}
function getRemoteEntryUniqueKey(remoteInfo) {
  const { entry, name } = remoteInfo;
  return composeKeyWithSeparator(name, entry);
}
async function getRemoteEntry(params) {
  const { origin, remoteEntryExports, remoteInfo, getEntryUrl, resourceContext, _inErrorHandling = false } = params;
  const uniqueKey = getRemoteEntryUniqueKey(remoteInfo);
  if (remoteEntryExports) {
    await origin.loaderHook.lifecycle.afterLoadEntry.emit({
      origin,
      remoteInfo,
      remoteEntryExports,
      resourceContext,
      cached: true
    });
    return remoteEntryExports;
  }
  if (!globalLoading[uniqueKey]) {
    const loadEntryHook = origin.remoteHandler.hooks.lifecycle.loadEntry;
    const loaderHook = origin.loaderHook;
    const loading = loadEntryHook.emit({
      origin,
      loaderHook,
      remoteInfo,
      remoteEntryExports,
      resourceContext
    }).then((res) => {
      if (res) return res;
      return loadEntryDom({
        remoteInfo,
        remoteEntryExports,
        loaderHook,
        getEntryUrl,
        resourceContext
      }) ;
    }).then(async (res) => {
      await origin.loaderHook.lifecycle.afterLoadEntry.emit({
        origin,
        remoteInfo,
        remoteEntryExports: res,
        resourceContext
      });
      return res;
    }).catch(async (loadError) => {
      const isScriptExecutionError = loadError instanceof Error && loadError.message.includes("ScriptExecutionError");
      if (loadError instanceof Error && loadError.message.includes(RUNTIME_008) && !isScriptExecutionError && !_inErrorHandling) {
        const wrappedGetRemoteEntry = (params2) => {
          return getRemoteEntry({
            ...params2,
            _inErrorHandling: true
          });
        };
        const recoveredRemoteEntryExports = await origin.loaderHook.lifecycle.loadEntryError.emit({
          getRemoteEntry: wrappedGetRemoteEntry,
          origin,
          remoteInfo,
          remoteEntryExports,
          globalLoading,
          uniqueKey
        });
        if (recoveredRemoteEntryExports) {
          await origin.loaderHook.lifecycle.afterLoadEntry.emit({
            origin,
            remoteInfo,
            remoteEntryExports: recoveredRemoteEntryExports,
            resourceContext,
            error: loadError,
            recovered: true
          });
          return recoveredRemoteEntryExports;
        }
      }
      await origin.loaderHook.lifecycle.afterLoadEntry.emit({
        origin,
        remoteInfo,
        resourceContext,
        error: loadError
      });
      throw loadError;
    });
    globalLoading[uniqueKey] = loading;
    loading.then(void 0, () => {
      if (globalLoading[uniqueKey] === loading) delete globalLoading[uniqueKey];
    });
    remoteEntryLoadingOrigins.set(loading, origin);
  }
  const remoteEntryLoading = globalLoading[uniqueKey];
  if (remoteEntryLoadingOrigins.get(remoteEntryLoading) !== origin) try {
    const result = await remoteEntryLoading;
    await origin.loaderHook.lifecycle.afterLoadEntry.emit({
      origin,
      remoteInfo,
      remoteEntryExports: result,
      resourceContext
    });
    return result;
  } catch (loadError) {
    await origin.loaderHook.lifecycle.afterLoadEntry.emit({
      origin,
      remoteInfo,
      resourceContext,
      error: loadError
    });
    throw loadError;
  }
  return remoteEntryLoading;
}
function getRemoteInfo(remote) {
  return {
    ...remote,
    entry: "entry" in remote ? remote.entry : "",
    type: remote.type || DEFAULT_REMOTE_TYPE,
    entryGlobalName: remote.entryGlobalName || remote.name,
    shareScope: remote.shareScope || DEFAULT_SCOPE
  };
}

//#region src/utils/env.ts
function getBuilderId() {
	return typeof FEDERATION_BUILD_IDENTIFIER !== "undefined" ? FEDERATION_BUILD_IDENTIFIER : "";
}

//#region src/utils/plugin.ts
function getPluginsToRegister(plugins) {
	const pluginsByName = /* @__PURE__ */ new Map();
	[...plugins || [], ...getGlobalHostPlugins()].forEach((plugin) => {
		if (!plugin) return;
		assert(isPlainObject(plugin), "Plugin configuration is invalid.");
		assert(plugin.name, "A name must be provided by the plugin.");
		if (!pluginsByName.has(plugin.name)) pluginsByName.set(plugin.name, plugin);
	});
	return Array.from(pluginsByName.values());
}
function getInstancePlugin(plugin, instanceHooks) {
	if (instanceHooks === void 0) return plugin;
	return {
		...instanceHooks,
		name: plugin.name,
		version: plugin.version
	};
}
function registerPlugins(plugins, instance) {
	const registeredPlugins = /* @__PURE__ */ new Map();
	instance.options.plugins.forEach((plugin) => {
		if (plugin) registeredPlugins.set(plugin.name, plugin);
	});
	const hookInstances = [
		instance.hooks,
		instance.remoteHandler.hooks,
		instance.sharedHandler.hooks,
		instance.snapshotHandler.hooks,
		instance.loaderHook,
		instance.bridgeHook
	];
	getPluginsToRegister(plugins).forEach((plugin) => {
		registeredPlugins.set(plugin.name, plugin);
		if (instance.hooks.registerPlugins[plugin.name]) return;
		const instancePlugin = getInstancePlugin(plugin, plugin.apply?.(instance));
		hookInstances.forEach((hookInstance) => {
			hookInstance.applyPlugin(instancePlugin);
		});
	});
	return Array.from(registeredPlugins.values());
}

//#region src/utils/context.ts
function remoteToEntry(r) {
	return {
		name: r.name,
		alias: r.alias,
		entry: "entry" in r ? r.entry : void 0,
		version: "version" in r ? r.version : void 0,
		type: r.type,
		entryGlobalName: r.entryGlobalName,
		shareScope: r.shareScope
	};
}
/**
* Build a partial MFContext from runtime Options.
* Used to enrich diagnostic entries with host context at error sites.
*/
function optionsToMFContext(options) {
	const shared = {};
	for (const [pkgName, versions] of Object.entries(options.shared)) {
		const first = versions[0];
		if (first) shared[pkgName] = {
			version: first.version,
			singleton: first.shareConfig?.singleton,
			requiredVersion: first.shareConfig?.requiredVersion === false ? false : first.shareConfig?.requiredVersion,
			eager: first.eager,
			strictVersion: first.shareConfig?.strictVersion
		};
	}
	return {
		project: {
			name: options.name,
			mfRole: options.remotes?.length > 0 ? "host" : "unknown"
		},
		mfConfig: {
			name: options.name,
			remotes: options.remotes?.map(remoteToEntry) ?? [],
			shared
		}
	};
}

//#region src/utils/preload.ts
function defaultPreloadArgs(preloadConfig) {
	return {
		resourceCategory: "sync",
		share: true,
		depsRemote: true,
		recordPreloadedAssets: true,
		...preloadConfig
	};
}
function formatPreloadArgs(remotes, preloadArgs) {
	return preloadArgs.map((args) => {
		const remoteInfo = matchRemote(remotes, args.nameOrAlias);
		assert(remoteInfo, `Unable to preload ${args.nameOrAlias} as it is not included in ${!remoteInfo && safeToString({
			remoteInfo,
			remotes
		})}`);
		return {
			remote: remoteInfo,
			preloadConfig: defaultPreloadArgs(args)
		};
	});
}
function normalizePreloadExposes(exposes) {
	if (!exposes) return [];
	return exposes.map((expose) => {
		if (expose === ".") return expose;
		if (expose.startsWith("./")) return expose.replace("./", "");
		return expose;
	});
}
function isTimeoutError(error) {
	if (!(error instanceof Error)) return false;
	return error.message.includes("timed out") || error.name.includes("Timeout");
}
function createAssetResult(context, url, status, error) {
	return {
		url,
		status,
		resourceType: context.resourceType,
		initiator: context.initiator,
		id: context.id,
		error
	};
}
function preloadAssetOnce(context, url, recordPreloadedAssets, preload) {
	if (!recordPreloadedAssets) return preload();
	if (getPreloadedAsset(url)) return Promise.resolve(createAssetResult(context, url, "cached"));
	setPreloadedAsset(url);
	return preload();
}
async function waitForRemoteEntryPreload(host, remoteInfo, entryRemoteInfo, context) {
	const cachedRemote = host.moduleCache.get(entryRemoteInfo.name);
	const url = entryRemoteInfo.entry;
	if (cachedRemote?.remoteEntryExports) return createAssetResult(context, url, "cached");
	try {
		if (!await getRemoteEntry({
			origin: host,
			remoteInfo: entryRemoteInfo,
			remoteEntryExports: cachedRemote?.remoteEntryExports,
			resourceContext: {
				...context,
				url
			}
		})) throw new Error(`Failed to load remoteEntry "${url}".`);
		return createAssetResult(context, url, "success");
	} catch (error) {
		return createAssetResult(context, url, isTimeoutError(error) ? "timeout" : "error", error);
	}
}
function waitForLinkPreload({ host, remoteInfo, url, attrs, context, needDeleteLink }) {
	return new Promise((resolve) => {
		const { link, needAttach } = createLink({
			url,
			cb: () => {
				resolve(createAssetResult(context, url, needAttach ? "success" : "cached"));
			},
			onErrorCallback: (error) => {
				resolve(createAssetResult(context, url, isTimeoutError(error) ? "timeout" : "error", error));
			},
			attrs,
			createLinkHook: (hookUrl, hookAttrs) => {
				const res = host.loaderHook.lifecycle.createLink.emit({
					url: hookUrl,
					attrs: hookAttrs,
					remoteInfo,
					resourceContext: {
						...context,
						url: hookUrl
					}
				});
				if (res instanceof HTMLLinkElement) return res;
				return res;
			},
			needDeleteLink
		});
		needAttach && document.head.appendChild(link);
	});
}
function waitForScriptPreload({ host, remoteInfo, url, attrs, context }) {
	return new Promise((resolve) => {
		const { script, needAttach } = createScript({
			url,
			cb: () => {
				resolve(createAssetResult(context, url, needAttach ? "success" : "cached"));
			},
			onErrorCallback: (error) => {
				resolve(createAssetResult(context, url, isTimeoutError(error) ? "timeout" : "error", error));
			},
			attrs,
			createScriptHook: (hookUrl, hookAttrs) => {
				const res = host.loaderHook.lifecycle.createScript.emit({
					url: hookUrl,
					attrs: hookAttrs,
					remoteInfo,
					resourceContext: {
						...context,
						url: hookUrl
					}
				});
				if (res instanceof HTMLScriptElement) return res;
				return res;
			},
			needDeleteScript: true
		});
		needAttach && document.head.appendChild(script);
	});
}
function createResourceContext(baseContext, resourceType) {
	return {
		...baseContext,
		resourceType
	};
}
function preloadAssets(remoteInfo, host, assets, useLinkPreload = true, baseContext = {
	initiator: "preloadRemote",
	id: remoteInfo.name
}, recordPreloadedAssets = true) {
	const { cssAssets, jsAssetsWithoutEntry, entryAssets } = assets;
	const results = [];
	if (host.options.inBrowser) {
		entryAssets.forEach((asset) => {
			const { moduleInfo: entryRemoteInfo } = asset;
			results.push(waitForRemoteEntryPreload(host, remoteInfo, entryRemoteInfo, createResourceContext(baseContext, "remoteEntry")));
		});
		if (useLinkPreload) {
			const defaultAttrs = {
				rel: "preload",
				as: "style"
			};
			cssAssets.forEach((cssUrl) => {
				const context = createResourceContext(baseContext, "css");
				results.push(preloadAssetOnce(context, cssUrl, recordPreloadedAssets, () => waitForLinkPreload({
					host,
					remoteInfo,
					url: cssUrl,
					attrs: defaultAttrs,
					context
				})));
			});
		} else {
			const defaultAttrs = {
				rel: "stylesheet",
				type: "text/css"
			};
			cssAssets.forEach((cssUrl) => {
				const context = createResourceContext(baseContext, "css");
				results.push(preloadAssetOnce(context, cssUrl, recordPreloadedAssets, () => waitForLinkPreload({
					host,
					remoteInfo,
					url: cssUrl,
					attrs: defaultAttrs,
					needDeleteLink: false,
					context
				})));
			});
		}
		let preloadJsAsset = waitForScriptPreload;
		let defaultAttrs = {
			fetchpriority: "high",
			type: "text/javascript"
		};
		if (useLinkPreload) {
			preloadJsAsset = waitForLinkPreload;
			defaultAttrs = {
				rel: "preload",
				as: "script"
			};
		} else if (isEsmRemoteType(remoteInfo.type)) {
			preloadJsAsset = waitForLinkPreload;
			defaultAttrs = {
				rel: "modulepreload",
				fetchpriority: "high"
			};
		}
		jsAssetsWithoutEntry.forEach((jsUrl) => {
			const context = createResourceContext(baseContext, "js");
			results.push(preloadAssetOnce(context, jsUrl, recordPreloadedAssets, () => preloadJsAsset({
				host,
				remoteInfo,
				url: jsUrl,
				attrs: defaultAttrs,
				context
			})));
		});
	}
	return Promise.all(results);
}

//#region src/helpers.ts
const ShareUtils = {
	getRegisteredShare,
	getGlobalShareScope
};
var helpers_default = {
	share: ShareUtils};

//#region src/module/index.ts
function getAvailableExposeNames(remoteSnapshot) {
	if (!remoteSnapshot || !("modules" in remoteSnapshot) || !Array.isArray(remoteSnapshot.modules)) return;
	const exposes = remoteSnapshot.modules.map((module) => module.moduleName).filter(Boolean);
	return exposes.length ? exposes.join(",") : void 0;
}
function createRemoteEntryInitOptions(remoteInfo, hostShareScopeMap, rawInitScope) {
	const localShareScopeMap = hostShareScopeMap;
	const shareScopeKeys = Array.isArray(remoteInfo.shareScope) ? remoteInfo.shareScope : [remoteInfo.shareScope];
	if (!shareScopeKeys.length) shareScopeKeys.push("default");
	shareScopeKeys.forEach((shareScopeKey) => {
		if (!localShareScopeMap[shareScopeKey]) localShareScopeMap[shareScopeKey] = {};
	});
	const remoteEntryInitOptions = {
		version: remoteInfo.version || "",
		shareScopeKeys: Array.isArray(remoteInfo.shareScope) ? shareScopeKeys : remoteInfo.shareScope || "default"
	};
	Object.defineProperty(remoteEntryInitOptions, "shareScopeMap", {
		value: localShareScopeMap,
		enumerable: false
	});
	return {
		remoteEntryInitOptions,
		shareScope: localShareScopeMap[shareScopeKeys[0]],
		initScope: rawInitScope ?? []
	};
}
var Module$1 = class {
	constructor({ remoteInfo, host }) {
		this.inited = false;
		this.initing = false;
		this.lib = void 0;
		this.remoteInfo = remoteInfo;
		this.host = host;
	}
	async getEntry(expose, resourceContext) {
		const effectiveResourceContext = resourceContext || {
			initiator: "loadRemote",
			id: composeRemoteRequestId(this.remoteInfo.name, expose),
			resourceType: "remoteEntry",
			url: this.remoteInfo.entry,
			expose
		};
		const remoteEntryExports = await getRemoteEntry({
			origin: this.host,
			remoteInfo: this.remoteInfo,
			remoteEntryExports: this.remoteEntryExports,
			resourceContext: effectiveResourceContext
		});
		assert(remoteEntryExports, `remoteEntryExports is undefined \n ${safeToString(this.remoteInfo)}`);
		this.remoteEntryExports = remoteEntryExports;
		return this.remoteEntryExports;
	}
	async init(id, remoteSnapshot, rawInitScope, expose, resourceContext) {
		const remoteEntryExports = await this.getEntry(expose, resourceContext);
		if (this.inited) {
			await this.host.loaderHook.lifecycle.afterInitRemote.emit({
				id,
				remoteInfo: this.remoteInfo,
				remoteSnapshot,
				remoteEntryExports,
				cached: true,
				origin: this.host
			});
			return remoteEntryExports;
		}
		if (this.initPromise) {
			try {
				await this.initPromise;
				await this.host.loaderHook.lifecycle.afterInitRemote.emit({
					id,
					remoteInfo: this.remoteInfo,
					remoteSnapshot,
					remoteEntryExports,
					cached: true,
					origin: this.host
				});
			} catch (initError) {
				await this.host.loaderHook.lifecycle.afterInitRemote.emit({
					id,
					remoteInfo: this.remoteInfo,
					remoteSnapshot,
					remoteEntryExports,
					error: initError,
					cached: true,
					origin: this.host
				});
				throw initError;
			}
			return remoteEntryExports;
		}
		this.initing = true;
		this.initPromise = (async () => {
			await this.host.loaderHook.lifecycle.beforeInitRemote.emit({
				id,
				remoteInfo: this.remoteInfo,
				remoteSnapshot,
				origin: this.host
			});
			const { remoteEntryInitOptions, shareScope, initScope } = createRemoteEntryInitOptions(this.remoteInfo, this.host.shareScopeMap, rawInitScope);
			const initContainerOptions = await this.host.hooks.lifecycle.beforeInitContainer.emit({
				shareScope,
				remoteEntryInitOptions,
				initScope,
				remoteInfo: this.remoteInfo,
				origin: this.host
			});
			if (typeof remoteEntryExports?.init === "undefined") error(RUNTIME_002, runtimeDescMap, {
				hostName: this.host.name,
				remoteName: this.remoteInfo.name,
				remoteEntryUrl: this.remoteInfo.entry,
				remoteEntryKey: this.remoteInfo.entryGlobalName
			}, void 0, optionsToMFContext(this.host.options));
			try {
				await remoteEntryExports.init(initContainerOptions.shareScope, initContainerOptions.initScope, initContainerOptions.remoteEntryInitOptions);
			} catch (initError) {
				error(RUNTIME_015, runtimeDescMap, {
					hostName: this.host.name,
					remoteName: this.remoteInfo.name,
					remoteEntryUrl: this.remoteInfo.entry,
					remoteEntryKey: this.remoteInfo.entryGlobalName,
					shareScope: this.remoteInfo.shareScope
				}, `${initError}`, optionsToMFContext(this.host.options));
			}
			await this.host.hooks.lifecycle.initContainer.emit({
				...initContainerOptions,
				id,
				remoteSnapshot,
				remoteEntryExports
			});
			this.inited = true;
		})();
		try {
			await this.initPromise;
			await this.host.loaderHook.lifecycle.afterInitRemote.emit({
				id,
				remoteInfo: this.remoteInfo,
				remoteSnapshot,
				remoteEntryExports,
				origin: this.host
			});
		} catch (initError) {
			await this.host.loaderHook.lifecycle.afterInitRemote.emit({
				id,
				remoteInfo: this.remoteInfo,
				remoteSnapshot,
				remoteEntryExports,
				error: initError,
				origin: this.host
			});
			throw initError;
		} finally {
			this.initing = false;
			this.initPromise = void 0;
		}
		return remoteEntryExports;
	}
	async get(id, expose, options, remoteSnapshot) {
		const { loadFactory = true } = options || { loadFactory: true };
		const remoteEntryExports = await this.init(id, remoteSnapshot, void 0, expose);
		this.lib = remoteEntryExports;
		await this.host.loaderHook.lifecycle.beforeGetExpose.emit({
			id,
			expose,
			moduleInfo: this.remoteInfo,
			remoteEntryExports,
			origin: this.host
		});
		let moduleFactory;
		try {
			const hookModuleFactory = await this.host.loaderHook.lifecycle.getModuleFactory.emit({
				remoteEntryExports,
				expose,
				moduleInfo: this.remoteInfo
			});
			moduleFactory = typeof hookModuleFactory === "function" ? hookModuleFactory : void 0;
			if (!moduleFactory) moduleFactory = await remoteEntryExports.get(expose);
			if (!moduleFactory) error(RUNTIME_014, runtimeDescMap, {
				hostName: this.host.name,
				remoteName: this.remoteInfo.name,
				remoteEntryUrl: this.remoteInfo.entry,
				expose,
				requestId: id,
				availableExposes: getAvailableExposeNames(remoteSnapshot)
			}, void 0, optionsToMFContext(this.host.options));
			await this.host.loaderHook.lifecycle.afterGetExpose.emit({
				id,
				expose,
				moduleInfo: this.remoteInfo,
				remoteEntryExports,
				moduleFactory,
				origin: this.host
			});
		} catch (getExposeError) {
			await this.host.loaderHook.lifecycle.afterGetExpose.emit({
				id,
				expose,
				moduleInfo: this.remoteInfo,
				remoteEntryExports,
				error: getExposeError,
				origin: this.host
			});
			throw getExposeError;
		}
		const symbolName = processModuleAlias(this.remoteInfo.name, expose);
		const wrapModuleFactory = this.wraperFactory(moduleFactory, symbolName);
		if (!loadFactory) return wrapModuleFactory;
		await this.host.loaderHook.lifecycle.beforeExecuteFactory.emit({
			id,
			expose,
			moduleInfo: this.remoteInfo,
			loadFactory,
			origin: this.host
		});
		try {
			const exposeContent = await wrapModuleFactory();
			await this.host.loaderHook.lifecycle.afterExecuteFactory.emit({
				id,
				expose,
				moduleInfo: this.remoteInfo,
				loadFactory,
				exposeModule: exposeContent,
				origin: this.host
			});
			return exposeContent;
		} catch (executeFactoryError) {
			await this.host.loaderHook.lifecycle.afterExecuteFactory.emit({
				id,
				expose,
				moduleInfo: this.remoteInfo,
				loadFactory,
				error: executeFactoryError,
				origin: this.host
			});
			throw executeFactoryError;
		}
	}
	wraperFactory(moduleFactory, id) {
		function defineModuleId(res, id) {
			if (res && typeof res === "object" && Object.isExtensible(res) && !Object.getOwnPropertyDescriptor(res, Symbol.for("mf_module_id"))) Object.defineProperty(res, Symbol.for("mf_module_id"), {
				value: id,
				enumerable: false
			});
		}
		return () => {
			const res = moduleFactory();
			if (res instanceof Promise) return res.then((asyncRes) => {
				defineModuleId(asyncRes, id);
				return asyncRes;
			});
			defineModuleId(res, id);
			return res;
		};
	}
};

//#region src/utils/hooks/pluginSystem.ts
var PluginSystem = class {
	constructor(lifecycle) {
		this.registerPlugins = {};
		this.lifecycle = lifecycle;
		this.lifecycleKeys = Object.keys(lifecycle);
	}
	applyPlugin(plugin) {
		assert(isPlainObject(plugin), "Plugin configuration is invalid.");
		const pluginName = plugin.name;
		assert(pluginName, "A name must be provided by the plugin.");
		if (!this.registerPlugins[pluginName]) {
			this.registerPlugins[pluginName] = plugin;
			this.lifecycleKeys.forEach((key) => {
				const pluginLife = plugin[key];
				if (pluginLife) this.lifecycle[key].on(pluginLife);
			});
		}
	}
	removePlugin(pluginName) {
		assert(pluginName, "A name is required.");
		const plugin = this.registerPlugins[pluginName];
		assert(plugin, `The plugin "${pluginName}" is not registered.`);
		this.lifecycleKeys.forEach((key) => {
			const pluginLife = plugin[key];
			if (pluginLife) this.lifecycle[key].remove(pluginLife);
		});
		delete this.registerPlugins[pluginName];
	}
};

//#region src/utils/hooks/syncHook.ts
var SyncHook = class {
	constructor(type) {
		this.type = "";
		this.listeners = /* @__PURE__ */ new Set();
		if (type) this.type = type;
	}
	on(fn) {
		if (typeof fn === "function") this.listeners.add(fn);
	}
	once(fn) {
		const self = this;
		this.on(function wrapper(...args) {
			self.remove(wrapper);
			return fn.apply(null, args);
		});
	}
	emit(...data) {
		let result;
		if (this.listeners.size > 0) this.listeners.forEach((fn) => {
			const nextResult = fn(...data);
			if (nextResult !== void 0) result = nextResult;
		});
		return result;
	}
	remove(fn) {
		this.listeners.delete(fn);
	}
	removeAll() {
		this.listeners.clear();
	}
};

//#region src/utils/hooks/asyncHook.ts
var AsyncHook = class extends SyncHook {
	emit(...data) {
		let result;
		const ls = Array.from(this.listeners);
		if (ls.length > 0) {
			let i = 0;
			const call = (prev) => {
				if (prev === false) return false;
				else if (i < ls.length) return Promise.resolve(ls[i++].apply(null, data)).then((result) => {
					if (result === void 0 || data.length === 1 && result === data[0]) return call(prev);
					return call(result);
				});
				else return prev;
			};
			result = call();
		}
		return Promise.resolve(result);
	}
};

//#region src/utils/hooks/syncWaterfallHook.ts
function checkReturnData(originalData, returnedData) {
	if (!isObject(returnedData)) return false;
	if (originalData !== returnedData) {
		for (const key in originalData) if (!(key in returnedData)) return false;
	}
	return true;
}
var SyncWaterfallHook = class extends SyncHook {
	constructor(type) {
		super();
		this.onerror = error;
		this.type = type;
	}
	emit(data) {
		if (!isObject(data)) error(`The data for the "${this.type}" hook should be an object.`);
		for (const fn of this.listeners) try {
			const tempData = fn(data);
			if (tempData === void 0) continue;
			if (checkReturnData(data, tempData)) data = tempData;
			else {
				this.onerror(`A plugin returned an unacceptable value for the "${this.type}" type.`);
				break;
			}
		} catch (e) {
			warn$1(e);
			this.onerror(e);
		}
		return data;
	}
};

//#region src/utils/hooks/asyncWaterfallHooks.ts
var AsyncWaterfallHook = class extends SyncHook {
	constructor(type) {
		super();
		this.onerror = error;
		this.type = type;
	}
	emit(data) {
		if (!isObject(data)) error(`The response data for the "${this.type}" hook must be an object.`);
		const ls = Array.from(this.listeners);
		if (ls.length > 0) {
			let i = 0;
			const processError = (e) => {
				warn$1(e);
				this.onerror(e);
				return data;
			};
			const call = (prevData) => {
				if (prevData !== void 0 && checkReturnData(data, prevData)) data = prevData;
				else if (prevData !== void 0) {
					this.onerror(`A plugin returned an incorrect value for the "${this.type}" type.`);
					return data;
				}
				if (i < ls.length) try {
					return Promise.resolve(ls[i++](data)).then(call, processError);
				} catch (e) {
					return processError(e);
				}
				return data;
			};
			return Promise.resolve(call(data));
		}
		return Promise.resolve(data);
	}
};

//#region src/remote/disabled.ts
const REMOTE_DISABLED_MESSAGE = "Remote loading is disabled by experiments.optimization.disableRemote.";
var UnavailableRemoteModule = class {
	constructor() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
};
var DisabledRemoteHandler = class {
	constructor() {
		this.hooks = new PluginSystem({});
	}
	formatAndRegisterRemote() {
		return [];
	}
	loadRemote() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
	preloadRemote() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
	registerRemotes() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
	getRemoteModuleAndOptions() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
	initRawContainer() {
		throw new Error(REMOTE_DISABLED_MESSAGE);
	}
};

//#region src/plugins/snapshot/index.ts
function assignRemoteInfo(remoteInfo, remoteSnapshot) {
	const remoteEntryInfo = getRemoteEntryInfoFromSnapshot(remoteSnapshot);
	if (!remoteEntryInfo.url) error(RUNTIME_011, runtimeDescMap, { remoteName: remoteInfo.name });
	let entryUrl = getResourceUrl(remoteSnapshot, remoteEntryInfo.url);
	remoteInfo.type = remoteEntryInfo.type;
	remoteInfo.entryGlobalName = remoteEntryInfo.globalName;
	remoteInfo.entry = entryUrl;
	remoteInfo.version = remoteSnapshot.version;
	remoteInfo.buildVersion = remoteSnapshot.buildVersion;
}
function snapshotPlugin() {
	return {
		name: "snapshot-plugin",
		async afterResolve(args) {
			const { remote, pkgNameOrAlias, expose, origin, remoteInfo, id } = args;
			if (!isRemoteInfoWithEntry(remote) || !isPureRemoteEntry(remote)) {
				const { remoteSnapshot, globalSnapshot } = await origin.snapshotHandler.loadRemoteSnapshotInfo({
					moduleInfo: remote,
					id: composeRemoteRequestId(remote.name, expose)
				});
				assignRemoteInfo(remoteInfo, remoteSnapshot);
				const preloadOps = [{
					nameOrAlias: pkgNameOrAlias,
					exposes: [expose],
					resourceCategory: "sync",
					share: false,
					depsRemote: false,
					recordPreloadedAssets: true
				}];
				await origin.remoteHandler.hooks.lifecycle.beforePreloadRemote.emit({
					preloadOps,
					options: origin.options,
					origin
				});
				const [preloadConfig] = preloadOps;
				if (preloadConfig) {
					const preloadOptions = {
						remote,
						preloadConfig
					};
					const assets = await origin.remoteHandler.hooks.lifecycle.generatePreloadAssets.emit({
						origin,
						preloadOptions,
						remoteInfo,
						remote,
						remoteSnapshot,
						globalSnapshot
					});
					if (assets) preloadAssets(remoteInfo, origin, assets, false, {
						initiator: "loadRemote",
						id
					}, preloadConfig.recordPreloadedAssets).catch(() => void 0);
				}
				return {
					...args,
					remoteSnapshot
				};
			}
			return args;
		}
	};
}

//#region src/plugins/generate-preload-assets.ts
function splitId(id) {
	const splitInfo = id.split(":");
	if (splitInfo.length === 1) return {
		name: splitInfo[0],
		version: void 0
	};
	else if (splitInfo.length === 2) return {
		name: splitInfo[0],
		version: splitInfo[1]
	};
	else return {
		name: splitInfo[1],
		version: splitInfo[2]
	};
}
function traverseModuleInfo(globalSnapshot, remoteInfo, traverse, isRoot, memo = {}, remoteSnapshot) {
	const { value: snapshotValue } = getInfoWithoutType(globalSnapshot, getFMId(remoteInfo));
	const effectiveRemoteSnapshot = remoteSnapshot || snapshotValue;
	if (effectiveRemoteSnapshot && !isManifestProvider(effectiveRemoteSnapshot)) {
		traverse(effectiveRemoteSnapshot, remoteInfo, isRoot);
		if (effectiveRemoteSnapshot.remotesInfo) {
			const remoteKeys = Object.keys(effectiveRemoteSnapshot.remotesInfo);
			for (const key of remoteKeys) {
				if (memo[key]) continue;
				memo[key] = true;
				const subRemoteInfo = splitId(key);
				const remoteValue = effectiveRemoteSnapshot.remotesInfo[key];
				traverseModuleInfo(globalSnapshot, {
					name: subRemoteInfo.name,
					version: remoteValue.matchedVersion
				}, traverse, false, memo, void 0);
			}
		}
	}
}
const isExisted = (type, url) => {
	return document.querySelector(`${type}[${type === "link" ? "href" : "src"}="${url}"]`);
};
function generatePreloadAssets(origin, preloadOptions, remote, globalSnapshot, remoteSnapshot) {
	const cssAssets = [];
	const jsAssets = [];
	const entryAssets = [];
	const loadedSharedJsAssets = /* @__PURE__ */ new Set();
	const loadedSharedCssAssets = /* @__PURE__ */ new Set();
	const { options } = origin;
	const { preloadConfig: rootPreloadConfig } = preloadOptions;
	const { depsRemote } = rootPreloadConfig;
	traverseModuleInfo(globalSnapshot, remote, (moduleInfoSnapshot, remoteInfo, isRoot) => {
		let preloadConfig;
		if (isRoot) preloadConfig = rootPreloadConfig;
		else if (Array.isArray(depsRemote)) {
			const findPreloadConfig = depsRemote.find((remoteConfig) => {
				if (remoteConfig.nameOrAlias === remoteInfo.name || remoteConfig.nameOrAlias === remoteInfo.alias) return true;
				return false;
			});
			if (!findPreloadConfig) return;
			preloadConfig = defaultPreloadArgs(findPreloadConfig);
		} else if (depsRemote === true) preloadConfig = rootPreloadConfig;
		else return;
		const remoteEntryUrl = getResourceUrl(moduleInfoSnapshot, getRemoteEntryInfoFromSnapshot(moduleInfoSnapshot).url);
		if (remoteEntryUrl) entryAssets.push({
			name: remoteInfo.name,
			moduleInfo: {
				name: remoteInfo.name,
				entry: remoteEntryUrl,
				type: "remoteEntryType" in moduleInfoSnapshot ? moduleInfoSnapshot.remoteEntryType : "global",
				entryGlobalName: "globalName" in moduleInfoSnapshot ? moduleInfoSnapshot.globalName : remoteInfo.name,
				shareScope: "",
				version: "version" in moduleInfoSnapshot ? moduleInfoSnapshot.version : void 0
			},
			url: remoteEntryUrl
		});
		let moduleAssetsInfo = "modules" in moduleInfoSnapshot ? moduleInfoSnapshot.modules : [];
		const normalizedPreloadExposes = normalizePreloadExposes(preloadConfig.exposes);
		if (normalizedPreloadExposes.length && "modules" in moduleInfoSnapshot) moduleAssetsInfo = moduleInfoSnapshot?.modules?.reduce((assets, moduleAssetInfo) => {
			if (normalizedPreloadExposes?.indexOf(moduleAssetInfo.moduleName) !== -1) assets.push(moduleAssetInfo);
			return assets;
		}, []);
		function handleAssets(assets) {
			const assetsRes = assets.map((asset) => getResourceUrl(moduleInfoSnapshot, asset));
			if (preloadConfig.filter) return assetsRes.filter(preloadConfig.filter);
			return assetsRes;
		}
		if (moduleAssetsInfo) {
			const assetsLength = moduleAssetsInfo.length;
			for (let index = 0; index < assetsLength; index++) {
				const assetsInfo = moduleAssetsInfo[index];
				const exposeFullPath = `${remoteInfo.name}/${assetsInfo.moduleName}`;
				origin.remoteHandler.hooks.lifecycle.handlePreloadModule.emit({
					id: assetsInfo.moduleName === "." ? remoteInfo.name : exposeFullPath,
					name: remoteInfo.name,
					remoteSnapshot: moduleInfoSnapshot,
					preloadConfig,
					remote: remoteInfo,
					origin
				});
				if (getPreloaded(exposeFullPath)) continue;
				if (preloadConfig.resourceCategory === "all") {
					cssAssets.push(...handleAssets(assetsInfo.assets.css.async));
					cssAssets.push(...handleAssets(assetsInfo.assets.css.sync));
					jsAssets.push(...handleAssets(assetsInfo.assets.js.async));
					jsAssets.push(...handleAssets(assetsInfo.assets.js.sync));
				} else if (preloadConfig.resourceCategory === "sync") {
					cssAssets.push(...handleAssets(assetsInfo.assets.css.sync));
					jsAssets.push(...handleAssets(assetsInfo.assets.js.sync));
				}
				setPreloaded(exposeFullPath);
			}
		}
	}, true, {}, remoteSnapshot);
	if (remoteSnapshot.shared && remoteSnapshot.shared.length > 0) {
		const collectSharedAssets = (shareInfo, snapshotShared) => {
			const { shared: registeredShared } = getRegisteredShare(origin.shareScopeMap, snapshotShared.sharedName, shareInfo, origin.sharedHandler.hooks.lifecycle.resolveShare) || {};
			if (registeredShared && typeof registeredShared.lib === "function") {
				snapshotShared.assets.js.sync.forEach((asset) => {
					loadedSharedJsAssets.add(asset);
				});
				snapshotShared.assets.css.sync.forEach((asset) => {
					loadedSharedCssAssets.add(asset);
				});
			}
		};
		remoteSnapshot.shared.forEach((shared) => {
			const shareInfos = options.shared?.[shared.sharedName];
			if (!shareInfos) return;
			const sharedOptions = shared.version ? shareInfos.find((s) => s.version === shared.version) : shareInfos;
			if (!sharedOptions) return;
			arrayOptions(sharedOptions).forEach((s) => {
				collectSharedAssets(s, shared);
			});
		});
	}
	const needPreloadJsAssets = jsAssets.filter((asset) => !loadedSharedJsAssets.has(asset) && !isExisted("script", asset));
	return {
		cssAssets: cssAssets.filter((asset) => !loadedSharedCssAssets.has(asset) && !isExisted("link", asset)),
		jsAssetsWithoutEntry: needPreloadJsAssets,
		entryAssets: entryAssets.filter((entry) => !isExisted("script", entry.url))
	};
}
const generatePreloadAssetsPlugin = function() {
	return {
		name: "generate-preload-assets-plugin",
		async generatePreloadAssets(args) {
			const { origin, preloadOptions, remoteInfo, remote, globalSnapshot, remoteSnapshot } = args;
			if (isRemoteInfoWithEntry(remote) && isPureRemoteEntry(remote)) return {
				cssAssets: [],
				jsAssetsWithoutEntry: [],
				entryAssets: [{
					name: remote.name,
					url: remote.entry,
					moduleInfo: {
						name: remoteInfo.name,
						entry: remote.entry,
						type: remoteInfo.type || "global",
						entryGlobalName: "",
						shareScope: ""
					}
				}]
			};
			assignRemoteInfo(remoteInfo, remoteSnapshot);
			return generatePreloadAssets(origin, preloadOptions, remoteInfo, globalSnapshot, remoteSnapshot);
		}
	};
};

//#region src/plugins/snapshot/SnapshotHandler.ts
function getGlobalRemoteInfo(moduleInfo, origin) {
	const hostGlobalSnapshot = getGlobalSnapshotInfoByModuleInfo({
		name: origin.name,
		version: origin.options.version
	});
	const globalRemoteInfo = hostGlobalSnapshot && "remotesInfo" in hostGlobalSnapshot && hostGlobalSnapshot.remotesInfo && getInfoWithoutType(hostGlobalSnapshot.remotesInfo, moduleInfo.name).value;
	if (globalRemoteInfo && globalRemoteInfo.matchedVersion) return {
		hostGlobalSnapshot,
		globalSnapshot: getGlobalSnapshot(),
		remoteSnapshot: getGlobalSnapshotInfoByModuleInfo({
			name: moduleInfo.name,
			version: globalRemoteInfo.matchedVersion
		})
	};
	return {
		hostGlobalSnapshot: void 0,
		globalSnapshot: getGlobalSnapshot(),
		remoteSnapshot: getGlobalSnapshotInfoByModuleInfo({
			name: moduleInfo.name,
			version: "version" in moduleInfo ? moduleInfo.version : void 0
		})
	};
}
var SnapshotHandler = class {
	constructor(HostInstance) {
		this.loadingHostSnapshot = null;
		this.manifestCache = /* @__PURE__ */ new Map();
		this.hooks = new PluginSystem({
			beforeLoadRemoteSnapshot: new AsyncHook("beforeLoadRemoteSnapshot"),
			loadSnapshot: new AsyncWaterfallHook("loadGlobalSnapshot"),
			loadRemoteSnapshot: new AsyncWaterfallHook("loadRemoteSnapshot"),
			afterLoadSnapshot: new AsyncWaterfallHook("afterLoadSnapshot"),
			beforeLoadManifest: new AsyncHook("beforeLoadManifest"),
			afterLoadManifest: new AsyncHook("afterLoadManifest")
		});
		this.manifestLoading = Global.__FEDERATION__.__MANIFEST_LOADING__;
		this.HostInstance = HostInstance;
		this.loaderHook = HostInstance.loaderHook;
	}
	async loadRemoteSnapshotInfo({ moduleInfo, id, initiator = "loadRemote" }) {
		const { options } = this.HostInstance;
		await this.hooks.lifecycle.beforeLoadRemoteSnapshot.emit({
			options,
			moduleInfo,
			origin: this.HostInstance
		});
		let hostSnapshot = getGlobalSnapshotInfoByModuleInfo({
			name: this.HostInstance.options.name,
			version: this.HostInstance.options.version
		});
		if (!hostSnapshot) {
			hostSnapshot = {
				version: this.HostInstance.options.version || "",
				remoteEntry: "",
				remotesInfo: {}
			};
			addGlobalSnapshot({ [this.HostInstance.options.name]: hostSnapshot });
		}
		if (hostSnapshot && "remotesInfo" in hostSnapshot && !getInfoWithoutType(hostSnapshot.remotesInfo, moduleInfo.name).value) {
			if ("version" in moduleInfo || "entry" in moduleInfo) hostSnapshot.remotesInfo = {
				...hostSnapshot?.remotesInfo,
				[moduleInfo.name]: { matchedVersion: "version" in moduleInfo ? moduleInfo.version : moduleInfo.entry }
			};
		}
		const { hostGlobalSnapshot, remoteSnapshot, globalSnapshot } = this.getGlobalRemoteInfo(moduleInfo);
		const { remoteSnapshot: globalRemoteSnapshot, globalSnapshot: globalSnapshotRes } = await this.hooks.lifecycle.loadSnapshot.emit({
			options,
			moduleInfo,
			hostGlobalSnapshot,
			remoteSnapshot,
			globalSnapshot
		});
		let mSnapshot;
		let gSnapshot;
		if (globalRemoteSnapshot) if (isManifestProvider(globalRemoteSnapshot)) {
			const remoteEntry = globalRemoteSnapshot.remoteEntry ;
			const moduleSnapshot = await this.loadManifestSnapshot(remoteEntry, moduleInfo, {}, {
				initiator,
				id: id || moduleInfo.name
			});
			const globalSnapshotRes = setGlobalSnapshotInfoByModuleInfo({
				...moduleInfo,
				entry: remoteEntry
			}, moduleSnapshot);
			mSnapshot = moduleSnapshot;
			gSnapshot = globalSnapshotRes;
		} else {
			const { remoteSnapshot: remoteSnapshotRes } = await this.hooks.lifecycle.loadRemoteSnapshot.emit({
				options: this.HostInstance.options,
				moduleInfo,
				remoteSnapshot: globalRemoteSnapshot,
				from: "global"
			});
			mSnapshot = remoteSnapshotRes;
			gSnapshot = globalSnapshotRes;
		}
		else if (isRemoteInfoWithEntry(moduleInfo)) {
			const moduleSnapshot = await this.loadManifestSnapshot(moduleInfo.entry, moduleInfo, {}, {
				initiator,
				id: id || moduleInfo.name
			});
			const globalSnapshotRes = setGlobalSnapshotInfoByModuleInfo(moduleInfo, moduleSnapshot);
			mSnapshot = moduleSnapshot;
			gSnapshot = globalSnapshotRes;
		} else error(RUNTIME_007, runtimeDescMap, {
			remoteName: moduleInfo.name,
			remoteVersion: moduleInfo.version,
			hostName: this.HostInstance.options.name,
			globalSnapshot: JSON.stringify(globalSnapshotRes)
		}, void 0, optionsToMFContext(this.HostInstance.options));
		await this.hooks.lifecycle.afterLoadSnapshot.emit({
			id,
			host: this.HostInstance,
			options,
			moduleInfo,
			remoteSnapshot: mSnapshot
		});
		return {
			remoteSnapshot: mSnapshot,
			globalSnapshot: gSnapshot
		};
	}
	getGlobalRemoteInfo(moduleInfo) {
		return getGlobalRemoteInfo(moduleInfo, this.HostInstance);
	}
	async getManifestJson(manifestUrl, moduleInfo, extraOptions, resourceOptions) {
		const getManifest = async () => {
			const remoteInfo = getRemoteInfo(moduleInfo);
			let manifestJson = this.manifestCache.get(manifestUrl);
			if (manifestJson) {
				await this.hooks.lifecycle.afterLoadManifest.emit({
					manifestUrl,
					moduleInfo,
					resourceOptions,
					manifestJson,
					cached: true,
					origin: this.HostInstance
				});
				return manifestJson;
			}
			await this.hooks.lifecycle.beforeLoadManifest.emit({
				manifestUrl,
				moduleInfo,
				resourceOptions,
				origin: this.HostInstance
			});
			let response;
			let loadError;
			let recovered = false;
			try {
				let res = await this.loaderHook.lifecycle.fetch.emit(manifestUrl, {}, remoteInfo, resourceOptions ? {
					...resourceOptions,
					url: manifestUrl,
					resourceType: "manifest"
				} : void 0);
				if (!res || !(res instanceof Response)) res = await fetch(manifestUrl, {});
				response = res;
				manifestJson = await res.json();
			} catch (err) {
				loadError = err;
				manifestJson = await this.HostInstance.remoteHandler.hooks.lifecycle.errorLoadRemote.emit({
					id: manifestUrl,
					error: err,
					from: "runtime",
					lifecycle: "afterResolve",
					remote: remoteInfo,
					origin: this.HostInstance
				});
				if (!manifestJson) {
					delete this.manifestLoading[manifestUrl];
					await this.hooks.lifecycle.afterLoadManifest.emit({
						manifestUrl,
						moduleInfo,
						resourceOptions,
						response,
						error: err,
						origin: this.HostInstance
					});
					error(RUNTIME_003, runtimeDescMap, {
						manifestUrl,
						moduleName: moduleInfo.name,
						hostName: this.HostInstance.options.name
					}, `${err}`, optionsToMFContext(this.HostInstance.options));
				}
				recovered = true;
			}
			const missingRequiredFields = [
				!manifestJson.metaData && "metaData",
				!manifestJson.exposes && "exposes",
				!manifestJson.shared && "shared"
			].filter(Boolean);
			const validationError = missingRequiredFields.length > 0 ? /* @__PURE__ */ new Error(`"${manifestUrl}" is not a valid federation manifest for remote "${moduleInfo.name}". Missing required fields: ${missingRequiredFields.join(", ")}.`) : void 0;
			if (validationError) await this.HostInstance.remoteHandler.hooks.lifecycle.errorLoadRemote.emit({
				id: manifestUrl,
				error: validationError,
				from: "runtime",
				lifecycle: "afterResolve",
				remote: remoteInfo,
				origin: this.HostInstance
			});
			await this.hooks.lifecycle.afterLoadManifest.emit({
				manifestUrl,
				moduleInfo,
				resourceOptions,
				manifestJson,
				response,
				error: validationError || loadError,
				recovered: validationError ? void 0 : recovered || void 0,
				origin: this.HostInstance
			});
			if (validationError) error(RUNTIME_013, runtimeDescMap, {
				manifestUrl,
				moduleName: moduleInfo.name,
				hostName: this.HostInstance.options.name,
				missingFields: missingRequiredFields.join(",")
			}, void 0, optionsToMFContext(this.HostInstance.options));
			this.manifestCache.set(manifestUrl, manifestJson);
			return manifestJson;
		};
		return getManifest();
	}
	async loadManifestSnapshot(manifestUrl, moduleInfo, extraOptions, resourceOptions) {
		const asyncLoadProcess = async () => {
			const manifestJson = await this.getManifestJson(manifestUrl, moduleInfo, extraOptions, resourceOptions);
			const remoteSnapshot = generateSnapshotFromManifest(manifestJson, { version: manifestUrl });
			const { remoteSnapshot: remoteSnapshotRes } = await this.hooks.lifecycle.loadRemoteSnapshot.emit({
				options: this.HostInstance.options,
				moduleInfo,
				manifestJson,
				remoteSnapshot,
				manifestUrl,
				from: "manifest"
			});
			return remoteSnapshotRes;
		};
		if (!this.manifestLoading[manifestUrl]) this.manifestLoading[manifestUrl] = asyncLoadProcess().then((res) => res);
		return this.manifestLoading[manifestUrl];
	}
};

//#region src/plugins/snapshot/disabled.ts
var DisabledSnapshotHandler = class {
	constructor() {
		this.hooks = new PluginSystem({});
	}
};

//#region src/shared/index.ts
var SharedHandler = class {
	constructor(host) {
		this.hooks = new PluginSystem({
			beforeRegisterShare: new SyncWaterfallHook("beforeRegisterShare"),
			afterRegisterShare: new SyncHook("afterRegisterShare"),
			afterResolve: new AsyncWaterfallHook("afterResolve"),
			beforeLoadShare: new AsyncWaterfallHook("beforeLoadShare"),
			loadShare: new AsyncHook(),
			afterLoadShare: new SyncHook("afterLoadShare"),
			errorLoadShare: new SyncHook("errorLoadShare"),
			resolveShare: new SyncWaterfallHook("resolveShare"),
			initContainerShareScopeMap: new SyncWaterfallHook("initContainerShareScopeMap")
		});
		this.host = host;
		this.shareScopeMap = {};
		this.initTokens = {};
		this._setGlobalShareScopeMap(host.options);
	}
	emitAfterRegisterShare(pkgName, input) {
		this.hooks.lifecycle.afterRegisterShare.emit({
			pkgName,
			...input,
			shareScopeMap: this.shareScopeMap,
			origin: this.host
		});
	}
	emitAfterLoadShare({ lifecycle, pkgName, shareInfo, selectedShared, loadContext }) {
		try {
			this.hooks.lifecycle.afterLoadShare.emit({
				pkgName,
				shareInfo,
				selectedShared,
				shared: this.host.options.shared,
				shareScopeMap: this.shareScopeMap,
				lifecycle,
				loadContext,
				origin: this.host
			});
		} catch (error) {
			warn$1(error);
		}
	}
	emitErrorLoadShare({ lifecycle, pkgName, shareInfo, error, recovered, loadContext }) {
		try {
			this.hooks.lifecycle.errorLoadShare.emit({
				pkgName,
				shareInfo,
				shared: this.host.options.shared,
				shareScopeMap: this.shareScopeMap,
				lifecycle,
				origin: this.host,
				error,
				recovered,
				loadContext
			});
		} catch (hookError) {
			warn$1(hookError);
		}
	}
	registerShared(globalOptions, userOptions) {
		const { newShareInfos, allShareInfos } = formatShareConfigs(globalOptions, userOptions);
		Object.keys(newShareInfos).forEach((sharedKey) => {
			newShareInfos[sharedKey].forEach((sharedVal) => {
				sharedVal.scope.forEach((sc) => {
					this.hooks.lifecycle.beforeRegisterShare.emit({
						origin: this.host,
						pkgName: sharedKey,
						shared: sharedVal
					});
					const registeredShared = this.shareScopeMap[sc]?.[sharedKey];
					const previousAtVersion = registeredShared?.[sharedVal.version];
					if (!registeredShared) this.setShared({
						pkgName: sharedKey,
						lib: sharedVal.lib,
						get: sharedVal.get,
						loaded: sharedVal.loaded || Boolean(sharedVal.lib),
						shared: sharedVal,
						from: userOptions.name
					});
					this.emitAfterRegisterShare(sharedKey, {
						scope: sc,
						shared: sharedVal,
						previousShared: previousAtVersion,
						registeredShared: this.shareScopeMap[sc]?.[sharedKey]?.[sharedVal.version],
						trigger: "runtime"
					});
				});
			});
		});
		return {
			newShareInfos,
			allShareInfos
		};
	}
	async loadShare(pkgName, extraOptions) {
		const { host } = this;
		let loadContext = extraOptions?.context;
		const shareOptions = getTargetSharedOptions({
			pkgName,
			extraOptions,
			shareInfos: host.options.shared
		});
		let shareOptionsRes = shareOptions;
		try {
			if (shareOptions?.scope) await Promise.all(shareOptions.scope.map(async (shareScope) => {
				await Promise.all(this.initializeSharing(shareScope, {
					strategy: shareOptions.strategy,
					context: loadContext
				}));
			}));
			const loadShareRes = await this.hooks.lifecycle.beforeLoadShare.emit({
				pkgName,
				shareInfo: shareOptions,
				shared: host.options.shared,
				origin: host,
				loadContext
			});
			shareOptionsRes = loadShareRes.shareInfo;
			loadContext = loadShareRes.loadContext || loadContext;
			assert(shareOptionsRes, `Cannot find shared "${pkgName}" in host "${host.options.name}". Ensure the shared config for "${pkgName}" is declared in the federation plugin options and the host has been initialized before loading shares.`);
			const resolvedShareOptions = shareOptionsRes;
			const { shared: registeredShared, useTreesShaking } = getRegisteredShare(this.shareScopeMap, pkgName, shareOptionsRes, this.hooks.lifecycle.resolveShare, loadContext) || {};
			if (registeredShared) {
				const targetShared = directShare(registeredShared, useTreesShaking);
				if (targetShared.lib) {
					addUseIn(targetShared, host.options.name);
					this.emitAfterLoadShare({
						lifecycle: "loadShare",
						pkgName,
						shareInfo: resolvedShareOptions,
						selectedShared: registeredShared,
						loadContext
					});
					return targetShared.lib;
				} else if (targetShared.loading && !targetShared.loaded) {
					const factory = await targetShared.loading;
					targetShared.loaded = true;
					if (!targetShared.lib) targetShared.lib = factory;
					addUseIn(targetShared, host.options.name);
					this.emitAfterLoadShare({
						lifecycle: "loadShare",
						pkgName,
						shareInfo: resolvedShareOptions,
						selectedShared: registeredShared,
						loadContext
					});
					return factory;
				} else {
					const asyncLoadProcess = async () => {
						const factory = await targetShared.get();
						addUseIn(targetShared, host.options.name);
						targetShared.loaded = true;
						targetShared.lib = factory;
						return factory;
					};
					const loading = asyncLoadProcess();
					this.setShared({
						pkgName,
						loaded: false,
						shared: registeredShared,
						from: host.options.name,
						lib: null,
						loading,
						treeShaking: useTreesShaking ? targetShared : void 0
					});
					const factory = await loading;
					this.emitAfterLoadShare({
						lifecycle: "loadShare",
						pkgName,
						shareInfo: resolvedShareOptions,
						selectedShared: registeredShared,
						loadContext
					});
					return factory;
				}
			} else {
				if (extraOptions?.customShareInfo) {
					this.emitErrorLoadShare({
						lifecycle: "loadShare",
						pkgName,
						shareInfo: resolvedShareOptions,
						recovered: true,
						loadContext
					});
					return false;
				}
				const _useTreeShaking = shouldUseTreeShaking(resolvedShareOptions.treeShaking);
				const targetShared = directShare(resolvedShareOptions, _useTreeShaking);
				const asyncLoadProcess = async () => {
					const factory = await targetShared.get();
					targetShared.lib = factory;
					targetShared.loaded = true;
					addUseIn(targetShared, host.options.name);
					const { shared: gShared, useTreesShaking: gUseTreeShaking } = getRegisteredShare(this.shareScopeMap, pkgName, resolvedShareOptions, this.hooks.lifecycle.resolveShare, loadContext) || {};
					if (gShared) {
						const targetGShared = directShare(gShared, gUseTreeShaking);
						targetGShared.lib = factory;
						targetGShared.loaded = true;
						gShared.from = resolvedShareOptions.from;
					}
					return factory;
				};
				const loading = asyncLoadProcess();
				this.setShared({
					pkgName,
					loaded: false,
					shared: resolvedShareOptions,
					from: host.options.name,
					lib: null,
					loading,
					treeShaking: _useTreeShaking ? targetShared : void 0
				});
				const factory = await loading;
				this.emitAfterLoadShare({
					lifecycle: "loadShare",
					pkgName,
					shareInfo: resolvedShareOptions,
					selectedShared: resolvedShareOptions,
					loadContext
				});
				return factory;
			}
		} catch (shareError) {
			this.emitErrorLoadShare({
				lifecycle: "loadShare",
				pkgName,
				shareInfo: shareOptionsRes,
				error: shareError,
				loadContext
			});
			throw shareError;
		}
	}
	/**
	* This function initializes the sharing sequence (executed only once per share scope).
	* It accepts one argument, the name of the share scope.
	* If the share scope does not exist, it creates one.
	*/
	initializeSharing(shareScopeName = DEFAULT_SCOPE, extraOptions) {
		const { host } = this;
		const from = extraOptions?.from;
		const strategy = extraOptions?.strategy;
		const trigger = extraOptions?.context?.trigger || from || "runtime";
		let initScope = extraOptions?.initScope;
		const promises = [];
		if (from !== "build") {
			const { initTokens } = this;
			if (!initScope) initScope = [];
			let initToken = initTokens[shareScopeName];
			if (!initToken) initToken = initTokens[shareScopeName] = { from: this.host.name };
			if (initScope.indexOf(initToken) >= 0) return promises;
			initScope.push(initToken);
		}
		const shareScope = this.shareScopeMap;
		const hostName = host.options.name;
		if (!shareScope[shareScopeName]) shareScope[shareScopeName] = {};
		const scope = shareScope[shareScopeName];
		const register = (name, shared) => {
			const { version, eager } = shared;
			scope[name] = scope[name] || {};
			const versions = scope[name];
			const existingShared = versions[version];
			const activeVersion = existingShared && directShare(existingShared);
			const activeVersionEager = Boolean(activeVersion && ("eager" in activeVersion && activeVersion.eager || "shareConfig" in activeVersion && activeVersion.shareConfig?.eager));
			if (Boolean(!activeVersion || activeVersion.strategy !== "loaded-first" && !activeVersion.loaded && (Boolean(!eager) !== !activeVersionEager ? eager : hostName > versions[version].from))) versions[version] = shared;
			this.emitAfterRegisterShare(name, {
				scope: shareScopeName,
				shared,
				previousShared: existingShared,
				registeredShared: versions[version],
				trigger
			});
		};
		const initRemoteModule = async (key) => {
			const { module } = await host.remoteHandler.getRemoteModuleAndOptions({ id: key });
			let remoteEntryExports = void 0;
			const resourceContext = {
				initiator: "loadShare",
				id: key,
				resourceType: "remoteEntry",
				url: module.remoteInfo.entry
			};
			try {
				remoteEntryExports = await module.getEntry(void 0, resourceContext);
			} catch (error) {
				remoteEntryExports = await host.remoteHandler.hooks.lifecycle.errorLoadRemote.emit({
					id: key,
					error,
					from: "runtime",
					lifecycle: "beforeLoadShare",
					remote: module.remoteInfo,
					origin: host
				});
				if (!remoteEntryExports) return;
			} finally {
				if (remoteEntryExports?.init && !module.initing) {
					module.remoteEntryExports = remoteEntryExports;
					await module.init(void 0, void 0, initScope, void 0, resourceContext);
				}
			}
		};
		Object.keys(host.options.shared).forEach((shareName) => {
			host.options.shared[shareName].forEach((shared) => {
				if (shared.scope.includes(shareScopeName)) register(shareName, shared);
			});
		});
		if (host.options.shareStrategy === "version-first" || strategy === "version-first") host.options.remotes.forEach((remote) => {
			if (remote.shareScope === shareScopeName) promises.push(initRemoteModule(remote.name));
		});
		return promises;
	}
	loadShareSync(pkgName, extraOptions) {
		const { host } = this;
		const loadContext = extraOptions?.context;
		const shareOptions = getTargetSharedOptions({
			pkgName,
			extraOptions,
			shareInfos: host.options.shared
		});
		try {
			if (shareOptions?.scope) shareOptions.scope.forEach((shareScope) => {
				this.initializeSharing(shareScope, {
					strategy: shareOptions.strategy,
					from: extraOptions?.from,
					context: loadContext
				});
			});
			const { shared: registeredShared } = getRegisteredShare(this.shareScopeMap, pkgName, shareOptions, this.hooks.lifecycle.resolveShare, loadContext) || {};
			if (registeredShared) {
				if (typeof registeredShared.lib === "function") {
					addUseIn(registeredShared, host.options.name);
					if (!registeredShared.loaded) {
						registeredShared.loaded = true;
						if (registeredShared.from === host.options.name) shareOptions.loaded = true;
					}
					this.emitAfterLoadShare({
						lifecycle: "loadShareSync",
						pkgName,
						shareInfo: shareOptions,
						selectedShared: registeredShared,
						loadContext
					});
					return registeredShared.lib;
				}
				if (typeof registeredShared.get === "function") {
					const module = registeredShared.get();
					if (!(module instanceof Promise)) {
						addUseIn(registeredShared, host.options.name);
						this.setShared({
							pkgName,
							loaded: true,
							from: host.options.name,
							lib: module,
							shared: registeredShared
						});
						this.emitAfterLoadShare({
							lifecycle: "loadShareSync",
							pkgName,
							shareInfo: shareOptions,
							selectedShared: registeredShared,
							loadContext
						});
						return module;
					}
				}
			}
			if (shareOptions.lib) {
				if (!shareOptions.loaded) shareOptions.loaded = true;
				this.emitAfterLoadShare({
					lifecycle: "loadShareSync",
					pkgName,
					shareInfo: shareOptions,
					selectedShared: shareOptions,
					loadContext
				});
				return shareOptions.lib;
			}
			if (shareOptions.get) {
				const module = shareOptions.get();
				if (module instanceof Promise) error(extraOptions?.from === "build" ? RUNTIME_005 : RUNTIME_006, runtimeDescMap, {
					hostName: host.options.name,
					sharedPkgName: pkgName
				}, void 0, optionsToMFContext(host.options));
				shareOptions.lib = module;
				this.setShared({
					pkgName,
					loaded: true,
					from: host.options.name,
					lib: shareOptions.lib,
					shared: shareOptions
				});
				this.emitAfterLoadShare({
					lifecycle: "loadShareSync",
					pkgName,
					shareInfo: shareOptions,
					selectedShared: shareOptions,
					loadContext
				});
				return shareOptions.lib;
			}
			error(RUNTIME_006, runtimeDescMap, {
				hostName: host.options.name,
				sharedPkgName: pkgName
			}, void 0, optionsToMFContext(host.options));
		} catch (shareError) {
			this.emitErrorLoadShare({
				lifecycle: "loadShareSync",
				pkgName,
				shareInfo: shareOptions,
				error: shareError,
				loadContext
			});
			throw shareError;
		}
	}
	initShareScopeMap(scopeName, shareScope, extraOptions = {}) {
		const { host } = this;
		this.shareScopeMap[scopeName] = shareScope;
		this.hooks.lifecycle.initContainerShareScopeMap.emit({
			shareScope,
			options: host.options,
			origin: host,
			scopeName,
			hostShareScopeMap: extraOptions.hostShareScopeMap
		});
	}
	setShared({ pkgName, shared, from, lib, loading, loaded, get, treeShaking }) {
		const { version, scope = "default", ...shareInfo } = shared;
		const scopes = Array.isArray(scope) ? scope : [scope];
		const mergeAttrs = (shared) => {
			const merge = (s, key, val) => {
				if (val && !s[key]) s[key] = val;
			};
			const targetShared = treeShaking ? shared.treeShaking : shared;
			merge(targetShared, "loaded", loaded);
			merge(targetShared, "loading", loading);
			merge(targetShared, "get", get);
			merge(targetShared, "lib", lib);
		};
		scopes.forEach((sc) => {
			if (!this.shareScopeMap[sc]) this.shareScopeMap[sc] = {};
			if (!this.shareScopeMap[sc][pkgName]) this.shareScopeMap[sc][pkgName] = {};
			if (!this.shareScopeMap[sc][pkgName][version]) this.shareScopeMap[sc][pkgName][version] = {
				version,
				scope: [sc],
				...shareInfo,
				lib
			};
			const registeredShared = this.shareScopeMap[sc][pkgName][version];
			mergeAttrs(registeredShared);
			if (from && registeredShared.from !== from) registeredShared.from = from;
		});
	}
	_setGlobalShareScopeMap(hostOptions) {
		const globalShareScopeMap = getGlobalShareScope();
		const identifier = hostOptions.id || hostOptions.name;
		if (identifier && !globalShareScopeMap[identifier]) globalShareScopeMap[identifier] = this.shareScopeMap;
	}
};

//#region src/shared/disabled.ts
var DisabledSharedHandler = class {
	constructor() {
		this.shareScopeMap = {};
		this.hooks = new PluginSystem({ afterResolve: new AsyncWaterfallHook("afterResolve") });
	}
	registerShared() {
		return {
			newShareInfos: {},
			allShareInfos: {}
		};
	}
	loadShare() {
		throw new Error("Shared dependency loading is disabled by experiments.optimization.disableShared.");
	}
	loadShareSync() {
		throw new Error("Shared dependency loading is disabled by experiments.optimization.disableShared.");
	}
	initializeSharing() {
		return [];
	}
	initShareScopeMap(scopeName, shareScope) {
		this.shareScopeMap[scopeName] = shareScope;
	}
};

//#region src/remote/index.ts
var RemoteHandler = class {
	constructor(host) {
		this.hooks = new PluginSystem({
			beforeRegisterRemote: new SyncWaterfallHook("beforeRegisterRemote"),
			registerRemote: new SyncWaterfallHook("registerRemote"),
			beforeRequest: new AsyncWaterfallHook("beforeRequest"),
			afterMatchRemote: new AsyncHook("afterMatchRemote"),
			onLoad: new AsyncHook("onLoad"),
			afterLoadRemote: new AsyncHook("afterLoadRemote"),
			handlePreloadModule: new SyncHook("handlePreloadModule"),
			errorLoadRemote: new AsyncHook("errorLoadRemote"),
			beforePreloadRemote: new AsyncHook("beforePreloadRemote"),
			generatePreloadAssets: new AsyncHook("generatePreloadAssets"),
			afterPreloadRemote: new AsyncHook("afterPreloadRemote"),
			loadEntry: new AsyncHook()
		});
		this.host = host;
		this.idToRemoteMap = {};
	}
	formatAndRegisterRemote(globalOptions, userOptions) {
		return (userOptions.remotes || []).reduce((res, remote) => {
			this.registerRemote(remote, res, { force: false });
			return res;
		}, globalOptions.remotes);
	}
	setIdToRemoteMap(id, remoteMatchInfo) {
		const { remote, expose } = remoteMatchInfo;
		const { name, alias } = remote;
		this.idToRemoteMap[id] = {
			name: remote.name,
			expose
		};
		if (alias && id.startsWith(name)) {
			const idWithAlias = id.replace(name, alias);
			this.idToRemoteMap[idWithAlias] = {
				name: remote.name,
				expose
			};
			return;
		}
		if (alias && id.startsWith(alias)) {
			const idWithName = id.replace(alias, name);
			this.idToRemoteMap[idWithName] = {
				name: remote.name,
				expose
			};
		}
	}
	async loadRemote(id, options) {
		const { host } = this;
		const startMatchInfo = matchRemoteWithNameAndExpose(host.options.remotes, id);
		let completeRequestId = id;
		let completeExpose = startMatchInfo?.expose;
		let completeRemote = startMatchInfo ? getRemoteInfo(startMatchInfo.remote) : void 0;
		let afterLoadRemoteArgs;
		try {
			const { loadFactory = true } = options || { loadFactory: true };
			const { module, moduleOptions, remoteMatchInfo } = await this.getRemoteModuleAndOptions({ id });
			const { pkgNameOrAlias, remote, expose, id: idRes, remoteSnapshot } = remoteMatchInfo;
			completeRequestId = idRes;
			completeExpose = expose;
			completeRemote = getRemoteInfo(remote);
			const moduleOrFactory = await module.get(idRes, expose, options, remoteSnapshot);
			const moduleWrapper = await this.hooks.lifecycle.onLoad.emit({
				id: idRes,
				pkgNameOrAlias,
				expose,
				exposeModule: loadFactory ? moduleOrFactory : void 0,
				exposeModuleFactory: loadFactory ? void 0 : moduleOrFactory,
				remote,
				options: moduleOptions,
				moduleInstance: module,
				origin: host
			});
			this.setIdToRemoteMap(id, remoteMatchInfo);
			afterLoadRemoteArgs = {
				id: completeRequestId,
				expose: completeExpose,
				remote: completeRemote,
				options,
				origin: host
			};
			if (typeof moduleWrapper === "function") return moduleWrapper;
			return moduleOrFactory;
		} catch (error) {
			const { from = "runtime" } = options || { from: "runtime" };
			let failOver;
			try {
				failOver = await this.hooks.lifecycle.errorLoadRemote.emit({
					id,
					error,
					from,
					lifecycle: "onLoad",
					expose: completeExpose,
					remote: completeRemote,
					origin: host
				});
			} catch (hookError) {
				afterLoadRemoteArgs = {
					id: completeRequestId,
					expose: completeExpose,
					remote: completeRemote,
					options,
					error: hookError,
					origin: host
				};
				throw hookError;
			}
			if (!failOver) {
				afterLoadRemoteArgs = {
					id: completeRequestId,
					expose: completeExpose,
					remote: completeRemote,
					options,
					error,
					origin: host
				};
				throw error;
			}
			afterLoadRemoteArgs = {
				id: completeRequestId,
				expose: completeExpose,
				remote: completeRemote,
				options,
				error,
				origin: host,
				recovered: true
			};
			return failOver;
		} finally {
			if (afterLoadRemoteArgs) await this.hooks.lifecycle.afterLoadRemote.emit(afterLoadRemoteArgs);
		}
	}
	async preloadRemote(preloadOptions) {
		const { host } = this;
		const preloadResults = [];
		await this.hooks.lifecycle.beforePreloadRemote.emit({
			preloadOps: preloadOptions,
			options: host.options,
			origin: host
		});
		const preloadOps = formatPreloadArgs(host.options.remotes, preloadOptions);
		const createPreloadAssetOps = (ops) => {
			const { preloadConfig, remote } = ops;
			const exposes = preloadConfig.exposes || [];
			if (!exposes.length) return [{
				ops,
				id: `${remote.name}/*`
			}];
			return exposes.map((expose) => ({
				ops: {
					...ops,
					preloadConfig: {
						...preloadConfig,
						exposes: [expose]
					}
				},
				id: composeRemoteRequestId(remote.name, expose)
			}));
		};
		let preloadError;
		await Promise.all(preloadOps.flatMap(createPreloadAssetOps).map(async (assetOps) => {
			const { ops, id: preloadId } = assetOps;
			const { remote, preloadConfig } = ops;
			const remoteInfo = getRemoteInfo(remote);
			try {
				const { globalSnapshot, remoteSnapshot } = await host.snapshotHandler.loadRemoteSnapshotInfo({
					moduleInfo: remote,
					id: preloadId,
					initiator: "preloadRemote"
				});
				const assets = await this.hooks.lifecycle.generatePreloadAssets.emit({
					origin: host,
					preloadOptions: ops,
					remote,
					remoteInfo,
					globalSnapshot,
					remoteSnapshot
				});
				if (!assets) return;
				const results = await preloadAssets(remoteInfo, host, assets, true, {
					initiator: "preloadRemote",
					id: preloadId
				}, preloadConfig.recordPreloadedAssets);
				preloadResults.push({
					remote,
					remoteInfo,
					preloadConfig,
					id: preloadId,
					results
				});
			} catch (error) {
				preloadResults.push({
					remote,
					remoteInfo,
					preloadConfig,
					id: preloadId,
					results: [{
						url: remoteInfo.entry,
						status: "error",
						resourceType: /\.json(?:$|[?#])/i.test(remoteInfo.entry) ? "manifest" : "remoteEntry",
						initiator: "preloadRemote",
						id: preloadId,
						error
					}]
				});
			}
		}));
		const failedResults = preloadResults.flatMap((preloadResult) => preloadResult.results.filter((result) => result.status === "error" || result.status === "timeout"));
		if (failedResults.length > 0) {
			preloadError = /* @__PURE__ */ new Error(`preloadRemote failed to load ${failedResults.length} resource(s).`);
			Object.assign(preloadError, {
				results: preloadResults,
				failedResults
			});
		}
		await this.hooks.lifecycle.afterPreloadRemote.emit({
			preloadOps: preloadOptions,
			options: host.options,
			origin: host,
			results: preloadResults,
			error: preloadError
		});
		if (preloadError) throw preloadError;
	}
	registerRemotes(remotes, options) {
		const { host } = this;
		remotes.forEach((remote) => {
			this.registerRemote(remote, host.options.remotes, { force: options?.force });
		});
	}
	initRawContainer(name, url, container) {
		const { host } = this;
		const module = new Module$1({
			host,
			remoteInfo: getRemoteInfo({
				name,
				entry: url
			})
		});
		module.remoteEntryExports = container;
		host.moduleCache.set(name, module);
		return module;
	}
	async getRemoteModuleAndOptions(options) {
		const { host } = this;
		const { id } = options;
		let loadRemoteArgs;
		try {
			loadRemoteArgs = await this.hooks.lifecycle.beforeRequest.emit({
				id,
				options: host.options,
				origin: host
			});
		} catch (error) {
			loadRemoteArgs = await this.hooks.lifecycle.errorLoadRemote.emit({
				id,
				options: host.options,
				origin: host,
				from: "runtime",
				error,
				lifecycle: "beforeRequest"
			});
			if (!loadRemoteArgs) throw error;
		}
		const { id: idRes } = loadRemoteArgs;
		const remoteSplitInfo = matchRemoteWithNameAndExpose(host.options.remotes, idRes);
		if (!remoteSplitInfo) try {
			error(RUNTIME_004, runtimeDescMap, {
				hostName: host.options.name,
				requestId: idRes
			}, void 0, optionsToMFContext(host.options));
		} catch (matchError) {
			await this.hooks.lifecycle.afterMatchRemote.emit({
				id: idRes,
				options: host.options,
				error: matchError,
				origin: host
			});
			throw matchError;
		}
		const { remote: rawRemote } = remoteSplitInfo;
		const remoteInfo = getRemoteInfo(rawRemote);
		await this.hooks.lifecycle.afterMatchRemote.emit({
			id: idRes,
			...remoteSplitInfo,
			options: host.options,
			remoteInfo,
			origin: host
		});
		const matchInfo = await host.sharedHandler.hooks.lifecycle.afterResolve.emit({
			id: idRes,
			...remoteSplitInfo,
			options: host.options,
			origin: host,
			remoteInfo
		});
		const { remote, expose } = matchInfo;
		assert(remote && expose, `The 'beforeRequest' hook was executed, but it failed to return the correct 'remote' and 'expose' values while loading ${idRes}.`);
		let module = host.moduleCache.get(remote.name);
		const moduleOptions = {
			host,
			remoteInfo
		};
		if (!module) {
			module = new Module$1(moduleOptions);
			host.moduleCache.set(remote.name, module);
		}
		return {
			module,
			moduleOptions,
			remoteMatchInfo: matchInfo
		};
	}
	registerRemote(remote, targetRemotes, options) {
		const { host } = this;
		const normalizeRemote = () => {
			if (remote.alias) {
				const findEqual = targetRemotes.find((item) => remote.alias && (item.name.startsWith(remote.alias) || item.alias?.startsWith(remote.alias)));
				assert(!findEqual, `The alias ${remote.alias} of remote ${remote.name} is not allowed to be the prefix of ${findEqual && findEqual.name} name or alias`);
			}
			if ("entry" in remote) {
				if (typeof window !== "undefined" && !remote.entry.startsWith("http")) remote.entry = new URL(remote.entry, window.location.origin).href;
			}
			if (!remote.shareScope) remote.shareScope = DEFAULT_SCOPE;
			if (!remote.type) remote.type = DEFAULT_REMOTE_TYPE;
		};
		this.hooks.lifecycle.beforeRegisterRemote.emit({
			remote,
			origin: host
		});
		const registeredRemote = targetRemotes.find((item) => item.name === remote.name);
		if (!registeredRemote) {
			normalizeRemote();
			targetRemotes.push(remote);
			this.hooks.lifecycle.registerRemote.emit({
				remote,
				origin: host
			});
		} else {
			const messages = [`The remote "${remote.name}" is already registered.`, "Please note that overriding it may cause unexpected errors."];
			if (options?.force) {
				this.removeRemote(registeredRemote);
				normalizeRemote();
				targetRemotes.push(remote);
				this.hooks.lifecycle.registerRemote.emit({
					remote,
					origin: host
				});
				warn(messages.join(" "));
			}
		}
	}
	removeRemote(remote) {
		try {
			const { host } = this;
			const { name } = remote;
			const remoteIndex = host.options.remotes.findIndex((item) => item.name === name);
			if (remoteIndex !== -1) host.options.remotes.splice(remoteIndex, 1);
			const globalSnapshotKey = getInfoWithoutType(CurrentGlobal.__FEDERATION__.moduleInfo, getFMId(remote)).key;
			delete CurrentGlobal.__FEDERATION__.moduleInfo[globalSnapshotKey];
			if ("entry" in remote) {
				host.snapshotHandler.manifestCache.delete(remote.entry);
				delete Global.__FEDERATION__.__MANIFEST_LOADING__[remote.entry];
			}
			const { hostGlobalSnapshot } = getGlobalRemoteInfo(remote, host);
			if (hostGlobalSnapshot) {
				const remoteKey = hostGlobalSnapshot && "remotesInfo" in hostGlobalSnapshot && hostGlobalSnapshot.remotesInfo && getInfoWithoutType(hostGlobalSnapshot.remotesInfo, remote.name).key;
				if (remoteKey) delete hostGlobalSnapshot.remotesInfo[remoteKey];
			}
			const loadedModule = host.moduleCache.get(remote.name);
			if (loadedModule) {
				const remoteInfo = loadedModule.remoteInfo;
				const key = remoteInfo.entryGlobalName;
				if (CurrentGlobal[key]) if (Object.getOwnPropertyDescriptor(CurrentGlobal, key)?.configurable) delete CurrentGlobal[key];
				else CurrentGlobal[key] = void 0;
				const remoteEntryUniqueKey = getRemoteEntryUniqueKey(loadedModule.remoteInfo);
				if (globalLoading[remoteEntryUniqueKey]) delete globalLoading[remoteEntryUniqueKey];
				let remoteInsId = remoteInfo.buildVersion ? composeKeyWithSeparator(remoteInfo.name, remoteInfo.buildVersion) : remoteInfo.name;
				const remoteInsIndex = CurrentGlobal.__FEDERATION__.__INSTANCES__.findIndex((ins) => {
					if (remoteInfo.buildVersion) return ins.options.id === remoteInsId;
					else return ins.name === remoteInsId;
				});
				if (remoteInsIndex !== -1) {
					const remoteIns = CurrentGlobal.__FEDERATION__.__INSTANCES__[remoteInsIndex];
					remoteInsId = remoteIns.options.id || remoteInsId;
					const globalShareScopeMap = getGlobalShareScope();
					let isAllSharedNotUsed = true;
					const needDeleteKeys = [];
					Object.keys(globalShareScopeMap).forEach((instId) => {
						const shareScopeMap = globalShareScopeMap[instId];
						shareScopeMap && Object.keys(shareScopeMap).forEach((shareScope) => {
							const shareScopeVal = shareScopeMap[shareScope];
							shareScopeVal && Object.keys(shareScopeVal).forEach((shareName) => {
								const sharedPkgs = shareScopeVal[shareName];
								sharedPkgs && Object.keys(sharedPkgs).forEach((shareVersion) => {
									const shared = sharedPkgs[shareVersion];
									if (shared && typeof shared === "object" && shared.from === remoteInfo.name) if (shared.loaded || shared.loading) {
										shared.useIn = shared.useIn.filter((usedHostName) => usedHostName !== remoteInfo.name);
										if (shared.useIn.length) isAllSharedNotUsed = false;
										else needDeleteKeys.push([
											instId,
											shareScope,
											shareName,
											shareVersion
										]);
									} else needDeleteKeys.push([
										instId,
										shareScope,
										shareName,
										shareVersion
									]);
								});
							});
						});
					});
					if (isAllSharedNotUsed) {
						remoteIns.shareScopeMap = {};
						delete globalShareScopeMap[remoteInsId];
					}
					needDeleteKeys.forEach(([insId, shareScope, shareName, shareVersion]) => {
						delete globalShareScopeMap[insId]?.[shareScope]?.[shareName]?.[shareVersion];
					});
					CurrentGlobal.__FEDERATION__.__INSTANCES__.splice(remoteInsIndex, 1);
				}
				host.moduleCache.delete(remote.name);
			}
		} catch (err) {
			logger.error(`removeRemote failed: ${err instanceof Error ? err.message : String(err)}`);
		}
	}
};

//#region src/core.ts
const USE_SNAPSHOT = typeof FEDERATION_OPTIMIZE_NO_SNAPSHOT_PLUGIN === "boolean" ? !FEDERATION_OPTIMIZE_NO_SNAPSHOT_PLUGIN : true;
const USE_REMOTE = typeof FEDERATION_OPTIMIZE_NO_REMOTE === "boolean" ? !FEDERATION_OPTIMIZE_NO_REMOTE : true;
const USE_SHARED = typeof FEDERATION_OPTIMIZE_NO_SHARED === "boolean" ? !FEDERATION_OPTIMIZE_NO_SHARED : true;
var ModuleFederation = class {
	constructor(userOptions) {
		this.hooks = new PluginSystem({
			beforeInit: new SyncWaterfallHook("beforeInit"),
			init: new SyncHook(),
			beforeInitContainer: new AsyncWaterfallHook("beforeInitContainer"),
			initContainer: new AsyncWaterfallHook("initContainer")
		});
		this.version = "2.9.3";
		this.moduleCache = /* @__PURE__ */ new Map();
		this.loaderHook = new PluginSystem({
			getModuleInfo: new SyncHook(),
			createScript: new SyncHook(),
			createLink: new SyncHook(),
			fetch: new AsyncHook(),
			loadEntryError: new AsyncHook(),
			afterLoadEntry: new AsyncHook("afterLoadEntry"),
			beforeInitRemote: new AsyncHook("beforeInitRemote"),
			afterInitRemote: new AsyncHook("afterInitRemote"),
			beforeGetExpose: new AsyncHook("beforeGetExpose"),
			afterGetExpose: new AsyncHook("afterGetExpose"),
			beforeExecuteFactory: new AsyncHook("beforeExecuteFactory"),
			afterExecuteFactory: new AsyncHook("afterExecuteFactory"),
			getModuleFactory: new AsyncHook()
		});
		this.bridgeHook = new PluginSystem({
			beforeBridgeRender: new SyncHook(),
			afterBridgeRender: new SyncHook(),
			beforeBridgeDestroy: new SyncHook(),
			afterBridgeDestroy: new SyncHook(),
			afterBridgeRouteSync: new SyncHook()
		});
		const plugins = USE_REMOTE && USE_SNAPSHOT ? [snapshotPlugin(), generatePreloadAssetsPlugin()] : [];
		const defaultOptions = {
			id: getBuilderId(),
			name: userOptions.name,
			plugins,
			remotes: [],
			shared: {},
			inBrowser: isBrowserEnvValue
		};
		this.name = userOptions.name;
		this.options = defaultOptions;
		this.snapshotHandler = USE_REMOTE ? new SnapshotHandler(this) : new DisabledSnapshotHandler();
		this.sharedHandler = USE_SHARED ? new SharedHandler(this) : new DisabledSharedHandler();
		this.remoteHandler = USE_REMOTE ? new RemoteHandler(this) : new DisabledRemoteHandler();
		this.shareScopeMap = this.sharedHandler.shareScopeMap;
		this.registerPlugins([...defaultOptions.plugins, ...userOptions.plugins || []]);
		this.options = this.formatOptions(defaultOptions, userOptions);
	}
	initOptions(userOptions) {
		if (userOptions.name && userOptions.name !== this.options.name) error(getShortErrorMsg(RUNTIME_010, runtimeDescMap));
		this.registerPlugins(userOptions.plugins);
		const options = this.formatOptions(this.options, userOptions);
		this.options = options;
		return options;
	}
	async loadShare(pkgName, extraOptions) {
		return this.sharedHandler.loadShare(pkgName, extraOptions);
	}
	loadShareSync(pkgName, extraOptions) {
		return this.sharedHandler.loadShareSync(pkgName, extraOptions);
	}
	initializeSharing(shareScopeName = DEFAULT_SCOPE, extraOptions) {
		return this.sharedHandler.initializeSharing(shareScopeName, extraOptions);
	}
	initRawContainer(name, url, container) {
		return this.remoteHandler.initRawContainer(name, url, container);
	}
	async loadRemote(id, options) {
		return this.remoteHandler.loadRemote(id, options);
	}
	async preloadRemote(preloadOptions) {
		return this.remoteHandler.preloadRemote(preloadOptions);
	}
	initShareScopeMap(scopeName, shareScope, extraOptions = {}) {
		this.sharedHandler.initShareScopeMap(scopeName, shareScope, extraOptions);
	}
	formatOptions(globalOptions, userOptions) {
		const shared = USE_SHARED ? formatShareConfigs(globalOptions, userOptions).allShareInfos : {};
		const { userOptions: userOptionsRes, options: globalOptionsRes } = this.hooks.lifecycle.beforeInit.emit({
			origin: this,
			userOptions,
			options: globalOptions,
			shareInfo: shared
		});
		const remotes = this.remoteHandler.formatAndRegisterRemote(globalOptionsRes, userOptionsRes);
		const { allShareInfos } = this.sharedHandler.registerShared(globalOptionsRes, userOptionsRes);
		const plugins = [...globalOptionsRes.plugins];
		if (userOptionsRes.plugins) userOptionsRes.plugins.forEach((plugin) => {
			if (!plugins.includes(plugin)) plugins.push(plugin);
		});
		const optionsRes = {
			...globalOptions,
			...userOptions,
			plugins,
			remotes,
			shared: allShareInfos,
			id: userOptionsRes.id || globalOptions.id
		};
		this.hooks.lifecycle.init.emit({
			origin: this,
			options: optionsRes
		});
		return optionsRes;
	}
	registerPlugins(plugins) {
		this.options.plugins = registerPlugins(plugins, this);
	}
	registerRemotes(remotes, options) {
		return this.remoteHandler.registerRemotes(remotes, options);
	}
	registerShared(shared) {
		this.sharedHandler.registerShared(this.options, {
			...this.options,
			shared
		});
	}
};

//#region src/index.ts
const helpers = helpers_default;
typeof FEDERATION_OPTIMIZE_NO_REMOTE === "boolean" && FEDERATION_OPTIMIZE_NO_REMOTE ? UnavailableRemoteModule : Module$1;

export { CurrentGlobal as C, ModuleFederation as M, setGlobalFederationConstructor as a, getGlobalFederationConstructor as g, helpers as h, setGlobalFederationInstance as s };
