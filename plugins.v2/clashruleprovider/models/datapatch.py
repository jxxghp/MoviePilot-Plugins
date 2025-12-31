from pydantic import BaseModel, Field, RootModel


class PatchItem(BaseModel):
    lifecycle: int = Field(default=3)
    patch: str


class DataPatch(RootModel[dict[str, PatchItem]]):
    """DataPatch model for storing patch items."""
    root: dict[str, PatchItem] = Field(default_factory=dict, description="Dictionary of patch items.")

    def update_patch(self, alive_keys: list[str] | set[str], lifespan: int = 3):
        outdated_keys = []
        for key in list(self.root.keys()):
            if key not in alive_keys:
                self.root[key].lifecycle -= 1
                if self.root[key].lifecycle == 0:
                    outdated_keys.append(key)
            else:
                self.root[key].lifecycle = lifespan
        for key in outdated_keys:
            del self.root[key]

    def __setitem__(self, key: str, value: PatchItem):
        self.root[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def __getitem__(self, key: str) -> PatchItem:
        return self.root[key]
