import hashlib
from pathlib import Path
from typing import Self

import requests
from bencode import decode, encode


class CSSiteConfig(object):
    """
    站点辅种配置类
    """

    def __init__(self, site_name: str, site_url: str, site_passkey: str) -> None:
        self.name = site_name
        self.url = site_url.removesuffix("/")
        self.passkey = site_passkey

    def get_api_url(self):
        if self.name == "憨憨":
            return f"{self.url}/npapi/pieces-hash"
        return f"{self.url}/api/pieces-hash"

    def get_torrent_url(self, torrent_id: str):
        return f"{self.url}/download.php?id={torrent_id}&passkey={self.passkey}"


class TorInfo:

    def __init__(
        self,
        site_name: str = None,
        torrent_path: str = None,
        file_path: str = None,
        info_hash: str = None,
        pieces_hash: str = None,
        torrent_id: str = None,
    ) -> None:
        self.site_name = site_name
        self.torrent_path = torrent_path
        self.file_path = file_path
        self.info_hash = info_hash
        self.pieces_hash = pieces_hash
        self.torrent_id = torrent_id
        self.torrent_announce = None

    @staticmethod
    def local(torrent_path: str, info_hash: str, pieces_hash: str) -> Self:

        return TorInfo(
            torrent_path=torrent_path, info_hash=info_hash, pieces_hash=pieces_hash
        )

    @staticmethod
    def remote(site_name: str, pieces_hash: str, torrent_id: str) -> Self:
        return TorInfo(
            site_name=site_name, pieces_hash=pieces_hash, torrent_id=torrent_id
        )

    @staticmethod
    def from_data(data: bytes) -> tuple[Self, str]:
        try:
            torrent = decode(data)
            info = torrent["info"]
            pieces = info["pieces"]
            info_hash = hashlib.sha1(encode(info)).hexdigest()
            pieces_hash = hashlib.sha1(pieces).hexdigest()
            local_tor = TorInfo(info_hash=info_hash, pieces_hash=pieces_hash)
            #从种子中获取 announce, qb可能存在获取不到的情况，会存在于fastresume文件中
            if "announce" in torrent:
                local_tor.torrent_announce  = torrent["announce"]
            return local_tor, None
        except Exception as err:
            return None, err

    def get_name_id_tag(self):
        return f"{self.site_name}:{self.torrent_id}"

    def get_name_pieces_tag(self):
        return f"{self.site_name}:{self.pieces_hash}"

class CrossSeedHelper(object):
    _version = "0.2.0"

    def get_local_torrent_info(self, torrent_path: Path | str) -> tuple[TorInfo, str]:
        try:
            torrent_data = None
            if isinstance(torrent_path, Path):
                torrent_data = torrent_path.read_bytes()
            else:
                with open(torrent_path, "rb") as f:
                    torrent_data = f.read()
            local_tor, err = TorInfo.from_data(torrent_data)
            if not local_tor:
                return None, err
            local_tor.torrent_path = str(torrent_path)
            return local_tor, ""
        except Exception as err:
            return None, err

    def get_target_torrent(
        self, site: CSSiteConfig, pieces_hash_set: list[str]
    ) -> list[TorInfo]:
        """
        返回pieces_hash对应的种子信息，包括站点id,pieces_hash,种子id
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CrossSeedHelper",
        }
        data = {"passkey": site.passkey, "pieces_hash": pieces_hash_set}
        try:
            response = requests.post(
                site.get_api_url(), headers=headers, json=data, timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return None, f"站点{site.name}请求失败：{e}"
        rsp_body = response.json()

        remote_torrent_infos = []
        if isinstance(rsp_body["data"], dict):
            for pieces_hash, torrent_id in rsp_body["data"].items():
                remote_torrent_infos.append(
                    TorInfo.remote(site.name, pieces_hash, torrent_id)
                )
        return remote_torrent_infos, None
