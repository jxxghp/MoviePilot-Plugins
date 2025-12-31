from pydantic import Field, RootModel, BaseModel

from .metadata import Metadata


class HostData(BaseModel):
    domain: str
    value: list[str]
    using_cloudflare: bool
    meta: Metadata = Field(default_factory=Metadata)


class Hosts(RootModel[list[HostData]]):
    root: list[HostData] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.root)

    def update(self, domain: str, data: HostData):
        self.root = [host for host in self.root if host.domain != domain]
        self.root.append(data)

    def delete(self, domain: str):
        self.root = [host for host in self.root if host.domain != domain]

    def to_dict(self, cloudflare: list[str]) -> dict[str, list[str]]:
        hosts = {}
        for host in self.root:
            if host.using_cloudflare:
                hosts[host.domain] = cloudflare
            else:
                hosts[host.domain] = host.value
        return hosts
