#!/bin/bash

set -euo pipefail

DOWNLOAD_BASE="https://www.makemkv.com/download"
LINUX_PAGE="https://forum.makemkv.com/forum/viewtopic.php?f=3&t=224"
DOWNLOAD_PAGE="https://www.makemkv.com/download/"
BUILD_DIR="/tmp/makemkv_build"
BUILD_PACKAGES=(
  wget
  ca-certificates
  pkg-config
  libc6-dev
  libssl-dev
  libexpat1-dev
  libavcodec-dev
  zlib1g-dev
  build-essential
)
PACKAGES_INSTALLED_BEFORE=()

download_url() {
  local package="$1"
  local version="$2"
  echo "${DOWNLOAD_BASE}/makemkv-${package}-${version}.tar.gz"
}

package_exists() {
  local version="$1"
  wget -q --spider "$(download_url oss "${version}")" \
    && wget -q --spider "$(download_url bin "${version}")"
}

extract_versions() {
  grep -Eo 'makemkv-(oss|bin)-[0-9]+(\.[0-9]+)+\.tar\.gz|MakeMKV v?[0-9]+(\.[0-9]+)+' \
    | grep -Eo '[0-9]+(\.[0-9]+)+' \
    | sort -Vr \
    | uniq
}

resolve_version() {
  if [ -n "${MAKEMKV_VERSION:-}" ]; then
    if ! package_exists "${MAKEMKV_VERSION}"; then
      echo "指定版本不可下载: ${MAKEMKV_VERSION}" >&2
      exit 1
    fi
    echo "${MAKEMKV_VERSION}"
    return
  fi

  local versions version
  versions="$(
    {
      wget -qO- "${LINUX_PAGE}" || true
      wget -qO- "${DOWNLOAD_PAGE}" || true
    } | extract_versions || true
  )"

  for version in ${versions}; do
    if package_exists "${version}"; then
      echo "${version}"
      return
    fi
  done

  echo "无法从 MakeMKV 官网解析到可下载版本" >&2
  exit 1
}

cleanup() {
  cd /
  rm -rf "${BUILD_DIR}"
}

record_installed_packages() {
  local package
  for package in "${BUILD_PACKAGES[@]}"; do
    if dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -q "install ok installed"; then
      PACKAGES_INSTALLED_BEFORE+=("${package}")
    fi
  done
}

was_installed_before() {
  local package="$1"
  local existing
  for existing in "${PACKAGES_INSTALLED_BEFORE[@]}"; do
    if [ "${existing}" = "${package}" ]; then
      return 0
    fi
  done
  return 1
}

remove_new_build_packages() {
  local package
  local packages_to_remove=()
  for package in "${BUILD_PACKAGES[@]}"; do
    if ! was_installed_before "${package}"; then
      packages_to_remove+=("${package}")
    fi
  done
  if [ "${#packages_to_remove[@]}" -gt 0 ]; then
    apt-get remove -y "${packages_to_remove[@]}"
  fi
}

trap cleanup EXIT

echo "=========================================="
echo "准备安装 MakeMKV"
echo "=========================================="

apt-get update
record_installed_packages
apt-get install -y --no-install-recommends "${BUILD_PACKAGES[@]}"

MAKEMKV_VERSION="$(resolve_version)"
OSS_URL="$(download_url oss "${MAKEMKV_VERSION}")"
BIN_URL="$(download_url bin "${MAKEMKV_VERSION}")"

echo "=========================================="
echo "开始编译安装 MakeMKV ${MAKEMKV_VERSION} (无 GUI)"
echo "=========================================="

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

wget -O "makemkv-oss-${MAKEMKV_VERSION}.tar.gz" "${OSS_URL}"
wget -O "makemkv-bin-${MAKEMKV_VERSION}.tar.gz" "${BIN_URL}"

tar -zxf "makemkv-oss-${MAKEMKV_VERSION}.tar.gz"
tar -zxf "makemkv-bin-${MAKEMKV_VERSION}.tar.gz"

echo "[1/3] 编译开源核心 (OSS)..."
cd "makemkv-oss-${MAKEMKV_VERSION}"
./configure --disable-gui
make -j"$(nproc)"
make install

echo "[2/3] 编译闭源核心 (BIN)..."
cd "../makemkv-bin-${MAKEMKV_VERSION}"
mkdir -p tmp
touch tmp/eula_accepted
make
make install

echo "[3/3] 清理编译目录和顶层构建包..."
cleanup
remove_new_build_packages
apt-get clean

echo "=========================================="
echo "安装完成，测试运行 makemkvcon --info"
echo "=========================================="
makemkvcon --info
