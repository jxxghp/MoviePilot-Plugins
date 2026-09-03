const isValidUrl = (urlString) => {
  if (!urlString) return false;
  try {
    const url = new URL(urlString);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (e) {
    return false;
  }
};
function isValidIP(ip) {
  const ipv4Regex = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
  const ipv6Regex = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(([0-9a-fA-F]{1,4}:){1,7}|:):([0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4})$/;
  return ipv4Regex.test(ip) || ipv6Regex.test(ip);
}
function validateIPs(ips) {
  if (ips.length === 0) {
    return `至少需要一个 IP 地址`;
  }
  for (const ip of ips) {
    if (!isValidIP(ip)) {
      return `无效的 IP 地址: ${ip}`;
    }
  }
  return true;
}
function getUsageColor(percentage) {
  return percentage > 90 ? "error" : percentage > 70 ? "warning" : "success";
}
function getBehaviorColor(action) {
  const colors = {
    classical: "success",
    domain: "error",
    ipcidr: "error"
  };
  return colors[action] || "primary";
}
function getFormatColor(action) {
  const colors = {
    yaml: "success",
    text: "warning",
    mrs: "info"
  };
  return colors[action] || "secondary";
}
function getRuleTypeColor(type) {
  const colors = {
    DOMAIN: "primary",
    "DOMAIN-SUFFIX": "primary",
    "DOMAIN-KEYWORD": "primary",
    "DOMAIN-REGEX": "primary",
    "DOMAIN-WILDCARD": "primary",
    GEOSITE: "info",
    GEOIP: "info",
    "IP-CIDR": "warning",
    "IP-CIDR6": "warning",
    "IP-SUFFIX": "warning",
    "IP-ASN": "warning",
    "SRC-GEOIP": "info",
    "SRC-IP-ASN": "warning",
    "SRC-IP-CIDR": "warning",
    "SRC-IP-SUFFIX": "warning",
    "DST-PORT": "success",
    "SRC-PORT": "success",
    "IN-PORT": "success",
    "IN-TYPE": "success",
    "IN-USER": "success",
    "IN-NAME": "success",
    "PROCESS-PATH": "error",
    "PROCESS-PATH-REGEX": "error",
    "PROCESS-NAME": "error",
    "PROCESS-NAME-REGEX": "error",
    UID: "secondary",
    NETWORK: "secondary",
    DSCP: "secondary",
    "RULE-SET": "deep-purple",
    AND: "deep-orange",
    OR: "deep-orange",
    NOT: "deep-orange",
    "SUB-RULE": "deep-orange",
    MATCH: "teal"
  };
  return colors[type] || "grey";
}
function getSourceColor(source) {
  const colors = {
    Auto: "success",
    Manual: "info"
  };
  return colors[source] || "primary";
}
function getActionColor(action) {
  const colors = {
    DIRECT: "success",
    REJECT: "error",
    "REJECT-DROP": "error",
    PASS: "warning",
    COMPATIBLE: "info"
  };
  return colors[action] || "primary";
}
function getProxyGroupTypeColor(action) {
  const colors = {
    "url-test": "success",
    fallback: "error",
    "load-balance": "primary",
    select: "info"
  };
  return colors[action] || "warning";
}
function getProxyColor(action) {
  const colors = {
    ss: "success",
    ssr: "success",
    trojan: "error",
    vmess: "primary",
    vless: "primary",
    hysteria: "info",
    hysteria2: "info",
    anytls: "warning"
  };
  return colors[action] || "secondary";
}
function getBoolColor(value) {
  if (value) {
    return "primary";
  }
  return "success";
}
function isSystemRule(rule) {
  return rule.meta.source?.startsWith("Auto");
}
function isManual(source) {
  return source === "Manual";
}
function isInvalid(source) {
  return source === "Invalid";
}
function isRegion(source) {
  return source === "Auto";
}
function pageTitle(itemPerPageValue) {
  if (itemPerPageValue < 0) {
    return "♾️";
  }
  return `${itemPerPageValue}`;
}
function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}
function formatTimestamp(timestamp) {
  if (!timestamp) return "N/A";
  const date = new Date(timestamp * 1e3);
  return date.toLocaleDateString("zh-CN");
}
function timestampToDate(timestamp) {
  if (!timestamp) return "N/A";
  const date = new Date(timestamp * 1e3);
  return date.toLocaleString("zh-CN", {
    // 'en-GB' 表示使用英国格式（YYYY-MM-DD HH:mm:ss）
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
    // 24小时制
  });
}
function getExpireColor(timestamp) {
  if (!timestamp) return "grey";
  const secondsLeft = timestamp - Math.floor(Date.now() / 1e3);
  const daysLeft = secondsLeft / 86400;
  return daysLeft < 7 ? "error" : daysLeft < 30 ? "warning" : "success";
}
function extractDomain(url) {
  try {
    const hostname = new URL(url).hostname;
    const parts = hostname.split(".");
    if (/^\d+\.\d+\.\d+\.\d+$/.test(hostname) || hostname.includes(":")) {
      return hostname;
    }
    if (parts.length <= 2) {
      return hostname;
    }
    return parts.slice(-2).join(".");
  } catch {
    return url;
  }
}
function getUsedPercentageFloor(data) {
  const used = data.upload + data.download;
  return data.total > 0 ? Math.floor(used / data.total * 100) : 0;
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

export { _export_sfc as _, getActionColor as a, isManual as b, isRegion as c, getSourceColor as d, getProxyGroupTypeColor as e, isValidUrl as f, getRuleTypeColor as g, isInvalid as h, isSystemRule as i, getProxyColor as j, extractDomain as k, formatTimestamp as l, getExpireColor as m, formatBytes as n, getUsageColor as o, pageTitle as p, getUsedPercentageFloor as q, getFormatColor as r, getBehaviorColor as s, timestampToDate as t, getBoolColor as u, validateIPs as v };
