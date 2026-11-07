from dataclasses import dataclass


from app.sdk.media import MediaInfo, TorrentInfo, MetaVideo


@dataclass
class Matchinfo:
    """
      比赛相关信息
    """
    torrentinfo: TorrentInfo = None
    mediainfo: MediaInfo = None
    metainfo: MetaVideo = None
    language: str = None
    pix: int = 0
