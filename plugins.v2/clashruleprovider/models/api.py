from typing import List

from pydantic import BaseModel, Field, RootModel
from simpleeval import simple_eval


class ClashApi(BaseModel):
    url: str
    secret: str


class Connectivity(BaseModel):
    clash_apis: List[ClashApi] = Field(default_factory=list)
    sub_links: List[str] = Field(default_factory=list)


class SubscriptionSetting(BaseModel):
    url: str
    enabled: bool


class DataUsage(BaseModel):
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0

    @property
    def header(self) -> str:
        return f'upload={self.upload}; download={self.download}; total={self.total}; expire={self.expire};'


class SubscriptionInfo(DataUsage):
    last_update: int = Field(default=0)
    proxy_num: int = Field(default=0)
    enabled: bool = True

    def update(self, setting: SubscriptionSetting):
        self.enabled = setting.enabled


class SubscriptionsInfo(RootModel[dict[str, SubscriptionInfo]]):
    root: dict[str, SubscriptionInfo] = Field(default_factory=dict)

    def update(self, urls: list[str]):
        if not urls:
            return

        self.root.clear()
        for url in urls:
            self.root[url] = self.root.get(url, SubscriptionInfo())

    def get(self, url: str) -> SubscriptionInfo:
        return self.root.get(url, SubscriptionInfo())

    def __setitem__(self, key: str, value: SubscriptionInfo):
        self.root[key] = value

    def set(self, setting: SubscriptionSetting):
        if setting.url in self.root:
            self.root[setting.url].update(setting)


class ConfigRequest(BaseModel):
    url: str
    client_host: str
    identifier: str | None = None
    user_agent : str | None = None

    def resolve(self, expr) -> bool:
        return bool(simple_eval(expr=expr, names=self.model_dump()))
